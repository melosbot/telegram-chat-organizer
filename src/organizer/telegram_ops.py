import asyncio
import json
import logging
import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from telethon import TelegramClient
from telethon.tl import functions, types

RECENT_MESSAGE_LIMIT = 10
RECENT_MESSAGE_CHAR_LIMIT = 220
RECENT_CONTEXT_CHAR_LIMIT = 1800


def setup_logging(log_file: Path) -> None:
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)

    for handler in logger.handlers[:]:
        logger.removeHandler(handler)

    log_file.parent.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter("[%(asctime)s] [%(levelname)s] - %(message)s", datefmt="%H:%M:%S")

    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    for noisy_logger in (
        "telethon",
        "telethon.network",
        "telethon.client",
        "google",
        "google.genai",
        "httpx",
        "httpcore",
    ):
        logging.getLogger(noisy_logger).setLevel(logging.WARNING)


def create_client_with_retry(
    api_id: int,
    api_hash: str,
    session_name: str,
    sessions_dir: Path,
    max_retries: int = 3,
) -> TelegramClient:
    sessions_dir.mkdir(parents=True, exist_ok=True)

    for attempt in range(max_retries):
        try:
            current_session = f"{session_name}_{int(time.time())}" if attempt > 0 else session_name
            session_file = sessions_dir / f"{current_session}.session"
            client = TelegramClient(str(session_file), api_id, api_hash)
            logging.info("Telethon client initialized with session: %s", session_file.name)
            return client
        except Exception as exc:
            if "database is locked" in str(exc) and attempt < max_retries - 1:
                logging.warning("Session database is locked. Retrying (%d/%d)...", attempt + 1, max_retries)
                time.sleep(1)
                continue
            raise

    raise RuntimeError("Unable to create Telegram client")


async def ensure_session_exists(session_name: str, sessions_dir: Path) -> None:
    sessions_dir.mkdir(parents=True, exist_ok=True)
    session_file = sessions_dir / f"{session_name}.session"
    if session_file.exists():
        logging.info("Found existing session file: %s", session_file)
        return

    logging.info("Session file not found. Creating a new session...")
    from create_session import create_session

    await create_session(session_name=session_name, session_dir=str(sessions_dir))
    if not session_file.exists():
        raise RuntimeError(f"Session 文件创建失败: {session_file}")


def backup_existing_groups_file(filename: str | Path = "groups.json") -> str | None:
    source = Path(filename)
    if not source.exists():
        return None

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = source.parent / f"{timestamp}-{source.name}"
    shutil.copy2(source, backup_path)
    logging.info("Backed up %s to %s", source, backup_path)
    return str(backup_path)


def save_json_file(filename: str | Path, data: dict, backup: bool = False) -> bool:
    path = Path(filename)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if backup and path.exists():
            backup_existing_groups_file(path)
        with path.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logging.info("Saved file: %s", path)
        return True
    except Exception as exc:
        logging.error("Failed to save %s: %s", path, exc)
        return False


def load_json_file(filename: str | Path) -> dict | None:
    path = Path(filename)
    try:
        if not path.exists():
            return None
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        logging.error("Failed to load %s: %s", path, exc)
        return None


def save_chats_info(chats_data: list[dict], filename: str | Path = "chats_info.json") -> bool:
    payload = {
        "timestamp": datetime.now().isoformat(),
        "total_chats": len(chats_data),
        "chats": chats_data,
    }
    return save_json_file(filename, payload)


def load_chats_info(filename: str | Path = "chats_info.json") -> list[dict] | None:
    data = load_json_file(filename)
    if not data:
        return None
    chats = data.get("chats")
    return chats if isinstance(chats, list) else None


def save_folders_info(folders_data: list[dict], filename: str | Path = "folders_info.json") -> bool:
    payload = {
        "timestamp": datetime.now().isoformat(),
        "total_folders": len(folders_data),
        "folders": [{"id": item["id"], "title": item["title"]} for item in folders_data],
    }
    return save_json_file(filename, payload)


def save_groups_data(data: dict, filename: str | Path = "groups.json") -> bool:
    return save_json_file(filename, data, backup=True)


def load_groups_data(filename: str | Path = "groups.json") -> dict | None:
    return load_json_file(filename)


