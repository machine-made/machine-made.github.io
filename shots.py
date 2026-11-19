#!/usr/bin/env python3
"""Screenshots of a house site, and the checks that need a browser. Needs Playwright; build.py does not.

  uv run --with playwright==1.65.1 python3 shots.py [--site DIR] [--out DIR] [--chrome PATH] [--axe FILE]

--site    the folder that holds docs/ (default: this repository)
--out     where the PNG files and report.json go; default ./shots/ in this repository (git ignores it)
--chrome  a Chrome or Chromium binary, when Playwright has no browser of its own
--axe     axe.min.js of axe-core; with it, axe runs on the home page and the 404 page and every violation fails

The site is served over HTTP the way GitHub Pages serves it: a missing path gets 404.html with status 404.

At 320, 360, 390, 720, 1000, 1280 and 1920 px the run checks: no sideways scroll and no element past the right edge
outside a scrolling or clipping box; every font face the page uses loaded, all text in a machine-made font at weight
400 and normal style (no faux bold or italic); no image failed to load and every image has width and height; no line
of reading text has 70 characters or more; the page asks for no file outside the site; in each plate grid the images
are equal in height with equal gaps; exactly one entry of bar 1 is marked and it is not a link; one h1 and no skipped
heading level; Latest names no repository twice. At 1280 and 1920 px no facts line wraps. At 390 px the side margins
are 16 px and every link is at least 44 px high. At 390 and 1280 px, on the home page and the 404 page, no glyph is
drawn in a system font (Chrome's platform-fonts query). The 404 page is loaded at a nested missing path and must load
its fonts and images. Shots: home and 404 at 390 and 1280 px, full page.
"""

import argparse
import functools
import http.server
import json
import sys
import threading
from itertools import pairwise
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent
FIT_WIDTHS = (320, 360, 390, 720, 1000, 1280, 1920)
SHOT_WIDTHS = (390, 1280)
HEIGHT = 900
MAX_LINE = 70
FAMILIES = {"weft": "mm Weft", "sans": "mm Sans", "heddle": "mm Heddle", "warp": "mm Warp"}
FONTS_LOADED = "() => [...document.fonts].map(f => [f.family.replace(/^[\"']|[\"']$/g, ''), f.style, f.status])"
IMAGES_LOADED = "() => [...document.images].every(i => i.complete && i.naturalWidth > 0)"
SCROLL_ALL = """async () => {
  for (let y = 0; y < document.body.scrollHeight; y += innerHeight / 2) { scrollTo(0, y); await new Promise(r => setTimeout(r, 80)); }
  scrollTo(0, 0);
}"""
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
# The geometry of the page: images per plate grid, links, bar 1, the side margins, elements past the right edge.
GEOMETRY = """() => {
  const rect = (e) => { const r = e.getBoundingClientRect(); return [r.left, r.top, r.width, r.height]; };
  const grids = [...document.querySelectorAll("ul.grid")].map((g) => [...g.querySelectorAll(".plate img")].map(rect));
  const links = [...document.querySelectorAll("a:not(.skip)")].map((a) => [a.textContent.trim().slice(0, 20) || a.getAttribute("aria-label"), a.getBoundingClientRect().height]);
  const wrap = document.querySelector("main > *").getBoundingClientRect();
  const width = document.documentElement.clientWidth;
  const contained = (e) => { for (let p = e.parentElement; p; p = p.parentElement) { const o = getComputedStyle(p).overflowX; if (o !== "visible") return true; } return false; };
  const past = [...document.body.querySelectorAll("*")].filter((e) => !e.closest(".skip, .vh") && e.getBoundingClientRect().right > width + 0.5 && !contained(e)).map((e) => e.tagName + "." + e.className);
  return {
    grids, links, left: wrap.left, right: width - wrap.right, past,
    unsized: [...document.images].filter((i) => !i.getAttribute("width") || !i.getAttribute("height")).length,
    current: [...document.querySelectorAll(".b1 [aria-current]")].map((e) => e.tagName),
    barLinks: document.querySelectorAll(".b1 a").length,
  };
}"""
PROBE = """() => {
  const levels = [...document.querySelectorAll("h1, h2, h3, h4, h5, h6")].map((h) => +h.tagName[1]);
  const lines = (el) => { const r = document.createRange(); r.selectNodeContents(el); return new Set([...r.getClientRects()].filter((x) => x.width > 0).map((x) => Math.round(x.top))).size; };
  const wrapped = [...document.querySelectorAll(".facts")].filter((el) => lines(el) > 1).map((el) => el.textContent.trim());
  const latest = [...document.querySelectorAll(".latest li > a")].map((a) => a.textContent.trim());
  return {levels, wrapped, latest, facts: document.querySelectorAll("main .grid:not(.g3) .plate .facts").length, plates: document.querySelectorAll("main .grid:not(.g3) .plate").length};
}"""
BYTES = """() => {
  const out = {font: 0, image: 0};
  performance.getEntriesByType("resource").forEach((e) => {
    const n = e.name.split("?")[0];
    const b = e.encodedBodySize || e.transferSize || 0;
    if (/\\.woff2$/.test(n)) out.font += b;
    else if (/\\.(avif|webp|jpe?g|png|svg)$/.test(n)) out.image += b;
  });
  return out;
}"""


