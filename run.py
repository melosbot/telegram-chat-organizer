import os
import json
import asyncio
import logging
import time
import shutil
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

from telethon import TelegramClient, events
from telethon.tl import functions, types

# --- 配置日志记录到文件和控制台 ---
def setup_logging():
    """设置日志记录到文件和控制台"""
    # 创建日志器
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    
    # 如果已经有处理器，先移除
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
    
    # 文件处理器
    file_handler = logging.FileHandler('run.log', encoding='utf-8')
    file_handler.setLevel(logging.INFO)
    
    # 控制台处理器
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    
    # 设置格式
    formatter = logging.Formatter('[%(asctime)s] [%(levelname)s] - %(message)s', datefmt='%H:%M:%S')
    file_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)
    
    # 添加处理器
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

setup_logging()

# --- 加载环境变量 ---
load_dotenv()

# --- Telegram 配置 ---
API_ID = int(os.getenv("API_ID", 0))
API_HASH = os.getenv("API_HASH")
SESSION_NAME = os.getenv("SESSION_NAME", "mili")

# --- 检查session文件并自动创建 ---
async def ensure_session_exists():
    """检查session文件是否存在，如不存在则创建"""
    session_file = f"{SESSION_NAME}.session"
    
    if not os.path.exists(session_file):
        logging.info("未找到session文件，开始创建session...")
        from create_session import create_session
        await create_session()
        
        if not os.path.exists(session_file):
            raise Exception(f"Session文件 {session_file} 创建失败")
    else:
        logging.info(f"找到现有session文件: {session_file}")

# --- 初始化客户端 ---
def create_client_with_retry(max_retries=3):
    """创建客户端，如果数据库锁定则重试"""
    for attempt in range(max_retries):
        try:
            session_name = f"{SESSION_NAME}_{int(time.time())}" if attempt > 0 else SESSION_NAME
            client = TelegramClient(f"{session_name}.session", API_ID, API_HASH)
            logging.info(f"Telethon client initialized with session: {session_name}")
            return client
        except Exception as e:
            if "database is locked" in str(e) and attempt < max_retries - 1:
                logging.warning(f"Database locked, retrying with new session name... (attempt {attempt + 1})")
                time.sleep(1)
            else:
                logging.error(f"Failed to initialize Telethon client: {e}")
                raise e

# --- 立即初始化客户端（在装饰器使用之前） ---
try:
    client = create_client_with_retry()
except Exception as e:
    logging.error(f"Failed to create client: {e}")
    exit(1)

# --- 等待用户回复的辅助函数 ---
async def wait_for_user_response(event, timeout=30):
    """等待用户回复"""
    try:
        # 创建一个Future来等待回复
        future = asyncio.Future()
        
        # 定义临时事件处理器
        @client.on(events.NewMessage(chats=event.chat_id, from_users=event.sender_id))
        async def temp_handler(response_event):
            if not future.done():
                future.set_result(response_event)
                # 移除临时处理器
                client.remove_event_handler(temp_handler)
        
        # 等待回复或超时
        response = await asyncio.wait_for(future, timeout=timeout)
        return response
        
    except asyncio.TimeoutError:
        # 确保移除处理器
        try:
            client.remove_event_handler(temp_handler)
        except:
            pass
        raise asyncio.TimeoutError()

# --- 文件保存和加载功能 ---

def backup_existing_groups_file():
    """备份现有的groups.json文件"""
    if os.path.exists("groups.json"):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_name = f"{timestamp}-groups.json"
        shutil.copy2("groups.json", backup_name)
        logging.info(f"已备份现有groups.json为: {backup_name}")
        return backup_name
    return None

def save_chats_info(chats_data, filename="chats_info.json"):
    """保存聊天详细信息到JSON文件"""
    try:
        save_data = {
            "timestamp": datetime.now().isoformat(),
            "total_chats": len(chats_data),
            "chats": chats_data
        }
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(save_data, f, ensure_ascii=False, indent=2)
        logging.info(f"Chats info saved to {filename}")
        return True
    except Exception as e:
        logging.error(f"Failed to save chats info: {e}")
        return False

def load_chats_info(filename="chats_info.json"):
    """从JSON文件加载聊天详细信息"""
    try:
        if os.path.exists(filename):
            with open(filename, 'r', encoding='utf-8') as f:
                data = json.load(f)
            logging.info(f"Chats info loaded from {filename}")
            return data.get("chats", [])
        else:
            logging.info(f"File {filename} does not exist")
            return None
    except Exception as e:
        logging.error(f"Failed to load chats info: {e}")
        return None

def save_groups_data(data, filename="groups.json"):
    """保存群组数据到JSON文件，实时写入"""
    try:
        # 备份现有文件
        if filename == "groups.json":
            backup_existing_groups_file()
        
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logging.info(f"Groups data saved to {filename}")
        return True
    except Exception as e:
        logging.error(f"Failed to save groups data: {e}")
        return False

