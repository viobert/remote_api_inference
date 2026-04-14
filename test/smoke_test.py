"""
conda run -n inference python test/smoke_test.py \ 
    --model gpt-5.4-nano-2026-03-17
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from urllib import error, request


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ENV_FILE = REPO_ROOT / ".env"
DEFAULT_INPUT_FILE = REPO_ROOT / "data" / "input" / "smoke_test" / "smoke_test_input.jsonl"
DEFAULT_OUTPUT_FILE = REPO_ROOT / "data" / "output" / "smoke_test" / "smoke_test_output.jsonl"


def load_env_file(env_file: Path) -> None:
    if not env_file.exists():
        return

    for raw_line in env_file.read_text(encoding="utf-8").splitlines():
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


def call_vapi(*, api_key: str, base_url: str, model: str, messages: list[dict], temperature: float) -> dict:
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
        with request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc
    except error.URLError as exc:
        raise RuntimeError(f"Network error: {exc.reason}") from exc


def append_jsonl(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Simple standalone V-API smoke test.")
    parser.add_argument("--env-file", default=str(DEFAULT_ENV_FILE))
    parser.add_argument("--input", default=str(DEFAULT_INPUT_FILE))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT_FILE))
    parser.add_argument("--model", required=True)
    parser.add_argument("--temperature", type=float, default=0.2)
    args = parser.parse_args()

    load_env_file(Path(args.env_file))

    api_key = os.environ.get("VAPI_API_KEY")
    base_url = os.environ.get("VAPI_BASE_URL")
    if not api_key:
        raise ValueError("Missing VAPI_API_KEY in .env")
    if not base_url:
        raise ValueError("Missing VAPI_BASE_URL in .env")

    base_url = normalize_base_url(base_url)
    input_path = Path(args.input)
    output_path = Path(args.output)

    with output_path.open("w", encoding="utf-8") as _:
        pass

    for line_number, record in iter_jsonl(input_path):
        record_id = str(record.get("id") or f"line-{line_number}")
        messages = prepare_messages(record)
        response_json = call_vapi(
            api_key=api_key,
            base_url=base_url,
            model=args.model,
            messages=messages,
            temperature=args.temperature,
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

