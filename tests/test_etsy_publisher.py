from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace

import pytest

from merch.defaults import fixture_product_template
from merch.schemas import Channel, EtsyListingDefaults, MarketplaceListing, PriceQuote
from merch.services.etsy_publisher import direct_inventory, publish_direct_etsy
from merch.services.storefront import StorefrontVerificationError


def fixtures():  # type: ignore[no-untyped-def]
    template = fixture_product_template().model_copy(update={"featured_variant_id": 1001})
    defaults = EtsyListingDefaults(
        taxonomy_id=482, shipping_profile_id=11, return_policy_id=12,
        readiness_state_id=13, production_partner_ids=[14],
    )
    listing = MarketplaceListing(
        channel=Channel.ETSY, title="Original forest shirt", short_description="A shirt",
        long_description="An original forest shirt made by Printify.",
        tags=["forest", "shirt"], bullet_points=[], alt_text="Forest design",
        target_customer="Hikers", gift_occasions=[], seo_meta_title="Forest shirt",
        seo_meta_description="Forest shirt",
    )
    quotes = [
        PriceQuote(channel=Channel.ETSY, variant_id=variant.variant_id,
                   production_cost_cents=variant.production_cost_cents,
                   retail_price_cents=2599 if variant.variant_id == 1001 else 3099,
                   estimated_fee_cents=300, estimated_margin=0.4)
        for variant in template.variants
    ]
    product = {
        "id": "printify-1", "is_locked": False, "external": None,
        "variants": [
            {"id": 1001, "sku": "black-m", "is_enabled": True, "is_default": True, "price": 2599},
            {"id": 1002, "sku": "forest-l", "is_enabled": True, "is_default": False, "price": 3099},
        ],
        "images": [
            {"mockup_id": "product_1001_front", "position": "front",
             "src": "https://images.printify.com/black.jpg"},
            {"mockup_id": "product_1002_front", "position": "front",
             "src": "https://images.printify.com/forest.jpg"},
        ],
    }
    return template, defaults, listing, quotes, product


class FakeEtsy:
    def __init__(self) -> None:
        self.settings = SimpleNamespace(etsy_shop_id=42)
        self.remote: dict[str, object] | None = None
        self.inventory_data: dict[str, object] = {"products": []}
        self.photos: list[dict[str, object]] = []
        self.links: list[dict[str, int]] = []
        self.creates = 0

    async def shop_listings(self, state):  # type: ignore[no-untyped-def]
        return [deepcopy(self.remote)] if self.remote and self.remote["state"] == state else []

    async def listing(self, listing_id):  # type: ignore[no-untyped-def]
        assert self.remote and listing_id == self.remote["listing_id"]
        return deepcopy(self.remote)

    async def create_draft(self, payload):  # type: ignore[no-untyped-def]
        self.creates += 1
        self.remote = {
            "listing_id": 99, "shop_id": 42, "state": "draft", "title": payload["title"],
            "description": payload["description"], "taxonomy_id": int(payload["taxonomy_id"]),
            "tags": [], "url": "https://www.etsy.com/listing/99",
        }
        return deepcopy(self.remote)

    async def update_listing(self, listing_id, payload):  # type: ignore[no-untyped-def]
        assert self.remote and listing_id == 99
        if "tags" in payload:
            self.remote["tags"] = payload["tags"].split(",")
        if "state" in payload:
            self.remote["state"] = payload["state"]
        return deepcopy(self.remote)

    async def inventory(self, listing_id):  # type: ignore[no-untyped-def]
        assert listing_id == 99
        return deepcopy(self.inventory_data)

    async def update_inventory(self, listing_id, payload):  # type: ignore[no-untyped-def]
        assert listing_id == 99
        products = []
        for item in payload["products"]:
            props = deepcopy(item["property_values"])
            for prop in props:
                prop["value_ids"] = [abs(hash(prop["values"][0])) % 10000 + 1]
            offering = deepcopy(item["offerings"][0])
            offering["price"] = {
                "amount": round(offering["price"] * 100),
                "divisor": 100, "currency_code": "USD",
            }
            products.append({"sku": item["sku"], "property_values": props,
                             "offerings": [offering]})
        self.inventory_data = {"products": products}

    async def images(self, listing_id):  # type: ignore[no-untyped-def]
        assert listing_id == 99
        return deepcopy(self.photos)

    async def upload_mockup(self, listing_id, image, content_type, alt_text, rank):  # type: ignore[no-untyped-def]
        assert listing_id == 99 and image == b"mockup" and content_type == "image/jpeg"
        image_id = 100 + len(self.photos)
        self.photos.append({"listing_image_id": image_id, "rank": rank, "alt_text": alt_text})
        return image_id

    async def variation_images(self, listing_id):  # type: ignore[no-untyped-def]
        assert listing_id == 99
        return deepcopy(self.links)

    async def update_variation_images(self, listing_id, images):  # type: ignore[no-untyped-def]
        assert listing_id == 99
        self.links = deepcopy(images)


