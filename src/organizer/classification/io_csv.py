"""CSV import/export for the review and memory files."""

import csv
import hashlib
import re
from collections import OrderedDict
from datetime import datetime
from pathlib import Path
from typing import Any

from ._shared import chat_recent_context, clean_string_list, csv_context_text


SKIP_REVIEW_STATUSES = {"skip", "ignore", "remove", "delete", "x", "no", "n", "忽略", "跳过", "删除"}
CLASSIFICATION_MEMORY_COLUMNS = [
    "status",
    "folder_id",
    "folder_title",
    "chat_id",
    "chat_title",
    "chat_type",
    "username",
    "description",
    "chat_signature",
    "confidence",
    "evidence",
    "reason",
    "updated_at",
]


def compute_chat_signature(chat: dict) -> str:
    """Stable fingerprint of a chat's identifying surface used for memory invalidation.

    A change in title / username / description / about means the chat
    likely shifted topic and the memorised classification should be
    re-validated by AI.
    """
    parts = [
        str(chat.get("title", "")).strip().lower(),
        str(chat.get("username", "")).strip().lower(),
        re.sub(r"\s+", " ", str(chat.get("description", "")).strip().lower())[:400],
        re.sub(r"\s+", " ", str(chat.get("about", "")).strip().lower())[:400],
    ]
    raw = "|".join(parts)
    return hashlib.md5(raw.encode("utf-8")).hexdigest()[:16]


def export_classification_review_csv(
    csv_file: str | Path,
    categorized_data: dict,
    chats_for_ai: list[dict],
) -> None:
    path = Path(csv_file)
    path.parent.mkdir(parents=True, exist_ok=True)

    chat_lookup = {int(chat["chat_id"]): chat for chat in chats_for_ai if chat.get("chat_id") is not None}
    assigned_ids = set()

    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "status",
                "folder_id",
                "folder_title",
                "chat_id",
                "chat_title",
                "chat_type",
                "username",
                "description",
                "last_message",
                "recent_messages",
                "confidence",
                "evidence",
                "reason",
            ]
        )

        for folder_item in categorized_data.get("categorized", []):
            folder_id = folder_item.get("folder_id")
            folder_title = folder_item.get("folder_title", "")
            for chat_item in folder_item.get("chats", []):
                chat_id = int(chat_item.get("chat_id"))
                chat = chat_lookup.get(chat_id, {})
                last_message, _, recent_messages_text = chat_recent_context(chat)
                assigned_ids.add(chat_id)
                writer.writerow(
                    [
                        "categorized",
                        folder_id,
                        folder_title,
                        chat_id,
                        chat.get("title", ""),
                        chat_item.get("type", chat.get("type", "")),
                        chat.get("username", ""),
                        csv_context_text(chat.get("description", ""), 500),
                        last_message,
                        csv_context_text(recent_messages_text, 500),
                        chat_item.get("confidence", ""),
                        " | ".join(clean_string_list(chat_item.get("evidence", []))),
                        chat_item.get("reason", ""),
                    ]
                )

        for chat in chats_for_ai:
            chat_id = int(chat["chat_id"])
            if chat_id in assigned_ids:
                continue
            last_message, _, recent_messages_text = chat_recent_context(chat)
            writer.writerow(
                [
                    "unassigned",
                    "",
                    "",
                    chat_id,
                    chat.get("title", ""),
                    chat.get("type", ""),
                    chat.get("username", ""),
                    csv_context_text(chat.get("description", ""), 500),
                    last_message,
                    csv_context_text(recent_messages_text, 500),
                    "",
                    "",
                    "",
                ]
            )


