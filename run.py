import asyncio
import json
import logging
import os
import shutil
import sqlite3
import sys
from datetime import datetime
from math import ceil
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from organizer.ai_clients import AIClientError, create_ai_client
from organizer.classification import (
    add_chat_assignment,
    build_categorization_from_memory_csv,
    build_categorization_from_review_csv,
    build_folder_rules_summary_lines,
    build_manual_prompt,
    build_summary_lines,
    compute_assigned_chat_ids,
    compute_unassigned_chats,
    create_manual_draft_template,
    export_classification_memory_csv,
    export_classification_review_csv,
    filter_classification_folders,
    merge_categorization_results,
    normalize_groups_data,
    print_detailed_classification_guidance,
    sync_folder_rules,
    validate_reference_integrity,
)
from organizer.cli_flow import (
    print_cache_strategy_hint,
    print_clear_strategy_hint,
    print_draft_edit_hint,
    print_file_review_hint,
    print_folder_picker,
    print_folder_rules_hint,
    print_folder_rules_summary,
    print_folder_summary,
    print_header,
    print_manual_fallback_hint,
    print_startup_overview,
    print_step,
    print_target_mode_hint,
    print_unassigned_hint,
    prompt_choice,
    prompt_text,
    prompt_yes_no,
    wait_for_enter,
)
from organizer.config import ConfigError, ensure_runtime_dirs, load_config
from organizer.telegram_ops import (
    clear_existing_folders,
    collect_chats_for_ai,
    collect_dialog_map,
    create_client_with_retry,
    ensure_session_exists,
    get_existing_folders,
    load_chats_info,
    save_chats_info,
    save_folders_info,
    save_groups_data,
    save_json_file,
    setup_logging,
    update_folders_with_categorization,
    validate_groups_json,
)


def _runtime_files(config):
    data_dir = config.paths.data_dir
    return {
        "draft": data_dir / "groups.draft.json",
        "final": data_dir / "groups.json",
        "chats": data_dir / "chats_info.json",
        "folders": data_dir / "folders_info.json",
        "folder_rules": data_dir / "folder_rules.json",
        "memory": data_dir / "classification_memory.csv",
        "review_csv": data_dir / "classification_review.csv",
        "log": config.paths.logs_dir / "run.log",
    }


def _is_database_locked_error(exc: Exception) -> bool:
    return "database is locked" in str(exc).lower()


