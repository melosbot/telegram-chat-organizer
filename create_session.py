import asyncio
import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from telethon.sync import TelegramClient


class bcolors:
    HEADER = "\033[95m"
    OKBLUE = "\033[94m"
    OKGREEN = "\033[92m"
    WARNING = "\033[93m"
    FAIL = "\033[91m"
    ENDC = "\033[0m"


async def create_session(session_name: str | None = None, session_dir: str | None = None) -> None:
    """Generate a Telethon .session file interactively."""
    print(f"{bcolors.HEADER}--- Telegram Session Generator ---{bcolors.ENDC}")

    load_dotenv(override=True)

    try:
        api_id = int(os.environ["API_ID"])
        api_hash = os.environ["API_HASH"]
        resolved_session_name = session_name or os.environ.get("SESSION_NAME", "mili")
    except (KeyError, ValueError) as exc:
        print(f"{bcolors.FAIL}Error: API_ID or API_HASH is missing/invalid.{bcolors.ENDC}")
        print(f"{bcolors.WARNING}Please check your .env settings.{bcolors.ENDC}")
        raise exc

    resolved_session_dir = Path(session_dir or os.environ.get("SESSIONS_DIR", "sessions"))
    resolved_session_dir.mkdir(parents=True, exist_ok=True)
    session_file = resolved_session_dir / f"{resolved_session_name}.session"

    client = TelegramClient(str(session_file), api_id, api_hash)

    try:
        async with client:
            user = await client.get_me()
            username = f"@{user.username}" if user.username else "(no username)"
            print(f"\n{bcolors.OKGREEN}Session file created: {session_file}{bcolors.ENDC}")
            print(f"{bcolors.OKBLUE}Logged in as: {user.first_name} {username}{bcolors.ENDC}")
            print(f"{bcolors.WARNING}You can now run: python run.py{bcolors.ENDC}")
            logging.info("Session created for user: %s %s", user.first_name, username)
    except Exception as exc:
        print(f"{bcolors.FAIL}Error creating session: {exc}{bcolors.ENDC}")
        logging.error("Error creating session: %s", exc)
        raise


if __name__ == "__main__":
    asyncio.run(create_session())
