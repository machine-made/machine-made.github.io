#!/usr/bin/env python3
"""Screenshots of a house site, and the layout checks. Needs Playwright; build.py and check_site.py do not.

Usage: python3 shots.py [--site DIR] [--out DIR] [--chrome PATH]
--site    the folder that holds docs/ (default: this repository)
--out     where the PNG files go (390 and 1280 px); default ./shots/ in this repository (git ignores it)
--chrome  a Chrome or Chromium binary, when Playwright has no browser of its own

The scroll check runs at 320, 360, 390, 720, 1000, 1280 and 1920 px. The same run checks that every
font face the page uses loaded, that all text is a machine-made font at weight 400 and normal style (no
faux bold or italic), that no image failed to load and every image has width and height, that no line of
copy has 70 characters or more, that the page asks for no file outside docs/, that the plate images are
equal in height with equal gaps, that exactly one entry of the top bar is marked and is not a link, and
that the screenshots have the width asked for. At 390 px it also checks the 16 px side margin and that
every link is at least 44 px high.
"""

import argparse
import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent
FIT_WIDTHS = (320, 360, 390, 720, 1000, 1280, 1920)
SHOT_WIDTHS = (390, 1280)
HEIGHT = 900
MAX_LINE = 70
FONTS_LOADED = "() => [...document.fonts].map(f => [f.family.replace(/^[\"']|[\"']$/g, ''), f.style, f.status])"
IMAGES_LOADED = "() => [...document.images].every(i => i.complete && i.naturalWidth > 0)"
LONGEST_LINE = """() => {
  let longest = 0;
  for (const p of document.querySelectorAll("main p, main .ds, footer p")) {
    const lines = new Map();
    const walker = document.createTreeWalker(p, NodeFilter.SHOW_TEXT);
    for (let node = walker.nextNode(); node; node = walker.nextNode()) {
      const range = document.createRange();
      for (let i = 0; i < node.length; i++) {
        range.setStart(node, i);
        range.setEnd(node, i + 1);
        const rect = range.getClientRects()[0];
        if (!rect || rect.width === 0) continue;
        const key = Math.round((rect.top + rect.bottom) / 12);
        lines.set(key, (lines.get(key) || 0) + 1);
      }
    }
    for (const count of lines.values()) longest = Math.max(longest, count);
  }
  return longest;
}"""


# Every element that holds text: its computed family, weight and style.
TEXT_FACES = """() => {
  const out = [];
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  const seen = new Set();
  for (let n = walker.nextNode(); n; n = walker.nextNode()) {
    if (!n.textContent.trim() || seen.has(n.parentElement)) continue;
    seen.add(n.parentElement);
    const c = getComputedStyle(n.parentElement);
    out.push([n.parentElement.tagName, c.fontFamily.split(",")[0].replace(/^[\"']|[\"']$/g, ""), c.fontWeight, c.fontStyle]);
  }
  return out;
}"""
# The geometry of the page: images, plates, links, the top bar and the side margins.
GEOMETRY = """() => {
  const rect = (e) => { const r = e.getBoundingClientRect(); return [r.left, r.top, r.width, r.height]; };
  const plates = [...document.querySelectorAll(".plate img")].map(rect);
  const links = [...document.querySelectorAll("a:not(.skip)")].map((a) => [a.textContent.trim().slice(0, 20), a.getBoundingClientRect().height]);
  const wrap = document.querySelector("main").getBoundingClientRect();
  return {
    plates, links, left: wrap.left, right: document.documentElement.clientWidth - wrap.right,
    unsized: [...document.images].filter((i) => !i.getAttribute("width") || !i.getAttribute("height")).length,
    current: [...document.querySelectorAll(".bar [aria-current]")].map((e) => e.tagName),
    barLinks: document.querySelectorAll(".bar a").length,
  };
}"""


def plate_problems(plates: list[list[float]]) -> list[str]:
    """Equal heights, and equal horizontal gaps inside every row and from row to row."""
    problems = []
    heights = {round(h, 1) for _, _, _, h in plates}
    if len(heights) > 1:
        problems.append(f"plate images differ in height: {sorted(heights)}")
    gaps = set()
    rows: dict[int, list[list[float]]] = {}
    for plate in plates:
        rows.setdefault(round(plate[1]), []).append(plate)
    for row in rows.values():
        row.sort()
        gaps |= {round(b[0] - (a[0] + a[2]), 1) for a, b in zip(row, row[1:])}
    if len(gaps) > 1:
        problems.append(f"gaps between plate images differ: {sorted(gaps)}")
    return problems