def _pid_is_running(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _read_session_run_lock(lock_file: Path) -> dict:
    try:
        with lock_file.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _acquire_session_run_lock(session_name: str, sessions_dir: Path) -> Path:
    sessions_dir.mkdir(parents=True, exist_ok=True)
    lock_file = sessions_dir / f"{session_name}.run.lock"
    payload = {
        "pid": os.getpid(),
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "session_name": session_name,
    }

    for _ in range(2):
        try:
            fd = os.open(str(lock_file), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            existing = _read_session_run_lock(lock_file)
            pid = existing.get("pid")
            if isinstance(pid, int) and _pid_is_running(pid):
                created_at = existing.get("created_at", "未知时间")
                raise RuntimeError(
                    "当前 session 正在被另一个整理流程使用。\n"
                    f"- lock: {lock_file}\n"
                    f"- pid: {pid}\n"
                    f"- started: {created_at}\n"
                    "请先结束另一个 python run.py / create_session.py 进程，再重新运行。"
                )
            logging.warning("Removing stale session run lock: %s", lock_file)
            try:
                lock_file.unlink()
            except FileNotFoundError:
                pass
            continue

        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
        return lock_file

    raise RuntimeError(f"无法创建 session 运行锁: {lock_file}")


def _release_session_run_lock(lock_file: Path | None) -> None:
    if lock_file is None:
        return
    existing = _read_session_run_lock(lock_file)
    if existing.get("pid") != os.getpid():
        return
    try:
        lock_file.unlink()
    except FileNotFoundError:
        pass
    except Exception as exc:
        logging.warning("Failed to release session run lock %s: %s", lock_file, exc)


def _print_session_database_locked_message(session_file: Path) -> None:
    print("\nTelegram session 数据库被锁定，已停止本次运行。")
    print(f"- session: {session_file}")
    print("- 常见原因：另一个 python run.py / create_session.py 正在使用同一个 session，或上一次运行刚异常退出。")
    print("- 处理方式：关闭另一个终端里的运行进程，等待几秒后重试。")
    print("- 不建议删除 .session 文件；删除后需要重新登录 Telegram。")


async def _start_client_or_report_locked(client, session_file: Path) -> bool:
    try:
        await client.start()
        return True
    except sqlite3.OperationalError as exc:
        if not _is_database_locked_error(exc):
            raise
        logging.error("Telegram session database is locked during start: %s", exc)
        _print_session_database_locked_message(session_file)
        return False


async def _safe_disconnect_client(client) -> None:
    if client is None:
        return
    try:
        await client.disconnect()
    except sqlite3.OperationalError as exc:
        if _is_database_locked_error(exc):
            logging.warning("Skip Telegram disconnect state save because session database is locked: %s", exc)
            return
        raise
    except Exception as exc:
        logging.warning("Telegram disconnect failed: %s", exc)


def _migrate_legacy_files(config, files: dict[str, Path]) -> list[str]:
    moved = []
    mapping = {
        PROJECT_ROOT / "chats_info.json": files["chats"],
        PROJECT_ROOT / "folders_info.json": files["folders"],
        PROJECT_ROOT / "folder_rules.json": files["folder_rules"],
        PROJECT_ROOT / "classification_memory.csv": files["memory"],
        PROJECT_ROOT / "groups.draft.json": files["draft"],
        PROJECT_ROOT / "groups.json": files["final"],
        PROJECT_ROOT / "classification_review.csv": files["review_csv"],
        PROJECT_ROOT / "run.log": files["log"],
        PROJECT_ROOT / f"{config.telegram.session_name}.session": config.paths.sessions_dir / f"{config.telegram.session_name}.session",
        PROJECT_ROOT / f"{config.telegram.session_name}.session-journal": config.paths.sessions_dir
        / f"{config.telegram.session_name}.session-journal",
    }
    for source, target in mapping.items():
        if source.exists() and not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(target))
            moved.append(f"{source.name} -> {target}")
    return moved


def _build_chat_lookup(chats_for_ai: list[dict]) -> dict[int, dict]:
    return {int(chat["chat_id"]): chat for chat in chats_for_ai if chat.get("chat_id") is not None}


def _cache_has_recent_messages(chats_for_ai: list[dict]) -> bool:
    for chat in chats_for_ai:
        if not isinstance(chat, dict):
            return False
        if "recent_messages" not in chat or "recent_messages_text" not in chat:
            return False
    return True


def _print_draft_summary(categorized_data: dict, chats_for_ai: list[dict]) -> None:
    chat_lookup = _build_chat_lookup(chats_for_ai)
    lines, total = build_summary_lines(categorized_data, chat_lookup)
    unassigned = compute_unassigned_chats(chats_for_ai, categorized_data)

    print("\n草稿分类摘要：")
    if lines:
        for line in lines:
            print(line)
    else:
        print("- 当前草稿没有任何分类项")
    print(f"- 拟分类聊天总数: {total}")
    print(f"- 未分类聊天数: {len(unassigned)}")


def _suggest_folder_id(chat: dict, folders: list[dict]) -> int | None:
    text = (
        f"{chat.get('title', '')} "
        f"{chat.get('description', '')} "
        f"{chat.get('recent_messages_text', '')} "
        f"{chat.get('last_message', '')}"
    ).lower()
    best_id = None
    best_score = 0
    for folder in folders:
        tokens = [token for token in folder["title"].lower().split() if token]
        score = sum(1 for token in tokens if token in text)
        if score > best_score:
            best_score = score
            best_id = int(folder["id"])
    return best_id if best_score > 0 else None


async def _classify_with_ai_in_batches(
    ai_client,
    chats_for_ai: list[dict],
    folders: list[dict],
    batch_size: int,
    concurrency: int = 1,
    folder_rules: dict | None = None,
) -> dict:
    total_batches = max(1, ceil(len(chats_for_ai) / batch_size))
    batches = []
    for index in range(total_batches):
        start = index * batch_size
        end = start + batch_size
        batch = chats_for_ai[start:end]
        batches.append((index, batch))

    effective_concurrency = max(1, min(concurrency, total_batches))
    print(f"- AI 分类批次总数: {total_batches}，并发数: {effective_concurrency}")
    semaphore = asyncio.Semaphore(effective_concurrency)

    async def classify_one(index: int, batch: list[dict]) -> tuple[int, dict]:
        async with semaphore:
            print(f"- 开始 AI 分类批次 {index + 1}/{total_batches}，本批 {len(batch)} 条聊天")
            batch_result = await ai_client.classify(batch, folders, folder_rules=folder_rules)
            print(f"- 完成 AI 分类批次 {index + 1}/{total_batches}")
            return index, batch_result

    completed = await asyncio.gather(*(classify_one(index, batch) for index, batch in batches))
    results = [result for _, result in sorted(completed, key=lambda item: item[0])]

    folder_lookup = {folder["id"]: folder["title"] for folder in folders}
    return merge_categorization_results(results, folder_lookup)


def _load_json_with_error(filename: str | Path) -> tuple[dict | None, str | None]:
    path = Path(filename)
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f), None
    except FileNotFoundError:
        return None, f"文件不存在: {path}"
    except json.JSONDecodeError as exc:
        return None, f"JSON 解析失败: {exc}"
    except Exception as exc:  # pragma: no cover - defensive
        return None, f"读取文件失败: {exc}"


