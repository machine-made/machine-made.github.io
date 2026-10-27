#!/usr/bin/env python3
"""Screenshots of docs/index.html. Needs Playwright; build.py and check_site.py do not.

Usage: python3 shots.py [--out DIR]
--out    where the PNG files go (375 and 1440 px, light and dark); default ./shots/ in this
         repository (git ignores it). The scroll check runs at 320, 360, 375, 720, 1000, 1440
         and 1920 px, in both schemes. The same run checks that no line of copy has 70
         characters or more, that the two fonts of the site loaded, and that the page asks for
         no file outside docs/.
"""

import argparse
import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent
FIT_WIDTHS = (320, 360, 375, 720, 1000, 1440, 1920)
SHOT_WIDTHS = (375, 1440)
HEIGHT = 900
MAX_LINE = 70
FAMILIES = ("machine-made Weft", "machine-made Sans")
FONTS_LOADED = """() => [...document.fonts].filter(
  f => %s.includes(f.family.replace(/"/g, "")) && f.status === "loaded").length""" % list(FAMILIES)
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
def main():
    parser = argparse.ArgumentParser(description="Screenshots of docs/index.html")
    parser.add_argument("--out", type=Path, default=ROOT / "shots")
    args = parser.parse_args()
    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    url = (ROOT / "docs" / "index.html").as_uri()
    docs = (ROOT / "docs").as_uri() + "/"
    report = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for width in FIT_WIDTHS:
            for scheme in ("light", "dark"):
                ctx = browser.new_context(
                    viewport={"width": width, "height": HEIGHT}, color_scheme=scheme
                )
                page = ctx.new_page()
                outside = []
                page.on("request", lambda req, outside=outside: req.url.startswith(docs) or outside.append(req.url))
                page.goto(url, wait_until="networkidle")
                page.evaluate("document.fonts.ready")
                loaded = page.evaluate(FONTS_LOADED)
                for img in page.query_selector_all("img[loading=lazy]"):
                    img.scroll_into_view_if_needed()
                page.evaluate("window.scrollTo(0, 0)")
                page.wait_for_timeout(300)
                metrics = page.evaluate(
                    "({scrollWidth: document.documentElement.scrollWidth, innerWidth: window.innerWidth})"
                )
                entry = {"width": width, "scheme": scheme, **metrics}
                entry["fits"] = metrics["scrollWidth"] <= metrics["innerWidth"]
                entry["longest_line"] = page.evaluate(LONGEST_LINE)
                entry["measure_ok"] = entry["longest_line"] < MAX_LINE
                entry["fonts_ok"] = loaded == len(FAMILIES)
                entry["outside"] = outside
                if width in SHOT_WIDTHS:
                    path = out / f"home-{width}-{scheme}.png"
                    page.screenshot(path=str(path), full_page=True)
                    entry["shot"] = str(path)
                report.append(entry)
                ctx.close()
        browser.close()
    print(json.dumps(report, indent=1))
    if not all(r["fits"] and r["measure_ok"] and r["fonts_ok"] and not r["outside"] for r in report):
        sys.exit(1)


if __name__ == "__main__":
    main()
