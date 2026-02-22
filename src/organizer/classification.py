import csv
import json
import re
from collections import OrderedDict
from pathlib import Path
from typing import Any


def _truncate(text: str, max_len: int) -> str:
    if not text:
        return ""
    return text if len(text) <= max_len else f"{text[:max_len]}..."


def build_prompts(chats: list[dict], folders: list[dict]) -> tuple[str, str]:
    folder_payload = [{"id": f["id"], "title": f["title"]} for f in folders]

    chat_payload = []
    for chat in chats:
        chat_payload.append(
            {
                "chat_id": chat.get("chat_id"),
                "title": _truncate(str(chat.get("title", "")), 120),
                "type": chat.get("type", "UNKNOWN"),
                "username": _truncate(str(chat.get("username", "")), 80),
                "description": _truncate(str(chat.get("description", "")), 300),
                "last_message": _truncate(str(chat.get("last_message", "")), 300),
                "participant_count": chat.get("participant_count", 0),
                "is_verified": bool(chat.get("is_verified", False)),
                "is_scam": bool(chat.get("is_scam", False)),
            }
        )

    system_prompt = (
        "你是 Telegram 聊天整理专家。"
        "请严格输出 JSON，不要输出 markdown 代码块，不要输出解释性文字。"
    )

    user_prompt = (
        "请根据 folders 与 chats 的语义相关性进行分类。\n"
        "规则:\n"
        "1) 一个 chat 只能分配到一个 folder。\n"
        "2) 仅输出需要新增 chat 的 folder。\n"
        "3) 不确定时可暂不分类。\n"
        "4) 必须返回如下 JSON 结构:\n"
        '{"categorized":[{"folder_id":123,"folder_title":"名称","chats":[{"chat_id":1,"type":"GROUP","reason":"原因"}]}]}\n\n'
        f"folders={json.dumps(folder_payload, ensure_ascii=False)}\n"
        f"chats={json.dumps(chat_payload, ensure_ascii=False)}"
    )
    return system_prompt, user_prompt


def print_detailed_classification_guidance(folders: list[dict]) -> None:
    print("\n[步骤 5/11] 分类规则说明")
    print("=" * 88)
    print("目标：把每个群组/频道分到最相关的现有 Telegram 文件夹。")
    print("\n判定优先级（从高到低）：")
    print("1) 标题与用户名关键词（最可靠）")
    print("2) 描述/简介（领域和用途）")
    print("3) 最近消息语境（近期主题）")
    print("4) 群类型与规模（GROUP/CHANNEL、人数）")
    print("\n常见误判提醒：")
    print("1) 名称看似技术群，但内容是招聘/广告")
    print("2) 频道转发杂糅，最近消息不能代表长期主题")
    print("3) 同名但不同语言社区")
    print("\n建议审阅策略：")
    print("1) 先看每个文件夹新增数量是否异常")
    print("2) 抽查每个文件夹前 3 条映射是否语义一致")
    print("3) 对不确定聊天先留在未分类，后续手动归类")
    print("\n当前文件夹：")
    for folder in folders:
        print(f"- ID={folder['id']} | {folder['title']}")
    print("=" * 88)


def _strip_markdown_fence(text: str) -> str:
    cleaned = text.strip()
    fence_pattern = r"^```(?:json)?\s*(.*?)\s*```$"
    match = re.match(fence_pattern, cleaned, flags=re.IGNORECASE | re.DOTALL)
    if match:
        return match.group(1).strip()
    return cleaned


def parse_ai_response_to_groups(text: str) -> dict:
    cleaned = _strip_markdown_fence(text)
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise ValueError("AI 响应不是有效 JSON 对象")
        parsed = json.loads(cleaned[start : end + 1])
    return normalize_groups_data(parsed)


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
            normalized_chats.append(
                {
                    "chat_id": chat_id,
                    "type": str(chat_item.get("type", "UNKNOWN")),
                    "reason": _truncate(str(chat_item.get("reason", "")), 200),
                }
            )

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
            "reason": reason,
        }
    )


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
                "reason",
            ]
        )

        for folder_item in categorized_data.get("categorized", []):
            folder_id = folder_item.get("folder_id")
            folder_title = folder_item.get("folder_title", "")
            for chat_item in folder_item.get("chats", []):
                chat_id = int(chat_item.get("chat_id"))
                chat = chat_lookup.get(chat_id, {})
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
                        chat_item.get("reason", ""),
                    ]
                )

        for chat in chats_for_ai:
            chat_id = int(chat["chat_id"])
            if chat_id in assigned_ids:
                continue
            writer.writerow(
                [
                    "unassigned",
                    "",
                    "",
                    chat_id,
                    chat.get("title", ""),
                    chat.get("type", ""),
                    chat.get("username", ""),
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
    chat_lookup = {int(chat["chat_id"]): chat for chat in chats_for_ai if chat.get("chat_id") is not None}
    seen_chat_ids = set()
    categorized_map: OrderedDict[int, dict] = OrderedDict()

    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        required_columns = {"status", "folder_id", "chat_id"}
        if not reader.fieldnames or not required_columns.issubset(set(reader.fieldnames)):
            raise ValueError("CSV 缺少必需列：status, folder_id, chat_id")

        for row in reader:
            status = str(row.get("status", "")).strip().lower()
            if status != "categorized":
                continue

            try:
                folder_id = int(str(row.get("folder_id", "")).strip())
                chat_id = int(str(row.get("chat_id", "")).strip())
            except ValueError:
                continue

            if folder_id not in folder_lookup:
                continue
            if chat_id not in chat_lookup:
                continue
            if chat_id in seen_chat_ids:
                continue

            seen_chat_ids.add(chat_id)
            chat = chat_lookup[chat_id]
            reason = str(row.get("reason", "")).strip() or "CSV审核归类"
            chat_type = str(row.get("chat_type", "")).strip() or str(chat.get("type", "UNKNOWN"))

            if folder_id not in categorized_map:
                categorized_map[folder_id] = {
                    "folder_id": folder_id,
                    "folder_title": folder_lookup[folder_id],
                    "chats": [],
                }
            categorized_map[folder_id]["chats"].append(
                {
                    "chat_id": chat_id,
                    "type": chat_type,
                    "reason": reason,
                }
            )

    return {"categorized": list(categorized_map.values())}


def create_manual_draft_template() -> dict:
    return {"categorized": []}


def build_manual_prompt(chats: list[dict], folders: list[dict]) -> str:
    _, user_prompt = build_prompts(chats, folders)
    return user_prompt
