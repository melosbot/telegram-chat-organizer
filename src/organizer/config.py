import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv


class ConfigError(ValueError):
    """Raised when environment configuration is invalid."""


@dataclass(frozen=True)
class TelegramConfig:
    api_id: int
    api_hash: str
    session_name: str


@dataclass(frozen=True)
class ProviderConfig:
    api_key: str
    base_url: str
    model: str
    timeout_seconds: int


@dataclass(frozen=True)
class PathsConfig:
    project_root: Path
    data_dir: Path
    logs_dir: Path
    sessions_dir: Path


@dataclass(frozen=True)
class AppConfig:
    telegram: TelegramConfig
    ai_provider: str
    openai: ProviderConfig
    gemini: ProviderConfig
    openai_reasoning_effort: str
    openai_verbosity: str
    gemini_thinking_budget: int
    gemini_include_thoughts: bool
    ai_max_retries: int
    ai_retry_backoff_seconds: float
    ai_confirm_timeout_seconds: int
    ai_batch_size: int
    ai_concurrency: int
    telegram_recent_message_limit: int
    telegram_channel_recent_message_limit: int
    telegram_scan_delay_seconds: float
    telegram_scan_concurrency: int
    telegram_fetch_full_info: bool
    telegram_cache_save_every: int
    paths: PathsConfig

    @property
    def active_provider(self) -> ProviderConfig:
        return self.openai if self.ai_provider == "openai" else self.gemini


def _parse_int(name: str, default: int, minimum: int = 0) -> int:
    raw = os.getenv(name, str(default)).strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} 必须是整数，当前值: {raw}") from exc
    if value < minimum:
        raise ConfigError(f"{name} 不能小于 {minimum}，当前值: {value}")
    return value


def _parse_float(name: str, default: float, minimum: float = 0.0) -> float:
    raw = os.getenv(name, str(default)).strip()
    try:
        value = float(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} 必须是数字，当前值: {raw}") from exc
    if value < minimum:
        raise ConfigError(f"{name} 不能小于 {minimum}，当前值: {value}")
    return value


def _parse_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "y", "on", "是"}:
        return True
    if normalized in {"0", "false", "no", "n", "off", "否"}:
        return False
    raise ConfigError(f"{name} 必须是布尔值（true/false），当前值: {raw}")


def _parse_optional_choice(name: str, default: str, allowed: set[str]) -> str:
    raw = os.getenv(name, default).strip().lower()
    if raw in {"", "none", "off", "false", "0", "disable", "disabled"}:
        return ""
    if raw not in allowed:
        options = ", ".join(sorted(allowed))
        raise ConfigError(f"{name} 可选值: {options}；留空表示禁用，当前值: {raw}")
    return raw