def validate_groups_json(data: dict) -> tuple[bool, str]:
    try:
        if not isinstance(data, dict):
            return False, "数据必须是 JSON 对象"
        categorized = data.get("categorized")
        if not isinstance(categorized, list):
            return False, "缺少 categorized 数组"

        for i, folder_update in enumerate(categorized):
            if not isinstance(folder_update, dict):
                return False, f"categorized[{i}] 必须是对象"
            for field in ("folder_id", "folder_title", "chats"):
                if field not in folder_update:
                    return False, f"categorized[{i}] 缺少字段: {field}"
            try:
                int(folder_update["folder_id"])
            except (TypeError, ValueError):
                return False, f"categorized[{i}].folder_id 必须是整数"
            if not isinstance(folder_update["chats"], list):
                return False, f"categorized[{i}].chats 必须是数组"

            for j, chat in enumerate(folder_update["chats"]):
                if not isinstance(chat, dict):
                    return False, f"categorized[{i}].chats[{j}] 必须是对象"
                if "chat_id" not in chat:
                    return False, f"categorized[{i}].chats[{j}] 缺少 chat_id"
                try:
                    int(chat["chat_id"])
                except (TypeError, ValueError):
                    return False, f"categorized[{i}].chats[{j}].chat_id 必须是整数"

        return True, "OK"
    except Exception as exc:  # pragma: no cover - defensive
        return False, f"验证失败: {exc}"


def _flatten_message_text(text: str) -> str:
    return " ".join(str(text).split())


def _extract_message_excerpt(message, max_len: int = RECENT_MESSAGE_CHAR_LIMIT) -> str:
    text = getattr(message, "message", None) or getattr(message, "raw_text", None) or ""
    if text:
        return _flatten_message_text(str(text))[:max_len]

    action = getattr(message, "action", None)
    if action:
        return f"[{action.__class__.__name__}]"

    media = getattr(message, "media", None)
    if media:
        return f"[{media.__class__.__name__}]"

    return ""


async def _fetch_recent_message_samples(
    client: TelegramClient,
    entity,
    limit: int = RECENT_MESSAGE_LIMIT,
) -> list[str]:
    request_limit = max(limit * 2, limit)
    try:
        messages = await client.get_messages(entity, limit=request_limit)
    except Exception as exc:
        logging.debug("Could not fetch recent messages for entity %s: %s", getattr(entity, "id", "?"), exc)
        return []

    samples: list[str] = []
    for message in messages or []:
        if not message:
            continue
        text = _extract_message_excerpt(message)
        if not text:
            continue
        if getattr(message, "date", None):
            text = f"{message.date.strftime('%m-%d %H:%M')} {text}"
        samples.append(text)
        if len(samples) >= limit:
            break
    return samples


async def get_detailed_chat_info(
    client: TelegramClient,
    dialog,
    recent_message_limit: int = RECENT_MESSAGE_LIMIT,
) -> dict:
    entity = dialog.entity
    chat_info = {
        "chat_id": dialog.id,
        "title": dialog.name or "未知",
        "type": "UNKNOWN",
        "username": "",
        "description": "",
        "about": "",
        "last_message": "",
        "last_message_date": "",
        "recent_messages": [],
        "recent_messages_text": "",
        "participant_count": 0,
        "is_verified": False,
        "is_scam": False,
    }

    try:
        if isinstance(entity, types.User):
            chat_info["type"] = "BOT" if entity.bot else "PRIVATE"
            chat_info["username"] = entity.username or ""
        elif isinstance(entity, types.Channel):
            chat_info["type"] = "CHANNEL" if entity.broadcast else "SUPERGROUP"
            chat_info["username"] = entity.username or ""
            chat_info["is_verified"] = getattr(entity, "verified", False)
            chat_info["is_scam"] = getattr(entity, "scam", False)
        elif isinstance(entity, types.Chat):
            chat_info["type"] = "GROUP"

        if hasattr(entity, "about") and entity.about:
            chat_info["about"] = entity.about

        if chat_info["type"] in {"CHANNEL", "SUPERGROUP", "GROUP"}:
            try:
                if isinstance(entity, types.Channel):
                    full_chat = await client(functions.channels.GetFullChannelRequest(entity))
                    full_info = getattr(full_chat, "full_chat", None)
                else:
                    full_chat = await client(functions.messages.GetFullChatRequest(entity.id))
                    full_info = getattr(full_chat, "full_chat", None)
                if full_info:
                    if getattr(full_info, "about", None):
                        chat_info["description"] = full_info.about
                    if getattr(full_info, "participants_count", None):
                        chat_info["participant_count"] = full_info.participants_count
            except Exception as exc:
                logging.debug("Could not fetch full chat info for %s: %s", dialog.id, exc)

        if dialog.message:
            message = dialog.message
            if getattr(message, "message", None):
                chat_info["last_message"] = str(message.message)[:300]
            elif getattr(message, "action", None):
                chat_info["last_message"] = f"[系统消息: {message.action.__class__.__name__}]"
            if getattr(message, "date", None):
                chat_info["last_message_date"] = message.date.strftime("%Y-%m-%d %H:%M")

        if chat_info["type"] in {"CHANNEL", "SUPERGROUP", "GROUP"}:
            recent_messages = await _fetch_recent_message_samples(
                client=client,
                entity=entity,
                limit=recent_message_limit,
            )
            if recent_messages:
                chat_info["recent_messages"] = recent_messages
                chat_info["recent_messages_text"] = " || ".join(recent_messages)[:RECENT_CONTEXT_CHAR_LIMIT]
                if not chat_info["last_message"]:
                    chat_info["last_message"] = recent_messages[0][:300]

        if not chat_info["description"] and chat_info["about"]:
            chat_info["description"] = chat_info["about"]
    except Exception as exc:
        logging.warning("Error while reading chat %s info: %s", dialog.id, exc)

    return chat_info


