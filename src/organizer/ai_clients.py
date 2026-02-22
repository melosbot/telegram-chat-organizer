import asyncio
import json
import logging
import sys
from typing import Any, Protocol
from urllib import parse, request
from urllib.error import HTTPError, URLError

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


class GeminiRESTError(RuntimeError):
    """Raised when Gemini REST API request fails."""

    def __init__(self, message: str, code: int | None = None) -> None:
        super().__init__(message)
        self.code = code


class OpenAIRESTError(RuntimeError):
    """Raised when OpenAI-compatible REST API request fails."""

    def __init__(self, message: str, code: int | None = None) -> None:
        super().__init__(message)
        self.code = code


class AIClient(Protocol):
    async def classify(self, chats: list[dict], folders: list[dict]) -> dict: ...


def _build_openai_chat_endpoint(base_url: str) -> str:
    normalized = base_url.rstrip("/")
    parsed = parse.urlparse(normalized)
    path = parsed.path.rstrip("/")

    if not path:
        path = "/v1"
    if not path.endswith("/chat/completions"):
        path = f"{path}/chat/completions"

    return parse.urlunparse((parsed.scheme, parsed.netloc, path, "", "", ""))


def _extract_openai_text(payload: dict) -> str:
    choices = payload.get("choices") or []
    if not choices:
        return ""

    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    content = (message or {}).get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, dict):
                text = part.get("text")
                if text:
                    parts.append(str(text))
        return "".join(parts).strip()
    return ""


def _build_gemini_rest_endpoint(base_url: str, model: str, api_key: str) -> str:
    normalized = base_url.rstrip("/")
    parsed = parse.urlparse(normalized)

    path = parsed.path.rstrip("/")
    if not path:
        path = "/v1beta"
    elif path.endswith("/models"):
        pass
    elif "/v1/" not in f"{path}/" and "/v1beta/" not in f"{path}/":
        path = f"{path}/v1beta"

    encoded_model = parse.quote(model, safe="")
    if path.endswith("/models"):
        endpoint_path = f"{path}/{encoded_model}:generateContent"
    else:
        endpoint_path = f"{path}/models/{encoded_model}:generateContent"

    query = parse.urlencode({"key": api_key})
    return parse.urlunparse((parsed.scheme, parsed.netloc, endpoint_path, "", query, ""))


