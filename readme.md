# Telegram聊天分组整理工具

一个自动化的Telegram聊天分组整理工具，通过AI智能分析聊天内容，帮您将群组和频道自动分类到现有文件夹中。

## ✨ 功能特点

- 🤖 **AI智能分析**：支持任何AI服务（ChatGPT、Claude等）进行聊天分类
- 📁 **自动文件夹整理**：将聊天自动分配到现有Telegram文件夹
- 💾 **数据缓存**：支持聊天信息缓存，避免重复获取
- 🔄 **增量更新**：可选择清空文件夹或在现有基础上添加
- 📋 **详细日志**：完整的运行日志记录所有操作过程
- 🛡️ **数据安全**：所有数据保存在本地，不上传到第三方服务

## 📋 系统要求

- Python 3.8 或更高版本
- Telegram账号
- Telegram API凭据（API_ID 和 API_HASH）

## 🚀 快速开始

### 第一步：获取Telegram API凭据

1. 访问 [https://my.telegram.org/apps](https://my.telegram.org/apps)
2. 使用您的Telegram账号登录
3. 创建新应用，获取 `API_ID` 和 `API_HASH`

### 第二步：下载项目

```bash
git clone <项目地址>
cd telegram-chat-organizer
```

或直接下载ZIP文件并解压到任意目录。

### 第三步：设置Python环境

#### 方案一：Windows PowerShell

```powershell
# 创建虚拟环境
python -m venv venv

# 激活虚拟环境
.\venv\Scripts\Activate.ps1

# 如果执行策略错误，请先运行：
# Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser

# 安装依赖
pip install -r requirements.txt
```

#### 方案二：Windows CMD

```cmd
# 创建虚拟环境
python -m venv venv

# 激活虚拟环境
venv\Scripts\activate.bat

# 安装依赖
pip install -r requirements.txt
```

#### 方案三：Linux/macOS Bash

```bash
# 创建虚拟环境
python3 -m venv venv

# 激活虚拟环境
source venv/bin/activate

# 安装依赖
pip install -r requirements.txt
```

### 第四步：配置代理（可选）

如果您需要通过代理访问Telegram，请在安装依赖前设置代理：

#### Windows PowerShell

```powershell
# 设置HTTP代理
$env:HTTP_PROXY = "http://127.0.0.1:7890"
$env:HTTPS_PROXY = "http://127.0.0.1:7890"

# 或设置SOCKS5代理
$env:HTTP_PROXY = "socks5://127.0.0.1:7890"
$env:HTTPS_PROXY = "socks5://127.0.0.1:7890"
```

#### Windows CMD

```cmd
# 设置HTTP代理
set HTTP_PROXY=http://127.0.0.1:7890
set HTTPS_PROXY=http://127.0.0.1:7890

# 或设置SOCKS5代理
set HTTP_PROXY=socks5://127.0.0.1:7890
set HTTPS_PROXY=socks5://127.0.0.1:7890
```

#### Linux/macOS Bash

```bash
# 设置HTTP代理
export HTTP_PROXY=http://127.0.0.1:7890
export HTTPS_PROXY=http://127.0.0.1:7890

# 或设置SOCKS5代理
export HTTP_PROXY=socks5://127.0.0.1:7890
export HTTPS_PROXY=socks5://127.0.0.1:7890
```

> **注意**：请将 `127.0.0.1:7890` 替换为您实际的代理地址和端口。

### 第五步：配置环境变量

1. 复制 `.env.example` 文件并重命名为 `.env`：

```bash
# Linux/macOS
cp .env.example .env

# Windows
copy .env.example .env
```

2. 编辑 `.env` 文件，填入您的配置：

```env
# Telegram API配置
API_ID=12345678
API_HASH=abcdef1234567890abcdef1234567890
SESSION_NAME=mili
```

**配置说明：**

- `API_ID`：从Telegram开发者平台获取的数字ID
- `API_HASH`：从Telegram开发者平台获取的Hash字符串
- `SESSION_NAME`：会话文件名称（可自定义，建议保持默认）

### 第六步：运行程序

```bash
python run.py
```

首次运行时，程序会：

1. 自动检查并创建session文件
2. 要求您输入手机号码和验证码进行Telegram登录
3. 成功后显示启动信息

## 📖 使用说明

### 基本使用流程

1. **启动程序**：运行 `python run.py`
2. **发送命令**：在Telegram中向您自己发送私聊消息 `/get`
3. **选择模式**：
   - 如果存在 `groups.json` 文件，可选择使用现有数据或重新分析
   - 如果存在 `chats_info.json` 文件，可选择使用缓存或重新收集
4. **文件夹处理**：选择是否清空现有文件夹
5. **AI分类**：按照控制台输出的指导进行AI分类
6. **完成分类**：保存AI结果为 `groups.json` 后回复 `done`
7. **自动执行**：程序自动将聊天分配到对应文件夹

### AI分类步骤详解

当程序输出AI分类指导时，请按以下步骤操作：

#### 步骤1：准备文件

确认以下文件已生成：

- `chats_info.json` - 聊天详细信息
- `folders_info.json` - 文件夹信息

#### 步骤2：复制提示词

从控制台复制完整的提示词（不包含文件内容）

#### 步骤3：使用AI服务

1. **访问AI服务**：打开支持文件上传的AI对话页面
   - ChatGPT
   - Claude
   - 其他支持文件上传的AI服务

2. **粘贴提示词**：将复制的提示词粘贴到对话框

3. **上传文件**：上传以下两个文件
   - `chats_info.json`
   - `folders_info.json`

4. **发送请求**：点击发送，等待AI分析

#### 步骤4：处理AI响应

1. **获取结果**：AI会返回JSON格式的分类结果
2. **清理格式**：如果包含markdown代码块标记（```json），请手动删除
3. **验证格式**：确保是有效的JSON格式

#### 步骤5：保存结果

1. **创建文件**：在项目目录下创建 `groups.json` 文件
2. **复制内容**：将AI返回的纯JSON内容复制到文件中
3. **保存文件**：使用UTF-8编码保存
4. **验证格式**：可使用在线JSON验证器检查格式正确性

#### 步骤6：继续执行

回到程序中回复 `done`，程序将自动读取 `groups.json` 并执行分类

### JSON格式要求

AI返回的结果必须严格按照以下格式：

```json
{
  "categorized": [
    {
      "folder_id": 123,
      "folder_title": "工作群组",
      "chats": [
        {
          "chat_id": 456789,
          "type": "GROUP",
          "reason": "包含工作相关讨论内容"
        }
      ]
    }
  ]
}
```

**字段说明：**

- `folder_id`: 必须是现有文件夹的ID（来自folders_info.json）
- `folder_title`: 文件夹名称（用于显示）
- `chat_id`: 必须是待分类聊天的ID（来自chats_info.json）
- `type`: 聊天类型（GROUP、CHANNEL、SUPERGROUP等）
- `reason`: 分类原因（可选，用于日志）

### 生成的文件说明

运行过程中会生成以下文件：

- **`chats_info.json`**：聊天详细信息（包含标题、类型、描述等）
- **`folders_info.json`**：现有文件夹信息
- **`groups.json`**：AI分类结果
- **`run.log`**：详细运行日志
- **`YYYYMMDD_HHMMSS-groups.json`**：自动备份的历史分类文件

## 🛠️ 高级配置

### 自定义Session名称

如果需要多个账号或避免Session冲突：

```env
SESSION_NAME=my_account_1
```

### 环境变量优先级

程序按以下优先级读取配置：

1. `.env` 文件中的配置
2. 系统环境变量
3. 默认值

## 🐛 故障排除

### 常见问题

#### 1. `ModuleNotFoundError: No module named 'xxx'`

**解决方案**：

```bash
# 确保激活了虚拟环境
source venv/bin/activate  # Linux/macOS
# 或
.\venv\Scripts\Activate.ps1  # Windows PowerShell

# 重新安装依赖
pip install -r requirements.txt
```

#### 2. `API_ID` 或 `API_HASH` 错误

**解决方案**：

- 检查 `.env` 文件中的配置是否正确
- 确认从 [https://my.telegram.org/apps](https://my.telegram.org/apps) 获取的凭据无误
- API_ID 应该是纯数字，API_HASH 应该是32位字符串

#### 3. Session文件创建失败

**解决方案**：

```bash
# 删除可能损坏的session文件
rm *.session

# 重新运行程序
python run.py
```

#### 4. 网络连接问题

**解决方案**：

- 检查网络连接
- 请配置代理（参见上面的代理设置）
- 确认防火墙没有阻止Python程序

#### 5. `Database is locked` 错误

**解决方案**：
程序会自动重试，如果仍然失败：

```bash
# 关闭所有Python进程
# 删除session文件
rm *.session

# 重新运行
python run.py
```

#### 6. JSON格式验证失败

**解决方案**：

- 使用在线JSON验证器检查 `groups.json` 格式
- 确保AI返回的内容不包含markdown代码块标记
- 确保所有chat_id和folder_id都是有效数字

### 调试模式

如需查看详细日志：

```bash
# 查看实时日志
tail -f run.log

# Windows查看日志
Get-Content run.log -Wait
```

### 重置程序

如需完全重置：

```bash
# 删除所有生成的文件
rm *.json *.log *.session

# 重新运行程序
python run.py
```

## 📝 文件结构

```
telegram-chat-organizer/
├── run.py                    # 主程序
├── create_session.py         # Session创建模块
├── requirements.txt          # Python依赖
├── .env.example             # 环境变量示例
├── .env                     # 环境变量配置（需要创建）
├── README.md                # 说明文档
├── venv/                    # 虚拟环境目录
├── *.session               # Telegram会话文件（自动生成）
├── chats_info.json         # 聊天信息（自动生成）
├── folders_info.json       # 文件夹信息（自动生成）
├── groups.json             # 分类结果（AI生成）
└── run.log                 # 运行日志（自动生成）
```

## 💡 使用技巧

1. **首次使用建议**：先在测试环境或备用账号上尝试
2. **定期备份**：重要的groups.json文件会自动备份，建议保留
3. **分批处理**：如果聊天数量很多，可以分批进行分类
4. **AI提示优化**：可以根据需要修改AI提示词以获得更好的分类效果
5. **文件夹规划**：使用前先在Telegram中创建好合适的文件夹结构

## 🔒 隐私和安全

- **本地运行**：所有数据处理都在本地进行
- **Session安全**：Session文件包含登录凭据，请妥善保管
- **API密钥**：请不要分享您的API_ID和API_HASH
- **日志文件**：run.log可能包含聊天标题等信息，请注意保护隐私

## 📞 支持

如果您遇到问题：

1. 首先查看本README的故障排除部分
2. 检查 `run.log` 文件中的错误信息
3. 确保Python版本和依赖包版本符合要求

## 📄 许可证

本项目仅供学习和个人使用，请遵守Telegram的服务条款。

---

**免责声明**：使用本工具时请遵守相关法律法规和平台服务条款。开发者不对使用本工具造成的任何损失承担责任。
