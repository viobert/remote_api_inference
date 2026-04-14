from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path


DEFAULT_TIMEOUT_SECONDS = 120
DEFAULT_MAX_RETRIES = 3
DEFAULT_RETRY_BACKOFF_SECONDS = 2.0


@dataclass(slots=True)
class Settings:
    api_key: str
    base_url: str
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS
    max_retries: int = DEFAULT_MAX_RETRIES
    retry_backoff_seconds: float = DEFAULT_RETRY_BACKOFF_SECONDS


def load_dotenv(env_file: str | None) -> None:
    if not env_file:
        return

    path = Path(env_file)
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        key, sep, value = line.partition("=")
        if not sep:
            continue
        key = key.strip()
        value = value.strip()
        if value and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ.setdefault(key, value)


def normalize_base_url(base_url: str) -> str:
    normalized = base_url.strip().rstrip("/")
    if not normalized:
        raise ValueError("Missing VAPI_BASE_URL.")
    if not normalized.endswith("/v1"):
        normalized = f"{normalized}/v1"
    return normalized


def load_settings(
    env_file: str | None = ".env",
    base_url: str | None = None,
    timeout_seconds: int | None = None,
    max_retries: int | None = None,
) -> Settings:
    load_dotenv(env_file)

    api_key = os.environ.get("VAPI_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("Missing VAPI_API_KEY. Put it in .env or export it in your shell.")

    raw_base_url = base_url or os.environ.get("VAPI_BASE_URL")
    if not raw_base_url:
        raise ValueError("Missing VAPI_BASE_URL. Put it in .env or pass --base-url.")

    return Settings(
        api_key=api_key,
        base_url=normalize_base_url(raw_base_url),
        timeout_seconds=timeout_seconds or DEFAULT_TIMEOUT_SECONDS,
        max_retries=max_retries or DEFAULT_MAX_RETRIES,
        retry_backoff_seconds=DEFAULT_RETRY_BACKOFF_SECONDS,
    )

