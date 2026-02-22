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
    print("本次将执行单次向导流程，完成后自动退出。")
    print("\n配置摘要（敏感信息已脱敏）:")
    print(f"- SESSION_NAME: {config.telegram.session_name}")
    print(f"- AI_PROVIDER: {config.ai_provider}")
    print(f"- MODEL: {active.model}")
    print(f"- BASE_URL: {active.base_url}")
    print(f"- API_KEY: {mask_secret(active.api_key)}")
    print(f"- AI_MAX_RETRIES: {config.ai_max_retries}")
    print(f"- AI_RETRY_BACKOFF_SECONDS: {config.ai_retry_backoff_seconds}")
    print(f"- AI_CONFIRM_TIMEOUT_SECONDS: {config.ai_confirm_timeout_seconds}")
    print(f"- AI_BATCH_SIZE: {config.ai_batch_size}")
    print(f"- DATA_DIR: {config.paths.data_dir}")
    print(f"- LOGS_DIR: {config.paths.logs_dir}")
    print(f"- SESSIONS_DIR: {config.paths.sessions_dir}")
    print("\n流程概览:")
    print("1) 启动检查")
    print("2) Telegram 连接检查")
    print("3) 文件夹策略确认")
    print("4) 聊天数据准备")
    print("5) 分类规则说明")
    print("6) AI 自动分类")
    print("7) 草稿审阅")
    print("8) 草稿校验")
    print("9) 未分类复核")
    print("10) 两段确认")
    print("11) 执行并输出报告")


def print_step(index: int, title: str) -> None:
    print(f"\n[步骤 {index}/11] {title}")
    print("-" * 88)


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


def print_draft_edit_hint(draft_file: str) -> None:
    print("\n草稿已生成，请手动审阅并可直接修改：")
    print(f"- 文件: {draft_file}")
    print("- 建议先检查每个文件夹新增数量是否合理")
    print("- 再抽查示例聊天是否语义匹配")


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
