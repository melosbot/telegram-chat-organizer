import asyncio
import csv
import json
import logging
import os
import re
import shutil
import sqlite3
import sys
from collections import Counter
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
    logs_dir = config.paths.logs_dir
    return {
        "draft": data_dir / "groups.draft.json",
        "final": data_dir / "groups.json",
        "chats": data_dir / "chats_info.json",
        "folders": data_dir / "folders_info.json",
        "folder_rules": data_dir / "folder_rules.json",
        "memory": data_dir / "classification_memory.csv",
        "review_csv": data_dir / "classification_review.csv",
        "execution_preview": data_dir / "execution_preview.csv",
        "log": logs_dir / "run.log",
        "failed_batches": logs_dir / "failed_batches.json",
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
    on_partial_result=None,
) -> tuple[dict, list[dict]]:
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
    folder_lookup = {folder["id"]: folder["title"] for folder in folders}

    async def classify_one(index: int, batch: list[dict]) -> tuple[int, dict | None, dict | None]:
        async with semaphore:
            print(f"- 开始 AI 分类批次 {index + 1}/{total_batches}，本批 {len(batch)} 条聊天")
            try:
                batch_result = await ai_client.classify(batch, folders, folder_rules=folder_rules)
                print(f"- 完成 AI 分类批次 {index + 1}/{total_batches}")
                return index, batch_result, None
            except (AIClientError, ValueError) as exc:
                chat_ids = []
                for chat in batch:
                    try:
                        chat_ids.append(int(chat.get("chat_id")))
                    except (TypeError, ValueError):
                        continue
                logging.error(
                    "AI classify batch %d/%d failed: %s",
                    index + 1,
                    total_batches,
                    exc,
                    exc_info=True,
                )
                print(f"- 批次 {index + 1}/{total_batches} 失败，已记录失败聊天，将继续后续批次。原因: {exc}")
                return index, None, {
                    "batch_index": index,
                    "chat_ids": chat_ids,
                    "error": str(exc),
                }

    tasks = [asyncio.create_task(classify_one(index, batch)) for index, batch in batches]
    results_by_index: dict[int, dict] = {}
    failed_batches: list[dict] = []

    for coro in asyncio.as_completed(tasks):
        index, batch_result, error = await coro
        if error is not None:
            failed_batches.append(error)
            continue
        results_by_index[index] = batch_result
        if on_partial_result is not None:
            ordered = [results_by_index[i] for i in sorted(results_by_index)]
            partial_merged = merge_categorization_results(ordered, folder_lookup)
            try:
                on_partial_result(partial_merged, len(results_by_index), total_batches)
            except Exception as exc:  # pragma: no cover - defensive
                logging.warning("partial result callback failed: %s", exc)

    ordered_results = [results_by_index[i] for i in sorted(results_by_index)]
    merged = merge_categorization_results(ordered_results, folder_lookup)
    return merged, failed_batches


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


