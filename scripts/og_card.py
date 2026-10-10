#!/usr/bin/env python3
"""Draw the link-preview card from the current catalogue counts.

Counts come from data/families.json at build time, so a later sync does not
leave a stale number on the card. The card names the sources and those counts.
The subset fonts have no glyph for ő, so the image spells Erdos in ASCII.
The alt text is preview_alt() and does not need that spelling.
"""

from __future__ import annotations

import json

from PIL import Image, ImageDraw, ImageFont

from atlaslib import (
    FAMILIES_JSON,
    PREVIEW_HEIGHT,
    PREVIEW_IMAGE_NAME,
    PREVIEW_WIDTH,
    ROOT,
    oeis_preview_phrase,
)

FONT_DIR = ROOT / "scripts" / "fonts"

BG = (243, 239, 230)
PAPER = (250, 247, 241)
INK = (29, 26, 22)
MUTED = (78, 72, 63)
LINE = (221, 212, 198)
ACCENT = (31, 77, 74)
MARK_INK = (244, 240, 230)
GOLD = (228, 196, 138)


def font(name: str, size: int) -> ImageFont.FreeTypeFont:
    path = FONT_DIR / name
    if not path.is_file():
        raise SystemExit(f"missing preview font {path}")
    return ImageFont.truetype(path, size)


def draw_mark(draw: ImageDraw.ImageDraw, x: int, y: int, size: int) -> None:
    """Same grid mark as public/favicon.svg, scaled up."""
    scale = size / 32
    draw.rounded_rectangle(
        [x, y, x + size, y + size],
        radius=round(6 * scale),
        fill=ACCENT,
    )

    def px(value: float) -> int:
        return round(x + value * scale)

    def py(value: float) -> int:
        return round(y + value * scale)

    stroke = max(2, round(1.6 * scale))
    for y_line in (10, 16, 22):
        draw.line([(px(8), py(y_line)), (px(24), py(y_line))], fill=MARK_INK, width=stroke)
    for x_line in (12, 20):
        draw.line([(px(x_line), py(8)), (px(x_line), py(24))], fill=MARK_INK, width=stroke)
    dot = 2.2 * scale
    cx, cy = px(16), py(16)
    draw.ellipse([cx - dot, cy - dot, cx + dot, cy + dot], fill=GOLD)


def ink_top(face: ImageFont.FreeTypeFont, text: str, y: int) -> int:
    """Place the top of the ink at y. FreeType's origin is the baseline."""
    top = face.getbbox(text)[1]
    return y - top


def text_width(face: ImageFont.FreeTypeFont, text: str) -> int:
    box = face.getbbox(text)
    return box[2] - box[0]


def require_glyphs(face: ImageFont.FreeTypeFont, text: str) -> None:
    """The card subset has empty boxes for ő, the dagger, and the en dash."""
    missing = []
    for char in set(text):
        if char.isspace():
            continue
        box = face.getbbox(char)
        if box[2] <= box[0] or box[3] <= box[1]:
            missing.append(char)
    if missing:
        shown = ", ".join(repr(char) for char in missing)
        raise SystemExit(f"preview font is missing glyphs: {shown}")