def _file_mtime_ns(path: Path) -> int | None:
    try:
        return path.stat().st_mtime_ns
    except FileNotFoundError:
        return None


async def _prepare_folder_rules(rules_file: Path, folders: list[dict]) -> dict:
    existing_rules, load_error = _load_json_with_error(rules_file)
    if load_error and rules_file.exists():
        print(f"文件夹说明读取失败，将生成新模板: {load_error}")

    rules_data = sync_folder_rules(folders, existing_rules)
    save_json_file(rules_file, rules_data)

    while True:
        lines, missing_count = build_folder_rules_summary_lines(rules_data, folders)
        print_folder_rules_hint(str(rules_file), missing_count)
        action = await prompt_choice(
            "文件夹说明 [Enter=继续 / e=编辑后继续 / s=查看摘要]: ",
            allowed={"c", "e", "s"},
            default="c",
        )
        if action == "s":
            print_folder_rules_summary(lines)
            continue
        if action == "e":
            await wait_for_enter(f"请编辑 {rules_file}，完成后返回终端")
            reloaded, reload_error = _load_json_with_error(rules_file)
            if reload_error:
                print(f"文件夹说明读取失败: {reload_error}")
                continue
            rules_data = sync_folder_rules(folders, reloaded)
            save_json_file(rules_file, rules_data)
            lines, missing_count = build_folder_rules_summary_lines(rules_data, folders)
            print_folder_rules_summary(lines)
            return rules_data
        return rules_data


def _load_continue_draft(files: dict[str, Path]) -> tuple[dict | None, str | None]:
    for key in ("draft", "final"):
        path = files[key]
        data, error = _load_json_with_error(path)
        if data is None:
            continue
        try:
            return normalize_groups_data(data), str(path)
        except ValueError as exc:
            logging.warning("Continue draft invalid: %s (%s)", path, exc)
            if error:
                logging.warning("Continue draft load error: %s", error)
    return None, None


async def _apply_review_files(
    files: dict[str, Path],
    folders: list[dict],
    chats_for_ai: list[dict],
    draft_mtime_before: int | None,
    csv_mtime_before: int | None,
    valid_folder_ids: set[int],
    valid_chat_ids: set[int],
) -> dict:
    draft_changed = _file_mtime_ns(files["draft"]) != draft_mtime_before
    csv_changed = _file_mtime_ns(files["review_csv"]) != csv_mtime_before

    if csv_changed:
        try:
            csv_based_data = build_categorization_from_review_csv(
                csv_file=files["review_csv"],
                folders=folders,
                chats_for_ai=chats_for_ai,
            )
            save_json_file(files["draft"], csv_based_data)
            print("检测到审核 CSV 已修改，已根据 CSV 重建草稿 JSON。")
        except ValueError as exc:
            print(f"CSV 重建草稿失败，将继续校验 JSON 草稿: {exc}")
    elif draft_changed:
        print("检测到 JSON 草稿已修改，将校验 JSON 草稿。")
    else:
        print("未检测到审核文件修改，将使用当前草稿继续。")

    return await _validate_draft_loop(files["draft"], valid_folder_ids, valid_chat_ids)


