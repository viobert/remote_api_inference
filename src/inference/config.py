from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Any, Iterable

import yaml


@dataclass(slots=True)
class RetrySettings:
    max_retries: int
    initial_delay_seconds: float
    backoff_multiplier: float
    max_delay_seconds: float
    retry_status_codes: set[int]


@dataclass(slots=True)
class Pricing:
    input_per_1k_usd: float | None
    output_per_1k_usd: float | None


@dataclass(slots=True)
class ProviderConfig:
    name: str
    env_files: tuple[Path, ...]
    api_key_env: str
    base_url: str
    models: dict[str, Pricing]


@dataclass(slots=True)
class AppConfig:
    provider: str
    env_files: tuple[Path, ...]
    api_key_env: str
    base_url: str
    input_path: Path
    output_root: Path
    log_root: Path
    model: str
    pricing: Pricing
    temperature: float | None
    max_tokens: int | None
    concurrency: int
    timeout_seconds: int
    retry: RetrySettings


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a YAML mapping.")
    return data


def load_dotenv(env_files: Iterable[Path]) -> None:
    for path in env_files:
        if not path.exists():
            continue

        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            key, sep, value = line.partition("=")
            if not sep:
                continue
            os.environ.setdefault(key.strip(), value.strip().strip("'\""))


def normalize_base_url(raw_base_url: str) -> str:
    base_url = raw_base_url.strip().rstrip("/")
    if not base_url.endswith("/v1"):
        base_url = f"{base_url}/v1"
    return base_url


def _to_optional_float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


def _to_path_tuple(value: Any) -> tuple[Path, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (Path(value),)
    if isinstance(value, list):
        paths: list[Path] = []
        for item in value:
            if item:
                paths.append(Path(str(item)))
        return tuple(paths)
    raise ValueError("`env_file` or `env_files` must be a string or a list of strings.")


def _resolve_provider_path(provider_value: str, config_path: Path | None) -> Path:
    direct_path = Path(provider_value)
    if direct_path.suffix in {".yaml", ".yml"} or direct_path.exists():
        return direct_path

    candidates = [Path("configs/providers") / f"{provider_value}.yaml"]
    if config_path is not None:
        candidates.extend(
            [
                config_path.parent / "providers" / f"{provider_value}.yaml",
                config_path.parent.parent / "providers" / f"{provider_value}.yaml",
            ]
        )

    for candidate in candidates:
        if candidate.exists():
            return candidate

    raise ValueError(f"Cannot find provider config for `{provider_value}`.")


def _load_model_pricing(provider_path: Path, model_name: str, model_raw: Any) -> Pricing:
    if not isinstance(model_raw, dict):
        raise ValueError(f"Model `{model_name}` in {provider_path} must be a mapping.")

    pricing_raw = model_raw.get("pricing")
    if pricing_raw is None:
        pricing_raw = model_raw
    if not isinstance(pricing_raw, dict):
        raise ValueError(f"Model `{model_name}` pricing in {provider_path} must be a mapping.")

    return Pricing(
        input_per_1k_usd=_to_optional_float(pricing_raw.get("input_per_1k_usd")),
        output_per_1k_usd=_to_optional_float(pricing_raw.get("output_per_1k_usd")),
    )


def load_provider_config(provider_value: str, config_path: Path | None = None) -> ProviderConfig:
    provider_path = _resolve_provider_path(provider_value, config_path)
    raw = load_yaml(provider_path)

    api_raw = raw.get("api") or {}
    if not isinstance(api_raw, dict):
        raise ValueError(f"`api` in {provider_path} must be a mapping.")

    env_files = _to_path_tuple(api_raw.get("env_files", api_raw.get("env_file")))
    load_dotenv(env_files)

    api_key_env = str(api_raw.get("api_key_env") or "").strip()
    if not api_key_env:
        raise ValueError(f"Missing `api.api_key_env` in {provider_path}.")

    base_url_env = str(api_raw.get("base_url_env") or "").strip()
    base_url_value = os.environ.get(base_url_env) if base_url_env else None
    base_url_value = base_url_value or api_raw.get("base_url")
    if not base_url_value:
        raise ValueError(
            f"Missing base URL for provider `{provider_value}`. "
            f"Set `{base_url_env}` or fill `api.base_url` in {provider_path}."
        )

    models_raw = raw.get("models") or {}
    if not isinstance(models_raw, dict) or not models_raw:
        raise ValueError(f"Missing `models` in {provider_path}.")

    models = {
        str(model_name): _load_model_pricing(provider_path, str(model_name), model_raw)
        for model_name, model_raw in models_raw.items()
    }

    return ProviderConfig(
        name=str(raw.get("name") or provider_path.stem),
        env_files=env_files,
        api_key_env=api_key_env,
        base_url=normalize_base_url(str(base_url_value)),
        models=models,
    )


def load_app_config(config_path: Path) -> AppConfig:
    raw = load_yaml(config_path)
    retry_raw = raw.get("retry") or {}

    provider_value = str(raw.get("provider") or "").strip()
    if not provider_value:
        raise ValueError("Missing `provider` in config.")

    provider_config = load_provider_config(provider_value, config_path)

    model = raw.get("model")
    if not model:
        raise ValueError("Missing `model` in config.")
    model_name = str(model)

    pricing = provider_config.models.get(model_name)
    if pricing is None:
        raise ValueError(f"Model `{model_name}` is not defined in provider `{provider_config.name}`.")

    input_value = raw.get("input_path")
    if not input_value:
        raise ValueError("Missing `input_path` in config.")
    input_path = Path(str(input_value))

    return AppConfig(
        provider=provider_config.name,
        env_files=provider_config.env_files,
        api_key_env=provider_config.api_key_env,
        base_url=provider_config.base_url,
        input_path=input_path,
        output_root=Path(raw.get("output_root", "data/output")),
        log_root=Path(raw.get("log_root", "log")),
        model=model_name,
        pricing=pricing,
        temperature=raw.get("temperature"),
        max_tokens=raw.get("max_tokens"),
        concurrency=int(raw.get("concurrency", 1)),
        timeout_seconds=int(raw.get("timeout_seconds", 120)),
        retry=RetrySettings(
            max_retries=int(retry_raw.get("max_retries", 5)),
            initial_delay_seconds=float(retry_raw.get("initial_delay_seconds", 1)),
            backoff_multiplier=float(retry_raw.get("backoff_multiplier", 2)),
            max_delay_seconds=float(retry_raw.get("max_delay_seconds", 16)),
            retry_status_codes={int(code) for code in retry_raw.get("retry_status_codes", [408, 409, 429, 500, 502, 503, 504])},
        ),
    )
