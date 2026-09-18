"""Install the vetted Bella+Canvas 3001 / SwiftPOD Etsy template.

Run with ``python -m merch.setup_etsy_tee`` inside the configured web container.
Variant IDs and front-print dimensions are checked against Printify's live catalog.
The color selection follows Printify's published sales ranking, with familiar
additional colors to cover a wider range of artwork. Garment swatches are
approximations for contrast QA; costs are the operator-reviewed Printify UI
snapshot from 2026-09-16 and should be reviewed when Printify changes prices.
"""

from __future__ import annotations

import asyncio
from typing import Any

from sqlalchemy import select

from merch.config import get_settings
from merch.database import session_scope
from merch.models import RunRecord
from merch.repository import ConfigurationRepository
from merch.schemas import Channel, ChannelConfig, ProductTemplate, RunStatus, VariantConfig
from merch.services.printify import PrintifyClient

SIZES = ("XS", "S", "M", "L", "XL", "2XL", "3XL")
COLORS = {
    "Black": "#000000",
    "White": "#FFFFFF",
    "Navy": "#1A1F35",
    "Asphalt": "#525455",
    "Dark Grey Heather": "#1C1B1C",
    "Athletic Heather": "#C7C7C5",
    "Natural": "#FFF8EA",
    "Military Green": "#515942",
    "Olive": "#414823",
    "Light Blue": "#A6BBC8",
    "Maroon": "#59242A",
    "True Royal": "#2B4DA4",
    "Red": "#BA2326",
    "Soft Pink": "#FFEAE5",
}
COST_CENTS = {
    "XS": 1175,
    "S": 1175,
    "M": 1175,
    "L": 1175,
    "XL": 1175,
    "2XL": 1437,
    "3XL": 1675,
}
ACTIVE_STATUSES = {
    RunStatus.PENDING.value,
    RunStatus.RESEARCHING.value,
    RunStatus.SCREENING.value,
    RunStatus.RANKING.value,
    RunStatus.GENERATING.value,
    RunStatus.PREPRESS.value,
    RunStatus.QA.value,
    RunStatus.AWAITING_BRIEF_REVISION.value,
    RunStatus.LISTING.value,
    RunStatus.AWAITING_APPROVAL.value,
    RunStatus.PUBLISHING.value,
    RunStatus.PARTIALLY_PUBLISHED.value,
}


def build_template(
    catalog: dict[str, Any],
    etsy_channel: ChannelConfig,
    production_partner_confirmed: bool = False,
) -> ProductTemplate:
    """Match every selected color/size to a real front-DTG catalog variant."""
    by_options = {
        (item["options"]["color"], item["options"]["size"]): item for item in catalog["variants"]
    }
    variants: list[VariantConfig] = []
    for color, color_hex in COLORS.items():
        for size in SIZES:
            remote = by_options.get((color, size))
            if remote is None:
                raise ValueError(f"SwiftPOD does not offer {color} / {size}")
            front = [
                area
                for area in remote["placeholders"]
                if area["position"] == "front" and area["decoration_method"] == "dtg"
            ]
            if len(front) != 1 or front[0]["width"] > 3692 or front[0]["height"] > 4800:
                raise ValueError(f"Unexpected front print area for {color} / {size}")
            variants.append(
                VariantConfig(
                    variant_id=remote["id"],
                    title=remote["title"],
                    color=color,
                    color_hex=color_hex,
                    size=size,
                    production_cost_cents=COST_CENTS[size],
                )
            )
    return ProductTemplate(
        name="Bella+Canvas 3001 / SwiftPOD / Etsy US / 14 colors / XS-3XL",
        blueprint_id=12,
        print_provider_id=39,
        print_width=3692,
        print_height=4800,
        variants=variants,
        featured_variant_id=next(
            item.variant_id for item in variants if item.color == "Black" and item.size == "L"
        ),
        channels=[etsy_channel],
        etsy_production_partner_confirmed=production_partner_confirmed,
    )


async def main() -> None:
    settings = get_settings()
    if not settings.printify_api_token.get_secret_value():
        raise RuntimeError("Printify API token is required to verify catalog variants")
    with session_scope() as session:
        current = ConfigurationRepository(session).get_template()
        etsy_channels = [
            item for item in current.channels if item.channel == Channel.ETSY and item.enabled
        ]
        if len(etsy_channels) != 1 or (
            settings.etsy_production_partner_check_enabled
            and not current.etsy_production_partner_confirmed
        ):
            raise RuntimeError(
                "Active Etsy shop and fees are required; production-partner confirmation is required when its check is enabled"
            )
        etsy_channel = etsy_channels[0]
        production_partner_confirmed = current.etsy_production_partner_confirmed
        active_run = session.scalar(
            select(RunRecord.id).where(RunRecord.status.in_(ACTIVE_STATUSES))
        )
        if active_run:
            raise RuntimeError(f"Resolve active run {active_run} before changing the template")
    printify = PrintifyClient(settings)
    try:
        shops, catalog = await asyncio.gather(printify.shops(), printify.variants(12, 39))
    finally:
        await printify.close()
    if not any(str(shop["id"]) == etsy_channel.printify_shop_id for shop in shops):
        raise RuntimeError("Configured Etsy Printify shop is not available to this API token")
    template = build_template(catalog, etsy_channel, production_partner_confirmed)
    assert len(template.variants) == 98
    with session_scope() as session:
        repository = ConfigurationRepository(session)
        if repository.get_template() == template:
            print("The 98-variant Etsy template is already active; no change made")
            return
        active_run = session.scalar(
            select(RunRecord.id).where(RunRecord.status.in_(ACTIVE_STATUSES))
        )
        if active_run:
            raise RuntimeError(f"Resolve active run {active_run} before changing the template")
        record = repository.save_template(template)
        print(f"Saved template v{record.version}: 14 colors x 7 sizes = 98 Etsy variants")


if __name__ == "__main__":
    asyncio.run(main())