def _print_execution_preview(categorized_data: dict, chats_for_ai: list[dict], folders: list[dict]) -> None:
    folder_lookup = {int(folder["id"]): folder for folder in folders}
    chat_lookup = _build_chat_lookup(chats_for_ai)
    total_targets = 0

    print("\n执行前预览：")
    for folder_item in categorized_data.get("categorized", []):
        folder_id = int(folder_item.get("folder_id"))
        folder = folder_lookup.get(folder_id, {})
        existing_count = len(folder.get("existing_peers", []))
        chats = folder_item.get("chats", [])
        total_targets += len(chats)
        examples = []
        for chat_item in chats[:3]:
            chat = chat_lookup.get(int(chat_item.get("chat_id")), {})
            examples.append(chat.get("title") or str(chat_item.get("chat_id")))
        example_text = f"；示例: {', '.join(examples)}" if examples else ""
        print(f"- {folder_item.get('folder_title', folder.get('title', 'Unknown'))}: 当前 {existing_count} 个，建议添加 {len(chats)} 个{example_text}")

    unassigned = compute_unassigned_chats(chats_for_ai, categorized_data)
    print(f"- 建议写入目标总数: {total_targets}")
    print(f"- 保持未分类: {len(unassigned)}")


def _print_clear_report(report: dict) -> None:
    print("\n清空结果：")
    print(f"- 已清空文件夹: {report.get('cleared', 0)}")
    print(f"- 跳过文件夹: {report.get('skipped', 0)}")
    failed = report.get("failed", [])
    if failed:
        print(f"- 清空失败: {len(failed)}")
        for item in failed[:5]:
            print(f"  - {item.get('folder_title')} ({item.get('folder_id')}): {item.get('error')}")


def _print_update_report(report: dict) -> None:
    print("\n写入结果：")
    print(f"- 成功更新文件夹: {report.get('folders_updated', 0)}")
    print(f"- 新增聊天: {report.get('chats_added', 0)}")
    print(f"- 跳过文件夹: {report.get('folders_skipped', 0)}")
    missing_chats = report.get("missing_chats", [])
    failed_folders = report.get("failed_folders", [])
    if missing_chats:
        print(f"- 未找到或无效聊天: {len(missing_chats)}")
        for item in missing_chats[:5]:
            print(f"  - chat_id={item.get('chat_id')}: {item.get('reason')}")
    if failed_folders:
        print(f"- 写入失败文件夹: {len(failed_folders)}")
        for item in failed_folders[:5]:
            print(f"  - {item.get('folder_title')} ({item.get('folder_id')}): {item.get('error')}")


async def _validate_draft_loop(draft_file: Path, valid_folder_ids: set[int], valid_chat_ids: set[int]) -> dict:
    while True:
        data, load_error = _load_json_with_error(draft_file)
        if load_error:
            print(f"草稿读取失败: {load_error}")
        else:
            try:
                normalized = normalize_groups_data(data)
            except ValueError as exc:
                print(f"草稿结构错误: {exc}")
                normalized = None

            if normalized:
                is_valid, error_msg = validate_groups_json(normalized)
                if not is_valid:
                    print(f"草稿格式错误: {error_msg}")
                else:
                    integrity_errors = validate_reference_integrity(normalized, valid_folder_ids, valid_chat_ids)
                    if not integrity_errors:
                        return normalized
                    print("草稿引用错误：")
                    for err in integrity_errors:
                        print(f"- {err}")

        keep_edit = await prompt_yes_no("是否继续编辑草稿并重试校验？", default=True)
        if keep_edit is not True:
            raise RuntimeError("你已取消流程。")
        await wait_for_enter(f"请编辑 {draft_file} 修正问题")


