from __future__ import annotations

from collections import Counter
from typing import Any

from .io_utils import iter_jsonl


def compute_stats(path: str) -> dict[str, Any]:
    total = 0
    ok = 0
    error = 0
    latency_values: list[int] = []
    total_prompt_tokens = 0
    total_completion_tokens = 0
    total_tokens = 0
    error_types: Counter[str] = Counter()
    model_counter: Counter[str] = Counter()

    for _, record in iter_jsonl(path):
        total += 1
        status = record.get("status")
        if status == "ok":
            ok += 1
        else:
            error += 1
            error_type = ((record.get("error") or {}).get("type")) or "UnknownError"
            error_types[error_type] += 1

        model = record.get("model")
        if model:
            model_counter[str(model)] += 1

        metrics = record.get("metrics") or {}
        latency_ms = metrics.get("latency_ms")
        if isinstance(latency_ms, (int, float)):
            latency_values.append(int(latency_ms))

        usage = record.get("usage") or {}
        total_prompt_tokens += int(usage.get("prompt_tokens", 0) or 0)
        total_completion_tokens += int(usage.get("completion_tokens", 0) or 0)
        total_tokens += int(usage.get("total_tokens", 0) or 0)

    average_latency_ms = round(sum(latency_values) / len(latency_values), 2) if latency_values else None

    return {
        "total_records": total,
        "ok_records": ok,
        "error_records": error,
        "success_rate": round(ok / total, 4) if total else None,
        "average_latency_ms": average_latency_ms,
        "prompt_tokens": total_prompt_tokens,
        "completion_tokens": total_completion_tokens,
        "total_tokens": total_tokens,
        "models": dict(model_counter),
        "error_types": dict(error_types),
    }

