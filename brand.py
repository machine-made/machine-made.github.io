#!/usr/bin/env python3
"""The profile hero and the avatar, drawn from card.py, the module that draws the website.

Usage: python3 brand.py --fonts DIR [--out DIR]
--fonts  a folder of Geist woff2 files (names like geist-latin-400-normal.woff2). Needed. The
         type in the hero is cut into outlines from these files, so the hero needs no font.
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
AVATAR_SCALE = 19
# The header of the site, drawn in the frame. Sizes and baselines are in frame pixels.
LEFT = 64
WORDMARK = (48, 168)
TAGLINE_SIZE, TAGLINE_FIRST, TAGLINE_STEP = 34, 246, 42
SUBTITLE_GAP = 46
CAPTION_SIZE, CAPTION_BASE = 12.5, 384
WORDMARK_TRACKING = -0.04


def load_font(fonts: Path, slug: str, weight: int) -> TTFont:
    name = f"{slug}-latin-{weight}-normal.woff2"
    found = sorted(fonts.rglob(name))
    if not found:
        raise SystemExit(f"FAIL fonts: {name} is not in {fonts}")
    return TTFont(found[0])


def outline(font: TTFont, text: str, x: float, baseline: float, size: float, tracking: float = 0.0) -> str:
    """The outlines of text as one svg path, set from x on the baseline."""
    glyphs, cmap = font.getGlyphSet(), font.getBestCmap()
    scale = size / font["head"].unitsPerEm
    pen = SVGPathPen(glyphs, ntos=card.num)
    for char in text:
        glyph = glyphs[cmap[ord(char)]]
        glyph.draw(TransformPen(pen, (scale, 0, 0, -scale, x, baseline)))
        x += glyph.width * scale + tracking * size
    return str(pen.getCommands())


def profile_svg(mode: card.Mode, site: dict[str, Any], fonts: Path) -> str:
    """The profile hero of one scheme: the header of the site, with the type cut into outlines."""
    name, tagline, subtitle = site["name"], site["tagline"], site["subtitle"]
    mono500, mono400 = load_font(fonts, "geist-mono", 500), load_font(fonts, "geist-mono", 400)
    sans = load_font(fonts, "geist", 400)
    size = WORDMARK[0]
    mark_size = card.MARK_SIZE
    mark_x = LEFT
    mark_y = WORDMARK[1] - mark_size
    mark_card, mark_red = card.mark_parts(mark_x, mark_y, mark_size)
    word_x = mark_x + mark_size + 0.33 * size
    lines = card.sentences(tagline)
    text = outline(mono500, name, word_x, WORDMARK[1], size, WORDMARK_TRACKING)
    text += "".join(
        outline(sans, line, LEFT, TAGLINE_FIRST + i * TAGLINE_STEP, TAGLINE_SIZE) for i, line in enumerate(lines)
    )
    quiet = outline(sans, subtitle, LEFT, TAGLINE_FIRST + (len(lines) - 1) * TAGLINE_STEP + SUBTITLE_GAP, TAGLINE_SIZE)
    quiet += outline(mono400, card.CAPTION, LEFT, CAPTION_BASE, CAPTION_SIZE)
    card_d, small, red = card.card_parts(" ".join(lines), card.CARD_X, card.CARD_Y)
    body = "\n".join(
        [
            f'<rect class="g" width="{card.FRAME_W}" height="{card.FRAME_H}"/>',
            f'<path class="k" fill-rule="evenodd" d="{mark_card}"/>',
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
    """The mark alone, centred on white, with about 18% of the width as padding."""
    size = card.MARK_SIZE * AVATAR_SCALE
    origin = (AVATAR - size) / 2
    mark_card, mark_red = card.mark_parts(origin, origin, size)
    style = card.fixed("light", {"g": "bg", "k": "fg"})
    body = (
        f'<rect class="g" width="{AVATAR}" height="{AVATAR}"/>\n'
        f'<path class="k" fill-rule="evenodd" d="{mark_card}"/>\n<path class="r" d="{mark_red}"/>'
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
