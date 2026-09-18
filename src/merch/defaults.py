from __future__ import annotations

from merch.schemas import Channel, ChannelConfig, ProductTemplate, VariantConfig


def fixture_product_template() -> ProductTemplate:
    return ProductTemplate(
        name="Fixture Unisex DTG Tee",
        blueprint_id=6,
        print_provider_id=1,
        print_width=3153,
        print_height=3995,
        variants=[
            VariantConfig(
                variant_id=1001,
                title="Black / M",
                color="#111827",
                size="M",
                production_cost_cents=950,
            ),
            VariantConfig(
                variant_id=1002,
                title="Forest / L",
                color="#1F3A32",
                size="L",
                production_cost_cents=1050,
            ),
        ],
        channels=[
            ChannelConfig(
                channel=Channel.SHOPIFY,
                printify_shop_id="fixture-shopify",
                percent_fee=0.03,
                fixed_fee_cents=30,
            ),
            ChannelConfig(
                channel=Channel.ETSY,
                printify_shop_id="fixture-etsy",
                percent_fee=0.10,
                fixed_fee_cents=45,
            ),
            ChannelConfig(
                channel=Channel.AMAZON_US,
                printify_shop_id="fixture-amazon",
                percent_fee=0.15,
                fixed_fee_cents=0,
            ),
        ],
        etsy_production_partner_confirmed=True,
    )
