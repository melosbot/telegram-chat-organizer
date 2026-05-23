"""Folder rule synchronisation, filtering, and summary helpers."""

import re
from collections import Counter

from ._shared import clean_string_list, truncate


FOLDER_RULES_VERSION = 1

# Stop words that are too generic to suggest as folder keywords. Kept tiny on
# purpose: the goal is "suggestions a human can edit", not perfect NLP.
_SUGGESTED_KEYWORD_STOPWORDS = {
    "the",
    "a",
    "an",
    "and",
    "or",
    "of",
    "in",
    "for",
    "to",
    "is",
    "on",
    "by",
    "with",
    "this",
    "that",
    "中国",
    "official",
    "channel",
    "group",
    "chat",
    "bot",
    "news",
}


def _folder_rule_from_existing(folder: dict, existing: dict | None = None, missing: bool = False) -> dict:
    existing = existing or {}
    rule = {
        "folder_id": int(folder["id"]),
        "folder_title": str(folder["title"]),
        "auto_classify": bool(existing.get("auto_classify", True)),
        "description": str(existing.get("description", "")).strip(),
        "include_keywords": clean_string_list(existing.get("include_keywords", [])),
        "exclude_keywords": clean_string_list(existing.get("exclude_keywords", [])),
        "notes": str(existing.get("notes", "")).strip(),
        "missing_from_telegram": missing,
    }
    suggested = clean_string_list(existing.get("suggested_keywords", []))
    if suggested:
        rule["suggested_keywords"] = suggested
    return rule


def sync_folder_rules(folders: list[dict], existing_rules: dict | None = None) -> dict:
    """Return a rules file payload aligned to the current Telegram folders."""
    existing_by_id: dict[int, dict] = {}
    if isinstance(existing_rules, dict):
        for item in existing_rules.get("folders", []) or []:
            if not isinstance(item, dict):
                continue
            try:
                folder_id = int(item.get("folder_id"))
            except (TypeError, ValueError):
                continue
            existing_by_id[folder_id] = item

    current_ids = {int(folder["id"]) for folder in folders}
    synced_folders = []
    for folder in folders:
        folder_id = int(folder["id"])
        synced_folders.append(_folder_rule_from_existing(folder, existing_by_id.get(folder_id)))

    for folder_id, old_rule in existing_by_id.items():
        if folder_id in current_ids:
            continue
        orphan = {
            "folder_id": folder_id,
            "folder_title": str(old_rule.get("folder_title", "")),
            "auto_classify": bool(old_rule.get("auto_classify", True)),
            "description": str(old_rule.get("description", "")).strip(),
            "include_keywords": clean_string_list(old_rule.get("include_keywords", [])),
            "exclude_keywords": clean_string_list(old_rule.get("exclude_keywords", [])),
            "notes": str(old_rule.get("notes", "")).strip(),
            "missing_from_telegram": True,
        }
        suggested = clean_string_list(old_rule.get("suggested_keywords", []))
        if suggested:
            orphan["suggested_keywords"] = suggested
        synced_folders.append(orphan)

    return {"version": FOLDER_RULES_VERSION, "folders": synced_folders}


def active_folder_rules_map(folder_rules: dict | None) -> dict[int, dict]:
    rules: dict[int, dict] = {}
    if not isinstance(folder_rules, dict):
        return rules
    for item in folder_rules.get("folders", []) or []:
        if not isinstance(item, dict) or item.get("missing_from_telegram"):
            continue
        try:
            folder_id = int(item.get("folder_id"))
        except (TypeError, ValueError):
            continue
        rules[folder_id] = item
    return rules


def filter_classification_folders(folders: list[dict], folder_rules: dict | None) -> list[dict]:
    rules = active_folder_rules_map(folder_rules)
    targets = []
    for folder in folders:
        folder_id = int(folder["id"])
        rule = rules.get(folder_id, {})
        if rule.get("auto_classify", True) is False:
            continue
        targets.append(folder)
    return targets


def build_folder_rules_summary_lines(folder_rules: dict | None, folders: list[dict]) -> tuple[list[str], int]:
    rules = active_folder_rules_map(folder_rules)
    lines = []
    missing_description_count = 0
    for folder in folders:
        folder_id = int(folder["id"])
        rule = rules.get(folder_id, {})
        auto_classify = rule.get("auto_classify", True) is not False
        description = str(rule.get("description", "")).strip()
        include_keywords = clean_string_list(rule.get("include_keywords", []))
        exclude_keywords = clean_string_list(rule.get("exclude_keywords", []))
        if auto_classify and not description:
            missing_description_count += 1
        status = "启用" if auto_classify else "禁用分类目标"
        detail = description or "未填写说明"
        extras = []
        if include_keywords:
            extras.append(f"包含: {', '.join(include_keywords[:6])}")
        if exclude_keywords:
            extras.append(f"排除: {', '.join(exclude_keywords[:6])}")
        suffix = f" ({'；'.join(extras)})" if extras else ""
        lines.append(f"- ID={folder_id} | {folder['title']} | {status} | {detail}{suffix}")
    return lines, missing_description_count


