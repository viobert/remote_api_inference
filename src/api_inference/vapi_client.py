from __future__ import annotations

import json
import time
from typing import Any
from urllib import error, request

from .config import Settings


RETRYABLE_STATUS_CODES = {408, 409, 429, 500, 502, 503, 504}


class APIRequestError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None, body: str | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.body = body


def _headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }


def _request_json(
    method: str,
    url: str,
    headers: dict[str, str],
    payload: dict[str, Any] | None,
    timeout_seconds: int,
) -> dict[str, Any]:
    data = None
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    http_request = request.Request(url=url, data=data, headers=headers, method=method)

    try:
        with request.urlopen(http_request, timeout=timeout_seconds) as response:
            body = response.read().decode("utf-8")
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise APIRequestError(
            f"HTTP {exc.code} for {url}",
            status_code=exc.code,
            body=body,
        ) from exc
    except error.URLError as exc:
        raise APIRequestError(f"Network error for {url}: {exc.reason}") from exc

    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise APIRequestError(f"Failed to decode JSON response from {url}", body=body) from exc


def list_models(settings: Settings) -> dict[str, Any]:
    return _request_json(
        method="GET",
        url=f"{settings.base_url}/models",
        headers=_headers(settings.api_key),
        payload=None,
        timeout_seconds=settings.timeout_seconds,
    )


def chat_completion(
    settings: Settings,
    *,
    model: str,
    messages: list[dict[str, Any]],
    temperature: float | None = None,
    max_tokens: int | None = None,
    extra_body: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], int]:
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": False,
    }
    if temperature is not None:
        payload["temperature"] = temperature
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens
    if extra_body:
        payload.update(extra_body)

    last_error: Exception | None = None
    for attempt in range(1, settings.max_retries + 1):
        try:
            response_json = _request_json(
                method="POST",
                url=f"{settings.base_url}/chat/completions",
                headers=_headers(settings.api_key),
                payload=payload,
                timeout_seconds=settings.timeout_seconds,
            )
            return response_json, attempt
        except APIRequestError as exc:
            last_error = exc
            if exc.status_code not in RETRYABLE_STATUS_CODES or attempt >= settings.max_retries:
                raise
            time.sleep(settings.retry_backoff_seconds * attempt)
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if attempt >= settings.max_retries:
                raise
            time.sleep(settings.retry_backoff_seconds * attempt)

    raise RuntimeError(f"Request failed after retries: {last_error}")


def extract_text(response_json: dict[str, Any]) -> str:
    choices = response_json.get("choices")
    if not choices:
        return ""

    message = choices[0].get("message", {})
    content = message.get("content", "")

    if isinstance(content, str):
        return content

    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
                continue
            if isinstance(item, dict):
                text_value = item.get("text")
                if isinstance(text_value, str):
                    parts.append(text_value)
        return "\n".join(part for part in parts if part)

    return str(content)

