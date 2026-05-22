# Telegram Chat Organizer

面向个人用户的 Telegram 文件夹整理工具。  
它通过命令行向导收集聊天元信息，调用内置 AI 生成分类草稿，并支持人工审核后再执行写入，避免“黑盒自动改动”风险。

## 1. 功能概览

- 单次 CLI 向导流程（`python run.py`）
- 双 AI Provider：OpenAI / Gemini
- 官方 SDK 接入（`openai`、`google-genai`）
- 文件夹说明规则：`data/folder_rules.json`
- CSV 优先的草稿审核：
  - `data/classification_review.csv`（默认人工审核入口）
  - `data/groups.draft.json`（程序校验用结构化草稿）
- 分类记忆：`data/classification_memory.csv` 会保存审核后的已分类聊天，下次优先读取，减少重复手工分类
- 文件审核自动应用：修改 CSV 后继续即可重建草稿
- 执行前预览与两段确认：先落盘，再写入 Telegram
- 未分类聊天复核（支持逐条和批量归类）
- 运行文件分目录：`data/`、`logs/`、`sessions/`
- `.gitignore` 默认屏蔽密钥和运行产物

## 2. 运行流程（7 个阶段）

1. 选择整理目标：增量补充、重新整理、只生成草稿、从草稿继续
2. 扫描账号状态：读取文件夹，加载缓存或重新扫描聊天
3. 补全文件夹说明：生成/更新 `data/folder_rules.json`
4. 生成分类建议：AI 按文件夹说明和聊天上下文生成草稿
5. 审核建议：默认编辑 CSV，或在终端处理未分类聊天
6. 执行前预览：查看每个文件夹将新增多少聊天，再选择增量或重建
7. 写入与报告：最终确认后写入 Telegram 并输出运行文件路径

## 3. 文件夹说明与审核文件

### 3.1 文件夹说明

- 文件：`data/folder_rules.json`
- 用途：告诉 AI 每个 Telegram 文件夹的真实含义，减少只看标题造成的误判
- 程序会根据当前 Telegram 文件夹自动生成模板，并保留你已经写过的说明

示例：

```json
{
  "version": 1,
  "folders": [
    {
      "folder_id": 1,
      "folder_title": "技术",
      "auto_classify": true,
      "description": "Python、AI、后端、开源项目相关群组和频道",
      "include_keywords": ["python", "openai", "github"],
      "exclude_keywords": ["招聘", "广告", "币圈"],
      "notes": "偏工程技术，不包含纯资讯频道",
      "missing_from_telegram": false
    }
  ]
}
```

如果某个 Telegram 文件夹不希望被自动分类或写入，可以设置：

```json
"auto_classify": false
```

程序不会把聊天自动分到该文件夹；执行“清空重建”时也只会处理启用的分类目标。

### 3.2 CSV 审核（默认编辑）

- 文件：`data/classification_review.csv`
- 用途：便于在 Excel/WPS/Sheets 中批量审核与修改，是默认人工入口
- 文件审核模式下，程序会检测 CSV 是否被修改；修改后继续即可自动重建草稿
- 人工归类未分类行时，可以只填 `folder_id`，或填精确的 `folder_title`
- 人工移除分类行时，可以清空 `folder_id`，或把 `status` 改为 `ignore` / `skip` / `remove`

CSV 列定义：

- `status`：`categorized` / `unassigned`
- `folder_id`：目标文件夹 ID（仅 `categorized` 行有效）
- `folder_title`：目标文件夹名称（展示用途）
- `chat_id`：聊天 ID
- `chat_title`：聊天标题
- `chat_type`：聊天类型（GROUP/CHANNEL/...）
- `username`：聊天用户名（可空）
- `description`：群/频道简介摘要
- `last_message`：频道最后一条消息摘要（如已读取）
- `recent_messages`：最近消息摘要（如已读取）
- `confidence`：AI 置信度（high / medium / low，可空）
- `evidence`：AI 给出的可核验证据短语
- `reason`：分类原因（可手填）

