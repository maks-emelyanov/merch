"""Turn color-specific contrast findings into options for one publication."""

from __future__ import annotations

from typing import Any

from merch.schemas import ProductTemplate, QAReport, VariantConfig

# Ordered reserve shades for Bella+Canvas 3001 / SwiftPOD. Names are verified
# against Printify's catalog at run time; hex values approximate the Bella+Canvas
# color card and are used only to screen artwork contrast. Keep the broad,
# familiar colors first so a product does not fill up with novelty shades.
FALLBACK_COLORS = {
    "Silver": "#D6D5D1",
    "Forest": "#20362F",
    "Steel Blue": "#5F849C",
    "Sage": "#97A798",
    "Heather Navy": "#3B4559",
    "Heather Dust": "#CDC6BD",
    "Baby Blue": "#83B0C1",
    "Heather Forest": "#48655B",
    "Deep Teal": "#00597A",
    "Mint": "#A0DAB3",
    "Pink": "#F7CED7",
    "Rust": "#9E483F",
    "Heather Maroon": "#5B2B42",
    "Heather Military Green": "#6C6E60",
    "Heather True Royal": "#24509A",
    "Kelly": "#007A53",
    "Orange": "#FF6A39",
    "Black Heather": "#454038",
    "Dark Olive": "#36362D",
    "Heather Prism Natural": "#D2CFC4",
    "Heather Ice Blue": "#C4E1DE",
    "Tan": "#B8B298",
    "Heather Slate": "#586975",
    "Heather Peach": "#F3BE8D",
    "Heather Kelly": "#00965E",
    "Heather Olive": "#7F7457",
    "Heather Prism Blue": "#A5B3CC",
    "Heather Prism Mint": "#A0DAB3",
    "Heather Prism Peach": "#EABEB0",
    "Heather Brown": "#5E4B3C",
    "Evergreen": "#115740",
    "Heather Blue Lagoon": "#86A1A9",
    "Heather Prism Lilac": "#C7A1B2",
}


def exclude_low_contrast_colors(
    report: QAReport, template: ProductTemplate, *, allow_all: bool = False
) -> tuple[QAReport, list[str]]:
    """Accept localized contrast failures by removing those garment colors."""
    enabled = {item.color for item in template.variants if item.enabled}
    lookup: dict[str, set[str]] = {}
    for item in template.variants:
        if item.enabled:
            lookup.setdefault(item.color.casefold(), set()).add(item.color)
            if item.color_hex:
                lookup.setdefault(item.color_hex.casefold(), set()).add(item.color)
    localized: dict[int, set[str]] = {}
    for index, issue in enumerate(report.issues):
        if issue.severity != "error" or "contrast" not in issue.code.casefold():
            continue
        if issue.affected_shirt_colors and all(
            color.casefold() in lookup for color in issue.affected_shirt_colors
        ):
            localized[index] = set().union(
                *(lookup[color.casefold()] for color in issue.affected_shirt_colors)
            )
    excluded = set().union(*localized.values()) if localized else set()
    if not excluded or (excluded == enabled and not allow_all):
        return report, []
    issues = [
        issue.model_copy(
            update={
                "severity": "warning",
                "recommended_fix": "This product omits the affected shirt colors",
            }
        )
        if index in localized
        else issue
        for index, issue in enumerate(report.issues)
    ]
    remaining_errors = any(issue.severity == "error" for issue in issues)
    return (
        report.model_copy(
            update={"issues": issues, "passed": not remaining_errors and (report.passed or bool(localized))}
        ),
        sorted(excluded),
    )