async def _review_unassigned_chats(categorized_data: dict, unassigned_chats: list[dict], folders: list[dict]) -> dict:
    if not unassigned_chats:
        print("未分类复核：无未分类聊天。")
        return categorized_data

    folder_lookup = {int(folder["id"]): folder["title"] for folder in folders}
    print_unassigned_hint()
    print_folder_picker(folders)
    print(f"需要复核的未分类聊天数: {len(unassigned_chats)}")

    index = 0
    last_folder_id: int | None = None
    while index < len(unassigned_chats):
        chat = unassigned_chats[index]
        chat_id = int(chat["chat_id"])
        title = chat.get("title", "未知")
        chat_type = chat.get("type", "UNKNOWN")
        description = chat.get("description") or chat.get("recent_messages_text") or chat.get("last_message") or ""
        suggested_folder = _suggest_folder_id(chat, folders)

        print("\n" + "-" * 88)
        print(f"[{index + 1}/{len(unassigned_chats)}] chat_id={chat_id} | {title} | {chat_type}")
        if description:
            print(f"摘要: {description[:160]}")
        if suggested_folder is not None:
            print(f"建议归类: {suggested_folder} ({folder_lookup[suggested_folder]})")

        action = await prompt_choice("选择操作 [i/m/l/q]: ", allowed={"i", "m", "l", "q"}, default="i")
        if action == "q":
            print("已结束未分类复核，剩余聊天保持未分类。")
            break
        if action == "l":
            print_folder_picker(folders)
            continue
        if action == "i":
            index += 1
            continue

        while True:
            hint = f"输入 folder_id（l 列表 / c 取消，回车使用上次 {last_folder_id or '无'}）: "
            raw_folder_id = await prompt_text(hint)
            if raw_folder_id is None:
                continue
            text = raw_folder_id.strip().lower()
            if text == "":
                if last_folder_id is None:
                    print("尚未选择过文件夹，不能直接回车。")
                    continue
                target_folder_id = last_folder_id
            elif text == "l":
                print_folder_picker(folders)
                continue
            elif text == "c":
                break
            elif text.startswith("all:"):
                try:
                    bulk_folder_id = int(text.split(":", 1)[1])
                except ValueError:
                    print("all: 后面必须是数字 folder_id。")
                    continue
                if bulk_folder_id not in folder_lookup:
                    print("folder_id 不存在。")
                    continue
                confirmed = await prompt_yes_no(
                    f"确认将剩余 {len(unassigned_chats) - index} 个聊天全部归到 {folder_lookup[bulk_folder_id]} 吗？",
                    default=False,
                )
                if confirmed is True:
                    for rest_chat in unassigned_chats[index:]:
                        add_chat_assignment(
                            categorized_data=categorized_data,
                            folder_id=bulk_folder_id,
                            folder_title=folder_lookup[bulk_folder_id],
                            chat=rest_chat,
                            reason="手动批量归类",
                        )
                    print("已完成批量归类。")
                    return categorized_data
                continue
            else:
                try:
                    target_folder_id = int(text)
                except ValueError:
                    print("folder_id 必须是整数。")
                    continue

            if target_folder_id not in folder_lookup:
                print("folder_id 不存在，请输入当前文件夹列表中的 ID。")
                continue

            add_chat_assignment(
                categorized_data=categorized_data,
                folder_id=target_folder_id,
                folder_title=folder_lookup[target_folder_id],
                chat=chat,
                reason="手动复核归类",
            )
            print(f"已手动归类: {title} -> {folder_lookup[target_folder_id]}")
            last_folder_id = target_folder_id
            index += 1
            break

    return categorized_data