### 3.3 JSON 草稿

- 文件：`data/groups.draft.json`
- 用途：机器可读、结构稳定，便于程序校验
- 通常不需要手工编辑；CSV 修改后会自动重建该文件

### 3.4 分类记忆

- 文件：`data/classification_memory.csv`
- 用途：保存审核完成后的聊天归类，下次运行时先读取这份记忆，已命中的聊天不再交给 AI 重复判断
- 如果想让某个聊天重新交给 AI，删除对应行即可
- `include_keywords` 更适合放品牌名、项目名、别名和硬边界；主要分类依据仍应写在 `description` 和 `notes`

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
| `AI_CONCURRENCY` | AI 分类批次并发数；接口不稳定时建议降到 1-2 | `1` |
| `OPENAI_REASONING_EFFORT` | OpenAI 推理强度；留空禁用，不兼容时自动降级重试 | `high` |
| `OPENAI_VERBOSITY` | OpenAI 输出详细度；留空禁用，不兼容时自动降级重试 | `medium` |
| `GEMINI_THINKING_BUDGET` | Gemini thinking token 预算；`0` 表示禁用 | `2048` |
| `GEMINI_INCLUDE_THOUGHTS` | 是否请求 Gemini 返回 thoughts；默认关闭，只影响内部思考预算 | `false` |
| `TELEGRAM_RECENT_MESSAGE_LIMIT` | 每个聊天最多读取最近消息数；默认不读取，避免短期话题污染分类 | `0` |
| `TELEGRAM_CHANNEL_RECENT_MESSAGE_LIMIT` | 频道最多读取最近消息数；频道最后一条可辅助判断发布风格 | `1` |
| `TELEGRAM_SCAN_DELAY_SECONDS` | 扫描每个聊天后的等待秒数 | `1` |
| `TELEGRAM_FETCH_FULL_INFO` | 是否读取频道/群完整简介与人数 | `false` |
| `TELEGRAM_CACHE_SAVE_EVERY` | 扫描中每多少条保存一次缓存 | `10` |
| `OPENAI_API_KEY` | OpenAI 密钥 | 无 |
| `OPENAI_BASE_URL` | OpenAI 端点（可含端口） | `https://api.openai.com/v1` |
| `OPENAI_MODEL` | OpenAI 模型 | `gpt-4o-mini` |
| `OPENAI_TIMEOUT_SECONDS` | OpenAI 超时 | `45` |
| `GEMINI_API_KEY` | Gemini 密钥 | 无 |
| `GEMINI_BASE_URL` | Gemini 端点（可含端口） | `https://generativelanguage.googleapis.com` |
| `GEMINI_MODEL` | Gemini 模型 | `gemini-2.0-flash` |
| `GEMINI_TIMEOUT_SECONDS` | Gemini 超时 | `45` |

## 7. CSV 直接分类操作示例

1. 运行到“审核建议”阶段，程序生成 `data/classification_review.csv`
2. 打开 CSV，修改如下字段：
   - 对未分类行填入目标 `folder_id`，`status` 可以保持 `unassigned`
   - 或填入精确的 `folder_title`
   - 可选填写 `reason`
3. 回到终端继续
4. 程序检测到 CSV 已修改后，会自动重建 `groups.draft.json` 并继续校验

## 8. 未分类复核

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
- 建议优先使用当前账号可用的高质量模型；速度优先时可用 flash 系列

### 9.3 Telethon session database is locked

- 通常是另一个 `python run.py` / `create_session.py` 仍在使用同一个 `sessions/*.session`
- 程序会创建 `sessions/<SESSION_NAME>.run.lock` 防止同一工具重复打开同一个 session
- 如果确认没有残留进程，等待几秒后重试；不要直接删除 `.session`，否则需要重新登录 Telegram

## 10. 许可与责任

本项目用于个人效率提升。请遵守 Telegram 平台条款及当地法律法规。  
请在可控范围内使用自动化能力并做好数据备份。
