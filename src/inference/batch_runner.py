from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any

import aiohttp

from .config import AppConfig, RetrySettings, load_app_config
from .io_utils import (
    append_jsonl,
    build_run_paths,
    extract_text,
    iter_jsonl,
    prepare_messages,
    reset_output_file,
    setup_logger,
)
from .stats import build_status_record, summarize_status_records


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="High-concurrency OpenAI-compatible batch runner.")
    parser.add_argument("--config", default="configs/runs/default.yaml", help="Path to the YAML config file.")
    return parser


def compute_delay_seconds(retry: RetrySettings, attempt: int) -> float:
    delay = retry.initial_delay_seconds * (retry.backoff_multiplier ** max(attempt - 1, 0))
    return min(delay, retry.max_delay_seconds)


async def parse_response_body(response: aiohttp.ClientResponse) -> tuple[dict[str, Any] | None, str]:
    body_text = await response.text()
    try:
        payload = json.loads(body_text)
        if isinstance(payload, dict):
            return payload, body_text
    except json.JSONDecodeError:
        pass
    return None, body_text


async def request_with_retries(
    *,
    session: aiohttp.ClientSession,
    api_key: str,
    config: AppConfig,
    messages: list[dict[str, Any]],
    logger: logging.Logger,
    record_id: str,
) -> tuple[bool, dict[str, Any] | None, int | None, int]:
    payload: dict[str, Any] = {
        "model": config.model,
        "messages": messages,
        "stream": False,
    }
    if config.temperature is not None:
        payload["temperature"] = config.temperature
    if config.max_tokens is not None:
        payload["max_tokens"] = config.max_tokens

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    last_payload: dict[str, Any] | None = None
    last_status_code: int | None = None

    for attempt in range(1, config.retry.max_retries + 1):
        try:
            async with session.post(
                f"{config.base_url}/chat/completions",
                json=payload,
                headers=headers,
            ) as response:
                response_payload, response_text = await parse_response_body(response)
                last_payload = response_payload
                last_status_code = response.status

                if 200 <= response.status < 300:
                    return True, response_payload, response.status, attempt

                retryable = response.status in config.retry.retry_status_codes and attempt < config.retry.max_retries
                logger.warning(
                    "record=%s attempt=%s status=%s retryable=%s body=%s",
                    record_id,
                    attempt,
                    response.status,
                    retryable,
                    response_text[:500],
                )
                if not retryable:
                    return False, response_payload, response.status, attempt

        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            retryable = attempt < config.retry.max_retries
            logger.warning(
                "record=%s attempt=%s transport_error=%s retryable=%s",
                record_id,
                attempt,
                exc,
                retryable,
            )
            if not retryable:
                return False, None, None, attempt

        await asyncio.sleep(compute_delay_seconds(config.retry, attempt))

    return False, last_payload, last_status_code, config.retry.max_retries


async def process_record(
    *,
    session: aiohttp.ClientSession,
    api_key: str,
    config: AppConfig,
    logger: logging.Logger,
    output_file: Path,
    status_file: Path,
    output_lock: asyncio.Lock,
    status_lock: asyncio.Lock,
    semaphore: asyncio.Semaphore,
    status_records: list[dict[str, Any]],
    line_number: int,
    record: dict[str, Any],
) -> None:
    record_id = str(record.get("id") or f"line-{line_number}")

    try:
        messages = prepare_messages(record)
    except Exception as exc:  # noqa: BLE001
        status_record = build_status_record(
            record_id=record_id,
            status="error",
            status_code=None,
            usage=None,
            pricing=config.pricing,
        )
        async with status_lock:
            append_jsonl(status_file, status_record)
            status_records.append(status_record)
        logger.error("record=%s invalid_input=%s", record_id, exc)
        return

    async with semaphore:
        ok, response_payload, status_code, attempt = await request_with_retries(
            session=session,
            api_key=api_key,
            config=config,
            messages=messages,
            logger=logger,
            record_id=record_id,
        )

    usage = response_payload.get("usage") if isinstance(response_payload, dict) else None
    status_record = build_status_record(
        record_id=record_id,
        status="ok" if ok else "error",
        status_code=status_code,
        usage=usage,
        pricing=config.pricing,
    )

    async with status_lock:
        append_jsonl(status_file, status_record)
        status_records.append(status_record)

    if ok and isinstance(response_payload, dict):
        output_record = {
            "id": record_id,
            "output": extract_text(response_payload),
        }
        async with output_lock:
            append_jsonl(output_file, output_record)
        logger.info("record=%s status=ok attempt=%s", record_id, attempt)
        return

    logger.error("record=%s status=error attempt=%s status_code=%s", record_id, attempt, status_code)


async def run_batch(config: AppConfig, logger: logging.Logger) -> dict[str, Any]:
    api_key = os.environ.get(config.api_key_env)
    if not api_key:
        raise ValueError(f"Missing `{config.api_key_env}` in environment or provider env files.")

    run_paths = build_run_paths(config)
    reset_output_file(run_paths.output_file)
    reset_output_file(run_paths.status_file)

    records = list(iter_jsonl(config.input_path))
    logger.info(
        "loaded_records=%s input=%s provider=%s model=%s",
        len(records),
        config.input_path,
        config.provider,
        config.model,
    )

    output_lock = asyncio.Lock()
    status_lock = asyncio.Lock()
    semaphore = asyncio.Semaphore(config.concurrency)
    status_records: list[dict[str, Any]] = []

    timeout = aiohttp.ClientTimeout(total=config.timeout_seconds)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        await asyncio.gather(
            *(
                process_record(
                    session=session,
                    api_key=api_key,
                    config=config,
                    logger=logger,
                    output_file=run_paths.output_file,
                    status_file=run_paths.status_file,
                    output_lock=output_lock,
                    status_lock=status_lock,
                    semaphore=semaphore,
                    status_records=status_records,
                    line_number=line_number,
                    record=record,
                )
                for line_number, record in records
            )
        )

    summary = summarize_status_records(status_records)
    summary["output_file"] = str(run_paths.output_file)
    summary["status_file"] = str(run_paths.status_file)
    logger.info("summary=%s", json.dumps(summary, ensure_ascii=False))
    return summary


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config_path = Path(args.config)
    config = load_app_config(config_path)
    run_paths = build_run_paths(config)
    logger = setup_logger(run_paths.log_file)
    logger.info("config=%s", config_path)
    logger.info("log_file=%s", run_paths.log_file)

    summary = asyncio.run(run_batch(config, logger))
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
