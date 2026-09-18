"""Rank the final print design on the garment colors approved for this run."""

from __future__ import annotations

import hashlib
import io
import json
import math
from typing import Any, cast

from PIL import Image, ImageColor, ImageDraw, ImageFont

from merch.schemas import ProductTemplate, ShirtColorRanking, VariantConfig


def color_candidates(
    template: ProductTemplate, preferred_size: str | None = None
) -> list[dict[str, Any]]:
    """Use one variant per color, retaining the catalog's preferred size."""
    preferred_size = preferred_size or template.featured_variant().size
    colors = sorted({item.color for item in template.variants if item.enabled})
    result: list[dict[str, Any]] = []
    for index, color in enumerate(colors, 1):
        variants = [item for item in template.variants if item.enabled and item.color == color]
        variant = min(
            variants,
            key=lambda item: (item.size != preferred_size, item.variant_id),
        )
        result.append(
            {
                "candidate_id": index,
                "color": color,
                "color_hex": variant.color_hex or color,
                "variant_id": variant.variant_id,
            }
        )
    return result


def candidate_signature(candidates: list[dict[str, Any]]) -> str:
    return hashlib.sha256(json.dumps(candidates, sort_keys=True).encode()).hexdigest()


def render_color_preview(artwork: bytes, candidates: list[dict[str, Any]]) -> bytes:
    art = Image.open(io.BytesIO(artwork)).convert("RGBA")
    art.thumbnail((278, 324), Image.Resampling.LANCZOS)
    columns = min(4, len(candidates))
    rows = math.ceil(len(candidates) / columns)
    tile_width, tile_height = 330, 390
    sheet = Image.new("RGB", (columns * tile_width, rows * tile_height), "#FFFFFF")
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default()
    for index, candidate in enumerate(candidates):
        left = index % columns * tile_width
        top = index // columns * tile_height
        swatch = ImageColor.getrgb(str(candidate["color_hex"]))
        draw.rectangle((left + 5, top + 5, left + 324, top + 341), fill=swatch)
        x = left + (tile_width - art.width) // 2
        y = top + 8 + (330 - art.height) // 2
        sheet.paste(art, (x, y), art)
        draw.rectangle((left + 5, top + 344, left + 324, top + 384), fill="white")
        label = f"{candidate['candidate_id']}. {candidate['color']}"
        draw.text((left + 13, top + 357), label, fill="black", font=font)
    output = io.BytesIO()
    sheet.save(output, "PNG", optimize=True)
    return output.getvalue()


def _luminance(rgb: tuple[int, int, int]) -> float:
    values = [
        value / 3294.6 if value <= 10 else ((value / 255 + 0.055) / 1.055) ** 2.4 for value in rgb
    ]
    return 0.2126 * values[0] + 0.7152 * values[1] + 0.0722 * values[2]


def _contrast(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    light, dark = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


def contrast_scores(
    artwork: bytes, candidates: list[dict[str, Any]]
) -> dict[int, tuple[float, float]]:
    image = Image.open(io.BytesIO(artwork)).convert("RGBA")
    image.thumbnail((160, 160), Image.Resampling.BOX)
    pixels = cast(list[tuple[int, int, int, int]], image.get_flattened_data())
    visible = [pixel for pixel in pixels if pixel[3] > 0]
    result: dict[int, tuple[float, float]] = {}
    for candidate in candidates:
        rgb = ImageColor.getrgb(str(candidate["color_hex"]))
        background = (rgb[0], rgb[1], rgb[2])
        total_weight = readable_weight = ratio_sum = 0.0
        for red, green, blue, alpha in visible:
            weight = alpha / 255
            composited = (
                round(red * weight + background[0] * (1 - weight)),
                round(green * weight + background[1] * (1 - weight)),
                round(blue * weight + background[2] * (1 - weight)),
            )
            ratio = _contrast(composited, background)
            total_weight += weight
            readable_weight += weight * (ratio >= 1.8)
            ratio_sum += weight * ratio
        result[int(candidate["candidate_id"])] = (
            round(readable_weight / total_weight, 6) if total_weight else 0.0,
            round(ratio_sum / total_weight, 6) if total_weight else 0.0,
        )
    return result


def select_featured_color(
    artwork: bytes,
    template: ProductTemplate,
    ranking: ShirtColorRanking | None,
    *,
    artwork_sha256: str,
    preview_artifact_id: str,
    fallback_reason: str | None = None,
    catalog_featured: VariantConfig | None = None,
) -> tuple[ProductTemplate, dict[str, Any]]:
    candidates = color_candidates(template, catalog_featured.size if catalog_featured else None)
    expected = {int(item["candidate_id"]) for item in candidates}
    valid_ranking = (
        ranking is not None
        and len(ranking.scores) == len(candidates)
        and {item.candidate_id for item in ranking.scores} == expected
    )
    model_scores = (
        {item.candidate_id: item for item in ranking.scores} if valid_ranking and ranking else {}
    )
    measured = contrast_scores(artwork, candidates)
    preferred_color = (
        catalog_featured.color if catalog_featured else template.featured_variant().color
    )

    def sort_key(item: dict[str, Any]) -> tuple[float | int | bool, ...]:
        candidate_id = int(item["candidate_id"])
        readability, mean_contrast = measured[candidate_id]
        catalog_tie_break = item["color"] != preferred_color
        if model_scores:
            return (
                -model_scores[candidate_id].score,
                catalog_tie_break,
                -readability,
                -mean_contrast,
                int(item["variant_id"]),
            )
        return (-readability, -mean_contrast, catalog_tie_break, int(item["variant_id"]))

    ordered = sorted(candidates, key=sort_key)
    winner = ordered[0]
    winner_id = int(winner["candidate_id"])
    method = "vision" if model_scores else "contrast_fallback"
    reason = (
        model_scores[winner_id].reason
        if model_scores
        else "Highest measured artwork readability and contrast on approved colors"
    )
    data = template.model_dump(mode="json")
    data["featured_variant_id"] = winner["variant_id"]
    selected = ProductTemplate.model_validate(data)
    if model_scores:
        saved_fallback_reason = None
    elif ranking is not None:
        saved_fallback_reason = (
            fallback_reason or "Vision ranking did not cover every approved color exactly once"
        )
    else:
        saved_fallback_reason = fallback_reason
    result = {
        "method": method,
        "reason": reason,
        "fallback_reason": saved_fallback_reason,
        "artwork_sha256": artwork_sha256,
        "candidate_signature": candidate_signature(candidates),
        "preview_artifact_id": preview_artifact_id,
        "selected_color": winner["color"],
        "selected_variant_id": winner["variant_id"],
        "scores": [
            {
                **item,
                "vision_score": model_scores[int(item["candidate_id"])].score
                if model_scores
                else None,
                "contrast_fraction": measured[int(item["candidate_id"])][0],
                "mean_contrast": measured[int(item["candidate_id"])][1],
                "reason": model_scores[int(item["candidate_id"])].reason if model_scores else None,
            }
            for item in ordered
        ],
    }
    return selected, result


def saved_selection_matches(
    selection: dict[str, Any] | None,
    template: ProductTemplate,
    artwork_sha256: str,
    catalog_featured: VariantConfig | None = None,
) -> bool:
    if not selection:
        return False
    candidates = color_candidates(template, catalog_featured.size if catalog_featured else None)
    return (
        selection.get("artwork_sha256") == artwork_sha256
        and selection.get("candidate_signature") == candidate_signature(candidates)
        and selection.get("selected_variant_id") in {item["variant_id"] for item in candidates}
    )
