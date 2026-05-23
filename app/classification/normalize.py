"""Normalization, merging, and reference integrity for categorization results."""

from collections import OrderedDict
from typing import Any

from ._shared import clean_string_list, truncate


def normalize_groups_data(data: Any) -> dict:
    if not isinstance(data, dict):
        raise ValueError("分类结果必须是 JSON 对象")

    categorized = data.get("categorized")
    if not isinstance(categorized, list):
        raise ValueError("分类结果缺少 categorized 数组")

    normalized: list[dict] = []
    for folder_item in categorized:
        if not isinstance(folder_item, dict):
            continue
        folder_id = folder_item.get("folder_id")
        try:
            folder_id = int(folder_id)
        except (ValueError, TypeError):
            continue
        folder_title = str(folder_item.get("folder_title", "")).strip()
        chats = folder_item.get("chats", [])
        if not isinstance(chats, list):
            continue

        normalized_chats: list[dict] = []
        folder_seen = set()
        for chat_item in chats:
            if not isinstance(chat_item, dict):
                continue
            chat_id = chat_item.get("chat_id")
            try:
                chat_id = int(chat_id)
            except (ValueError, TypeError):
                continue
            if chat_id in folder_seen:
                continue
            folder_seen.add(chat_id)
            normalized_chat = {
                "chat_id": chat_id,
                "type": str(chat_item.get("type", "UNKNOWN")),
                "reason": truncate(str(chat_item.get("reason", "")), 200),
            }
            confidence = str(chat_item.get("confidence", "")).strip().lower()
            if confidence in {"high", "medium", "low", "manual"}:
                normalized_chat["confidence"] = confidence
            evidence = clean_string_list(chat_item.get("evidence", []))[:3]
            if evidence:
                normalized_chat["evidence"] = [truncate(item, 120) for item in evidence]
            normalized_chats.append(normalized_chat)

        normalized.append(
            {
                "folder_id": folder_id,
                "folder_title": folder_title,
                "chats": normalized_chats,
            }
        )

    return {"categorized": normalized}


def merge_categorization_results(results: list[dict], folder_lookup: dict[int, str]) -> dict:
    merged_folders: OrderedDict[int, dict] = OrderedDict()
    assigned_global = set()

    for result in results:
        for folder_item in result.get("categorized", []):
            folder_id = folder_item.get("folder_id")
            folder_title = folder_item.get("folder_title") or folder_lookup.get(folder_id, "Unknown")
            if folder_id not in merged_folders:
                merged_folders[folder_id] = {
                    "folder_id": folder_id,
                    "folder_title": folder_title,
                    "chats": [],
                }

            for chat_item in folder_item.get("chats", []):
                chat_id = chat_item.get("chat_id")
                if chat_id in assigned_global:
                    continue
                assigned_global.add(chat_id)
                merged_folders[folder_id]["chats"].append(chat_item)

    return {"categorized": list(merged_folders.values())}


def build_summary_lines(categorized_data: dict, chat_lookup: dict[int, dict], max_examples: int = 3) -> tuple[list[str], int]:
    lines = []
    total = 0
    for folder_item in categorized_data.get("categorized", []):
        chats = folder_item.get("chats", [])
        if not chats:
            continue
        folder_title = folder_item.get("folder_title", "Unknown")
        total += len(chats)
        examples = []
        for chat_item in chats[:max_examples]:
            chat_id = chat_item.get("chat_id")
            chat = chat_lookup.get(chat_id, {})
            examples.append(chat.get("title") or str(chat_id))
        example_text = f"（示例: {', '.join(examples)}）" if examples else ""
        lines.append(f"- {folder_title}: +{len(chats)} {example_text}")
    return lines, total


def compute_unassigned_chats(chats: list[dict], categorized_data: dict) -> list[dict]:
    assigned = set()
    for folder_item in categorized_data.get("categorized", []):
        for chat_item in folder_item.get("chats", []):
            assigned.add(chat_item.get("chat_id"))
    return [chat for chat in chats if chat.get("chat_id") not in assigned]


def compute_assigned_chat_ids(categorized_data: dict) -> set[int]:
    assigned = set()
    for folder_item in categorized_data.get("categorized", []):
        for chat_item in folder_item.get("chats", []):
            try:
                assigned.add(int(chat_item.get("chat_id")))
            except (TypeError, ValueError):
                continue
    return assigned


def validate_reference_integrity(
    data: dict,
    valid_folder_ids: set[int],
    valid_chat_ids: set[int],
) -> list[str]:
    errors = []
    seen_chat_ids = set()

    for i, folder_item in enumerate(data.get("categorized", [])):
        folder_id = folder_item.get("folder_id")
        if folder_id not in valid_folder_ids:
            errors.append(f"categorized[{i}].folder_id={folder_id} 不存在")
        chats = folder_item.get("chats", [])
        for j, chat_item in enumerate(chats):
            chat_id = chat_item.get("chat_id")
            if chat_id not in valid_chat_ids:
                errors.append(f"categorized[{i}].chats[{j}].chat_id={chat_id} 不存在")
            if chat_id in seen_chat_ids:
                errors.append(f"chat_id={chat_id} 在多个文件夹重复出现")
            seen_chat_ids.add(chat_id)
    return errors


def add_chat_assignment(
    categorized_data: dict,
    folder_id: int,
    folder_title: str,
    chat: dict,
    reason: str,
) -> None:
    target = None
    for folder_item in categorized_data.get("categorized", []):
        if folder_item.get("folder_id") == folder_id:
            target = folder_item
            break

    if target is None:
        target = {"folder_id": folder_id, "folder_title": folder_title, "chats": []}
        categorized_data.setdefault("categorized", []).append(target)

    target["chats"].append(
        {
            "chat_id": int(chat["chat_id"]),
            "type": str(chat.get("type", "UNKNOWN")),
            "confidence": "manual",
            "reason": reason,
        }
    )


def create_manual_draft_template() -> dict:
    return {"categorized": []}