def catalog_replacement_groups(
    template: ProductTemplate, catalog: dict[str, Any]
) -> list[list[VariantConfig]]:
    """Return complete, available color groups with the same print area and sizes."""
    if (template.blueprint_id, template.print_provider_id) != (12, 39):
        return []
    base_colors = {item.color for item in template.variants if item.enabled}
    sizes = {item.size for item in template.variants if item.enabled}
    costs = {item.size: item.production_cost_cents for item in template.variants if item.enabled}
    by_options = {
        (item["options"]["color"], item["options"]["size"]): item
        for item in catalog.get("variants", [])
    }
    groups: list[list[VariantConfig]] = []
    for color, swatch in FALLBACK_COLORS.items():
        if color in base_colors:
            continue
        group: list[VariantConfig] = []
        for size in sorted(sizes):
            remote = by_options.get((color, size))
            if not remote or not remote.get("is_available", True):
                break
            front = [
                area for area in remote.get("placeholders", [])
                if area.get("position") == template.position
                and area.get("decoration_method") == template.decoration_method
            ]
            if len(front) != 1 or not (
                0 < front[0].get("width", 0) <= template.print_width
                and 0 < front[0].get("height", 0) <= template.print_height
            ):
                break
            group.append(
                VariantConfig(
                    variant_id=remote["id"],
                    title=remote["title"],
                    color=color,
                    color_hex=swatch,
                    size=size,
                    production_cost_cents=costs[size],
                )
            )
        if len(group) == len(sizes):
            groups.append(group)
    return groups


def full_color_publication_template(
    template: ProductTemplate,
    excluded_colors: set[str],
    candidate_groups: list[list[VariantConfig]],
    rejected_candidates: set[str],
) -> ProductTemplate | None:
    """Keep passing base colors and fill every vacant slot from vetted reserves."""
    base_colors = {item.color for item in template.variants if item.enabled}
    if excluded_colors - base_colors:
        raise ValueError("QA excluded a shirt color outside the approved template")
    retained = [
        item for item in template.variants if item.enabled and item.color not in excluded_colors
    ]
    needed = len(base_colors) - len({item.color for item in retained})
    replacements = [
        group for group in candidate_groups
        if group[0].color not in rejected_candidates and group[0].color not in base_colors
    ][:needed]
    if len(replacements) != needed:
        return None
    variants = retained + [item for group in replacements for item in group]
    featured = next(
        (item for item in variants if item.variant_id == template.featured_variant().variant_id),
        None,
    ) or next(
        (item for item in variants if item.size == template.featured_variant().size),
        variants[0],
    )
    data = template.model_dump(mode="json")
    data["variants"] = [item.model_dump(mode="json") for item in variants]
    data["featured_variant_id"] = featured.variant_id
    return ProductTemplate.model_validate(data)


def publication_template(
    template: ProductTemplate,
    excluded_colors: list[str],
    snapshot: dict[str, Any] | None = None,
) -> ProductTemplate:
    """Use the saved product palette, or disable excluded colors for older runs."""
    if snapshot is not None:
        publication = ProductTemplate.model_validate(snapshot)
        if (
            publication.blueprint_id != template.blueprint_id
            or publication.print_provider_id != template.print_provider_id
            or publication.print_width != template.print_width
            or publication.print_height != template.print_height
        ):
            raise ValueError("Publication snapshot does not match the approved garment")
        return publication
    excluded = set(excluded_colors)
    enabled_colors = {item.color for item in template.variants if item.enabled}
    if excluded - enabled_colors:
        raise ValueError("QA excluded a shirt color outside the approved template")
    variants = [
        item.model_copy(update={"enabled": item.enabled and item.color not in excluded})
        for item in template.variants
    ]
    available = [item for item in variants if item.enabled]
    if not available:
        raise ValueError("No shirt colors remain after contrast QA")
    original_featured = template.featured_variant()
    featured = next(
        (item for item in available if item.variant_id == original_featured.variant_id),
        None,
    ) or next(
        (item for item in available if item.size == original_featured.size),
        available[0],
    )
    data = template.model_dump(mode="json")
    data["variants"] = [item.model_dump(mode="json") for item in variants]
    data["featured_variant_id"] = featured.variant_id
    return ProductTemplate.model_validate(data)
