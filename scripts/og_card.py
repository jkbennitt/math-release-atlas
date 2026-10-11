#!/usr/bin/env python3
"""Draw the link-preview card from the registered catalogues.

Each source contributes one share bar. The bar is chosen from the shape of
that source's records: families with a Lean status, a release list, or Lean
files plus one paper gap. A source that matches none of those shapes stops
the build. The card does not name a source of its own. The alt text is
card_alt().
"""

from __future__ import annotations

import io
import json
import re
from dataclasses import dataclass
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from atlaslib import (
    FAMILIES_JSON,
    FLT_PREVIEW_NOTE,
    PREVIEW_HEIGHT,
    PREVIEW_IMAGE_NAME,
    PREVIEW_WIDTH,
    ROOT,
    SOCIAL_IMAGE_ALT_MAX,
    affiliation_sentence,
    preview_entries,
    published_prefix,
    claim_word_failures,
    scan_overclaims,
)

FONT_DIR = ROOT / "scripts" / "fonts"
SERIF_BOLD = "AtlasCardSerif-Bold.ttf"
SANS = "AtlasCardSans-Regular.ttf"

BG = (243, 239, 230)
PAPER = (250, 247, 241)
INK = (29, 26, 22)
MUTED = (78, 72, 63)
LINE = (221, 212, 198)
ACCENT = (31, 77, 74)
# Lightness steps, each at least 3:1 on #f3efe6. #286460 is 5.94:1, #ac7348 is 3.45:1,
# #93866e is 3.11:1. The partly-in-Lean segment is hatched so it stays apart from the tan.
CHALLENGE = (40, 100, 96)
PARTIAL = (172, 115, 72)
PAPER_ONLY = (147, 134, 110)
MARK_INK = (244, 240, 230)
GOLD = (228, 196, 138)
HATCH_STEP = 4
# Rendered bar swatches stay at least this far apart on a 0–255 gray ramp.
GRAY_GAP = 12

BRAND = "Math Release Atlas"
HEADLINE = "AI math claims: on paper, or in Lean?"
PANEL_TITLE = "SHARE OF EACH CATALOGUE WITH LEAN FILES"
UNAFFILIATED = "Unofficial · not affiliated with any lab"
SENTENCE_TAIL = ", each linked to its paper or Lean files at a pinned commit."
CAPTION_GAP = "  \u00b7  "
LEAN_MAIN = "main-result-formalized"
LEAN_CHALLENGE = "comparator-challenge-only"
LEAN_NONE = "none"
KIND_NEW = "new-result"
KIND_FORMALIZATION = "formalization"
_INITIALS = re.compile(r"[A-Za-z]+(?:['\u2019][A-Za-z]+)?")
_NOT_FORMALIZED = "NOT FORMALIZED"

LX = 56
LW = 520
RX = 624
RW = 520
PANEL_TOP = 40
PANEL_BOTTOM = 548
# Room to the right of every bar for the percent, in dark ink.
PERCENT_GUTTER = 72
SHARE_LABEL = "Share with Lean files"
LEGEND_SWATCH = 18
LEGEND_GAP = 22
LEGEND_LINE = 22


@dataclass(frozen=True)
class SegmentStyle:
    role: str
    label: str
    fill: tuple[int, int, int]
    hatch: bool


# Order is the legend order. A role is listed only when some bar has a positive count.
STYLES: tuple[SegmentStyle, ...] = (
    SegmentStyle("lean", "result in Lean", ACCENT, False),
    SegmentStyle("challenge", "Lean challenge only", CHALLENGE, False),
    SegmentStyle("partial", "partly in Lean", PARTIAL, True),
    SegmentStyle("paper", "paper only", PAPER_ONLY, False),
)
_STYLE_BY_ROLE = {style.role: style for style in STYLES}


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


def card_host() -> str:
    prefix = published_prefix()
    if not prefix:
        raise SystemExit("preview card cannot read the published host")
    host = prefix
    for scheme in ("https://", "http://"):
        if host.startswith(scheme):
            host = host[len(scheme) :]
            break
    return host.rstrip("/")