def _normalize_base_url(name: str, value: str) -> str:
    normalized = value.strip().rstrip("/")
    if not normalized:
        raise ConfigError(f"{name} 不能为空")
    parsed = urlparse(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ConfigError(f"{name} 必须是完整 URL（如 http://127.0.0.1:8000/v1）")
    return normalized


def _require(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ConfigError(f"缺少必填环境变量: {name}")
    return value


def _build_openai_config() -> ProviderConfig:
    return ProviderConfig(
        api_key=os.getenv("OPENAI_API_KEY", "").strip(),
        base_url=_normalize_base_url(
            "OPENAI_BASE_URL",
            os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        ),
        model=os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip() or "gpt-4o-mini",
        timeout_seconds=_parse_int("OPENAI_TIMEOUT_SECONDS", 45, minimum=1),
    )


def _build_gemini_config() -> ProviderConfig:
    config = ProviderConfig(
        api_key=os.getenv("GEMINI_API_KEY", "").strip(),
        base_url=_normalize_base_url(
            "GEMINI_BASE_URL",
            os.getenv("GEMINI_BASE_URL", "https://generativelanguage.googleapis.com"),
        ),
        model=os.getenv("GEMINI_MODEL", "gemini-2.0-flash").strip() or "gemini-2.0-flash",
        timeout_seconds=_parse_int("GEMINI_TIMEOUT_SECONDS", 45, minimum=1),
    )
    if config.api_key and config.api_key.startswith("sk-"):
        raise ConfigError("GEMINI_API_KEY 看起来像 OpenAI key（sk- 开头）。请改为 Gemini key（通常 AIza 开头）。")
    return config


def _build_paths(project_root: Path) -> PathsConfig:
    data_dir = (project_root / os.getenv("DATA_DIR", "data")).resolve()
    logs_dir = (project_root / os.getenv("LOGS_DIR", "logs")).resolve()
    sessions_dir = (project_root / os.getenv("SESSIONS_DIR", "sessions")).resolve()
    return PathsConfig(
        project_root=project_root,
        data_dir=data_dir,
        logs_dir=logs_dir,
        sessions_dir=sessions_dir,
    )


def ensure_runtime_dirs(paths: PathsConfig) -> None:
    paths.data_dir.mkdir(parents=True, exist_ok=True)
    paths.logs_dir.mkdir(parents=True, exist_ok=True)
    paths.sessions_dir.mkdir(parents=True, exist_ok=True)


def load_config(project_root: Path | None = None) -> AppConfig:
    # Keep .env as source of truth for most fields, but allow temporary
    # provider switch from current shell (e.g. AI_PROVIDER=gemini python run.py).
    runtime_ai_provider = os.getenv("AI_PROVIDER")
    load_dotenv(override=True)
    if runtime_ai_provider is not None:
        os.environ["AI_PROVIDER"] = runtime_ai_provider

    root = (project_root or Path.cwd()).resolve()

    telegram = TelegramConfig(
        api_id=_parse_int("API_ID", 0, minimum=1),
        api_hash=_require("API_HASH"),
        session_name=os.getenv("SESSION_NAME", "mili").strip() or "mili",
    )

    ai_provider = os.getenv("AI_PROVIDER", "openai").strip().lower()
    if ai_provider not in {"openai", "gemini"}:
        raise ConfigError("AI_PROVIDER 只能是 openai 或 gemini")

    openai = _build_openai_config()
    gemini = _build_gemini_config()

    if ai_provider == "openai" and not openai.api_key:
        raise ConfigError("AI_PROVIDER=openai 时必须配置 OPENAI_API_KEY")
    if ai_provider == "gemini" and not gemini.api_key:
        raise ConfigError("AI_PROVIDER=gemini 时必须配置 GEMINI_API_KEY")

    paths = _build_paths(root)

    return AppConfig(
        telegram=telegram,
        ai_provider=ai_provider,
        openai=openai,
        gemini=gemini,
        openai_reasoning_effort=_parse_optional_choice(
            "OPENAI_REASONING_EFFORT",
            "high",
            {"minimal", "low", "medium", "high"},
        ),
        openai_verbosity=_parse_optional_choice(
            "OPENAI_VERBOSITY",
            "medium",
            {"low", "medium", "high"},
        ),
        gemini_thinking_budget=_parse_int("GEMINI_THINKING_BUDGET", 2048, minimum=0),
        gemini_include_thoughts=_parse_bool("GEMINI_INCLUDE_THOUGHTS", False),
        ai_max_retries=_parse_int("AI_MAX_RETRIES", 3, minimum=1),
        ai_retry_backoff_seconds=_parse_float("AI_RETRY_BACKOFF_SECONDS", 1.0, minimum=0.1),
        ai_confirm_timeout_seconds=_parse_int("AI_CONFIRM_TIMEOUT_SECONDS", 120, minimum=1),
        ai_batch_size=_parse_int("AI_BATCH_SIZE", 80, minimum=1),
        ai_concurrency=_parse_int("AI_CONCURRENCY", 1, minimum=1),
        telegram_recent_message_limit=_parse_int("TELEGRAM_RECENT_MESSAGE_LIMIT", 0, minimum=0),
        telegram_channel_recent_message_limit=_parse_int("TELEGRAM_CHANNEL_RECENT_MESSAGE_LIMIT", 1, minimum=0),
        telegram_scan_delay_seconds=_parse_float("TELEGRAM_SCAN_DELAY_SECONDS", 1.0, minimum=0.0),
        telegram_scan_concurrency=_parse_int("TELEGRAM_SCAN_CONCURRENCY", 3, minimum=1),
        telegram_fetch_full_info=_parse_bool("TELEGRAM_FETCH_FULL_INFO", False),
        telegram_cache_save_every=_parse_int("TELEGRAM_CACHE_SAVE_EVERY", 10, minimum=1),
        paths=paths,
    )


def mask_secret(secret: str) -> str:
    if not secret:
        return "<empty>"
    if len(secret) <= 8:
        return "*" * len(secret)
    return f"{secret[:4]}...{secret[-4:]}"