def load_groups_data(filename="groups.json"):
    """从JSON文件加载群组数据"""
    try:
        if os.path.exists(filename):
            with open(filename, 'r', encoding='utf-8') as f:
                data = json.load(f)
            logging.info(f"Groups data loaded from {filename}")
            return data
        else:
            logging.info(f"File {filename} does not exist")
            return None
    except Exception as e:
        logging.error(f"Failed to load groups data: {e}")
        return None

def save_folders_info(folders_data, filename="folders_info.json"):
    """保存文件夹信息到JSON文件"""
    try:
        save_data = {
            "timestamp": datetime.now().isoformat(),
            "total_folders": len(folders_data),
            "folders": [{"id": f["id"], "title": f["title"]} for f in folders_data]
        }
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(save_data, f, ensure_ascii=False, indent=2)
        logging.info(f"Folders info saved to {filename}")
        return True
    except Exception as e:
        logging.error(f"Failed to save folders info: {e}")
        return False

def validate_groups_json(data):
    """验证groups.json的格式是否正确"""
    try:
        if not isinstance(data, dict):
            return False, "数据必须是JSON对象"
        
        if "categorized" not in data:
            return False, "缺少 'categorized' 字段"
        
        categorized = data["categorized"]
        if not isinstance(categorized, list):
            return False, "'categorized' 必须是数组"
        
        for i, folder_update in enumerate(categorized):
            if not isinstance(folder_update, dict):
                return False, f"categorized[{i}] 必须是对象"
            
            required_fields = ["folder_id", "folder_title", "chats"]
            for field in required_fields:
                if field not in folder_update:
                    return False, f"categorized[{i}] 缺少字段 '{field}'"
            
            if not isinstance(folder_update["folder_id"], int):
                return False, f"categorized[{i}].folder_id 必须是数字"
            
            if not isinstance(folder_update["chats"], list):
                return False, f"categorized[{i}].chats 必须是数组"
            
            for j, chat in enumerate(folder_update["chats"]):
                if not isinstance(chat, dict):
                    return False, f"categorized[{i}].chats[{j}] 必须是对象"
                
                if "chat_id" not in chat:
                    return False, f"categorized[{i}].chats[{j}] 缺少字段 'chat_id'"
                
                try:
                    int(chat["chat_id"])
                except (ValueError, TypeError):
                    return False, f"categorized[{i}].chats[{j}].chat_id 必须是有效的数字"
        
        return True, "格式验证通过"
    
    except Exception as e:
        return False, f"验证过程中出错: {str(e)}"