class Pages(http.server.SimpleHTTPRequestHandler):
    """GitHub Pages: a missing path gets 404.html with status 404."""

    def log_message(self, *args: object) -> None:
        pass

    def send_error(self, code: int, message: str | None = None, explain: str | None = None) -> None:
        page = Path(self.directory) / "404.html"
        if code != 404 or not page.is_file():
            super().send_error(code, message, explain)
            return
        body = page.read_bytes()
        self.send_response(404)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def serve(docs: Path) -> tuple[http.server.ThreadingHTTPServer, str]:
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Pages, directory=str(docs)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}/"


def plate_problems(grids: list[list[list[float]]]) -> list[str]:
    """In each plate grid: equal image heights, and equal horizontal gaps inside every row."""
    problems = []
    for grid in grids:
        heights = {round(h, 1) for _, _, _, h in grid}
        if len(heights) > 1:
            problems.append(f"plate images differ in height: {sorted(heights)}")
        gaps = set()
        rows: dict[int, list[list[float]]] = {}
        for plate in grid:
            rows.setdefault(round(plate[1]), []).append(plate)
        for row in rows.values():
            row.sort()
            gaps |= {round(b[0] - (a[0] + a[2]), 1) for a, b in pairwise(row)}
        if len(gaps) > 1:
            problems.append(f"gaps between plate images differ: {sorted(gaps)}")
    return problems


def system_fonts(context: object, page: object) -> list[str]:
    """Every text node drawn, even in part, in a font that is not a web font of the page."""
    cdp = context.new_cdp_session(page)  # type: ignore[attr-defined]
    cdp.send("DOM.enable")
    cdp.send("CSS.enable")
    root = cdp.send("DOM.getDocument", {"depth": -1, "pierce": False})["root"]
    bad: list[str] = []

    def walk(node: dict) -> None:
        if node.get("nodeName") in ("SCRIPT", "STYLE", "HEAD", "TITLE"):
            return
        kids = node.get("children", [])
        if any(c.get("nodeType") == 3 and c.get("nodeValue", "").strip() for c in kids):
            fonts = cdp.send("CSS.getPlatformFontsForNode", {"nodeId": node["nodeId"]})["fonts"]
            text = "".join(c.get("nodeValue", "") for c in kids if c.get("nodeType") == 3).strip()
            bad.extend(f'{f["familyName"]} x{f["glyphCount"]} in "{text[:30]}"' for f in fonts if not f.get("isCustomFont"))
        for c in kids:
            walk(c)

    walk(root)
    cdp.detach()
    return bad


