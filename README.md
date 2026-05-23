# Telegram Chat Organizer

> 通过 CLI 向导收集 Telegram 聊天信息，让 AI 生成分类草稿，人工审核后再写入文件夹。
> 强调"先审后写"，避免黑盒自动改动。

---

## 目录

1. [快速开始](#1-快速开始)
2. [核心流程](#2-核心流程)
3. [环境变量](#3-环境变量)
   - [3.1 必填](#31-必填)
   - [3.2 选填（可调可不调）](#32-选填可调可不调)
4. [运行产物](#4-运行产物)
5. [常用操作](#5-常用操作)
6. [项目结构](#6-项目结构)
7. [常见问题](#7-常见问题)
8. [开发与测试](#8-开发与测试)
9. [许可与责任](#9-许可与责任)

---

## 1. 快速开始

```bash
# 1. 准备环境
python -m venv .venv
.venv/bin/pip install -r requirements.txt

# 2. 配置最少必填项（见 §3.1）
cp .env.example .env
# 编辑 .env，至少填好 API_ID / API_HASH / OPENAI_API_KEY 或 GEMINI_API_KEY

# 3. 首次登录 Telegram（一次性）
.venv/bin/python create_session.py

# 4. 运行整理向导
.venv/bin/python run.py
```

`create_session.py` 会在 `sessions/<SESSION_NAME>.session` 写入登录态；之后再跑 `run.py` 直接复用，不会再要求验证码。

Windows PowerShell 用户把 `.venv/bin/...` 换成 `.venv\Scripts\...` 即可。

---

## 2. 核心流程

`run.py` 是一个 7 阶段的 CLI 向导，每阶段在终端打印步骤标题，关键节点会停下来等待你确认：

| 阶段 | 名称 | 做什么 | 你需要做什么 |
|---|---|---|---|
| 1 | 选择整理目标 | 选模式：增量补充 / 重新整理 / 只生成草稿 / 从已有草稿继续 | 输入 `i` / `r` / `d` / `c`，回车默认 `i` |
| 2 | 扫描账号状态 | 读取你的 Telegram 文件夹和聊天列表（受 `TELEGRAM_*` 配置控制） | 选择使用缓存或重新扫描 |
| 3 | 补全文件夹说明 | 把当前 Telegram 文件夹同步到 `data/folder_rules.json`，保留你已写过的说明 | 可选：编辑 `description` / `notes` / `include_keywords` 后回车继续 |
| 4 | 生成分类建议 | 命中 `classification_memory.csv` 的聊天跳过 AI；其余分批送给 AI（OpenAI 或 Gemini） | 等待 AI 完成；失败批会记录在 `logs/failed_batches.json`，下次可一键重试 |
| 5 | 审核建议 | 把结果导出到 `data/classification_review.csv`，可在 Excel/Sheets 编辑；也支持终端逐条复核 | **重点环节**：修改 CSV 或终端命令调整结果 |
| 6 | 执行前预览 | 打印每个文件夹的"当前数量 → 新增数量"对比，并把每条 add/keep/remove 导出 `data/execution_preview.csv` | 检查后确认是否生成 `groups.json` |
| 7 | 写入与报告 | （可选）先备份再清空旧文件夹，然后写入 Telegram；输出每个文件的最终路径 | 二次确认后执行；可选"增量添加"或"先清空再重建" |

**双重确认机制**：阶段 6 → `groups.json` 落盘；阶段 7 → 真正写入 Telegram。任何一步都可取消，已审核数据保留在 `data/` 目录里。

---

## 3. 环境变量

所有环境变量在 `.env` 中配置（参考 `.env.example`）。

### 3.1 必填

只有 4 项是真正必填的，缺一不可：

| 变量 | 说明 | 获取方式 |
|---|---|---|
| `API_ID` | Telegram API ID | https://my.telegram.org → API development tools |
| `API_HASH` | Telegram API hash | 同上 |
| `AI_PROVIDER` | `openai` 或 `gemini`，决定下面哪个 key 必填 | 自行选择 |
| `OPENAI_API_KEY` **或** `GEMINI_API_KEY` | AI 服务密钥，与 `AI_PROVIDER` 对应 | OpenAI 控制台 / Google AI Studio |

只要这 4 项填好就能跑起来——其它变量都有合理默认值。

### 3.2 选填（可调可不调）

按主题分组，按需调整。**保持默认就能用**；下面是你可能想调的场景。

#### 路径与会话

| 变量 | 默认值 | 调整时机 |
|---|---|---|
| `SESSION_NAME` | `mili` | 同一项目维护多账号时改名 |
| `SESSIONS_DIR` | `sessions` | 把 `.session` 文件放到别处 |
| `DATA_DIR` | `data` | CSV/JSON 产物想放别处 |
| `LOGS_DIR` | `logs` | 日志想放别处 |

#### AI 调用控制

| 变量 | 默认值 | 调整时机 |
|---|---|---|
| `AI_BATCH_SIZE` | `40` | 失败率高时降到 20；账号稳定时可升到 80 |
| `AI_CONCURRENCY` | `2` | 接口限流严重时降到 1 |
| `AI_MAX_RETRIES` | `3` | 网络抖动多时升到 5 |
| `AI_RETRY_BACKOFF_SECONDS` | `1` | 第 N 次重试等 `backoff × 2^(N-1)` 秒 |
| `AI_CONFIRM_TIMEOUT_SECONDS` | `120` | 关键 y/n 确认的超时秒数 |

#### OpenAI 专属

| 变量 | 默认值 | 调整时机 |
|---|---|---|
| `OPENAI_MODEL` | `gpt-4o-mini` | 想换模型时改 |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` | 走自建代理或 Azure 时改 |
| `OPENAI_TIMEOUT_SECONDS` | `45` | 模型推理慢时升到 90 |
| `OPENAI_REASONING_EFFORT` | `high` | `minimal` / `low` / `medium` / `high`；不兼容端点会自动降级 |
| `OPENAI_VERBOSITY` | `medium` | `low` / `medium` / `high`；不兼容端点会自动降级 |

#### Gemini 专属

| 变量 | 默认值 | 调整时机 |
|---|---|---|
| `GEMINI_MODEL` | `gemini-2.0-flash` | 想换模型时改 |
| `GEMINI_BASE_URL` | `https://generativelanguage.googleapis.com` | 走代理时改 |
| `GEMINI_TIMEOUT_SECONDS` | `45` | 模型推理慢时升到 90 |
| `GEMINI_THINKING_BUDGET` | `2048` | `0` 禁用思考 token；想更深推理可升到 4096+ |
| `GEMINI_INCLUDE_THOUGHTS` | `false` | 是否让 Gemini 返回 thoughts；默认关，仅影响内部预算 |

#### Telegram 扫描调优

| 变量 | 默认值 | 调整时机 |
|---|---|---|
| `TELEGRAM_SCAN_CONCURRENCY` | `3` | 频繁 FloodWait 时降到 1 |
| `TELEGRAM_SCAN_DELAY_SECONDS` | `0.3` | 同上，可适当升到 1.0 |
| `TELEGRAM_RECENT_MESSAGE_LIMIT` | `0` | 想让 AI 看最近几条消息时升到 5（注意：易被短期话题污染分类） |
| `TELEGRAM_CHANNEL_RECENT_MESSAGE_LIMIT` | `1` | 频道辅助判断发布风格的最近消息数 |
| `TELEGRAM_FETCH_FULL_INFO` | `false` | 想拉取完整简介/成员数时设 `true`（慢且更多 API 调用） |
| `TELEGRAM_CACHE_SAVE_EVERY` | `10` | 扫描中每 N 条保存一次缓存 |

---

## 4. 运行产物

所有运行产物落在 3 个目录（路径可通过 §3.2 改名）：

```
data/
├── chats_info.json              扫描缓存（聊天元信息）
├── folders_info.json            扫描缓存（Telegram 文件夹）
├── folder_rules.json            ★ 你编辑的文件夹说明
├── classification_review.csv    ★ 审核入口（在 Excel 打开编辑）
├── classification_memory.csv    分类记忆，下次跳过已分类聊天
├── groups.draft.json            程序校验用的中间草稿
├── groups.json                  阶段 6 确认后的最终结果
├── execution_preview.csv        阶段 7 执行前的 add/keep/remove 清单
└── folder_snapshot_<ts>.json    "清空重建"前的旧文件夹快照（用于回滚）

logs/
├── run.log                      运行日志（INFO 级别）
└── failed_batches.json          上次失败的 AI 批次（下次自动询问是否重试）

sessions/
├── <SESSION_NAME>.session       Telegram 登录态
└── <SESSION_NAME>.run.lock      运行锁，防止并发跑两次
```

★ 标记的是**最常需要你打开编辑**的两个文件。

### `data/folder_rules.json`

告诉 AI 每个 Telegram 文件夹的真实含义。最小只需要 `description` 字段：

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
      "suggested_keywords": ["python", "ai"],
      "missing_from_telegram": false
    }
  ]
}
```

- `auto_classify: false` — 该文件夹不参与自动分类，"清空重建"也会跳过
- `suggested_keywords` — 程序自动从已分类聊天的标题里提炼的高频词，**仅供你参考，不参与 AI 提示**
- `missing_from_telegram: true` — 旧规则保留，但当前 Telegram 已无对应文件夹

### `data/classification_review.csv`

阶段 5 的人工审核入口，可在 Excel/Sheets 直接编辑：

| 列 | 含义 |
|---|---|
| `status` | `categorized` / `unassigned` |
| `folder_id` | 目标文件夹 ID（也可只填 `folder_title`） |
| `folder_title` | 目标文件夹名称 |
| `chat_id` / `chat_title` / `chat_type` / `username` | 聊天身份字段 |
| `description` / `last_message` / `recent_messages` | 用于决策的内容 |
| `confidence` / `evidence` / `reason` | AI 给出的依据，可以人工覆盖 |

**调整方式**：
- 给未分类行填 `folder_id` → 加入分类
- 清空 `folder_id`，或把 `status` 改成 `ignore` / `skip` / `remove` → 移除分类

修改保存后回到终端继续，程序会自动重建 `groups.draft.json` 并校验。

### `data/classification_memory.csv`

记忆已经审核过的聊天，下次跳过 AI。带 `chat_signature` 列：当聊天的 title/username/description 发生变化，签名失效，该聊天会重新交给 AI。

想强制让 AI 重新判断某条，删除对应行即可。

---

## 5. 常用操作

### 阶段 1 的四种整理模式

| 模式 | 输入 | 行为 |
|---|---|---|
| 增量补充（默认） | `i` 或回车 | 不动现有文件夹成员，只追加新分类 |
| 重新整理 | `r` | 写入时提示是否清空旧文件夹再重建（带快照备份） |
| 只生成草稿 | `d` | 走完阶段 6 就停，不写 Telegram |
| 从草稿继续 | `c` | 跳过扫描 + AI，直接加载 `groups.draft.json` 进入审核 |

### 阶段 5 未分类终端复核命令

| 命令 | 含义 |
|---|---|
| `Enter` 或 `i` | 忽略当前聊天 |
| `m` | 手动指定一个 `folder_id`（之后支持 `all:<folder_id>` 把剩余全部归类） |
| `b <folder_id> <chat_id,chat_id,...>` | 批量归类指定聊天 |
| `b <folder_id> all` | 把当前队列剩余聊天全部归到该文件夹 |
| `s <关键词>` | 在队列中按 title/username/description 过滤 |
| `r` | 重置过滤，恢复未处理队列 |
| `g` | 显示当前队列按 chat_type 的分桶数 |
| `l` | 重新打印文件夹列表 |
| `q` | 结束复核，剩余保持未分类 |
| `?` | 重新打印帮助 |

---

## 6. 项目结构

```
telegram-chat-organizer/
├── run.py                   入口：7 阶段 CLI 向导
├── create_session.py        一次性：生成 .session 登录态
├── .env / .env.example      环境变量
├── requirements.txt         运行依赖
├── requirements-dev.txt     开发依赖（pytest）
├── pytest.ini               测试配置
├── README.md
├── LICENSE
│
├── app/                     主代码（按主题分子包）
│   ├── __init__.py
│   ├── config.py            .env 加载与校验
│   ├── ai/
│   │   └── clients.py       OpenAI / Gemini SDK + REST fallback
│   ├── classification/      分类核心
│   │   ├── prompts.py       system / decision rubric / few-shot
│   │   ├── normalize.py     规范化 AI 输出 / 合并 / 引用校验
│   │   ├── folder_rules.py  folder_rules.json 同步 + 关键词反哺
│   │   ├── io_csv.py        review.csv + memory.csv 读写
│   │   └── _shared.py       内部文本辅助
│   ├── cli/
│   │   ├── flow.py          向导步骤、prompt、提示文案
│   │   └── unassigned_review.py  未分类终端复核
│   ├── telegram/
│   │   ├── client.py        Telethon 包装 + 扫描 + 写入
│   │   └── session_lock.py  防并发的运行锁
│   ├── runtime/
│   │   ├── preview.py       执行预览 CSV + 快照
│   │   └── failed_batches.py 失败批次落盘与读取
│   └── utils/
│       └── text.py          文本去重 / 时间戳剥离
│
├── tests/                   pytest 测试（40+ 用例）
├── data/                    JSON / CSV 运行产物（gitignored）
├── logs/                    运行日志（gitignored）
└── sessions/                Telegram session（gitignored）
```

---

## 7. 常见问题

### 7.1 Gemini / OpenAI 报 400

- 确认 `.env` 是否被正确加载（程序启动时会打印脱敏摘要）
- 检查 `AI_PROVIDER` 与 `*_API_KEY` 是否匹配
- 检查 `*_BASE_URL` 与 `*_MODEL` 是否可用

### 7.2 Gemini 报 500

- 通常是服务端瞬时错误或 preview 模型高负载
- 降低 `AI_BATCH_SIZE`（如 20）减小单批负担
- 优先用当前账号可用的稳定模型；速度优先时换 flash 系列

### 7.3 Telethon `database is locked`

- 另一个 `python run.py` / `create_session.py` 还在使用同一个 `.session`
- 程序通过 `sessions/<SESSION_NAME>.run.lock` 防止重复启动
- 等几秒重试；**不要删 `.session`**，否则要重新登录

### 7.4 启动报"当前 session 正在被另一个整理流程使用"

- 上一次运行异常退出，残留了 run.lock
- 错误信息里会直接给出可执行的 `rm sessions/<SESSION_NAME>.run.lock`
- 删除前用 `ps -p <PID>` 确认占用进程确实不存在

### 7.5 上次 AI 分类有失败批次

- 失败批次记录在 `logs/failed_batches.json`，含 `chat_id` 和最后一次错误
- 下次启动到阶段 4 时，会询问"仅重试上次失败的聊天？"，回车默认是
- 不想再重试就删 `logs/failed_batches.json`（成功一次后程序也会自动清理）

---

## 8. 开发与测试

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/pytest
```

测试覆盖：文本工具、分类规范化、文件夹规则同步、CSV 读写（含签名失效）、AI 响应解析、关键词反哺。运行约 0.1 秒，无外部依赖。

---

## 9. 许可与责任

本项目仅用于个人效率提升。请遵守 Telegram 平台条款及当地法律法规。

请在可控范围内使用自动化能力，并对 `data/` 目录做好备份——尤其在使用"清空重建"模式之前。