def build_categorization_from_review_csv(
    csv_file: str | Path,
    folders: list[dict],
    chats_for_ai: list[dict],
) -> dict:
    path = Path(csv_file)
    if not path.exists():
        raise ValueError(f"CSV 不存在: {path}")

    folder_lookup = {int(folder["id"]): folder["title"] for folder in folders}
    folder_title_lookup = {str(folder["title"]).strip().lower(): int(folder["id"]) for folder in folders}
    chat_lookup = {int(chat["chat_id"]): chat for chat in chats_for_ai if chat.get("chat_id") is not None}
    seen_chat_ids = set()
    categorized_map: OrderedDict[int, dict] = OrderedDict()

    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        required_columns = {"status", "chat_id"}
        if not reader.fieldnames or not required_columns.issubset(set(reader.fieldnames)):
            raise ValueError("CSV 缺少必需列：status, chat_id")

        for row in reader:
            status = str(row.get("status", "")).strip().lower()
            if status in SKIP_REVIEW_STATUSES:
                continue

            folder_id = None
            folder_id_raw = str(row.get("folder_id", "")).strip()
            if folder_id_raw:
                try:
                    folder_id = int(folder_id_raw)
                except ValueError:
                    folder_id = None
            if folder_id is None and status != "categorized":
                folder_title = str(row.get("folder_title", "")).strip().lower()
                if folder_title:
                    folder_id = folder_title_lookup.get(folder_title)

            if status != "categorized" and folder_id is None:
                continue

            try:
                chat_id = int(str(row.get("chat_id", "")).strip())
            except ValueError:
                continue

            if folder_id is None or folder_id not in folder_lookup:
                continue
            if chat_id not in chat_lookup:
                continue
            if chat_id in seen_chat_ids:
                continue

            seen_chat_ids.add(chat_id)
            chat = chat_lookup[chat_id]
            reason = str(row.get("reason", "")).strip() or "CSV审核归类"
            chat_type = str(row.get("chat_type", "")).strip() or str(chat.get("type", "UNKNOWN"))
            confidence = str(row.get("confidence", "")).strip().lower()
            evidence = [item.strip() for item in str(row.get("evidence", "")).split("|") if item.strip()]

            if folder_id not in categorized_map:
                categorized_map[folder_id] = {
                    "folder_id": folder_id,
                    "folder_title": folder_lookup[folder_id],
                    "chats": [],
                }
            chat_item = {
                "chat_id": chat_id,
                "type": chat_type,
                "reason": reason,
            }
            if confidence in {"high", "medium", "low", "manual"}:
                chat_item["confidence"] = confidence
            if evidence:
                chat_item["evidence"] = evidence[:3]
            categorized_map[folder_id]["chats"].append(chat_item)

    return {"categorized": list(categorized_map.values())}


def build_categorization_from_memory_csv(
    csv_file: str | Path,
    folders: list[dict],
    chats_for_ai: list[dict],
) -> tuple[dict, dict]:
    """Return (categorized_data, stats).

    stats keys:
    - hit: rows whose signature still matches the current chat
    - changed: rows skipped because the chat signature changed
    - missing_chat: rows skipped because the chat is no longer present
    - legacy_no_signature: rows accepted but with no signature recorded
    """
    path = Path(csv_file)
    stats = {"hit": 0, "changed": 0, "missing_chat": 0, "legacy_no_signature": 0}
    if not path.exists():
        return {"categorized": []}, stats

    folder_lookup = {int(folder["id"]): folder["title"] for folder in folders}
    folder_title_lookup = {str(folder["title"]).strip().lower(): int(folder["id"]) for folder in folders}
    chat_lookup = {int(chat["chat_id"]): chat for chat in chats_for_ai if chat.get("chat_id") is not None}
    seen_chat_ids = set()
    categorized_map: OrderedDict[int, dict] = OrderedDict()

    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames or "chat_id" not in reader.fieldnames:
            return {"categorized": []}, stats
        has_signature_column = "chat_signature" in reader.fieldnames

        for row in reader:
            status = str(row.get("status", "")).strip().lower()
            if status in SKIP_REVIEW_STATUSES:
                continue

            try:
                chat_id = int(str(row.get("chat_id", "")).strip())
            except ValueError:
                continue
            if chat_id in seen_chat_ids:
                continue
            if chat_id not in chat_lookup:
                stats["missing_chat"] += 1
                continue

            folder_id = None
            folder_id_raw = str(row.get("folder_id", "")).strip()
            if folder_id_raw:
                try:
                    folder_id = int(folder_id_raw)
                except ValueError:
                    folder_id = None
            if folder_id is None:
                folder_title = str(row.get("folder_title", "")).strip().lower()
                if folder_title:
                    folder_id = folder_title_lookup.get(folder_title)
            if folder_id is None or folder_id not in folder_lookup:
                continue

            chat = chat_lookup[chat_id]
            stored_signature = str(row.get("chat_signature", "")).strip() if has_signature_column else ""
            current_signature = compute_chat_signature(chat)
            if stored_signature:
                if stored_signature != current_signature:
                    stats["changed"] += 1
                    continue
                stats["hit"] += 1
            else:
                stats["legacy_no_signature"] += 1

            seen_chat_ids.add(chat_id)
            chat_type = str(row.get("chat_type", "")).strip() or str(chat.get("type", "UNKNOWN"))
            confidence = str(row.get("confidence", "")).strip().lower() or "manual"
            reason = str(row.get("reason", "")).strip() or "分类记忆"
            evidence = [item.strip() for item in str(row.get("evidence", "")).split("|") if item.strip()]

            if folder_id not in categorized_map:
                categorized_map[folder_id] = {
                    "folder_id": folder_id,
                    "folder_title": folder_lookup[folder_id],
                    "chats": [],
                }

            chat_item = {
                "chat_id": chat_id,
                "type": chat_type,
                "confidence": confidence if confidence in {"high", "medium", "low", "manual"} else "manual",
                "reason": reason,
            }
            if evidence:
                chat_item["evidence"] = evidence[:3]
            categorized_map[folder_id]["chats"].append(chat_item)

    return {"categorized": list(categorized_map.values())}, stats


