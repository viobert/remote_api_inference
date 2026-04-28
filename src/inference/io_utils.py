from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
import logging
from pathlib import Path
from typing import Any, Iterable

from .config import AppConfig


@dataclass(slots=True)
class RunPaths:
    output_file: Path
    status_file: Path
    log_file: Path


def iter_jsonl(path: Path) -> Iterable[tuple[int, dict[str, Any]]]:
    with path.open("r", encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if not line:
                continue
            record = json.loads(line)
            if not isinstance(record, dict):
                raise ValueError(f"Line {line_number} in {path} is not a JSON object.")
            yield line_number, record


def prepare_messages(record: dict[str, Any]) -> list[dict[str, Any]]:
    messages = record.get("messages")
    prompt = record.get("prompt")

    if messages is not None:
        if not isinstance(messages, list) or not messages:
            raise ValueError("`messages` must be a non-empty list.")
        return messages

    if prompt is not None:
        return [{"role": "user", "content": prompt}]

    raise ValueError("Each row must contain either `prompt` or `messages`.")


def extract_text(response_json: dict[str, Any]) -> str:
    choices = response_json.get("choices") or []
    if not choices:
        return ""

    message = choices[0].get("message") or {}
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


def model_filename_component(model: str) -> str:
    if not model:
        raise ValueError("Model name must not be empty.")
    if "/" in model or "\\" in model:
        raise ValueError(f"Model name `{model}` cannot be used in an output filename.")
    return model


def build_run_paths(config: AppConfig) -> RunPaths:
    run_timestamp = datetime.now().strftime("%y-%m-%d_%H%M%S")
    input_stem = config.input_path.stem
    model_stem = model_filename_component(config.model)
    output_dir = config.output_root / config.provider / config.model / run_timestamp
    log_dir = config.log_root / config.provider / config.model / run_timestamp
    output_dir.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)
    return RunPaths(
        output_file=output_dir / f"{input_stem}_{model_stem}_output.jsonl",
        status_file=output_dir / f"{input_stem}_status.jsonl",
        log_file=log_dir / f"{input_stem}.log",
    )


def setup_logger(log_file: Path) -> logging.Logger:
    logger = logging.getLogger("inference.batch_runner")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    logger.propagate = False

    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")

    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)
    return logger


def reset_output_file(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8"):
        pass


def append_jsonl(path: Path, record: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
