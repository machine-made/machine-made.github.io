#!/usr/bin/env python3
"""Screenshots of a house site, and the layout checks. Needs Playwright; build.py and check_site.py do not.

Usage: python3 shots.py [--site DIR] [--out DIR] [--chrome PATH]
--site    the folder that holds docs/ (default: this repository)
--out     where the PNG files go (390 and 1280 px); default ./shots/ in this repository (git ignores it)
--chrome  a Chrome or Chromium binary, when Playwright has no browser of its own

The scroll check runs at 320, 360, 390, 720, 1000, 1280 and 1920 px. The same run checks that every
font face of the page loaded, that no image failed to load, that no line of copy has 70 characters or
more, that the page asks for no file outside docs/ and that the screenshots have the width asked for.
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
FONTS_LOADED = "() => [...document.fonts].map(f => f.status)"
IMAGES_LOADED = "() => [...document.images].every(i => i.complete && i.naturalWidth > 0)"
LONGEST_LINE = """() => {
  let longest = 0;
  for (const p of document.querySelectorAll("main p, footer p")) {
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
            entry["fonts_ok"] = bool(statuses) and all(s == "loaded" for s in statuses)
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
        for r in report
    )
    if not ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