def percent(part: int, total: int) -> int:
    """Half-even percentage, so the card and the alt text round the same way."""
    if total <= 0:
        raise SystemExit("share bar has an empty catalogue")
    quotient, remainder = divmod(part * 100, total)
    if remainder * 2 < total:
        return quotient
    if remainder * 2 > total:
        return quotient + 1
    if quotient % 2 == 0:
        return quotient
    return quotient + 1


def _plural(count: int, singular: str, plural_form: str | None = None) -> str:
    word = singular if count == 1 else (plural_form or f"{singular}s")
    return f"{count} {word}"


def _channel(value: float) -> float:
    return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4


def _luminance(color: tuple[int, int, int]) -> float:
    red, green, blue = (_channel(part / 255) for part in color)
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def _contrast(left: tuple[int, int, int], right: tuple[int, int, int]) -> float:
    lighter = max(_luminance(left), _luminance(right))
    darker = min(_luminance(left), _luminance(right))
    return (lighter + 0.05) / (darker + 0.05)


def style_for(role: str) -> SegmentStyle:
    style = _STYLE_BY_ROLE.get(role)
    if style is None:
        raise SystemExit(f"share card has no swatch for {role}")
    return style


def legend_for(rows: list[dict[str, Any]]) -> list[SegmentStyle]:
    """Legend entries for roles that actually appear, in swatch order."""
    present: set[str] = set()
    for row in rows:
        for count, role in row["segments"]:
            if role not in _STYLE_BY_ROLE:
                raise SystemExit(f"share card has no swatch for {role}")
            if count > 0:
                present.add(role)
    return [style for style in STYLES if style.role in present]


def _legend_lines(
    styles: list[SegmentStyle],
    face: ImageFont.FreeTypeFont,
    width: int,
) -> list[list[SegmentStyle]]:
    lines: list[list[SegmentStyle]] = []
    current: list[SegmentStyle] = []
    cursor = 0
    for style in styles:
        item = 26 + text_width(face, style.label)
        if item > width:
            raise SystemExit(f"legend does not fit: {style.label}")
        extra = LEGEND_GAP if current else 0
        if current and cursor + extra + item > width:
            lines.append(current)
            current = [style]
            cursor = item
            continue
        cursor += extra + item
        current.append(style)
    if current:
        lines.append(current)
    return lines


def _legend_height(line_count: int) -> int:
    if line_count <= 0:
        return 0
    return LEGEND_SWATCH + (line_count - 1) * LEGEND_LINE


def _fill_segment(
    image: Image.Image,
    box: list[int],
    fill: tuple[int, int, int],
    hatch: bool,
) -> None:
    """A 1px ink outline so neighboring segments stay separate. One role is hatched."""
    x0, y0, x1, y1 = (int(value) for value in box)
    width, height = x1 - x0, y1 - y0
    if width <= 0 or height <= 0:
        return
    if hatch:
        tile = Image.new("RGB", (width, height), fill)
        tile_draw = ImageDraw.Draw(tile)
        for offset in range(-height, width + height, HATCH_STEP):
            tile_draw.line([(offset, 0), (offset + height, height)], fill=INK, width=1)
        image.paste(tile, (x0, y0))
        ImageDraw.Draw(image).rectangle([x0, y0, x1, y1], outline=INK, width=1)
        return
    ImageDraw.Draw(image).rectangle([x0, y0, x1, y1], fill=fill, outline=INK, width=1)


def _mean_gray(image: Image.Image) -> float:
    pixels = list(image.convert("L").getdata())
    return sum(pixels) / len(pixels)