def _extract_gemini_rest_text(payload: dict) -> str:
    candidates = payload.get("candidates") or []
    parts: list[str] = []
    for candidate in candidates:
        content = candidate.get("content") if isinstance(candidate, dict) else None
        for part in (content or {}).get("parts", []) or []:
            if not isinstance(part, dict):
                continue
            text = part.get("text")
            if text:
                parts.append(str(text))
    return "\n".join(parts).strip()


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
                    "%s request failed (status=%s, attempt=%d/%d), retry in %.1fs: %s",
                    provider_name,
                    status_code,
                    attempt,
                    max_retries,
                    delay,
                    exc,
                )
                await asyncio.sleep(delay)
                continue
            message = f"{provider_name} request failed"
            if status_code is not None:
                message += f" status={status_code}"
            message += f": {exc}"
            raise AIClientError(message) from exc
    raise AIClientError(f"{provider_name} request failed after max retries: {last_error}")


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
        super().__init__(config)
        settings = config.openai
        self.api_key = settings.api_key
        self.base_url = settings.base_url
        self.model = settings.model
        self.timeout_seconds = settings.timeout_seconds
        self._sdk_client = None
        self._use_rest_fallback = OpenAI is None

        if self._use_rest_fallback:
            logging.warning(
                "OpenAI SDK import failed on Python %s, fallback to REST API. error=%s",
                sys.version.split()[0],
                _openai_import_error,
            )
            return

        try:
            self._sdk_client = OpenAI(
                api_key=self.api_key,
                base_url=self.base_url,
                timeout=self.timeout_seconds,
            )
        except Exception as exc:
            self._use_rest_fallback = True
            logging.warning(
                "OpenAI SDK init failed on Python %s, fallback to REST API. error=%s",
                sys.version.split()[0],
                exc,
            )

    def _classify_via_sdk(self, system_prompt: str, user_prompt: str) -> str:
        response = self._sdk_client.chat.completions.create(
            model=self.model,
            temperature=0.1,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        choices = getattr(response, "choices", None) or []
        if not choices:
            raise OpenAIRESTError("OpenAI SDK response missing choices")

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
            raise OpenAIRESTError("OpenAI SDK response missing message.content")
        return str(content)

    def _classify_via_rest(self, system_prompt: str, user_prompt: str) -> str:
        endpoint = _build_openai_chat_endpoint(self.base_url)
        payload = {
            "model": self.model,
            "temperature": 0.1,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = request.Request(
            endpoint,
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )

        try:
            with request.urlopen(req, timeout=self.timeout_seconds) as response:
                raw = response.read().decode("utf-8")
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore").strip()
            message = detail or str(exc)
            raise OpenAIRESTError(f"OpenAI REST HTTP {exc.code}: {message}", code=exc.code) from exc
        except URLError as exc:
            raise OpenAIRESTError(f"OpenAI REST network error: {exc}") from exc

        try:
            payload_json = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise OpenAIRESTError(f"OpenAI REST returned invalid JSON: {exc}") from exc

        content = _extract_openai_text(payload_json)
        if content:
            return content
        raise OpenAIRESTError("OpenAI REST response does not contain text content.")

    async def classify(self, chats: list[dict], folders: list[dict]) -> dict:
        system_prompt, user_prompt = build_prompts(chats, folders)
        if self._use_rest_fallback:
            response_text = await self._execute_with_retry(
                "OpenAI",
                lambda: self._classify_via_rest(system_prompt, user_prompt),
            )
            return parse_ai_response_to_groups(str(response_text))

        response_text = await self._execute_with_retry(
            "OpenAI",
            lambda: self._classify_via_sdk(system_prompt, user_prompt),
        )
        return parse_ai_response_to_groups(str(response_text))


class GeminiClient(BaseProviderClient):
    def __init__(self, config: AppConfig) -> None:
        super().__init__(config)
        settings = config.gemini
        self.model = settings.model
        self.api_key = settings.api_key
        self.base_url = settings.base_url
        self.timeout_seconds = settings.timeout_seconds
        self._sdk_client = None
        self._use_rest_fallback = genai is None or types is None

        if self._use_rest_fallback:
            logging.warning(
                "google-genai SDK import failed on Python %s, fallback to Gemini REST API. error=%s",
                sys.version.split()[0],
                _google_import_error,
            )
            return

        try:
            self._sdk_client = self._build_sdk_client()
        except Exception as exc:
            self._use_rest_fallback = True
            logging.warning(
                "Gemini SDK init failed on Python %s, fallback to REST API. error=%s",
                sys.version.split()[0],
                exc,
            )

    def _build_sdk_client(self):
        try:
            http_options = types.HttpOptions(base_url=self.base_url, timeout=self.timeout_seconds * 1000)
            return genai.Client(api_key=self.api_key, http_options=http_options)
        except Exception:
            return genai.Client(
                api_key=self.api_key,
                http_options={"base_url": self.base_url, "timeout": self.timeout_seconds * 1000},
            )

    def _classify_via_sdk(self, system_prompt: str, user_prompt: str) -> str:
        config_kwargs = {
            "system_instruction": system_prompt,
            "temperature": 0.1,
            "response_mime_type": "application/json",
        }
        try:
            config_kwargs["automatic_function_calling"] = types.AutomaticFunctionCallingConfig(disable=True)
        except Exception:
            pass

        config = types.GenerateContentConfig(**config_kwargs)
        response = self._sdk_client.models.generate_content(
            model=self.model,
            contents=user_prompt,
            config=config,
        )

        content = getattr(response, "text", None)
        if content:
            return str(content)

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
            raise GeminiRESTError("Gemini SDK response does not contain text content.")
        return content

    def _classify_via_rest(self, system_prompt: str, user_prompt: str) -> str:
        endpoint = _build_gemini_rest_endpoint(
            base_url=self.base_url,
            model=self.model,
            api_key=self.api_key,
        )
        payload = {
            "system_instruction": {"parts": [{"text": system_prompt}]},
            "contents": [{"parts": [{"text": user_prompt}]}],
            "generationConfig": {
                "temperature": 0.1,
                "responseMimeType": "application/json",
            },
        }
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = request.Request(
            endpoint,
            data=body,
            method="POST",
            headers={"Content-Type": "application/json"},
        )

        try:
            with request.urlopen(req, timeout=self.timeout_seconds) as response:
                raw = response.read().decode("utf-8")
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore").strip()
            message = detail or str(exc)
            raise GeminiRESTError(f"Gemini REST HTTP {exc.code}: {message}", code=exc.code) from exc
        except URLError as exc:
            raise GeminiRESTError(f"Gemini REST network error: {exc}") from exc

        try:
            payload_json = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise GeminiRESTError(f"Gemini REST returned invalid JSON: {exc}") from exc

        content = _extract_gemini_rest_text(payload_json)
        if content:
            return content

        prompt_feedback = payload_json.get("promptFeedback")
        if isinstance(prompt_feedback, dict):
            reason = prompt_feedback.get("blockReason")
            if reason:
                raise GeminiRESTError(f"Gemini REST blocked the prompt: {reason}")

        raise GeminiRESTError("Gemini REST response does not contain text content.")

    async def classify(self, chats: list[dict], folders: list[dict]) -> dict:
        system_prompt, user_prompt = build_prompts(chats, folders)

        if self._use_rest_fallback:
            response_text = await self._execute_with_retry(
                "Gemini",
                lambda: self._classify_via_rest(system_prompt, user_prompt),
            )
            return parse_ai_response_to_groups(str(response_text))

        response_text = await self._execute_with_retry(
            "Gemini",
            lambda: self._classify_via_sdk(system_prompt, user_prompt),
        )
        return parse_ai_response_to_groups(str(response_text))


def create_ai_client(config: AppConfig) -> AIClient:
    if config.ai_provider == "openai":
        return OpenAIClient(config)
    return GeminiClient(config)