def export_classification_memory_csv(
    csv_file: str | Path,
    categorized_data: dict,
    chats_for_ai: list[dict],
) -> int:
    path = Path(csv_file)
    path.parent.mkdir(parents=True, exist_ok=True)

    existing_rows: OrderedDict[int, dict] = OrderedDict()
    if path.exists():
        try:
            with path.open("r", encoding="utf-8-sig", newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    try:
                        chat_id = int(str(row.get("chat_id", "")).strip())
                    except ValueError:
                        continue
                    status = str(row.get("status", "")).strip().lower()
                    if status in SKIP_REVIEW_STATUSES:
                        continue
                    existing_rows[chat_id] = {column: row.get(column, "") for column in CLASSIFICATION_MEMORY_COLUMNS}
        except Exception:
            existing_rows = OrderedDict()

    chat_lookup = {int(chat["chat_id"]): chat for chat in chats_for_ai if chat.get("chat_id") is not None}
    current_chat_ids = set(chat_lookup)
    for chat_id in current_chat_ids:
        existing_rows.pop(chat_id, None)

    updated_at = datetime.now().isoformat(timespec="seconds")
    new_rows: list[dict] = []
    for folder_item in categorized_data.get("categorized", []):
        folder_id = folder_item.get("folder_id")
        folder_title = folder_item.get("folder_title", "")
        for chat_item in folder_item.get("chats", []):
            try:
                chat_id = int(chat_item.get("chat_id"))
            except (TypeError, ValueError):
                continue
            chat = chat_lookup.get(chat_id)
            if not chat:
                continue
            new_rows.append(
                {
                    "status": "categorized",
                    "folder_id": folder_id,
                    "folder_title": folder_title,
                    "chat_id": chat_id,
                    "chat_title": chat.get("title", ""),
                    "chat_type": chat_item.get("type", chat.get("type", "")),
                    "username": chat.get("username", ""),
                    "description": csv_context_text(chat.get("description", ""), 500),
                    "chat_signature": compute_chat_signature(chat),
                    "confidence": chat_item.get("confidence", "manual") or "manual",
                    "evidence": " | ".join(clean_string_list(chat_item.get("evidence", []))),
                    "reason": chat_item.get("reason", "") or "审核确认分类",
                    "updated_at": updated_at,
                }
            )

    for row in new_rows:
        existing_rows[int(row["chat_id"])] = row

    rows = list(existing_rows.values())
    rows.sort(key=lambda row: (str(row.get("folder_title", "")), str(row.get("chat_title", "")), str(row.get("chat_id", ""))))

    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CLASSIFICATION_MEMORY_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    return len(rows)
