"""Helpers for execution previews, dry-run CSV, and pre-clear snapshots."""

import csv
import logging
from datetime import datetime
from pathlib import Path

from ..classification import compute_unassigned_chats


def build_chat_lookup(chats_for_ai: list[dict]) -> dict[int, dict]:
    return {int(chat["chat_id"]): chat for chat in chats_for_ai if chat.get("chat_id") is not None}


def extract_chat_id_from_peer(peer) -> int | None:
    for attr in ("channel_id", "chat_id", "user_id"):
        value = getattr(peer, attr, None)
        if value:
            try:
                return int(value)
            except (TypeError, ValueError):
                continue
    return None


def snapshot_folders(snapshot_dir: Path, folders: list[dict]) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = snapshot_dir / f"folder_snapshot_{timestamp}.json"
    payload = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "folders": [],
    }
    for folder in folders:
        peer_ids: list[int] = []
        for peer in folder.get("existing_peers", []) or []:
            chat_id = extract_chat_id_from_peer(peer)
            if chat_id is not None:
                peer_ids.append(chat_id)
        payload["folders"].append(
            {
                "folder_id": int(folder.get("id")),
                "folder_title": str(folder.get("title", "")),
                "existing_chat_ids": peer_ids,
            }
        )
    import json

    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        logging.info("Saved folder snapshot: %s", path)
    except Exception as exc:  # pragma: no cover - defensive
        logging.warning("Failed to write %s: %s", path, exc)
    return path


def export_execution_preview_csv(
    path: Path,
    categorized_data: dict,
    chats_for_ai: list[dict],
    folders: list[dict],
    clear_folders: bool,
) -> tuple[int, int, int]:
    path.parent.mkdir(parents=True, exist_ok=True)
    chat_lookup = build_chat_lookup(chats_for_ai)
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
                chat_id = extract_chat_id_from_peer(peer)
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


def print_draft_summary(categorized_data: dict, chats_for_ai: list[dict]) -> None:
    from ..classification import build_summary_lines

    chat_lookup = build_chat_lookup(chats_for_ai)
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


def print_execution_preview(categorized_data: dict, chats_for_ai: list[dict], folders: list[dict]) -> None:
    folder_lookup = {int(folder["id"]): folder for folder in folders}
    chat_lookup = build_chat_lookup(chats_for_ai)
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
        print(
            f"- {folder_item.get('folder_title', folder.get('title', 'Unknown'))}: "
            f"当前 {existing_count} 个，建议添加 {len(chats)} 个{example_text}"
        )

    unassigned = compute_unassigned_chats(chats_for_ai, categorized_data)
    print(f"- 建议写入目标总数: {total_targets}")
    print(f"- 保持未分类: {len(unassigned)}")


def print_clear_report(report: dict) -> None:
    print("\n清空结果：")
    print(f"- 已清空文件夹: {report.get('cleared', 0)}")
    print(f"- 跳过文件夹: {report.get('skipped', 0)}")
    failed = report.get("failed", [])
    if failed:
        print(f"- 清空失败: {len(failed)}")
        for item in failed[:5]:
            print(f"  - {item.get('folder_title')} ({item.get('folder_id')}): {item.get('error')}")


def print_update_report(report: dict) -> None:
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