def print_ai_guide(chats_data, existing_folders):
    """在控制台输出AI分类指导"""
    print("\n" + "="*80)
    print("🤖 AI分类指导 - 请按以下步骤操作")
    print("="*80)
    
    print("\n📋 第一步：准备文件")
    print("   以下文件已生成，请准备上传到AI：")
    print("   1. 📄 chats_info.json - 包含所有聊天的详细信息")
    print("   2. 📁 folders_info.json - 包含现有文件夹信息")
    print("   3. ⚠️  groups.json - 需要AI生成的分类结果文件")
    
    print(f"\n📊 数据概览：")
    print(f"   • 现有文件夹数量：{len(existing_folders)} 个")
    print(f"   • 待分类聊天数量：{len(chats_data)} 个")
    
    print(f"\n📁 现有文件夹列表：")
    for folder in existing_folders:
        print(f"   • ID: {folder['id']} - 名称: {folder['title']}")
    
    print("\n" + "="*80)
    print("📝 第二步：复制以下提示词并上传文件到AI")
    print("="*80)
    
    # 构建简化的提示词
    prompt = """你是一个专业的Telegram聊天分类专家。我将提供两个JSON文件：

**文件说明：**
1. folders_info.json - 包含现有文件夹信息
2. chats_info.json - 包含待分类的聊天详细信息

**任务要求：**
请根据聊天的详细信息，将每个聊天分类到最合适的现有文件夹中。

**分类规则：**
1. 仔细分析聊天的名称(title)、简介(description)、用户名(username)和最近消息(last_message)
2. 理解聊天的主要内容和用途
3. 将聊天分配到最相关的现有文件夹
4. 每个聊天只能分配到一个文件夹
5. 只返回需要添加聊天的文件夹
6. 如果某个聊天不适合任何现有文件夹，可以不包含它

**重要：你必须返回严格的JSON格式，不能包含任何markdown标记、解释文字或其他内容。**

**必须严格按照以下JSON格式返回：**

```json
{
  "categorized": [
    {
      "folder_id": 文件夹ID数字,
      "folder_title": "文件夹名称",
      "chats": [
        {
          "chat_id": 聊天ID数字,
          "type": "聊天类型",
          "reason": "分类原因"
        }
      ]
    }
  ]
}
```

**注意事项：**
- folder_id 必须是 folders_info.json 中存在的文件夹ID
- chat_id 必须是 chats_info.json 中存在的聊天ID
- 请返回纯JSON格式，不要包含任何解释或markdown标记
- 可以根据聊天内容的相关性决定是否分类某个聊天

请开始分析并返回分类结果。"""
    
    print("\n🔸 提示词开始 🔸")
    print("-"*80)
    print(prompt)
    print("-"*80)
    print("🔸 提示词结束 🔸")
    
    print("\n" + "="*80)
    print("⚡ 第三步：在AI中操作")
    print("="*80)
    print("1. 访问AI对话页面（ChatGPT、Claude、文心一言等）")
    print("2. 复制上面的提示词到对话框")
    print("3. 上传以下两个文件：")
    print("   📄 chats_info.json")
    print("   📁 folders_info.json")
    print("4. 发送消息，等待AI分析并返回JSON结果")
    print("5. 复制AI返回的JSON内容")
    print("6. 将JSON内容保存为 groups.json 文件")
    
    print("\n" + "="*80)
    print("💾 第四步：保存分类结果")
    print("="*80)
    print("1. 创建新文件：groups.json")
    print("2. 将AI返回的JSON内容完整复制到文件中")
    print("3. 确保JSON格式正确（去除markdown代码块标记）")
    print("4. 保存文件，确保使用UTF-8编码")
    print("5. 回到程序中回复 'done' 继续执行分类")
    
    print("\n📄 groups.json 正确格式示例：")
    example_data = {
        "categorized": [
            {
                "folder_id": existing_folders[0]["id"] if existing_folders else 1,
                "folder_title": existing_folders[0]["title"] if existing_folders else "示例文件夹",
                "chats": [
                    {
                        "chat_id": chats_data[0]["chat_id"] if chats_data else 123456789,
                        "type": chats_data[0]["type"] if chats_data else "GROUP",
                        "reason": "根据聊天内容判断适合此文件夹"
                    }
                ]
            }
        ]
    }
    print(json.dumps(example_data, ensure_ascii=False, indent=2))
    
    print("\n" + "="*80)
    print("🎯 重要注意事项")
    print("="*80)
    print("✅ 支持的AI服务：")
    print("   • ChatGPT、Claude、其他支持文件上传的AI服务")
    print("")
    print("⚠️  操作要点：")
    print("   • 确保上传两个JSON文件：chats_info.json 和 folders_info.json")
    print("   • AI返回结果如果包含```json标记，请手动删除")
    print("   • 文件夹ID和聊天ID必须是有效数字")
    print("   • 保存groups.json时使用UTF-8编码")
    print("   • 可以使用在线JSON验证器检查格式")
    print("")
    print("🔧 文件位置：")
    current_path = os.path.abspath(".")
    print(f"   • 当前目录：{current_path}")
    print(f"   • chats_info.json：{os.path.join(current_path, 'chats_info.json')}")
    print(f"   • folders_info.json：{os.path.join(current_path, 'folders_info.json')}")
    print(f"   • 需要创建：{os.path.join(current_path, 'groups.json')}")
    print("="*80)
    
    # 额外提示：检查文件是否存在
    print("\n🔍 文件检查：")
    if os.path.exists("chats_info.json"):
        print("   ✅ chats_info.json 已生成")
    else:
        print("   ❌ chats_info.json 不存在")
    
    if os.path.exists("folders_info.json"):
        print("   ✅ folders_info.json 已生成")
    else:
        print("   ❌ folders_info.json 不存在")
    
    if os.path.exists("groups.json"):
        print("   ⚠️  groups.json 已存在（将被备份）")
    else:
        print("   📝 groups.json 待创建")

# --- 获取详细聊天信息 ---