def main() -> None:
    parser = argparse.ArgumentParser(description="Screenshots and browser checks of docs/")
    parser.add_argument("--site", type=Path, default=ROOT)
    parser.add_argument("--out", type=Path, default=ROOT / "shots")
    parser.add_argument("--chrome", default=None)
    parser.add_argument("--axe", type=Path, default=None)
    args = parser.parse_args()
    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    docs = args.site.resolve() / "docs"
    face = json.loads((args.site / "site.json").read_text(encoding="utf-8"))["theme"]["face"]
    wanted = {FAMILIES["weft"], FAMILIES["sans"], FAMILIES[face]}
    axe = args.axe.read_text(encoding="utf-8") if args.axe else None
    server, base = serve(docs)
    report: list[dict] = []
    try:
        with sync_playwright() as pw:
            launch = {"executable_path": args.chrome, "args": ["--no-sandbox"]} if args.chrome else {}
            browser = pw.chromium.launch(**launch)
            for width in FIT_WIDTHS:
                ctx = browser.new_context(viewport={"width": width, "height": HEIGHT}, color_scheme="dark", device_scale_factor=1)
                page = ctx.new_page()
                outside: list[str] = []
                page.on("request", lambda req, outside=outside: req.url.startswith(base) or outside.append(req.url))
                page.goto(base, wait_until="networkidle")
                page.evaluate("document.fonts.ready")
                first = page.evaluate(BYTES)
                page.evaluate(SCROLL_ALL)
                page.wait_for_load_state("networkidle")
                page.wait_for_timeout(300)
                entry: dict = {"page": "index", "width": width}
                metrics = page.evaluate("({scrollWidth: document.documentElement.scrollWidth, innerWidth: window.innerWidth})")
                entry.update(metrics)
                problems: list[str] = []
                if metrics["scrollWidth"] > metrics["innerWidth"]:
                    problems.append(f"the page scrolls sideways: {metrics['scrollWidth']} > {metrics['innerWidth']}")
                entry["longest_line"] = page.evaluate(LONGEST_LINE)
                if entry["longest_line"] >= MAX_LINE:
                    problems.append(f"a line of copy has {entry['longest_line']} characters")
                statuses = page.evaluate(FONTS_LOADED)
                if not (all(st == "loaded" for _, _, st in statuses) and wanted <= {f for f, _, _ in statuses}):
                    problems.append(f"fonts not loaded: {statuses}")
                faces = page.evaluate(TEXT_FACES)
                bad_faces = sorted({f"{tag} {fam} {w} {st}" for tag, fam, w, st in faces if fam not in wanted or w != "400" or st != "normal"})
                if bad_faces:
                    problems.append(f"text not in a machine-made face at 400 normal: {bad_faces[:4]}")
                geometry = page.evaluate(GEOMETRY)
                problems += plate_problems(geometry["grids"])
                if geometry["past"]:
                    problems.append(f"elements past the right edge: {geometry['past'][:4]}")
                if geometry["unsized"]:
                    problems.append(f"{geometry['unsized']} images have no width and height")
                if geometry["current"] != ["SPAN"] or geometry["barLinks"] != 3:
                    problems.append("bar 1 must hold one marked span and three links")
                if width == 390:
                    if round(geometry["left"], 1) != 16 or round(geometry["right"], 1) != 16:
                        problems.append(f"side margins at 390 px are {geometry['left']} and {geometry['right']}, not 16")
                    short = [(name, round(h, 1)) for name, h in geometry["links"] if h < 44]
                    if short:
                        problems.append(f"links below 44 px high at 390 px: {short}")
                probe = page.evaluate(PROBE)
                levels = probe["levels"]
                if levels.count(1) != 1 or levels[0] != 1 or any(b - a > 1 for a, b in pairwise(levels)):
                    problems.append(f"headings: {levels}")
                if width >= 1280 and probe["wrapped"]:
                    problems.append(f"facts lines wrap at {width} px: {probe['wrapped']}")
                if len(set(probe["latest"])) != len(probe["latest"]) or len(probe["latest"]) > 3:
                    problems.append(f"Latest repeats a repository: {probe['latest']}")
                if probe["facts"] != probe["plates"]:
                    problems.append(f"{probe['plates'] - probe['facts']} plates have no facts line")
                if not page.evaluate(IMAGES_LOADED):
                    problems.append("an image failed to load")
                if outside:
                    problems.append(f"requests outside the site: {outside[:3]}")
                if width in SHOT_WIDTHS:
                    shot = out / f"home-{width}.png"
                    page.screenshot(path=str(shot), full_page=True)
                    entry["shot"] = str(shot)
                    entry["bytes"] = {"first_view": first, "all": page.evaluate(BYTES)}
                    misses = system_fonts(ctx, page)
                    if misses:
                        problems.append(f"glyphs drawn in a system font: {misses[:3]}")
                if width == 1280 and axe:
                    page.add_script_tag(content=axe)
                    found = page.evaluate("async () => (await axe.run(document, {resultTypes: ['violations']})).violations.map(v => [v.id, v.nodes.length])")
                    entry["axe"] = found
                    if found:
                        problems.append(f"axe violations: {found}")
                entry["problems"] = problems
                report.append(entry)
                ctx.close()
            # The 404 page, where GitHub Pages serves it: at any missing path.
            for width in SHOT_WIDTHS:
                ctx = browser.new_context(viewport={"width": width, "height": HEIGHT}, color_scheme="dark", device_scale_factor=1)
                page = ctx.new_page()
                failed: list[str] = []
                page.on("response", lambda r, failed=failed: r.status >= 400 and r.request.resource_type != "document" and failed.append(r.url))
                response = page.goto(base + "no/such/page", wait_until="networkidle")
                page.evaluate("document.fonts.ready")
                page.wait_for_timeout(300)
                problems = []
                if response is None or response.status != 404:
                    problems.append("a missing path does not answer 404")
                if failed:
                    problems.append(f"the 404 page fails to load {failed[:3]}")
                statuses = page.evaluate(FONTS_LOADED)
                if not (all(st == "loaded" for _, _, st in statuses) and wanted <= {f for f, _, _ in statuses}):
                    problems.append(f"404 fonts not loaded: {statuses}")
                if not page.evaluate(IMAGES_LOADED):
                    problems.append("a 404 image failed to load")
                if page.evaluate("document.documentElement.scrollWidth > window.innerWidth"):
                    problems.append("the 404 page scrolls sideways")
                misses = system_fonts(ctx, page)
                if misses:
                    problems.append(f"404 glyphs drawn in a system font: {misses[:3]}")
                shot = out / f"404-{width}.png"
                page.screenshot(path=str(shot), full_page=True)
                entry = {"page": "404", "width": width, "shot": str(shot)}
                if width == 1280 and axe:
                    page.add_script_tag(content=axe)
                    found = page.evaluate("async () => (await axe.run(document, {resultTypes: ['violations']})).violations.map(v => [v.id, v.nodes.length])")
                    entry["axe"] = found
                    if found:
                        problems.append(f"404 axe violations: {found}")
                entry["problems"] = problems
                report.append(entry)
                ctx.close()
            browser.close()
    finally:
        server.shutdown()
    (out / "report.json").write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8")
    bad = [f"{r['page']}@{r['width']}: {p}" for r in report for p in r["problems"]]
    print("\n".join(bad) if bad else f"SHOTS OK ({len(report)} renders)")
    if bad:
        sys.exit(1)


if __name__ == "__main__":
    main()
