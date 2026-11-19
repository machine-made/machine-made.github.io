#!/usr/bin/env python3
"""Check the built site in docs/.

  uv run --with fonttools==4.68.0 --with brotli==1.2.1 --with pillow==13.0.0 python3 check_site.py --data FILE [--site DIR] [--deny FILE]

Prints OK and exits 0 when every rule holds. Otherwise prints one line per failure and exits 1.
`--self-test` breaks a copy of docs/ in many ways and checks that each break is caught.

The checks read the public list of the house from allow.json (next to site.json): the owner, the line, the
colours and the face, the four sites, the projects in their groups, the project sites and the redirects. The page
passes only when site.json and allow.json agree. --data is the GitHub facts file that fetch.py wrote and build.py
read: every facts line, Latest and the houses row must match it. MM_DATA=FILE does the same.

The font checks open the font files, so they need fontTools and brotli; everything else is the standard library.

Private repository names are not kept in this repository. Rules that need them read a list from a file outside
the repository: `--deny FILE` or MM_DENY_FILE=FILE. FILE has one name per line. Without it, the allowlist rules
still reject every link and every repository-shaped name that is not public.
"""

import argparse
import datetime
import hashlib
import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from collections import Counter
from collections.abc import Callable, Iterator
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Literal, NoReturn
from urllib.parse import unquote, urlsplit

# The generator: src/system.css, fonts/, the allow.json of every house. ROOT is the house being checked.
GEN = Path(__file__).resolve().parent
ROOT = GEN
DOCS = ROOT / "docs"
SYSTEM_SRC = GEN / "src" / "system.css"
FONT_DIR = GEN / "fonts"

# The public list of the house. load_allow() fills it from allow.json.
OWNER = ""
LINE = ""
THEME: dict[str, str] = {}
SELF = ""
# The four sites as (name, url), in the order of bar 1.
SITES: tuple[tuple[str, str], ...] = ()
# (title, ("owner/repo", ...)) in page order.
GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = ()
# "owner/repo" -> the project's own site or documentation, linked after the description of the plate.
SITE_LINKS: dict[str, str] = {}
# "owner/repo" -> "docs" when that link is the documentation; every other site link reads "site".
SITE_LABELS: dict[str, str] = {}
# Moved repositories: docs/<name>/index.html forwards the old path to the new home.
REDIRECTS: dict[str, str] = {}
# The other two houses: name -> (line, repositories), from their allow.json in this generator.
OTHERS: dict[str, tuple[str, tuple[str, ...]]] = {}
# The GitHub facts (fetch.py): language, latest release, releases and last commit per repository; the newest
# release of each type family; the date of the fetch.
DATA: dict[str, Any] = {}

# The source fonts in fonts/: the release files of machine-made/type, unchanged. build.py cuts a subset of each
# for each page. The hash pins the file; fonts/SOURCES.json must say the same.
SOURCES = {
    "mm-weft.woff2": ("machine-made Weft", "0.2.0", "9115be68c727ae8c707eed1097f878fd7e7bd54fa75bd70b099e94e4e5e71e85"),
    "mm-sans.woff2": ("machine-made Sans", "0.2.0", "8ec52cf1b8a799dcda3aab4cf967d681cbd8bffd3f4cb581ed4e5ffa72e0864e"),
    "mm-heddle.woff2": ("machine-made Heddle", "0.2.0", "3f7d0bde0d436dc800abc9b9c760938f38f19c627cc3378bb199032c3a6ec0e1"),
    "mm-warp-regular.woff2": ("machine-made Warp", "0.2.0", "035042b467e6c138666b2e6b3b3a38eeb8d6dc3602ac4354f1e335e425101481"),
}
FONT_SOURCE = {"weft": "mm-weft.woff2", "sans": "mm-sans.woff2", "heddle": "mm-heddle.woff2", "warp": "mm-warp-regular.woff2"}
LICENCE = {"weft": "mm-weft-OFL.txt", "sans": "mm-sans-OFL.txt", "heddle": "mm-heddle-OFL.txt", "warp": "mm-warp-OFL.txt"}
# The CSS family of each font and its @font-face descriptors (variable weight and width ranges).
CSS_FAMILY = {"weft": "mm Weft", "sans": "mm Sans", "heddle": "mm Heddle", "warp": "mm Warp"}
DESCRIPTORS = {
    "weft": "font-weight:100 900", "sans": "font-weight:200 800",
    "heddle": "font-weight:100 900;font-stretch:70% 140%", "warp": "font-weight:400",
}
WEIGHTS = {"weft": (100, 900), "sans": (200, 800), "heddle": (100, 900), "warp": (400, 400)}
FACES = ("weft", "heddle", "warp")
# The OpenType features the style asks for, and kerning: a subset must keep each one its source has.
USED_FEATURES = {"ss01", "tnum", "onum", "pnum", "smcp", "c2sc", "kern"}
# Fallbacks in a font stack: machine-made families and CSS generic families only. No system font by name.
GENERIC_FAMILIES = {"system-ui", "ui-monospace", "monospace", "serif", "sans-serif"}
# The type scale: ratio 1.25 on 16 px. Step n is 1.25**n rem.
STEPS = range(-1, 6)
LEADING = "1.5"
# The spacing scale. Margins, paddings, gaps and insets use these tokens only.
SPACING = (4, 8, 12, 16, 24, 32, 48, 64, 96)
# Contrast floors: text and muted on the ground and on the surface; the accent marks only.
PAIRS = (("text", "ground", 7.0), ("muted", "ground", 4.5), ("text", "surface", 7.0), ("muted", "surface", 4.5), ("accent", "ground", 3.0))
THEME_KEYS = ("ground", "surface", "line", "text", "muted", "accent")
# Public sites that a licence text names. Only the licences may name them.
LICENCE_URLS = {
    "fonts/mm-weft-OFL.txt": ("github.com/machine-made/type",),
    "fonts/mm-sans-OFL.txt": ("github.com/machine-made/type", "github.com/tokotype/PlusJakartaSans"),
    "fonts/mm-heddle-OFL.txt": ("github.com/machine-made/type",),
    "fonts/mm-warp-OFL.txt": ("github.com/machine-made/type",),
}
# Bar 1 and the footer: the three sites, then the type site.
BAR_NAMES = ("machine-made", "openfluids", "BoringQuantSystems", "type")
TYPE_URL = "https://machine-made.github.io/type/"
TYPE_LINE = "Four typefaces, made by code."
# The tags that set bold or italic by themselves. The page uses none.
FAUX_TAGS = ("b", "strong", "i", "em", "cite", "dfn")
BANNER_SIZE = (1408, 469)
PLATE_SIZE = (704, 235)
BANNER_WIDTHS = (704, 1408)
PLATE_WIDTHS = (352, 704)
OG_SIZE = (1200, 630)
PNG_SIZES = {"img/icon.png": 64, "img/touch.png": 180, "img/avatar.png": 56}
MAX_IMAGE_BYTES = 400_000
PLATE_SIZES = "(min-width: 1264px) 282px, (min-width: 1000px) 22vw, (min-width: 520px) 46vw, calc(100vw - 32px)"
BANNER_SIZES = "(min-width: 1264px) 1200px, calc(100vw - 32px)"
VIEWPORT = '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">'
# The gradients the style may use, each a mask, each written exactly so: the banner fades at its top and bottom
# edge, and bar-2 sections fade at the right edge on a phone. Each appears with and without the -webkit- prefix.
MASKS = (
    "mask-image: linear-gradient(transparent, #000 10%, #000 90%, transparent);",
    "mask-image: linear-gradient(90deg, #000 calc(100% - var(--sp-6)), transparent);",
)
# The one CSS escape the style may hold: the middle dot drawn between facts and between footer names.
DOT = 'content: "\\00b7";'
FILE_NAME = re.compile(r"[a-z0-9][a-z0-9._-]*")
FORBIDDEN = re.compile(
    r"[$€£]\s?[0-9]|\b(?:usd|chf|eur)\s?[0-9]|[0-9]\s?(?:usd|chf|eur)\b"
    r"|tokens|punchcard|night-shift|nexus",
    re.I,
)
# Words that never appear in public text. The one exception is the line of pi-rethread.
BANNED = re.compile(r"\b(founder|brief|jac|card|session|codex)\b", re.I)
BANNED_OK = ("hand work to a fresh Pi session",)
NEVER = ("homebrew-tap",)
VOID = {"meta", "link", "img", "br", "hr", "input", "source", "track", "area", "base", "col", "embed", "wbr"}
GITHUB_URL = r"https://github\.com"
GITHUB = re.compile(r"github\.com/[\w.-]+(?:/[\w.-]+)*", re.I)
RS_NAME = re.compile(r"(?<![\w-])[a-z0-9][a-z0-9._-]*-rs(?![\w-])", re.I)
MAX_WORDS = 25
# Tags that run code or load a resource. The page needs none of them. <source> is allowed only inside <picture>.
FORBIDDEN_TAGS = (
    "script", "iframe", "object", "embed", "form", "input", "button", "audio", "video", "track", "base",
)
ALLOWED_ATTRS = {
    "lang", "charset", "name", "content", "rel", "href", "type", "crossorigin", "as", "class", "id",
    "src", "width", "height", "alt", "loading", "aria-labelledby", "property", "srcset", "sizes", "decoding",
    "fetchpriority", "imagesizes", "imagesrcset", "datetime", "viewbox", "focusable", "x", "y",
}
PAINT_PROPS = ("fill", "stroke", "stop-color", "flood-color", "lighting-color", "color")
PAINT_DECL = re.compile(r"(?<![\w-])(fill|stroke|stop-color|flood-color|lighting-color|color)\s*:\s*([^;}]+)")
PAINT_KEYWORDS = {"none", "currentcolor", "inherit", "transparent", "initial", "unset", "context-fill", "context-stroke"}
FRAGMENT_URL = re.compile(r"url\(\s*#[\w.-]+\s*\)(.*)", re.S)
URL_REF = re.compile(r"url\(\s*(['\"]?)(.*?)\1\s*\)", re.I | re.S)
IMPORT_REF = re.compile(r"@import\s+(['\"])(.*?)\1", re.I | re.S)
# Every CSS function that loads an image, except url(). url() is checked target by target.
IMAGE_FUNC = re.compile(
    r"(?<![\w-])((?:-(?:webkit|moz|ms|o)-)?(?:image-set|image|cross-fade|element|paint|src))\s*\(", re.I
)
# The 148 colour names of CSS Color 4 and its system colours. Only black and white are allowed.
NAMED_COLOURS = frozenset(
    """aliceblue antiquewhite aqua aquamarine azure beige bisque black blanchedalmond blue blueviolet
    brown burlywood cadetblue chartreuse chocolate coral cornflowerblue cornsilk crimson cyan darkblue
    darkcyan darkgoldenrod darkgray darkgreen darkgrey darkkhaki darkmagenta darkolivegreen darkorange
    darkorchid darkred darksalmon darkseagreen darkslateblue darkslategray darkslategrey darkturquoise
    darkviolet deeppink deepskyblue dimgray dimgrey dodgerblue firebrick floralwhite forestgreen fuchsia
    gainsboro ghostwhite gold goldenrod gray green greenyellow grey honeydew hotpink indianred indigo
    ivory khaki lavender lavenderblush lawngreen lemonchiffon lightblue lightcoral lightcyan
    lightgoldenrodyellow lightgray lightgreen lightgrey lightpink lightsalmon lightseagreen lightskyblue
    lightslategray lightslategrey lightsteelblue lightyellow lime limegreen linen magenta maroon
    mediumaquamarine mediumblue mediumorchid mediumpurple mediumseagreen mediumslateblue
    mediumspringgreen mediumturquoise mediumvioletred midnightblue mintcream mistyrose moccasin
    navajowhite navy oldlace olive olivedrab orange orangered orchid palegoldenrod palegreen
    paleturquoise palevioletred papayawhip peachpuff peru pink plum powderblue purple rebeccapurple red
    rosybrown royalblue saddlebrown salmon sandybrown seagreen seashell sienna silver skyblue slateblue
    slategray slategrey snow springgreen steelblue tan teal thistle tomato turquoise violet wheat white
    whitesmoke yellow yellowgreen""".split()
)
SYSTEM_COLOURS = frozenset(
    """accentcolor accentcolortext activetext buttonborder buttonface buttontext canvas canvastext field
    fieldtext graytext highlight highlighttext linktext mark marktext selecteditem selecteditemtext
    visitedtext""".split()
)
GREY_NAMES = {"black": "#000000", "white": "#ffffff"}
WORD = re.compile(r"(?<![\w-])[a-z][a-z-]*(?![\w-])", re.I)
CssKind = Literal["css", "svg"]
SVG_FORBIDDEN = {
    "script", "foreignObject", "image", "iframe", "object", "embed", "audio", "video",
    "linearGradient", "radialGradient", "stop",
}
RED = "#e5251c"
MONTHS = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()

failures: list[str] = []


def fail(rule: str, message: str) -> None:
    line = f"FAIL {rule}: {message}"
    if line not in failures:
        failures.append(line)