async def get_detailed_chat_info(dialog):
    """获取聊天的详细信息"""
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
        "participant_count": 0,
        "is_verified": False,
        "is_scam": False
    }
    
    try:
        # 确定聊天类型
        if isinstance(entity, types.User):
            chat_info["type"] = "BOT" if entity.bot else "PRIVATE"
            chat_info["username"] = entity.username or ""
        elif isinstance(entity, types.Channel):
            chat_info["type"] = "CHANNEL" if entity.broadcast else "SUPERGROUP"
            chat_info["username"] = entity.username or ""
            chat_info["is_verified"] = getattr(entity, 'verified', False)
            chat_info["is_scam"] = getattr(entity, 'scam', False)
        elif isinstance(entity, types.Chat):
            chat_info["type"] = "GROUP"
        
        # 获取简介/关于信息
        if hasattr(entity, 'about') and entity.about:
            chat_info["about"] = entity.about
        
        # 尝试获取完整信息（对于频道和群组）
        if chat_info["type"] in ["CHANNEL", "SUPERGROUP", "GROUP"]:
            try:
                if isinstance(entity, types.Channel):
                    full_chat = await client(functions.channels.GetFullChannelRequest(entity))
                    if hasattr(full_chat, 'full_chat'):
                        full_info = full_chat.full_chat
                        if hasattr(full_info, 'about') and full_info.about:
                            chat_info["description"] = full_info.about
                        if hasattr(full_info, 'participants_count'):
                            chat_info["participant_count"] = full_info.participants_count
                elif isinstance(entity, types.Chat):
                    full_chat = await client(functions.messages.GetFullChatRequest(entity.id))
                    if hasattr(full_chat, 'full_chat'):
                        full_info = full_chat.full_chat
                        if hasattr(full_info, 'about') and full_info.about:
                            chat_info["description"] = full_info.about
                        if hasattr(full_info, 'participants_count'):
                            chat_info["participant_count"] = full_info.participants_count
            except Exception as e:
                logging.debug(f"Could not get full info for {chat_info['title']}: {e}")
        
        # 获取最后一条消息信息
        if dialog.message:
            message = dialog.message
            if hasattr(message, 'message') and message.message:
                chat_info["last_message"] = message.message[:300]  # 限制长度
            elif hasattr(message, 'action'):
                # 处理系统消息
                action = message.action
                if hasattr(action, '__class__'):
                    chat_info["last_message"] = f"[系统消息: {action.__class__.__name__}]"
            
            if hasattr(message, 'date'):
                chat_info["last_message_date"] = message.date.strftime("%Y-%m-%d %H:%M")
        
        # 如果description为空，使用about
        if not chat_info["description"] and chat_info["about"]:
            chat_info["description"] = chat_info["about"]
            
    except Exception as e:
        logging.warning(f"Error getting detailed info for chat {dialog.id}: {e}")
    
    return chat_info

# --- 文件夹管理逻辑 ---

async def get_existing_folders():
    """获取现有的文件夹列表"""
    logging.info("Fetching existing folders...")
    folders = []
    
    try:
        existing_filters = await client(functions.messages.GetDialogFiltersRequest())
        for filter_obj in existing_filters.filters:
            if hasattr(filter_obj, 'id'):
                # 处理title - 保留原始对象用于后续更新，但提取文本用于显示和AI处理
                title_obj = filter_obj.title
                title_text = ""
                
                if hasattr(title_obj, 'text'):
                    # 如果是TextWithEntities对象，提取text属性
                    title_text = title_obj.text
                elif isinstance(title_obj, str):
                    # 如果是字符串
                    title_text = title_obj
                else:
                    # 其他情况，转换为字符串
                    title_text = str(title_obj)
                
                # 获取文件夹中现有的聊天
                existing_peers = []
                if hasattr(filter_obj, 'include_peers'):
                    existing_peers = filter_obj.include_peers or []
                
                folders.append({
                    "id": filter_obj.id,
                    "title": title_text,  # 用于显示和AI处理的文本
                    "title_obj": title_obj,  # 保留原始对象用于更新
                    "existing_peers": existing_peers,
                    "pinned_peers": getattr(filter_obj, 'pinned_peers', []),
                    "exclude_peers": getattr(filter_obj, 'exclude_peers', []),
                    "filter_obj": filter_obj  # 保存完整的filter对象以便后续使用
                })
                logging.info(f"Found folder: {title_text} (ID: {filter_obj.id}) with {len(existing_peers)} chats")
    except Exception as e:
        logging.error(f"Could not get existing filters: {e}")
    
    return folders