def _save_failed_batches(path: Path, failed_batches: list[dict], context: dict | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "context": context or {},
        "failed_batches": failed_batches,
    }
    try:
        with path.open("w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        logging.info("Saved failed batches: %s", path)
    except Exception as exc:  # pragma: no cover - defensive
        logging.warning("Failed to write %s: %s", path, exc)


def _clear_failed_batches(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        return
    except Exception as exc:  # pragma: no cover - defensive
        logging.warning("Failed to remove %s: %s", path, exc)


def _load_failed_batches_chat_ids(path: Path) -> tuple[list[int], str | None]:
    data, error = _load_json_with_error(path)
    if data is None:
        return [], error
    chat_ids: list[int] = []
    for item in data.get("failed_batches", []) or []:
        for raw_id in item.get("chat_ids", []) or []:
            try:
                chat_ids.append(int(raw_id))
            except (TypeError, ValueError):
                continue
    timestamp = str(data.get("timestamp", "")).strip() or None
    return chat_ids, timestamp


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


def _extract_chat_id_from_peer(peer) -> int | None:
    for attr in ("channel_id", "chat_id", "user_id"):
        value = getattr(peer, attr, None)
        if value:
            try:
                return int(value)
            except (TypeError, ValueError):
                continue
    return None


def _snapshot_folders(snapshot_dir: Path, folders: list[dict]) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = snapshot_dir / f"folder_snapshot_{timestamp}.json"
    payload = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "folders": [],
    }
    for folder in folders:
        peer_ids: list[int] = []
        for peer in folder.get("existing_peers", []) or []:
            chat_id = _extract_chat_id_from_peer(peer)
            if chat_id is not None:
                peer_ids.append(chat_id)
        payload["folders"].append(
            {
                "folder_id": int(folder.get("id")),
                "folder_title": str(folder.get("title", "")),
                "existing_chat_ids": peer_ids,
            }
        )
    save_json_file(path, payload)
    return path


def _export_execution_preview_csv(
    path: Path,
    categorized_data: dict,
    chats_for_ai: list[dict],
    folders: list[dict],
    clear_folders: bool,
) -> tuple[int, int, int]:
    path.parent.mkdir(parents=True, exist_ok=True)
    chat_lookup = _build_chat_lookup(chats_for_ai)
    folder_map = {int(f["id"]): f for f in folders}
    add_count = keep_count = remove_count = 0

    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            ["folder_id", "folder_title", "chat_id", "chat_title", "chat_type", "action", "reason"]
        )

        for folder_item in categorized_data.get("categorized", []):
            try:
                folder_id = int(folder_item.get("folder_id"))
            except (TypeError, ValueError):
                continue
            folder_title = folder_item.get("folder_title", "")
            folder = folder_map.get(folder_id, {})
            existing_ids: set[int] = set()
            for peer in folder.get("existing_peers", []) or []:
                chat_id = _extract_chat_id_from_peer(peer)
                if chat_id is not None:
                    existing_ids.add(chat_id)

            target_ids: set[int] = set()
            for chat_item in folder_item.get("chats", []):
                try:
                    chat_id = int(chat_item.get("chat_id"))
                except (TypeError, ValueError):
                    continue
                target_ids.add(chat_id)
                chat = chat_lookup.get(chat_id, {})
                action = "keep" if chat_id in existing_ids else "add"
                if action == "add":
                    add_count += 1
                else:
                    keep_count += 1
                writer.writerow(
                    [
                        folder_id,
                        folder_title,
                        chat_id,
                        chat.get("title", ""),
                        chat_item.get("type", chat.get("type", "")),
                        action,
                        chat_item.get("reason", ""),
                    ]
                )

            if clear_folders:
                for chat_id in sorted(existing_ids - target_ids):
                    chat = chat_lookup.get(chat_id, {})
                    remove_count += 1
                    writer.writerow(
                        [
                            folder_id,
                            folder_title,
                            chat_id,
                            chat.get("title", ""),
                            chat.get("type", ""),
                            "remove",
                            "clear-rebuild 移除",
                        ]
                    )

    return add_count, keep_count, remove_count


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


def _chat_haystack(chat: dict) -> str:
    return " ".join(
        [
            str(chat.get("title", "")),
            str(chat.get("username", "")),
            str(chat.get("description", "")),
            str(chat.get("recent_messages_text", "")),
            str(chat.get("last_message", "")),
        ]
    ).lower()


def _parse_chat_id_tokens(text: str) -> set[int]:
    ids: set[int] = set()
    for token in re.split(r"[,\s]+", text or ""):
        if not token:
            continue
        try:
            ids.add(int(token))
        except ValueError:
            continue
    return ids