def site_json() -> dict[str, Any]:
    try:
        data = json.loads((ROOT / "site.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def site_title(name: str | None) -> str | None:
    """The name as people read it: site.json title (the name with capitals) when set, else the name."""
    if not name:
        return None
    title = site_json().get("title", name)
    if not isinstance(title, str) or title.lower() != name:
        fail("site", "site.json title must be the name with capitals only")
        return name
    return title


def site_name() -> str | None:
    """The site name from site.json, under the same file-name rule as build.py. None if unusable."""
    name = site_json().get("name")
    if not isinstance(name, str) or not FILE_NAME.fullmatch(name) or ".." in name:
        fail("site", "site.json has no readable name, or it is not a safe file name")
        return None
    return name


def repos_of(groups: tuple[tuple[str, tuple[str, ...]], ...] | None = None) -> list[str]:
    """Every 'owner/repo' of the public list, in page order."""
    return [full for _, fulls in (GROUPS if groups is None else groups) for full in fulls]


def uses() -> list[str]:
    """The fonts the house loads: Weft and Sans, and its face when that is not Weft."""
    face = THEME.get("face", "weft")
    return ["weft", "sans"] + ([face] if face != "weft" else [])


def house_key(name: str) -> str:
    return name.lower()


Attrs = dict[str, str | None]


class Page(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[str] = []
        self.ids: list[str] = []
        self.links: list[Attrs] = []
        self.imgs: list[Attrs] = []
        self.sources: list[tuple[Attrs, str]] = []
        self.metas: list[Attrs] = []
        self.tags: list[str] = []
        self.text: list[str] = []
        self.values: list[str] = []
        self.headings: list[tuple[str, str]] = []
        self.hidden: list[str] = []
        self.paragraphs: list[str] = []
        self.paragraph: str | None = None
        self.styles: list[str] = []
        self.unknown_attrs: list[str] = []
        self.first_link: Attrs | None = None
        self.heading: list[str] | None = None
        self.problems: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        names = [k for k, _ in attrs]
        if len(set(names)) != len(names):
            self.problems.append(f"<{tag}> repeats an attribute")
        a: Attrs = dict(attrs)
        self.tags.append(tag)
        id_value = a.get("id")
        if id_value is not None:
            self.ids.append(id_value)
        for key, value in attrs:
            if key not in ALLOWED_ATTRS and not key.startswith("aria-"):
                self.unknown_attrs.append(f"<{tag}> has the attribute {key}")
            if value is None:
                continue
            if key in ("class", "id", "charset", "name", "rel", "lang"):
                self.hidden.append(value)
            else:
                self.values.append(value)
            if key.startswith("on"):
                self.problems.append(f"<{tag}> has an event handler ({key})")
        if tag == "a":
            self.links.append(a)
            if self.first_link is None:
                self.first_link = a
        if tag == "link" and "href" in a:
            self.links.append({"href": a["href"], "rel": a.get("rel") or "", "tag": "link"})
        if tag == "meta":
            self.metas.append(a)
        if tag == "img":
            self.imgs.append({**a, "in_h1": "1" if "h1" in self.stack else None})
            if self.heading is not None:
                self.heading[1] += a.get("alt") or ""
        if tag == "source":
            self.sources.append((a, self.stack[-1] if self.stack else ""))
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self.heading = [tag, ""]
        if tag == "p":
            self.paragraph = ""
        if tag not in VOID:
            self.stack.append(tag)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag not in VOID and self.stack and self.stack[-1] == tag:
            self.stack.pop()

    def handle_endtag(self, tag: str) -> None:
        if tag in VOID:
            self.problems.append(f"</{tag}> closes a void element")
        elif not self.stack or self.stack[-1] != tag:
            self.problems.append(f"</{tag}> does not match the open <{self.stack[-1] if self.stack else 'nothing'}>")
        else:
            self.stack.pop()
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6") and self.heading:
            self.headings.append((self.heading[0], self.heading[1].strip()))
            self.heading = None
        if tag == "p" and self.paragraph is not None:
            self.paragraphs.append(" ".join(self.paragraph.split()))
            self.paragraph = None

    def handle_comment(self, data: str) -> None:
        self.hidden.append(data)

    def handle_data(self, data: str) -> None:
        if self.stack and self.stack[-1] in ("style", "script"):
            self.hidden.append(data)
            if self.stack[-1] == "style":
                self.styles.append(data)
            return
        self.text.append(data)
        if self.heading:
            self.heading[1] += data
        if self.paragraph is not None:
            self.paragraph += data

    def error(self, message: str) -> None:
        self.problems.append(message)


def parse(text: str) -> Page:
    page = Page()
    page.feed(text)
    page.close()
    return page


def luminance(hexcolour: str) -> float:
    h = hexcolour.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    channels = []
    for i in (0, 2, 4):
        c = int(h[i : i + 2], 16) / 255
        channels.append(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4)
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def contrast(a: str, b: str) -> float:
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


HEX = re.compile(r"#[0-9a-fA-F]+\b")
FUNC = re.compile(r"\b(?:rgba?|hsla?|hwb|lab|lch|oklab|oklch|color|color-mix|light-dark|device-cmyk)\(", re.I)


def colours_of(text: str, where: str) -> set[str]:
    """Return the set of 6-digit colours in text; fail on forms that hide a colour."""
    found: set[str] = set()
    for hit in HEX.findall(text):
        h = hit.lstrip("#")
        if len(h) in (4, 8):
            fail("colour", f"{where} has {hit}, a colour with alpha; use #rgb or #rrggbb")
            continue
        if len(h) not in (3, 6):
            fail("colour", f"{where} has {hit}, which is not a colour")
            continue
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        found.add("#" + h.lower())
    if FUNC.search(text):
        fail("colour", f"{where} uses a colour function; write colours as hex")
    if "gradient" in text.lower():
        fail("colour", f"{where} uses a gradient")
    return found


def split_accent(colours: set[str]) -> set[str]:
    """The colours that are not greys."""
    greys = {c for c in colours if c[1:3] == c[3:5] == c[5:7]}
    return colours - greys


def read(rel: str) -> str:
    path = DOCS / rel
    if not path.is_file():
        fail("files", f"{rel} is missing; run python3 build.py")
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def slug(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")


def esc(text: str) -> str:
    return html.escape(text, quote=True)


# ------------------------------------------------------------------ the expected markup, from allow.json and the facts
def date_text(iso: str) -> str:
    d = datetime.date.fromisoformat(iso[:10])
    year = datetime.date.fromisoformat(DATA["fetched"]).year
    return f"{d.day} {MONTHS[d.month - 1]}" + ("" if d.year == year else f" {d.year}")


def time_html(iso: str) -> str:
    return f'<time datetime="{iso[:10]}">{date_text(iso)}</time>'


def facts_html(parts: list[str]) -> str:
    return '<p class="facts"><span>' + "".join(f"<span>{p}</span>" for p in parts) + "</span></p>"


def repo_facts(full: str) -> str:
    r = DATA["repos"][full]
    parts = [esc(r["lang"])] if r["lang"] else []
    parts.append(esc(r["release"]["tagName"]) if r["release"] else "unreleased")
    parts.append(time_html(r["commit"]))
    return facts_html(parts)


def newest(fulls: list[str]) -> list[tuple[str, str, dict[str, str]]]:
    """The newest release of each repository, newest first: (date, repository, release)."""
    found = []
    for full in fulls:
        releases = DATA["repos"][full]["releases"]
        if releases:
            r = max(releases, key=lambda x: x["publishedAt"])
            found.append((r["publishedAt"], full.split("/")[1], r))
    return sorted(found, key=lambda x: (x[0], x[1]), reverse=True)


def picture(prefix: str, stem: str, widths: tuple[int, int], size: tuple[int, int], alt: str, sizes: str, lazy: bool = True) -> str:
    load = 'loading="lazy" decoding="async"' if lazy else 'decoding="async" fetchpriority="high"'
    avif = ", ".join(f"{prefix}img/{stem}-{w}.avif {w}w" for w in widths)
    jpeg = ", ".join(f"{prefix}img/{stem}-{w}.jpg {w}w" for w in widths)
    return (
        f'<picture><source type="image/avif" srcset="{avif}" sizes="{sizes}">'
        f'<img src="{prefix}img/{stem}-{widths[1]}.jpg" srcset="{jpeg}" sizes="{sizes}" width="{size[0]}" height="{size[1]}" alt="{esc(alt)}" {load}></picture>'
    )


MK = (
    '<svg class="mk" viewBox="0 0 30 30" aria-hidden="true" focusable="false">'
    + "".join(f'<rect class="{"on" if (x, y) == (11, 11) else "o"}" x="{x}" y="{y}" width="8" height="8"/>' for y in (0, 11, 22) for x in (0, 11, 22))
    + "</svg>"
)


def label_html(text: str, ident: str) -> str:
    return f'<h2 class="lbl" id="{ident}">{MK}<span>{esc(text)}</span></h2>'


def bar1_html() -> str:
    lis = "".join(
        f'<li><span aria-current="page">{esc(n)}</span></li>' if n == SELF else f'<li><a href="{esc(u)}">{esc(n)}</a></li>'
        for n, u in SITES
    )
    return f'<nav class="b1" aria-label="Sites"><ul class="wrap">{lis}</ul></nav>'


def footer_html() -> str:
    return '<footer class="wrap"><div class="fl"><ul>' + "".join(f'<li><a href="{esc(u)}">{esc(n)}</a></li>' for n, u in SITES) + "</ul></div></footer>"


def latest_html() -> str:
    items = newest(repos_of())[:3]
    if not items:
        return ""
    lis = "".join(f'<li><a href="{esc(r["url"])}">{esc(repo)}</a>{facts_html([esc(r["tagName"]), time_html(r["publishedAt"])])}</li>' for _, repo, r in items)
    return f'<section class="row tight" aria-labelledby="g-latest">{label_html("Latest", "g-latest")}<ol class="latest n{len(items)}">{lis}</ol></section>'


def houses_html() -> str:
    lis = []
    for n, u in SITES:
        if n == SELF:
            continue
        if n == "type":
            img = picture("", "type", PLATE_WIDTHS, PLATE_SIZE, "", PLATE_SIZES)
            r = max(DATA["families"].items(), key=lambda kv: (kv[1]["publishedAt"], kv[0].capitalize()))
            fx = facts_html([f'{r[0].capitalize()} {esc(r[1]["tagName"].split("-")[-1])}', time_html(r[1]["publishedAt"])])
            caption = TYPE_LINE
        else:
            line, fulls = OTHERS[n]
            img = picture("", f"banner-{house_key(n)}", BANNER_WIDTHS, BANNER_SIZE, "", PLATE_SIZES)
            rel = newest(list(fulls))
            fx = facts_html([f"{esc(rel[0][1])} {esc(rel[0][2]['tagName'])}", time_html(rel[0][2]["publishedAt"])]) if rel else facts_html(["unreleased"])
            caption = line
        lis.append(f'<li class="plate"><a class="pic" href="{esc(u)}" aria-label="{esc(n)}">{img}</a><p class="ds">{esc(caption)}</p>{fx}</li>')
    return f'<section class="row" aria-labelledby="g-houses">{label_html("The houses", "g-houses")}<ul class="grid g3">{"".join(lis)}</ul></section>'


def plate_html(full: str, line: str | None = None) -> re.Pattern[str]:
    """The markup of one plate: the repository banner as a link to the repository, named by aria-label, with an
    empty alt text; one line under it, with the site or docs link of a project that has one; the live facts."""
    repo = full.split("/")[1]
    url = re.escape(f"https://github.com/{full}")
    text = r"(?P<line>\S(?:[^<]*\S)?)" if line is None else re.escape(line)
    more = ""
    if full in SITE_LINKS:
        word = SITE_LABELS.get(full, "site")
        more = rf' <a href="{re.escape(esc(SITE_LINKS[full]))}" aria-label="{re.escape(repo)} {word}">{word}</a>'
    return re.compile(
        rf'<li class="plate"><a class="pic" href="{url}" aria-label="{re.escape(repo)}">'
        + re.escape(picture("", repo, PLATE_WIDTHS, PLATE_SIZE, "", PLATE_SIZES))
        + rf'</a><p class="ds">{text}{more}</p>{re.escape(repo_facts(full))}</li>'
    )


# ------------------------------------------------------------------ files, links, head
def wanted_files() -> set[str]:
    files = {"index.html", "404.html", "llms.txt", "og.jpg", "img/touch.png"}
    files |= {"mark.svg"} if SELF == "machine-made" else {"img/icon.png", "img/avatar.png"}
    for f in uses():
        files |= {f"fonts/{f}.woff2", f"fonts/{LICENCE[f]}"}
    stems = [(full.split("/")[1], PLATE_WIDTHS) for full in repos_of()] + [("type", PLATE_WIDTHS)]
    stems += [(f"banner-{house_key(n)}", BANNER_WIDTHS) for n, _ in SITES if n != "type"]
    files |= {f"img/{stem}-{w}.{ext}" for stem, widths in stems for w in widths for ext in ("avif", "jpg")}
    files |= {f"{folder}/index.html" for folder in REDIRECTS}
    return files


def check_files() -> None:
    wanted = wanted_files()
    present = {p.relative_to(DOCS).as_posix() for p in DOCS.rglob("*") if p.is_file()}
    for extra in sorted(present - wanted):
        fail("files", f"docs/{extra} is not part of the site")
    for missing in sorted(wanted - present):
        fail("files", f"docs/{missing} is missing; run python3 build.py")


def redirect_page(name: str, url: str) -> str:
    return (
        '<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f'<title>{name} has moved</title>\n<meta http-equiv="refresh" content="0; url={url}">\n'
        f'<link rel="canonical" href="{url}">\n</head>\n<body>\n<p><a href="{url}">{name} has moved</a></p>\n'
        "</body>\n</html>\n"
    )


def check_redirects() -> None:
    for name, url in REDIRECTS.items():
        if not url.startswith("https://"):
            fail("redirects", f"{name} must forward to an https URL")
        elif read(f"{name}/index.html") != redirect_page(name, url):
            fail("redirects", f"docs/{name}/index.html must be the plain redirect page to {url}")


def local_target(href: str, rooted: bool) -> Path | None:
    """The file a local link names, or None when it names nothing or leaves docs/. A rooted page (404.html) names
    every file from the site root (/img/x.jpg); the home page names it relative to itself (img/x.jpg). A folder
    means its index.html."""
    path = unquote(href.split("#", 1)[0].split("?", 1)[0])
    if not path:
        return None
    if path.startswith("/") != rooted:
        return None
    if rooted:
        path = path[1:] or "./"
    if path.endswith("/"):
        path += "index.html"
    root = DOCS.resolve()
    target = (DOCS / path).resolve()
    return target if root in target.parents else None


def release_urls() -> set[str]:
    return {r["url"] for full in repos_of() for r in DATA["repos"][full]["releases"]}


def allowed_https() -> set[str]:
    """Every https address that the page may link: the four sites, the project sites, the repositories, their
    releases and the organisation on GitHub."""
    return (
        {u for _, u in SITES} | set(SITE_LINKS.values()) | {f"https://github.com/{full}" for full in repos_of()}
        | release_urls() | {f"https://github.com/{OWNER}"}
    )


def srcset_urls(value: str) -> list[str]:
    return [part.strip().split()[0] for part in value.split(",") if part.strip()]


def check_html(page: Page, html_text: str, where: str, rooted: bool) -> None:
    """The rules both pages share: parse, head basics, no script, semantics, images and links."""
    for problem in page.problems:
        fail("parse", f"{where}: {problem}")
    if page.stack:
        fail("parse", f"{where}: unclosed tags: {', '.join(page.stack)}")
    if not html_text.lstrip().lower().startswith("<!doctype html>"):
        fail("parse", f"{where}: no doctype")
    if len(page.ids) != len(set(page.ids)):
        fail("parse", f"{where}: an id is used twice")
    if not re.search(r'<html lang="[a-z-]+"', html_text):
        fail("a11y", f"{where}: the html element has no lang")
    if VIEWPORT not in html_text:
        fail("responsive", f"{where}: no viewport meta")
    if '<meta name="color-scheme" content="dark">' not in html_text:
        fail("dark", f"{where}: the page is dark only: the color-scheme meta must be dark")
    if f'<meta name="theme-color" content="{THEME.get("ground", "")}">' not in html_text:
        fail("dark", f"{where}: the theme-color meta must be the ground colour of the house")
    if re.search(r"<title>[^<]+</title>", html_text) is None:
        fail("a11y", f"{where}: no title")
    for problem in page.unknown_attrs:
        fail("attrs", f"{where}: {problem}; the page uses no other attributes")
    for forbidden in FORBIDDEN_TAGS:
        if forbidden in page.tags:
            fail("no-js", f"{where}: <{forbidden}> is not allowed on a page that needs no script")
    for attrs, parent in page.sources:
        if parent != "picture" or attrs.get("type") != "image/avif" or "src" in attrs:
            fail("no-js", f"{where}: <source> is allowed only inside <picture>, as type image/avif with a srcset")
    for tag in ("header", "nav", "main", "footer", "h1"):
        if tag not in page.tags:
            fail("semantic", f"{where}: no <{tag}>")
    if page.tags.count("h1") != 1:
        fail("semantic", f"{where}: the page needs exactly one h1")
    if page.tags.count("main") != 1:
        fail("semantic", f"{where}: the page needs exactly one main")
    levels = [int(kind[1]) for kind, _ in page.headings]
    if levels and (levels[0] != 1 or any(b - a > 1 for a, b in zip(levels, levels[1:], strict=False))):
        fail("semantic", f"{where}: the headings skip a level: {levels}")
    for faux in FAUX_TAGS:
        if faux in page.tags:
            fail("fonts", f"{where}: <{faux}> sets bold or italic by itself; the page uses no bold and no italic")
    if html_text.count("aria-current=") != 1:
        fail("a11y", f"{where}: exactly one entry of bar 1 must carry aria-current")
    first: Attrs = page.first_link or {}
    if first.get("href") != "#main" or "main" not in page.ids:
        fail("a11y", f"{where}: the first link must be a skip link to #main")
    for img in page.imgs:
        # The banner in the h1 carries the house name. Every other image is decorative (alt=""): its link names it.
        if "alt" not in img or (img.get("in_h1") and not (img.get("alt") or "").strip()):
            fail("a11y", f"{where}: image {img.get('src')} has no alt attribute, or the banner has empty alt text")
        if not img.get("in_h1") and img.get("alt") != "":
            fail("a11y", f"{where}: image {img.get('src')} is decorative: its alt text is empty and its link carries the name")
        if not (img.get("width") and img.get("height")):
            fail("responsive", f"{where}: image {img.get('src')} has no width and height")
        for src in [img.get("src") or "", *srcset_urls(img.get("srcset") or "")]:
            target = local_target(src, rooted)
            if target is None or not target.is_file():
                fail("links", f"{where}: image {src} does not resolve inside docs/")
    for attrs, _ in page.sources:
        for src in srcset_urls(attrs.get("srcset") or ""):
            target = local_target(src, rooted)
            if target is None or not target.is_file():
                fail("links", f"{where}: image {src} does not resolve inside docs/")
    allowed = allowed_https()
    names = {u: n for n, u in SITES}
    for link in page.links:
        href = link.get("href") or ""
        parts = urlsplit(href)
        if link.get("class") == "pic":
            want = names.get(href) or href.rstrip("/").rsplit("/", 1)[-1]
            if (link.get("aria-label") or "").strip() != want:
                fail("a11y", f"{where}: the image link to {href} needs aria-label with the repository or site name")
        if href.startswith("#"):
            if href[1:] not in page.ids:
                fail("links", f"{where}: {href} points to no id")
        elif parts.scheme or parts.netloc:
            if parts.scheme.lower() != "https":
                fail("links", f"{where}: {href} is not an https link")
            elif link.get("tag") == "link":
                fail("links", f"{where}: {href} is an external resource; the page loads only files in docs/")
            elif href not in allowed:
                fail("links", f"{where}: {href} is not in the public list")
        else:
            target = local_target(href, rooted)
            if target is None or not target.is_file():
                fail("links", f"{where}: {href} does not resolve inside docs/")
            elif rooted and parts.fragment and target.name == "index.html":
                ids = parse(target.read_text(encoding="utf-8", errors="replace")).ids
                if parts.fragment not in ids:
                    fail("links", f"{where}: {href} points to no id on the home page")


def meta_values(page: Page, attr: str, key: str) -> list[str]:
    """The content of every <meta> whose attribute attr is key, whatever the order of its attributes."""
    return [a.get("content") or "" for a in page.metas if a.get(attr) == key]


def check_head(page: Page, html_text: str, shown: str | None, where: str, prefix: str) -> None:
    """The head: description, favicon, touch icon, and the social preview at 1200 by 630."""
    if meta_values(page, "name", "description") != [LINE]:
        fail("head", f"{where}: the description meta must be the house line, word for word")
    icon = (
        f'<link rel="icon" href="{prefix}mark.svg" type="image/svg+xml">' if SELF == "machine-made"
        else f'<link rel="icon" href="{prefix}img/icon.png" type="image/png" sizes="64x64">'
    )
    if html_text.count('rel="icon"') != 1 or icon not in html_text:
        fail("head", f"{where}: the page needs its favicon, {icon}")
    if f'<link rel="apple-touch-icon" href="{prefix}img/touch.png">' not in html_text:
        fail("head", f"{where}: the page needs its touch icon, {prefix}img/touch.png")
    home = dict(SITES).get(SELF, "")
    expected = {
        "og:type": "website", "og:title": shown or "", "og:description": LINE, "og:url": home,
        "og:image": f"{home}og.jpg", "og:image:width": str(OG_SIZE[0]), "og:image:height": str(OG_SIZE[1]),
        "og:image:alt": shown or "",
    }
    for key, value in expected.items():
        if meta_values(page, "property", key) != [value]:
            fail("head", f"{where}: the social preview meta {key} must be {value!r}; og:image is og.jpg at 1200 by 630")
    if meta_values(page, "name", "twitter:card") != ["summary_large_image"]:
        fail("head", f"{where}: the twitter:card meta must be summary_large_image")


def check_refs(text: str, where: str, kind: CssKind, rooted: bool = False) -> None:
    """url() and @import targets: css may load only local files; svg only #fragments.

    Every other CSS image function is refused, and so is a backslash, which can spell any name. The one escape
    allowed is the middle dot in a content string."""
    if "\\" in text.replace(DOT, "").replace(DOT.replace(": ", ":"), ""):
        fail("css", f"{where} has a backslash escape, which can hide a function or a colour name")
    for func in IMAGE_FUNC.finditer(text):
        fail("links", f"{where} uses {func.group(1).lower()}(); only url() may load an image")
    targets = [m.group(2).strip() for m in URL_REF.finditer(text)]
    targets += [m.group(2).strip() for m in IMPORT_REF.finditer(text)]
    for target in targets:
        if target.startswith("#"):
            continue
        parts = urlsplit(target)
        if kind == "svg":
            fail("links", f"{where} refers to {target[:50]!r}; an svg may refer only to its own ids")
        elif parts.scheme or parts.netloc:
            fail("links", f"{where} loads {target[:50]!r}; only local files are allowed")
        else:
            local = local_target(target, rooted)
            if local is None or not local.is_file():
                fail("links", f"{where} refers to {target[:50]!r}, which is not a file inside docs/")


# ------------------------------------------------------------------ the style
def system_css() -> str:
    """src/system.css as the page carries it: without comments and blank lines."""
    try:
        text = SYSTEM_SRC.read_text(encoding="utf-8")
    except OSError:
        fail("css", "src/system.css is missing")
        return ""
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return "\n".join(line.rstrip() for line in text.splitlines() if line.strip()) + "\n"


def faces_css(prefix: str) -> str:
    faces = "".join(
        f'@font-face{{font-family:"{CSS_FAMILY[f]}";src:url({prefix}fonts/{f}.woff2) format("woff2");{DESCRIPTORS[f]};font-style:normal;font-display:swap}}'
        for f in uses()
    )
    tokens = ":root{" + ";".join(f"--{k}:{THEME.get(k, '')}" for k in THEME_KEYS) + "}"
    return f"{faces}\n{tokens}"


def check_styles(page: Page, where: str, prefix: str) -> str:
    """Two style blocks: the font faces and the house colours, then the one system stylesheet, src/system.css.
    Returns the system block, which check_css reads."""
    if len(page.styles) != 2:
        fail("css", f"{where}: the page needs exactly two style blocks, the faces and colours, then src/system.css")
        return page.styles[-1] if page.styles else ""
    first, system = page.styles
    if first != faces_css(prefix):
        fail("fonts", f"{where}: the first style block must be the @font-face rules of {', '.join(CSS_FAMILY[f] for f in uses())} and the colours of allow.json")
    if system != system_css():
        fail("css", f"{where}: the second style block must be src/system.css without its comments")
    check_refs(first, where, "css", rooted=prefix == "/")
    check_colour_names(first, where)
    colours_of(first, where)
    return system


def check_font_faces(css: str, where: str, prefix: str) -> None:
    """Every @font-face: a machine-made family of the house, its own subset file, swap, its weight range."""
    faces = re.findall(r"@font-face\s*\{([^}]*)\}", css, re.I)
    seen: set[str] = set()
    by_family = {CSS_FAMILY[f]: f for f in uses()}
    for face in faces:
        family = re.search(r"font-family\s*:\s*(['\"])(.*?)\1", face)
        name = family.group(2) if family else "?"
        if name not in by_family:
            fail("fonts", f"{where} declares the font family {name!r}; this house uses only {', '.join(by_family)}")
            continue
        f = by_family[name]
        seen.add(f)
        if f"src:url({prefix}fonts/{f}.woff2) format(\"woff2\")" not in face:
            fail("fonts", f"{where}: the @font-face of {name} must load only fonts/{f}.woff2")
        if not re.search(r"font-display\s*:\s*swap\b", face):
            fail("fonts", f"{where}: the @font-face of {name} needs font-display: swap")
        if DESCRIPTORS[f] not in face:
            fail("fonts", f"{where}: the @font-face of {name} must have {DESCRIPTORS[f]}")
        if not re.search(r"font-style\s*:\s*normal\s*(;|$)", face):
            fail("fonts", f"{where}: the @font-face of {name} must have font-style normal")
    for f in uses():
        if f not in seen:
            fail("fonts", f"{where} has no @font-face for {CSS_FAMILY[f]}")


def check_preloads(html_text: str, where: str, prefix: str, banner: bool) -> None:
    """One font preload, the house face (the house line is the largest text above the fold); on the home page one
    image preload too, the banner, fetched first."""
    face = THEME.get("face", "weft")
    fonts = re.findall(r'<link\b[^>]*\bas="font"[^>]*>', html_text)
    if fonts != [f'<link rel="preload" href="{prefix}fonts/{face}.woff2" as="font" type="font/woff2" crossorigin>']:
        fail("fonts", f"{where} must preload exactly the house face, {prefix}fonts/{face}.woff2, as a font with crossorigin")
    images = re.findall(r'<link\b[^>]*\bas="image"[^>]*>', html_text)
    name = house_key(SELF)
    want = (
        [f'<link rel="preload" as="image" type="image/avif" fetchpriority="high" imagesizes="{BANNER_SIZES}" '
         f'imagesrcset="img/banner-{name}-704.avif 704w, img/banner-{name}-1408.avif 1408w">'] if banner else []
    )
    if images != want:
        fail("fonts" if not banner else "images", f"{where} must preload {'the banner and no other image' if banner else 'no image'}")
    if html_text.count('rel="preload"') != len(fonts) + len(images):
        fail("fonts", f"{where} has a preload that is not the house face or the banner")


def declarations(body: str) -> dict[str, str]:
    found: dict[str, str] = {}
    for declaration in body.split(";"):
        prop, colon, value = declaration.partition(":")
        if colon:
            found[prop.strip().lower()] = re.sub(r"\s*!important\s*$", "", value.strip(), flags=re.I)
    return found


Rule = tuple[tuple[str, ...], str, dict[str, str]]


def css_rules(css: str, conditions: tuple[str, ...] = ()) -> Iterator[Rule]:
    """(media conditions, selector or at-rule, declarations) of every rule block in css, nested @media included.

    A media condition is lower case with its spaces removed."""
    css = re.sub(r"/\*.*?\*/", " ", css, flags=re.S)
    i = 0
    while True:
        start = css.find("{", i)
        if start < 0:
            return
        prelude = css[i:start].strip()
        depth, k = 1, start + 1
        while k < len(css) and depth:
            depth += (css[k] == "{") - (css[k] == "}")
            k += 1
        body = css[start + 1 : k - 1]
        if prelude.lower().startswith(("@media", "@supports")):
            yield from css_rules(body, (*conditions, re.sub(r"\s+", "", prelude.lower())))
        elif not prelude.lower().startswith("@keyframes"):
            yield conditions, re.sub(r"\s+", " ", prelude), declarations(body)
        i = k


MOTION = re.compile(r"^(transition|animation|transform|scroll-behavior|will-change)")


def check_behaviour(css: str) -> None:
    """Hover effects only on hover-capable pointers; motion only when the reader has not asked for less."""
    for conditions, selector, decls in css_rules(css):
        if ":hover" in selector and not any("(hover:hover)" in c for c in conditions):
            fail("hover", f"{selector[:40]} is a hover rule outside @media (hover: hover)")
        for prop in decls:
            if MOTION.match(prop) and not any("(prefers-reduced-motion:no-preference)" in c for c in conditions):
                fail("motion", f"{selector[:40]} sets {prop} outside @media (prefers-reduced-motion: no-preference)")
        if selector.startswith("@font-face") or ":root" in selector:
            continue
        if "outline" in decls and "none" in decls["outline"] and ":focus-visible" not in selector:
            fail("focus", f"{selector[:40]} removes an outline")
    clipped = {s for _, s, d in css_rules(css) if d.get("overflow") == "hidden"}
    for _, selector, decls in css_rules(css):
        if "scale" in decls.get("transform", ""):
            for part in selector.split(","):
                wrapper = part.strip().split(":hover")[0]
                if wrapper not in clipped:
                    fail("hover", f"{wrapper} scales an image on hover but is not clipped (overflow: hidden)")
    focus = [d for c, s, d in css_rules(css) if s == ":focus-visible" and not c]
    if not focus or "var(--accent)" not in focus[0].get("outline", ""):
        fail("focus", ":focus-visible must draw an outline in the accent colour on every element")


def text_colour(value: str, prop: str, tokens: dict[str, str]) -> str | None:
    """The hex that a color or background value gives. None when it takes what is there.

    Only a palette token, black, white or transparent sets a colour. Anything else fails."""
    v = value.lower()
    token = re.fullmatch(r"var\(\s*--([a-z-]+)\s*\)", v)
    if token and token.group(1) in tokens:
        return tokens[token.group(1)]
    if v in GREY_NAMES:
        return GREY_NAMES[v]
    if v == "transparent":
        return tokens["ground"]
    if v in ("inherit", "currentcolor"):
        return None
    fail("contrast", f"the style sets {prop}: {value[:30]!r}; use a palette token (var(--name)), black, white or transparent")
    return None


def check_text_colours(css: str, tokens: dict[str, str]) -> None:
    """Measure the colours that text uses: each color and background in the style, against its partner.

    A rule with only color is measured on the ground. A rule with only a background is measured with the text
    colour. A rule that draws an empty box (content: "") sets no text and is not measured."""
    for _, _, decls in css_rules(css):
        if decls.get("content") in ('""', "''"):
            continue
        fg = decls.get("color")
        bgs: list[str | None] = [decls[k] for k in ("background-color", "background") if k in decls]
        if fg is None and not bgs:
            continue
        fg_hex = text_colour(fg, "color", tokens) if fg is not None else None
        for bg in bgs or [None]:
            bg_hex = text_colour(bg, "background", tokens) if bg is not None else None
            top, ground = fg_hex or tokens["text"], bg_hex or tokens["ground"]
            need = 3.0 if top == tokens["accent"] else 4.5
            ratio = contrast(top, ground)
            if ratio < need:
                fail("contrast", f"the style has text {top} on {ground} at {ratio:.2f}, below {need}")


def family_of(value: str) -> str | None:
    """The machine-made font a font or font-family value selects through var(--f-x), or None."""
    hit = re.search(r"var\(\s*--f-(weft|sans|heddle|warp)\s*\)", value)
    return hit.group(1) if hit else None


def family_names(stack: str) -> list[str]:
    return [part.strip().strip("'\"") for part in stack.split(",") if part.strip()]


def check_font_use(css: str, root: dict[str, str]) -> None:
    """Every font stack starts with its machine-made family and falls back only to machine-made or generic
    families. Every rule selects its font through a stack token. No rule sets a weight outside the range of the font
    it uses, so no weight is faked, and no rule sets italic: no italic face is loaded."""
    mm = set(CSS_FAMILY.values())
    for f, fam in CSS_FAMILY.items():
        names = family_names(root.get(f"f-{f}", ""))
        if not names or names[0] != fam:
            fail("fonts", f"--f-{f} must start with {fam!r}")
        for name in names[1:]:
            if name not in mm and name not in GENERIC_FAMILIES:
                fail("fonts", f"--f-{f} names the font family {name!r}; only machine-made fonts and generic families are allowed")
    for _, selector, decls in css_rules(css):
        if selector.startswith("@font-face") or ":root" in selector:
            continue
        for prop in ("font-family", "font"):
            if prop in decls and not family_of(decls[prop]) and not re.search(r'"mm (Weft|Sans|Heddle|Warp) Full"', decls[prop]):
                fail("fonts", f"{selector[:40]} sets {prop}: {decls[prop][:30]!r}; use var(--f-weft), var(--f-sans), var(--f-heddle) or var(--f-warp)")
        fam = family_of(decls.get("font", "") + decls.get("font-family", "")) or "sans"
        tokens = decls.get("font", "").split()
        weight = decls.get("font-weight") or next((t for t in tokens if re.fullmatch(r"\d{3}|bold|bolder|lighter", t)), "400")
        if weight == "normal":
            weight = "400"
        if not weight.isdigit() or not WEIGHTS[fam][0] <= int(weight) <= WEIGHTS[fam][1]:
            fail("fonts", f"{selector[:40]} sets font-weight {weight}, outside the {CSS_FAMILY[fam]} range: the browser would fake it")
        style = decls.get("font-style") or next((t for t in tokens if t in ("italic", "oblique")), "normal")
        if style not in ("normal", "inherit"):
            fail("fonts", f"{selector[:40]} sets font-style {style}; no italic face is loaded")
    labels = [d for c, s, d in css_rules(css) if s == ".lbl" and not c]
    if not labels or not re.search(r"(?<![\w.-])400(?![\w.-])", labels[0].get("font", "")):
        fail("fonts", "the group label (h2) must set font-weight 400, or the browser draws it bold")


def check_scale(css: str, root: dict[str, str]) -> None:
    """One type scale (ratio 1.25 on 16 px) and one spacing scale on the four sites."""
    for n in STEPS:
        want = 1.25**n
        got = root.get(f"step-{n}", "")
        value = re.fullmatch(r"([\d.]+)rem", got)
        if not value or abs(float(value.group(1)) - want) > 0.001:
            fail("scale", f"--step-{n} is {got or 'missing'}; the scale is 1.25 ** {n} = {want:.4f}rem")
    for _, selector, decls in css_rules(css):
        if ":root" in selector or selector.startswith("@font-face"):
            continue
        sizes = [decls["font-size"]] if "font-size" in decls else []
        if "font" in decls:
            sizes += re.findall(r"(\S+)\s*/", decls["font"]) or [decls["font"].split()[1] if len(decls["font"].split()) > 1 else ""]
        for size in sizes:
            if not re.fullmatch(r"var\(--(step-?-?\d|t-line|t-display)\)", size):
                fail("scale", f"{selector[:40]} sets the size {size!r}; use a step of the type scale")
    body = [d for c, s, d in css_rules(css) if s == "body" and not c]
    if not body or f"/{LEADING} " not in body[0].get("font", ""):
        fail("scale", f"body must set the line height {LEADING}, the same on the four sites")
    for n, px in enumerate(SPACING, start=1):
        if root.get(f"sp-{n}") != f"{px}px":
            fail("spacing", f"--sp-{n} must be {px}px: the spacing scale is {', '.join(map(str, SPACING))} px")
    if re.search(r"--sp-(?:[1-9]\d|0)\b", css):
        fail("spacing", "the spacing scale has a token outside --sp-1 to --sp-9")
    for _, selector, decls in css_rules(css):
        for prop, value in decls.items():
            if re.fullmatch(r"(margin|padding|gap|row-gap|column-gap|inset|top|bottom|left|right)(-[a-z-]+)?", prop):
                raw = re.findall(r"(?<![\w-])-?\d+(?:\.\d+)?(?:px|rem|em)\b", value)
                if raw:
                    fail("spacing", f"{selector[:40]} sets {prop}: {value[:40]}; use the --sp-* tokens, not {raw[0]}")


def rule(css: str, selector: str, condition: str = "") -> dict[str, str]:
    """The declarations of the first rule with exactly this selector, under media conditions that contain condition
    (no condition: a rule outside any media query)."""
    for c, s, d in css_rules(css):
        if s == selector and ((condition and any(condition in x for x in c)) or (not condition and not c)):
            return d
    return {}


def check_touch(css: str) -> None:
    """The links a finger needs: 44 px high where they are small on a phone, the description links underlined."""
    if "underline" not in rule(css, "a.u, .ds a").get("text-decoration", ""):
        fail("touch", "the link after a description must be underlined always, not only on hover")
    if rule(css, ".ds a").get("padding-block") != "var(--sp-3)" or rule(css, ".ds a").get("margin-block") != "calc(-1 * var(--sp-3))":
        fail("touch", ".ds a must add 12 px above and below its text without moving the line: 44 px to tap")
    if rule(css, ".secs a").get("height") != "44px":
        fail("touch", "a bar-2 section link must be 44 px high")
    if rule(css, "footer a").get("min-height") != "44px":
        fail("touch", "a footer link must be at least 44 px high")
    for c, s, d in css_rules(css):
        if s in ("footer a", ".b1 li", ".b1 a, .b1 span", ".logo", ".latest a") and any("max-width" in x for x in c):
            for prop in ("height", "min-height"):
                if prop in d and d[prop] not in ("44px", "100%"):
                    fail("touch", f"{s} is {d[prop]} high on a narrow screen; a tap needs 44 px")
    dots = rule(css, "footer li::before")
    if dots.get("content") != '"\\00b7"':
        fail("touch", "the footer draws the dot before each name in the style, so a dot never wraps alone")
    hover = rule(css, ".plate:hover .pic img, .plate:hover .tile", "(hover:hover)")
    if "filter" not in hover:
        fail("hover", "a plate image must show its hover state without motion: .plate:hover .pic img sets a filter")


def check_responsive(css: str, flat: str) -> None:
    if ".row { display: grid; grid-template-columns: repeat(12, minmax(0, 1fr));" not in flat:
        fail("responsive", "the page grid is 12 columns: .row sets grid-template-columns: repeat(12, minmax(0, 1fr))")
    if rule(css, ".grid").get("grid-template-columns") != "repeat(3, minmax(0, 1fr))":
        fail("responsive", "the plate grid is 3 columns on a wide screen")
    if rule(css, ".grid, .grid.g2", "(max-width:519px)").get("grid-template-columns") != "minmax(0, 1fr)":
        fail("responsive", "the plate grid is one column below 520 px")
    if not re.search(r"--max:\s*1200px", css):
        fail("responsive", "the content width must be --max: 1200px")
    if re.search(r"(?<![-\w])width:\s*\d{3,}px", css):
        fail("responsive", "the style forces a width that can scroll")


def check_css(system: str, first: str) -> None:
    """The style of the page: the house colours and the system stylesheet."""
    css = system
    root = {k[2:]: v for k, v in rule(css, ":root").items() if k.startswith("--")}
    found = re.search(r":root\{([^}]*)\}", first)
    if not found:
        fail("palette", "the page needs the :root block of the house colours")
        return
    tokens = {k: v.lower() for k, v in re.findall(r"--([a-z]+):(#[0-9a-fA-F]{6})", found.group(1))}
    for key in THEME_KEYS:
        if tokens.get(key) != THEME.get(key):
            fail("palette", f"--{key} is {tokens.get(key) or 'missing'}; allow.json gives {THEME.get(key)}")
    if set(tokens) != set(THEME_KEYS):
        return
    for fg, bg, floor in PAIRS:
        ratio = contrast(tokens[fg], tokens[bg])
        if ratio < floor:
            fail("contrast", f"--{fg} on --{bg} is {ratio:.2f}, below {floor}")
    check_font_use(css, root)
    check_scale(css, root)
    check_touch(css)
    check_refs(css, "the style", "css")
    check_colour_names(css, "the style")
    if "prefers-color-scheme" in css or not re.search(r"color-scheme:\s*dark\b", css):
        fail("dark", "the page is dark only: the style sets color-scheme: dark and has no light scheme")
    # The masks are the only gradients. They are cut out before the colour check, which refuses any other.
    flat = re.sub(r"\s+", " ", css)
    rest = flat
    for mask in MASKS:
        if flat.count(f"-webkit-{mask}") != 1 or flat.count(mask) != 2:
            fail("colour", f"the style must hold this mask once, with and without -webkit-: {mask}")
        rest = rest.replace(mask, "")
    colours = colours_of(rest, "the style")
    if colours - set(tokens.values()) - {"#000000"}:
        fail("accent", f"the style has colours outside the palette: {sorted(colours - set(tokens.values()) - {'#000000'})}")
    if "var(--accent)" not in css:
        fail("accent", "the style never uses the accent colour")
    check_text_colours(css, tokens)
    check_behaviour(css)
    check_responsive(css, flat)


def refuse_name(name: str, where: str) -> None:
    fail(
        "accent",
        f"{where} uses the colour name {name}; only black, white, transparent, currentColor"
        " and the palette tokens are allowed",
    )


def declaration_values(css: str) -> Iterator[str]:
    """The value of every declaration in css. css is a stylesheet or the text of a style attribute.

    Comments, strings and url() are cut out first. Selectors and at-rule preludes are not values."""
    css = re.sub(r"/\*.*?\*/", " ", css, flags=re.S)
    css = re.sub(r"(['\"]).*?\1", " ", css, flags=re.S)
    css = re.sub(r"url\([^)]*\)", " ", css, flags=re.I)
    for match in re.finditer(r"([^{};]*)([{};]|$)", css):
        head, end = match.groups()
        _, colon, value = head.partition(":")
        if end != "{" and colon:
            yield value


def check_colour_names(css: str, where: str) -> None:
    """Refuse every CSS colour name except black and white. A name is a colour, so it is an accent."""
    for value in declaration_values(css):
        for word in WORD.findall(value):
            name = word.lower()
            if (name in NAMED_COLOURS and name not in GREY_NAMES) or name in SYSTEM_COLOURS:
                refuse_name(name, where)


def paint_colours(value: str, where: str) -> set[str]:
    """The colours one paint value sets. A fallback after url(#id) is a paint too."""
    v = value.strip()
    fragment = FRAGMENT_URL.fullmatch(v)
    if fragment:
        v = fragment.group(1).strip()
        if not v:
            return set()
    name = v.lower()
    if name in PAINT_KEYWORDS:
        return set()
    if re.fullmatch(r"#[0-9a-fA-F]+", v):
        return colours_of(v, where)
    if name in GREY_NAMES:
        return {GREY_NAMES[name]}
    if name in NAMED_COLOURS or name in SYSTEM_COLOURS:
        refuse_name(name, where)
        return set()
    fail("colour", f"{where} paints with {v[:30]!r}; write the colour as hex")
    return set()


def svg_colours(tree: ET.Element, where: str) -> set[str]:
    """Every colour an svg sets: style rules, style attributes and paint attributes."""
    found: set[str] = set()
    for el in tree.iter():
        local = el.tag.rsplit("}", 1)[-1]
        texts = [el.text or ""] if local == "style" else []
        for key, value in el.attrib.items():
            name = key.rsplit("}", 1)[-1]
            if name in PAINT_PROPS:
                found |= paint_colours(value, where)
            elif name == "style":
                texts.append(value)
        for text in texts:
            for _, value in PAINT_DECL.findall(text):
                found |= paint_colours(value, where)
            found |= colours_of(text, where)
            check_colour_names(text, where)
            check_refs(text, where, "svg")
    return found


def check_svg_safety(tree: ET.Element, where: str) -> None:
    for el in tree.iter():
        local = el.tag.rsplit("}", 1)[-1]
        if local in SVG_FORBIDDEN:
            rule_name = "colour" if local in ("linearGradient", "radialGradient", "stop") else "no-js"
            fail(rule_name, f"{where} has <{local}>, which this site does not use")
        for key, value in el.attrib.items():
            name = key.rsplit("}", 1)[-1]
            if re.fullmatch(r"on[a-z]+", name.lower()):
                fail("no-js", f"{where} has an event handler ({name})")
            if name == "href" and not value.startswith("#"):
                fail("links", f"{where} has an href that is not an id of its own")
            check_refs(value, where, "svg")


def check_mark() -> None:
    """The favicon of machine-made, mark.svg: a valid, script-free svg whose only accent is the red of the mark."""
    if SELF != "machine-made":
        return
    text = read("mark.svg")
    if not text:
        return
    try:
        tree = ET.fromstring(text)  # noqa: S314 -- mark.svg is written by this repository's own generator
    except ET.ParseError as exc:
        fail("parse", f"mark.svg is not valid XML: {exc}")
        return
    check_svg_safety(tree, "mark.svg")
    if split_accent(svg_colours(tree, "mark.svg")) != {RED}:
        fail("accent", "mark.svg needs exactly one accent colour, the red of the mark")


# ------------------------------------------------------------------ content
def sentences_of(paragraph: str) -> list[str]:
    return re.split(r"(?<=[.!?])\s+", paragraph.strip())


def check_prose(paragraphs: list[str], where: str) -> None:
    for paragraph in paragraphs:
        for sentence in sentences_of(paragraph):
            if len(sentence.split()) > MAX_WORDS:
                fail("voice", f"{where}: a sentence has more than {MAX_WORDS} words: {sentence[:40]}")


def line_html(face: str) -> str:
    """The house line: a hyphenated word never breaks; in Warp, a word in capitals is set in small capitals."""
    t = re.sub(r"\b\w+(?:-\w+)+\b", lambda w: '<span class="nb">' + w.group(0) + "</span>", esc(LINE))
    if face == "warp":
        t = re.sub(r"\b[A-Z]{2,}\b", lambda w: '<span class="sc">' + w.group(0) + "</span>", t)
    return f'<p class="line {face}">{t}</p>'


def bar2_html(root: str) -> str:
    """The house logo, linked home, then one link per group and GitHub. The labels come from site.json, the targets
    from allow.json."""
    labels = [g.get("nav", "") for g in site_json().get("groups", []) if isinstance(g, dict)]
    if len(labels) != len(GROUPS):
        return "<missing labels>"
    secs = "".join(f'<a href="{root}#g-{slug(t)}">{esc(str(n))}</a>' for (t, _), n in zip(GROUPS, labels, strict=True))
    secs += f'<a href="https://github.com/{esc(OWNER)}">GitHub</a>'
    shown = site_title(site_name()) or SELF
    if SELF == "machine-made":
        logo = (
            '<svg viewBox="0 0 30 30" aria-hidden="true" focusable="false">'
            + "".join(f'<rect{RED_CELL if (x, y) == (11, 11) else ""} x="{x}" y="{y}" width="8" height="8"/>' for y in (0, 11, 22) for x in (0, 11, 22))
            + "</svg>"
        )
    else:
        logo = f'<img src="{root}img/avatar.png" width="28" height="28" alt="">'
    return (
        f'<header class="b2"><div class="wrap"><a class="logo" href="{root or "./"}" aria-label="{esc(shown)} home">{logo}</a>'
        f'<nav class="secs" aria-label="Sections">{secs}</nav></div></header>'
    )


RED_CELL = ' class="r"'


def check_content(page: Page, html_text: str, shown: str | None) -> str:
    """The home page, part by part, in order: bar 1, bar 2, the banner, the house line, Latest, the groups of
    plates, the houses row, the footer."""
    text = " ".join(" ".join(page.text).split())
    visible = " ".join([text, *page.values, *page.hidden, *page.tags])
    face = THEME.get("face", "weft")
    if shown and ("h1", shown) not in page.headings:
        fail("content", f"the h1 must be the banner with the site name, {shown}, as its alt text")
    title = re.search(r"<title>([^<]+)</title>", html_text)
    if shown and (not title or html.unescape(title.group(1)) != shown):
        fail("head", f"the title must be the site name, {shown}")
    if bar1_html() not in html_text:
        fail("content", f"bar 1 must read {' · '.join(n for n, _ in SITES)}: {SELF} marked with aria-current and not linked, type last")
    if footer_html() not in html_text:
        fail("content", f"the footer must link {' · '.join(n for n, _ in SITES)}, in that order, and nothing else")
    if bar2_html("") not in html_text:
        fail("content", "bar 2 must hold the logo (the mark, or the avatar at 28 px), linked home and named '<house> home', then one link per group in order and GitHub last")
    banner = f'<h1 class="banner">{picture("", "banner-" + house_key(SELF), BANNER_WIDTHS, BANNER_SIZE, shown or "", BANNER_SIZES, lazy=False)}</h1>'
    if banner not in html_text:
        fail("content", "the h1 must hold the house banner, AVIF and JPEG at 704 and 1408 px, loaded first, with the name as alt text")
    if line_html(face) not in html_text:
        fail("content", f"the house line must follow the banner, in the house face ({face}), word for word as allow.json has it, each hyphenated word kept on one line")
    if latest_html() not in html_text:
        fail("latest", "Latest must list the newest release of each repository, distinct repositories, newest first, at most three, as the facts give them")
    names = re.findall(r'<ol class="latest n\d">(.*?)</ol>', html_text)
    shown_repos = re.findall(r'<li><a href="[^"]*">([^<]*)</a>', names[0]) if names else []
    if len(set(shown_repos)) != len(shown_repos) or len(shown_repos) > 3:
        fail("latest", "Latest repeats a repository or has more than three entries")
    if houses_html() not in html_text:
        fail("houses", "the houses row must show the other two houses and the type site: banner, line and newest release")
    marks = ['class="b1"', 'class="b2"', 'class="banner"', f'class="line {face}"', 'aria-labelledby="g-latest"',
             *(f'aria-labelledby="g-{slug(t)}"' for t, _ in GROUPS), 'aria-labelledby="g-houses"', "<footer"]
    order = [html_text.find(m) for m in marks if m != 'aria-labelledby="g-latest"' or latest_html()]
    if -1 in order or order != sorted(order):
        fail("content", "the page order is: bar 1, bar 2, banner, house line, Latest, the groups, the houses, footer")
    hrefs = [link.get("href") or "" for link in page.links if link.get("tag") != "link"]
    repo_links = [h for h in hrefs if h.startswith("https://github.com/") and "/releases/tag/" not in h and h != f"https://github.com/{OWNER}"]
    plain_repos = [f"https://github.com/{full}" for full in repos_of()]
    if sorted(repo_links) != sorted(plain_repos):
        fail("projects", "the project links are not exactly the public repositories")
    for full in repos_of():
        if full.split("/")[1] in NEVER:
            fail("projects", f"{full} is never listed")
    # Another house is linked in bar 1, in the houses row and in the footer; this house once, in the footer. A
    # project site is linked once more, after the description of its plate.
    others = Counter(u for n, u in SITES if n != SELF)
    want = others + others + Counter(u for _, u in SITES) + Counter(SITE_LINKS.values())
    for url in {u for _, u in SITES} | set(SITE_LINKS.values()):
        if hrefs.count(url) != want[url]:
            fail("links", f"{url} must be linked {want[url]} time(s): in bar 1 and the houses row when it is another site, once in the footer, after the description of its plate when it is a project site")
    heads = [h for kind, h in page.headings if kind == "h2"]
    if heads != (["Latest"] if latest_html() else []) + [t for t, _ in GROUPS] + ["The houses"]:
        fail("projects", "the h2 headings must be Latest, the group titles in order, then The houses")
    sections = re.findall(
        r'<section class="row" aria-labelledby="(g-[\w-]+)"><h2 class="lbl" id="(g-[\w-]+)">' + re.escape(MK) + r'<span>([^<]*)</span></h2><ul class="grid">(.*?)</ul></section>',
        html_text,
    )
    if len(sections) != len(GROUPS) or html_text.count("<section") != len(GROUPS) + 1 + (1 if latest_html() else 0):
        fail("projects", "the projects are not in the groups of the public list")
        return visible
    lines: list[str] = []
    for (lab, ident, title, body), (want_title, fulls) in zip(sections, GROUPS, strict=True):
        if html.unescape(title) != want_title or lab != ident or ident != f"g-{slug(want_title)}":
            fail("projects", f"the group {want_title} must carry its title and its id g-{slug(want_title)}")
        plates = re.findall(r'<li class="plate">.*?</li>', body)
        if len(plates) != len(fulls) or "".join(plates) != body:
            fail("projects", f"the group {want_title} must hold exactly its projects, in order")
            continue
        for full, plate in zip(fulls, plates, strict=True):
            hit = plate_html(full).fullmatch(plate)
            if not hit:
                fail("projects", f"the plate of {full} is not the banner link (named by aria-label, empty alt text), one line, and its facts")
            else:
                lines.append(html.unescape(hit.group("line")))
                if re.match(rf"{re.escape(full.split('/')[1])}(?![\w-])", lines[-1], re.I):
                    fail("projects", f"the line of {full} starts with the repository name, which the banner already shows")
    site_links = len(re.findall(r'<p class="ds">[^<]*<a ', html_text))
    if site_links != len(SITE_LINKS):
        fail("projects", "the page has a site link that the allowed list does not name")
    check_prose(page.paragraphs + lines, "index.html")
    return visible


def check_not_found(page: Page, html_text: str, shown: str | None) -> None:
    """The 404 page: the same bars and footer, one line and a way home. GitHub Pages serves it at any depth, so
    every local address starts at the site root."""
    face = THEME.get("face", "weft")
    if f"<title>Not found &ndash; {shown}</title>" not in html_text:
        fail("404", f"the title of the 404 page must be 'Not found – {shown}'")
    if ("h1", "Not found") not in page.headings:
        fail("404", "the h1 of the 404 page must read Not found")
    if bar1_html() not in html_text or footer_html() not in html_text:
        fail("404", "the 404 page has the same bar 1 and footer as the home page")
    body = (
        f'<main id="main" class="wrap nf"><h1 class="line {face}">Not found</h1><p class="ds">This page does not exist.</p>'
        f'<p class="more"><a class="u" href="/">Back to {esc(shown or "")}</a></p></main>'
    )
    if body not in html_text:
        fail("404", "the 404 page says Not found in the house face, one line, and links back to the home page")
    if bar2_html("/") not in html_text:
        fail("404", "bar 2 of the 404 page links home and to each group from the site root")
    for href in re.findall(r'(?:href|src)="([^"#][^"]*)"', html_text):
        if "://" not in href and not href.startswith("/"):
            fail("404", f"the 404 page names {href} relative to itself; it is served at any depth, so start at the root")
    for target in re.findall(r"url\(([^)]*)\)", page.styles[0] if page.styles else ""):
        if not target.startswith("/"):
            fail("404", f"the 404 page loads {target} relative to itself; start at the root")


def emitted(visible: str) -> Iterator[tuple[str, str]]:
    """Every emitted text file as (name, text). The home page counts as what a reader or a crawler gets."""
    yield "index.html", visible
    for path in sorted(DOCS.rglob("*")):
        name = path.relative_to(DOCS).as_posix()
        if path.is_file() and name != "index.html" and path.suffix in (".html", ".txt", ".svg"):
            yield name, path.read_text(encoding="utf-8", errors="replace")


def decoded(source: str) -> str:
    """source with every character reference decoded, however deeply it is nested."""
    while (plain := html.unescape(source)) != source:
        source = plain
    return source


def check_leaks(visible: str, deny: list[str]) -> None:
    forwards = {f"{folder}/index.html": url.split("//", 1)[1] for folder, url in REDIRECTS.items()}
    public = {f"github.com/{full}" for full in repos_of()} | {f"github.com/{OWNER}"}
    public |= {u.split("//", 1)[1] for u in release_urls()}
    for name, raw in emitted(visible):
        # Files are plain ASCII.
        if not raw.isascii():
            fail("voice", f"docs/{name} has characters that are not plain ASCII")
            continue
        source = raw + "\n" + decoded(raw)
        for match in GITHUB.findall(source):
            ok = match == forwards.get(name) or match in LICENCE_URLS.get(name, ()) or match in public
            if not ok:
                fail("private", f"{match} is not in the public list ({name})")
        for repo in RS_NAME.findall(source):
            if repo.lower() not in {full.split("/")[1].lower() for full in repos_of()}:
                fail("private", f"{repo} looks like a repository that is not in the public list ({name})")
        for word in deny:
            if re.search(rf"(?<![\w]){re.escape(word)}(?![\w])", source, re.I):
                fail("private", f"a private name appears in docs/{name} ({len(word)} letters)")
    for rel in ("index.html", "404.html"):
        raw_page = (DOCS / rel).read_text(encoding="utf-8", errors="replace") if (DOCS / rel).is_file() else ""
        if not raw_page.isascii():
            fail("voice", f"docs/{rel} has characters that are not plain ASCII")
    for path in DOCS.rglob("*"):
        for word in deny:
            if path.is_file() and re.search(re.escape(word), path.name, re.I):
                fail("private", f"a private name is part of the file name {path.name}")


def check_forbidden() -> None:
    """Money, internal words, and the words that never reach public text, in every text file."""
    for path in sorted(DOCS.rglob("*")):
        if path.is_file() and path.suffix in (".html", ".txt", ".svg"):
            text = path.read_text(encoding="utf-8", errors="replace")
            rel = path.relative_to(DOCS).as_posix()
            hit = FORBIDDEN.search(text)
            if hit:
                fail("forbidden", f"docs/{rel} contains {hit.group(0)!r}")
            # Public words: the text a reader sees and the attribute values a reader or a crawler gets.
            plain = decoded(visible_text(text) if path.suffix == ".html" else text)
            for ok in BANNED_OK:
                plain = plain.replace(ok, "")
            hit = BANNED.search(plain)
            if hit and not rel.startswith("fonts/"):
                fail("forbidden", f"docs/{rel} contains the word {hit.group(0)!r}")
            for never in NEVER:
                if never in decoded(text):
                    fail("forbidden", f"docs/{rel} names {never}, which is never listed")


# ------------------------------------------------------------------ images and fonts
def scaled(size: tuple[int, int], width: int) -> tuple[int, int]:
    return width, round(size[1] * width / size[0])


def jpeg_size(data: bytes) -> tuple[int, int] | None:
    """(width, height) of a JPEG, read from its first start-of-frame marker. None when it is not a JPEG."""
    if data[:3] != b"\xff\xd8\xff":
        return None
    i = 2
    while i + 9 < len(data):
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7 or marker == 0xFF:
            i += 1 if marker == 0xFF else 2
            continue
        length = int.from_bytes(data[i + 2 : i + 4], "big")
        if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
            return int.from_bytes(data[i + 7 : i + 9], "big"), int.from_bytes(data[i + 5 : i + 7], "big")
        i += 2 + length
    return None


def avif_size(data: bytes) -> tuple[int, int] | None:
    """(width, height) of an AVIF, from its ftyp brand and its ispe box. None when it is not an AVIF."""
    if data[4:12] != b"ftypavif":
        return None
    at = data.find(b"ispe")
    if at < 0:
        return None
    return int.from_bytes(data[at + 8 : at + 12], "big"), int.from_bytes(data[at + 12 : at + 16], "big")


def png_size(data: bytes) -> tuple[int, int] | None:
    if data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
        return None
    return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")


def expected_size(rel: str) -> tuple[int, int] | None:
    if rel == "og.jpg":
        return OG_SIZE
    if rel in PNG_SIZES:
        return PNG_SIZES[rel], PNG_SIZES[rel]
    hit = re.fullmatch(r"img/(.+)-(\d+)\.(?:avif|jpg)", rel)
    if not hit:
        return None
    full = BANNER_SIZE if hit.group(1).startswith("banner-") else PLATE_SIZE
    return scaled(full, int(hit.group(2)))


def check_images() -> None:
    """Each image is a real JPEG, AVIF or PNG of the size the page declares, complete, and no larger than it needs."""
    paths = [DOCS / "og.jpg", *sorted((DOCS / "img").glob("*"))] if (DOCS / "img").is_dir() else [DOCS / "og.jpg"]
    for path in paths:
        if not path.is_file():
            continue
        rel = path.relative_to(DOCS).as_posix()
        data = path.read_bytes()
        reader = {".jpg": jpeg_size, ".avif": avif_size, ".png": png_size}.get(path.suffix)
        size = reader(data) if reader else None
        want = expected_size(rel)
        if size is None:
            fail("images", f"docs/{rel} is not a {path.suffix[1:].upper()} image")
        elif path.suffix == ".jpg" and not data.endswith(b"\xff\xd9"):
            fail("images", f"docs/{rel} is cut short: it has no end-of-image marker")
        elif path.suffix == ".png" and not data.endswith(b"IEND\xaeB`\x82"):
            fail("images", f"docs/{rel} is cut short: it has no IEND chunk")
        elif size != want:
            fail("images", f"docs/{rel} is {size[0]} x {size[1]}; it must be {want[0] if want else '?'} x {want[1] if want else '?'}")
        if len(data) > MAX_IMAGE_BYTES:
            fail("images", f"docs/{rel} is {len(data)} bytes; the limit is {MAX_IMAGE_BYTES}")


def check_font_sources() -> None:
    """The source fonts in fonts/ are the release files that SOURCES pins, and fonts/SOURCES.json says the same."""
    try:
        listed = json.loads((FONT_DIR / "SOURCES.json").read_text(encoding="utf-8"))["fonts"]
    except (OSError, ValueError, KeyError) as exc:
        fail("fonts", f"fonts/SOURCES.json is missing or unreadable ({exc.__class__.__name__})")
        return
    if set(listed) != set(SOURCES):
        fail("fonts", f"fonts/SOURCES.json lists {sorted(listed)}; the checks pin {sorted(SOURCES)}")
    for name, (family, version, digest) in SOURCES.items():
        entry = listed.get(name, {})
        if (entry.get("family"), entry.get("version"), entry.get("sha256")) != (family, version, digest):
            fail("fonts", f"fonts/SOURCES.json disagrees with the pinned {name}: {family} {version}")
        path = FONT_DIR / name
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            fail("fonts", f"fonts/{name} is not the {family} {version} release file")


def check_subsets(pages: list[str]) -> None:
    """Each font in docs/fonts/ is a subset of its pinned source: a woff2 of the same family, every variation axis
    and every feature the style uses kept, every glyph it holds from the source, and every character the page sets
    in it present."""
    try:
        from fontTools.ttLib import TTFont
    except ImportError:
        fail("fonts", "the font checks need fontTools and brotli: run check_site.py under uv run --with fonttools --with brotli")
        return
    from io import BytesIO

    def meta(font: Any) -> tuple[list[tuple[str, float, float]], set[str], str, set[int]]:
        axes = [(a.axisTag, a.minValue, a.maxValue) for a in font["fvar"].axes] if "fvar" in font else []
        feats = {r.FeatureTag for t in ("GSUB", "GPOS") if t in font for r in font[t].table.FeatureList.FeatureRecord}
        name = font["name"].getDebugName(16) or font["name"].getDebugName(1) or ""
        return axes, feats, name, set(font.getBestCmap())

    text = "".join(visible_text(p) for p in pages)
    chars = {ord(c) for c in text + text.upper() if not c.isspace()}
    for f in uses():
        path = DOCS / "fonts" / f"{f}.woff2"
        if not path.is_file():
            continue
        data = path.read_bytes()
        if data[:4] != b"wOF2":
            fail("fonts", f"docs/fonts/{f}.woff2 is not a woff2 font")
            continue
        try:
            sub = meta(TTFont(BytesIO(data)))
            src = meta(TTFont(FONT_DIR / FONT_SOURCE[f]))
        except Exception as exc:  # noqa: BLE001 -- any parse error of the shipped file is a failure to report
            fail("fonts", f"docs/fonts/{f}.woff2 cannot be read as a font ({exc.__class__.__name__})")
            continue
        if sub[2] != src[2]:
            fail("fonts", f"docs/fonts/{f}.woff2 is {sub[2]!r}, not a subset of {src[2]!r}")
        if sub[0] != src[0]:
            fail("fonts", f"docs/fonts/{f}.woff2 lost a variation axis: {src[0]} became {sub[0]}")
        lost = (src[1] & USED_FEATURES) - sub[1]
        if lost:
            fail("fonts", f"docs/fonts/{f}.woff2 lost the features {sorted(lost)}")
        if sub[3] - src[3]:
            fail("fonts", f"docs/fonts/{f}.woff2 holds characters its source does not have")
        need = chars if f in ("weft", "sans") else {ord(c) for p in pages for c in face_text(p, f) if not c.isspace()}
        missing = sorted(chr(c) for c in need & src[3] - sub[3])
        if missing:
            fail("fonts", f"docs/fonts/{f}.woff2 lacks characters the page sets in it: {''.join(missing)[:20]!r}")


class FaceText(HTMLParser):
    """The text inside any element whose class names the face."""

    def __init__(self, face: str) -> None:
        super().__init__(convert_charrefs=True)
        self.face, self.stack, self.out = face, [], set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag not in VOID and tag != "rect":
            self.stack.append(self.face in (dict(attrs).get("class") or "").split())

    def handle_endtag(self, tag: str) -> None:
        if tag not in VOID and tag != "rect" and self.stack:
            self.stack.pop()

    def handle_data(self, data: str) -> None:
        if any(self.stack):
            self.out |= set(data)


def strip_code(page: str) -> str:
    return re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", page, flags=re.S)


def visible_text(page: str) -> str:
    page = strip_code(page)
    page = re.sub(r'(?:aria-label|alt|title|content)="([^"]*)"', lambda m: " " + m.group(1) + " ", page)
    return html.unescape(re.sub(r"<[^>]+>", " ", page))


def face_text(page: str, face: str) -> set[str]:
    parser = FaceText(face)
    parser.feed(strip_code(page))
    return parser.out


def check_llms(name: str | None) -> None:
    text = read("llms.txt")
    if not text:
        return
    links = re.findall(r"\]\((https://[^)]+)\)", text)
    expected = [f"https://github.com/{full}" for full in repos_of()] + [u for _, u in SITES] + list(SITE_LINKS.values())
    if sorted(links) != sorted(expected):
        fail("llms", "llms.txt must list exactly the public repositories, the project sites and the four sites")
    shown = site_title(name)
    if shown and not text.startswith(f"# {shown}\n\n> {LINE}\n\n## "):
        fail("llms", "llms.txt must start with the name and the line")
    sites = "".join(f"- [{n}]({u})\n" for n, u in SITES)
    if not text.endswith(f"## Sites\n\n{sites}"):
        fail("llms", "llms.txt must end with the Sites section: the four sites")
    found = [
        (title, re.findall(rf"{GITHUB_URL}/([\w.-]+/[\w.-]+)", body))
        for title, body in re.findall(r"## ([^\n]+)\n\n((?:- [^\n]*\n?)+)", text, re.S)
    ]
    if [(t, r) for t, r in found if t != "Sites"] != [(title, list(fulls)) for title, fulls in GROUPS]:
        fail("llms", "llms.txt must follow the groups of the public list, in order")
    lines = (re.sub(r"^[#>-]+\s*", "", line) for line in text.splitlines())
    check_prose([re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", line) for line in lines], "llms.txt")


class Args(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        print(f"FAIL args: {message}")
        sys.exit(2)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = Args(description="Check the built site in docs/.", allow_abbrev=False)
    parser.add_argument("--deny", metavar="FILE", help="names that must not appear in the output")
    parser.add_argument("--self-test", action="store_true", help="break a copy of docs/ and check the breaks are caught")
    parser.add_argument("--site", metavar="DIR", help="check another house: DIR holds site.json, allow.json and docs/")
    parser.add_argument("--data", metavar="FILE", help="the GitHub facts file that fetch.py wrote and build.py read")
    return parser.parse_args(argv)


def load_deny(path: str | None) -> list[str]:
    """One name per line. Blank lines and lines that start with # are dropped. A name may hold spaces."""
    path = path or os.environ.get("MM_DENY_FILE")
    if not path:
        return []
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        print(f"FAIL deny: cannot read the deny file: {exc.strerror}")
        sys.exit(2)
    names = [line.strip() for line in lines]
    return [name for name in names if name and not name.startswith("#")]


def load_data(path: str | None) -> None:
    """The GitHub facts: every repository of the three houses and the type families."""
    global DATA  # noqa: PLW0603
    path = path or os.environ.get("MM_DATA")
    if not path:
        print("FAIL args: name the GitHub facts file with --data FILE (python3 fetch.py FILE writes it)")
        sys.exit(2)
    try:
        DATA = json.loads(Path(path).read_text(encoding="utf-8"))
        datetime.date.fromisoformat(DATA["fetched"])
        fulls = [*repos_of(), *(f for _, fulls in OTHERS.values() for f in fulls)]
        missing = [f for f in fulls if f not in DATA["repos"]]
        if missing or set(DATA["families"]) != {"weft", "sans", "heddle", "warp"}:
            raise KeyError(missing[0] if missing else "families")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"FAIL args: the GitHub facts file {path} is missing or incomplete ({exc.__class__.__name__}: {exc})")
        sys.exit(2)


def run_checks(deny: list[str]) -> list[str]:
    del failures[:]
    name = site_name()
    shown = site_title(name)
    check_files()
    check_redirects()
    check_font_sources()
    pages = []
    visible = ""
    for rel, rooted in (("index.html", False), ("404.html", True)):
        html_text = read(rel)
        if not html_text:
            continue
        pages.append(html_text)
        page = parse(html_text)
        prefix = "/" if rooted else ""
        check_html(page, html_text, rel, rooted)
        check_head(page, html_text, shown, rel, prefix)
        system = check_styles(page, rel, prefix)
        check_font_faces(page.styles[0] if page.styles else "", rel, prefix)
        check_preloads(html_text, rel, prefix, banner=not rooted)
        if rooted:
            check_not_found(page, html_text, shown)
        else:
            visible = check_content(page, html_text, shown)
            check_css(system, page.styles[0] if page.styles else "")
    check_subsets(pages)
    check_leaks(visible, deny)
    check_forbidden()
    check_images()
    check_mark()
    check_llms(name)
    return list(failures)


# ------------------------------------------------------------------ self-test
LONG = " ".join(["word"] * 30) + "."


def edit(docs: Path, name: str, old: str, new: str) -> None:
    path = docs / name
    text = path.read_text(encoding="utf-8")
    if old not in text:
        raise AssertionError(f"self-test is stale: {old!r} is not in docs/{name}")  # noqa: TRY003
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def edit_all(docs: Path, name: str, *pairs: tuple[str, str]) -> None:
    """Apply several edits to one file, in order."""
    for old, new in pairs:
        edit(docs, name, old, new)


def edit_css(docs: Path, old: str, new: str) -> None:
    """Change the system style the way a changed src/system.css would: in the source copy and in both pages, so that
    only the rule under test can catch it."""
    global SYSTEM_SRC  # noqa: PLW0603
    copy = docs.parent / "system.css"
    if not copy.is_file():
        shutil.copy(SYSTEM_SRC, copy)
    SYSTEM_SRC = copy
    text = copy.read_text(encoding="utf-8")
    flat_old = old
    if flat_old not in text:
        raise AssertionError(f"self-test is stale: {old!r} is not in src/system.css")  # noqa: TRY003
    copy.write_text(text.replace(old, new, 1), encoding="utf-8")
    for page in ("index.html", "404.html"):
        edit(docs, page, old, new)


def site_copy(root: Path, changes: dict[str, object], data: Path) -> subprocess.CompletedProcess[bytes]:
    """Build a copy of the generator in root, with these keys of site.json changed."""
    (root / "src").mkdir(parents=True)
    for rel in ("build.py", "card.py", "fetch.py", "src/system.css", "allow.json"):
        shutil.copy(GEN / rel, root / rel)
    for folder in ("fonts", "img", "houses"):
        shutil.copytree(GEN / folder, root / folder, ignore=shutil.ignore_patterns("docs"))
    site = json.loads((GEN / "site.json").read_text(encoding="utf-8"))
    old = site["name"]
    site.update(changes)
    new = changes.get("name")
    if isinstance(new, str) and FILE_NAME.fullmatch(new) and ".." not in new:
        # A renamed site keeps the banner of the site it was copied from, under the new name.
        shutil.copy(GEN / "img" / "org" / f"{old}.jpg", root / "img" / "org" / f"{new}.jpg")
    (root / "site.json").write_text(json.dumps(site), encoding="utf-8")
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    return subprocess.run([sys.executable, str(root / "build.py"), "--data", str(data)], capture_output=True, env=env, check=False)


def build_rejects(changes: dict[str, object], data: Path) -> bool:
    """True when build.py exits 2 on a site.json with these changes and writes no page."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "site"
        done = site_copy(root, changes, data)
        written = [p.name for p in Path(tmp).rglob("*.html")]
        return done.returncode == 2 and not written


def build_needs(rel: str, data: Path) -> bool:
    """True when build.py exits 2 without this file of the generator and writes no docs/."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "site"
        site_copy(root, {}, data)
        shutil.rmtree(root / "docs")
        (root / rel).unlink()
        env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
        done = subprocess.run([sys.executable, str(root / "build.py"), "--data", str(data)], capture_output=True, env=env, check=False)
        return done.returncode == 2 and not (root / "docs").exists()


def build_fails_on_fetch() -> bool:
    """True when build.py, left to fetch for itself with gh unreachable, exits 2 and writes no docs/."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "site"
        site_copy(root, {}, Path(DATA_PATH))
        shutil.rmtree(root / "docs")
        env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PATH": str(Path(tmp) / "nobin"), "GH_TOKEN": "x"}
        done = subprocess.run([sys.executable, str(root / "build.py")], capture_output=True, env=env, check=False)
        return done.returncode == 2 and not (root / "docs").exists()


def cli_fails(args: list[str], prefix: str) -> bool:
    """True when check_site.py exits 2 with exactly one line that starts with prefix."""
    env = {k: v for k, v in os.environ.items() if k not in ("MM_DENY_FILE", "MM_DATA")}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    done = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), *args], capture_output=True, text=True, env=env, check=False
    )
    lines = done.stdout.splitlines()
    return done.returncode == 2 and len(lines) == 1 and lines[0].startswith(prefix) and not done.stderr


DATA_PATH = ""


def site_links_hold(data: Path) -> list[str]:
    """The site-link fixture for a plain address and for one with a query string, which the page writes with &amp;."""
    return [
        *site_link_fixture("https://machine-made.github.io/zz-site/", data),
        *site_link_fixture("https://example.net/docs/?a=1&b=2", data),
    ]


def site_link_fixture(url: str, data: Path) -> list[str]:
    """Build a site with one more project site link and run the checks on it: it passes, and each way of breaking the
    link fails. The checks read the link from the public list, so the list changes too."""
    global DOCS, SITE_LINKS  # noqa: PLW0603
    real_docs, real_links = DOCS, SITE_LINKS
    full = next(f for f in repos_of() if f not in real_links)
    repo, eurl = full.split("/")[1], html.escape(url)
    problems: list[str] = []
    site = json.loads((GEN / "site.json").read_text(encoding="utf-8"))
    next(p for g in site["groups"] for p in g["projects"] if p["repo"] == repo)["site"] = url
    link = f' <a href="{eurl}" aria-label="{repo} site">site</a>'
    breaks: list[tuple[str, Callable[[Path], object]]] = [
        ("site link missing", lambda d: edit(d, "index.html", link, "")),
        ("site link on another host", lambda d: edit(d, "index.html", eurl, "https://example.net/zz-site/")),
        ("site link to another path", lambda d: edit(d, "index.html", eurl, "https://machine-made.github.io/other/")),
        ("second site link", lambda d: edit(d, "index.html", "</ol>", f'</ol><p class="ds">x <a href="{eurl}">x</a></p>')),
        ("site link says docs but the list says site", lambda d: edit(d, "index.html", f'aria-label="{repo} site">site</a>', f'aria-label="{repo} docs">docs</a>')),
        ("site link without its accessible name", lambda d: edit(d, "index.html", f' aria-label="{repo} site"', "")),
        ("site link on the banner", lambda d: edit(d, "index.html", f'<a class="pic" href="https://github.com/{full}" aria-label=', f'<a class="pic" href="{eurl}" aria-label=')),
        ("linked banner without an accessible name", lambda d: edit(d, "index.html", f'class="pic" href="https://github.com/{full}" aria-label="{repo}"', f'class="pic" href="https://github.com/{full}"')),
    ]
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "site"
        if site_copy(root, {"groups": site["groups"]}, data).returncode != 0:
            return ["the site-link fixture does not build"]
        SITE_LINKS = {**real_links, full: url}
        try:
            for title, mutate in [("clean fixture", lambda d: None), *breaks]:
                DOCS = Path(tmp) / "case" / "docs"
                shutil.rmtree(DOCS.parent, ignore_errors=True)
                shutil.copytree(root / "docs", DOCS)
                mutate(DOCS)
                found = run_checks([])
                caught = not found if title == "clean fixture" else any(line.startswith(("FAIL links:", "FAIL projects:")) for line in found)
                if not caught:
                    problems.append(f"site-link fixture {url}, {title}: got {found[:2]}")
        finally:
            DOCS, SITE_LINKS = real_docs, real_links
    return problems


Case = tuple[str, str | None, list[str], Callable[[Path], object]]


def self_test() -> None:
    global DOCS, SYSTEM_SRC, FONT_DIR  # noqa: PLW0603
    real, real_src = DOCS, SYSTEM_SRC
    data = Path(DATA_PATH)
    name = site_name()
    if not name:
        print("\n".join(failures))
        sys.exit(1)
    # Plates without a site link of their own: the cases below break their markup.
    plain = [f.split("/")[1] for f in repos_of() if f not in SITE_LINKS]
    first = plain[0]
    second = plain[1] if len(plain) > 1 else first
    first_full = next(f for f in repos_of() if f.endswith(f"/{first}"))
    nav_other = next(u for n, u in SITES if n != SELF)
    other_name = next(n for n, _ in SITES if n != SELF)
    self_url = dict(SITES)[SELF]
    face = THEME["face"]
    tokens_first = f":root{{--ground:{THEME['ground']};"
    first_img = f'<img src="img/{first}-704.jpg" srcset="img/{first}-352.jpg 352w, img/{first}-704.jpg 704w" sizes="{PLATE_SIZES}" width="704" height="235" alt="" loading="lazy" decoding="async">'

    def plate_edit(repo: str, change: Callable[[str], str]) -> Callable[[Path], object]:
        """Change the markup of one plate: change() takes the <li> of the repository and returns the new one."""
        def run(d: Path) -> None:
            text = read_index(d)
            li = next(m for m in re.findall(r'<li class="plate">.*?</li>', text) if f'aria-label="{repo}"' in m)
            edit(d, "index.html", li, change(li))

        return run

    cases: list[Case] = [
        ("private name in the style", "private", ["zzprivate"], lambda d: edit(d, "index.html", "<style>", "<style>/* zzprivate */")),
        ("private name in the mark svg", "private", ["zzprivate"], lambda d: edit(d, "mark.svg", "<title>", "<title>zzprivate ") if SELF == "machine-made" else edit(d, "404.html", "<body>", "<body><!-- zzprivate -->")),
        ("private name in an html comment", "private", ["zzprivate"], lambda d: edit(d, "index.html", "<body>", "<body><!-- zzprivate -->")),
        ("private link", "links", [], lambda d: edit(d, "index.html", f"/{first}\"", "/zzprivate\"")),
        ("private rs name in llms.txt", "private", [], lambda d: edit(d, "llms.txt", "## Sites", "zz-rs\n\n## Sites")),
        ("long project line", "voice", [], lambda d: edit(d, "index.html", '<p class="ds">', f'<p class="ds">{LONG} ')),
        ("long house line", "voice", [], lambda d: edit(d, "llms.txt", f"> {LINE}", f"> {LONG} {LINE}")),
        ("long line in llms.txt", "voice", [], lambda d: edit(d, "llms.txt", "## Sites", f"{LONG}\n\n## Sites")),
        ("alpha hex in a variable", "colour", [], lambda d: edit_all(d, "index.html", (f"--muted:{THEME['muted']}", f"--muted:{THEME['muted']}80"))),
        ("short alpha hex in a rule", "colour", [], lambda d: edit_css(d, "box-sizing: border-box;", "color:#fff8;box-sizing: border-box;")),
        ("second accent", "accent", [], lambda d: edit_css(d, "box-sizing: border-box;", "color:#0000ff;box-sizing: border-box;")),
        ("a hex grey outside the palette", "accent", [], lambda d: edit_css(d, "box-sizing: border-box;", "color:#777777;box-sizing: border-box;")),
        ("accent changed in the page", "palette", [], lambda d: edit(d, "index.html", f"--accent:{THEME['accent']}", "--accent:#123456")),
        ("ground changed in the page", "palette", [], lambda d: edit(d, "index.html", tokens_first, ":root{--ground:#222222;")),
        ("surface changed in the page", "palette", [], lambda d: edit(d, "index.html", f"--surface:{THEME['surface']}", "--surface:#333333")),
        ("light scheme comes back", "dark", [], lambda d: edit_css(d, "box-sizing: border-box; }", "box-sizing: border-box; }@media (prefers-color-scheme: light){a{margin:0}}")),
        ("color-scheme meta is light dark", "dark", [], lambda d: edit(d, "index.html", 'content="dark"', 'content="light dark"')),
        ("theme-color differs from the ground", "dark", [], lambda d: edit(d, "index.html", f'name="theme-color" content="{THEME["ground"]}"', 'name="theme-color" content="#ffffff"')),
        ("link leaves docs/", "links", [], lambda d: edit(d, "index.html", 'href="./"', 'href="../README.md"')),
        ("image leaves docs/", "links", [], lambda d: edit(d, "index.html", f'src="img/{first}-704.jpg"', 'src="../README.md"')),
        ("srcset leaves docs/", "links", [], lambda d: edit(d, "index.html", f'srcset="img/{first}-352.avif', 'srcset="../README.md')),
        ("icon leaves docs/", "links", [], lambda d: edit(d, "index.html", 'href="img/touch.png"', 'href="../README.md"')),
        ("absolute local link", "links", [], lambda d: edit(d, "index.html", 'href="./"', 'href="/etc/hostname"')),
        ("root link on the home page", "links", [], lambda d: edit(d, "index.html", 'href="./"', 'href="/"')),
        ("protocol-relative link", "links", [], lambda d: edit(d, "index.html", 'href="./"', 'href="//example.com/x.css"')),
        ("Google Fonts stylesheet", "links", [], lambda d: edit(d, "index.html", "<style>", '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Other"><style>')),
        ("font preconnect", "links", [], lambda d: edit(d, "index.html", "<style>", '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin><style>')),
        ("remote stylesheet", "links", [], lambda d: edit(d, "index.html", "<style>", '<link rel="stylesheet" href="https://example.net/style.css"><style>')),
        ("preload of a remote font", "links", [], lambda d: edit(d, "index.html", f'href="fonts/{face}.woff2"', 'href="https://fonts.gstatic.com/x.woff2"')),
        ("preload of a file that is not the house face", "fonts", [], lambda d: edit(d, "index.html", f'<link rel="preload" href="fonts/{face}.woff2"', '<link rel="preload" href="fonts/sans.woff2"')),
        ("preload without crossorigin", "fonts", [], lambda d: edit(d, "index.html", 'type="font/woff2" crossorigin>', 'type="font/woff2">')),
        ("no font preload", "fonts", [], lambda d: edit(d, "index.html", f'<link rel="preload" href="fonts/{face}.woff2" as="font" type="font/woff2" crossorigin>', "")),
        ("a second font preload", "fonts", [], lambda d: edit(d, "index.html", "<style>", '<link rel="preload" href="fonts/weft.woff2" as="font" type="font/woff2" crossorigin><style>')),
        ("no banner preload", "images", [], lambda d: edit(d, "index.html", '<link rel="preload" as="image"', '<link rel="prefetch" as="image"')),
        ("the banner preload without high priority", "images", [], lambda d: edit(d, "index.html", 'type="image/avif" fetchpriority="high" imagesizes', 'type="image/avif" imagesizes')),
        ("css font face from a font host", "links", [], lambda d: edit(d, "index.html", "url(fonts/weft.woff2)", "url(https://fonts.gstatic.com/s/other/v1/x.woff2)")),
        ("css imports Google Fonts", "links", [], lambda d: edit_css(d, ":root {", '@import url("https://fonts.googleapis.com/css2?family=Other");:root {')),
        ("css font face from a local file that is not the font", "fonts", [], lambda d: edit(d, "index.html", "url(fonts/weft.woff2)", "url(fonts/mark.woff2)")),
        ("css font face for another family", "fonts", [], lambda d: edit(d, "index.html", '@font-face{font-family:"mm Weft"', '@font-face{font-family:"Other"')),
        ("css font face for Lato", "fonts", [], lambda d: edit(d, "index.html", '@font-face{font-family:"mm Weft"', '@font-face{font-family:"Lato"')),
        ("css font face for EB Garamond", "fonts", [], lambda d: edit(d, "index.html", '@font-face{font-family:"mm Weft"', '@font-face{font-family:"EB Garamond"')),
        ("css font face without swap", "fonts", [], lambda d: edit(d, "index.html", "font-display:swap", "font-display:block")),
        ("css font face with another weight", "fonts", [], lambda d: edit(d, "index.html", "font-weight:100 900", "font-weight:400")),
        ("css font face with another style", "fonts", [], lambda d: edit(d, "index.html", "font-weight:100 900;font-style:normal", "font-weight:100 900;font-style:italic")),
        ("css font face drops a face", "fonts", [], lambda d: edit(d, "index.html", re.search(r'@font-face\{font-family:"mm Sans".*?\}', read_index(d)).group(0), "")),  # type: ignore[union-attr]
        ("a stack names a system font", "fonts", [], lambda d: edit_css(d, '--f-warp: "mm Warp", serif;', '--f-warp: "mm Warp", Georgia, serif;')),
        ("a stack starts with another font", "fonts", [], lambda d: edit_css(d, '--f-sans: "mm Sans", system-ui', '--f-sans: Arial, "mm Sans", system-ui')),
        ("a rule sets a font family of its own", "fonts", [], lambda d: edit_css(d, "box-sizing: border-box; }", "box-sizing: border-box; }.zz{font-family:Lato}")),
        ("a rule sets a named family in the font shorthand", "fonts", [], lambda d: edit_css(d, "box-sizing: border-box; }", "box-sizing: border-box; }.zz{font:400 var(--step-0) Lato}")),
        ("a rule sets a weight Warp does not have", "fonts", [], lambda d: edit_css(d, "box-sizing: border-box; }", "box-sizing: border-box; }.zz{font:700 var(--step-0)/1 var(--f-warp)}")),
        ("a rule sets bold beyond Sans", "fonts", [], lambda d: edit_css(d, "box-sizing: border-box; }", "box-sizing: border-box; }.zz{font-weight:900}")),
        ("a rule sets italic", "fonts", [], lambda d: edit_css(d, "box-sizing: border-box; }", "box-sizing: border-box; }.zz{font-style:italic}")),
        ("a weight inside the variable range is allowed", None, [], lambda d: edit_css(d, "box-sizing: border-box; }", "box-sizing: border-box; }.zz{font:600 var(--step-0)/1 var(--f-weft)}")),
        ("the group label loses its weight", "fonts", [], lambda d: edit_css(d, "font: 400 var(--step--1)/1.4 var(--f-weft); letter-spacing: 0.05em;", "font: var(--step--1)/1.4 var(--f-weft); letter-spacing: 0.05em;")),
        ("a bold tag", "fonts", [], lambda d: edit(d, "index.html", "<body>", "<body><b>x</b>")),
        ("an italic tag", "fonts", [], lambda d: edit(d, "index.html", "<body>", "<body><em>x</em>")),
        ("a second og:image with content first", "head", [], lambda d: edit(d, "index.html", "<style>", '<meta content="https://example.net/x.jpg" property="og:image"><style>')),
        ("a second description", "head", [], lambda d: edit(d, "index.html", "<style>", '<meta content="Other." name="description"><style>')),
        ("the font subset is not a woff2", "fonts", [], lambda d: (d / "fonts" / f"{face}.woff2").write_bytes(b"<svg/>")),
        ("the font subset is another font", "fonts", [], lambda d: (d / "fonts" / "weft.woff2").write_bytes((d / "fonts" / "sans.woff2").read_bytes())),
        ("the font subset is cut too far", "fonts", [], lambda d: (d / "fonts" / "sans.woff2").write_bytes(cut_font(d / "fonts" / "sans.woff2", "ab"))),
        ("the source font is not the release file", "fonts", [], break_source),
        ("a step of the type scale changed", "scale", [], lambda d: edit_css(d, "--step-0: 1rem;", "--step-0: 1.0625rem;")),
        ("a size off the scale", "scale", [], lambda d: edit_css(d, "box-sizing: border-box; }", "box-sizing: border-box; }.zz{font-size:17px}")),
        ("the body line height changed", "scale", [], lambda d: edit_css(d, "var(--step-0)/1.5 var(--f-sans)", "var(--step-0)/1.4 var(--f-sans)")),
        ("a spacing token off the scale", "spacing", [], lambda d: edit_css(d, "--sp-3: 12px;", "--sp-3: 10px;")),
        ("a raw margin", "spacing", [], lambda d: edit_css(d, "box-sizing: border-box; }", "box-sizing: border-box; }.zz{margin-top:10px}")),
        ("a raw gap in rem", "spacing", [], lambda d: edit_css(d, "box-sizing: border-box; }", "box-sizing: border-box; }.zz{gap:1rem}")),
        ("the description link is underlined on hover only", "touch", [], lambda d: edit_css(d, "a.u, .ds a { color: var(--text); text-decoration: underline 1px var(--accent);", "a.u, .ds a { color: var(--text); text-decoration: none;")),
        ("the description link is short", "touch", [], lambda d: edit_css(d, ".ds a { display: inline-block; padding-block: var(--sp-3);", ".ds a { display: inline-block; padding-block: var(--sp-1);")),
        ("a section link is short", "touch", [], lambda d: edit_css(d, "height: 44px; position: relative;", "height: 32px; position: relative;")),
        ("a bar-1 link is short on a phone", "touch", [], lambda d: edit_css(d, ".b1 li { height: 44px; }", ".b1 li { height: var(--sp-6); }")),
        ("a footer link is short on a phone", "touch", [], lambda d: edit_css(d, "@media (max-width: 719px) { .banner img", "@media (max-width: 719px) { footer a { min-height: var(--sp-6); } }\n@media (max-width: 719px) { .banner img")),
        ("the footer dot is dropped from the style", "touch", [], lambda d: edit_css(d, 'footer li::before { content: "\\00b7";', 'footer li::after { content: "\\00b7";')),
        ("a plate image has no hover state", "hover", [], lambda d: edit_css(d, ".plate:hover .pic img, .plate:hover .tile { filter: brightness(1.02); }", ".plate:hover .pic img, .plate:hover .tile { outline-color: var(--line); }")),
        ("font file missing", "files", [], lambda d: (d / "fonts" / "weft.woff2").unlink()),
        ("font licence missing", "files", [], lambda d: (d / "fonts" / "mm-weft-OFL.txt").unlink()),
        ("extra font file", "files", [], lambda d: (d / "fonts" / "other.woff2").write_bytes(b"wOF2")),
        ("the full font comes back", "files", [], lambda d: (d / "fonts" / "mm-weft.woff2").write_bytes((GEN / "fonts" / "mm-weft.woff2").read_bytes())),
        ("Lato comes back", "files", [], lambda d: (d / "fonts" / "lato-400.woff2").write_bytes(b"wOF2")),
        ("EB Garamond comes back", "files", [], lambda d: (d / "fonts" / "eb-garamond-OFL.txt").write_text("OFL")),
        ("private repo in a font licence", "private", [], lambda d: edit(d, "fonts/mm-weft-OFL.txt", "SIL OPEN FONT", "github.com/machine-made/zzprivate SIL OPEN FONT")),
        ("upstream link outside its licence", "private", [], lambda d: edit(d, "fonts/mm-weft-OFL.txt", "SIL OPEN FONT", "github.com/tokotype/PlusJakartaSans SIL OPEN FONT")),
        ("money amount in a font licence", "forbidden", [], lambda d: edit(d, "fonts/mm-weft-OFL.txt", "SIL OPEN FONT", "$5 SIL OPEN FONT")),
        *[
            (f"{tag} tag", "no-js", [], lambda d, tag=tag: edit(d, "index.html", "<body>", f'<body><{tag} src="https://example.net/x"></{tag}>'))
            for tag in ("audio", "video", "iframe", "object", "embed")
        ],
        ("source outside a picture", "no-js", [], lambda d: edit(d, "index.html", "<body>", '<body><source type="image/avif" srcset="og.jpg">')),
        ("source of another type", "no-js", [], lambda d: edit(d, "index.html", '<source type="image/avif"', '<source type="video/mp4"')),
        ("track tag", "no-js", [], lambda d: edit(d, "index.html", "<body>", '<body><track src="https://example.net/x">')),
        ("script tag", "no-js", [], lambda d: edit(d, "index.html", "</body>", "<script>1</script></body>")),
        ("script tag on the 404 page", "no-js", [], lambda d: edit(d, "404.html", "</body>", "<script>1</script></body>")),
        ("banner without alt", "a11y", [], lambda d: edit(d, "index.html", f'height="469" alt="{site_title(name)}"', 'height="469" alt=" "')),
        ("plate image without alt attribute", "a11y", [], lambda d: edit(d, "index.html", first_img, first_img.replace(' alt=""', ""))),
        ("plate link without an accessible name", "a11y", [], plate_edit(first, lambda li: li.replace(f' aria-label="{first}"', "", 1))),
        ("plate link named by something else", "a11y", [], plate_edit(first, lambda li: li.replace(f'aria-label="{first}"', 'aria-label="zz"', 1))),
        ("house link named by something else", "a11y", [], lambda d: edit(d, "index.html", f'class="pic" href="{TYPE_URL}" aria-label="type"', f'class="pic" href="{TYPE_URL}" aria-label="fonts"')),
        ("the repository name comes back under the plate", "projects", [], plate_edit(first, lambda li: li.replace('<p class="ds">', f'<span class="nm">{first}</span><p class="ds">', 1))),
        ("the repository name comes back inside the plate line", "projects", [], plate_edit(first, lambda li: li.replace('<p class="ds">', f'<p class="ds">{first} ', 1))),
        ("the plate has no image link", "projects", [], plate_edit(first, lambda li: re.sub(r'<a class="pic"[^>]*>(<picture>.*?</picture>)</a>', r"\1", li, count=1))),
        ("plate image has alt text that repeats the name", "a11y", [], lambda d: edit(d, "index.html", first_img, first_img.replace('alt=""', f'alt="{first}"'))),
        ("plate image without lazy loading", "projects", [], lambda d: edit(d, "index.html", first_img, first_img.replace(' loading="lazy"', ""))),
        ("plate image without size", "responsive", [], lambda d: edit(d, "index.html", first_img, first_img.replace(' width="704" height="235"', ""))),
        ("plate without AVIF", "projects", [], plate_edit(first, lambda li: re.sub(r"<source[^>]*>", "", li, count=1))),
        ("the plate facts are not the live facts", "projects", [], plate_edit(first, lambda li: re.sub(r'<time datetime="[^"]*">', '<time datetime="2001-01-01">', li, count=1))),
        ("the plate facts lose the language", "projects", [], plate_edit(first, lambda li: li.replace('<p class="facts"><span><span>', '<p class="facts"><span><span hidden>', 1))),
        ("plate image missing", "files", [], lambda d: (d / "img" / f"{first}-704.avif").unlink()),
        ("extra image", "files", [], lambda d: (d / "img" / "extra.jpg").write_bytes(b"\xff\xd8\xff")),
        ("og image missing", "files", [], lambda d: (d / "og.jpg").unlink()),
        ("banner is not a JPEG", "images", [], lambda d: (d / "img" / f"banner-{house_key(SELF)}-1408.jpg").write_bytes(b"<svg/>")),
        ("banner AVIF is not an AVIF", "images", [], lambda d: (d / "img" / f"banner-{house_key(SELF)}-1408.avif").write_bytes((d / "og.jpg").read_bytes())),
        ("plate has the wrong size", "images", [], lambda d: (d / "img" / f"{first}-704.jpg").write_bytes((d / "img" / f"{first}-352.jpg").read_bytes())),
        ("plate AVIF has the wrong size", "images", [], lambda d: (d / "img" / f"{first}-704.avif").write_bytes((d / "img" / f"{first}-352.avif").read_bytes())),
        ("banner is cut short", "images", [], lambda d: (d / "img" / f"banner-{house_key(SELF)}-1408.jpg").write_bytes((d / "img" / f"banner-{house_key(SELF)}-1408.jpg").read_bytes()[:-2])),
        ("og image has the wrong size", "images", [], lambda d: (d / "og.jpg").write_bytes((d / "img" / f"banner-{house_key(SELF)}-1408.jpg").read_bytes())),
        ("touch icon has the wrong size", "images", [], lambda d: (d / "img" / "touch.png").write_bytes(tiny_png())),
        ("image is too large", "images", [], lambda d: (d / "img" / f"{first}-704.jpg").write_bytes((d / "img" / f"{first}-704.jpg").read_bytes() + b"\x00" * 400_000)),
        ("money amount", "forbidden", [], lambda d: edit(d, "llms.txt", "## Sites", "$5\n\n## Sites")),
        ("a banned word", "forbidden", [], lambda d: edit(d, "llms.txt", "## Sites", "the brief\n\n## Sites")),
        ("a banned word in a character reference", "forbidden", [], lambda d: edit(d, "index.html", "<body>", "<body>&#99;ard")),
        ("homebrew-tap is listed", "forbidden", [], lambda d: edit(d, "llms.txt", "## Sites", "homebrew-tap\n\n## Sites")),
        ("second page", "files", [], lambda d: (d / "second.html").write_text("<!doctype html>")),
        ("mark file missing", "files" if SELF == "machine-made" else None, [], lambda d: (d / "mark.svg").unlink() if SELF == "machine-made" else None),
        ("old style file comes back", "files", [], lambda d: (d / "style.css").write_text("a{}")),
        ("old hero comes back", "files", [], lambda d: (d / "heroes").mkdir() or (d / "heroes" / "x.svg").write_text("<svg/>")),
        ("non-ASCII in llms.txt", "voice", [], lambda d: edit(d, "llms.txt", "## Sites", "café\n\n## Sites")),
        ("non-ASCII in the page", "voice", [], lambda d: edit(d, "index.html", "<body>", "<body>café")),
        ("non-ASCII in the 404 page", "voice", [], lambda d: edit(d, "404.html", "&ndash;", "–")),
        ("a dot written in the footer", "content", [], lambda d: edit(d, "index.html", "</ul></div></footer>", "<li>&middot;</li></ul></div></footer>")),
        ("bar 1 loses a site", "content", [], lambda d: edit(d, "index.html", f'<li><a href="{nav_other}">{other_name}</a></li>', "")),
        ("bar 1 marks another site", "content", [], lambda d: edit_all(d, "index.html", (f'<span aria-current="page">{SELF}</span>', f'<a href="{self_url}">{SELF}</a>'), (f'<li><a href="{nav_other}">{other_name}</a>', f'<li><span aria-current="page">{other_name}</span>'))),
        ("the current site links to itself", "content", [], lambda d: edit(d, "index.html", f'<span aria-current="page">{SELF}</span>', f'<a href="{self_url}" aria-current="page">{SELF}</a>')),
        ("the current site is not marked", "content", [], lambda d: edit(d, "index.html", f'<span aria-current="page">{SELF}</span>', f"<span>{SELF}</span>")),
        ("two entries are marked", "a11y", [], lambda d: edit(d, "index.html", f'<li><a href="{nav_other}">{other_name}</a>', f'<li><a href="{nav_other}" aria-current="page">{other_name}</a>')),
        ("a site linked twice", "links", [], lambda d: edit(d, "index.html", "</ul></div></footer>", f'<li><a href="{nav_other}">x</a></li></ul></div></footer>')),
        ("the footer loses the type link", "content", [], lambda d: edit(d, "index.html", f'<li><a href="{TYPE_URL}">type</a></li></ul></div></footer>', "</ul></div></footer>")),
        ("the footer is plain text again", "content", [], lambda d: edit(d, "index.html", footer_of(d), '<footer class="wrap"><p>' + " ".join(n for n, _ in SITES) + "</p></footer>")),
        ("the footer type link goes elsewhere", "content", [], lambda d: edit(d, "index.html", f'<li><a href="{TYPE_URL}">type</a></li></ul></div></footer>', '<li><a href="https://machine-made.github.io/fonts/">type</a></li></ul></div></footer>')),
        ("a footer link without its site", "links", [], lambda d: edit(d, "index.html", "</ul></div></footer>", f'<li><a href="{self_url}">x</a></li></ul></div></footer>')),
        ("the type link is missing", "content", [], lambda d: edit(d, "index.html", f'<li><a href="{TYPE_URL}">type</a></li></ul></nav>', "</ul></nav>")),
        ("the type link goes elsewhere", "content", [], lambda d: edit(d, "index.html", f'<li><a href="{TYPE_URL}">type</a></li></ul></nav>', '<li><a href="https://machine-made.github.io/fonts/">type</a></li></ul></nav>')),
        ("the type link moves first", "content", [], lambda d: edit_all(d, "index.html", (f'<li><a href="{TYPE_URL}">type</a></li></ul></nav>', "</ul></nav>"), ('<ul class="wrap">', f'<ul class="wrap"><li><a href="{TYPE_URL}">type</a></li>'))),
        ("the type link reads fonts", "content", [], lambda d: edit(d, "index.html", f'<a href="{TYPE_URL}">type</a></li></ul></nav>', f'<a href="{TYPE_URL}">fonts</a></li></ul></nav>')),
        ("bar 2 loses a section", "content", [], lambda d: edit(d, "index.html", f'<a href="#g-{slug(GROUPS[0][0])}">', '<a href="#main">')),
        ("bar 2 loses GitHub", "content", [], lambda d: edit(d, "index.html", f'<a href="https://github.com/{OWNER}">GitHub</a>', "")),
        ("bar 2 logo is not named", "content", [], lambda d: edit(d, "index.html", f'aria-label="{site_title(name)} home"', 'aria-label="home"')),
        ("a section link points to no group", "links", [], lambda d: edit(d, "index.html", f'<a href="#g-{slug(GROUPS[0][0])}">', '<a href="#g-zz">')),
        ("a heading level is skipped", "semantic", [], lambda d: edit_all(d, "index.html", ('<h2 class="lbl" id="g-houses">', '<h4 class="lbl" id="g-houses">'), ("<span>The houses</span></h2>", "<span>The houses</span></h4>"))),
        ("a second h1", "semantic", [], lambda d: edit(d, "index.html", "</main>", "<h1>x</h1></main>")),
        # The head: title, description, favicon and the social preview.
        ("the title changed", "head", [], lambda d: edit(d, "index.html", "<title>", "<title>Other ")),
        ("the description meta changed", "head", [], lambda d: edit(d, "index.html", '<meta name="description" content="', '<meta name="description" content="Other. ')),
        ("the favicon is missing", "head", [], lambda d: edit(d, "index.html", re.search(r'<link rel="icon"[^>]*>', read_index(d)).group(0), "")),  # type: ignore[union-attr]
        ("the touch icon is missing", "head", [], lambda d: edit(d, "index.html", '<link rel="apple-touch-icon" href="img/touch.png">', "")),
        ("og:image is missing", "head", [], lambda d: edit(d, "index.html", f'<meta property="og:image" content="{self_url}og.jpg">', "")),
        ("og:image is the banner", "head", [], lambda d: edit(d, "index.html", f'content="{self_url}og.jpg"', f'content="{self_url}img/banner-{house_key(SELF)}-1408.jpg"')),
        ("og:image is a relative path", "head", [], lambda d: edit(d, "index.html", f'content="{self_url}og.jpg"', 'content="og.jpg"')),
        ("og:image has the old size", "head", [], lambda d: edit(d, "index.html", '<meta property="og:image:height" content="630">', '<meta property="og:image:height" content="469">')),
        ("og:title changed", "head", [], lambda d: edit(d, "index.html", '<meta property="og:title" content="', '<meta property="og:title" content="Other ')),
        ("og:url changed", "head", [], lambda d: edit(d, "index.html", f'<meta property="og:url" content="{self_url}"', '<meta property="og:url" content="https://example.net/"')),
        ("twitter:card is missing", "head", [], lambda d: edit(d, "index.html", '<meta name="twitter:card" content="summary_large_image">', "")),
        ("the banner is not in the h1", "content", [], lambda d: edit_all(d, "index.html", ('<h1 class="banner"><picture>', '<h1 class="banner"></h1><picture>'), ("</picture></h1>", "</picture>"))),
        ("banner shows another image", "content", [], lambda d: edit(d, "index.html", f'<img src="img/banner-{house_key(SELF)}-1408.jpg"', f'<img src="img/{first}-704.jpg"')),
        ("banner loads lazily", "content", [], lambda d: edit(d, "index.html", 'decoding="async" fetchpriority="high"></picture></h1>', 'loading="lazy" decoding="async"></picture></h1>')),
        ("house line changed", "content", [], lambda d: edit(d, "index.html", f'<p class="line {face}">', f'<p class="line {face}">Another line. ')),
        ("house line in another face", "content", [], lambda d: edit(d, "index.html", f'<p class="line {face}">', '<p class="line sans">')),
        ("the name paragraph comes back", "content", [], lambda d: edit(d, "index.html", f'<p class="line {face}">', '<p class="blurb">x</p><p class="line zz">')),
        ("house line missing in llms.txt", "llms", [], lambda d: edit(d, "llms.txt", f"> {LINE}", "> ")),
        ("Latest is not the newest", "latest", [], lambda d: edit(d, "index.html", '<ol class="latest', '<ol class="latest"><li><a href="#main">zz</a></li></ol><ol class="zz')),
        ("Latest repeats a repository", "latest", [], lambda d: edit(d, "index.html", re.search(r'(<ol class="latest n\d">)(<li>.*?</li>)', read_index(d)).group(0), re.sub(r'(<ol class="latest n\d">)(<li>.*?</li>)', r"\1\2\2", re.search(r'(<ol class="latest n\d">)(<li>.*?</li>)', read_index(d)).group(0)))),  # type: ignore[union-attr]
        ("Latest has an old date", "latest", [], lambda d: edit(d, "index.html", re.search(r'<ol class="latest n\d"><li>.*?<time datetime="[^"]*">', read_index(d)).group(0), re.sub(r'datetime="[^"]*"', 'datetime="2001-01-01"', re.search(r'<ol class="latest n\d"><li>.*?<time datetime="[^"]*">', read_index(d)).group(0)))),  # type: ignore[union-attr]
        ("the houses row loses the type site", "houses", [], lambda d: edit(d, "index.html", re.search(r'<li class="plate"><a class="pic" href="' + re.escape(TYPE_URL) + r'".*?</li>', read_index(d)).group(0), "")),  # type: ignore[union-attr]
        ("the houses row shows this house", "houses", [], lambda d: edit(d, "index.html", f'<li class="plate"><a class="pic" href="{nav_other}"', f'<li class="plate"><a class="pic" href="{self_url}"')),
        ("the houses row has a stale release", "houses", [], lambda d: edit(d, "index.html", re.search(r'aria-labelledby="g-houses".*?<time datetime="[^"]*">', read_index(d)).group(0), re.sub(r'datetime="[^"]*">$', 'datetime="2001-01-01">', re.search(r'aria-labelledby="g-houses".*?<time datetime="[^"]*">', read_index(d)).group(0)))),  # type: ignore[union-attr]
        ("sites missing in llms.txt", "llms", [], lambda d: edit(d, "llms.txt", "## Sites", "## Elsewhere")),
        ("page order changed", "content", [], move_footer_up),
        ("a group heading is renamed", "projects", [], lambda d: edit(d, "index.html", f"<span>{GROUPS[0][0]}</span></h2>", "<span>Tools</span></h2>")),
        ("a group has no label class", "projects", [], lambda d: edit(d, "index.html", f'<h2 class="lbl" id="g-{slug(GROUPS[0][0])}"', f'<h2 id="g-{slug(GROUPS[0][0])}"')),
        ("a project is dropped", "projects", [], plate_edit(first, lambda li: "")),
        *(
            [("two projects swap places", "projects", [], lambda d: edit_all(d, "index.html", (f"/{first}\"", "/zz-swap\""), (f"/{second}\"", f"/{first}\""), ("/zz-swap\"", f"/{second}\"")))]
            if second != first
            else []
        ),
        ("a project is added", "projects", [], lambda d: edit(d, "index.html", '</ul></section><section class="row" aria-labelledby="g-houses">', f'<li class="plate"><a class="pic" href="https://github.com/{OWNER}/{first}" aria-label="{first}">x</a></li></ul></section><section class="row" aria-labelledby="g-houses">')),
        ("a group heading is renamed in llms.txt", "llms", [], lambda d: edit(d, "llms.txt", f"## {GROUPS[0][0]}", "## Tools")),
        ("unexpected site link", "links", [], plate_edit(second, lambda li: li.replace("</p><p class=\"facts\">", ' <a href="https://machine-made.github.io/zz/">site</a></p><p class="facts">', 1))),
        ("unexpected site link on another host", "links", [], plate_edit(second, lambda li: li.replace("</p><p class=\"facts\">", ' <a href="https://example.net/">site</a></p><p class="facts">', 1))),
        ("plate name is a heading", "projects", [], plate_edit(second, lambda li: li.replace("</li>", f'<h3 class="nm">{second}</h3></li>'))),
        ("moved repository listed again", "projects", [], lambda d: edit(d, "index.html", "</ol>", f'</ol><a href="https://github.com/{OWNER}/chaos-atlas">chaos-atlas</a>')),
        ("private name in a class value", "private", ["zzprivate"], lambda d: edit(d, "index.html", '<main id="main" class="wrap', '<main id="main" class="zzprivate wrap')),
        ("private name in an id value", "private", ["zzprivate"], lambda d: edit(d, "index.html", 'id="main"', 'id="zzprivate"')),
        ("unknown attribute", "attrs", [], lambda d: edit(d, "index.html", '<main id="main"', '<main data-x="1" id="main"')),
        ("css imports a remote file", "links", [], lambda d: edit_css(d, ":root {", '@import url("https://example.net/x.css");:root {')),
        ("css string import", "links", [], lambda d: edit_css(d, ":root {", '@import "https://example.net/x.css";:root {')),
        ("css url on a look-alike font host", "links", [], lambda d: edit_css(d, ":root {", "a{background:url(https://fonts.gstatic.com.example.net/f.woff2)}:root {")),
        ("css url leaves docs/", "links", [], lambda d: edit_css(d, ":root {", "a{background:url(../README.md)}:root {")),
        ("css data url", "links", [], lambda d: edit_css(d, ":root {", "a{background:url(data:image/png;base64,AAAA)}:root {")),
        ("css image-set", "links", [], lambda d: edit_css(d, ":root {", 'a{background:image-set("og.jpg" 1x)}:root {')),
        ("css image()", "links", [], lambda d: edit_css(d, ":root {", 'a{background:image("og.jpg")}:root {')),
        ("css prefixed cross-fade", "links", [], lambda d: edit_css(d, ":root {", "a{background:-webkit-cross-fade(url(og.jpg),url(og.jpg),50%)}:root {")),
        ("css escaped function name", "css", [], lambda d: edit_css(d, ":root {", "a{background:\\69mage-set(og.jpg 1x)}:root {")),
        ("a second escape in a content string", "css", [], lambda d: edit_css(d, "box-sizing: border-box; }", 'box-sizing: border-box; }.zz::before{content:"\\72 ed"}')),
        ("named colour in the style", "accent", [], lambda d: edit_css(d, "box-sizing: border-box;", "color:red;box-sizing: border-box;")),
        ("upper-case named colour", "accent", [], lambda d: edit_css(d, "box-sizing: border-box;", "color:BLUE;box-sizing: border-box;")),
        ("named colour in a border", "accent", [], lambda d: edit_css(d, "box-sizing: border-box;", "border:1px solid tomato;box-sizing: border-box;")),
        ("named colour in a var fallback", "accent", [], lambda d: edit_css(d, "box-sizing: border-box;", "color:var(--text,navy);box-sizing: border-box;")),
        ("system colour", "accent", [], lambda d: edit_css(d, "box-sizing: border-box;", "color:LinkText;box-sizing: border-box;")),
        ("escaped colour name", "css", [], lambda d: edit_css(d, "box-sizing: border-box;", "color:\\72 ed;box-sizing: border-box;")),
        ("colour mix function", "colour", [], lambda d: edit_css(d, "box-sizing: border-box;", "color:color-mix(in srgb,#fff,#000);box-sizing: border-box;")),
        ("black, white and transparent are allowed", None, [], lambda d: edit_css(d, "box-sizing: border-box;", "color:black;background:WHITE;border-color:transparent;outline-color:currentColor;box-sizing: border-box;")),
        ("a class with a colour name is not a colour", None, [], lambda d: edit_css(d, "box-sizing: border-box; }", "box-sizing: border-box; }.red{margin:0}a:not(.tan){margin:0}.zz{margin:0}")),
        ("named colour in the colour block", "accent", [], lambda d: edit(d, "index.html", "<style>@font-face", "<style>a{color:red}@font-face")),
        ("a third style block", "css", [], lambda d: edit(d, "index.html", "</head>", "<style>a{color:#00f}</style></head>")),
        ("text colour from a low-contrast grey", "contrast", [], lambda d: edit_css(d, "box-sizing: border-box; }", f"box-sizing: border-box; }}.zz{{color:{THEME['ground'].replace('0', '1', 1)}}}")),
        ("text colour from the line token", "contrast", [], lambda d: edit_css(d, "box-sizing: border-box; }", "box-sizing: border-box; }.zz{color:var(--line)}")),
        ("text on a low-contrast background token", "contrast", [], lambda d: edit_css(d, "box-sizing: border-box; }", "box-sizing: border-box; }.zz{color:var(--text);background:var(--muted)}")),
        ("background shorthand with more than a token", "contrast", [], lambda d: edit_css(d, "box-sizing: border-box; }", "box-sizing: border-box; }.zz{background:var(--ground) url(og.jpg)}")),
        ("text colour from an unknown token", "contrast", [], lambda d: edit_css(d, "box-sizing: border-box; }", "box-sizing: border-box; }.zz{color:var(--nope)}")),
        ("a pair of palette tokens is allowed", None, [], lambda d: edit_css(d, "box-sizing: border-box; }", "box-sizing: border-box; }.zz{color:var(--muted);background:var(--surface) !important}")),
        ("the muted colour fails its floor", "contrast", [], lambda d: (edit(d, "index.html", f"--muted:{THEME['muted']}", "--muted:#4a4a4a"), set_theme("muted", "#4a4a4a"))),
        ("upper-case colour function", "colour", [], lambda d: edit_css(d, "box-sizing: border-box;", "color:RGB(0,0,255);box-sizing: border-box;")),
        ("upper-case gradient", "colour", [], lambda d: edit_css(d, "box-sizing: border-box;", "background:LINEAR-GRADIENT(red,blue);box-sizing: border-box;")),
        ("a second gradient", "colour", [], lambda d: edit_css(d, "box-sizing: border-box;", "background:linear-gradient(#000,#000);box-sizing: border-box;")),
        ("the banner mask changed", "colour", [], lambda d: edit_css(d, " mask-image: linear-gradient(transparent, #000 10%", " mask-image: linear-gradient(transparent, #000 20%")),
        ("the banner mask missing", "colour", [], lambda d: edit_css(d, " " + MASKS[0], " ")),
        ("base tag", "no-js", [], lambda d: edit(d, "index.html", "<body>", '<body><base href="https://example.net/">')),
        ("private name as a character reference in llms.txt", "private", ["zzprivate"], lambda d: edit(d, "404.html", "<body>", "<body>zz&#x70;rivate ")),
        ("private name as a nested reference in an attribute", "private", ["zzprivate"], lambda d: edit(d, "llms.txt", "## Sites", "zz&amp;#112;rivate\n\n## Sites")),
        ("private repo as a character reference", "private", [], lambda d: edit(d, "llms.txt", "## Sites", "github.com/&#x6d;achine-made/zzprivate\n\n## Sites")),
        ("USD before an amount", "forbidden", [], lambda d: edit(d, "llms.txt", "## Sites", "USD 5\n\n## Sites")),
        ("CHF before an amount", "forbidden", [], lambda d: edit(d, "llms.txt", "## Sites", "chf 5\n\n## Sites")),
        ("EUR before an amount", "forbidden", [], lambda d: edit(d, "llms.txt", "## Sites", "Eur5\n\n## Sites")),
        ("USD after an amount", "forbidden", [], lambda d: edit(d, "llms.txt", "## Sites", "5 USD\n\n## Sites")),
        ("private name as an element name", "private", ["zzprivate"], lambda d: edit(d, "index.html", "<body>", "<body><zzprivate></zzprivate>")),
        # The behaviour rules: each break is one rule moved out of its media query.
        ("a hover rule outside the hover query", "hover", [], lambda d: edit_css(d, "box-sizing: border-box; }", "box-sizing: border-box; }.plate:hover{margin:0}")),
        ("a colour hover outside the hover query", "hover", [], lambda d: edit_css(d, "@media (hover: hover) { .b1 a:hover { color: var(--text); } }", ".b1 a:hover { color: var(--text); }")),
        ("a hover rule in the wrong query", "hover", [], lambda d: edit_css(d, "box-sizing: border-box; }", "box-sizing: border-box; }@media (min-width: 1px){.plate:hover{margin:0}}")),
        ("a hover rule in the hover query is allowed", None, [], lambda d: edit_css(d, "box-sizing: border-box; }", "box-sizing: border-box; }@media (hover: hover){.zz:hover{margin:0}}")),
        ("a transition outside the motion query", "motion", [], lambda d: edit_css(d, "box-sizing: border-box; }", "box-sizing: border-box; }.zz{transition:color 1s}")),
        ("a transform outside the motion query", "motion", [], lambda d: edit_css(d, "box-sizing: border-box; }", "box-sizing: border-box; }.zz{transform:scale(2)}")),
        ("the plate transition leaves the motion query", "motion", [], lambda d: edit_css(d, "outline-offset: -1px; }", "outline-offset: -1px; transition: filter 240ms var(--ease); }")),
        ("the bar-2 line animates for every reader", "motion", [], lambda d: edit_css(d, "@media (prefers-reduced-motion: no-preference) {\n  @supports", "@media (min-width: 1px) {\n  @supports")),
        ("an animation in a hover query only", "motion", [], lambda d: edit_css(d, "box-sizing: border-box; }", "box-sizing: border-box; }@media (hover: hover){.zz{animation:none}}")),
        ("smooth scrolling outside the motion query", "motion", [], lambda d: edit_css(d, "box-sizing: border-box; }", "box-sizing: border-box; }html{scroll-behavior:smooth}")),
        ("the focus ring is removed", "focus", [], lambda d: edit_css(d, ":focus-visible { outline: 2px solid var(--accent);", ":focus-visible { outline: none;")),
        ("the focus ring is not the accent", "focus", [], lambda d: edit_css(d, ":focus-visible { outline: 2px solid var(--accent);", ":focus-visible { outline: 2px solid var(--text);")),
        ("an outline is removed on a link", "focus", [], lambda d: edit_css(d, "box-sizing: border-box; }", "box-sizing: border-box; }.plate a{outline:none}")),
        ("the page grid changed", "responsive", [], lambda d: edit_css(d, ".row { display: grid; grid-template-columns: repeat(12,", ".row { display: grid; grid-template-columns: repeat(10,")),
        ("the plate grid is four columns", "responsive", [], lambda d: edit_css(d, ".grid { display: grid; grid-template-columns: repeat(3,", ".grid { display: grid; grid-template-columns: repeat(4,")),
        ("the plate grid keeps two columns on a phone", "responsive", [], lambda d: edit_css(d, ".grid, .grid.g2 { grid-template-columns: minmax(0, 1fr);", ".grid, .grid.g2 { grid-template-columns: repeat(2, minmax(0, 1fr));")),
        ("the content width changed", "responsive", [], lambda d: edit_css(d, "--max: 1200px", "--max: 1280px")),
        ("a forced width", "responsive", [], lambda d: edit_css(d, "box-sizing: border-box;", "width:900px;box-sizing: border-box;")),
        ("the accent never used", "accent", [], lambda d: edit_css_all(d, "var(--accent)", "var(--text)")),
        ("the style is not src/system.css", "css", [], lambda d: edit(d, "index.html", "box-sizing: border-box;", "box-sizing: content-box;")),
        ("the faces block differs from the house", "fonts", [], lambda d: edit(d, "index.html", "font-display:swap}", "font-display:swap} ")),
        # The 404 page.
        ("the 404 page links relative to itself", "404", [], lambda d: edit(d, "404.html", 'href="/img/touch.png"', 'href="img/touch.png"')),
        ("the 404 page loads fonts relative to itself", "404", [], lambda d: edit(d, "404.html", "url(/fonts/weft.woff2)", "url(fonts/weft.woff2)")),
        ("the 404 page loses its way home", "404", [], lambda d: edit(d, "404.html", '<a class="u" href="/">', '<a class="u" href="#main">')),
        ("the 404 title changed", "404", [], lambda d: edit(d, "404.html", "<title>Not found &ndash;", "<title>Missing &ndash;")),
        ("the 404 page has another bar 1", "404", [], lambda d: edit(d, "404.html", f'<span aria-current="page">{SELF}</span>', f'<a href="{self_url}" aria-current="page">{SELF}</a>')),
        ("the 404 section link points to no group", "links", [], lambda d: edit(d, "404.html", f'<a href="/#g-{slug(GROUPS[0][0])}">', '<a href="/#g-zz">')),
        ("the 404 page loads a missing image", "links", [], lambda d: edit(d, "404.html", 'href="/img/touch.png"', 'href="/img/zz.png"')),
    ]
    if REDIRECTS:
        folder = next(iter(REDIRECTS))
        target = REDIRECTS[folder]
        cases += [
            ("redirect page missing", "files", [], lambda d: (d / folder / "index.html").unlink()),
            ("redirect page extra", "files", [], lambda d: (d / "other").mkdir() or (d / "other" / "index.html").write_text(redirect_page("other", "https://example.net/"))),
            ("redirect to an unlisted target", "redirects", [], lambda d: (d / folder / "index.html").write_text(redirect_page(folder, "https://example.net/x/"))),
            ("redirect refresh differs from canonical", "redirects", [], lambda d: edit(d, f"{folder}/index.html", f'content="0; url={target}"', 'content="0; url=https://example.net/"')),
            ("redirect page with a script", "redirects", [], lambda d: edit(d, f"{folder}/index.html", "</head>", "<script>1</script></head>")),
        ]
    if SELF == "machine-made":
        cases += [
            ("accent in a style attribute", "accent", [], lambda d: edit(d, "mark.svg", '<rect class="k"', '<path style="fill:#00f" class="k"')),
            ("accent in stop-color", "accent", [], lambda d: edit(d, "mark.svg", '<rect class="k"', '<path stop-color="#00ff00" class="k"')),
            ("named colour in a stroke", "accent", [], lambda d: edit(d, "mark.svg", '<rect class="k"', '<path stroke="red" class="k"')),
            ("named colour in an svg rule", "accent", [], lambda d: edit(d, "mark.svg", ".k{fill:", ".k{stroke:red;fill:")),
            ("gradient in the mark", "colour", [], lambda d: edit(d, "mark.svg", "<rect", '<defs><linearGradient id="z"/></defs><rect')),
            ("script in the mark svg", "no-js", [], lambda d: edit(d, "mark.svg", "<title>", "<script>1</script><title>")),
            ("event handler in the mark svg", "no-js", [], lambda d: edit(d, "mark.svg", '<rect class="k"', '<path onclick="x()" class="k"')),
            ("external href in the mark svg", "links", [], lambda d: edit(d, "mark.svg", "<rect", '<use href="https://example.net/x.svg#a"/><rect')),
            ("remote url in an svg rule", "links", [], lambda d: edit(d, "mark.svg", "<style>", "<style>.z{fill:url(https://example.net/x.svg#a)}")),
            ("accent as the fallback of a fragment paint", "accent", [], lambda d: edit(d, "mark.svg", '<rect class="k"', '<path fill="url(#a) #0000ff" class="k"')),
            ("named fallback of a fragment paint", "accent", [], lambda d: edit(d, "mark.svg", '<rect class="k"', '<path fill="url(#a) red" class="k"')),
            ("function fallback of a fragment paint", "colour", [], lambda d: edit(d, "mark.svg", '<rect class="k"', '<path fill="url(#a) rgb(0,0,255)" class="k"')),
            ("keyword fallback of a fragment paint", None, [], lambda d: edit(d, "mark.svg", '<rect class="k"', '<path fill="url(#a) currentColor" class="k"')),
            ("private name as a character reference in the mark", "private", ["zzprivate"], lambda d: edit(d, "mark.svg", "<title>", "<title>zz&#x70;rivate ")),
            ("private repo as a character reference in the mark", "private", [], lambda d: edit(d, "mark.svg", "<title>", "<title>github.com/&#x6d;achine-made/zzprivate ")),
            ("remote url in a filter attribute", "links", [], lambda d: edit(d, "mark.svg", '<rect class="k"', '<path filter="url(https://example.net/x.svg#f)" class="k"')),
            ("remote url in a fill attribute", "links", [], lambda d: edit(d, "mark.svg", '<rect class="k"', '<path fill="url(https://example.net/x.svg#f)" class="k"')),
            ("local fragment in a filter attribute", None, [], lambda d: edit(d, "mark.svg", '<rect class="k"', '<path filter="url(#f)" class="k"')),
        ]
    total, bad = 0, 0

    def report(ok: bool, title: str) -> None:
        nonlocal total, bad
        total += 1
        if not ok:
            bad += 1
            print(f"SELF-TEST FAIL: {title}")

    real_theme = dict(THEME)
    with tempfile.TemporaryDirectory() as tmp:
        for title, rule_name, deny, mutate in [*cases, ("clean copy", None, [], lambda d: None)]:
            root = Path(tmp) / "case"
            shutil.rmtree(root, ignore_errors=True)
            shutil.copytree(real, root / "docs")
            (root / "README.md").write_text("outside docs/\n")
            DOCS, SYSTEM_SRC = root / "docs", real_src
            THEME.clear()
            THEME.update(real_theme)
            FONT_DIR = GEN / "fonts"
            try:
                mutate(DOCS)
                found = run_checks(deny)
            except AssertionError as exc:
                found, rule_name = [str(exc)], "stale"
            except Exception as exc:  # noqa: BLE001 -- a crash is a self-test failure, reported with its case
                found, rule_name = [f"crash {exc!r}"], "no crash"
            caught = any(line.startswith(f"FAIL {rule_name}:") for line in found) if rule_name else not found
            report(caught, f"{title}: expected {rule_name or 'a clean pass'}, got {found[:2]}")
        DOCS, SYSTEM_SRC, FONT_DIR = real, real_src, GEN / "fonts"
        THEME.clear()
        THEME.update(real_theme)
        site = json.loads((GEN / "site.json").read_text(encoding="utf-8"))
        for bad_name in ("../evil", "Machine", "a..b", "-x", "a/b"):
            report(build_rejects({"name": bad_name}, data), f"build.py accepted the site name {bad_name!r}")
        theme = site["theme"]
        group0 = site["groups"][0]
        bad_sites: list[dict[str, object]] = [
            {"groups": []},
            {"groups": "x"},
            {"groups": [{"title": "A", "nav": "A", "projects": []}]},
            {"groups": [{"title": "A", "nav": "A", "projects": [{"repo": first, "line": "y"}]}, {"title": "a!", "nav": "B", "projects": [{"repo": second, "line": "y"}]}]},
            {"groups": [{"title": "A", "nav": "A", "projects": [{"repo": first, "line": "y"}, {"repo": first, "line": "y"}]}]},
            {"groups": [{"title": "A", "nav": "A", "projects": [{"repo": first, "line": "y", "site": "http://x"}]}]},
            {"groups": [{"title": "A", "nav": "A", "projects": [{"repo": "zz-no-image", "line": "y"}]}]},
            {"groups": [{"title": "A", "nav": "A", "projects": [{"repo": first, "line": "café"}]}]},
            {"groups": [{"title": "A", "nav": "A", "projects": [{"repo": "homebrew-tap", "line": "y"}]}]},
            {"groups": [{"title": "A", "projects": [{"repo": first, "line": "y"}]}]},
            {"groups": [{**group0, "nav": "A label far too long"}]},
            {"blurb": "x"},
            {"line": "café"},
            {"theme": {**theme, "ground": "#000"}},
            {"theme": {**theme, "size": 20}},
            {"theme": {k: v for k, v in theme.items() if k != "surface"}},
            {"theme": {**theme, "muted": "#3a3a3a"}},
            {"theme": {**theme, "face": "Comic Sans"}},
            {"groups": [{"title": "A", "nav": "A", "projects": [{"repo": first, "line": "y", "site": "https://example.net/", "site_label": "demo"}]}]},
            {"groups": [{"title": "A", "nav": "A", "projects": [{"repo": first, "line": "y", "site_label": "docs"}]}]},
            {"nav": []},
            {"nav": ["machine-made"]},
            {"nav": [dict(n) for n in site["nav"][:3]]},
            {"nav": [*site["nav"][:3], {"name": "type", "url": "https://example.net/type/"}]},
            {"nav": [*site["nav"][:3], {"name": "type", "url": TYPE_URL, "self": True}]},
            {"redirects": {"404.html": "https://example.net/x"}},
            {"redirects": {"llms.txt": "https://example.net/x"}},
        ]
        for changes in bad_sites:
            report(build_rejects(changes, data), f"build.py accepted {str(changes)[:60]}")
        for problem in site_links_hold(data):
            report(False, problem)
        report(build_needs("fonts/mm-weft.woff2", data), "build.py builds without the fonts in fonts/")
        report(build_needs("src/system.css", data), "build.py builds without src/system.css")
        report(build_needs(f"img/org/{name}.jpg", data), "build.py builds without the banner of the house")
        report(build_needs(f"img/repo/{first}.jpg", data), "build.py builds without the banner of a repository")
        report(build_fails_on_fetch(), "build.py builds when the GitHub fetch fails")
        broken = Path(tmp) / "data.json"
        facts = json.loads(data.read_text(encoding="utf-8"))
        del facts["repos"][first_full]
        broken.write_text(json.dumps(facts), encoding="utf-8")
        report(build_rejects({}, broken), "build.py builds from a facts file that lacks a repository")
        missing = str(Path(tmp) / "missing")
        denied = Path(tmp) / "deny.txt"
        denied.write_text("# a comment\n\nzz one\n  zz two  \n#zz three\n", encoding="utf-8")
        report(load_deny(str(denied)) == ["zz one", "zz two"], "load_deny does not keep one name per line")
        report(cli_fails(["--deny"], "FAIL args:"), "--deny without a file")
        report(cli_fails(["--data", DATA_PATH, "--deny", missing], "FAIL deny:"), "--deny with a missing file")
        report(cli_fails(["--no-such-flag"], "FAIL args:"), "an unknown flag")
        report(cli_fails(["--data", DATA_PATH, "--site", missing], "FAIL args:"), "--site with no allow.json")
        report(cli_fails([], "FAIL args:"), "no GitHub facts file")
        report(cli_fails(["--data", str(broken)], "FAIL args:"), "a facts file that lacks a repository")
    if bad:
        sys.exit(1)
    print(f"SELF-TEST OK ({total} cases)")


def break_source(docs: Path) -> None:
    """Point the checks at a copy of fonts/ whose Weft source has one more byte."""
    global FONT_DIR  # noqa: PLW0603
    copy = docs.parent / "fonts"
    shutil.copytree(GEN / "fonts", copy)
    (copy / "mm-weft.woff2").write_bytes((copy / "mm-weft.woff2").read_bytes() + b"\x00")
    FONT_DIR = copy


def set_theme(key: str, value: str) -> None:
    """A case that changes the public list itself: the page and allow.json agree on a colour that fails its floor."""
    THEME[key] = value


def cut_font(path: Path, keep: str) -> bytes:
    from io import BytesIO

    from fontTools import subset as fts

    opts = fts.Options()
    opts.flavor = "woff2"
    opts.layout_features = ["*"]
    font = fts.load_font(str(path), opts)
    sub = fts.Subsetter(opts)
    sub.populate(text=keep)
    sub.subset(font)
    buf = BytesIO()
    fts.save_font(font, buf, opts)
    return buf.getvalue()


def tiny_png() -> bytes:
    """A valid 1 x 1 PNG."""
    import struct
    import zlib

    def chunk(kind: bytes, body: bytes) -> bytes:
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))

    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(b"\x00\x00\x00\x00")) + chunk(b"IEND", b"")


def edit_css_all(docs: Path, old: str, new: str) -> None:
    """Replace every occurrence in the source copy and both pages."""
    global SYSTEM_SRC  # noqa: PLW0603
    copy = docs.parent / "system.css"
    if not copy.is_file():
        shutil.copy(SYSTEM_SRC, copy)
    SYSTEM_SRC = copy
    copy.write_text(copy.read_text(encoding="utf-8").replace(old, new), encoding="utf-8")
    for page in ("index.html", "404.html"):
        path = docs / page
        text = path.read_text(encoding="utf-8")
        head, _, style = text.rpartition("<style>")
        path.write_text(head + "<style>" + style.replace(old, new), encoding="utf-8")


def footer_of(docs: Path) -> str:
    """The footer element of docs/index.html as written."""
    found = re.search(r"<footer.*?</footer>", read_index(docs), re.S)
    if found is None:
        raise AssertionError("self-test is stale: no footer in docs/index.html")  # noqa: TRY003
    return found.group(0)


def move_footer_up(docs: Path) -> None:
    """Put the footer before the main part: the page order is broken."""
    text = read_index(docs)
    foot = footer_of(docs)
    text = text.replace(foot, "").replace('<main id="main"', foot + '<main id="main"', 1)
    (docs / "index.html").write_text(text, encoding="utf-8")


def read_index(docs: Path) -> str:
    return (docs / "index.html").read_text(encoding="utf-8")


def load_allow(folder: str) -> None:
    """Point the checks at a house. Its allow.json is the public list, kept apart from site.json on purpose: the page
    passes only when the two agree. The other houses come from the allow.json files of this generator."""
    global ROOT, DOCS, OWNER, LINE, THEME, SELF, SITES, GROUPS, SITE_LINKS, SITE_LABELS, REDIRECTS, OTHERS  # noqa: PLW0603
    root = Path(folder).resolve()
    try:
        allow = json.loads((root / "allow.json").read_text(encoding="utf-8"))
        OWNER, LINE = str(allow["owner"]), str(allow["line"])
        THEME = {k: str(allow["theme"][k]) for k in (*THEME_KEYS, "face")}
        SITES = tuple((str(n), str(u)) for n, u in allow["sites"])
        SELF = str(allow["self"])
        GROUPS = tuple((str(title), tuple(str(r) for r in repos)) for title, repos in allow["groups"])
        SITE_LINKS = {str(k): str(v) for k, v in allow.get("site_links", {}).items()}
        SITE_LABELS = {str(k): str(v) for k, v in allow.get("site_labels", {}).items()}
        REDIRECTS = {str(k): str(v) for k, v in allow.get("redirects", {}).items()}
        site_owner = str(json.loads((root / "site.json").read_text(encoding="utf-8"))["owner"])
        others = {}
        for path in [GEN / "allow.json", *sorted((GEN / "houses").glob("*/allow.json"))]:
            other = json.loads(path.read_text(encoding="utf-8"))
            if other["self"] != SELF:
                others[str(other["self"])] = (str(other["line"]), tuple(str(r) for _, repos in other["groups"] for r in repos))
        OTHERS = others
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"FAIL args: {folder}/allow.json is missing or incomplete ({exc.__class__.__name__})")
        sys.exit(2)
    if site_owner != OWNER:
        print(f"FAIL args: {folder}/allow.json owner {OWNER!r} differs from site.json owner {site_owner!r}")
        sys.exit(2)
    if THEME["face"] not in FACES or SELF not in {n for n, _ in SITES}:
        print(f"FAIL args: {folder}/allow.json names a face or a current site that the checks do not know")
        sys.exit(2)
    if [n for n, _ in SITES] != list(BAR_NAMES) or dict(SITES)["type"] != TYPE_URL or SELF == "type":
        print(f"FAIL args: {folder}/allow.json sites must be {', '.join(BAR_NAMES)} with type at {TYPE_URL}")
        sys.exit(2)
    if set(OTHERS) != set(BAR_NAMES[:3]) - {SELF}:
        print(f"FAIL args: the generator must hold the allow.json of {', '.join(BAR_NAMES[:3])}")
        sys.exit(2)
    if set(SITE_LABELS) - set(SITE_LINKS) or not set(SITE_LABELS.values()) <= {"docs"}:
        print(f"FAIL args: {folder}/allow.json site_labels may only mark a site link as docs")
        sys.exit(2)
    ROOT, DOCS = root, root / "docs"


def main() -> None:
    global DATA_PATH  # noqa: PLW0603
    args = parse_args(sys.argv[1:])
    load_allow(args.site or str(GEN))
    load_data(args.data)
    DATA_PATH = str(Path(args.data or os.environ["MM_DATA"]).resolve())
    deny = load_deny(args.deny)
    if args.self_test:
        self_test()
        return
    found = run_checks(deny)
    if found:
        print("\n".join(found))
        sys.exit(1)
    print("OK")


if __name__ == "__main__":
    main()
