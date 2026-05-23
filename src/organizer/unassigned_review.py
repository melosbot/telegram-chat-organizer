"""Interactive terminal review for chats that the AI left unassigned."""

import re
from collections import Counter

from .classification import add_chat_assignment
from .cli_flow import print_folder_picker, print_unassigned_hint, prompt_text, prompt_yes_no


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


def suggest_folder_id(chat: dict, folders: list[dict]) -> int | None:
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


async def review_unassigned_chats(categorized_data: dict, unassigned_chats: list[dict], folders: list[dict]) -> dict:
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
        suggested_folder = suggest_folder_id(chat, folders)

        print("\n" + "-" * 88)
        print(
            f"剩余 {len(queue)} 条（总未处理 {len(rebuild_queue_from_pool())}） | "
            f"chat_id={chat_id} | {title} | {chat_type}"
        )
        if description:
            print(f"摘要: {description[:160]}")
        if suggested_folder is not None:
            print(f"建议归类: {suggested_folder} ({folder_lookup[suggested_folder]})")

        raw = await prompt_text(
            "操作 [Enter/i 忽略 | m 归类 | b 批量 | s 过滤 | r 重置过滤 | g 分桶 | l 列表 | q 结束 | ?]: "
        )
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
