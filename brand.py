#!/usr/bin/env python3
"""The profile hero and the avatar, drawn from card.py, the module that draws the logo and the cards of the website.

Usage: python3 brand.py --fonts DIR [--out DIR]
--fonts  the folder of the site fonts: fonts/ in this repository (mm-weft.woff2, mm-sans.woff2,
         which fonts.py cuts from machine-made/type). Needed. The type in the hero is cut into
         outlines from these files at fixed axis values, so the hero needs no font.
--out    where the files go; default brand/ in this repository.

Writes profile-hero-light.svg, profile-hero-dark.svg, each as a PNG at 1408 by 469 px and, as
name@2x.png, at 2816 by 938 px, and avatar.png at 1024 by 1024 px. The same input gives the same
bytes. Needs fontTools, brotli and Playwright; build.py and check_site.py do not.
"""

import argparse
import struct
from pathlib import Path
from typing import Any

from fontTools.pens.svgPathPen import SVGPathPen  # type: ignore[import-untyped]
from fontTools.pens.transformPen import TransformPen  # type: ignore[import-untyped]
from fontTools.ttLib import TTFont  # type: ignore[import-untyped]
from playwright.sync_api import sync_playwright

import build
import card

ROOT = Path(__file__).resolve().parent
PNG_KEEP = {b"IHDR", b"PLTE", b"IDAT", b"IEND"}
AVATAR = 1024
AVATAR_LOGO = 660
# The header of the site, drawn in the frame. Sizes and baselines are in frame pixels.
LEFT = 64
WORDMARK = (42, 168)
LOGO = 34
TAGLINE_SIZE, TAGLINE_FIRST, TAGLINE_STEP = 34, 246, 42
SUBTITLE_GAP = 46
CAPTION_SIZE, CAPTION_BASE = 12.5, 384
# Weft has a wide advance (750 units), so the name and the caption are set tighter, as on the site.
WORDMARK_TRACKING = -0.08
CAPTION_TRACKING = -0.03
# The axis values of each text. The name has FRAG 12, as on the site; all other text has FRAG 0.
NAME_AXES = {"wght": 500, "FRAG": 12}
CAPTION_AXES = {"wght": 400, "FRAG": 0}
SANS_AXES = {"wght": 400}
# The word space of Sans is narrow (170 units); the site and the hero add 0.05 em to it.
WORD_SPACING = 0.05


Face = tuple[TTFont, dict[str, float]]


def load_font(fonts: Path, slug: str, axes: dict[str, float]) -> Face:
    path = fonts / f"{slug}.woff2"
    if not path.is_file():
        raise SystemExit(f"FAIL fonts: {path.name} is not in {fonts}")
    font = TTFont(path)
    ranges = {a.axisTag: (a.minValue, a.maxValue) for a in font["fvar"].axes}
    for tag, value in axes.items():
        low, high = ranges.get(tag, (None, None))
        if low is None or not low <= value <= high:
            raise SystemExit(f"FAIL fonts: {path.name} has no {tag} {value}")
    return font, axes


def outline(
    face: Face, text: str, x: float, baseline: float, size: float, tracking: float = 0.0, words: float = 0.0
) -> str:
    """The outlines of text as one svg path, set from x on the baseline."""
    font, axes = face
    glyphs, cmap = font.getGlyphSet(location=axes, normalized=False), font.getBestCmap()
    scale = size / font["head"].unitsPerEm
    pen = SVGPathPen(glyphs, ntos=card.num)
    for char in text:
        glyph = glyphs[cmap[ord(char)]]
        glyph.draw(TransformPen(pen, (scale, 0, 0, -scale, x, baseline)))
        x += glyph.width * scale + tracking * size + (words * size if char == " " else 0.0)
    return str(pen.getCommands())