async def _review_unassigned_chats(categorized_data: dict, unassigned_chats: list[dict], folders: list[dict]) -> dict:
    if not unassigned_chats:
        print("未分类复核：无未分类聊天。")
        return categorized_data

    folder_lookup = {int(folder["id"]): folder["title"] for folder in folders}
    print_unassigned_hint()
    print_folder_picker(folders)
    print(f"需要复核的未分类聊天数: {len(unassigned_chats)}")

    pool: list[dict] = list(unassigned_chats)
    handled_ids: set[int] = set()
    queue: list[dict] = list(pool)
    last_folder_id: int | None = None

    def rebuild_queue_from_pool() -> list[dict]:
        return [chat for chat in pool if int(chat["chat_id"]) not in handled_ids]

    while queue:
        chat = queue[0]
        chat_id = int(chat["chat_id"])
        title = chat.get("title", "未知")
        chat_type = chat.get("type", "UNKNOWN")
        description = chat.get("description") or chat.get("recent_messages_text") or chat.get("last_message") or ""
        suggested_folder = _suggest_folder_id(chat, folders)

        print("\n" + "-" * 88)
        print(f"剩余 {len(queue)} 条（总未处理 {len(rebuild_queue_from_pool())}） | chat_id={chat_id} | {title} | {chat_type}")
        if description:
            print(f"摘要: {description[:160]}")
        if suggested_folder is not None:
            print(f"建议归类: {suggested_folder} ({folder_lookup[suggested_folder]})")

        raw = await prompt_text("操作 [Enter/i 忽略 | m 归类 | b 批量 | s 过滤 | r 重置过滤 | g 分桶 | l 列表 | q 结束 | ?]: ")
        if raw is None:
            continue
        cmd = raw.strip()
        if not cmd:
            cmd = "i"
        head, _, rest = cmd.partition(" ")
        head = head.lower()
        rest = rest.strip()

        if head == "q":
            print("已结束未分类复核，剩余聊天保持未分类。")
            break
        if head == "?":
            print_unassigned_hint()
            continue
        if head == "l":
            print_folder_picker(folders)
            continue
        if head == "i":
            handled_ids.add(chat_id)
            queue.pop(0)
            continue
        if head == "g":
            counts = Counter(str(c.get("type", "UNKNOWN")) for c in queue)
            print("当前队列分桶:")
            for chat_type_name, n in counts.most_common():
                print(f"  {chat_type_name}: {n}")
            continue
        if head == "r":
            queue = rebuild_queue_from_pool()
            print(f"已重置过滤，当前队列 {len(queue)} 条。")
            continue
        if head == "s":
            keyword = rest.lower()
            if not keyword:
                print("用法: s <关键词>")
                continue
            filtered = [c for c in rebuild_queue_from_pool() if keyword in _chat_haystack(c)]
            if not filtered:
                print(f"过滤后无匹配 '{keyword}'。")
                continue
            preview_limit = 30
            print(f"过滤命中 {len(filtered)} 条（最多展示 {preview_limit}）：")
            for idx, c in enumerate(filtered[:preview_limit], start=1):
                print(f"  [{idx}] chat_id={c['chat_id']} | {c.get('title')} | {c.get('type')}")
            if len(filtered) > preview_limit:
                print(f"  ... 还有 {len(filtered) - preview_limit} 条未展示")
            queue = filtered
            continue
        if head == "b":
            parts = rest.split(maxsplit=1)
            if not parts:
                print("用法: b <folder_id> <chat_id1,chat_id2,...> 或 b <folder_id> all")
                continue
            try:
                target_fid = int(parts[0])
            except ValueError:
                print("folder_id 必须是整数。")
                continue
            if target_fid not in folder_lookup:
                print("folder_id 不存在。")
                continue
            selector = parts[1].strip() if len(parts) > 1 else ""
            if not selector:
                print("用法: b <folder_id> <chat_id1,chat_id2,...> 或 b <folder_id> all")
                continue
            if selector.lower() == "all":
                target_chats = list(queue)
            else:
                target_ids = _parse_chat_id_tokens(selector)
                if not target_ids:
                    print("未解析到有效 chat_id。")
                    continue
                target_chats = [c for c in queue if int(c["chat_id"]) in target_ids]
            if not target_chats:
                print("当前队列里没有匹配的聊天（试试 r 重置过滤）。")
                continue
            confirmed = await prompt_yes_no(
                f"确认把 {len(target_chats)} 条聊天归到 {folder_lookup[target_fid]} 吗？",
                default=False,
            )
            if confirmed is not True:
                continue
            for c in target_chats:
                add_chat_assignment(
                    categorized_data=categorized_data,
                    folder_id=target_fid,
                    folder_title=folder_lookup[target_fid],
                    chat=c,
                    reason="手动批量归类",
                )
            assigned_set = {int(c["chat_id"]) for c in target_chats}
            handled_ids |= assigned_set
            queue = [c for c in queue if int(c["chat_id"]) not in assigned_set]
            last_folder_id = target_fid
            print(f"已批量归类 {len(target_chats)} 条到 {folder_lookup[target_fid]}。")
            continue
        if head == "m":
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
                        f"确认将剩余 {len(queue)} 个聊天全部归到 {folder_lookup[bulk_folder_id]} 吗？",
                        default=False,
                    )
                    if confirmed is True:
                        for rest_chat in queue:
                            add_chat_assignment(
                                categorized_data=categorized_data,
                                folder_id=bulk_folder_id,
                                folder_title=folder_lookup[bulk_folder_id],
                                chat=rest_chat,
                                reason="手动批量归类",
                            )
                        handled_ids |= {int(c["chat_id"]) for c in queue}
                        queue = []
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
                handled_ids.add(chat_id)
                queue.pop(0)
                break
            continue

        print("未知命令。输入 ? 查看帮助。")

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

            failed_ids, failed_ts = _load_failed_batches_chat_ids(files["failed_batches"])
            candidate_id_set = set()
            for chat in ai_candidate_chats:
                try:
                    candidate_id_set.add(int(chat.get("chat_id")))
                except (TypeError, ValueError):
                    continue
            retry_ids = sorted({cid for cid in failed_ids if cid in candidate_id_set})
            if retry_ids:
                print(
                    f"检测到上次失败批次记录（{failed_ts or '时间未知'}），"
                    f"共 {len(retry_ids)} 条聊天可仅重试。"
                )
                retry_only = await prompt_yes_no("仅重试上次失败的聊天？", default=True)
                if retry_only is True:
                    retry_set = set(retry_ids)
                    ai_candidate_chats = [
                        chat for chat in ai_candidate_chats
                        if int(chat.get("chat_id", 0) or 0) in retry_set
                    ]
                    print(f"已切换为仅重试 {len(ai_candidate_chats)} 条聊天。")

        print_step(4, "生成分类建议")
        if source_path:
            print(f"已加载已有草稿: {source_path}")
        elif continue_from_draft:
            print("未找到可继续的草稿，将重新生成 AI 分类建议。")

        if initial_data is None:
            ai_result = create_manual_draft_template()
            failed_batches: list[dict] = []
            if ai_candidate_chats:
                ai_client = create_ai_client(config)
                updates_paused_for_ai = False
                folder_lookup_for_save = {
                    int(folder["id"]): str(folder["title"]) for folder in classification_folders
                }

                def _save_partial(partial_result: dict, done: int, total: int) -> None:
                    merged = merge_categorization_results(
                        [memory_data, partial_result], folder_lookup_for_save
                    )
                    save_json_file(files["draft"], merged)
                    print(f"- 已保存增量草稿（{done}/{total} 批）: {files['draft']}")

                try:
                    try:
                        await client.set_receive_updates(False)
                        updates_paused_for_ai = True
                        logging.info("Paused Telegram live updates during AI classification.")
                    except Exception as exc:
                        logging.warning("Failed to pause Telegram live updates: %s", exc)

                    ai_result, failed_batches = await _classify_with_ai_in_batches(
                        ai_client=ai_client,
                        chats_for_ai=ai_candidate_chats,
                        folders=classification_folders,
                        batch_size=config.ai_batch_size,
                        concurrency=config.ai_concurrency,
                        folder_rules=folder_rules,
                        on_partial_result=_save_partial,
                    )
                    if failed_batches:
                        failed_chat_count = sum(len(item.get("chat_ids", [])) for item in failed_batches)
                        print(
                            f"AI 分类完成：{len(failed_batches)} 个批次失败，"
                            f"涉及 {failed_chat_count} 条聊天；详见 {files['failed_batches']}。"
                        )
                    else:
                        print("AI 分类完成，已生成草稿数据。")
                except (AIClientError, ValueError) as exc:
                    logging.error("AI classify failed: %s", exc, exc_info=True)
                    manual_prompt = build_manual_prompt(ai_candidate_chats, classification_folders, folder_rules=folder_rules)
                    print_manual_fallback_hint(str(exc), manual_prompt)
                    ai_result = create_manual_draft_template()
                    failed_batches = [
                        {
                            "batch_index": -1,
                            "chat_ids": [
                                int(chat.get("chat_id"))
                                for chat in ai_candidate_chats
                                if chat.get("chat_id") is not None
                            ],
                            "error": str(exc),
                        }
                    ]
                finally:
                    if updates_paused_for_ai:
                        try:
                            await client.set_receive_updates(True)
                            logging.info("Resumed Telegram live updates.")
                        except Exception as exc:
                            logging.warning("Failed to resume Telegram live updates: %s", exc)

                if failed_batches:
                    _save_failed_batches(
                        files["failed_batches"],
                        failed_batches,
                        context={"total_candidates": len(ai_candidate_chats)},
                    )
                else:
                    _clear_failed_batches(files["failed_batches"])
            else:
                print("所有当前聊天都已命中分类记忆，跳过 AI 分类。")
                _clear_failed_batches(files["failed_batches"])

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

        add_count, keep_count, remove_count = _export_execution_preview_csv(
            path=files["execution_preview"],
            categorized_data=validated_data,
            chats_for_ai=chats_for_ai,
            folders=folders,
            clear_folders=clear_folders,
        )
        print(
            f"执行预览已导出: {files['execution_preview']} "
            f"(add={add_count} keep={keep_count} remove={remove_count})"
        )
        print("- 请在 Excel/Sheets 打开预览 CSV，按 action 列过滤可确认每条操作")

        second_confirm = await prompt_yes_no(
            "确认把分类结果写入 Telegram 文件夹吗？",
            default=False,
            timeout_seconds=config.ai_confirm_timeout_seconds,
        )
        if second_confirm is not True:
            print("已取消：结果已保存到 groups.json，但未写入 Telegram。")
            return

        print_step(7, "写入与报告")
        snapshot_path: Path | None = None
        if clear_folders:
            snapshot_path = _snapshot_folders(config.paths.data_dir, folders)
            print(f"清空前快照已保存: {snapshot_path}")
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
        print(f"- 执行预览 CSV: {files['execution_preview']}")
        if snapshot_path is not None:
            print(f"- 清空前快照: {snapshot_path}")
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