def render(
    families: int,
    manuscripts: int,
    lean_files: int,
    erdos_files: int,
    oeis_files: int,
    oeis_paper: int,
    oeis_status: str,
    stacks_files: int,
    collaborator_files: int,
    provenance_status: str,
    provenance_label: str,
    anthropic_files: int = 0,
    anthropic_new: int = 0,
    anthropic_formalizations: int = 0,
    zeta_files: int = 0,
    three_files: int = 0,
    flt_files: int = 0,
) -> Image.Image:
    image = Image.new("RGB", (PREVIEW_WIDTH, PREVIEW_HEIGHT), BG)
    draw = ImageDraw.Draw(image)
    draw.rectangle([0, 0, PREVIEW_WIDTH, 14], fill=ACCENT)
    draw.rectangle([0, PREVIEW_HEIGHT - 14, PREVIEW_WIDTH, PREVIEW_HEIGHT], fill=ACCENT)

    title_font = font("AtlasCardSerif-Bold.ttf", 64)
    subtitle_font = font("AtlasCardSans-Regular.ttf", 28)
    detail_font = font("AtlasCardSans-Regular.ttf", 24)
    footer_font = font("AtlasCardSans-Regular.ttf", 24)

    mark = 80
    mark_x, mark_y = 64, 48
    draw_mark(draw, mark_x, mark_y, mark)

    title = "Math Release Atlas"
    title_x = mark_x + mark + 24
    title_box = title_font.getbbox(title)
    title_h = title_box[3] - title_box[1]
    title_y = ink_top(title_font, title, mark_y + (mark - title_h) // 2)
    draw.text((title_x, title_y), title, font=title_font, fill=INK)

    if anthropic_files:
        subtitle = "OpenAI Math, AlphaProof Nexus, and Anthropic"
        footer = "Unofficial, not affiliated with OpenAI, Google DeepMind, or Anthropic."
        noun = "formalization" if anthropic_formalizations == 1 else "formalizations"
        anthropic_line = (
            f"Anthropic {anthropic_files} Lean files: {zeta_files} + {three_files} + {flt_files}; "
            f"{anthropic_new} new results, {anthropic_formalizations} {noun}"
        )
    else:
        subtitle = "OpenAI Math and AlphaProof Nexus"
        footer = "Unofficial, not affiliated with OpenAI or Google DeepMind."
        anthropic_line = ""
    draw.text((64, ink_top(subtitle_font, subtitle, 168)), subtitle, font=subtitle_font, fill=MUTED)

    cards = (
        (str(families), "result families"),
        (str(manuscripts), "manuscripts"),
        (str(lean_files), "Lean files"),
        (provenance_status, provenance_label),
    )
    margin = 64
    gap = 18
    card_y = 230
    card_h = 156
    card_w = (PREVIEW_WIDTH - margin * 2 - gap * (len(cards) - 1)) // len(cards)
    for index, (number, label) in enumerate(cards):
        number_face = fitting_font("AtlasCardSerif-Bold.ttf", number, card_w - 48, 52)
        label_face = fitting_font("AtlasCardSans-Regular.ttf", label, card_w - 48, 22)
        require_glyphs(number_face, number)
        require_glyphs(label_face, label)
        x = margin + index * (card_w + gap)
        draw.rounded_rectangle(
            [x, card_y, x + card_w, card_y + card_h],
            radius=16,
            fill=PAPER,
            outline=LINE,
            width=2,
        )
        draw.text((x + 24, ink_top(number_face, number, card_y + 24)), number, font=number_face, fill=INK)
        draw.text((x + 24, ink_top(label_face, label, card_y + 96)), label, font=label_face, fill=MUTED)

    detail = (
        f"Erdos {erdos_files}, {oeis_preview_phrase(oeis_files, oeis_paper, oeis_status)}, "
        f"Stacks {stacks_files}, AI collaborator {collaborator_files}"
    )
    drawn: list[tuple[ImageFont.FreeTypeFont, str, int]] = [(detail_font, detail, 424)]
    if anthropic_line:
        anthropic_font = fitting_font(
            "AtlasCardSans-Regular.ttf",
            anthropic_line,
            PREVIEW_WIDTH - margin * 2,
            24,
        )
        drawn.append((anthropic_font, anthropic_line, 468))
        footer_y = 528
    else:
        footer_y = 500
    drawn.append((footer_font, footer, footer_y))
    for face, line, _top in drawn + [(subtitle_font, subtitle, 168), (title_font, title, title_y)]:
        require_glyphs(face, line)
    if text_width(detail_font, detail) > PREVIEW_WIDTH - margin * 2:
        raise SystemExit("preview breakdown line does not fit")
    if text_width(footer_font, footer) > PREVIEW_WIDTH - margin * 2:
        raise SystemExit("preview footer does not fit")
    for face, line, top in drawn:
        draw.text((margin, ink_top(face, line, top)), line, font=face, fill=MUTED)
    return image


def fitting_font(filename: str, text: str, max_width: int, size: int) -> ImageFont.FreeTypeFont:
    while size >= 16:
        face = font(filename, size)
        if text_width(face, text) <= max_width:
            return face
        size -= 2
    raise SystemExit(f"preview card text does not fit: {text}")


def main() -> int:
    payload = json.loads(FAMILIES_JSON.read_text(encoding="utf-8"))
    counts = payload["counts"]
    alphaproof_counts = payload["alphaproof"]["counts"]
    gaps = {gap["id"]: gap for gap in payload["alphaproof"]["gaps"]}
    oeis = gaps["oeis-count"]
    provenance = gaps["per-row-provenance"]
    anthropic_counts = payload["anthropic"]["counts"]
    by_release = {release["id"]: release for release in payload["anthropic"]["releases"]}
    image = render(
        int(counts["families"]),
        int(counts["manuscripts"]),
        int(alphaproof_counts["lean_files"]),
        int(alphaproof_counts["erdos"]),
        int(alphaproof_counts["oeis_files"]),
        int(oeis["paper_count"]),
        str(oeis["status"]),
        int(alphaproof_counts["stacks"]),
        int(alphaproof_counts["ai_collaborator"]),
        str(provenance["status"]),
        str(provenance["label"]),
        int(anthropic_counts["lean_files"]),
        int(anthropic_counts["new_results"]),
        int(anthropic_counts["formalizations"]),
        int(by_release["zeta23"]["counts"]["lean_files"]),
        int(by_release["3sum-apsp"]["counts"]["lean_files"]),
        int(by_release["fermat-last-theorem"]["counts"]["lean_files"]),
    )
    dest = ROOT / "public" / PREVIEW_IMAGE_NAME
    dest.parent.mkdir(parents=True, exist_ok=True)
    image.save(dest, format="PNG", optimize=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
