from __future__ import annotations

import pytest

from merch.services.analytics import parse_etsy_stats_csv


def test_etsy_csv_normalizes_nullable_funnel_metrics() -> None:
    rows = parse_etsy_stats_csv(
        b"date,listing_id,impressions,visits,favorites,cart_adds,orders,revenue\n"
        b"2026-09-10,123,100,12,3,,2,44.50\n"
    )
    assert len(rows) == 1
    assert rows[0].impressions == 100
    assert rows[0].cart_adds is None
    assert rows[0].gross_revenue_cents == 4450
    assert rows[0].completeness["cart_adds"] is False


def test_etsy_csv_rejects_unknown_shape() -> None:
    with pytest.raises(ValueError, match="date and listing_id"):
        parse_etsy_stats_csv(b"day,item\n2026-09-10,1\n")
