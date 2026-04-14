"""
python test/smoke_test.py \
    --provider vapi \
    --model gpt-5.4-mini-low
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import socket
import sys
from urllib import error, request


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from inference.config import load_provider_config


DEFAULT_PROVIDER = "vapi"
DEFAULT_INPUT_FILE = REPO_ROOT / "data" / "input" / "smoke_test" / "smoke_test_input.jsonl"
DEFAULT_OUTPUT_FILE = REPO_ROOT / "data" / "output" / "smoke_test" / "smoke_test_output.jsonl"


def iter_jsonl(path: Path):
    with path.open("r", encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if not line:
                continue
            yield line_number, json.loads(line)


def prepare_messages(record: dict) -> list[dict]:
    if "messages" in record:
        return record["messages"]
    if "prompt" in record:
        return [{"role": "user", "content": record["prompt"]}]
    raise ValueError("Each JSONL row must contain either `prompt` or `messages`.")


def call_chat_completions(
    *,
    api_key: str,
    base_url: str,
    model: str,
    messages: list[dict],
    temperature: float,
    timeout_seconds: int,
) -> dict:
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "stream": False,
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = request.Request(
        url=f"{base_url}/chat/completions",
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with request.urlopen(req, timeout=timeout_seconds) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc
    except error.URLError as exc:
        raise RuntimeError(f"Network error: {exc.reason}") from exc
    except TimeoutError as exc:
        raise RuntimeError(f"Request timed out after {timeout_seconds}s.") from exc
    except socket.timeout as exc:
        raise RuntimeError(f"Request timed out after {timeout_seconds}s.") from exc


def append_jsonl(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Simple standalone provider smoke test.")
    parser.add_argument("--provider", default=DEFAULT_PROVIDER)
    parser.add_argument("--input", default=str(DEFAULT_INPUT_FILE))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT_FILE))
    parser.add_argument("--model", required=True)
    parser.add_argument("--temperature", type=float, default=0.2)
    parser.add_argument("--timeout", type=int, default=300)
    args = parser.parse_args()

    provider_config = load_provider_config(args.provider)
    if args.model not in provider_config.models:
        raise ValueError(f"Model `{args.model}` is not defined in provider `{provider_config.name}`.")

    api_key = os.environ.get(provider_config.api_key_env)
    if not api_key:
        raise ValueError(f"Missing `{provider_config.api_key_env}` in provider env files.")

    input_path = Path(args.input)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open("w", encoding="utf-8") as _:
        pass

    for line_number, record in iter_jsonl(input_path):
        record_id = str(record.get("id") or f"line-{line_number}")
        messages = prepare_messages(record)
        response_json = call_chat_completions(
            api_key=api_key,
            base_url=provider_config.base_url,
            model=args.model,
            messages=messages,
            temperature=args.temperature,
            timeout_seconds=args.timeout,
        )

        output_record = {
            "id": record_id,
            "response": response_json,
        }
        append_jsonl(output_path, output_record)
        print(json.dumps(output_record, ensure_ascii=False, indent=2))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