def _swatch_grays(scale: int) -> list[tuple[str, float]]:
    """Gray means of the bar swatches. scale=3 is a 400px-wide card."""
    grays: list[tuple[str, float]] = []
    width, height = 120 * scale, 36 * scale
    for style in STYLES:
        image = Image.new("RGB", (width, height), BG)
        _fill_segment(image, [0, 0, width, height], style.fill, style.hatch)
        if scale != 1:
            image = image.resize((width // scale, height // scale), Image.Resampling.LANCZOS)
        grays.append((style.role, _mean_gray(image)))
    return grays


def _require_gray_gap(grays: list[tuple[str, float]], label: str) -> None:
    for index, (left_role, left) in enumerate(grays):
        for right_role, right in grays[index + 1 :]:
            gap = abs(left - right)
            if gap < GRAY_GAP:
                raise SystemExit(
                    f"{left_role} and {right_role} are {gap:.1f} gray apart {label}"
                )


def _require_segment_contrast() -> None:
    """Each fill reads on the page and on the card. Swatches stay apart in grayscale."""
    for style in STYLES:
        for ground_name, ground in (("background", BG), ("paper", PAPER)):
            ratio = _contrast(style.fill, ground)
            if ratio < 3:
                raise SystemExit(f"{style.role} segment is {ratio:.2f}:1 on the {ground_name}")
    for style in STYLES:
        if style.role not in {"partial", "paper"}:
            continue
        ratio = _contrast(INK, style.fill)
        if ratio < 3:
            raise SystemExit(f"segment outline is {ratio:.2f}:1 on {style.role}")
    _require_gray_gap(_swatch_grays(1), "at full size")
    _require_gray_gap(_swatch_grays(3), "at a 400px-wide downscale")


def _reject_overclaim(text: str) -> None:
    failures = scan_overclaims(text, "preview card")
    failures.extend(claim_word_failures(text, "preview card"))
    if failures:
        raise SystemExit(failures[0])


def _initials(title: str) -> str:
    words = _INITIALS.findall(title)
    if not words:
        raise SystemExit(f"preview card cannot initial a release title {title!r}")
    return "".join(word[0].upper() for word in words)


def _families_for(catalog: dict[str, Any], source_id: str) -> list[dict[str, Any]]:
    families = catalog.get("families")
    if not isinstance(families, list):
        return []
    matched: list[dict[str, Any]] = []
    for family in families:
        if isinstance(family, dict) and family.get("source") == source_id:
            matched.append(family)
    return matched


def _catalogue_blocks(catalog: dict[str, Any]) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    for value in catalog.values():
        if not isinstance(value, dict):
            continue
        source = value.get("source")
        if isinstance(source, dict) and isinstance(source.get("id"), str):
            blocks.append(value)
    return blocks


def _block_for(catalog: dict[str, Any], source_id: str, name: str) -> dict[str, Any] | None:
    matches = [block for block in _catalogue_blocks(catalog) if block["source"]["id"] == source_id]
    if len(matches) > 1:
        raise SystemExit(f"{name} matches more than one catalogue")
    return matches[0] if matches else None


def _family_row(name: str, org: str, families: list[dict[str, Any]]) -> dict[str, Any]:
    counts = {LEAN_MAIN: 0, LEAN_CHALLENGE: 0, LEAN_NONE: 0}
    for family in families:
        lean = family.get("lean")
        status = lean.get("status") if isinstance(lean, dict) else None
        if status not in counts:
            raise SystemExit(f"{name} has a Lean status the share card cannot draw")
        counts[status] += 1
    total = sum(counts.values())
    if total <= 0:
        raise SystemExit(f"{name} has no result families")
    main = counts[LEAN_MAIN]
    challenge = counts[LEAN_CHALLENGE]
    paper = counts[LEAN_NONE]
    lean = main + challenge
    family_noun = "result family" if total == 1 else "result families"
    clause = f"{total} {org} {family_noun}"
    caption = (
        f"{main} result in Lean{CAPTION_GAP}{challenge} challenge only{CAPTION_GAP}{paper} paper only"
    )
    short_noun = "family" if total == 1 else "families"
    alt = f"of {total} {short_noun} ({main} main result, {challenge} challenge only, {paper} paper only)"
    return {
        "name": name,
        "org": org,
        "unit": f"{total} {family_noun}",
        "percent": f"{percent(lean, total)}%",
        "caption": caption,
        "short_caption": (
            f"{main} in Lean{CAPTION_GAP}{challenge} challenge{CAPTION_GAP}{paper} paper"
        ),
        "clause": clause,
        "alt": alt,
        "segments": [(main, "lean"), (challenge, "challenge"), (paper, "paper")],
    }


def _gap_series(gap_id: str) -> str:
    head = gap_id.split("-", 1)[0]
    if head.lower() == "oeis":
        return head.upper()
    raise SystemExit(f"preview card cannot name the paper gap {gap_id}")


def _file_row(name: str, org: str, block: dict[str, Any]) -> dict[str, Any]:
    counts = block.get("counts")
    files = counts.get("lean_files") if isinstance(counts, dict) else None
    if not isinstance(files, int):
        raise SystemExit(f"{name} has no Lean-file count")
    gaps = block.get("gaps")
    if not isinstance(gaps, list):
        raise SystemExit(f"{name} has no paper gap")
    matched = [
        gap
        for gap in gaps
        if isinstance(gap, dict)
        and str(gap.get("id", "")).lower().startswith("oeis")
        and isinstance(gap.get("absent"), int)
    ]
    if len(matched) != 1:
        raise SystemExit(f"{name} needs one paper gap with an absent count")
    absent = int(matched[0]["absent"])
    total = files + absent
    if total <= 0:
        raise SystemExit(f"{name} has no files to share")
    series = _gap_series(str(matched[0]["id"]))
    file_noun = "file" if files == 1 else "files"
    lean_noun = "Lean file" if files == 1 else "Lean files"
    who = name if name == org else f"{org} {name}"
    return {
        "name": name,
        "org": org,
        "unit": f"{files} {file_noun} + {absent} named in paper",
        "percent": f"{percent(files, total)}%",
        "caption": f"{files} {lean_noun}{CAPTION_GAP}{absent} {series} results in paper, no file",
        "short_caption": f"{files} Lean{CAPTION_GAP}{absent} no file",
        "clause": f"{files} {who} {lean_noun}",
        "alt": f"({files} {file_noun}, {absent} paper only)",
        "segments": [(files, "lean"), (absent, "paper")],
    }


def _release_row(name: str, org: str, block: dict[str, Any]) -> dict[str, Any]:
    releases = block.get("releases")
    if not isinstance(releases, list) or not releases:
        raise SystemExit(f"{name} has no releases")
    counts = block.get("counts") if isinstance(block.get("counts"), dict) else {}
    recorded = counts.get("releases")
    if isinstance(recorded, int) and recorded != len(releases):
        raise SystemExit(f"{name} release count disagrees with its release list")
    new_results: list[dict[str, Any]] = []
    formalizations: list[dict[str, Any]] = []
    full = 0
    partial = 0
    paper = 0
    for release in releases:
        if not isinstance(release, dict):
            raise SystemExit(f"{name} has a release the share card cannot draw")
        kind = release.get("kind")
        if kind == KIND_NEW:
            new_results.append(release)
        elif kind == KIND_FORMALIZATION:
            formalizations.append(release)
        else:
            raise SystemExit(f"{name} has a release kind the share card cannot draw")
        release_counts = release.get("counts")
        lean_files = release_counts.get("lean_files") if isinstance(release_counts, dict) else None
        if not isinstance(lean_files, int):
            raise SystemExit(f"{name} has a release without a Lean-file count")
        gaps = release.get("gaps")
        not_formalized = isinstance(gaps, list) and any(
            isinstance(gap, dict) and gap.get("status") == _NOT_FORMALIZED for gap in gaps
        )
        if lean_files <= 0:
            paper += 1
        elif not_formalized:
            partial += 1
        else:
            full += 1
    total = len(releases)
    with_lean = full + partial
    recorded_new = counts.get("new_results")
    recorded_formal = counts.get("formalizations")
    if isinstance(recorded_new, int) and recorded_new != len(new_results):
        raise SystemExit(f"{name} new-result count disagrees with its releases")
    if isinstance(recorded_formal, int) and recorded_formal != len(formalizations):
        raise SystemExit(f"{name} formalization count disagrees with its releases")
    tags = [_initials(str(release.get("title") or "")) for release in formalizations]
    formal_phrase = _plural(len(formalizations), "formalization")
    if tags:
        formal_phrase += f" ({', '.join(tags)})"
    new_phrase = _plural(len(new_results), "new result")
    release_noun = "release" if total == 1 else "releases"
    who = name if name == org else f"{org} {name}"
    if partial:
        caption = (
            f"{full} in Lean{CAPTION_GAP}{partial} partly in Lean{CAPTION_GAP}"
            f"{len(new_results)} new, {formal_phrase}"
        )
        short_caption = (
            f"{full} in Lean{CAPTION_GAP}{partial} partly in Lean{CAPTION_GAP}{formal_phrase}"
        )
    else:
        caption = f"{with_lean} of {total} with Lean{CAPTION_GAP}{new_phrase}, {formal_phrase}"
        short_caption = f"{with_lean} of {total} with Lean"
    return {
        "name": name,
        "org": org,
        "unit": f"{total} {release_noun}",
        "percent": f"{percent(with_lean, total)}%",
        "caption": caption,
        "short_caption": short_caption,
        "clause": f"{total} {who} {release_noun}",
        "alt": f"({with_lean} of {total}; {new_phrase}, {_plural(len(formalizations), 'formalization')})",
        "segments": [(full, "lean"), (partial, "partial"), (paper, "paper")],
    }


def row_for(catalog: dict[str, Any], entry: dict[str, Any]) -> dict[str, Any]:
    source_id = str(entry["id"])
    name = str(entry["name"])
    org = str(entry["org"])
    families = _families_for(catalog, source_id)
    block = _block_for(catalog, source_id, name)
    if families and block is not None:
        raise SystemExit(f"{name} matches more than one share-card catalogue")
    if families:
        return _family_row(name, org, families)
    if block is None:
        raise SystemExit(f"{name} has no catalogue the share card can draw")
    if isinstance(block.get("releases"), list):
        return _release_row(name, org, block)
    return _file_row(name, org, block)


def share_rows(catalog: dict[str, Any]) -> list[dict[str, Any]]:
    entries = preview_entries(catalog["sources"]["sources"])
    rows = []
    for entry in entries:
        row = row_for(catalog, entry)
        _reject_overclaim(str(row["caption"]))
        _reject_overclaim(str(row["short_caption"]))
        rows.append(row)
    if not rows:
        raise SystemExit("preview card has no sources")
    return rows


def share_sentence(rows: list[dict[str, Any]]) -> str:
    clauses = [str(row["clause"]) for row in rows]
    if len(clauses) == 1:
        joined = clauses[0]
    elif len(clauses) == 2:
        joined = f"{clauses[0]} and {clauses[1]}"
    else:
        joined = ", ".join(clauses[:-1]) + " and " + clauses[-1]
    return f"{joined}{SENTENCE_TAIL}"


def formalization_note(catalog: dict[str, Any]) -> str:
    entries = preview_entries(catalog["sources"]["sources"])
    for entry in entries:
        blob = f"{entry.get('fragment', '')}\n{entry.get('detail', '')}"
        if FLT_PREVIEW_NOTE in blob:
            return FLT_PREVIEW_NOTE
    return ""


def card_alt(catalog: dict[str, Any]) -> str:
    """Image alt for the share card. Names every source and stays within the X limit."""
    rows = share_rows(catalog)
    body = "; ".join(f"{row['name']} {row['percent']} {row['alt']}" for row in rows)
    note = formalization_note(catalog)
    line = affiliation_sentence([str(row["org"]) for row in rows])
    if note:
        alt = f"{BRAND}. {HEADLINE} {SHARE_LABEL}: {body}. {note}. {line}"
    else:
        alt = f"{BRAND}. {HEADLINE} {SHARE_LABEL}: {body}. {line}"
    _reject_overclaim(alt)
    if len(alt) > SOCIAL_IMAGE_ALT_MAX:
        raise SystemExit(f"preview alt is {len(alt)} characters, over {SOCIAL_IMAGE_ALT_MAX}")
    return alt


def _headline_lines() -> tuple[ImageFont.FreeTypeFont, list[str]]:
    size = 66
    while size >= 32:
        face = font(SERIF_BOLD, size)
        lines = wrap_text(face, HEADLINE, LW)
        if len(lines) <= 3:
            return face, lines
        size -= 2
    raise SystemExit("preview headline does not fit")


def compose(catalog: dict[str, Any]) -> list[str]:
    """The exact strings the card draws, in paint order. Overflow stops the build."""
    _require_segment_contrast()
    rows = share_rows(catalog)
    sentence = share_sentence(rows)
    _reject_overclaim(sentence)
    headline_face, headline_lines = _headline_lines()
    sentence_face = font(SANS, 25)
    sentence_lines = wrap_text(sentence_face, sentence, LW)
    y = 118
    line_height = int(headline_face.size * 1.12)
    y += line_height * len(headline_lines)
    y += 18
    y += 34 * len(sentence_lines)
    if y > 540:
        raise SystemExit(f"preview card left column is too tall: {y}")

    lines = [BRAND, *headline_lines, *sentence_lines, card_host(), UNAFFILIATED, PANEL_TITLE]
    name_face = font(SERIF_BOLD, 28)
    unit_face = font(SANS, 19)
    caption_face = font(SANS, 17)
    percent_face = font(SERIF_BOLD, 24)
    ix = RX + 28
    iw = RW - 56
    y = 108
    for row in rows:
        name = str(row["name"])
        unit = str(row["unit"])
        label = str(row["caption"])
        pct = str(row["percent"])
        if text_width(name_face, name) + text_width(unit_face, unit) + 8 > iw:
            raise SystemExit(f"{name} does not fit beside its unit")
        if text_width(caption_face, label) > iw:
            raise SystemExit(f"label overflows: {label}")
        segments = [(count, color) for count, color in row["segments"] if count > 0]
        total = sum(count for count, _color in segments)
        if total <= 0:
            raise SystemExit(f"{name} has an empty share bar")
        bar_w = iw - PERCENT_GUTTER
        if bar_w < 120:
            raise SystemExit("share bar has no room beside the percent")
        if text_width(percent_face, pct) > PERCENT_GUTTER - 8:
            raise SystemExit(f"percent label does not fit beside the bar for {name}")
        _reject_overclaim(f"{name} {unit} {pct} {label}")
        lines.extend([name, unit, pct, label])
        y = (y + 42) + 36 + 50
    legend_lines = _legend_lines(legend_for(rows), caption_face, iw)
    legend_y = y + 2
    if legend_y + _legend_height(len(legend_lines)) > 540:
        raise SystemExit(f"right panel too tall: {legend_y}")
    for legend_line in legend_lines:
        lines.extend(style.label for style in legend_line)
    return lines


def planned_text(catalog: dict[str, Any]) -> list[str]:
    return compose(catalog)


def render(catalog: dict[str, Any]) -> Image.Image:
    expected = compose(catalog)
    rows = share_rows(catalog)
    image = Image.new("RGB", (PREVIEW_WIDTH, PREVIEW_HEIGHT), BG)
    draw = ImageDraw.Draw(image)
    drawn: list[str] = []

    def paint(face: ImageFont.FreeTypeFont, text: str, xy: tuple[int, int], fill: tuple[int, int, int]) -> None:
        require_glyphs(face, text)
        draw.text(xy, text, font=face, fill=fill)
        drawn.append(text)

    draw.rectangle([0, 0, PREVIEW_WIDTH, 10], fill=ACCENT)
    draw.rectangle([0, PREVIEW_HEIGHT - 10, PREVIEW_WIDTH, PREVIEW_HEIGHT], fill=ACCENT)

    draw_mark(draw, LX, 40, 40)
    brand_face = font(SERIF_BOLD, 24)
    paint(brand_face, BRAND, (LX + 54, ink_top(brand_face, BRAND, 49)), ACCENT)

    headline_face, headline_lines = _headline_lines()
    y = 118
    line_height = int(headline_face.size * 1.12)
    for line in headline_lines:
        paint(headline_face, line, (LX, ink_top(headline_face, line, y)), INK)
        y += line_height
    y += 18
    sentence_face = font(SANS, 25)
    for line in wrap_text(sentence_face, share_sentence(rows), LW):
        paint(sentence_face, line, (LX, ink_top(sentence_face, line, y)), MUTED)
        y += 34

    footer_face = font(SANS, 20)
    host = card_host()
    paint(footer_face, host, (LX, ink_top(footer_face, host, 578)), ACCENT)
    paint(
        footer_face,
        UNAFFILIATED,
        (PREVIEW_WIDTH - 56 - text_width(footer_face, UNAFFILIATED), ink_top(footer_face, UNAFFILIATED, 578)),
        MUTED,
    )

    draw.rounded_rectangle(
        [RX, PANEL_TOP, RX + RW, PANEL_BOTTOM],
        radius=18,
        fill=PAPER,
        outline=LINE,
        width=2,
    )
    ix = RX + 28
    iw = RW - 56
    title_face = font(SANS, 19)
    paint(title_face, PANEL_TITLE, (ix, ink_top(title_face, PANEL_TITLE, 66)), MUTED)

    y = 108
    name_face = font(SERIF_BOLD, 28)
    unit_face = font(SANS, 19)
    caption_face = font(SANS, 17)
    percent_face = font(SERIF_BOLD, 24)
    for row in rows:
        name = str(row["name"])
        unit = str(row["unit"])
        label = str(row["caption"])
        pct = str(row["percent"])
        paint(name_face, name, (ix, ink_top(name_face, name, y)), INK)
        paint(
            unit_face,
            unit,
            (ix + iw - text_width(unit_face, unit), ink_top(unit_face, unit, y + 6)),
            MUTED,
        )
        bar_y = y + 42
        bar_h = 36
        bar_w = iw - PERCENT_GUTTER
        segments = [(count, style_for(role)) for count, role in row["segments"] if count > 0]
        total = sum(count for count, _style in segments)
        cursor = ix
        for index, (count, style) in enumerate(segments):
            width = round(bar_w * count / total) if index < len(segments) - 1 else ix + bar_w - cursor
            _fill_segment(image, [cursor, bar_y, cursor + width, bar_y + bar_h], style.fill, style.hatch)
            cursor += width
        paint(
            percent_face,
            pct,
            (ix + iw - text_width(percent_face, pct), ink_top(percent_face, pct, bar_y + 7)),
            INK,
        )
        paint(caption_face, label, (ix, ink_top(caption_face, label, bar_y + bar_h + 10)), MUTED)
        y = bar_y + bar_h + 50

    legend_y = y + 2
    for line_index, legend_line in enumerate(_legend_lines(legend_for(rows), caption_face, iw)):
        cursor = ix
        top = legend_y + line_index * LEGEND_LINE
        for style in legend_line:
            _fill_segment(
                image,
                [cursor, top, cursor + LEGEND_SWATCH, top + LEGEND_SWATCH],
                style.fill,
                style.hatch,
            )
            paint(caption_face, style.label, (cursor + 26, ink_top(caption_face, style.label, top + 1)), INK)
            cursor += 26 + text_width(caption_face, style.label) + LEGEND_GAP

    if drawn != expected:
        raise SystemExit("preview card omitted a registered source")
    return image


def png_bytes(image: Image.Image) -> bytes:
    """The bytes public/og.png and dist/og.png must share. optimize=True is part of the pin."""
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


SHARE_HEADING = "Share of each catalogue with Lean files"


def share_document(catalog: dict[str, Any]) -> dict[str, Any]:
    """The bars, percents, and legend the site draws. Same rows as the card."""
    if SHARE_HEADING.upper() != PANEL_TITLE:
        raise SystemExit("share heading drifted from the card panel title")
    rows = share_rows(catalog)
    painted = []
    for row in rows:
        segments = []
        for count, role in row["segments"]:
            if count <= 0:
                continue
            style_for(role)
            segments.append({"count": count, "role": role})
        if not segments:
            raise SystemExit(f"{row['name']} has an empty share bar")
        painted.append(
            {
                "name": row["name"],
                "unit": row["unit"],
                "percent": row["percent"],
                "caption": row["caption"],
                "shortCaption": row["short_caption"],
                "segments": segments,
            }
        )
    return {
        "headline": HEADLINE,
        "shareHeading": SHARE_HEADING,
        "sentence": share_sentence(rows),
        "legend": [{"role": style.role, "label": style.label} for style in legend_for(rows)],
        "rows": painted,
    }


def write_share_document(catalog: dict[str, Any]) -> None:
    dest = ROOT / "src" / "generated" / "share.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(share_document(catalog), indent=2) + "\n", encoding="utf-8")


def main() -> int:
    payload = json.loads(FAMILIES_JSON.read_text(encoding="utf-8"))
    sources = payload["sources"]["sources"]
    if not sources:
        raise SystemExit("preview card has no sources")
    image = render(payload)
    dest = ROOT / "public" / PREVIEW_IMAGE_NAME
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(png_bytes(image))
    write_share_document(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
