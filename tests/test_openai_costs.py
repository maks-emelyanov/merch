from __future__ import annotations

from merch.services.openai_costs import (
    estimate_image_cost,
    estimate_text_cost,
    summarize_costs,
)


def test_text_estimate_accounts_for_cached_tokens_and_search() -> None:
    cost = estimate_text_cost(
        "gpt-5.6-terra-2026-09-01",
        {
            "input_tokens": 1000,
            "input_tokens_details": {"cached_tokens": 400},
            "output_tokens": 200,
        },
        web_search_calls=1,
    )
    assert cost == 0.01368


def test_image_estimate_and_unpriced_calls() -> None:
    image = estimate_image_cost(
        "gpt-image-2.5-sunburst",
        {
            "input_tokens_details": {"text_tokens": 100, "image_tokens": 200},
            "output_tokens_details": {"image_tokens": 1000},
        },
    )
    assert image == 0.0321
    summary = summarize_costs(
        [
            {"stage": "artwork", "model": "gpt-image-2.5-sunburst", "estimated_cost_usd": image},
            {"stage": "artwork", "model": "gpt-image-2.5-sunburst"},
        ]
    )
    assert summary["estimated_usd"] == 0.0321
    assert summary["unpriced_calls"] == 1