def _tokenize_title(title: str) -> list[str]:
    text = re.sub(r"[^\w一-龥]+", " ", str(title).lower())
    tokens: list[str] = []
    for raw in text.split():
        token = raw.strip()
        if len(token) < 2:
            continue
        if token in _SUGGESTED_KEYWORD_STOPWORDS:
            continue
        if token.isdigit():
            continue
        tokens.append(token)
    return tokens


def derive_suggested_keywords(
    folder_rules: dict,
    categorized_data: dict,
    chats_for_ai: list[dict],
    *,
    max_per_folder: int = 10,
    min_count: int = 2,
) -> dict:
    """Return folder_rules with each folder's ``suggested_keywords`` populated
    from the high-frequency tokens of chat titles already assigned to it.

    Suggestions are advisory only: the AI prompt uses ``include_keywords``,
    not this field. Users can copy tokens they like into ``include_keywords``.
    """
    chat_lookup = {int(c["chat_id"]): c for c in chats_for_ai if c.get("chat_id") is not None}
    folder_token_counts: dict[int, Counter] = {}
    for folder_item in categorized_data.get("categorized", []):
        try:
            folder_id = int(folder_item.get("folder_id"))
        except (TypeError, ValueError):
            continue
        counter = folder_token_counts.setdefault(folder_id, Counter())
        for chat_item in folder_item.get("chats", []):
            try:
                chat_id = int(chat_item.get("chat_id"))
            except (TypeError, ValueError):
                continue
            chat = chat_lookup.get(chat_id)
            if not chat:
                continue
            for token in _tokenize_title(chat.get("title", "")):
                counter[token] += 1

    updated_folders: list[dict] = []
    for rule in folder_rules.get("folders", []) or []:
        if not isinstance(rule, dict):
            updated_folders.append(rule)
            continue
        new_rule = dict(rule)
        try:
            folder_id = int(rule.get("folder_id"))
        except (TypeError, ValueError):
            updated_folders.append(new_rule)
            continue
        counter = folder_token_counts.get(folder_id)
        if not counter:
            new_rule.pop("suggested_keywords", None)
            updated_folders.append(new_rule)
            continue

        existing = {
            tok.lower()
            for tok in clean_string_list(rule.get("include_keywords", []))
            + clean_string_list(rule.get("exclude_keywords", []))
        }
        suggestions: list[str] = []
        for token, count in counter.most_common():
            if count < min_count:
                break
            if token in existing:
                continue
            suggestions.append(token)
            if len(suggestions) >= max_per_folder:
                break
        if suggestions:
            new_rule["suggested_keywords"] = suggestions
        else:
            new_rule.pop("suggested_keywords", None)
        updated_folders.append(new_rule)

    return {"version": folder_rules.get("version", FOLDER_RULES_VERSION), "folders": updated_folders}


def print_detailed_classification_guidance(folders: list[dict]) -> None:
    print("\n分类规则说明")
    print("=" * 88)
    print("目标：把每个群组/频道分到最相关的现有 Telegram 文件夹。")
    print("\n判定优先级（从高到低）：")
    print("1) 标题与用户名关键词（最可靠）")
    print("2) 描述/简介（领域和用途）")
    print("3) 文件夹规则中的说明和边界")
    print("4) 最近消息语境（低权重，只能辅助）")
    print("5) 群类型与规模（GROUP/CHANNEL、人数）")
    print("\n常见误判提醒：")
    print("1) 名称看似技术群，但内容是招聘/广告")
    print("2) 大型群组/频道会串场讨论多个主题，不能只看关键词")
    print("3) 频道转发杂糅，最近消息不能代表长期主题")
    print("4) 同名但不同语言社区")
    print("\n建议审阅策略：")
    print("1) 先看每个文件夹新增数量是否异常")
    print("2) 抽查每个文件夹前 3 条映射是否语义一致")
    print("3) 标题、用户名或简介已经稳定命中规则时，优先让 AI 归类，减少手动处理")
    print("4) 对主题无关、候选接近或证据不足的聊天再留在未分类")
    print("\n当前文件夹：")
    for folder in folders:
        print(f"- ID={folder['id']} | {folder['title']}")
    print("=" * 88)
