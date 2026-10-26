#!/usr/bin/env python3
"""Cut the web fonts of the site from the machine-made type repository. Writes fonts/.

Usage: python3 fonts.py --type DIR [--out DIR]
--type  a checkout of machine-made/type. The script reads the two variable fonts
        fonts/weft/variable/MachineMadeWeft[FRAG,wght].ttf and
        fonts/sans/variable/MachineMadeSans[wght].ttf, and the licences weft/OFL.txt and
        sans/OFL.txt.
--out   where the files go; default fonts/ in this repository.

Writes mm-weft.woff2 and mm-sans.woff2, each cut to Latin-1 and the common punctuation, and
the two licences as mm-weft-OFL.txt and mm-sans-OFL.txt. Weft keeps both axes: wght 100 to
900 and FRAG limited to 0 to 15, the range for text. Sans keeps wght 200 to 800. The same
input gives the same bytes. Needs fontTools and brotli; build.py does not: it copies fonts/.
"""

import argparse
import hashlib
import io
import shutil
from pathlib import Path

from fontTools import subset  # type: ignore[import-untyped]
from fontTools.ttLib import TTFont  # type: ignore[import-untyped]
from fontTools.varLib import instancer  # type: ignore[import-untyped]

ROOT = Path(__file__).resolve().parent
# Latin-1, the dotless i, OE and oe, the spacing accents, dashes, quotes, dagger, bullet,
# ellipsis, single guillemets, fraction slash, euro, trade mark, minus.
UNICODES = (
    [*range(0x20, 0x7F), *range(0xA0, 0x100), 0x131, 0x152, 0x153, 0x2C6, 0x2DA, 0x2DC]
    + [0x2013, 0x2014, 0x2018, 0x2019, 0x201A, 0x201C, 0x201D, 0x201E, 0x2020, 0x2021, 0x2022]
    + [0x2026, 0x2039, 0x203A, 0x2044, 0x20AC, 0x2122, 0x2212]
)
FAMILIES = (
    ("mm-weft", "fonts/weft/variable/MachineMadeWeft[FRAG,wght].ttf", "weft/OFL.txt", {"FRAG": (0, 15)}),
    ("mm-sans", "fonts/sans/variable/MachineMadeSans[wght].ttf", "sans/OFL.txt", {}),
)


def cut(source: Path, limits: dict[str, tuple[int, int]]) -> bytes:
    font = TTFont(source, recalcTimestamp=False)
    if limits:
        font = instancer.instantiateVariableFont(
            font, {tag: instancer.AxisTriple(lo, lo, hi) for tag, (lo, hi) in limits.items()}
        )
        # Save and load again, so the subsetter reads compiled tables, as from a file.
        buffer = io.BytesIO()
        font.save(buffer)
        buffer.seek(0)
        font = TTFont(buffer, recalcTimestamp=False)
    options = subset.Options()
    options.flavor = "woff2"
    options.name_IDs = ["*"]
    options.notdef_outline = True
    sub = subset.Subsetter(options)
    sub.populate(unicodes=UNICODES)
    sub.subset(font)
    out = io.BytesIO()
    font.flavor = "woff2"
    font.recalcTimestamp = False
    font.save(out, reorderTables=True)
    return out.getvalue()


def main() -> None:
    parser = argparse.ArgumentParser(description="Web fonts of the site, cut from machine-made/type")
    parser.add_argument("--type", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=ROOT / "fonts")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    for name, font_rel, licence_rel, limits in FAMILIES:
        source, licence = args.type / font_rel, args.type / licence_rel
        for path in (source, licence):
            if not path.is_file():
                raise SystemExit(f"FAIL type: {path} is missing")
        data = cut(source, limits)
        (args.out / f"{name}.woff2").write_bytes(data)
        shutil.copyfile(licence, args.out / f"{name}-OFL.txt")
        digest = hashlib.sha256(source.read_bytes()).hexdigest()[:12]
        print(f"{name}.woff2: {len(data)} bytes from {source.name} ({source.stat().st_size} bytes, sha256 {digest})")


if __name__ == "__main__":
    main()