async def collect_dialog_map(client: TelegramClient) -> dict[int, Any]:
    dialogs = await client.get_dialogs()
    return {dialog.id: dialog for dialog in dialogs}


async def collect_chats_for_ai(
    client: TelegramClient,
    progress_every: int = 10,
    recent_message_limit: int = RECENT_MESSAGE_LIMIT,
) -> tuple[list[dict], dict[int, Any]]:
    dialogs = await client.get_dialogs()
    dialog_map = {}
    chats_for_ai = []
    processed_count = 0

    for dialog in dialogs:
        entity = dialog.entity
        if not entity:
            continue
        dialog_map[dialog.id] = dialog

        if isinstance(entity, types.User):
            chat_type = "BOT" if entity.bot else "PRIVATE"
        elif isinstance(entity, types.Channel):
            chat_type = "CHANNEL" if entity.broadcast else "SUPERGROUP"
        elif isinstance(entity, types.Chat):
            chat_type = "GROUP"
        else:
            continue

        if chat_type in {"GROUP", "CHANNEL", "SUPERGROUP"}:
            chat_info = await get_detailed_chat_info(
                client=client,
                dialog=dialog,
                recent_message_limit=recent_message_limit,
            )
            chats_for_ai.append(chat_info)
            processed_count += 1
            if processed_count % progress_every == 0:
                logging.info("Collected %d chats for AI", processed_count)
            await asyncio.sleep(0.1)

    return chats_for_ai, dialog_map


async def get_existing_folders(client: TelegramClient) -> list[dict]:
    logging.info("Fetching existing folders...")
    folders = []
    existing_filters = await client(functions.messages.GetDialogFiltersRequest())
    for filter_obj in existing_filters.filters:
        if not hasattr(filter_obj, "id"):
            continue
        title_obj = filter_obj.title
        if hasattr(title_obj, "text"):
            title_text = title_obj.text
        elif isinstance(title_obj, str):
            title_text = title_obj
        else:
            title_text = str(title_obj)
        existing_peers = filter_obj.include_peers or []
        folders.append(
            {
                "id": filter_obj.id,
                "title": title_text,
                "title_obj": title_obj,
                "existing_peers": existing_peers,
                "pinned_peers": getattr(filter_obj, "pinned_peers", []),
                "exclude_peers": getattr(filter_obj, "exclude_peers", []),
                "filter_obj": filter_obj,
            }
        )
        logging.info("Found folder: %s (ID=%s), existing chats=%d", title_text, filter_obj.id, len(existing_peers))
    return folders


def _peer_identity(peer) -> int | None:
    for attr in ("channel_id", "chat_id", "user_id"):
        value = getattr(peer, attr, None)
        if value:
            return int(value)
    return None


