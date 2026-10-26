#!/usr/bin/env python3
"""Screenshots of docs/index.html. Needs Playwright; build.py and check_site.py do not.

Usage: python3 shots.py [--out DIR] [--fonts DIR]
--out    where the PNG files go; default ./shots/ in this repository (git ignores it)
--fonts  a folder of Geist woff2 files (names like geist-latin-400-normal.woff2). It stands in
         for Google Fonts when the network blocks them. The page itself never reads it.
"""

import argparse
import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent
VIEWPORTS = {"1440": (1440, 900), "375": (375, 812)}
FACES = (
    ("Geist", "geist", 400),
    ("Geist", "geist", 500),
    ("Geist Mono", "geist-mono", 400),
    ("Geist Mono", "geist-mono", 500),
)


def font_routes(page, fonts):
    files = {p.name: p for p in fonts.rglob("*.woff2")}
    css = "".join(
        "@font-face{font-family:'%s';font-weight:%d;font-display:swap;"
        "src:url(https://fonts.gstatic.com/local/%s-latin-%d-normal.woff2) format('woff2')}"
        % (family, weight, slug, weight)
        for family, slug, weight in FACES
    )
    page.route(
        "https://fonts.googleapis.com/**",
        lambda route: route.fulfill(status=200, content_type="text/css", body=css),
    )

    def serve(route):
        name = route.request.url.rsplit("/", 1)[-1]
        if name in files:
            route.fulfill(status=200, content_type="font/woff2", body=files[name].read_bytes())
        else:
            route.abort()

    page.route("https://fonts.gstatic.com/**", serve)


def main():
    parser = argparse.ArgumentParser(description="Screenshots of docs/index.html")
    parser.add_argument("--out", type=Path, default=ROOT / "shots")
    parser.add_argument("--fonts", type=Path)
    args = parser.parse_args()
    fonts, out = args.fonts, args.out
    out.mkdir(parents=True, exist_ok=True)
    url = (ROOT / "docs" / "index.html").as_uri()
    report = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for label, (width, height) in VIEWPORTS.items():
            for scheme in ("light", "dark"):
                ctx = browser.new_context(
                    viewport={"width": width, "height": height}, color_scheme=scheme
                )
                page = ctx.new_page()
                if fonts:
                    font_routes(page, fonts)
                page.goto(url, wait_until="networkidle")
                page.evaluate("document.fonts.ready")
                for img in page.query_selector_all("img[loading=lazy]"):
                    img.scroll_into_view_if_needed()
                page.evaluate("window.scrollTo(0, 0)")
                page.wait_for_timeout(300)
                metrics = page.evaluate(
                    "({scrollWidth: document.documentElement.scrollWidth, innerWidth: window.innerWidth})"
                )
                path = out / f"home-{label}-{scheme}.png"
                page.screenshot(path=str(path), full_page=True)
                report.append({"shot": str(path), **metrics, "fits": metrics["scrollWidth"] <= metrics["innerWidth"]})
                ctx.close()
        browser.close()
    print(json.dumps(report, indent=1))
    if not all(r["fits"] for r in report):
        sys.exit(1)


if __name__ == "__main__":
    main()
