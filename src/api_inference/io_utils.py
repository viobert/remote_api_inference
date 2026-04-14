from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterator


def ensure_parent_dir(path: str | Path) -> None:
    Path(path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)


def iter_jsonl(path: str | Path) -> Iterator[tuple[int, dict[str, Any]]]:
    file_path = Path(path)
    with file_path.open("r", encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if not line:
                continue
            data = json.loads(line)
            if not isinstance(data, dict):
                raise ValueError(f"Line {line_number} in {file_path} is not a JSON object.")
            yield line_number, data


def append_jsonl(path: str | Path, record: dict[str, Any]) -> None:
    ensure_parent_dir(path)
    with Path(path).open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def load_seen_ids(path: str | Path) -> set[str]:
    file_path = Path(path)
    if not file_path.exists():
        return set()

    seen_ids: set[str] = set()
    for _, record in iter_jsonl(file_path):
        if record.get("status") != "ok":
            continue
        record_id = record.get("id")
        if record_id is not None:
            seen_ids.add(str(record_id))
    return seen_ids


def prepare_messages(record: dict[str, Any], system_prompt: str | None = None) -> list[dict[str, Any]]:
    if "messages" in record:
        messages = record["messages"]
        if not isinstance(messages, list) or not messages:
            raise ValueError("`messages` must be a non-empty list.")
    elif "prompt" in record:
        messages = [{"role": "user", "content": record["prompt"]}]
    else:
        raise ValueError("Each input row must contain either `prompt` or `messages`.")

    if system_prompt:
        return [{"role": "system", "content": system_prompt}, *messages]
    return messages

