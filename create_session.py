import asyncio
import os
from dotenv import load_dotenv
from telethon.sync import TelegramClient
import logging

# --- 彩色日志 ---
class bcolors:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'

async def create_session():
    """
    Generates a .session file for Telethon authentication.
    """
    print(f"{bcolors.HEADER}--- Telegram Session Generator ---{bcolors.ENDC}")
    
    load_dotenv()

    try:
        api_id = int(os.environ["API_ID"])
        api_hash = os.environ["API_HASH"]
        session_name = os.environ.get("SESSION_NAME", "mili")
    except (KeyError, ValueError) as e:
        print(f"{bcolors.FAIL}Error: Environment variables API_ID or API_HASH are missing or invalid.{bcolors.ENDC}")
        print(f"{bcolors.WARNING}Please ensure your .env file is correctly set up.{bcolors.ENDC}")
        raise e

    # 使用 .session 扩展名创建客户端
    client = TelegramClient(f"{session_name}.session", api_id, api_hash)

    try:
        async with client:
            user = await client.get_me()
            print(f"\n{bcolors.OKGREEN}Session file '{session_name}.session' created successfully!{bcolors.ENDC}")
            print(f"{bcolors.OKBLUE}Logged in as: {user.first_name} (@{user.username}){bcolors.ENDC}")
            print(f"{bcolors.WARNING}You can now run the main bot.py script.{bcolors.ENDC}")
            
            # 记录到日志
            logging.info(f"Session created successfully for user: {user.first_name} (@{user.username})")
            
    except Exception as e:
        print(f"{bcolors.FAIL}Error creating session: {e}{bcolors.ENDC}")
        logging.error(f"Error creating session: {e}")
        raise e

if __name__ == "__main__":
    asyncio.run(create_session())