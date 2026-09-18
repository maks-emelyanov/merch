from __future__ import annotations

import math

from merch.schemas import Channel, PriceQuote


def round_up_to_99(cents: float) -> int:
    """Return the smallest whole-dollar .99 price greater than or equal to cents."""
    if cents < 0:
        raise ValueError("price cannot be negative")
    return math.ceil((cents + 1) / 100) * 100 - 1


def quote_price(
    *,
    channel: Channel,
    variant_id: int,
    production_cost_cents: int,
    percent_fee: float,
    fixed_fee_cents: int,
    target_margin: float = 0.40,
) -> PriceQuote:
    denominator = 1 - percent_fee - target_margin
    if denominator <= 0:
        raise ValueError("fee and target margin leave no room for a valid price")
    raw = (production_cost_cents + fixed_fee_cents) / denominator
    retail = round_up_to_99(raw)
    fee = round(retail * percent_fee) + fixed_fee_cents
    margin = (retail - production_cost_cents - fee) / retail
    return PriceQuote(
        channel=channel,
        variant_id=variant_id,
        production_cost_cents=production_cost_cents,
        retail_price_cents=retail,
        estimated_fee_cents=fee,
        estimated_margin=margin,
    )