async def clear_existing_folders(client: TelegramClient, existing_folders: list[dict]) -> None:
    logging.info("Clearing existing folders (keeping one chat per folder)...")
    for folder in existing_folders:
        folder_id = folder.get("id")
        folder_title = folder.get("title", "Unknown")
        existing_peers = folder.get("existing_peers", [])
        if len(existing_peers) <= 1:
            logging.info("Folder '%s' has <=1 chats, skip.", folder_title)
            continue

        try:
            original_filter = folder.get("filter_obj")
            original_title = folder.get("title_obj") or (original_filter.title if original_filter else None)
            if original_title is None or not hasattr(original_title, "_bytes"):
                original_title = types.TextWithEntities(text=folder_title, entities=[])

            kept_peers = existing_peers[:1]
            cleared_filter = types.DialogFilter(
                id=folder_id,
                title=original_title,
                pinned_peers=[],
                include_peers=kept_peers,
                exclude_peers=folder.get("exclude_peers", []),
                contacts=getattr(original_filter, "contacts", False) if original_filter else False,
                non_contacts=getattr(original_filter, "non_contacts", False) if original_filter else False,
                groups=getattr(original_filter, "groups", False) if original_filter else False,
                broadcasts=getattr(original_filter, "broadcasts", False) if original_filter else False,
                bots=getattr(original_filter, "bots", False) if original_filter else False,
                exclude_muted=getattr(original_filter, "exclude_muted", False) if original_filter else False,
                exclude_read=getattr(original_filter, "exclude_read", False) if original_filter else False,
                exclude_archived=getattr(original_filter, "exclude_archived", False) if original_filter else False,
                emoticon=getattr(original_filter, "emoticon", None) if original_filter else None,
            )
            await client(functions.messages.UpdateDialogFilterRequest(id=folder_id, filter=cleared_filter))
            folder["existing_peers"] = kept_peers
            logging.info("Cleared folder '%s', kept 1 chat", folder_title)
            await asyncio.sleep(0.3)
        except Exception as exc:
            logging.error("Failed clearing folder '%s': %s", folder_title, exc, exc_info=True)
            await asyncio.sleep(1)


async def update_folders_with_categorization(
    client: TelegramClient,
    categorized_data: dict,
    dialog_map: dict[int, Any],
    existing_folders: list[dict],
    folders_were_cleared: bool = False,
) -> None:
    logging.info("Updating folders with categorization results...")
    folder_map = {folder["id"]: folder for folder in existing_folders}

    for folder_update in categorized_data.get("categorized", []):
        folder_id = folder_update.get("folder_id")
        folder_title = folder_update.get("folder_title", "Unknown")
        chats_to_add = folder_update.get("chats", [])
        folder = folder_map.get(folder_id)
        if not folder:
            logging.warning("Folder id=%s not found. Skip.", folder_id)
            continue

        new_peers = []
        for chat_item in chats_to_add:
            try:
                chat_id = int(chat_item.get("chat_id"))
            except (TypeError, ValueError):
                logging.warning("Invalid chat_id: %s", chat_item.get("chat_id"))
                continue
            dialog = dialog_map.get(chat_id)
            if not dialog:
                logging.warning("chat_id=%s not found in dialog map", chat_id)
                continue
            if dialog.input_entity:
                new_peers.append(dialog.input_entity)

        if not new_peers:
            logging.info("No chats to add for folder '%s'", folder_title)
            continue

        existing_peers = folder.get("existing_peers", [])
        if folders_were_cleared:
            peers_to_add = new_peers
        else:
            existing_ids = {_peer_identity(peer) for peer in existing_peers}
            peers_to_add = []
            for peer in new_peers:
                peer_id = _peer_identity(peer)
                if not peer_id or peer_id in existing_ids:
                    continue
                peers_to_add.append(peer)
                existing_ids.add(peer_id)

        if not peers_to_add:
            logging.info("All target chats already in folder '%s'", folder_title)
            continue

        all_peers = existing_peers + peers_to_add

        try:
            original_filter = folder.get("filter_obj")
            original_title = folder.get("title_obj") or (original_filter.title if original_filter else None)
            if original_title is None or not hasattr(original_title, "_bytes"):
                original_title = types.TextWithEntities(text=folder.get("title", "Unknown"), entities=[])

            updated_filter = types.DialogFilter(
                id=folder_id,
                title=original_title,
                pinned_peers=folder.get("pinned_peers", []),
                include_peers=all_peers,
                exclude_peers=folder.get("exclude_peers", []),
                contacts=getattr(original_filter, "contacts", False) if original_filter else False,
                non_contacts=getattr(original_filter, "non_contacts", False) if original_filter else False,
                groups=getattr(original_filter, "groups", False) if original_filter else False,
                broadcasts=getattr(original_filter, "broadcasts", False) if original_filter else False,
                bots=getattr(original_filter, "bots", False) if original_filter else False,
                exclude_muted=getattr(original_filter, "exclude_muted", False) if original_filter else False,
                exclude_read=getattr(original_filter, "exclude_read", False) if original_filter else False,
                exclude_archived=getattr(original_filter, "exclude_archived", False) if original_filter else False,
                emoticon=getattr(original_filter, "emoticon", None) if original_filter else None,
            )

            await client(functions.messages.UpdateDialogFilterRequest(id=folder_id, filter=updated_filter))
            folder["existing_peers"] = all_peers
            logging.info("Updated folder '%s', added %d chats", folder_title, len(peers_to_add))
            await asyncio.sleep(0.5)
        except Exception as exc:
            logging.error("Failed updating folder '%s': %s", folder_title, exc, exc_info=True)
            await asyncio.sleep(1)