async def clear_existing_folders(existing_folders: list):
    """清空现有文件夹中的大部分聊天，但保留一个以避免错误"""
    logging.info("Clearing existing folders (keeping one chat per folder)...")
    
    for folder in existing_folders:
        folder_id = folder.get("id")
        folder_title = folder.get("title", "Unknown")
        existing_peers = folder.get("existing_peers", [])
        
        if len(existing_peers) <= 1:
            logging.info(f"Folder '{folder_title}' has {len(existing_peers)} chats. Skipping clear.")
            continue
        
        try:
            # 获取原始filter对象的其他属性
            original_filter = folder.get("filter_obj")
            
            # 处理原始filter的title - 使用保存的原始title对象
            original_title = folder.get("title_obj") or (original_filter.title if original_filter else None)
            if original_title is None or not hasattr(original_title, '_bytes'):
                # 如果没有原始title或不是正确的TLObject，创建新的TextWithEntities
                title_text = folder.get("title", "Unknown")
                original_title = types.TextWithEntities(
                    text=title_text,
                    entities=[]
                )
            
            # 保留第一个聊天，移除其他的
            kept_peers = existing_peers[:1]  # 只保留第一个
            removed_count = len(existing_peers) - 1
            
            # 创建更新的 DialogFilter 对象（保留一个聊天）
            cleared_filter = types.DialogFilter(
                id=folder_id,
                title=original_title,  # 使用TextWithEntities对象
                pinned_peers=[],  # 清空置顶聊天
                include_peers=kept_peers,  # 保留一个聊天
                exclude_peers=folder.get("exclude_peers", []),  # 保留排除的聊天
                contacts=getattr(original_filter, 'contacts', False) if original_filter else False,
                non_contacts=getattr(original_filter, 'non_contacts', False) if original_filter else False,
                groups=getattr(original_filter, 'groups', False) if original_filter else False,
                broadcasts=getattr(original_filter, 'broadcasts', False) if original_filter else False,
                bots=getattr(original_filter, 'bots', False) if original_filter else False,
                exclude_muted=getattr(original_filter, 'exclude_muted', False) if original_filter else False,
                exclude_read=getattr(original_filter, 'exclude_read', False) if original_filter else False,
                exclude_archived=getattr(original_filter, 'exclude_archived', False) if original_filter else False,
                emoticon=getattr(original_filter, 'emoticon', None) if original_filter else None
            )
            
            # 发送更新请求
            await client(functions.messages.UpdateDialogFilterRequest(
                id=folder_id,
                filter=cleared_filter
            ))
            
            logging.info(f"Successfully cleared folder '{folder_title}' (removed {removed_count} chats, kept 1)")
            
            # 更新folder对象中的existing_peers为保留的聊天
            folder["existing_peers"] = kept_peers
            
            # 添加延迟以避免请求过快
            await asyncio.sleep(0.3)
            
        except Exception as e:
            logging.error(f"Error clearing folder '{folder_title}' (ID: {folder_id}): {e}", exc_info=True)
            await asyncio.sleep(1)

