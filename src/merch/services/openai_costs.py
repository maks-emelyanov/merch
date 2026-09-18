from __future__ import annotations

from typing import Any

# USD per million tokens, from OpenAI API pricing on 2026-09-17.
# These are estimates for standard requests; the organization invoice is authoritative.
TEXT_RATES: dict[str, tuple[float, float, float, float]] = {
    "gpt-6-astra": (10.0, 1.0, 12.5, 50.0),
    "gpt-5.6-sol": (4.0, 0.4, 5.0, 20.0),
    "gpt-5.6-terra": (2.0, 0.2, 2.5, 12.0),
    "gpt-5.6-luna": (0.2, 0.02, 0.25, 1.2),
}
IMAGE_RATES: dict[str, tuple[float, float, float]] = {
    "gpt-image-2.5-sunburst": (5.0, 8.0, 30.0),
    "gpt-image-2.5-flare": (5.0, 8.0, 30.0),
    "gpt-image-2": (2.5, 4.0, 15.0),
}
WEB_SEARCH_USD = 0.01


def _base_model(model: str) -> str:
    for name in (*TEXT_RATES, *IMAGE_RATES):
        if model == name or model.startswith(f"{name}-2026-"):
            return name
    return model


def estimate_text_cost(
    model: str, usage: dict[str, Any] | None, web_search_calls: int = 0
) -> float | None:
    rates = TEXT_RATES.get(_base_model(model))
    if rates is None or usage is None:
        return None
    input_rate, cached_rate, cache_write_rate, output_rate = rates
    input_tokens = int(usage.get("input_tokens") or 0)
    details = usage.get("input_tokens_details") or {}
    cached = min(input_tokens, int(details.get("cached_tokens") or 0))
    cache_write = min(input_tokens - cached, int(details.get("cache_write_tokens") or 0))
    ordinary = max(0, input_tokens - cached - cache_write)
    output_tokens = int(usage.get("output_tokens") or 0)
    return round(
        (
            ordinary * input_rate
            + cached * cached_rate
            + cache_write * cache_write_rate
            + output_tokens * output_rate
        )
        / 1_000_000
        + web_search_calls * WEB_SEARCH_USD,
        6,
    )


def estimate_image_cost(model: str, usage: dict[str, Any] | None) -> float | None:
    rates = IMAGE_RATES.get(_base_model(model))
    if rates is None or usage is None:
        return None
    text_rate, image_input_rate, image_output_rate = rates
    input_details = usage.get("input_tokens_details") or {}
    output_details = usage.get("output_tokens_details") or {}
    text_input = int(input_details.get("text_tokens") or 0)
    image_input = int(input_details.get("image_tokens") or 0)
    image_output = int(output_details.get("image_tokens") or usage.get("output_tokens") or 0)
    return round(
        (text_input * text_rate + image_input * image_input_rate + image_output * image_output_rate)
        / 1_000_000,
        6,
    )


def summarize_costs(calls: list[dict[str, Any]]) -> dict[str, Any]:
    stages: dict[str, dict[str, Any]] = {}
    total = 0.0
    unpriced = 0
    for call in calls:
        stage = str(call.get("stage") or "unknown")
        summary = stages.setdefault(stage, {"calls": 0, "estimated_usd": 0.0, "unpriced": 0})
        summary["calls"] += 1
        estimate = call.get("estimated_cost_usd")
        if estimate is None:
            if call.get("model") not in {"fixture", "deterministic"}:
                summary["unpriced"] += 1
                unpriced += 1
        else:
            amount = float(estimate)
            summary["estimated_usd"] += amount
            total += amount
    for summary in stages.values():
        summary["estimated_usd"] = round(summary["estimated_usd"], 4)
    return {
        "estimated_usd": round(total, 4),
        "unpriced_calls": unpriced,
        "stages": stages,
    }
