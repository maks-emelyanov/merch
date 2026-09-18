from __future__ import annotations

import io

from PIL import Image, ImageDraw

from merch.defaults import fixture_product_template
from merch.domain.featured_color import (
    color_candidates,
    render_color_preview,
    saved_selection_matches,
    select_featured_color,
)
from merch.domain.product_options import publication_template
from merch.schemas import ShirtColorRanking, ShirtColorScore, VariantConfig


def _artwork() -> bytes:
    image = Image.new("RGBA", (200, 200), (0, 0, 0, 0))
    ImageDraw.Draw(image).rectangle((35, 35, 165, 165), fill="white")
    output = io.BytesIO()
    image.save(output, "PNG")
    return output.getvalue()


def _template():  # type: ignore[no-untyped-def]
    variants = [
        VariantConfig(
            variant_id=1,
            title="Black / M",
            color="Black",
            color_hex="#111111",
            size="M",
            production_cost_cents=900,
        ),
        VariantConfig(
            variant_id=2,
            title="Black / L",
            color="Black",
            color_hex="#111111",
            size="L",
            production_cost_cents=900,
        ),
        VariantConfig(
            variant_id=3,
            title="Blue / M",
            color="Blue",
            color_hex="#111111",
            size="M",
            production_cost_cents=900,
        ),
        VariantConfig(
            variant_id=4,
            title="Blue / L",
            color="Blue",
            color_hex="#111111",
            size="L",
            production_cost_cents=900,
        ),
        VariantConfig(
            variant_id=5,
            title="White / M",
            color="White",
            color_hex="#FFFFFF",
            size="M",
            production_cost_cents=900,
        ),
        VariantConfig(
            variant_id=6,
            title="White / L",
            color="White",
            color_hex="#FFFFFF",
            size="L",
            production_cost_cents=900,
        ),
    ]
    return fixture_product_template().model_copy(
        update={"variants": variants, "featured_variant_id": 2}
    )


def test_vision_selects_best_approved_color_and_preferred_size() -> None:
    template = _template()
    candidates = color_candidates(template)
    preview = render_color_preview(_artwork(), candidates)
    assert Image.open(io.BytesIO(preview)).size == (990, 390)
    ranking = ShirtColorRanking(
        scores=[
            ShirtColorScore(candidate_id=1, score=75, reason="Clear on black"),
            ShirtColorScore(candidate_id=2, score=95, reason="Best overall color harmony"),
            ShirtColorScore(candidate_id=3, score=50, reason="Low contrast"),
        ]
    )
    selected, result = select_featured_color(
        _artwork(),
        template,
        ranking,
        artwork_sha256="artwork-hash",
        preview_artifact_id="preview-id",
    )
    assert selected.featured_variant_id == 4
    assert result["selected_color"] == "Blue"
    assert result["reason"] == "Best overall color harmony"
    assert result["method"] == "vision"
    assert saved_selection_matches(result, template, "artwork-hash")
    assert not saved_selection_matches(result, template, "new-artwork")


def test_invalid_ranking_falls_back_to_contrast_and_excludes_failed_color() -> None:
    template = _template()
    approved = publication_template(template, ["White"])
    invalid = ShirtColorRanking(
        scores=[
            ShirtColorScore(candidate_id=1, score=99, reason="Black"),
            ShirtColorScore(candidate_id=1, score=98, reason="Duplicate"),
            ShirtColorScore(candidate_id=3, score=97, reason="Excluded white"),
        ]
    )
    selected, result = select_featured_color(
        _artwork(),
        approved,
        invalid,
        artwork_sha256="artwork-hash",
        preview_artifact_id="preview-id",
        catalog_featured=template.featured_variant(),
    )
    assert selected.featured_variant_id == 2
    assert result["method"] == "contrast_fallback"
    assert {item["color"] for item in result["scores"]} == {"Black", "Blue"}
    assert "did not cover" in result["fallback_reason"]


def test_contrast_fallback_prefers_readability_then_catalog_tie_break() -> None:
    template = _template()
    selected, result = select_featured_color(
        _artwork(),
        template,
        None,
        artwork_sha256="artwork-hash",
        preview_artifact_id="preview-id",
    )
    assert selected.featured_variant_id == 2
    assert result["scores"][-1]["color"] == "White"
    one_color = publication_template(template, ["Blue", "White"])
    selected_one, result_one = select_featured_color(
        _artwork(),
        one_color,
        None,
        artwork_sha256="artwork-hash",
        preview_artifact_id="preview-id",
    )
    assert selected_one.featured_variant_id == 2
    assert len(result_one["scores"]) == 1


def test_equal_vision_scores_use_catalog_choice_before_contrast() -> None:
    template = _template().model_copy(update={"featured_variant_id": 4})
    variants = [
        item.model_copy(update={"color_hex": "#444444"}) if item.color == "Blue" else item
        for item in template.variants
    ]
    template = template.model_copy(update={"variants": variants})
    ranking = ShirtColorRanking(
        scores=[
            ShirtColorScore(candidate_id=1, score=85, reason="Good on black"),
            ShirtColorScore(candidate_id=2, score=85, reason="Good on blue"),
            ShirtColorScore(candidate_id=3, score=60, reason="Weak on white"),
        ]
    )
    selected, _ = select_featured_color(
        _artwork(),
        template,
        ranking,
        artwork_sha256="artwork-hash",
        preview_artifact_id="preview-id",
    )
    assert selected.featured_variant_id == 4
