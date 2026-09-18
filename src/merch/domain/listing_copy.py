"""Normalize and validate shopper-facing marketplace copy."""

from __future__ import annotations

import re

from merch.schemas import Channel, MarketplaceListingSet

ETSY_DISCLOSURE = (
    "Seller-prompted AI assisted the original artwork; Printify is the production partner."
)


def normalize_listing_copy(listings: MarketplaceListingSet) -> MarketplaceListingSet:
    normalized = []
    for listing in listings.listings:
        if listing.channel == Channel.ETSY and (
            "seller-prompted ai" not in listing.long_description.casefold()
            or "printify" not in listing.long_description.casefold()
        ):
            listing = listing.model_copy(
                update={"long_description": f"{listing.long_description.rstrip()}\n\n{ETSY_DISCLOSURE}"}
            )
        normalized.append(listing)
    return MarketplaceListingSet(listings=normalized)


def validate_listing_copy(listings: MarketplaceListingSet) -> None:
    for listing in listings.listings:
        if not listing.title.strip() or not listing.long_description.strip():
            raise ValueError(f"{listing.channel.value} title and description must be nonempty")
        if not listing.short_description.strip() or not listing.alt_text.strip():
            raise ValueError(f"{listing.channel.value} short description and alt text are required")
        if not listing.seo_meta_title.strip() or not listing.seo_meta_description.strip():
            raise ValueError(f"{listing.channel.value} SEO title and description are required")
        if len({tag.strip().casefold() for tag in listing.tags}) != len(listing.tags):
            raise ValueError(f"{listing.channel.value} tags must be unique")
        if listing.channel == Channel.ETSY:
            if len(listing.title) > 140:
                raise ValueError("Etsy title exceeds 140 characters")
            if len(listing.tags) > 13:
                raise ValueError("Etsy has more than 13 tags")
            if any(not tag.strip() or len(tag) > 20 for tag in listing.tags):
                raise ValueError("Etsy tags must contain 1-20 characters")
            if any(not re.fullmatch(r"[\w\s'-]+", tag, re.UNICODE) for tag in listing.tags):
                raise ValueError("Etsy tags contain unsupported characters")
            if (
                "seller-prompted ai" not in listing.long_description.casefold()
                or "printify" not in listing.long_description.casefold()
            ):
                raise ValueError("Etsy disclosure is missing")
        if listing.channel == Channel.AMAZON_US and len(listing.title) > 75:
            raise ValueError("Amazon title exceeds 75 characters")
