#!/usr/bin/env python3
"""Draw the link-preview card from the registered sources.

Each source contributes the preview stored on its registry record. Adding or
removing a source, or a count changing on sync, changes that record and this
card follows. The card does not name a source of its own. The subset fonts
have no glyph for ő, so a detail line spells Erdos in ASCII. The alt text is
preview_alt() and does not need that spelling.
"""

from __future__ import annotations

import io
import json
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from atlaslib import (
    FAMILIES_JSON,
    PREVIEW_HEIGHT,
    PREVIEW_IMAGE_NAME,
    PREVIEW_WIDTH,
    ROOT,
    affiliation_sentence,
    join_series,
    preview_entries,
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
MARGIN = 48
GAP = 16
MIN_CARD_W = 200


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


def fitting_font(filename: str, text: str, max_width: int, size: int) -> ImageFont.FreeTypeFont:
    while size >= 15:
        face = font(filename, size)
        if text_width(face, text) <= max_width:
            return face
        size -= 1
    raise SystemExit(f"preview card text does not fit: {text}")


def wrap_text(face: ImageFont.FreeTypeFont, text: str, max_width: int) -> list[str]:
    if not text:
        return []
    lines: list[str] = []
    current = ""
    for word in text.split():
        trial = word if not current else f"{current} {word}"
        if text_width(face, trial) <= max_width:
            current = trial
            continue
        if current:
            lines.append(current)
        current = word
    if current:
        lines.append(current)
    return lines


def card_width(count: int) -> int:
    if count < 1:
        raise SystemExit("preview card has no sources")
    width = (PREVIEW_WIDTH - MARGIN * 2 - GAP * (count - 1)) // count
    if width < MIN_CARD_W:
        raise SystemExit(f"preview card has {count} sources and no longer fits")
    return width


def plan(entries: list[dict[str, Any]]) -> dict[str, Any]:
    """The exact strings the card draws, in registry order."""
    if not entries:
        raise SystemExit("preview card has no sources")
    inner = card_width(len(entries)) - 36
    detail_face = font("AtlasCardSans-Regular.ttf", 16)
    panels = []
    for entry in entries:
        tiles = [(str(tile["value"]), str(tile["label"])) for tile in entry["tiles"]]
        detail = wrap_text(detail_face, str(entry.get("detail") or ""), inner)
        panels.append({"name": str(entry["name"]), "tiles": tiles, "detail_lines": detail})
    return {
        "title": "Math Release Atlas",
        "subtitle": join_series([str(entry["name"]) for entry in entries], "and"),
        "panels": panels,
        "footer": affiliation_sentence([str(entry["org"]) for entry in entries]),
    }


def planned_text(entries: list[dict[str, Any]]) -> list[str]:
    planned = plan(entries)
    lines = [planned["title"], planned["subtitle"]]
    for panel in planned["panels"]:
        lines.append(panel["name"])
        for value, label in panel["tiles"]:
            lines.append(value)
            lines.append(label)
        lines.extend(panel["detail_lines"])
    lines.append(planned["footer"])
    return lines


def render(entries: list[dict[str, Any]]) -> Image.Image:
    planned = plan(entries)
    image = Image.new("RGB", (PREVIEW_WIDTH, PREVIEW_HEIGHT), BG)
    draw = ImageDraw.Draw(image)
    drawn: list[str] = []

    def paint(face: ImageFont.FreeTypeFont, text: str, xy: tuple[int, int], fill: tuple[int, int, int]) -> None:
        require_glyphs(face, text)
        draw.text(xy, text, font=face, fill=fill)
        drawn.append(text)

    draw.rectangle([0, 0, PREVIEW_WIDTH, 12], fill=ACCENT)
    draw.rectangle([0, PREVIEW_HEIGHT - 12, PREVIEW_WIDTH, PREVIEW_HEIGHT], fill=ACCENT)

    mark = 64
    mark_x, mark_y = MARGIN, 28
    draw_mark(draw, mark_x, mark_y, mark)
    title = planned["title"]
    title_font = fitting_font("AtlasCardSerif-Bold.ttf", title, PREVIEW_WIDTH - mark_x - mark - 80, 52)
    title_box = title_font.getbbox(title)
    title_h = title_box[3] - title_box[1]
    paint(
        title_font,
        title,
        (mark_x + mark + 20, ink_top(title_font, title, mark_y + (mark - title_h) // 2)),
        INK,
    )
    subtitle = planned["subtitle"]
    subtitle_font = fitting_font("AtlasCardSans-Regular.ttf", subtitle, PREVIEW_WIDTH - MARGIN * 2, 26)
    paint(subtitle_font, subtitle, (MARGIN, ink_top(subtitle_font, subtitle, 112)), MUTED)

    panels = planned["panels"]
    card_w = card_width(len(panels))
    card_y = 158
    card_h = 400
    inner = card_w - 36
    for index, panel in enumerate(panels):
        x = MARGIN + index * (card_w + GAP)
        draw.rounded_rectangle(
            [x, card_y, x + card_w, card_y + card_h],
            radius=16,
            fill=PAPER,
            outline=LINE,
            width=2,
        )
        name_font = fitting_font("AtlasCardSerif-Bold.ttf", panel["name"], inner, 24)
        cursor = card_y + 18
        paint(name_font, panel["name"], (x + 18, ink_top(name_font, panel["name"], cursor)), INK)
        cursor += 40
        for tile_index, (value, label) in enumerate(panel["tiles"]):
            value_size = 40 if tile_index == 0 else 24
            value_font = fitting_font("AtlasCardSerif-Bold.ttf", value, inner, value_size)
            label_font = fitting_font("AtlasCardSans-Regular.ttf", label, inner, 18 if tile_index == 0 else 16)
            paint(value_font, value, (x + 18, ink_top(value_font, value, cursor)), INK)
            value_h = value_font.getbbox(value)[3] - value_font.getbbox(value)[1]
            cursor += value_h + 4
            paint(label_font, label, (x + 18, ink_top(label_font, label, cursor)), MUTED)
            label_h = label_font.getbbox(label)[3] - label_font.getbbox(label)[1]
            cursor += label_h + (16 if tile_index == 0 else 10)
        detail_font = font("AtlasCardSans-Regular.ttf", 16)
        for line in panel["detail_lines"]:
            if cursor + 20 > card_y + card_h - 12:
                raise SystemExit(f"preview card crowds {panel['name']}")
            paint(detail_font, line, (x + 18, ink_top(detail_font, line, cursor)), MUTED)
            cursor += 22
    footer = planned["footer"]
    footer_font = fitting_font("AtlasCardSans-Regular.ttf", footer, PREVIEW_WIDTH - MARGIN * 2, 22)
    paint(footer_font, footer, (MARGIN, ink_top(footer_font, footer, 578)), MUTED)
    if drawn != planned_text(entries):
        raise SystemExit("preview card omitted a registered source")
    return image


def png_bytes(image: Image.Image) -> bytes:
    """The bytes public/og.png and dist/og.png must share. optimize=True is part of the pin."""
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def main() -> int:
    payload = json.loads(FAMILIES_JSON.read_text(encoding="utf-8"))
    entries = preview_entries(payload["sources"]["sources"])
    image = render(entries)
    dest = ROOT / "public" / PREVIEW_IMAGE_NAME
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(png_bytes(image))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
