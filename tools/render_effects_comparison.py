"""Render reproducible effects fixtures with whichever text backend is installed."""

from __future__ import annotations

import argparse
import io
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from merch.domain.prepress import prepare_artwork
from merch.schemas import TypographySpec


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("output/artwork/effects"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    font_file = next(
        path
        for path in (
            Path("/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf"),
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        )
        if path.exists()
    )
    font_family = "Noto Sans" if "noto" in str(font_file) else "DejaVu Sans"
    label_font = ImageFont.truetype(str(font_file), 24)
    small_font = ImageFont.truetype(str(font_file), 18)
    examples = [
        ("Clean lettering", "none", 0, 0, False, ["WANDER MORE"]),
        ("Upward arch", "up", 0, 0, False, ["WANDER MORE"]),
        ("Downward arch", "down", 0, 0, False, ["WANDER MORE"]),
        ("Arch + text distress", "up", 3, 0, False, ["CAFÉ & TRAILS", "LET\u2019S WANDER!"]),
        ("Whole design distress", "up", 5, 3, True, ["TRAIL DAYS"]),
        ("Illustration-only distress", "none", 0, 5, True, []),
    ]
    sheet = Image.new("RGB", (1800, 1400), "#eee9df")
    summaries = []
    for index, (title, arc, text_level, design_level, illustration, lines) in enumerate(examples):
        source = Image.new("RGBA", (1600, 1800))
        if illustration:
            draw = ImageDraw.Draw(source)
            draw.ellipse((350, 400, 1250, 1300), fill="#DA8556")
            draw.polygon([(280, 1280), (800, 580), (1320, 1280)], fill="#EBCF94")
            draw.polygon([(520, 960), (800, 580), (1080, 960)], fill="#F9E9C8")
        buffer = io.BytesIO()
        source.save(buffer, "PNG")
        typography = (
            TypographySpec(
                exact_text=" ".join(lines),
                line_breaks=lines,
                letter_spacing=0,
                line_spacing=1.1,
                text_alignment="center",
                shadow=None,
                secondary_color=None,
                interaction_with_illustration="centered",
                text_arc_or_shape=arc,
                distress_level=text_level,
                primary_color="#F9E9C8" if not illustration else "#24342F",
                outline="#DA8556" if not illustration else "#F9E9C8",
                relative_width=0.84,
                relative_height=0.65 if len(lines) > 1 else 0.28,
            )
            if lines
            else None
        )
        prepared = prepare_artwork(
            buffer.getvalue(),
            1600,
            1800,
            typography=typography,
            artwork_distress_level=design_level,
            font_file=font_file,
            font_family=font_family,
        )
        name = f"{index + 1}-{title.lower().replace(' ', '-').replace('+', 'and')}"
        (args.output / f"{name}.png").write_bytes(prepared.data)
        art = Image.open(io.BytesIO(prepared.data)).convert("RGBA")
        preview = Image.new("RGBA", art.size, "#24342F")
        preview.alpha_composite(art)
        preview.thumbnail((560, 590), Image.Resampling.LANCZOS)
        x, y = index % 3 * 600, index // 3 * 700
        sheet.paste(preview.convert("RGB"), (x + (600 - preview.width) // 2, y + 52))
        draw_sheet = ImageDraw.Draw(sheet)
        draw_sheet.text((x + 24, y + 12), title, fill="#24342F", font=label_font)
        effects = prepared.effects
        distress = effects["distress"]
        caption = (
            f"Requested {design_level or text_level}/5 · removed {distress['removed_fraction']:.1%}"
        )
        draw_sheet.text((x + 24, y + 650), caption, fill="#24342F", font=small_font)
        summaries.append(
            {
                "title": title,
                "effects": effects,
                "issues": [issue.model_dump() for issue in prepared.issues],
            }
        )
    sheet.save(args.output / "comparison.png")
    (args.output / "effects.json").write_text(json.dumps(summaries, indent=2))
    print(args.output / "comparison.png")


if __name__ == "__main__":
    main()