def png_width(path: Path) -> int:
    return int.from_bytes(path.read_bytes()[16:20], "big")


def main() -> None:
    parser = argparse.ArgumentParser(description="Screenshots of docs/index.html")
    parser.add_argument("--site", type=Path, default=ROOT)
    parser.add_argument("--out", type=Path, default=ROOT / "shots")
    parser.add_argument("--chrome", default=None)
    args = parser.parse_args()
    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    docs_dir = args.site.resolve() / "docs"
    url = (docs_dir / "index.html").as_uri()
    docs = docs_dir.as_uri() + "/"
    theme_font = json.loads((args.site / "site.json").read_text(encoding="utf-8"))["theme"]["font"]
    wanted_faces = {"machine-made Weft", theme_font}
    # Every face of a family the page uses is declared; only the faces the text uses must be loaded. A face
    # the page does not use (an italic that no text asks for) stays unloaded, and none may fail.
    report = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=args.chrome) if args.chrome else pw.chromium.launch()
        for width in FIT_WIDTHS:
            ctx = browser.new_context(viewport={"width": width, "height": HEIGHT}, color_scheme="dark")
            page = ctx.new_page()
            outside: list[str] = []
            page.on("request", lambda req, outside=outside: req.url.startswith(docs) or outside.append(req.url))
            page.goto(url, wait_until="networkidle")
            for img in page.query_selector_all("img[loading=lazy]"):
                img.scroll_into_view_if_needed()
            page.wait_for_load_state("networkidle")
            page.evaluate("document.fonts.ready")
            page.evaluate("window.scrollTo(0, 0)")
            page.wait_for_timeout(300)
            metrics = page.evaluate(
                "({scrollWidth: document.documentElement.scrollWidth, innerWidth: window.innerWidth})"
            )
            entry = {"width": width, **metrics}
            entry["fits"] = metrics["scrollWidth"] <= metrics["innerWidth"]
            entry["longest_line"] = page.evaluate(LONGEST_LINE)
            entry["measure_ok"] = entry["longest_line"] < MAX_LINE
            statuses = page.evaluate(FONTS_LOADED)
            entry["fonts_ok"] = (
                all(st == "loaded" for _, style, st in statuses if style == "normal")
                and all(st != "error" for _, _, st in statuses)
                and wanted_faces <= {f for f, _, _ in statuses}
            )
            faces = page.evaluate(TEXT_FACES)
            entry["faces_bad"] = sorted({f"{tag} {fam} {w} {st}" for tag, fam, w, st in faces
                                         if not fam.startswith("machine-made ") or w != "400" or st != "normal"})
            geometry = page.evaluate(GEOMETRY)
            entry["geometry_bad"] = plate_problems(geometry["plates"])
            if geometry["unsized"]:
                entry["geometry_bad"].append(f"{geometry['unsized']} images have no width and height")
            if len(geometry["current"]) != 1 or geometry["current"][0] != "SPAN" or geometry["barLinks"] != 3:
                entry["geometry_bad"].append("the top bar must hold one marked span and three links")
            if width == 390:
                if round(geometry["left"], 1) != 16 or round(geometry["right"], 1) != 16:
                    entry["geometry_bad"].append(f"side margins at 390 px are {geometry['left']} and {geometry['right']}, not 16")
                short = [(name, round(h, 1)) for name, h in geometry["links"] if h < 44]
                if short:
                    entry["geometry_bad"].append(f"links below 44 px high at 390 px: {short}")
            entry["images_ok"] = page.evaluate(IMAGES_LOADED)
            entry["outside"] = outside
            if width in SHOT_WIDTHS:
                path = out / f"home-{width}.png"
                page.screenshot(path=str(path), full_page=True)
                entry["shot"] = str(path)
                entry["shot_width"] = png_width(path)
                entry["shot_ok"] = entry["shot_width"] == width
            report.append(entry)
            ctx.close()
        browser.close()
    print(json.dumps(report, indent=1))
    ok = all(
        r["fits"] and r["measure_ok"] and r["fonts_ok"] and r["images_ok"] and not r["outside"] and r.get("shot_ok", True)
        and not r["faces_bad"] and not r["geometry_bad"]
        for r in report
    )
    if not ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
