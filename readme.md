# Telegram Chat Organizer

面向个人用户的 Telegram 文件夹整理工具。  
它通过命令行向导收集聊天元信息，调用内置 AI 生成分类草稿，并支持人工审核后再执行写入，避免“黑盒自动改动”风险。

## 1. 功能概览

- 单次 CLI 向导流程（`python run.py`）
- 双 AI Provider：OpenAI / Gemini
- 官方 SDK 接入（`openai`、`google-genai`）
- 草稿双通道审核：
  - `data/groups.draft.json`（结构化草稿）
  - `data/classification_review.csv`（表格审核）
- 两段确认机制：先落盘，再写入 Telegram
- 未分类聊天复核（支持逐条和批量归类）
- 运行文件分目录：`data/`、`logs/`、`sessions/`
- `.gitignore` 默认屏蔽密钥和运行产物

## 2. 运行流程（11 步）

1. 启动检查与配置摘要
2. Session 与 Telegram 连接检查
3. 读取现有文件夹并选择清空策略
4. 加载缓存或重新收集聊天信息
5. 输出分类规则与审阅建议
6. AI 批次分类
7. 生成草稿 JSON + 审核 CSV
8. 选择草稿来源（`json` 或 `csv`）并校验
9. 未分类聊天复核
10. 两段确认
11. 写入 Telegram 并输出报告

## 3. 草稿与审核文件

### 3.1 JSON 草稿

- 文件：`data/groups.draft.json`
- 用途：机器可读、结构稳定，便于程序校验

### 3.2 CSV 审核（可直接编辑）

- 文件：`data/classification_review.csv`
- 用途：便于在 Excel/WPS/Sheets 中批量审核与修改
- 程序支持在步骤 8 选择 `csv` 作为草稿来源，直接从 CSV 重建分类结果

CSV 列定义：

- `status`：`categorized` / `unassigned`
- `folder_id`：目标文件夹 ID（仅 `categorized` 行有效）
- `folder_title`：目标文件夹名称（展示用途）
- `chat_id`：聊天 ID
- `chat_title`：聊天标题
- `chat_type`：聊天类型（GROUP/CHANNEL/...）
- `username`：聊天用户名（可空）
- `reason`：分类原因（可手填）

## 4. 目录结构

```text
telegram-chat-organizer/
├── run.py
├── create_session.py
├── .env.example
├── .gitignore
├── requirements.txt
├── src/
│   └── organizer/
│       ├── __init__.py
│       ├── config.py
│       ├── ai_clients.py
│       ├── classification.py
│       ├── cli_flow.py
│       └── telegram_ops.py
├── data/        # JSON / CSV 运行产物
├── logs/        # run.log
└── sessions/    # *.session
```

## 5. 安装与启动

```bash
python -m venv venv
# Windows PowerShell
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
python run.py
```

## 6. 配置说明（.env）

| 变量 | 说明 | 默认值 |
|---|---|---|
| `API_ID` | Telegram API ID | 无 |
| `API_HASH` | Telegram API HASH | 无 |
| `SESSION_NAME` | Session 名称 | `mili` |
| `SESSIONS_DIR` | Session 存储目录 | `sessions` |
| `DATA_DIR` | JSON/CSV 数据目录 | `data` |
| `LOGS_DIR` | 日志目录 | `logs` |
| `AI_PROVIDER` | `openai` 或 `gemini` | `openai` |
| `AI_MAX_RETRIES` | AI 请求最大重试次数 | `3` |
| `AI_RETRY_BACKOFF_SECONDS` | 重试退避基数 | `1` |
| `AI_CONFIRM_TIMEOUT_SECONDS` | 关键确认超时（秒） | `120` |
| `AI_BATCH_SIZE` | 每批聊天数 | `80` |
| `OPENAI_API_KEY` | OpenAI 密钥 | 无 |
| `OPENAI_BASE_URL` | OpenAI 端点（可含端口） | `https://api.openai.com/v1` |
| `OPENAI_MODEL` | OpenAI 模型 | `gpt-4o-mini` |
| `OPENAI_TIMEOUT_SECONDS` | OpenAI 超时 | `45` |
| `GEMINI_API_KEY` | Gemini 密钥 | 无 |
| `GEMINI_BASE_URL` | Gemini 端点（可含端口） | `https://generativelanguage.googleapis.com` |
| `GEMINI_MODEL` | Gemini 模型 | `gemini-2.0-flash` |
| `GEMINI_TIMEOUT_SECONDS` | Gemini 超时 | `45` |

## 7. CSV 直接分类操作示例

1. 运行到步骤 7，程序生成 `data/classification_review.csv`
2. 打开 CSV，修改如下字段：
   - 将未分类行 `status` 改为 `categorized`
   - 填入目标 `folder_id`
   - 可选填写 `reason`
3. 回到终端，在步骤 8 选择 `csv`
4. 程序会从 CSV 重建 `groups.draft.json` 并继续校验与执行

## 8. 未分类复核（步骤 9）

支持命令：

- `i` 忽略当前聊天
- `m` 手动归类到某个 `folder_id`
- `l` 重新查看文件夹列表
- `q` 结束复核
- 手动归类时支持 `all:<folder_id>`，将剩余聊天批量归类

## 9. 常见问题

### 9.1 Gemini / OpenAI 报 400

- 先确认 `.env` 是否被正确加载
- 检查 key 与 provider 是否匹配
- 检查 `BASE_URL` 与模型名是否可用

### 9.2 Gemini 报 500

- 常见于服务端瞬时错误或 preview 模型高负载
- 建议降低 `AI_BATCH_SIZE`（如 50~80）
- 建议优先使用最新模型（建议 gemini-3.1-pro-preview）

## 10. 许可与责任

本项目用于个人效率提升。请遵守 Telegram 平台条款及当地法律法规。  
请在可控范围内使用自动化能力并做好数据备份。
