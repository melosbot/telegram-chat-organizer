"""Internal shared helpers for the classification package."""

import re
from typing import Any

from ..utils.text import message_identity_text, messages_are_duplicate


def truncate(text: str, max_len: int) -> str:
    if not text:
        return ""
    return text if len(text) <= max_len else f"{text[:max_len]}..."


def clean_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    cleaned = []
    for item in value:
        text = str(item).strip()
        if text:
            cleaned.append(text)
    return cleaned


def csv_context_text(value: Any, max_len: int) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return truncate(text, max_len)


def dedupe_recent_messages(recent_messages: list[Any], last_message: Any = "") -> list[str]:
    cleaned = []
    seen = set()
    for item in recent_messages or []:
        text = csv_context_text(item, 220)
        if not text or messages_are_duplicate(text, last_message):
            continue
        identity = message_identity_text(text)
        if identity in seen:
            continue
        seen.add(identity)
        cleaned.append(text)
    return cleaned


def chat_recent_context(chat: dict, max_items: int = 10) -> tuple[str, list[str], str]:
    last_message = csv_context_text(chat.get("last_message", ""), 300)
    recent_messages_raw = chat.get("recent_messages")
    if not isinstance(recent_messages_raw, list):
        recent_messages_raw = []
    if not recent_messages_raw and chat.get("recent_messages_text"):
        recent_messages_raw = re.split(r"\s*\|\|\s*|\s+\|\s+", str(chat.get("recent_messages_text", "")))
    recent_messages = dedupe_recent_messages(recent_messages_raw, last_message)[:max_items]
    recent_messages_text = " | ".join(recent_messages)
    return last_message, recent_messages, recent_messages_text
