from __future__ import annotations

from typing import Any

from .config import Pricing


def _int_or_none(value: Any) -> int | None:
    if value is None:
        return None
    return int(value)


def _dict_or_empty(value: Any, field_name: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"`usage.{field_name}` must be an object when present.")
    return value


def compute_price(tokens: int | None, rate_per_1k_usd: float | None) -> float | None:
    if tokens is None or rate_per_1k_usd is None:
        return None
    return round(tokens / 1000 * rate_per_1k_usd, 10)


def build_status_record(
    *,
    record_id: str,
    status: str,
    status_code: int | None,
    usage: dict[str, Any] | None,
    pricing: Pricing,
) -> dict[str, Any]:
    if usage is None:
        usage = {}
    if not isinstance(usage, dict):
        raise ValueError("`usage` must be an object when present.")

    input_tokens = _int_or_none(usage.get("prompt_tokens"))
    output_tokens = _int_or_none(usage.get("completion_tokens"))
    total_tokens = _int_or_none(usage.get("total_tokens"))
    prompt_details = _dict_or_empty(usage.get("prompt_tokens_details"), "prompt_tokens_details")
    completion_details = _dict_or_empty(usage.get("completion_tokens_details"), "completion_tokens_details")

    input_price = compute_price(input_tokens, pricing.input_per_1k_usd)
    output_price = compute_price(output_tokens, pricing.output_per_1k_usd)
    total_price = None
    if input_price is not None or output_price is not None:
        total_price = round((input_price or 0.0) + (output_price or 0.0), 10)

    return {
        "id": record_id,
        "status": status,
        "status_code": status_code,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "input_cached_tokens": _int_or_none(prompt_details.get("cached_tokens")),
        "input_audio_tokens": _int_or_none(prompt_details.get("audio_tokens")),
        "output_reasoning_tokens": _int_or_none(completion_details.get("reasoning_tokens")),
        "output_audio_tokens": _int_or_none(completion_details.get("audio_tokens")),
        "output_accepted_prediction_tokens": _int_or_none(completion_details.get("accepted_prediction_tokens")),
        "output_rejected_prediction_tokens": _int_or_none(completion_details.get("rejected_prediction_tokens")),
        "usage": usage or None,
        "input_price_usd": input_price,
        "output_price_usd": output_price,
        "total_price_usd": total_price,
    }


def summarize_status_records(status_records: list[dict[str, Any]]) -> dict[str, Any]:
    success_count = sum(1 for record in status_records if record["status"] == "ok")
    non_success_count = len(status_records) - success_count

    input_tokens = [record["input_tokens"] for record in status_records if record["input_tokens"] is not None]
    output_tokens = [record["output_tokens"] for record in status_records if record["output_tokens"] is not None]
    total_price = sum(record["total_price_usd"] or 0.0 for record in status_records)

    return {
        "success_count": success_count,
        "non_success_count": non_success_count,
        "average_input_tokens": round(sum(input_tokens) / len(input_tokens), 4) if input_tokens else None,
        "average_output_tokens": round(sum(output_tokens) / len(output_tokens), 4) if output_tokens else None,
        "total_price_usd": round(total_price, 10),
        "priced_record_count": sum(1 for record in status_records if record["total_price_usd"] is not None),
        "total_record_count": len(status_records),
    }
