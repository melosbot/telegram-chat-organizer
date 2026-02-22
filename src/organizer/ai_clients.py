import asyncio
import logging
from typing import Any, Protocol

from .classification import build_prompts, parse_ai_response_to_groups
from .config import AppConfig

try:
    from google import genai
    from google.genai import types
    _google_import_error = None
except Exception as exc:  # pragma: no cover - env specific
    genai = None
    types = None
    _google_import_error = exc

try:
    from openai import OpenAI
    _openai_import_error = None
except Exception as exc:  # pragma: no cover - env specific
    OpenAI = None
    _openai_import_error = exc


class AIClientError(RuntimeError):
    """Raised when AI classification fails."""


class AIClient(Protocol):
    async def classify(self, chats: list[dict], folders: list[dict]) -> dict: ...


def _extract_status_code(exc: Exception) -> int | None:
    for attr in ("status_code", "code"):
        value = getattr(exc, attr, None)
        if isinstance(value, int):
            return value
    response = getattr(exc, "response", None)
    status_code = getattr(response, "status_code", None)
    if isinstance(status_code, int):
        return status_code
    return None


def _is_retryable_exception(exc: Exception, status_code: int | None) -> bool:
    if status_code in {429}:
        return True
    if status_code is not None and status_code >= 500:
        return True
    text = str(exc).lower()
    transient_signals = (
        "timed out",
        "timeout",
        "connection reset",
        "connection aborted",
        "temporary",
        "unavailable",
        "service unavailable",
        "network",
    )
    return any(token in text for token in transient_signals)


async def _run_with_retry(
    func,
    provider_name: str,
    max_retries: int,
    backoff_seconds: float,
) -> Any:
    last_error: Exception | None = None
    for attempt in range(1, max_retries + 1):
        try:
            return await asyncio.to_thread(func)
        except Exception as exc:  # pragma: no cover - depends on SDK/network
            last_error = exc
            status_code = _extract_status_code(exc)
            retryable = _is_retryable_exception(exc, status_code)
            if retryable and attempt < max_retries:
                delay = backoff_seconds * (2 ** (attempt - 1))
                logging.warning(
                    "%s 请求失败（status=%s, attempt=%d/%d），%.1f 秒后重试: %s",
                    provider_name,
                    status_code,
                    attempt,
                    max_retries,
                    delay,
                    exc,
                )
                await asyncio.sleep(delay)
                continue
            message = f"{provider_name} 请求失败"
            if status_code is not None:
                message += f" status={status_code}"
            message += f": {exc}"
            raise AIClientError(message) from exc
    raise AIClientError(f"{provider_name} 请求失败，达到最大重试次数: {last_error}")


class BaseProviderClient:
    def __init__(self, config: AppConfig) -> None:
        self.config = config

    async def _execute_with_retry(self, provider_name: str, func):
        return await _run_with_retry(
            func=func,
            provider_name=provider_name,
            max_retries=self.config.ai_max_retries,
            backoff_seconds=self.config.ai_retry_backoff_seconds,
        )


class OpenAIClient(BaseProviderClient):
    def __init__(self, config: AppConfig) -> None:
        if OpenAI is None:
            raise AIClientError(
                f"OpenAI SDK 未安装或不可用，请执行 pip install -r requirements.txt。原始错误: {_openai_import_error}"
            )
        super().__init__(config)
        settings = config.openai
        self.client = OpenAI(
            api_key=settings.api_key,
            base_url=settings.base_url,
            timeout=settings.timeout_seconds,
        )
        self.model = settings.model

    async def classify(self, chats: list[dict], folders: list[dict]) -> dict:
        system_prompt, user_prompt = build_prompts(chats, folders)

        def _do_request():
            return self.client.chat.completions.create(
                model=self.model,
                temperature=0.1,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            )

        response = await self._execute_with_retry("OpenAI", _do_request)
        choices = getattr(response, "choices", None) or []
        if not choices:
            raise AIClientError("OpenAI 返回缺少 choices")

        message = getattr(choices[0], "message", None)
        content = getattr(message, "content", None)
        if isinstance(content, list):
            content = "".join(
                [
                    str(getattr(part, "text", ""))
                    if not isinstance(part, dict)
                    else str(part.get("text", ""))
                    for part in content
                ]
            )
        if not content:
            raise AIClientError("OpenAI 返回缺少 message.content")

        return parse_ai_response_to_groups(str(content))


class GeminiClient(BaseProviderClient):
    def __init__(self, config: AppConfig) -> None:
        if genai is None or types is None:
            raise AIClientError(
                f"google-genai SDK 未安装或不可用，请执行 pip install -r requirements.txt。原始错误: {_google_import_error}"
            )
        super().__init__(config)
        settings = config.gemini
        self.model = settings.model
        self.timeout_seconds = settings.timeout_seconds

        try:
            http_options = types.HttpOptions(base_url=settings.base_url, timeout=settings.timeout_seconds * 1000)
            self.client = genai.Client(api_key=settings.api_key, http_options=http_options)
        except Exception:
            # Backward compatible fallback for SDK variants.
            try:
                self.client = genai.Client(
                    api_key=settings.api_key,
                    http_options={"base_url": settings.base_url, "timeout": settings.timeout_seconds * 1000},
                )
            except Exception as exc:
                raise AIClientError(
                    "Gemini 客户端初始化失败。请检查 google-genai 版本是否支持自定义 base_url/http_options。"
                ) from exc

    async def classify(self, chats: list[dict], folders: list[dict]) -> dict:
        system_prompt, user_prompt = build_prompts(chats, folders)

        def _do_request():
            config = types.GenerateContentConfig(
                system_instruction=system_prompt,
                temperature=0.1,
                response_mime_type="application/json",
                automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            )
            return self.client.models.generate_content(
                model=self.model,
                contents=user_prompt,
                config=config,
            )

        response = await self._execute_with_retry("Gemini", _do_request)
        content = getattr(response, "text", None)
        if not content:
            # Fallback for SDK responses where text isn't synthesized.
            candidates = getattr(response, "candidates", None) or []
            parts: list[str] = []
            for candidate in candidates:
                candidate_content = getattr(candidate, "content", None)
                for part in getattr(candidate_content, "parts", []) or []:
                    text = getattr(part, "text", None)
                    if text:
                        parts.append(str(text))
            content = "\n".join(parts).strip()

        if not content:
            raise AIClientError("Gemini 返回缺少文本内容")

        return parse_ai_response_to_groups(str(content))


def create_ai_client(config: AppConfig) -> AIClient:
    if config.ai_provider == "openai":
        return OpenAIClient(config)
    return GeminiClient(config)