def profile_svg(mode: card.Mode, site: dict[str, Any], fonts: Path) -> str:
    """The profile hero of one scheme: the header of the site, with the type cut into outlines."""
    name, tagline, subtitle = site["name"], site["tagline"], site["subtitle"]
    mono500, mono400 = load_font(fonts, "mm-weft", NAME_AXES), load_font(fonts, "mm-weft", CAPTION_AXES)
    sans = load_font(fonts, "mm-sans", SANS_AXES)
    size = WORDMARK[0]
    mark_size = LOGO
    mark_x = LEFT
    mark_y = WORDMARK[1] - mark_size
    mark_dark, mark_red = card.mark_parts(mark_x, mark_y, mark_size)
    word_x = mark_x + mark_size + 0.33 * size
    lines = card.sentences(tagline)
    text = outline(mono500, name, word_x, WORDMARK[1], size, WORDMARK_TRACKING)
    text += "".join(
        outline(sans, line, LEFT, TAGLINE_FIRST + i * TAGLINE_STEP, TAGLINE_SIZE, words=WORD_SPACING)
        for i, line in enumerate(lines)
    )
    subtitle_base = TAGLINE_FIRST + (len(lines) - 1) * TAGLINE_STEP + SUBTITLE_GAP
    quiet = outline(sans, subtitle, LEFT, subtitle_base, TAGLINE_SIZE, words=WORD_SPACING)
    quiet += outline(mono400, card.CAPTION, LEFT, CAPTION_BASE, CAPTION_SIZE, CAPTION_TRACKING)
    card_d, small, red = card.card_parts(" ".join(lines), card.CARD_X, card.CARD_Y)
    body = "\n".join(
        [
            f'<rect class="g" width="{card.FRAME_W}" height="{card.FRAME_H}"/>',
            f'<path class="k" d="{mark_dark}"/>',
            f'<path class="r" d="{mark_red}"/>',
            f'<path class="k" d="{text}"/>',
            f'<path class="m" d="{quiet}"/>',
            f'<path class="c" fill-rule="evenodd" d="{card_d}"/>',
            f'<path class="d" d="{small}"/>',
            f'<path class="r" d="{red}"/>',
        ]
    )
    style = card.fixed(mode, {"g": "bg", "k": "fg", "m": "muted", "c": "fg", "d": "dot"})
    size_attr = (str(card.FRAME_W), str(card.FRAME_H))
    return card.svg(*size_attr, f"0 0 {card.FRAME_W} {card.FRAME_H}", f"{name}: {tagline} {subtitle}", style, body)


def avatar_svg() -> str:
    """The logo alone, centred on white, with about 18% of the width as padding."""
    origin = (AVATAR - AVATAR_LOGO) / 2
    mark_dark, mark_red = card.mark_parts(origin, origin, AVATAR_LOGO)
    style = card.fixed("light", {"g": "bg", "k": "fg"})
    body = (
        f'<rect class="g" width="{AVATAR}" height="{AVATAR}"/>\n'
        f'<path class="k" d="{mark_dark}"/>\n<path class="r" d="{mark_red}"/>'
    )
    return card.svg(str(AVATAR), str(AVATAR), f"0 0 {AVATAR} {AVATAR}", "machine-made avatar", style, body)


def strip_png(data: bytes, width: int, height: int) -> bytes:
    """Keep only the chunks that draw the image, so no metadata can change the bytes."""
    out, i = data[:8], 8
    while i < len(data):
        (length,) = struct.unpack(">I", data[i : i + 4])
        kind = data[i + 4 : i + 8]
        if kind == b"IHDR" and struct.unpack(">II", data[i + 8 : i + 16]) != (width, height):
            raise SystemExit(f"FAIL size: the PNG is not {width} by {height}")
        if kind in PNG_KEEP:
            out += data[i : i + 12 + length]
        i += 12 + length
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Profile hero and avatar from card.py")
    parser.add_argument("--fonts", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=ROOT / "brand")
    args = parser.parse_args()
    site = build.load_site()
    args.out.mkdir(parents=True, exist_ok=True)
    jobs: list[tuple[str, str, int, int]] = []
    modes: tuple[card.Mode, ...] = ("light", "dark")
    for mode in modes:
        svg = profile_svg(mode, site, args.fonts)
        (args.out / f"profile-hero-{mode}.svg").write_text(svg, encoding="utf-8", newline="\n")
        jobs.append((f"profile-hero-{mode}.png", svg, card.FRAME_W, card.FRAME_H))
        jobs.append((f"profile-hero-{mode}@2x.png", svg, card.FRAME_W, card.FRAME_H))
    jobs.append(("avatar.png", avatar_svg(), AVATAR, AVATAR))
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for name, svg, width, height in jobs:
            scale = 2 if "@2x" in name else 1
            page = browser.new_page(viewport={"width": width, "height": height}, device_scale_factor=scale)
            page.set_content(f"<!doctype html><body style='margin:0'><div style='display:block;line-height:0'>{svg}</div>")
            png = page.screenshot(clip={"x": 0, "y": 0, "width": width, "height": height})
            page.close()
            (args.out / name).write_bytes(strip_png(png, width * scale, height * scale))
        browser.close()
    print(f"brand: {len(jobs)} images and 2 svg files in {args.out}")


if __name__ == "__main__":
    main()
