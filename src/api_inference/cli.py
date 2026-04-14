from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import json
import sys
import time
from typing import Any

from .config import load_settings
from .io_utils import append_jsonl, iter_jsonl, load_seen_ids, prepare_messages
from .stats import compute_stats
from .vapi_client import APIRequestError, chat_completion, extract_text, list_models


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Minimal V-API JSONL inference framework.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    models_parser = subparsers.add_parser("models", help="List models available for the current key.")
    models_parser.add_argument("--env-file", default=".env")
    models_parser.add_argument("--base-url", default=None)
    models_parser.add_argument("--timeout-seconds", type=int, default=120)

    run_parser = subparsers.add_parser("run", help="Run text inference from a JSONL file.")
    run_parser.add_argument("--env-file", default=".env")
    run_parser.add_argument("--base-url", default=None)
    run_parser.add_argument("--input", required=True)
    run_parser.add_argument("--output", required=True)
    run_parser.add_argument("--model", required=True)
    run_parser.add_argument("--system-prompt", default=None)
    run_parser.add_argument("--temperature", type=float, default=None)
    run_parser.add_argument("--max-tokens", type=int, default=None)
    run_parser.add_argument("--concurrency", type=int, default=4)
    run_parser.add_argument("--timeout-seconds", type=int, default=120)
    run_parser.add_argument("--max-retries", type=int, default=3)
    run_parser.add_argument("--no-resume", action="store_true")
    run_parser.add_argument("--max-samples", type=int, default=None)

    stats_parser = subparsers.add_parser("stats", help="Compute basic stats for an output JSONL file.")
    stats_parser.add_argument("--input", required=True)

    return parser


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def run_command(args: argparse.Namespace) -> int:
    settings = load_settings(
        env_file=args.env_file,
        base_url=args.base_url,
        timeout_seconds=args.timeout_seconds,
        max_retries=args.max_retries,
    )

    seen_ids = set() if args.no_resume else load_seen_ids(args.output)
    queue: asyncio.Queue[tuple[int, dict[str, Any]] | None] = asyncio.Queue(maxsize=max(args.concurrency * 2, 1))
    write_lock = asyncio.Lock()

    totals = {
        "queued": 0,
        "skipped": 0,
        "ok": 0,
        "error": 0,
    }

    async def producer() -> None:
        produced = 0
        for line_number, record in iter_jsonl(args.input):
            record_id = str(record.get("id") or f"line-{line_number}")
            if record_id in seen_ids:
                totals["skipped"] += 1
                continue

            queued_record = dict(record)
            queued_record["id"] = record_id
            await queue.put((line_number, queued_record))
            totals["queued"] += 1
            produced += 1

            if args.max_samples is not None and produced >= args.max_samples:
                break

        for _ in range(args.concurrency):
            await queue.put(None)

    async def worker(worker_index: int) -> None:
        del worker_index
        while True:
            item = await queue.get()
            if item is None:
                queue.task_done()
                return

            line_number, record = item
            record_id = record["id"]
            started_at = time.perf_counter()

            try:
                messages = prepare_messages(record, system_prompt=args.system_prompt)
                response_json, attempt = await asyncio.to_thread(
                    chat_completion,
                    settings,
                    model=args.model,
                    messages=messages,
                    temperature=args.temperature,
                    max_tokens=args.max_tokens,
                )
                latency_ms = int((time.perf_counter() - started_at) * 1000)
                output_record = {
                    "id": record_id,
                    "status": "ok",
                    "created_at": utc_now(),
                    "line_number": line_number,
                    "model": args.model,
                    "text": extract_text(response_json),
                    "usage": response_json.get("usage", {}),
                    "metrics": {
                        "latency_ms": latency_ms,
                        "attempt": attempt,
                    },
                    "metadata": record.get("metadata", {}),
                    "input": {
                        "messages": messages,
                    },
                    "response": response_json,
                }
                async with write_lock:
                    append_jsonl(args.output, output_record)
                totals["ok"] += 1
            except Exception as exc:  # noqa: BLE001
                latency_ms = int((time.perf_counter() - started_at) * 1000)
                error_record = {
                    "id": record_id,
                    "status": "error",
                    "created_at": utc_now(),
                    "line_number": line_number,
                    "model": args.model,
                    "metrics": {
                        "latency_ms": latency_ms,
                        "attempt": getattr(exc, "attempt", None),
                    },
                    "metadata": record.get("metadata", {}),
                    "input": {
                        "messages": record.get("messages"),
                        "prompt": record.get("prompt"),
                    },
                    "error": format_error(exc),
                }
                async with write_lock:
                    append_jsonl(args.output, error_record)
                totals["error"] += 1
            finally:
                queue.task_done()

    producer_task = asyncio.create_task(producer())
    worker_tasks = [asyncio.create_task(worker(index)) for index in range(args.concurrency)]

    await producer_task
    await queue.join()
    await asyncio.gather(*worker_tasks)

    summary = {
        "input": args.input,
        "output": args.output,
        "model": args.model,
        "queued": totals["queued"],
        "skipped": totals["skipped"],
        "ok": totals["ok"],
        "error": totals["error"],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def format_error(exc: Exception) -> dict[str, Any]:
    if isinstance(exc, APIRequestError):
        return {
            "type": "APIRequestError",
            "message": str(exc),
            "status_code": exc.status_code,
            "body": exc.body,
        }
    return {
        "type": exc.__class__.__name__,
        "message": str(exc),
    }


def models_command(args: argparse.Namespace) -> int:
    settings = load_settings(
        env_file=args.env_file,
        base_url=args.base_url,
        timeout_seconds=args.timeout_seconds,
    )
    payload = list_models(settings)
    data = payload.get("data", [])

    if not data:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    for item in data:
        model_id = item.get("id")
        owned_by = item.get("owned_by")
        if model_id:
            print(f"{model_id}\t{owned_by}")
    return 0


def stats_command(args: argparse.Namespace) -> int:
    summary = compute_stats(args.input)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "run":
        return asyncio.run(run_command(args))
    if args.command == "models":
        return models_command(args)
    if args.command == "stats":
        return stats_command(args)

    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    sys.exit(main())