async def update_folders_with_categorization(categorized_data: dict, dialog_map: dict, existing_folders: list, folders_were_cleared: bool = False):
    """根据AI分类结果更新现有文件夹"""
    logging.info("Starting folder updates based on AI categorization.")
    
    # 创建文件夹ID到文件夹对象的映射
    folder_map = {f["id"]: f for f in existing_folders}
    
    for folder_update in categorized_data.get("categorized", []):
        folder_id = folder_update.get("folder_id")
        chats_to_add = folder_update.get("chats", [])
        folder_title = folder_update.get("folder_title", "Unknown")
        
        if folder_id not in folder_map:
            logging.warning(f"Folder ID {folder_id} not found in existing folders. Skipping.")
            continue
        
        folder = folder_map[folder_id]
        
        try:
            # 收集新的对话的 InputPeer
            new_peers = []
            for chat in chats_to_add:
                try:
                    chat_id = int(chat["chat_id"])
                    reason = chat.get("reason", "")
                    if dialog := dialog_map.get(chat_id):
                        input_peer = dialog.input_entity
                        if input_peer:
                            new_peers.append(input_peer)
                            logging.info(f"Adding chat {dialog.name} to folder {folder_title}: {reason}")
                        else:
                            logging.warning(f"No input_entity for chat_id {chat_id}")
                    else:
                        logging.warning(f"Chat_id {chat_id} not found in dialog_map. Skipping.")
                except (ValueError, TypeError) as e:
                    logging.warning(f"Invalid chat_id format: {chat.get('chat_id')}. Error: {e}")
            
            if not new_peers:
                logging.info(f"No new chats to add to folder '{folder_title}'. Skipping update.")
                continue
            
            # 获取现有的peers
            existing_peers = folder.get("existing_peers", [])
            
            if folders_were_cleared:
                # 如果文件夹被清理过，existing_peers已经只剩一个或为空
                # 直接合并即可
                all_peers = existing_peers + new_peers
            else:
                # 如果文件夹没有被清理，需要去重
                # 创建一个集合来跟踪已有的peer ID，避免重复
                existing_peer_ids = set()
                for peer in existing_peers:
                    if hasattr(peer, 'channel_id'):
                        existing_peer_ids.add(peer.channel_id)
                    elif hasattr(peer, 'chat_id'):
                        existing_peer_ids.add(peer.chat_id)
                    elif hasattr(peer, 'user_id'):
                        existing_peer_ids.add(peer.user_id)
                
                # 只添加不重复的新peers
                unique_new_peers = []
                for peer in new_peers:
                    peer_id = None
                    if hasattr(peer, 'channel_id'):
                        peer_id = peer.channel_id
                    elif hasattr(peer, 'chat_id'):
                        peer_id = peer.chat_id
                    elif hasattr(peer, 'user_id'):
                        peer_id = peer.user_id
                    
                    if peer_id and peer_id not in existing_peer_ids:
                        unique_new_peers.append(peer)
                        existing_peer_ids.add(peer_id)
                
                if not unique_new_peers:
                    logging.info(f"All chats already exist in folder '{folder_title}'. Skipping update.")
                    continue
                
                all_peers = existing_peers + unique_new_peers
            
            # 获取原始filter对象的其他属性
            original_filter = folder.get("filter_obj")
            
            # 处理原始filter的title - 使用保存的原始title对象
            original_title = folder.get("title_obj") or (original_filter.title if original_filter else None)
            if original_title is None or not hasattr(original_title, '_bytes'):
                # 如果没有原始title或不是正确的TLObject，创建新的TextWithEntities
                title_text = folder.get("title", "Unknown")
                original_title = types.TextWithEntities(
                    text=title_text,
                    entities=[]
                )
            
            # 创建更新的 DialogFilter 对象
            updated_filter = types.DialogFilter(
                id=folder_id,
                title=original_title,  # 使用TextWithEntities对象
                pinned_peers=folder.get("pinned_peers", []),
                include_peers=all_peers,
                exclude_peers=folder.get("exclude_peers", []),
                contacts=getattr(original_filter, 'contacts', False) if original_filter else False,
                non_contacts=getattr(original_filter, 'non_contacts', False) if original_filter else False,
                groups=getattr(original_filter, 'groups', False) if original_filter else False,
                broadcasts=getattr(original_filter, 'broadcasts', False) if original_filter else False,
                bots=getattr(original_filter, 'bots', False) if original_filter else False,
                exclude_muted=getattr(original_filter, 'exclude_muted', False) if original_filter else False,
                exclude_read=getattr(original_filter, 'exclude_read', False) if original_filter else False,
                exclude_archived=getattr(original_filter, 'exclude_archived', False) if original_filter else False,
                emoticon=getattr(original_filter, 'emoticon', None) if original_filter else None
            )
            
            # 发送更新请求
            await client(functions.messages.UpdateDialogFilterRequest(
                id=folder_id,
                filter=updated_filter
            ))
            
            added_count = len(new_peers) if folders_were_cleared else len(unique_new_peers if not folders_were_cleared else new_peers)
            logging.info(f"Successfully updated folder '{folder_title}' with {added_count} new chats.")
            
            # 添加延迟以避免请求过快
            await asyncio.sleep(0.5)
            
        except Exception as e:
            logging.error(f"Error updating folder '{folder_title}' (ID: {folder_id}): {e}", exc_info=True)
            await asyncio.sleep(1)

# --- 主事件处理器 ---

