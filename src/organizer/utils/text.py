"""Shared text helpers for message and chat fields."""

import re
from typing import Any


def flatten_message_text(text: Any) -> str:
    """Collapse whitespace runs into single spaces."""
    return " ".join(str(text).split())


def message_identity_text(value: Any) -> str:
    """Strip leading 'MM-DD HH:MM ' timestamp and normalize whitespace/case."""
    text = re.sub(r"^\d{2}-\d{2}\s+\d{2}:\d{2}\s+", "", str(value or ""))
    return flatten_message_text(text).lower()


def messages_are_duplicate(left: Any, right: Any) -> bool:
    left_text = message_identity_text(left)
    right_text = message_identity_text(right)
    if not left_text or not right_text:
        return False
    if left_text == right_text:
        return True
    shorter, longer = sorted((left_text, right_text), key=len)
    return len(shorter) >= 12 and shorter in longer


def dedupe_message_samples(samples: list[Any], last_message: Any = "") -> list[str]:
    """Drop empty, duplicate, and last_message-like entries while preserving order."""
    deduped: list[str] = []
    seen: set[str] = set()
    for sample in samples or []:
        if not sample:
            continue
        text = str(sample)
        if messages_are_duplicate(text, last_message):
            continue
        identity = message_identity_text(text)
        if identity in seen:
            continue
        seen.add(identity)
        deduped.append(text)
    return deduped
