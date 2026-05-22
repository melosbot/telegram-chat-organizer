import asyncio
from typing import Iterable

from .config import AppConfig, mask_secret


def print_header(title: str) -> None:
    print("\n" + "=" * 88)
    print(title)
    print("=" * 88)


def print_startup_overview(config: AppConfig) -> None:
    active = config.active_provider
    print_header("Telegram Chat Organizer - CLI 向导")
    print("本次会先生成可审核建议，只有最终确认后才会写入 Telegram。")
    print("\n配置摘要（敏感信息已脱敏）:")
    print(f"- SESSION_NAME: {config.telegram.session_name}")
    print(f"- AI_PROVIDER: {config.ai_provider}")
    print(f"- MODEL: {active.model}")
    print(f"- BASE_URL: {active.base_url}")
    print(f"- API_KEY: {mask_secret(active.api_key)}")
    print(f"- AI_MAX_RETRIES: {config.ai_max_retries}")
    print(f"- AI_RETRY_BACKOFF_SECONDS: {config.ai_retry_backoff_seconds}")
    print(f"- AI_CONFIRM_TIMEOUT_SECONDS: {config.ai_confirm_timeout_seconds}")
    print(f"- OPENAI_REASONING_EFFORT: {config.openai_reasoning_effort or 'disabled'}")
    print(f"- OPENAI_VERBOSITY: {config.openai_verbosity or 'disabled'}")
    print(f"- GEMINI_THINKING_BUDGET: {config.gemini_thinking_budget}")
    print(f"- GEMINI_INCLUDE_THOUGHTS: {config.gemini_include_thoughts}")
    print(f"- AI_BATCH_SIZE: {config.ai_batch_size}")
    print(f"- AI_CONCURRENCY: {config.ai_concurrency}")
    print(f"- TELEGRAM_RECENT_MESSAGE_LIMIT: {config.telegram_recent_message_limit}")
    print(f"- TELEGRAM_CHANNEL_RECENT_MESSAGE_LIMIT: {config.telegram_channel_recent_message_limit}")
    print(f"- TELEGRAM_SCAN_DELAY_SECONDS: {config.telegram_scan_delay_seconds}")
    print(f"- TELEGRAM_FETCH_FULL_INFO: {config.telegram_fetch_full_info}")
    print(f"- TELEGRAM_CACHE_SAVE_EVERY: {config.telegram_cache_save_every}")
    print(f"- DATA_DIR: {config.paths.data_dir}")
    print(f"- LOGS_DIR: {config.paths.logs_dir}")
    print(f"- SESSIONS_DIR: {config.paths.sessions_dir}")
    print("\n流程概览:")
    print("1) 选择整理目标")
    print("2) 扫描账号状态")
    print("3) 补全文件夹说明")
    print("4) 生成分类建议")
    print("5) 审核建议")
    print("6) 执行前预览")
    print("7) 写入与报告")


def print_step(index: int, title: str, total: int = 7) -> None:
    print(f"\n[阶段 {index}/{total}] {title}")
    print("-" * 88)


def print_target_mode_hint() -> None:
    print("\n请选择这次整理的目标：")
    print("- i: 增量补充分组（推荐，不主动清空文件夹）")
    print("- r: 重新整理全部文件夹（执行前仍会再次确认）")
    print("- d: 只生成草稿，不写入 Telegram")
    print("- c: 从已有草稿继续")


async def prompt_text(prompt: str, timeout_seconds: int | None = None) -> str | None:
    try:
        if timeout_seconds is None:
            return await asyncio.to_thread(input, prompt)
        return await asyncio.wait_for(asyncio.to_thread(input, prompt), timeout=timeout_seconds)
    except asyncio.TimeoutError:
        return None


async def wait_for_enter(message: str) -> None:
    await prompt_text(f"{message}\n按回车继续...")


