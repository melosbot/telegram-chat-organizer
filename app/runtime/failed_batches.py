"""Persist AI batch failures so the next run can offer to retry only those chats."""

import json
import logging
from datetime import datetime
from pathlib import Path


def save_failed_batches(path: Path, failed_batches: list[dict], context: dict | None = None) -> None:
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


def clear_failed_batches(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        return
    except Exception as exc:  # pragma: no cover - defensive
        logging.warning("Failed to remove %s: %s", path, exc)


def load_failed_batches_chat_ids(path: Path) -> tuple[list[int], str | None]:
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return [], None
    except (json.JSONDecodeError, OSError):
        return [], None
    if not isinstance(data, dict):
        return [], None

    chat_ids: list[int] = []
    for item in data.get("failed_batches", []) or []:
        if not isinstance(item, dict):
            continue
        for raw_id in item.get("chat_ids", []) or []:
            try:
                chat_ids.append(int(raw_id))
            except (TypeError, ValueError):
                continue
    timestamp = str(data.get("timestamp", "")).strip() or None
    return chat_ids, timestamp
