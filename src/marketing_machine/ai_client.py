from __future__ import annotations

import json
import socket
import time
from dataclasses import dataclass, field
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request

from .http_safety import credential_safe_urlopen, read_limited


MAX_MODEL_RESPONSE_BYTES = 8 * 1024 * 1024


def urlopen(request: Request, timeout: float) -> Any:
    """Compatibility seam backed by the credential-safe no-redirect opener."""

    return credential_safe_urlopen(request, timeout=timeout)


RETRYABLE_HTTP_STATUS = {408, 409, 425, 429, 500, 502, 503, 504}


class AIClientError(RuntimeError):
    """A safe, classified model error that never includes request secrets."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        attempts: int = 0,
        latency_ms: int = 0,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.attempts = attempts
        self.latency_ms = latency_ms
        self.retryable = retryable


@dataclass(frozen=True)
class AICompletion:
    data: dict[str, Any]
    provider: str
    model: str
    latency_ms: int
    attempts: int
    response_id: str = ""
    usage: dict[str, int] = field(default_factory=dict)
    compatibility_mode: str = "json_schema"


class OpenAICompatibleClient:
    """Small dependency-free client for OpenAI-compatible chat completions.

    Structured output support differs between vLLM, Ollama, SGLang, and cloud
    providers. The client starts with JSON Schema and ``reasoning_effort=none``
    (important for Qwen reasoning models), then removes only optional parameters
    when a server explicitly rejects them.
    """

    def __init__(
        self,
        *,
        provider: str,
        model: str,
        base_url: str,
        api_key: str = "",
        route_name: str = "",
        temperature: float = 0.2,
        timeout_seconds: float = 45.0,
        max_retries: int = 2,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.provider = provider
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.route_name = route_name
        self.temperature = temperature
        self.timeout_seconds = max(1.0, float(timeout_seconds))
        self.max_retries = max(0, int(max_retries))
        self._sleep = sleep
        self._clock = clock

    def complete_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        json_schema: dict[str, Any],
        schema_name: str = "marketing_content",
        max_tokens: int = 1800,
    ) -> AICompletion:
        if not self.base_url or not self.model:
            raise AIClientError("not_configured", "model endpoint or model name is not configured")

        started = self._clock()
        attempts = 0
        last_error: AIClientError | None = None
        payloads = self._compatibility_payloads(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            json_schema=json_schema,
            schema_name=schema_name,
            max_tokens=max_tokens,
        )

        for compatibility_mode, payload in payloads:
            for retry_index in range(self.max_retries + 1):
                attempts += 1
                try:
                    response = self._post(payload)
                    data = _completion_payload(response)
                    return AICompletion(
                        data=data,
                        provider=self.provider,
                        model=self.model,
                        latency_ms=_elapsed_ms(started, self._clock),
                        attempts=attempts,
                        response_id=str(response.get("id", "")),
                        usage=_usage(response.get("usage")),
                        compatibility_mode=compatibility_mode,
                    )
                except HTTPError as exc:
                    status = int(exc.code)
                    if status == 400 and compatibility_mode != payloads[-1][0]:
                        last_error = AIClientError(
                            "unsupported_structured_output",
                            "provider rejected optional structured-output parameters",
                            attempts=attempts,
                            latency_ms=_elapsed_ms(started, self._clock),
                        )
                        break
                    retryable = status in RETRYABLE_HTTP_STATUS
                    last_error = AIClientError(
                        f"http_{status}",
                        f"model request failed with HTTP {status}",
                        attempts=attempts,
                        latency_ms=_elapsed_ms(started, self._clock),
                        retryable=retryable,
                    )
                    if not retryable or retry_index >= self.max_retries:
                        raise last_error from None
                    self._sleep(_retry_delay(retry_index))
                except (TimeoutError, socket.timeout) as exc:
                    last_error = AIClientError(
                        "timeout",
                        "model request timed out",
                        attempts=attempts,
                        latency_ms=_elapsed_ms(started, self._clock),
                        retryable=True,
                    )
                    if retry_index >= self.max_retries:
                        raise last_error from exc
                    self._sleep(_retry_delay(retry_index))
                except URLError as exc:
                    reason = getattr(exc, "reason", None)
                    is_timeout = isinstance(reason, (TimeoutError, socket.timeout))
                    last_error = AIClientError(
                        "timeout" if is_timeout else "connection_error",
                        "model endpoint could not be reached",
                        attempts=attempts,
                        latency_ms=_elapsed_ms(started, self._clock),
                        retryable=True,
                    )
                    if retry_index >= self.max_retries:
                        raise last_error from exc
                    self._sleep(_retry_delay(retry_index))
                except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
                    raise AIClientError(
                        "invalid_response",
                        "model returned an invalid structured response",
                        attempts=attempts,
                        latency_ms=_elapsed_ms(started, self._clock),
                    ) from exc

        if last_error is not None:
            raise last_error
        raise AIClientError(
            "request_failed",
            "model request failed",
            attempts=attempts,
            latency_ms=_elapsed_ms(started, self._clock),
        )

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "wamocon-marketing-machine/0.2",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = Request(
            _chat_completions_url(self.base_url),
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        with urlopen(request, timeout=self.timeout_seconds) as response:
            body = read_limited(
                response,
                max_bytes=MAX_MODEL_RESPONSE_BYTES,
                label="model response",
            )
        parsed = json.loads(body.decode("utf-8"))
        if not isinstance(parsed, dict):
            raise ValueError("completion response must be an object")
        return parsed

    def _compatibility_payloads(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        json_schema: dict[str, Any],
        schema_name: str,
        max_tokens: int,
    ) -> list[tuple[str, dict[str, Any]]]:
        common: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": self.temperature,
            "max_tokens": max(64, int(max_tokens)),
        }
        strict_schema = {
            **common,
            "reasoning_effort": "none",
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": schema_name,
                    "strict": True,
                    "schema": json_schema,
                },
            },
        }
        json_object = {
            **common,
            "reasoning_effort": "none",
            "response_format": {"type": "json_object"},
        }
        prompt_only = dict(common)
        return [
            ("json_schema", strict_schema),
            ("json_object", json_object),
            ("prompt_json", prompt_only),
        ]


def _chat_completions_url(base_url: str) -> str:
    normalized = base_url.rstrip("/")
    if normalized.endswith("/chat/completions"):
        return normalized
    return f"{normalized}/chat/completions"


def _completion_payload(response: dict[str, Any]) -> dict[str, Any]:
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ValueError("completion has no choices")
    message = choices[0].get("message")
    if not isinstance(message, dict):
        raise ValueError("completion choice has no message")
    content = message.get("content")
    if isinstance(content, list):
        content = "".join(
            str(part.get("text", ""))
            for part in content
            if isinstance(part, dict) and part.get("type") in {"text", "output_text"}
        )
    if not isinstance(content, str) or not content.strip():
        raise ValueError("completion message has no content")
    parsed = _parse_json_object(content)
    if not isinstance(parsed, dict):
        raise ValueError("completion content must be a JSON object")
    return parsed


def _parse_json_object(content: str) -> dict[str, Any]:
    text = content.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines:
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            raise
        parsed = json.loads(text[start : end + 1])
    if not isinstance(parsed, dict):
        raise ValueError("expected JSON object")
    return parsed


def _usage(value: Any) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, int] = {}
    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        raw = value.get(key)
        if isinstance(raw, int) and raw >= 0:
            result[key] = raw
    return result


def _retry_delay(retry_index: int) -> float:
    return min(0.25 * (2**retry_index), 2.0)


def _elapsed_ms(started: float, clock: Callable[[], float]) -> int:
    return max(0, int(round((clock() - started) * 1000)))
