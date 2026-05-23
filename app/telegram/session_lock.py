"""Session-level lock to prevent two organizer runs sharing the same .session file."""

import json
import logging
import os
import sqlite3
from datetime import datetime
from pathlib import Path


def is_database_locked_error(exc: Exception) -> bool:
    return "database is locked" in str(exc).lower()


def _pid_is_running(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _read_lock_payload(lock_file: Path) -> dict:
    try:
        with lock_file.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def acquire_session_run_lock(session_name: str, sessions_dir: Path) -> Path:
    sessions_dir.mkdir(parents=True, exist_ok=True)
    lock_file = sessions_dir / f"{session_name}.run.lock"
    payload = {
        "pid": os.getpid(),
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "session_name": session_name,
    }

    for _ in range(2):
        try:
            fd = os.open(str(lock_file), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            existing = _read_lock_payload(lock_file)
            pid = existing.get("pid")
            if isinstance(pid, int) and _pid_is_running(pid):
                created_at = existing.get("created_at", "未知时间")
                raise RuntimeError(
                    "当前 session 正在被另一个整理流程使用。\n"
                    f"- lock: {lock_file}\n"
                    f"- pid: {pid}\n"
                    f"- started: {created_at}\n"
                    "请先结束另一个 python run.py / create_session.py 进程，再重新运行。\n"
                    f"如果确认没有残留进程，可手动删除该锁：rm {lock_file}"
                )
            logging.warning("Removing stale session run lock: %s", lock_file)
            try:
                lock_file.unlink()
            except FileNotFoundError:
                pass
            continue

        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
        return lock_file

    raise RuntimeError(f"无法创建 session 运行锁: {lock_file}")


def release_session_run_lock(lock_file: Path | None) -> None:
    if lock_file is None:
        return
    existing = _read_lock_payload(lock_file)
    if existing.get("pid") != os.getpid():
        return
    try:
        lock_file.unlink()
    except FileNotFoundError:
        pass
    except Exception as exc:
        logging.warning("Failed to release session run lock %s: %s", lock_file, exc)


def print_session_database_locked_message(session_file: Path) -> None:
    print("\nTelegram session 数据库被锁定，已停止本次运行。")
    print(f"- session: {session_file}")
    print("- 常见原因：另一个 python run.py / create_session.py 正在使用同一个 session，或上一次运行刚异常退出。")
    print("- 处理方式：关闭另一个终端里的运行进程，等待几秒后重试。")
    print("- 不建议删除 .session 文件；删除后需要重新登录 Telegram。")


async def start_client_or_report_locked(client, session_file: Path) -> bool:
    try:
        await client.start()
        return True
    except sqlite3.OperationalError as exc:
        if not is_database_locked_error(exc):
            raise
        logging.error("Telegram session database is locked during start: %s", exc)
        print_session_database_locked_message(session_file)
        return False


async def safe_disconnect_client(client) -> None:
    if client is None:
        return
    try:
        await client.disconnect()
    except sqlite3.OperationalError as exc:
        if is_database_locked_error(exc):
            logging.warning(
                "Skip Telegram disconnect state save because session database is locked: %s",
                exc,
            )
            return
        raise
    except Exception as exc:
        logging.warning("Telegram disconnect failed: %s", exc)