async def run_cli_wizard() -> None:
    try:
        config = load_config(project_root=PROJECT_ROOT)
    except ConfigError as exc:
        print_header("配置错误")
        print(str(exc))
        print("请修正 .env 后重试。")
        return

    ensure_runtime_dirs(config.paths)
    files = _runtime_files(config)
    setup_logging(files["log"])

    moved = _migrate_legacy_files(config, files)
    if moved:
        print_header("文件整理")
        print("已将历史运行文件迁移到新目录：")
        for item in moved:
            print(f"- {item}")

    print_step(1, "选择整理目标")
    print_startup_overview(config)
    print("配置校验通过。")
    print_target_mode_hint()
    target_mode = await prompt_choice(
        "整理目标 [Enter=增量补充 / r=重新整理 / d=只生成草稿 / c=从草稿继续]: ",
        allowed={"i", "r", "d", "c"},
        default="i",
    )
    draft_only = target_mode == "d"
    prefer_rebuild = target_mode == "r"
    continue_from_draft = target_mode == "c"
    mode_labels = {
        "i": "增量补充分组",
        "r": "重新整理全部文件夹",
        "d": "只生成草稿，不写入 Telegram",
        "c": "从已有草稿继续",
    }
    print(f"本次目标: {mode_labels[target_mode]}")

    print_step(2, "扫描账号状态")
    session_lock_file = None
    client = None
    try:
        session_lock_file = _acquire_session_run_lock(config.telegram.session_name, config.paths.sessions_dir)
    except RuntimeError as exc:
        print(str(exc))
        return

    try:
        await ensure_session_exists(config.telegram.session_name, config.paths.sessions_dir)
        client = create_client_with_retry(
            api_id=config.telegram.api_id,
            api_hash=config.telegram.api_hash,
            session_name=config.telegram.session_name,
            sessions_dir=config.paths.sessions_dir,
        )
        session_file = config.paths.sessions_dir / f"{config.telegram.session_name}.session"
        if not await _start_client_or_report_locked(client, session_file):
            return
        me = await client.get_me()
        display_name = me.username or me.first_name or str(me.id)
        print(f"Telegram 连接成功，当前账号: {display_name}")
        logging.info("Connected as %s", display_name)

        folders = await get_existing_folders(client)
        if not folders:
            raise RuntimeError("未读取到任何 Telegram 文件夹，请先手动创建至少一个。")
        save_folders_info(folders, files["folders"])
        print_folder_summary(folders)

        print_cache_strategy_hint()
        chats_for_ai = []
        dialog_map = {}
        cached_chats = load_chats_info(files["chats"])
        use_cache = False
        if cached_chats:
            cache_choice = await prompt_choice(
                f"发现缓存文件 {files['chats'].name} [Enter=使用缓存 / r=重新扫描]: ",
                allowed={"c", "r"},
                default="c",
            )
            use_cache = cache_choice == "c"
        if use_cache:
            chats_for_ai = cached_chats
            if _cache_has_recent_messages(chats_for_ai):
                dialog_map = await collect_dialog_map(client)
            else:
                print("缓存缺少最近消息字段，将重新扫描 Telegram。")
                use_cache = False
                chats_for_ai = []
            print(f"已加载缓存聊天: {len(chats_for_ai)} 条")
        else:
            print("正在从 Telegram 收集聊天详情，这可能需要几分钟...")
            chats_for_ai, dialog_map = await collect_chats_for_ai(
                client,
                progress_every=10,
                recent_message_limit=config.telegram_recent_message_limit,
                channel_recent_message_limit=config.telegram_channel_recent_message_limit,
                scan_delay_seconds=config.telegram_scan_delay_seconds,
                fetch_full_info=config.telegram_fetch_full_info,
                partial_save_filename=files["chats"],
                partial_save_every=config.telegram_cache_save_every,
            )
            save_chats_info(chats_for_ai, files["chats"])
            print(f"收集完成并已缓存: {len(chats_for_ai)} 条")

        if not use_cache and not chats_for_ai:
            print("缓存不可用，正在重新扫描 Telegram...")
            chats_for_ai, dialog_map = await collect_chats_for_ai(
                client,
                progress_every=10,
                recent_message_limit=config.telegram_recent_message_limit,
                channel_recent_message_limit=config.telegram_channel_recent_message_limit,
                scan_delay_seconds=config.telegram_scan_delay_seconds,
                fetch_full_info=config.telegram_fetch_full_info,
                partial_save_filename=files["chats"],
                partial_save_every=config.telegram_cache_save_every,
            )
            save_chats_info(chats_for_ai, files["chats"])
            print(f"收集完成并已缓存: {len(chats_for_ai)}")

        if not chats_for_ai:
            print("未找到可分类的群组/频道，流程结束。")
            return

        initial_data = None
        source_path = None
        if continue_from_draft:
            initial_data, source_path = _load_continue_draft(files)

        print_step(3, "补全文件夹说明")
        folder_rules = await _prepare_folder_rules(files["folder_rules"], folders)
        classification_folders = filter_classification_folders(folders, folder_rules)
        classification_folder_ids = {int(item["id"]) for item in classification_folders}
        disabled_count = len(folders) - len(classification_folders)
        if disabled_count:
            disabled_titles = [
                str(folder["title"])
                for folder in folders
                if int(folder["id"]) not in classification_folder_ids
            ]
            print(f"已禁用 {disabled_count} 个分类目标: {', '.join(disabled_titles)}")
        if not classification_folders:
            raise RuntimeError("没有可用的分类目标文件夹，请在 folder_rules.json 中启用至少一个文件夹。")
        print_detailed_classification_guidance(classification_folders)
        if initial_data is not None:
            print("已找到可继续的草稿，将跳过 AI 分类，但仍会按启用的文件夹校验草稿。")

        memory_data = create_manual_draft_template()
        memory_assigned_ids: set[int] = set()
        ai_candidate_chats = chats_for_ai
        if initial_data is None:
            memory_data = build_categorization_from_memory_csv(files["memory"], classification_folders, chats_for_ai)
            memory_assigned_ids = compute_assigned_chat_ids(memory_data)
            if memory_assigned_ids:
                print(f"已读取分类记忆: {len(memory_assigned_ids)} 条，本次将跳过这些聊天的 AI 重新判断。")
                ai_candidate_chats = []
                for chat in chats_for_ai:
                    try:
                        chat_id = int(chat.get("chat_id"))
                    except (TypeError, ValueError):
                        ai_candidate_chats.append(chat)
                        continue
                    if chat_id not in memory_assigned_ids:
                        ai_candidate_chats.append(chat)
                print(f"需要 AI 新判断的聊天: {len(ai_candidate_chats)} 条")

        print_step(4, "生成分类建议")
        if source_path:
            print(f"已加载已有草稿: {source_path}")
        elif continue_from_draft:
            print("未找到可继续的草稿，将重新生成 AI 分类建议。")

        if initial_data is None:
            ai_result = create_manual_draft_template()
            if ai_candidate_chats:
                ai_client = create_ai_client(config)
                updates_paused_for_ai = False
                try:
                    try:
                        await client.set_receive_updates(False)
                        updates_paused_for_ai = True
                        logging.info("Paused Telegram live updates during AI classification.")
                    except Exception as exc:
                        logging.warning("Failed to pause Telegram live updates: %s", exc)

                    ai_result = await _classify_with_ai_in_batches(
                        ai_client=ai_client,
                        chats_for_ai=ai_candidate_chats,
                        folders=classification_folders,
                        batch_size=config.ai_batch_size,
                        concurrency=config.ai_concurrency,
                        folder_rules=folder_rules,
                    )
                    print("AI 分类完成，已生成草稿数据。")
                except (AIClientError, ValueError) as exc:
                    logging.error("AI classify failed: %s", exc, exc_info=True)
                    manual_prompt = build_manual_prompt(ai_candidate_chats, classification_folders, folder_rules=folder_rules)
                    print_manual_fallback_hint(str(exc), manual_prompt)
                    ai_result = create_manual_draft_template()
                finally:
                    if updates_paused_for_ai:
                        try:
                            await client.set_receive_updates(True)
                            logging.info("Resumed Telegram live updates.")
                        except Exception as exc:
                            logging.warning("Failed to resume Telegram live updates: %s", exc)
            else:
                print("所有当前聊天都已命中分类记忆，跳过 AI 分类。")

            folder_lookup = {int(folder["id"]): str(folder["title"]) for folder in classification_folders}
            initial_data = merge_categorization_results([memory_data, ai_result], folder_lookup)

        save_json_file(files["draft"], initial_data)
        export_classification_review_csv(files["review_csv"], initial_data, chats_for_ai)
        draft_mtime_before_review = _file_mtime_ns(files["draft"])
        csv_mtime_before_review = _file_mtime_ns(files["review_csv"])

        print_step(5, "审核建议")
        _print_draft_summary(initial_data, chats_for_ai)
        print_draft_edit_hint(str(files["review_csv"]), str(files["draft"]))
        print_file_review_hint(str(files["review_csv"]), str(files["draft"]))

        folder_ids = {int(folder["id"]) for folder in classification_folders}
        chat_ids = {int(chat["chat_id"]) for chat in chats_for_ai}
        review_mode = await prompt_choice(
            "审核方式 [Enter=文件审核 / t=终端处理未分类 / s=跳过审核]: ",
            allowed={"f", "t", "s"},
            default="f",
        )
        if review_mode == "f":
            await wait_for_enter("请编辑 CSV 审核表，完成后返回终端继续")
            validated_data = await _apply_review_files(
                files=files,
                folders=classification_folders,
                chats_for_ai=chats_for_ai,
                draft_mtime_before=draft_mtime_before_review,
                csv_mtime_before=csv_mtime_before_review,
                valid_folder_ids=folder_ids,
                valid_chat_ids=chat_ids,
            )
            handle_unassigned = await prompt_yes_no("是否继续在终端处理剩余未分类聊天？", default=False)
            if handle_unassigned:
                unassigned_chats = compute_unassigned_chats(chats_for_ai, validated_data)
                validated_data = await _review_unassigned_chats(validated_data, unassigned_chats, classification_folders)
        elif review_mode == "t":
            validated_data = await _validate_draft_loop(files["draft"], folder_ids, chat_ids)
            unassigned_chats = compute_unassigned_chats(chats_for_ai, validated_data)
            validated_data = await _review_unassigned_chats(validated_data, unassigned_chats, classification_folders)
        else:
            validated_data = await _validate_draft_loop(files["draft"], folder_ids, chat_ids)

        save_json_file(files["draft"], validated_data)
        validated_data = await _validate_draft_loop(files["draft"], folder_ids, chat_ids)
        save_json_file(files["draft"], validated_data)
        export_classification_review_csv(files["review_csv"], validated_data, chats_for_ai)
        memory_count = export_classification_memory_csv(files["memory"], validated_data, chats_for_ai)
        print("审核完成。")
        print(f"审核 CSV 已更新: {files['review_csv']}")
        print(f"分类记忆已更新: {files['memory']}（{memory_count} 条）")

        print_step(6, "执行前预览")
        _print_draft_summary(validated_data, chats_for_ai)
        _print_execution_preview(validated_data, chats_for_ai, folders)
        first_confirm = await prompt_yes_no(
            f"确认采用当前草稿并生成 {files['final'].name} 吗？",
            default=False,
            timeout_seconds=config.ai_confirm_timeout_seconds,
        )
        if first_confirm is not True:
            print("已取消：未生成 groups.json。")
            return

        if not save_groups_data(validated_data, files["final"]):
            raise RuntimeError("写入 groups.json 失败")
        print("groups.json 已更新。")

        if draft_only:
            print("本次目标是只生成草稿，已跳过 Telegram 写入。")
            return

        print_clear_strategy_hint()
        clear_choice = await prompt_choice(
            "文件夹处理方式 [Enter=增量添加 / r=先清空再重建]: ",
            allowed={"i", "r"},
            default="r" if prefer_rebuild else "i",
        )
        clear_folders = clear_choice == "r"
        if clear_folders:
            print("将先清空现有文件夹聊天，再按当前草稿重建。")
        else:
            print("将采用增量添加模式。")

        second_confirm = await prompt_yes_no(
            "确认把分类结果写入 Telegram 文件夹吗？",
            default=False,
            timeout_seconds=config.ai_confirm_timeout_seconds,
        )
        if second_confirm is not True:
            print("已取消：结果已保存到 groups.json，但未写入 Telegram。")
            return

        print_step(7, "写入与报告")
        if clear_folders:
            print("正在清空文件夹（每个文件夹保留 1 个聊天）...")
            clear_report = await clear_existing_folders(client, classification_folders)
            _print_clear_report(clear_report)
            print("文件夹清空完成。")

        update_report = await update_folders_with_categorization(
            client=client,
            categorized_data=validated_data,
            dialog_map=dialog_map,
            existing_folders=folders,
            folders_were_cleared=bool(clear_folders),
        )
        _print_update_report(update_report)

        _print_draft_summary(validated_data, chats_for_ai)
        print("\n执行完成：")
        if update_report.get("failed_folders") or update_report.get("missing_chats"):
            print("- Telegram 写入已完成，但存在跳过或失败项，请查看上方报告和日志")
        else:
            print("- 已更新 Telegram 文件夹")
        print(f"- 草稿文件: {files['draft']}")
        print(f"- 最终结果: {files['final']}")
        print(f"- 审核 CSV: {files['review_csv']}")
        print(f"- 分类记忆: {files['memory']}")
        print(f"- 聊天缓存: {files['chats']}")
        print(f"- 文件夹信息: {files['folders']}")
        print(f"- 日志文件: {files['log']}")
    finally:
        await _safe_disconnect_client(client)
        _release_session_run_lock(session_lock_file)


def main() -> None:
    asyncio.run(run_cli_wizard())


if __name__ == "__main__":
    main()