async def prompt_yes_no(
    question: str,
    default: bool | None = None,
    timeout_seconds: int | None = None,
) -> bool | None:
    suffix = " [y/n]: "
    if default is True:
        suffix = " [Y/n]: "
    elif default is False:
        suffix = " [y/N]: "

    yes_set = {"y", "yes", "是", "确认", "1"}
    no_set = {"n", "no", "否", "取消", "0"}

    while True:
        answer = await prompt_text(question + suffix, timeout_seconds=timeout_seconds)
        if answer is None:
            return None
        normalized = answer.strip().lower()
        if not normalized and default is not None:
            return default
        if normalized in yes_set:
            return True
        if normalized in no_set:
            return False
        print("输入无效，请输入 y 或 n。")


async def prompt_choice(question: str, allowed: Iterable[str], default: str | None = None) -> str:
    allowed_set = {item.lower() for item in allowed}
    while True:
        raw = await prompt_text(question)
        if raw is None:
            continue
        value = raw.strip().lower()
        if not value and default:
            value = default.lower()
        if value in allowed_set:
            return value
        print(f"输入无效，可选值: {', '.join(sorted(allowed_set))}")


def print_folder_summary(folders: list[dict]) -> None:
    print("已读取文件夹:")
    for folder in folders:
        print(f"- ID={folder['id']} | {folder['title']} | 已含 {len(folder.get('existing_peers', []))} 聊天")


def print_clear_strategy_hint() -> None:
    print("\n清空策略建议：")
    print("- 你希望完全重做分类时，选择“是”")
    print("- 你只想增量补充时，选择“否”")
    print("- 清空操作会保留每个文件夹 1 个聊天，避免 Telegram 接口报错")


def print_cache_strategy_hint() -> None:
    print("\n聊天缓存策略：")
    print("- 使用缓存速度更快，但可能缺少最近变更")
    print("- 重新收集更准确，但耗时更长")


def print_draft_edit_hint(review_csv: str, draft_file: str) -> None:
    print("\n审核文件已生成，默认请编辑 CSV：")
    print(f"- CSV 审核表: {review_csv}")
    print(f"- JSON 草稿: {draft_file}（程序校验用，通常不需要手改）")
    print("- 建议先按 folder_title 分组检查数量，再抽查 description/last_message 是否支持该分类")


def print_folder_rules_hint(rules_file: str, missing_description_count: int) -> None:
    print("\n文件夹说明用于告诉 AI：每个文件夹到底该收什么、不该收什么。")
    print(f"- 规则文件: {rules_file}")
    if missing_description_count:
        print(f"- 当前还有 {missing_description_count} 个文件夹没有说明")
    else:
        print("- 当前文件夹说明已填写完整")
    print("- 你可以只填 description；include_keywords / exclude_keywords / notes 都是可选增强项")


def print_folder_rules_summary(lines: list[str]) -> None:
    print("\n当前文件夹说明摘要：")
    if not lines:
        print("- 无可用文件夹说明")
        return
    for line in lines:
        print(line)


def print_file_review_hint(review_csv: str, draft_file: str) -> None:
    print("\nCSV 审核方式：")
    print(f"- 打开并编辑: {review_csv}")
    print("- 归类一行：填 folder_id，或填精确 folder_title；status 可保留 unassigned")
    print("- 移除一行：清空 folder_id，或把 status 改为 ignore/skip/remove")
    print(f"- 高级模式仍可直接编辑 JSON: {draft_file}")
    print("- 返回终端后程序会优先读取已修改的 CSV，并自动重建草稿")


def print_manual_fallback_hint(error_message: str, prompt: str) -> None:
    print("\nAI 自动分类失败，已切换到手工分类向导。")
    print(f"- 失败原因: {error_message}")
    print("- 你可以把以下提示词发给任意支持的 AI（或手工编辑 JSON）：")
    print("-" * 88)
    print(prompt)
    print("-" * 88)


def print_unassigned_hint() -> None:
    print("\n未分类聊天复核（更友好模式）：")
    print("- i: 忽略当前聊天")
    print("- m: 手动指定 folder_id")
    print("- l: 重新查看文件夹列表")
    print("- q: 结束复核，剩余全部忽略")


def print_folder_picker(folders: list[dict]) -> None:
    print("\n可选目标文件夹：")
    for folder in folders:
        print(f"- {folder['id']}: {folder['title']}")