class FakePrintify:
    def __init__(self, product, *, fail_link=False):  # type: ignore[no-untyped-def]
        self.remote = deepcopy(product)
        self.publishes = 0
        self.fail_link = fail_link

    async def product(self, shop_id, product_id):  # type: ignore[no-untyped-def]
        assert shop_id == "fixture-etsy" and product_id == "printify-1"
        return deepcopy(self.remote)

    async def publish(self, shop_id, product_id):  # type: ignore[no-untyped-def]
        self.publishes += 1
        return {}

    async def publishing_succeeded(self, shop_id, product_id, listing_id, handle):  # type: ignore[no-untyped-def]
        if self.fail_link:
            raise RuntimeError("Printify refused link")
        self.remote["external"] = {"id": str(listing_id), "handle": handle}


@pytest.mark.asyncio
async def test_direct_etsy_fallback_is_resumable_and_links_the_full_listing(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    async def mockup(_url):  # type: ignore[no-untyped-def]
        return b"mockup", "image/jpeg"

    monkeypatch.setattr("merch.services.etsy_publisher.download_mockup", mockup)
    template, defaults, listing, quotes, product = fixtures()
    etsy, printify = FakeEtsy(), FakePrintify(product)
    progress: dict[str, object] = {}

    def checkpoint(**updates):  # type: ignore[no-untyped-def]
        progress.update(deepcopy(updates))

    for _ in range(2):
        linked, featured_id, color_ids = await publish_direct_etsy(
            etsy, printify, "fixture-etsy", "printify-1", product,
            template, listing, quotes, defaults, progress, checkpoint,
        )
        assert linked["external"]["id"] == "99"
        assert featured_id == color_ids[template.featured_variant().color]
    assert etsy.creates == 1
    assert len(etsy.photos) == 2
    assert len(etsy.links) == 2
    assert etsy.remote["state"] == "active"
    assert etsy.remote["tags"] == listing.tags
    assert printify.publishes == 1
    assert progress["stage"] == "printify_link_verified"


@pytest.mark.asyncio
async def test_direct_etsy_uses_selected_color_as_first_photo(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    async def mockup(_url):  # type: ignore[no-untyped-def]
        return b"mockup", "image/jpeg"

    monkeypatch.setattr("merch.services.etsy_publisher.download_mockup", mockup)
    template, defaults, listing, quotes, product = fixtures()
    template = template.model_copy(update={"featured_variant_id": 1002})
    product["variants"][0]["is_default"] = False
    product["variants"][1]["is_default"] = True
    etsy, printify = FakeEtsy(), FakePrintify(product)
    _, featured_id, color_ids = await publish_direct_etsy(
        etsy, printify, "fixture-etsy", "printify-1", product,
        template, listing, quotes, defaults, {}, lambda **updates: None,
    )
    assert featured_id == color_ids["#1F3A32"] == 100
    assert etsy.photos[0]["rank"] == 1


@pytest.mark.asyncio
async def test_direct_etsy_fallback_stops_on_ambiguous_listing() -> None:
    template, defaults, listing, quotes, product = fixtures()
    etsy, printify = FakeEtsy(), FakePrintify(product)
    etsy.remote = {
        "listing_id": 99, "shop_id": 42, "state": "draft", "title": listing.title,
        "description": "Different product", "taxonomy_id": 482, "tags": [],
    }
    with pytest.raises(StorefrontVerificationError, match="not the approved product"):
        await publish_direct_etsy(
            etsy, printify, "fixture-etsy", "printify-1", product,
            template, listing, quotes, defaults, {}, lambda **updates: None,
        )
    assert etsy.creates == 0


@pytest.mark.asyncio
async def test_direct_etsy_fallback_adopts_matching_active_listing_without_new_photos() -> None:
    template, defaults, listing, quotes, product = fixtures()
    etsy, printify = FakeEtsy(), FakePrintify(product)
    await etsy.create_draft({
        "title": listing.title, "description": listing.long_description,
        "taxonomy_id": defaults.taxonomy_id,
    })
    await etsy.update_inventory(99, direct_inventory(product, template, quotes, defaults))
    etsy.remote["state"] = "active"
    etsy.photos = [{"listing_image_id": 77, "rank": 1, "alt_text": "Existing mockup"}]
    progress: dict[str, object] = {}

    def checkpoint(**updates):  # type: ignore[no-untyped-def]
        progress.update(updates)

    linked, featured_id, color_ids = await publish_direct_etsy(
        etsy, printify, "fixture-etsy", "printify-1", product,
        template, listing, quotes, defaults, progress, checkpoint,
    )
    assert linked["external"]["id"] == "99"
    assert featured_id == 0 and color_ids == {}
    assert etsy.creates == 1 and len(etsy.photos) == 1
    assert progress["stage"] == "adopted_existing_listing"


@pytest.mark.asyncio
async def test_direct_etsy_fallback_deactivates_run_owned_listing_if_link_fails(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    async def mockup(_url):  # type: ignore[no-untyped-def]
        return b"mockup", "image/jpeg"

    monkeypatch.setattr("merch.services.etsy_publisher.download_mockup", mockup)
    template, defaults, listing, quotes, product = fixtures()
    etsy, printify = FakeEtsy(), FakePrintify(product, fail_link=True)
    progress: dict[str, object] = {}

    def checkpoint(**updates):  # type: ignore[no-untyped-def]
        progress.update(deepcopy(updates))

    with pytest.raises(StorefrontVerificationError, match="link could not be confirmed"):
        await publish_direct_etsy(
            etsy, printify, "fixture-etsy", "printify-1", product,
            template, listing, quotes, defaults, progress, checkpoint,
        )
    assert etsy.remote["state"] == "inactive"
    assert progress["stage"] == "link_failed_listing_inactive"


@pytest.mark.asyncio
async def test_direct_etsy_fallback_deactivates_if_printify_links_another_listing(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    async def mockup(_url):  # type: ignore[no-untyped-def]
        return b"mockup", "image/jpeg"

    monkeypatch.setattr("merch.services.etsy_publisher.download_mockup", mockup)
    template, defaults, listing, quotes, product = fixtures()
    etsy, printify = FakeEtsy(), FakePrintify(product)
    printify.remote["external"] = {"id": "different"}
    progress: dict[str, object] = {}

    def checkpoint(**updates):  # type: ignore[no-untyped-def]
        progress.update(updates)

    with pytest.raises(StorefrontVerificationError, match="different Etsy listing"):
        await publish_direct_etsy(
            etsy, printify, "fixture-etsy", "printify-1", product,
            template, listing, quotes, defaults, progress, checkpoint,
        )
    assert etsy.remote["state"] == "inactive"
    assert progress["stage"] == "link_mismatch_listing_inactive"


@pytest.mark.asyncio
async def test_direct_etsy_fallback_does_not_repeat_unknown_image_upload() -> None:
    template, defaults, listing, quotes, product = fixtures()
    etsy, printify = FakeEtsy(), FakePrintify(product)
    await etsy.create_draft({
        "title": listing.title, "description": listing.long_description,
        "taxonomy_id": defaults.taxonomy_id,
    })
    await etsy.update_inventory(99, direct_inventory(product, template, quotes, defaults))
    featured_color = template.featured_variant().color
    progress = {
        "etsy_listing_id": 99, "etsy_listing_owned": True,
        "image_upload_started_color": featured_color,
    }
    with pytest.raises(StorefrontVerificationError, match="outcome is unknown"):
        await publish_direct_etsy(
            etsy, printify, "fixture-etsy", "printify-1", product,
            template, listing, quotes, defaults, progress, lambda **updates: None,
        )
    assert etsy.photos == []


@pytest.mark.asyncio
async def test_direct_etsy_fallback_deactivates_when_activation_readback_fails(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    async def mockup(_url):  # type: ignore[no-untyped-def]
        return b"mockup", "image/jpeg"

    class UnconfirmedEtsy(FakeEtsy):
        async def listing(self, listing_id):  # type: ignore[no-untyped-def]
            if self.remote and self.remote["state"] == "active":
                raise RuntimeError("Etsy read failed")
            return await super().listing(listing_id)

    monkeypatch.setattr("merch.services.etsy_publisher.download_mockup", mockup)
    template, defaults, listing, quotes, product = fixtures()
    etsy, printify = UnconfirmedEtsy(), FakePrintify(product)
    progress: dict[str, object] = {}

    def checkpoint(**updates):  # type: ignore[no-untyped-def]
        progress.update(updates)

    with pytest.raises(StorefrontVerificationError, match="activation could not be confirmed"):
        await publish_direct_etsy(
            etsy, printify, "fixture-etsy", "printify-1", product,
            template, listing, quotes, defaults, progress, checkpoint,
        )
    assert etsy.remote["state"] == "inactive"
    assert progress["stage"] == "activation_unverified_listing_inactive"