@client.on(events.NewMessage(pattern='/get'))
async def get_dialogues_handler(event: events.NewMessage.Event):
    """处理 /get 命令，开始整理流程"""
    if not event.is_private:
        return

    try:
        # 检查是否存在groups.json文件
        existing_data = load_groups_data()
        if existing_data:
            await event.reply("📁 **发现现有的分类数据！**\n\n发现 `groups.json` 文件，是否要使用现有数据直接执行分类？\n\n回复 `yes` 使用现有数据，回复 `no` 重新分析")
            
            # 等待用户回复
            try:
                response = await wait_for_user_response(event, timeout=30)
                
                if response.text.lower() in ['yes', 'y', '是', '确定']:
                    await event.reply("✅ **使用现有数据执行分类...**")
                    
                    # 获取现有文件夹和对话映射
                    existing_folders = await get_existing_folders()
                    if not existing_folders:
                        await event.reply("❌ **错误**\n\n未找到任何现有文件夹。")
                        return
                    
                    # 询问是否清空现有文件夹
                    await event.reply("🗑️ **清空文件夹**\n\n是否要在重新分类前清空所有现有文件夹中的聊天？\n\n回复 `yes` 清空后重新分类，回复 `no` 在现有基础上添加")
                    
                    folders_were_cleared = False
                    try:
                        clear_response = await wait_for_user_response(event, timeout=30)
                        
                        if clear_response.text.lower() in ['yes', 'y', '是', '确定']:
                            await event.reply("🗑️ **正在清空现有文件夹...**")
                            await clear_existing_folders(existing_folders)
                            await event.reply("✅ **文件夹已清空**")
                            folders_were_cleared = True
                    except asyncio.TimeoutError:
                        await event.reply("⏰ **超时**\n\n将在现有基础上添加聊天...")
                    
                    # 获取对话映射
                    dialog_map = {}
                    dialogs = await client.get_dialogs()
                    for dialog in dialogs:
                        dialog_map[dialog.id] = dialog
                    
                    # 直接执行分类
                    await update_folders_with_categorization(existing_data, dialog_map, existing_folders, folders_were_cleared)
                    
                    # 生成报告
                    report_lines = []
                    total_added = 0
                    for folder_update in existing_data.get("categorized", []):
                        folder_title = folder_update.get("folder_title", "Unknown")
                        chats = folder_update.get("chats", [])
                        if chats:
                            chat_count = len(chats)
                            total_added += chat_count
                            report_lines.append(f"  • {folder_title}: +{chat_count} 个聊天")
                    
                    if report_lines:
                        report = f"✅ **分类完成！**\n\n**共添加了 {total_added} 个聊天到文件夹：**\n" + "\n".join(report_lines)
                    else:
                        report = "✅ **执行完成！**\n\n没有需要更新的文件夹。"
                    
                    await event.reply(report)
                    return
            except asyncio.TimeoutError:
                await event.reply("⏰ **超时**\n\n未收到回复，将重新开始分析...")
        
        await event.reply("✅ **任务开始！**\n\n- 正在获取您的现有文件夹...\n- 正在获取您的所有对话...\n- 将生成AI分类指导...\n\n请耐心等待。")
        
        # 1. 获取现有文件夹
        existing_folders = await get_existing_folders()
        
        if not existing_folders:
            await event.reply("❌ **错误**\n\n未找到任何现有文件夹。请先手动创建至少一个文件夹。")
            return
        
        # 保存文件夹信息
        save_folders_info(existing_folders)
        
        folders_report = "\n".join([f"  • {f['title']} (ID: {f['id']})" for f in existing_folders])
        await event.reply(f"📁 **找到 {len(existing_folders)} 个现有文件夹：**\n{folders_report}\n\n正在分析您的聊天...")
        
        # 询问是否清空现有文件夹
        await event.reply("🗑️ **清空文件夹**\n\n是否要在重新分类前清空所有现有文件夹中的聊天？\n\n回复 `yes` 清空后重新分类，回复 `no` 在现有基础上添加")
        
        clear_folders = False
        try:
            clear_response = await wait_for_user_response(event, timeout=30)
            
            if clear_response.text.lower() in ['yes', 'y', '是', '确定']:
                clear_folders = True
                await event.reply("🗑️ **正在清空现有文件夹...**")
                await clear_existing_folders(existing_folders)
                await event.reply("✅ **文件夹已清空，开始重新分类**")
            else:
                await event.reply("✅ **将在现有基础上添加聊天**")
        except asyncio.TimeoutError:
            await event.reply("⏰ **超时**\n\n将在现有基础上添加聊天...")
        
        # 2. 检查是否存在聊天信息缓存
        existing_chats_info = load_chats_info()
        chats_for_ai = []
        
        if existing_chats_info:
            await event.reply("💾 **发现聊天信息缓存！**\n\n发现 `chats_info.json` 文件，是否要使用缓存的聊天信息？\n\n回复 `yes` 使用缓存，回复 `no` 重新收集")
            
            try:
                response = await wait_for_user_response(event, timeout=30)
                
                if response.text.lower() in ['yes', 'y', '是', '确定']:
                    chats_for_ai = existing_chats_info
                    await event.reply(f"✅ **使用缓存的 {len(chats_for_ai)} 个聊天信息**")
            except asyncio.TimeoutError:
                await event.reply("⏰ **超时**\n\n将重新收集聊天信息...")
        
        # 3. 如果没有缓存或用户选择重新收集，则获取所有对话并收集详细信息
        if not chats_for_ai:
            dialog_map = {}
            
            dialogs = await client.get_dialogs()
            logging.info(f"Found {len(dialogs)} dialogues.")
            
            progress_message = await event.reply("🔍 **正在收集聊天详细信息...**\n\n这可能需要一些时间，请耐心等待。")
            
            processed_count = 0
            for dialog in dialogs:
                entity = dialog.entity
                if not entity: 
                    continue

                # 存储完整的dialog对象
                dialog_map[dialog.id] = dialog

                # 只处理群组和频道
                if isinstance(entity, types.User):
                    chat_type = "BOT" if entity.bot else "PRIVATE"
                elif isinstance(entity, (types.Chat, types.Channel)):
                    chat_type = "CHANNEL" if getattr(entity, 'broadcast', False) else "GROUP"
                else:
                    continue
                
                if chat_type in ["GROUP", "CHANNEL", "SUPERGROUP"]:
                    # 获取详细信息
                    chat_info = await get_detailed_chat_info(dialog)
                    chats_for_ai.append(chat_info)
                    processed_count += 1
                    
                    # 每处理10个聊天更新一次进度
                    if processed_count % 10 == 0:
                        await progress_message.edit(f"🔍 **正在收集聊天详细信息...**\n\n已处理: {processed_count} 个聊天")
                    
                    # 添加小延迟避免请求过快
                    await asyncio.sleep(0.1)

            await progress_message.delete()
            
            # 保存聊天信息到文件
            if save_chats_info(chats_for_ai):
                await event.reply(f"💾 **聊天信息已保存到 chats_info.json**\n\n共收集了 {len(chats_for_ai)} 个聊天的详细信息")
        else:
            # 如果使用了缓存，需要重新构建dialog_map
            dialog_map = {}
            dialogs = await client.get_dialogs()
            for dialog in dialogs:
                dialog_map[dialog.id] = dialog
        
        logging.info(f"Processed dialogues: Found {len(chats_for_ai)} groups/channels to categorize.")
        
        if not chats_for_ai:
            await event.reply("️🤷‍♂️ 未找到任何群组或频道来进行分类。")
            return

        # 4. 输出AI分类指导
        await event.reply("🤖 **AI分类指导已生成！**\n\n请查看控制台输出，按照指导使用AI进行分类。\n\n分类完成后回复 `done` 继续执行。")
        
        # 在控制台输出详细指导
        print_ai_guide(chats_for_ai, existing_folders)
        
        # 等待用户手动完成分类
        try:
            done_response = await wait_for_user_response(event, timeout=1800)  # 30分钟超时
            
            if done_response.text.lower() not in ['done', 'ok', '完成', '好了']:
                await event.reply("❌ **操作取消**\n\n请回复 `done` 来确认分类完成。")
                return
            
            # 重新加载groups.json
            manual_data = load_groups_data()
            if not manual_data:
                await event.reply("❌ **错误**\n\n未找到groups.json文件。请确保已按照指导生成该文件。")
                return
            
            # 验证格式
            is_valid, error_msg = validate_groups_json(manual_data)
            if not is_valid:
                await event.reply(f"❌ **groups.json格式错误**\n\n{error_msg}\n\n请修正后重新运行。")
                return
            
            await event.reply("✅ **格式验证通过，开始执行分类...**")
            
        except asyncio.TimeoutError:
            await event.reply("⏰ **超时**\n\n操作已取消，请重新运行命令。")
            return
        
        # 5. 更新文件夹
        progress_message = await event.reply("📝 **正在更新文件夹...**")
        await update_folders_with_categorization(manual_data, dialog_map, existing_folders, clear_folders)
        
        # 6. 生成详细报告
        report_lines = []
        total_added = 0
        for folder_update in manual_data.get("categorized", []):
            folder_title = folder_update.get("folder_title", "Unknown")
            chats = folder_update.get("chats", [])
            if chats:
                chat_count = len(chats)
                total_added += chat_count
                # 显示前3个聊天的名称作为示例
                chat_names = []
                for chat in chats[:3]:
                    chat_id = chat.get("chat_id")
                    if chat_id and chat_id in dialog_map:
                        chat_names.append(dialog_map[chat_id].name)
                
                example_text = ""
                if chat_names:
                    example_text = f" (如: {', '.join(chat_names)}"
                    if len(chats) > 3:
                        example_text += f" 等{len(chats)}个)"
                    else:
                        example_text += ")"
                
                report_lines.append(f"  • {folder_title}: +{chat_count} 个聊天{example_text}")
        
        if report_lines:
            clear_text = "（已清空原有内容）" if clear_folders else "（在原有基础上添加）"
            report = f"✅ **整理完成！** {clear_text}\n\n**使用手动分类，共添加了 {total_added} 个聊天到文件夹：**\n" + "\n".join(report_lines)
            report += f"\n\n📁 相关文件已保存："
            report += f"\n  • chats_info.json - 聊天详细信息"
            report += f"\n  • folders_info.json - 文件夹信息"
            report += f"\n  • groups.json - 分类结果"
            report += f"\n  • run.log - 详细运行日志"
        else:
            report = "✅ **分析完成！**\n\n没有需要更新的文件夹，所有聊天可能已经在合适的文件夹中。"
        
        await progress_message.edit(report)

    except Exception as e:
        error_message = f"❌ **发生错误**\n\n`{type(e).__name__}: {e}`"
        logging.error(f"An error occurred during /get command processing: {e}", exc_info=True)
        await event.reply(error_message)

# --- 启动 ---
async def main():
    """主函数，启动并运行客户端"""
    logging.info("Bot starting...")
    
    try:
        # 确保session存在
        await ensure_session_exists()
        
        await client.start()
        me = await client.get_me()
        logging.info(f"Bot started successfully for @{me.username}. Use /get in a private chat to start.")
        await client.run_until_disconnected()
    except Exception as e:
        logging.error(f"Failed to start bot: {e}")
        raise

if __name__ == "__main__":
    asyncio.run(main())