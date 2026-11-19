#!/usr/bin/env python3
"""Check the built site in docs/. Standard library only.

Prints OK and exits 0 when every rule holds. Otherwise prints one line per failure and exits 1.
`python3 check_site.py --self-test` breaks a copy of docs/ in many ways and checks that each
break is caught.

The checks read the public list of the house from allow.json (next to site.json): the owner, the
line, the paragraph on the name, the colours and the font, the three sites, the projects in their
groups, the project sites and the redirects. The page passes only when site.json and allow.json
agree.

Private repository names are not kept in this repository. Rules that need them read a list
from a file outside the repository: `python3 check_site.py --deny FILE` or MM_DENY_FILE=FILE.
FILE has one name per line. Without it, the allowlist rules still reject every link and every
repository-shaped name that is not public.
"""

import argparse
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
from typing import Literal, NoReturn
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parent
DOCS = ROOT / "docs"

# The public list of the house. load_allow() fills it from allow.json.
OWNER = ""
LINE = ""
BLURB = ""
THEME: dict[str, str] = {}
SELF = ""
# The three sites as (name, url), in the order of the top bar.
SITES: tuple[tuple[str, str], ...] = ()
# (title, ("owner/repo", ...)) in page order.
GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = ()
# "owner/repo" -> the project's own site or documentation, linked after the description of the plate.
SITE_LINKS: dict[str, str] = {}
# "owner/repo" -> "docs" when that link is the documentation; every other site link reads "site".
SITE_LABELS: dict[str, str] = {}
# Moved repositories: docs/<name>/index.html forwards the old path to the new home.
REDIRECTS: dict[str, str] = {}

WEFT, SANS, WARP = "machine-made Weft", "machine-made Sans", "machine-made Warp"
# The only fonts a page may use, all machine-made, version 0.2.0 (https://machine-made.github.io/type/).
# family -> (faces, licence file). A face is (file stem, font-weight, font-style, sha256 of the woff2 file):
# the hash is the file of the 0.2.0 release, so a file under a machine-made name that is not that font fails.
FONT_SPECS: dict[str, tuple[tuple[tuple[str, str, str, str], ...], str]] = {
    WEFT: (
        (("mm-weft", "100 900", "normal", "9115be68c727ae8c707eed1097f878fd7e7bd54fa75bd70b099e94e4e5e71e85"),),
        "mm-weft-OFL.txt",
    ),
    SANS: (
        (("mm-sans", "200 800", "normal", "8ec52cf1b8a799dcda3aab4cf967d681cbd8bffd3f4cb581ed4e5ffa72e0864e"),),
        "mm-sans-OFL.txt",
    ),
    WARP: (
        (
            ("mm-warp-regular", "400", "normal", "035042b467e6c138666b2e6b3b3a38eeb8d6dc3602ac4354f1e335e425101481"),
            ("mm-warp-italic", "400", "italic", "4eb9d3abbff429bfc6130fb82790876e8416fe65bab69f11e2d7c35d693d6d53"),
        ),
        "mm-warp-OFL.txt",
    ),
}
# The word spacing of reading text, per text font: Sans has a narrow word space.
WORD_SPACING = {WEFT: "normal", SANS: "0.05em", WARP: "normal"}
# Fallbacks in a font stack: CSS generic families only. A stack names no font that is not machine-made.
GENERIC_FAMILIES = {"system-ui", "ui-monospace", "monospace", "serif", "sans-serif"}
# One type scale for the three houses: base size and house-line size in px, and the line height of the body.
SIZE, LINE_SIZE, LEADING = 16, 24, "1.55"
# Public sites that a licence text names. Only the licences may name them.
LICENCE_URLS = {
    "fonts/mm-weft-OFL.txt": ("github.com/machine-made/type",),
    "fonts/mm-sans-OFL.txt": ("github.com/machine-made/type", "github.com/tokotype/PlusJakartaSans"),
    "fonts/mm-warp-OFL.txt": ("github.com/machine-made/type",),
}
# The top bar: the three sites, then the type site. The footer reads the three sites.
BAR_NAMES = ("machine-made", "openfluids", "BoringQuantSystems", "type")
TYPE_URL = "https://machine-made.github.io/type/"
# The tags that set bold or italic by themselves. The page uses none: it has no bold and no italic face in use.
FAUX_TAGS = ("b", "strong", "i", "em", "cite", "dfn")
BANNER_SIZE = (1408, 469)
PLATE_SIZE = (704, 235)
MAX_IMAGE_BYTES = 400_000
# The one place that holds a non-ASCII character: the footer reads this line.
BAR_TEXT = "machine-made · openfluids · BoringQuantSystems"
BASE_FILES = {"index.html", "style.css", "mark.svg", "llms.txt", "img/banner.jpg"}
# The one gradient the page uses: it fades the top and bottom edges of the banner into the ground.
MASK = "mask-image: linear-gradient(transparent, #000 10%, #000 90%, transparent);"
GRID = "repeat(auto-fill, minmax(min(100%, 240px), 1fr))"
FILE_NAME = re.compile(r"[a-z0-9][a-z0-9._-]*")
FORBIDDEN = re.compile(
    r"[$€£]\s?[0-9]|\b(?:usd|chf|eur)\s?[0-9]|[0-9]\s?(?:usd|chf|eur)\b"
    r"|tokens|punchcard|night-shift|nexus",
    re.I,
)
VOID = {"meta", "link", "img", "br", "hr", "input", "source", "track", "area", "base", "col", "embed", "wbr"}
GITHUB_URL = r"https://github\.com"
GITHUB = re.compile(r"github\.com/[\w.-]+(?:/[\w.-]+)*", re.I)
RS_NAME = re.compile(r"(?<![\w-])[a-z0-9][a-z0-9._-]*-rs(?![\w-])", re.I)
MAX_WORDS = 25
# Tags that run code or load a resource. The page needs none of them.
FORBIDDEN_TAGS = (
    "script", "iframe", "object", "embed", "form", "input", "button", "audio", "video", "source", "track",
    "base",
)
ALLOWED_ATTRS = {
    "lang", "charset", "name", "content", "rel", "href", "type", "crossorigin", "as", "class", "id",
    "src", "width", "height", "alt", "loading", "aria-labelledby", "property",
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

failures: list[str] = []


def fail(rule: str, message: str) -> None:
    line = f"FAIL {rule}: {message}"
    if line not in failures:
        failures.append(line)


def site_title(name: str | None) -> str | None:
    """The name as people read it: site.json title (the name with capitals) when set, else the name."""
    if not name:
        return None
    try:
        title = json.loads((ROOT / "site.json").read_text(encoding="utf-8")).get("title", name)
    except (OSError, ValueError, AttributeError):
        return name
    if not isinstance(title, str) or title.lower() != name:
        fail("site", "site.json title must be the name with capitals only")
        return name
    return title


def site_name() -> str | None:
    """The site name from site.json, under the same file-name rule as build.py. None if unusable."""
    try:
        name = json.loads((ROOT / "site.json").read_text(encoding="utf-8"))["name"]
    except (OSError, ValueError, KeyError, TypeError):
        fail("site", "site.json has no readable name")
        return None
    if not isinstance(name, str) or not FILE_NAME.fullmatch(name) or ".." in name:
        fail("site", "site.json name is not a safe file name")
        return None
    return name


def repos_of(groups: tuple[tuple[str, tuple[str, ...]], ...] | None = None) -> list[str]:
    """Every 'owner/repo' of the public list, in page order."""
    return [full for _, fulls in (GROUPS if groups is None else groups) for full in fulls]


def families() -> list[str]:
    """The font families the house loads: Weft, then its own text face when that is not Weft."""
    return [WEFT] + ([THEME["font"]] if THEME.get("font") not in (None, WEFT) else [])


def font_files() -> set[str]:
    return {
        f"fonts/{name}" for fam in families() if fam in FONT_SPECS
        for name in (*(f"{stem}.woff2" for stem, _, _, _ in FONT_SPECS[fam][0]), FONT_SPECS[fam][1])
    }


def text_stem() -> str:
    """The file stem of the regular face of the house's text font: the main text font, which the page preloads."""
    return FONT_SPECS[THEME["font"]][0][0][0]


Attrs = dict[str, str | None]


class Page(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[str] = []
        self.ids: list[str] = []
        self.links: list[Attrs] = []
        self.imgs: list[Attrs] = []
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
        if tag == "img":
            self.imgs.append(a)
            if self.heading is not None:
                self.heading[1] += a.get("alt") or ""
        if tag in ("h1", "h2", "h3"):
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
        if tag in ("h1", "h2", "h3") and self.heading:
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


def luminance(hexcolour: str) -> float:
    h = hexcolour.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    channels = []
    for i in (0, 2, 4):
        c = int(h[i : i + 2], 16) / 255
        channels.append(c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4)
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


def section_titles() -> list[str]:
    """The h2 headings in page order: the groups."""
    return [title for title, _ in GROUPS]


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


def check_files() -> None:
    wanted = BASE_FILES | font_files() | {f"img/{full.split('/')[1]}.jpg" for full in repos_of()}
    wanted |= {f"{folder}/index.html" for folder in REDIRECTS}
    present = {p.relative_to(DOCS).as_posix() for p in DOCS.rglob("*") if p.is_file()}
    for extra in sorted(present - wanted):
        fail("files", f"docs/{extra} is not part of the one-page site")
    for missing in sorted(wanted - present):
        fail("files", f"docs/{missing} is missing; run python3 build.py")


def local_target(href: str) -> Path | None:
    """The file a local link names, or None when it names nothing or leaves docs/."""
    path = unquote(href.split("#", 1)[0].split("?", 1)[0])
    if not path:
        return None
    root = DOCS.resolve()
    target = (DOCS / path).resolve()
    return target if root in target.parents else None


def allowed_https() -> set[str]:
    """Every https address that the page may link: the three sites, the project sites, the repositories."""
    return {u for _, u in SITES} | set(SITE_LINKS.values()) | {f"https://github.com/{full}" for full in repos_of()}


def check_html(page: Page, html_text: str, name: str | None) -> None:
    for problem in page.problems:
        fail("parse", problem)
    if page.stack:
        fail("parse", f"unclosed tags: {', '.join(page.stack)}")
    if not html_text.lstrip().lower().startswith("<!doctype html>"):
        fail("parse", "no doctype")
    if len(page.ids) != len(set(page.ids)):
        fail("parse", "an id is used twice")
    if not re.search(r'<html lang="[a-z-]+"', html_text):
        fail("a11y", "the html element has no lang")
    if not re.search(r'<meta name="viewport" content="width=device-width, initial-scale=1">', html_text):
        fail("responsive", "no viewport meta")
    if '<meta name="color-scheme" content="dark">' not in html_text:
        fail("dark", "the page is dark only: the color-scheme meta must be dark")
    if f'<meta name="theme-color" content="{THEME.get("ground", "")}">' not in html_text:
        fail("dark", "the theme-color meta must be the ground colour of the house")
    if re.search(r"<title>[^<]+</title>", html_text) is None:
        fail("a11y", "no title")
    for problem in page.unknown_attrs:
        fail("attrs", f"{problem}; the page uses no other attributes")
    for css in page.styles:
        check_refs(css, "index.html", "css")
        check_colour_names(css, "index.html")
        if colours_of(css, "index.html"):
            fail("accent", "index.html has a style block with a colour of its own; colours belong in style.css")
    for forbidden in FORBIDDEN_TAGS:
        if forbidden in page.tags:
            fail("no-js", f"<{forbidden}> is not allowed on a page that needs no script")
    for tag in ("header", "nav", "main", "footer", "h1", "h2", "ul"):
        if tag not in page.tags:
            fail("semantic", f"no <{tag}>")
    if page.tags.count("h1") != 1:
        fail("semantic", "the page needs exactly one h1")
    if page.tags.count("main") != 1:
        fail("semantic", "the page needs exactly one main")
    shown = site_title(name)
    if shown and ("h1", shown) not in page.headings:
        fail("content", f"the h1 must be the site name, {shown}")
    check_head(html_text, shown)
    for faux in FAUX_TAGS:
        if faux in page.tags:
            fail("fonts", f"<{faux}> sets bold or italic by itself; the page uses no bold and no italic")
    if html_text.count("aria-current=") != 1:
        fail("a11y", "exactly one entry of the top bar must carry aria-current")
    first: Attrs = page.first_link or {}
    if first.get("href") != "#main" or "main" not in page.ids:
        fail("a11y", "the first link must be a skip link to #main")
    for img in page.imgs:
        # The banner carries the org name. A plate image is decorative (alt=""): its link names it.
        banner = img.get("class") == "banner"
        if "alt" not in img or (banner and not (img.get("alt") or "").strip()):
            fail("a11y", f"image {img.get('src')} has no alt attribute, or the banner has empty alt text")
        if not banner and img.get("alt") != "":
            fail("a11y", f"image {img.get('src')} is a plate image: its alt text is empty and its link carries the name")
        if not (img.get("width") and img.get("height")):
            fail("responsive", f"image {img.get('src')} has no width and height")
        target = local_target(img.get("src") or "")
        if target is None or not target.is_file():
            fail("links", f"image {img.get('src')} does not resolve inside docs/")
    allowed = allowed_https()
    for link in page.links:
        href = link.get("href") or ""
        parts = urlsplit(href)
        if link.get("class") == "pic" and (link.get("aria-label") or "").strip() != href.rstrip("/").rsplit("/", 1)[-1]:
            fail("a11y", f"the image link to {href} needs aria-label with the repository name")
        if href.startswith("#"):
            if href[1:] not in page.ids:
                fail("links", f"{href} points to no id")
        elif parts.scheme or parts.netloc:
            if parts.scheme.lower() != "https":
                fail("links", f"{href} is not an https link")
            elif link.get("tag") == "link":
                fail("links", f"{href} is an external resource; the page loads only files in docs/")
            elif href not in allowed:
                fail("links", f"{href} is not in the public list")
        else:
            target = local_target(href)
            if target is None or not target.is_file():
                fail("links", f"{href} does not resolve inside docs/")


def meta_values(html_text: str, attr: str, key: str) -> list[str]:
    return [html.unescape(v) for v in re.findall(rf'<meta {attr}="{re.escape(key)}" content="([^"]*)">', html_text)]


def check_head(html_text: str, shown: str | None) -> None:
    """The head: title, description, favicon, and the social preview that uses the org banner."""
    title = re.search(r"<title>([^<]+)</title>", html_text)
    if shown and (not title or html.unescape(title.group(1)) != shown):
        fail("head", f"the title must be the site name, {shown}")
    if meta_values(html_text, "name", "description") != [LINE]:
        fail("head", "the description meta must be the org line, word for word")
    if '<link rel="icon" href="mark.svg" type="image/svg+xml">' not in html_text:
        fail("head", "the page needs its favicon: <link rel=\"icon\" href=\"mark.svg\" type=\"image/svg+xml\">")
    home = next((u for n, u in SITES if n == SELF), "")
    expected = {
        "og:type": "website", "og:title": shown or "", "og:description": LINE, "og:url": home,
        "og:image": f"{home}img/banner.jpg", "og:image:width": str(BANNER_SIZE[0]),
        "og:image:height": str(BANNER_SIZE[1]), "og:image:alt": shown or "",
    }
    for key, value in expected.items():
        if meta_values(html_text, "property", key) != [value]:
            fail("head", f"the social preview meta {key} must be {value!r}; og:image is the org banner")
    if meta_values(html_text, "name", "twitter:card") != ["summary_large_image"]:
        fail("head", "the twitter:card meta must be summary_large_image")


def check_refs(text: str, where: str, kind: CssKind) -> None:
    """url() and @import targets: css may load only local files; svg only #fragments.

    Every other CSS image function is refused, and so is a backslash, which can spell any name."""
    if "\\" in text:
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
            local = local_target(target)
            if local is None or not local.is_file():
                fail("links", f"{where} refers to {target[:50]!r}, which is not a file inside docs/")


LOCAL_WOFF2 = re.compile(r"\s*url\(\s*(['\"]?)fonts/([a-z0-9-]+)\.woff2\1\s*\)\s*format\(\s*(['\"])woff2\3\s*\)\s*")


def check_fonts(html_text: str) -> None:
    """The fonts are files in docs/fonts/, all machine-made: one @font-face per face of each family of the
    house, each with a local woff2, font-display: swap, the right weight range and style; each file is the
    woff2 of the 0.2.0 release; the page preloads the main text font and no other file."""
    check_font_faces()
    check_font_files(html_text)


def check_font_faces() -> None:
    """The @font-face rules of style.css: only machine-made families, each face once, with its own file."""
    css = re.sub(r"/\*.*?\*/", " ", read("style.css"), flags=re.S)
    faces = re.findall(r"@font-face\s*\{([^}]*)\}", css, re.I)
    wanted = families()
    seen: set[tuple[str, str]] = set()
    for face in faces:
        family = re.search(r"font-family\s*:\s*(['\"])(.*?)\1", face)
        src = re.search(r"(?<![\w-])src\s*:\s*([^;]*)", face)
        source = re.fullmatch(LOCAL_WOFF2, src.group(1)) if src else None
        name = family.group(2) if family else "?"
        if name not in wanted:
            fail("fonts", f"style.css declares the font family {name!r}; this house uses only the machine-made fonts {', '.join(wanted)}")
            continue
        by_stem = {stem: (weight, style) for stem, weight, style, _ in FONT_SPECS[name][0]}
        stem = source.group(2) if source else ""
        if stem not in by_stem:
            fail("fonts", f"the @font-face of {name} must load only its machine-made files: {', '.join(by_stem)}")
            continue
        seen.add((name, stem))
        weight, style = by_stem[stem]
        if not re.search(r"font-display\s*:\s*swap\b", face):
            fail("fonts", f"the @font-face of {name} needs font-display: swap")
        if not re.search(rf"font-weight\s*:\s*{weight}\s*(;|$)", face):
            fail("fonts", f"the @font-face of {name} ({stem}) must have font-weight {weight}")
        if not re.search(rf"font-style\s*:\s*{style}\s*(;|$)", face):
            fail("fonts", f"the @font-face of {name} ({stem}) must have font-style {style}")
    for name in wanted:
        for stem, _, _, _ in FONT_SPECS[name][0]:
            if (name, stem) not in seen:
                fail("fonts", f"style.css has no @font-face for {name} ({stem})")


def check_font_files(html_text: str) -> None:
    """The font files in docs/fonts/ are the 0.2.0 release files; the page preloads the main text font only."""
    wanted = families()
    pinned = {f"fonts/{stem}.woff2": digest for name in wanted for stem, _, _, digest in FONT_SPECS[name][0]}
    for rel in sorted(pinned):
        path = DOCS / rel
        if not path.is_file():
            continue
        data = path.read_bytes()
        if data[:4] != b"wOF2":
            fail("fonts", f"docs/{rel} is not a woff2 font")
        elif hashlib.sha256(data).hexdigest() != pinned[rel]:
            fail("fonts", f"docs/{rel} is not the machine-made font file of version 0.2.0")
    preloads = re.findall(r"<link\b[^>]*\brel=\"preload\"[^>]*>", html_text)
    if not preloads:
        fail("fonts", "the page preloads no font; preload the main text font")
    hrefs = []
    for tag in preloads:
        href = re.search(r'\bhref="([^"]*)"', tag)
        target = href.group(1) if href else ""
        hrefs.append(target)
        if target not in {f"fonts/{stem}.woff2" for name in wanted for stem, _, _, _ in FONT_SPECS[name][0]}:
            fail("fonts", f"the page preloads {target[:50]!r}, which is not a font of the house")
        if 'as="font"' not in tag or 'type="font/woff2"' not in tag or not re.search(r"\bcrossorigin\b", tag):
            fail("fonts", f"the preload of {target[:50]!r} needs as=\"font\", type=\"font/woff2\" and crossorigin")
    if f"fonts/{text_stem()}.woff2" not in hrefs:
        fail("fonts", f"the page must preload the main text font, fonts/{text_stem()}.woff2")


def family_names(stack: str) -> list[str]:
    return [part.strip().strip("'\"") for part in stack.split(",") if part.strip()]


def check_font_use(css: str, found: dict[str, str]) -> None:
    """Every font family a rule names is machine-made or generic; no rule sets bold or italic that the page
    does not load as a real face."""
    for key in ("font", "mono"):
        for fam in family_names(found.get(key, "")):
            if fam not in FONT_SPECS and fam not in GENERIC_FAMILIES:
                fail("fonts", f"--{key} names the font family {fam!r}; only machine-made fonts and generic families are allowed")
    italic_ok = any(face[2] == "italic" for face in FONT_SPECS[THEME["font"]][0])
    for _, selector, decls in css_rules(css):
        if selector.startswith("@font-face") or ":root" in selector:
            continue
        for prop in ("font-family", "font"):
            if prop in decls and not re.search(r"var\(\s*--(?:font|mono)\s*\)", decls[prop]):
                fail("fonts", f"{selector[:40]} sets {prop}: {decls[prop][:30]!r}; use var(--font) or var(--mono)")
        tokens = decls.get("font", "").split()
        weight = decls.get("font-weight") or next((t for t in tokens if re.fullmatch(r"\d{3}|bold|bolder|lighter", t)), "400")
        if weight not in ("400", "normal", "inherit"):
            fail("fonts", f"{selector[:40]} sets font-weight {weight}; the page loads no bold face, so it sets none")
        style = decls.get("font-style") or next((t for t in tokens if t in ("italic", "oblique")), "normal")
        if style not in ("normal", "inherit") and not (italic_ok and style == "italic"):
            fail("fonts", f"{selector[:40]} sets font-style {style}; this house loads no italic face")
    labels = [d for _, s, d in css_rules(css) if ".lbl" in s.split(",")[0] and "font" in d]
    if not labels or not re.search(r"(?<![\w.-])400(?![\w.-])", labels[0]["font"]):
        fail("fonts", "the group label (h2) must set font-weight 400, or the browser draws it bold")


def check_scale_and_touch(css: str, found: dict[str, str]) -> None:
    """One type scale on the three houses, and the small links that a touch screen needs."""
    for key, px in (("fs", SIZE), ("ls", LINE_SIZE)):
        if found.get(key, "").lower() != f"{px / 16:g}rem":
            fail("scale", f"--{key} is {found.get(key) or 'missing'}; the three houses share {px / 16:g}rem ({px} px)")
    if found.get("ws") != WORD_SPACING[THEME["font"]] or re.sub(r"\s+", " ", css).count("word-spacing: var(--ws)") != 3:
        fail("scale", f"--ws must be {WORD_SPACING[THEME['font']]} for {THEME['font']}, and reading text must use word-spacing: var(--ws)")
    body = [d for c, s, d in css_rules(css) if s == "body" and not c]
    if not body or f"/ {LEADING} " not in body[0].get("font", ""):
        fail("scale", f"body must set the line height {LEADING}, the same on the three houses")
    rules = list(css_rules(css))
    link = [d for c, s, d in rules if s == ".ds a" and not c]
    if not link or "underline" not in link[0].get("text-decoration", ""):
        fail("touch", "the link after a description must be underlined always, not only on hover")
    for selector in (".ds a", ".bar a, .bar span"):
        narrow = [d for c, s, d in rules if s == selector and any("(max-width:720px)" in cond for cond in c)]
        if not narrow or narrow[0].get("min-height") != "44px":
            fail("touch", f"{selector} must be at least 44px high below 720px")
    hover = [d for c, s, d in rules if s == ".pic:hover img" and any("(hover:hover)" in cond for cond in c)]
    if not any("outline-color" in d for d in hover):
        fail("hover", "a plate image must show its hover state without motion: .pic:hover img sets outline-color")


def sentences_of(paragraph: str) -> list[str]:
    return re.split(r"(?<=[.!?])\s+", paragraph.strip())


def check_prose(paragraphs: list[str], where: str) -> None:
    for paragraph in paragraphs:
        for sentence in sentences_of(paragraph):
            if len(sentence.split()) > MAX_WORDS:
                fail("voice", f"{where}: a sentence has more than {MAX_WORDS} words: {sentence[:40]}")


def plate_html(full: str, line: str | None = None) -> re.Pattern[str]:
    """The markup of one plate: the repository banner as a link to the repository, named by aria-label, with an
    empty alt text, and one line under it. A project with a site or documentation has a small link after the line."""
    repo = full.split("/")[1]
    url = re.escape(f"https://github.com/{full}")
    img = (
        rf'<img src="img/{re.escape(repo)}\.jpg" width="{PLATE_SIZE[0]}" height="{PLATE_SIZE[1]}" '
        rf'loading="lazy" alt="">'
    )
    text = r"(?P<line>\S(?:[^<]*\S)?)" if line is None else re.escape(line)
    more = ""
    if full in SITE_LINKS:
        label = SITE_LABELS.get(full, "site")
        more = rf' <a class="nm" href="{re.escape(SITE_LINKS[full])}" aria-label="{re.escape(repo)} {label}">{label}</a>'
    return re.compile(
        rf'<li class="plate"><a class="pic" href="{url}" aria-label="{re.escape(repo)}">{img}</a>'
        rf'<span class="ds">{text}{more}</span></li>'
    )


def check_content(page: Page, html_text: str) -> str:
    text = " ".join(" ".join(page.text).split())
    visible = " ".join([text, *page.values, *page.hidden, *page.tags])
    expected_bar = "\n".join(
        f'<span aria-current="page">{html.escape(n)}</span>' if n == SELF else f'<a href="{html.escape(u)}">{html.escape(n)}</a>'
        for n, u in SITES
    )
    if f'<nav class="bar" aria-label="Sites">\n{expected_bar}\n</nav>' not in html_text:
        fail("content", f"the top bar must read {' · '.join(n for n, _ in SITES)}: {SELF} marked with aria-current and not linked, type last")
    if not re.search(r'<h1><img class="banner" src="img/banner\.jpg" width="1408" height="469" alt="[^"]+"></h1>', html_text):
        fail("content", "the h1 must hold the banner, img/banner.jpg at 1408 by 469, with the name as alt text")
    expected_duo = (
        f'<div class="duo">\n<p class="line">{html.escape(LINE)}</p>\n<p class="blurb">{html.escape(BLURB)}</p>\n</div>'
    )
    if expected_duo not in html_text:
        fail("content", "the org line and the paragraph on the name must sit side by side, word for word as allow.json has them")
    if f"<footer class=\"wrap\">\n<p>{BAR_TEXT.replace(chr(0xB7), '&middot;')}</p>\n</footer>" not in html_text:
        fail("content", f'the footer must read "{BAR_TEXT}"')
    order = [html_text.find(m) for m in ('class="bar"', 'class="banner"', 'class="duo"', 'class="grid"', "<footer")]
    if -1 in order or order != sorted(order):
        fail("content", "the page order is: top bar, banner, line and name, projects, footer")
    hrefs = [link.get("href") or "" for link in page.links if link.get("tag") != "link"]
    repo_links = [h for h in hrefs if h.startswith("https://github.com/")]
    plain_repos = [f"https://github.com/{full}" for full in repos_of()]
    if sorted(repo_links) != sorted(plain_repos):
        fail("projects", "the project links are not exactly the public repositories")
    # Another site is linked once, in the top bar; the current site is not linked. A project site is linked once more,
    # after the description of its plate.
    want = Counter(u for n, u in SITES if n != SELF) + Counter(SITE_LINKS.values())
    for url in {u for _, u in SITES} | set(SITE_LINKS.values()):
        if hrefs.count(url) != want[url]:
            fail("links", f"{url} must be linked {want[url]} time(s): in the top bar when it is another site, after the description of its plate when it is a project site")
    if any(kind == "h3" for kind, _ in page.headings):
        fail("projects", "the page has headings below h2; each project list is a plain list")
    if [h for kind, h in page.headings if kind == "h2"] != section_titles():
        fail("projects", "the h2 headings must be the group titles, in order")
    sections = re.findall(
        r'<section aria-labelledby="(g-[\w-]+)">\n<h2 class="lbl" id="(g-[\w-]+)">([^<]*)</h2>\n<ul class="grid">\n(.*?)\n</ul>\n</section>',
        html_text,
        re.S,
    )
    if len(sections) != len(GROUPS) or html_text.count("<section") != len(GROUPS):
        fail("projects", "the projects are not in the groups of the public list")
        return visible
    lines: list[str] = []
    for (label, ident, title, body), (want_title, fulls) in zip(sections, GROUPS, strict=True):
        if html.unescape(title) != want_title or label != ident or ident != f"g-{slug(want_title)}":
            fail("projects", f"the group {want_title} must carry its title and its id g-{slug(want_title)}")
        plates = body.split("\n")
        if len(plates) != len(fulls):
            fail("projects", f"the group {want_title} must hold exactly its projects, in order")
            continue
        for full, plate in zip(fulls, plates, strict=True):
            hit = plate_html(full).fullmatch(plate)
            if not hit:
                fail("projects", f"the plate of {full} is not the banner link, named by aria-label with empty alt text, and one line")
            else:
                lines.append(html.unescape(hit.group("line")))
                if re.match(rf"{re.escape(full.split('/')[1])}(?![\w-])", lines[-1], re.I):
                    fail("projects", f"the line of {full} starts with the repository name, which the banner already shows")
    if html_text.count('<a class="nm"') != len(SITE_LINKS):
        fail("projects", "the page has a site link that the allowed list does not name")
    if html_text.count('class="nm"') != len(SITE_LINKS):
        fail("projects", "the repository name is not repeated under a plate: only the site and docs links carry class nm")
    check_prose(page.paragraphs + lines, "index.html")
    return visible


def emitted(visible: str) -> Iterator[tuple[str, str]]:
    """Every emitted text file as (name, text). The page counts as what a reader or a crawler gets."""
    yield "index.html", visible
    for path in sorted(DOCS.rglob("*")):
        name = path.relative_to(DOCS).as_posix()
        if path.is_file() and name != "index.html" and path.suffix not in (".woff2", ".jpg"):
            yield name, path.read_text(encoding="utf-8", errors="replace")


def decoded(source: str) -> str:
    """source with every character reference decoded, however deeply it is nested."""
    while (plain := html.unescape(source)) != source:
        source = plain
    return source


def check_leaks(visible: str, deny: list[str]) -> None:
    forwards = {f"{folder}/index.html": url.split("//", 1)[1] for folder, url in REDIRECTS.items()}
    for name, raw in emitted(visible):
        # Files are plain ASCII. The one character beyond ASCII that a reader sees is the dot of the footer
        # line, which the file spells as &middot;.
        shown = raw.replace(BAR_TEXT, "") if name == "index.html" else raw
        if not shown.isascii():
            fail("voice", f"docs/{name} has characters that are not plain ASCII")
        if name != "index.html" and not raw.isascii():
            continue
        source = raw + "\n" + decoded(raw)
        for match in GITHUB.findall(source):
            ok = match == forwards.get(name) or match in LICENCE_URLS.get(name, ()) or any(
                match == f"github.com/{full}" for full in repos_of()
            )
            if not ok:
                fail("private", f"{match} is not in the public list ({name})")
        for repo in RS_NAME.findall(source):
            if repo.lower() not in {full.split("/")[1].lower() for full in repos_of()}:
                fail("private", f"{repo} looks like a repository that is not in the public list ({name})")
        for word in deny:
            if re.search(rf"(?<![\w]){re.escape(word)}(?![\w])", source, re.I):
                fail("private", f"a private name appears in docs/{name} ({len(word)} letters)")
    raw_page = (DOCS / "index.html").read_text(encoding="utf-8", errors="replace") if (DOCS / "index.html").is_file() else ""
    if not raw_page.isascii():
        fail("voice", "docs/index.html has characters that are not plain ASCII; spell the dot as &middot;")
    for path in DOCS.rglob("*"):
        for word in deny:
            if path.is_file() and re.search(re.escape(word), path.name, re.I):
                fail("private", f"a private name is part of the file name {path.name}")


def check_forbidden() -> None:
    for path in sorted(DOCS.rglob("*")):
        if path.is_file() and path.suffix not in (".woff2", ".jpg"):
            hit = FORBIDDEN.search(path.read_text(encoding="utf-8", errors="replace"))
            if hit:
                fail("forbidden", f"docs/{path.relative_to(DOCS).as_posix()} contains {hit.group(0)!r}")


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


def check_images() -> None:
    """Each image is a real JPEG of the size that the page declares, and no larger than a plate needs."""
    for path in sorted((DOCS / "img").glob("*")) if (DOCS / "img").is_dir() else []:
        data = path.read_bytes()
        size = jpeg_size(data)
        want = BANNER_SIZE if path.name == "banner.jpg" else PLATE_SIZE
        if size is None:
            fail("images", f"docs/img/{path.name} is not a JPEG")
        elif not data.endswith(b"\xff\xd9"):
            fail("images", f"docs/img/{path.name} is cut short: it has no end-of-image marker")
        elif size != want:
            fail("images", f"docs/img/{path.name} is {size[0]} x {size[1]}; it must be {want[0]} x {want[1]}")
        if len(data) > MAX_IMAGE_BYTES:
            fail("images", f"docs/img/{path.name} is {len(data)} bytes; the limit is {MAX_IMAGE_BYTES}")


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
        else:
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
    focus = [d for _, s, d in css_rules(css) if s == "a:focus-visible"]
    if not focus or "var(--accent)" not in focus[0].get("outline", ""):
        fail("focus", "a:focus-visible must draw an outline in the accent colour")


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
        return tokens["bg"]
    if v in ("inherit", "currentcolor"):
        return None
    fail("contrast", f"style.css sets {prop}: {value[:30]!r}; use a palette token (var(--name)), black, white or transparent")
    return None


def check_text_colours(css: str, tokens: dict[str, str]) -> None:
    """Measure the colours that text uses: each color and background in style.css, against its partner.

    A rule with only color is measured on --bg. A rule with only a background is measured with --fg.
    A rule that draws an empty box (content: "") sets no text and is not measured."""
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
            top, ground = fg_hex or tokens["fg"], bg_hex or tokens["bg"]
            need = 3.0 if top == tokens["accent"] else 4.5
            ratio = contrast(top, ground)
            if ratio < need:
                fail("contrast", f"style.css has text {top} on {ground} at {ratio:.2f}, below {need}")


def check_css() -> None:
    css = read("style.css")
    if not css:
        return
    root = re.search(r":root\{([^}]*)\}", css)
    if not root:
        fail("dark", "style.css needs the :root block of the house colours, fonts and sizes")
        return
    found = dict(re.findall(r"--([a-z-]+):\s*([^;]*);", root.group(1)))
    tokens = {k: found.get(k, "").lower() for k in ("bg", "fg", "muted", "accent", "edge")}
    for key, theme_key in (("bg", "ground"), ("fg", "text"), ("muted", "muted"), ("accent", "accent")):
        if tokens[key] != THEME.get(theme_key):
            fail("palette", f"--{key} is {tokens[key] or 'missing'}; allow.json gives {THEME.get(theme_key)}")
    if not re.fullmatch(r"#[0-9a-f]{6}", tokens["edge"]):
        fail("palette", "--edge must be #rrggbb")
        return
    family = THEME.get("font", "")
    if not found.get("font", "").startswith(f'"{family}"') or not found.get("mono", "").startswith(f'"{WEFT}"'):
        fail("fonts", f"--font must start with {family!r} and --mono with {WEFT!r}")
    check_font_use(css, found)
    check_scale_and_touch(css, found)
    for key, need in (("fg", 4.5), ("muted", 4.5), ("accent", 3.0)):
        ratio = contrast(tokens[key], tokens["bg"])
        if ratio < need:
            fail("contrast", f"--{key} on --bg is {ratio:.2f}, below {need}")
    check_refs(css, "style.css", "css")
    check_colour_names(css, "style.css")
    if "prefers-color-scheme" in css or not re.search(r"color-scheme:\s*dark\b", css):
        fail("dark", "the page is dark only: style.css sets color-scheme: dark and has no light scheme")
    # The one gradient is the mask of the banner. It is cut out before the colour check, which refuses any other.
    flat = re.sub(r"\s+", " ", css)
    masks = flat.count(MASK)
    if masks != 1:
        fail("colour", f"style.css must hold the banner mask exactly once: {MASK}")
    colours = colours_of(flat.replace(MASK, ""), "style.css")
    if colours - set(tokens.values()) - {"#000000"}:
        fail("accent", f"style.css has colours outside the palette: {sorted(colours - set(tokens.values()) - {'#000000'})}")
    if "var(--accent)" not in css:
        fail("accent", "style.css never uses the accent colour")
    check_text_colours(css, tokens)
    check_behaviour(css)
    if f"grid-template-columns: {GRID}" not in flat:
        fail("responsive", f"the plate grid must be grid-template-columns: {GRID}")
    if not re.search(r"--max:\s*1200px", css):
        fail("responsive", "the content width must be --max: 1200px")
    if re.search(r"\bnowrap\b|(?<![-\w])width:\s*\d{3,}px", css):
        fail("responsive", "style.css forces a width that can scroll")


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
            rule = "colour" if local in ("linearGradient", "radialGradient", "stop") else "no-js"
            fail(rule, f"{where} has <{local}>, which this site does not use")
        for key, value in el.attrib.items():
            name = key.rsplit("}", 1)[-1]
            if re.fullmatch(r"on[a-z]+", name.lower()):
                fail("no-js", f"{where} has an event handler ({name})")
            if name == "href" and not value.startswith("#"):
                fail("links", f"{where} has an href that is not an id of its own")
            check_refs(value, where, "svg")


def check_mark() -> None:
    """The favicon, mark.svg: a valid, script-free svg whose only accent is the red of the mark."""
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


def check_llms(name: str | None) -> None:
    text = read("llms.txt")
    if not text:
        return
    links = re.findall(r"\]\((https://[^)]+)\)", text)
    expected = [f"https://github.com/{full}" for full in repos_of()] + [u for _, u in SITES] + list(SITE_LINKS.values())
    if sorted(links) != sorted(expected):
        fail("llms", "llms.txt must list exactly the public repositories, the project sites and the three sites")
    shown = site_title(name)
    if shown and not text.startswith(f"# {shown}\n\n> {LINE}\n\n{BLURB}\n\n## "):
        fail("llms", "llms.txt must start with the name, the line and the paragraph on the name")
    sites = "".join(f"- [{n}]({u})\n" for n, u in SITES)
    if not text.endswith(f"## Sites\n\n{sites}"):
        fail("llms", "llms.txt must end with the Sites section: the three sites")
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


def run_checks(deny: list[str]) -> list[str]:
    del failures[:]
    name = site_name()
    check_files()
    check_redirects()
    html_text = read("index.html")
    if html_text:
        page = Page()
        page.feed(html_text)
        page.close()
        check_html(page, html_text, name)
        visible = check_content(page, html_text)
        check_leaks(visible, deny)
        check_fonts(html_text)
    check_forbidden()
    check_images()
    check_css()
    check_mark()
    check_llms(name)
    return list(failures)


LONG = " ".join(["word"] * 30) + "."
STYLE_LINK = '<link rel="stylesheet" href="style.css">'


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


def site_copy(root: Path, changes: dict[str, object]) -> subprocess.CompletedProcess[bytes]:
    """Build a copy of the generator in root, with these keys of site.json changed."""
    (root / "src").mkdir(parents=True)
    for rel in ("build.py", "card.py", "src/style.css"):
        shutil.copy(ROOT / rel, root / rel)
    shutil.copytree(ROOT / "fonts", root / "fonts")
    shutil.copytree(ROOT / "img", root / "img")
    data = json.loads((ROOT / "site.json").read_text(encoding="utf-8"))
    old = data["name"]
    data.update(changes)
    new = changes.get("name")
    if isinstance(new, str) and FILE_NAME.fullmatch(new) and ".." not in new:
        # A renamed site keeps the banner of the site it was copied from, under the new name.
        shutil.copy(ROOT / "img" / "org" / f"{old}.jpg", root / "img" / "org" / f"{new}.jpg")
        if "title" not in changes:
            data.pop("title", None)
    (root / "site.json").write_text(json.dumps(data), encoding="utf-8")
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    return subprocess.run([sys.executable, str(root / "build.py")], capture_output=True, env=env)


def build_rejects(changes: dict[str, object]) -> bool:
    """True when build.py exits 2 on a site.json with these changes and writes no docs/ outside the copy."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "site"
        done = site_copy(root, changes)
        outside = [p.name for p in Path(tmp).rglob("*.html") if root / "docs" not in p.parents]
        return done.returncode == 2 and not outside


def build_needs(rel: str) -> bool:
    """True when build.py exits 2 without this file of the generator and writes no docs/."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "site"
        site_copy(root, {})
        shutil.rmtree(root / "docs")
        target = root / rel
        target.unlink()
        env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
        done = subprocess.run([sys.executable, str(root / "build.py")], capture_output=True, env=env)
        return done.returncode == 2 and not (root / "docs").exists()


def renamed_site_passes(new_name: str) -> bool:
    """True when a site built under another name passes every check."""
    global ROOT, DOCS
    real_root, real_docs = ROOT, DOCS
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "site"
        if site_copy(root, {"name": new_name}).returncode != 0:
            return False
        ROOT, DOCS = root, root / "docs"
        try:
            return not run_checks([])
        finally:
            ROOT, DOCS = real_root, real_docs


def cli_fails(args: list[str], prefix: str) -> bool:
    """True when check_site.py exits 2 with exactly one line that starts with prefix."""
    env = {k: v for k, v in os.environ.items() if k != "MM_DENY_FILE"}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    done = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), *args], capture_output=True, text=True, env=env
    )
    lines = done.stdout.splitlines()
    return done.returncode == 2 and len(lines) == 1 and lines[0].startswith(prefix) and not done.stderr


def site_links_hold() -> list[str]:
    """Build a site with one more project site link and run the checks on it: it passes, and each way
    of breaking the link fails. The checks read the link from the public list, so the list changes too."""
    global DOCS, SITE_LINKS
    real_docs, real_links = DOCS, SITE_LINKS
    full = next(f for f in repos_of() if f not in real_links)
    repo, url = full.split("/")[1], "https://machine-made.github.io/zz-site/"
    problems: list[str] = []
    data = json.loads((ROOT / "site.json").read_text(encoding="utf-8"))
    next(p for g in data["groups"] for p in g["projects"] if p["repo"] == repo)["site"] = url
    link = f' <a class="nm" href="{url}" aria-label="{repo} site">site</a>'
    breaks: list[tuple[str, Callable[[Path], object]]] = [
        ("site link missing", lambda d: edit(d, "index.html", link, "")),
        ("site link on another host", lambda d: edit(d, "index.html", url, "https://example.net/zz-site/")),
        ("site link to another path", lambda d: edit(d, "index.html", url, "https://machine-made.github.io/other/")),
        ("second site link", lambda d: edit(d, "index.html", "</ul>", f'<li><a class="nm" href="{url}">x</a></li></ul>')),
        ("site link says docs but the list says site", lambda d: edit(d, "index.html", f'aria-label="{repo} site">site</a>', f'aria-label="{repo} docs">docs</a>')),
        ("site link without its accessible name", lambda d: edit(d, "index.html", f' aria-label="{repo} site"', "")),
        ("site link on the banner", lambda d: edit(d, "index.html", f'<a class="pic" href="https://github.com/{full}" aria-label=', f'<a class="pic" href="{url}" aria-label=')),
        ("linked banner without an accessible name", lambda d: edit(d, "index.html", f'class="pic" href="https://github.com/{full}" aria-label="{repo}"', f'class="pic" href="https://github.com/{full}"')),
    ]
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "site"
        if site_copy(root, {"groups": data["groups"]}).returncode != 0:
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
                    problems.append(f"site-link fixture, {title}: got {found[:2]}")
        finally:
            DOCS, SITE_LINKS = real_docs, real_links
    return problems


Case = tuple[str, str | None, list[str], Callable[[Path], object]]


def self_test() -> None:
    global DOCS
    real = DOCS
    name = site_name()
    if not name:
        print("\n".join(failures))
        sys.exit(1)
    # Plates without a site link of their own: the cases below break their markup.
    plain = [f.split("/")[1] for f in repos_of() if f not in SITE_LINKS]
    first = plain[0]
    second = plain[1] if len(plain) > 1 else first
    nav_other = next(u for n, u in SITES if n != SELF)
    other_name = next(n for n, _ in SITES if n != SELF)
    css_first = f":root{{--bg:{THEME['ground']};"
    font_stem = text_stem()
    self_url = dict(SITES)[SELF]
    italic_ok = any(face[2] == "italic" for face in FONT_SPECS[THEME["font"]][0])

    def plate_edit(repo: str, change: Callable[[str], str]) -> Callable[[Path], object]:
        """Change the markup of one plate: change() takes the <li> of the repository and returns the new one."""
        def run(d: Path) -> None:
            text = read_index(d)
            li = next(m for m in re.findall(r'<li class="plate">.*?</li>', text) if f'aria-label="{repo}"' in m)
            edit(d, "index.html", li, change(li))

        return run

    cases: list[Case] = [
        ("private name in style.css", "private", ["zzprivate"], lambda d: edit(d, "style.css", "box-sizing", "/* zzprivate */ box-sizing")),
        ("private name in the mark svg", "private", ["zzprivate"], lambda d: edit(d, "mark.svg", "<title>", "<title>zzprivate ")),
        ("private name in an html comment", "private", ["zzprivate"], lambda d: edit(d, "index.html", "<body>", "<body><!-- zzprivate -->")),
        ("private link", "links", [], lambda d: edit(d, "index.html", f"/{first}\"", "/zzprivate\"")),
        ("private rs name in llms.txt", "private", [], lambda d: edit(d, "llms.txt", "## Sites", "zz-rs\n\n## Sites")),
        ("long project line", "voice", [], lambda d: edit(d, "index.html", '<span class="ds">', f'<span class="ds">{LONG} ')),
        ("long org line", "voice", [], lambda d: edit(d, "llms.txt", f"> {LINE}", f"> {LONG} {LINE}")),
        ("long line in llms.txt", "voice", [], lambda d: edit(d, "llms.txt", "## Sites", f"{LONG}\n\n## Sites")),
        ("alpha hex in a variable", "colour", [], lambda d: edit(d, "style.css", f"--muted:{THEME['muted']}", f"--muted:{THEME['muted']}80")),
        ("short alpha hex in a rule", "colour", [], lambda d: edit(d, "style.css", "box-sizing", "color:#fff8;box-sizing")),
        ("second accent", "accent", [], lambda d: edit(d, "style.css", "box-sizing", "color:#0000ff;box-sizing")),
        ("a hex grey outside the palette", "accent", [], lambda d: edit(d, "style.css", "box-sizing", "color:#777777;box-sizing")),
        ("accent changed in style.css", "palette", [], lambda d: edit(d, "style.css", f"--accent:{THEME['accent']}", "--accent:#123456")),
        ("ground changed in style.css", "palette", [], lambda d: edit(d, "style.css", css_first, ":root{--bg:#222222;")),
        ("light scheme comes back", "dark", [], lambda d: edit(d, "style.css", "box-sizing", "box-sizing:border-box}@media (prefers-color-scheme: light){a{margin:0")),
        ("color-scheme meta is light dark", "dark", [], lambda d: edit(d, "index.html", 'content="dark"', 'content="light dark"')),
        ("theme-color differs from the ground", "dark", [], lambda d: edit(d, "index.html", f'name="theme-color" content="{THEME["ground"]}"', 'name="theme-color" content="#ffffff"')),
        ("link leaves docs/", "links", [], lambda d: edit(d, "index.html", 'href="style.css"', 'href="../README.md"')),
        ("image leaves docs/", "links", [], lambda d: edit(d, "index.html", 'src="img/banner.jpg"', 'src="../README.md"')),
        ("icon leaves docs/", "links", [], lambda d: edit(d, "index.html", 'href="mark.svg"', 'href="../README.md"')),
        ("absolute local link", "links", [], lambda d: edit(d, "index.html", 'href="style.css"', 'href="/etc/hostname"')),
        ("protocol-relative link", "links", [], lambda d: edit(d, "index.html", 'href="style.css"', 'href="//example.com/x.css"')),
        ("Google Fonts stylesheet", "links", [], lambda d: edit(d, "index.html", STYLE_LINK, '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Other">' + STYLE_LINK)),
        ("font preconnect", "links", [], lambda d: edit(d, "index.html", STYLE_LINK, '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>' + STYLE_LINK)),
        ("remote stylesheet", "links", [], lambda d: edit(d, "index.html", 'href="style.css"', 'href="https://example.net/style.css"')),
        ("preload of a remote font", "links", [], lambda d: edit(d, "index.html", 'href="fonts/mm-weft.woff2"', 'href="https://fonts.gstatic.com/x.woff2"')),
        ("preload of a file that is not a font", "fonts", [], lambda d: edit(d, "index.html", 'href="fonts/mm-weft.woff2"', 'href="mark.svg"')),
        ("preload without crossorigin", "fonts", [], lambda d: edit(d, "index.html", 'type="font/woff2" crossorigin>', 'type="font/woff2">')),
        ("no preload", "fonts", [], lambda d: edit_all(d, "index.html", *[(f'<link rel="preload" href="fonts/{f}.woff2" as="font" type="font/woff2" crossorigin>\n', "") for f in {"mm-weft", font_stem}])),
        ("css font face from a font host", "links", [], lambda d: edit(d, "style.css", "url(fonts/mm-weft.woff2)", "url(https://fonts.gstatic.com/s/other/v1/x.woff2)")),
        ("css imports Google Fonts", "links", [], lambda d: edit(d, "style.css", ":root{", '@import url("https://fonts.googleapis.com/css2?family=Other");:root{')),
        ("css font face from a local file that is not the font", "fonts", [], lambda d: edit(d, "style.css", "url(fonts/mm-weft.woff2)", "url(fonts/mark.woff2)")),
        ("css font face for another family", "fonts", [], lambda d: edit(d, "style.css", '@font-face{font-family:"machine-made Weft"', '@font-face{font-family:"Other"')),
        ("css font face for Lato", "fonts", [], lambda d: edit(d, "style.css", '@font-face{font-family:"machine-made Weft"', '@font-face{font-family:"Lato"')),
        ("css font face for EB Garamond", "fonts", [], lambda d: edit(d, "style.css", '@font-face{font-family:"machine-made Weft"', '@font-face{font-family:"EB Garamond"')),
        ("css font face without swap", "fonts", [], lambda d: edit(d, "style.css", "font-display:swap", "font-display:block")),
        ("css font face with another weight", "fonts", [], lambda d: edit(d, "style.css", "font-weight:100 900", "font-weight:400")),
        ("css font face with another style", "fonts", [], lambda d: edit(d, "style.css", "font-weight:100 900;font-style:normal", "font-weight:100 900;font-style:italic")),
        ("css font face drops a face", "fonts", [], lambda d: (d / "style.css").write_text("\n".join(line for line in read_css(d).splitlines() if font_stem not in line) + "\n") if font_stem != "mm-weft" else edit(d, "style.css", "url(fonts/mm-weft.woff2)", "url(fonts/mm-sans.woff2)")),
        ("a stack names a system font", "fonts", [], lambda d: edit(d, "style.css", "ui-monospace, monospace", "ui-monospace, Georgia, monospace")),
        ("a rule sets a font family of its own", "fonts", [], lambda d: edit(d, "style.css", "box-sizing", "box-sizing:border-box}.zz{font-family:Lato;margin")),
        ("a rule sets a named family in the font shorthand", "fonts", [], lambda d: edit(d, "style.css", "box-sizing", "box-sizing:border-box}.zz{font:400 1rem Lato;margin")),
        ("a rule sets bold", "fonts", [], lambda d: edit(d, "style.css", "box-sizing", "box-sizing:border-box}.zz{font-weight:700;margin")),
        ("a rule sets bold in the font shorthand", "fonts", [], lambda d: edit(d, "style.css", "box-sizing", "box-sizing:border-box}.zz{font:700 1rem var(--font);margin")),
        *([("a rule sets italic", "fonts", [], lambda d: edit(d, "style.css", "box-sizing", "box-sizing:border-box}.zz{font-style:italic;margin"))] if not italic_ok else []),
        ("the group label loses its weight", "fonts", [], lambda d: edit(d, "style.css", "font: 400 0.71875rem / 1 var(--mono);\n  letter-spacing: 0.08em;", "font: 0.71875rem / 1 var(--mono);\n  letter-spacing: 0.08em;")),
        ("a bold tag", "fonts", [], lambda d: edit(d, "index.html", "<body>", "<body><b>x</b>")),
        ("an italic tag", "fonts", [], lambda d: edit(d, "index.html", "<body>", "<body><em>x</em>")),
        ("the main text font is not preloaded", "fonts", [], lambda d: edit(d, "index.html", f'<link rel="preload" href="fonts/{font_stem}.woff2" as="font" type="font/woff2" crossorigin>\n', "")),
        ("the font file is not the 0.2.0 file", "fonts", [], lambda d: (d / "fonts" / f"{font_stem}.woff2").write_bytes(b"wOF2" + (d / "fonts" / f"{font_stem}.woff2").read_bytes()[4:] + b"\x00")),
        ("the type scale changed", "scale", [], lambda d: edit(d, "style.css", f"--fs:{SIZE / 16:g}rem", "--fs:1.125rem")),
        ("the house line size changed", "scale", [], lambda d: edit(d, "style.css", f"--ls:{LINE_SIZE / 16:g}rem", "--ls:1.6875rem")),
        ("the word spacing is dropped", "scale", [], lambda d: (d / "style.css").write_text(read_css(d).replace("word-spacing: var(--ws);", ""))),
        ("the word spacing of the house changed", "scale", [], lambda d: edit(d, "style.css", "--ws:" + ("0.05em" if THEME["font"] == SANS else "normal"), "--ws:0.3em")),
        ("the body line height changed", "scale", [], lambda d: edit(d, "style.css", f"/ {LEADING} ", "/ 1.4 ")),
        ("the description link is underlined on hover only", "touch", [], lambda d: edit(d, "style.css", "text-decoration: underline 1px var(--accent);\n  text-underline-offset: 0.2em;\n}\n\n@media (max-width", "text-decoration: none;\n  text-underline-offset: 0.2em;\n}\n\n@media (max-width")),
        ("the description link is short on a narrow screen", "touch", [], lambda d: edit(d, "style.css", "width: fit-content;\n    min-height: 44px;", "width: fit-content;\n    min-height: 20px;")),
        ("a top bar link is short on a narrow screen", "touch", [], lambda d: edit(d, "style.css", ".bar span {\n    min-height: 44px;", ".bar span {\n    min-height: 20px;")),
        ("a plate image has no hover state without motion", "hover", [], lambda d: edit(d, "style.css", "outline-color: var(--accent);", "margin: 0;")),
        ("font file is not a woff2", "fonts", [], lambda d: (d / "fonts" / "mm-weft.woff2").write_bytes(b"<svg/>")),
        ("font file missing", "files", [], lambda d: (d / "fonts" / "mm-weft.woff2").unlink()),
        ("font licence missing", "files", [], lambda d: (d / "fonts" / "mm-weft-OFL.txt").unlink()),
        ("extra font file", "files", [], lambda d: (d / "fonts" / "other.woff2").write_bytes(b"wOF2")),
        ("Lato comes back", "files", [], lambda d: (d / "fonts" / "lato-400.woff2").write_bytes(b"wOF2")),
        ("EB Garamond comes back", "files", [], lambda d: (d / "fonts" / "eb-garamond-OFL.txt").write_text("OFL")),
        ("private repo in a font licence", "private", [], lambda d: edit(d, "fonts/mm-weft-OFL.txt", "SIL OPEN FONT", "github.com/machine-made/zzprivate SIL OPEN FONT")),
        ("upstream link outside its licence", "private", [], lambda d: edit(d, "fonts/mm-weft-OFL.txt", "SIL OPEN FONT", "github.com/tokotype/PlusJakartaSans SIL OPEN FONT")),
        ("money amount in a font licence", "forbidden", [], lambda d: edit(d, "fonts/mm-weft-OFL.txt", "SIL OPEN FONT", "$5 SIL OPEN FONT")),
        *[
            (f"{tag} tag", "no-js", [], lambda d, tag=tag: edit(d, "index.html", "<body>", f'<body><{tag} src="https://example.net/x"></{tag}>'))
            for tag in ("audio", "video", "source", "track", "iframe", "object", "embed")
        ],
        ("script tag", "no-js", [], lambda d: edit(d, "index.html", "</body>", "<script>1</script></body>")),
        ("banner without alt", "a11y", [], lambda d: edit(d, "index.html", 'height="469" alt="', 'height="469" alt=" " data-x="')),
        ("plate image without alt attribute", "a11y", [], lambda d: edit(d, "index.html", f'<img src="img/{first}.jpg" width="704" height="235" loading="lazy" alt="">', f'<img src="img/{first}.jpg" width="704" height="235" loading="lazy">')),
        ("plate link without an accessible name", "a11y", [], plate_edit(first, lambda li: li.replace(f' aria-label="{first}"', "", 1))),
        ("plate link named by something else", "a11y", [], plate_edit(first, lambda li: li.replace(f'aria-label="{first}"', 'aria-label="zz"', 1))),
        ("the repository name comes back under the plate", "projects", [], plate_edit(first, lambda li: li.replace('<span class="ds">', f'<span class="nm">{first}</span><span class="ds">', 1))),
        ("the repository name comes back inside the plate line", "projects", [], plate_edit(first, lambda li: li.replace('<span class="ds">', f'<span class="ds">{first} ', 1))),
        ("the plate has no image link", "projects", [], plate_edit(first, lambda li: re.sub(r'<a class="pic"[^>]*>(<img[^>]*>)</a>', r"\1", li, count=1))),
        ("plate image has alt text that repeats the name", "projects", [], lambda d: edit(d, "index.html", f'<img src="img/{first}.jpg" width="704" height="235" loading="lazy" alt="">', f'<img src="img/{first}.jpg" width="704" height="235" loading="lazy" alt="{first}">')),
        ("plate image without lazy loading", "projects", [], lambda d: edit(d, "index.html", f'<img src="img/{first}.jpg" width="704" height="235" loading="lazy" alt="">', f'<img src="img/{first}.jpg" width="704" height="235" alt="">')),
        ("plate image without size", "responsive", [], lambda d: edit(d, "index.html", f'<img src="img/{first}.jpg" width="704" height="235"', f'<img src="img/{first}.jpg"')),
        ("plate image missing", "files", [], lambda d: (d / "img" / f"{first}.jpg").unlink()),
        ("extra image", "files", [], lambda d: (d / "img" / "extra.jpg").write_bytes(b"\xff\xd8\xff")),
        ("banner is not a JPEG", "images", [], lambda d: (d / "img" / "banner.jpg").write_bytes(b"<svg/>")),
        ("plate has the wrong size", "images", [], lambda d: (d / "img" / f"{first}.jpg").write_bytes((d / "img" / "banner.jpg").read_bytes())),
        ("banner is cut short", "images", [], lambda d: (d / "img" / "banner.jpg").write_bytes((d / "img" / "banner.jpg").read_bytes()[:-2])),
        ("banner has the wrong size", "images", [], lambda d: (d / "img" / "banner.jpg").write_bytes((d / "img" / f"{first}.jpg").read_bytes())),
        ("image is too large", "images", [], lambda d: (d / "img" / f"{first}.jpg").write_bytes((d / "img" / f"{first}.jpg").read_bytes() + b"\x00" * 400_000)),
        ("money amount", "forbidden", [], lambda d: edit(d, "llms.txt", "## Sites", "$5\n\n## Sites")),
        ("second page", "files", [], lambda d: (d / "second.html").write_text("<!doctype html>")),
        ("mark file missing", "files", [], lambda d: (d / "mark.svg").unlink()),
        ("old hero comes back", "files", [], lambda d: (d / "heroes").mkdir() or (d / "heroes" / "x.svg").write_text("<svg/>")),
        ("non-ASCII in llms.txt", "voice", [], lambda d: edit(d, "llms.txt", "## Sites", "café\n\n## Sites")),
        ("non-ASCII in the page", "voice", [], lambda d: edit(d, "index.html", "<body>", "<body>café")),
        ("the footer dot written raw", "voice", [], lambda d: edit(d, "index.html", "&middot;", "·")),
        ("the top bar loses a site", "content", [], lambda d: edit(d, "index.html", f'<a href="{nav_other}">{other_name}</a>\n', "")),
        ("the top bar marks another site", "content", [], lambda d: edit_all(d, "index.html", (f'<span aria-current="page">{SELF}</span>', f'<a href="{self_url}">{SELF}</a>'), (f'<a href="{nav_other}">{other_name}</a>', f'<span aria-current="page">{other_name}</span>'))),
        ("the current site links to itself", "content", [], lambda d: edit(d, "index.html", f'<span aria-current="page">{SELF}</span>', f'<a href="{self_url}" aria-current="page">{SELF}</a>')),
        ("the current site is not marked", "content", [], lambda d: edit(d, "index.html", f'<span aria-current="page">{SELF}</span>', f"<span>{SELF}</span>")),
        ("two entries are marked", "a11y", [], lambda d: edit(d, "index.html", f'<a href="{nav_other}">{other_name}</a>', f'<a href="{nav_other}" aria-current="page">{other_name}</a>')),
        ("a site linked twice", "links", [], lambda d: edit(d, "index.html", "</footer>", f'<a href="{nav_other}">x</a></footer>')),
        ("the current site is linked in the footer", "links", [], lambda d: edit(d, "index.html", "</footer>", f'<a href="{self_url}">x</a></footer>')),
        ("the type link is missing", "content", [], lambda d: edit(d, "index.html", f'<a href="{TYPE_URL}">type</a>\n', "")),
        ("the type link goes elsewhere", "content", [], lambda d: edit(d, "index.html", f'<a href="{TYPE_URL}">type</a>', '<a href="https://machine-made.github.io/fonts/">type</a>')),
        ("the type link moves first", "content", [], lambda d: edit_all(d, "index.html", (f'<a href="{TYPE_URL}">type</a>\n', ""), ('<nav class="bar" aria-label="Sites">\n', f'<nav class="bar" aria-label="Sites">\n<a href="{TYPE_URL}">type</a>\n'))),
        ("the type link reads fonts", "content", [], lambda d: edit(d, "index.html", f'<a href="{TYPE_URL}">type</a>', f'<a href="{TYPE_URL}">fonts</a>')),
        # The head: title, description, favicon and the social preview.
        ("the title changed", "head", [], lambda d: edit(d, "index.html", "<title>", "<title>Other ")),
        ("the description meta changed", "head", [], lambda d: edit(d, "index.html", '<meta name="description" content="', '<meta name="description" content="Other. ')),
        ("the favicon is missing", "head", [], lambda d: edit(d, "index.html", '<link rel="icon" href="mark.svg" type="image/svg+xml">\n', "")),
        ("og:image is missing", "head", [], lambda d: edit(d, "index.html", f'<meta property="og:image" content="{self_url}img/banner.jpg">\n', "")),
        ("og:image is not the org banner", "head", [], lambda d: edit(d, "index.html", f'content="{self_url}img/banner.jpg"', f'content="{self_url}img/{first}.jpg"')),
        ("og:image is a relative path", "head", [], lambda d: edit(d, "index.html", f'content="{self_url}img/banner.jpg"', 'content="img/banner.jpg"')),
        ("og:title changed", "head", [], lambda d: edit(d, "index.html", '<meta property="og:title" content="', '<meta property="og:title" content="Other ')),
        ("og:url changed", "head", [], lambda d: edit(d, "index.html", f'<meta property="og:url" content="{self_url}"', '<meta property="og:url" content="https://example.net/"')),
        ("twitter:card is missing", "head", [], lambda d: edit(d, "index.html", '<meta name="twitter:card" content="summary_large_image">\n', "")),
        ("the banner is not in the h1", "content", [], lambda d: edit(d, "index.html", "<h1><img", "<h1></h1><img")),
        ("banner shows another image", "content", [], lambda d: edit(d, "index.html", 'src="img/banner.jpg"', f'src="img/{first}.jpg"')),
        ("org line changed", "content", [], lambda d: edit(d, "index.html", f'<p class="line">{html.escape(LINE)}', '<p class="line">Another line.')),
        ("name paragraph changed", "content", [], lambda d: edit(d, "index.html", f'<p class="blurb">{html.escape(BLURB)}', '<p class="blurb">Another paragraph.')),
        ("line and paragraph swap", "content", [], lambda d: edit_all(d, "index.html", ('<p class="line">', '<p class="tmp">'), ('<p class="blurb">', '<p class="line">'), ('<p class="tmp">', '<p class="blurb">'))),
        ("org line missing in llms.txt", "llms", [], lambda d: edit(d, "llms.txt", f"> {LINE}", "> ")),
        ("name paragraph missing in llms.txt", "llms", [], lambda d: edit(d, "llms.txt", f"{BLURB}\n\n", "")),
        ("old footer text", "content", [], lambda d: edit(d, "index.html", "<footer class=\"wrap\">\n<p>", "<footer class=\"wrap\">\n<p>An open-source workshop. ")),
        ("footer line changed", "content", [], lambda d: edit(d, "index.html", "&middot; openfluids", "&middot; fluids")),
        ("page order changed", "content", [], move_footer_up),
        ("sites missing in llms.txt", "llms", [], lambda d: edit(d, "llms.txt", "## Sites", "## Elsewhere")),
        ("a group heading is renamed", "projects", [], lambda d: edit(d, "index.html", f">{GROUPS[0][0]}</h2>", ">Tools</h2>")),
        ("a group has no label class", "projects", [], lambda d: edit(d, "index.html", '<h2 class="lbl"', "<h2")),
        ("a project is dropped", "projects", [], lambda d: edit(d, "index.html", next(m for m in re.findall(r'<li class="plate">.*?</li>\n', read_index(d), re.S) if f"/{first}" in m), "")),
        *(
            [("two projects swap places", "projects", [], lambda d: edit_all(d, "index.html", (f"/{first}\"", "/zz-swap\""), (f"/{second}\"", f"/{first}\""), ("/zz-swap\"", f"/{second}\"")))]
            if second != first
            else []
        ),
        ("a project is added", "projects", [], lambda d: edit(d, "index.html", "</ul>", f'<li class="plate"><a class="pic" href="https://github.com/{OWNER}/{first}" aria-label="{first}">x</a></li></ul>')),
        ("a group heading is renamed in llms.txt", "llms", [], lambda d: edit(d, "llms.txt", f"## {GROUPS[0][0]}", "## Tools")),
        ("unexpected site link", "links", [], plate_edit(second, lambda li: li.replace("</span></li>", ' <a class="nm" href="https://machine-made.github.io/zz/">site</a></span></li>'))),
        ("unexpected site link on another host", "projects", [], plate_edit(second, lambda li: li.replace("</span></li>", ' <a class="nm" href="https://example.net/">site</a></span></li>'))),
        ("plate name is a heading", "projects", [], plate_edit(second, lambda li: li.replace("</span></li>", f'</span><h3 class="nm">{second}</h3></li>'))),
        ("moved repository listed again", "projects", [], lambda d: edit(d, "index.html", "</ul>", f'<li><a href="https://github.com/{OWNER}/chaos-atlas">chaos-atlas</a><p>x</p></li></ul>')),
        ("accent in a style attribute", "accent", [], lambda d: edit(d, "mark.svg", '<rect class="k"', '<path style="fill:#00f" class="k"')),
        ("accent in stop-color", "accent", [], lambda d: edit(d, "mark.svg", '<rect class="k"', '<path stop-color="#00ff00" class="k"')),
        ("named colour in a stroke", "accent", [], lambda d: edit(d, "mark.svg", '<rect class="k"', '<path stroke="red" class="k"')),
        ("named colour in an svg rule", "accent", [], lambda d: edit(d, "mark.svg", ".k{fill:", ".k{stroke:red;fill:")),
        ("gradient in the mark", "colour", [], lambda d: edit(d, "mark.svg", "<rect", '<defs><linearGradient id="z"/></defs><rect')),
        ("private name in a class value", "private", ["zzprivate"], lambda d: edit(d, "index.html", '<main id="main"', '<main id="main" class="zzprivate"')),
        ("private name in an id value", "private", ["zzprivate"], lambda d: edit(d, "index.html", 'id="main"', 'id="zzprivate"')),
        ("unknown attribute", "attrs", [], lambda d: edit(d, "index.html", '<main id="main"', '<main data-x="1" id="main"')),
        ("css imports a remote file", "links", [], lambda d: edit(d, "style.css", ":root{", '@import url("https://example.net/x.css");:root{')),
        ("css string import", "links", [], lambda d: edit(d, "style.css", ":root{", '@import "https://example.net/x.css";:root{')),
        ("css url on a look-alike font host", "links", [], lambda d: edit(d, "style.css", ":root{", "a{background:url(https://fonts.gstatic.com.example.net/f.woff2)}:root{")),
        ("css url leaves docs/", "links", [], lambda d: edit(d, "style.css", ":root{", "a{background:url(../README.md)}:root{")),
        ("css data url", "links", [], lambda d: edit(d, "style.css", ":root{", "a{background:url(data:image/png;base64,AAAA)}:root{")),
        ("script in the mark svg", "no-js", [], lambda d: edit(d, "mark.svg", "<title>", "<script>1</script><title>")),
        ("event handler in the mark svg", "no-js", [], lambda d: edit(d, "mark.svg", '<rect class="k"', '<path onclick="x()" class="k"')),
        ("external href in the mark svg", "links", [], lambda d: edit(d, "mark.svg", "<rect", '<use href="https://example.net/x.svg#a"/><rect')),
        ("remote url in an svg rule", "links", [], lambda d: edit(d, "mark.svg", "<style>", "<style>.z{fill:url(https://example.net/x.svg#a)}")),
        ("css image-set", "links", [], lambda d: edit(d, "style.css", ":root{", 'a{background:image-set("mark.svg" 1x)}:root{')),
        ("css image()", "links", [], lambda d: edit(d, "style.css", ":root{", 'a{background:image("mark.svg")}:root{')),
        ("css prefixed cross-fade", "links", [], lambda d: edit(d, "style.css", ":root{", "a{background:-webkit-cross-fade(url(mark.svg),url(mark.svg),50%)}:root{")),
        ("css escaped function name", "css", [], lambda d: edit(d, "style.css", ":root{", "a{background:\\69mage-set(mark.svg 1x)}:root{")),
        ("named colour in style.css", "accent", [], lambda d: edit(d, "style.css", "box-sizing", "color:red;box-sizing")),
        ("upper-case named colour", "accent", [], lambda d: edit(d, "style.css", "box-sizing", "color:BLUE;box-sizing")),
        ("named colour in a border", "accent", [], lambda d: edit(d, "style.css", "box-sizing", "border:1px solid tomato;box-sizing")),
        ("named colour in a var fallback", "accent", [], lambda d: edit(d, "style.css", "box-sizing", "color:var(--fg,navy);box-sizing")),
        ("system colour", "accent", [], lambda d: edit(d, "style.css", "box-sizing", "color:LinkText;box-sizing")),
        ("escaped colour name", "css", [], lambda d: edit(d, "style.css", "box-sizing", "color:\\72 ed;box-sizing")),
        ("colour mix function", "colour", [], lambda d: edit(d, "style.css", "box-sizing", "color:color-mix(in srgb,#fff,#000);box-sizing")),
        ("black, white and transparent are allowed", None, [], lambda d: edit(d, "style.css", "box-sizing", "color:black;background:WHITE;border-color:transparent;outline-color:currentColor;box-sizing")),
        ("a class with a colour name is not a colour", None, [], lambda d: edit(d, "style.css", "box-sizing", "box-sizing:border-box}.red{margin:0}a:not(.tan){margin:0}.zz{margin:0")),
        ("named colour in a page style block", "accent", [], lambda d: edit(d, "index.html", "<body>", "<body><style>a{color:red}</style>")),
        ("hex accent in a page style block", "accent", [], lambda d: edit(d, "index.html", "<body>", "<body><style>a{color:#00f}</style>")),
        ("accent as the fallback of a fragment paint", "accent", [], lambda d: edit(d, "mark.svg", '<rect class="k"', '<path fill="url(#a) #0000ff" class="k"')),
        ("named fallback of a fragment paint", "accent", [], lambda d: edit(d, "mark.svg", '<rect class="k"', '<path fill="url(#a) red" class="k"')),
        ("function fallback of a fragment paint", "colour", [], lambda d: edit(d, "mark.svg", '<rect class="k"', '<path fill="url(#a) rgb(0,0,255)" class="k"')),
        ("keyword fallback of a fragment paint", None, [], lambda d: edit(d, "mark.svg", '<rect class="k"', '<path fill="url(#a) currentColor" class="k"')),
        ("text colour from a low-contrast grey", "contrast", [], lambda d: edit(d, "style.css", "box-sizing", f"color:{THEME['ground'].replace('0', '1', 1)};box-sizing")),
        ("text colour from the edge token", "contrast", [], lambda d: edit(d, "style.css", "box-sizing", "color:var(--edge);box-sizing")),
        ("text on a low-contrast background token", "contrast", [], lambda d: edit(d, "style.css", "box-sizing", "color:var(--fg);background:var(--muted);box-sizing")),
        ("background shorthand with more than a token", "contrast", [], lambda d: edit(d, "style.css", "box-sizing", "background:var(--bg) url(mark.svg);box-sizing")),
        ("text colour from an unknown token", "contrast", [], lambda d: edit(d, "style.css", "box-sizing", "color:var(--nope);box-sizing")),
        ("a pair of palette tokens is allowed", None, [], lambda d: edit(d, "style.css", "box-sizing", "color:var(--muted);background:var(--bg) !important;box-sizing")),
        ("upper-case colour function", "colour", [], lambda d: edit(d, "style.css", "box-sizing", "color:RGB(0,0,255);box-sizing")),
        ("upper-case gradient", "colour", [], lambda d: edit(d, "style.css", "box-sizing", "background:LINEAR-GRADIENT(red,blue);box-sizing")),
        ("a second gradient", "colour", [], lambda d: edit(d, "style.css", "box-sizing", "background:linear-gradient(#000,#000);box-sizing")),
        ("the banner mask changed", "colour", [], lambda d: edit(d, "style.css", "#000 10%", "#000 20%")),
        ("the banner mask missing", "colour", [], lambda d: edit(d, "style.css", MASK, "")),
        ("base tag", "no-js", [], lambda d: edit(d, "index.html", "<body>", '<body><base href="https://example.net/">')),
        ("private name as a character reference in the mark", "private", ["zzprivate"], lambda d: edit(d, "mark.svg", "<title>", "<title>zz&#x70;rivate ")),
        ("private name as a nested reference in an attribute", "private", ["zzprivate"], lambda d: edit(d, "mark.svg", '<rect class="k"', '<path id="zz&amp;#112;rivate" class="k"')),
        ("private repo as a character reference in the mark", "private", [], lambda d: edit(d, "mark.svg", "<title>", "<title>github.com/&#x6d;achine-made/zzprivate ")),
        ("remote url in a filter attribute", "links", [], lambda d: edit(d, "mark.svg", '<rect class="k"', '<path filter="url(https://example.net/x.svg#f)" class="k"')),
        ("remote url in a fill attribute", "links", [], lambda d: edit(d, "mark.svg", '<rect class="k"', '<path fill="url(https://example.net/x.svg#f)" class="k"')),
        ("local fragment in a filter attribute", None, [], lambda d: edit(d, "mark.svg", '<rect class="k"', '<path filter="url(#f)" class="k"')),
        ("USD before an amount", "forbidden", [], lambda d: edit(d, "llms.txt", "## Sites", "USD 5\n\n## Sites")),
        ("CHF before an amount", "forbidden", [], lambda d: edit(d, "llms.txt", "## Sites", "chf 5\n\n## Sites")),
        ("EUR before an amount", "forbidden", [], lambda d: edit(d, "llms.txt", "## Sites", "Eur5\n\n## Sites")),
        ("USD after an amount", "forbidden", [], lambda d: edit(d, "llms.txt", "## Sites", "5 USD\n\n## Sites")),
        ("private name as an element name", "private", ["zzprivate"], lambda d: edit(d, "index.html", "<body>", "<body><zzprivate></zzprivate>")),
        # The behaviour rules of the brief: each break is one rule moved out of its media query.
        ("a hover rule outside the hover query", "hover", [], lambda d: edit(d, "style.css", "box-sizing", "box-sizing:border-box}.plate:hover{margin:0")),
        ("a scaled plate image is not clipped", "hover", [], lambda d: edit(d, "style.css", ".pic {\n  display: block;\n  overflow: hidden;", ".pic {\n  display: block;")),
        ("a hover rule in the wrong query", "hover", [], lambda d: edit(d, "style.css", "box-sizing", "box-sizing:border-box}@media (min-width: 1px){.plate:hover{margin:0}}.zz{margin:0")),
        ("a hover rule in the hover query is allowed", None, [], lambda d: edit(d, "style.css", "box-sizing", "box-sizing:border-box}@media (hover: hover){.zz:hover{margin:0}}.zz{margin:0")),
        ("a transition outside the motion query", "motion", [], lambda d: edit(d, "style.css", "box-sizing", "box-sizing:border-box}.zz{transition:color 1s")),
        ("a transform outside the motion query", "motion", [], lambda d: edit(d, "style.css", "box-sizing", "box-sizing:border-box}.zz{transform:scale(2)")),
        ("a hover transform without the motion query", "motion", [], lambda d: edit(d, "style.css", "@media (hover: hover) and (prefers-reduced-motion: no-preference)", "@media (hover: hover)")),
        ("an animation in a hover query only", "motion", [], lambda d: edit(d, "style.css", "box-sizing", "box-sizing:border-box}@media (hover: hover){.zz{animation:none}}.zz{margin:0")),
        ("smooth scrolling outside the motion query", "motion", [], lambda d: edit(d, "style.css", "box-sizing", "box-sizing:border-box}html{scroll-behavior:smooth")),
        ("the focus ring is removed", "focus", [], lambda d: edit(d, "style.css", "outline: 2px solid var(--accent);", "outline: none;")),
        ("the focus ring is not the accent", "focus", [], lambda d: edit(d, "style.css", "outline: 2px solid var(--accent);", "outline: 2px solid var(--fg);")),
        ("an outline is removed on a link", "focus", [], lambda d: edit(d, "style.css", "box-sizing", "box-sizing:border-box}.plate a{outline:none}.zz{margin:0")),
        ("the plate grid minimum changed", "responsive", [], lambda d: edit(d, "style.css", "minmax(min(100%, 240px), 1fr)", "minmax(min(100%, 150px), 1fr)")),
        ("the plate grid has a fixed minimum", "responsive", [], lambda d: edit(d, "style.css", "minmax(min(100%, 240px), 1fr)", "minmax(240px, 1fr)")),
        ("the content width changed", "responsive", [], lambda d: edit(d, "style.css", "--max: 1200px", "--max: 1280px")),
        ("a forced width", "responsive", [], lambda d: edit(d, "style.css", "box-sizing", "width:900px;box-sizing")),
        ("no-wrap text", "responsive", [], lambda d: edit(d, "style.css", "box-sizing", "white-space:nowrap;box-sizing")),
        ("the accent never used", "accent", [], lambda d: (d / "style.css").write_text(re.sub(r"var\(--accent\)", "var(--fg)", (d / "style.css").read_text()))),
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
    total, bad = 0, 0

    def report(ok: bool, title: str) -> None:
        nonlocal total, bad
        total += 1
        if not ok:
            bad += 1
            print(f"SELF-TEST FAIL: {title}")

    with tempfile.TemporaryDirectory() as tmp:
        for title, rule, deny, mutate in [*cases, ("clean copy", None, [], lambda d: None)]:
            root = Path(tmp) / "case"
            shutil.rmtree(root, ignore_errors=True)
            shutil.copytree(real, root / "docs")
            (root / "README.md").write_text("outside docs/\n")
            DOCS = root / "docs"
            try:
                mutate(DOCS)
                found = run_checks(deny)
            except AssertionError as exc:
                found, rule = [str(exc)], "stale"
            except Exception as exc:
                found, rule = [f"crash {exc!r}"], "no crash"
            caught = any(line.startswith(f"FAIL {rule}:") for line in found) if rule else not found
            report(caught, f"{title}: expected {rule or 'a clean pass'}, got {found[:2]}")
        DOCS = real
        for bad_name in ("../evil", "Machine", "a..b", "-x", "a/b"):
            report(build_rejects({"name": bad_name}), f"build.py accepted the site name {bad_name!r}")
        bad_sites: list[dict[str, object]] = [
            {"groups": []},
            {"groups": "x"},
            {"groups": [{"title": "A", "projects": []}]},
            {"groups": [{"title": "A", "projects": [{"repo": first, "line": "y"}]}, {"title": "a!", "projects": [{"repo": second, "line": "y"}]}]},
            {"groups": [{"title": "A", "projects": [{"repo": first, "line": "y"}, {"repo": first, "line": "y"}]}]},
            {"groups": [{"title": "A", "projects": [{"repo": first, "line": "y", "site": "http://x"}]}]},
            {"groups": [{"title": "A", "projects": [{"repo": "zz-no-image", "line": "y"}]}]},
            {"groups": [{"title": "A", "projects": [{"repo": first, "line": "café"}]}]},
            {"blurb": 5},
            {"line": "café"},
            {"theme": {"ground": "#000", "text": "#ffffff", "muted": "#888888", "accent": "#ff0000", "font": WEFT}},
            {"theme": {**json.loads((ROOT / "site.json").read_text(encoding="utf-8"))["theme"], "size": 20}},
            {"groups": [{"title": "A", "projects": [{"repo": first, "line": "y", "site": "https://example.net/", "site_label": "demo"}]}]},
            {"groups": [{"title": "A", "projects": [{"repo": first, "line": "y", "site_label": "docs"}]}]},
            {"theme": {**json.loads((ROOT / "site.json").read_text(encoding="utf-8"))["theme"], "font": "Comic Sans"}},
            {"nav": []},
            {"nav": ["machine-made"]},
            {"nav": [{k: v for k, v in n.items()} for n in json.loads((ROOT / "site.json").read_text(encoding="utf-8"))["nav"][:3]]},
            {"nav": [*json.loads((ROOT / "site.json").read_text(encoding="utf-8"))["nav"][:3], {"name": "type", "url": "https://example.net/type/"}]},
            {"nav": [*json.loads((ROOT / "site.json").read_text(encoding="utf-8"))["nav"][:3], {"name": "type", "url": TYPE_URL, "self": True}]},
            {"redirects": {"style.css": "https://example.net/x"}},
            {"redirects": {"llms.txt": "https://example.net/x"}},
        ]
        for changes in bad_sites:
            report(build_rejects(changes), f"build.py accepted {str(changes)[:60]}")
        for problem in site_links_hold():
            report(False, problem)
        report(renamed_site_passes("loom-x"), "a site under another name does not pass the checks")
        report(build_needs("fonts/mm-weft.woff2"), "build.py builds without the fonts in fonts/")
        report(build_needs(f"img/org/{name}.jpg"), "build.py builds without the banner of the house")
        report(build_needs(f"img/repo/{first}.jpg"), "build.py builds without the banner of a repository")
        missing = str(Path(tmp) / "missing")
        denied = Path(tmp) / "deny.txt"
        denied.write_text("# a comment\n\nzz one\n  zz two  \n#zz three\n", encoding="utf-8")
        report(load_deny(str(denied)) == ["zz one", "zz two"], "load_deny does not keep one name per line")
        report(cli_fails(["--deny"], "FAIL args:"), "--deny without a file")
        report(cli_fails(["--deny", missing], "FAIL deny:"), "--deny with a missing file")
        report(cli_fails(["--no-such-flag"], "FAIL args:"), "an unknown flag")
        report(cli_fails(["--site", missing], "FAIL args:"), "--site with no allow.json")
    if bad:
        sys.exit(1)
    print(f"SELF-TEST OK ({total} cases)")


def move_footer_up(docs: Path) -> None:
    """Put the footer before the main part: the page order is broken."""
    text = read_index(docs)
    foot = re.search(r"<footer.*?</footer>\n", text, re.S)
    if foot is None:
        raise AssertionError("self-test is stale: no footer in docs/index.html")  # noqa: TRY003
    text = text.replace(foot.group(0), "").replace('<main id="main"', foot.group(0) + '<main id="main"', 1)
    (docs / "index.html").write_text(text, encoding="utf-8")


def read_css(docs: Path) -> str:
    return (docs / "style.css").read_text(encoding="utf-8")


def read_index(docs: Path) -> str:
    return (docs / "index.html").read_text(encoding="utf-8")


def load_allow(folder: str) -> None:
    """Point the checks at a house. Its allow.json is the public list, kept apart from site.json
    on purpose: the page passes only when the two agree."""
    global ROOT, DOCS, OWNER, LINE, BLURB, THEME, SELF, SITES, GROUPS, SITE_LINKS, SITE_LABELS, REDIRECTS  # noqa: PLW0603
    root = Path(folder).resolve()
    try:
        allow = json.loads((root / "allow.json").read_text(encoding="utf-8"))
        OWNER, LINE, BLURB = str(allow["owner"]), str(allow["line"]), str(allow["blurb"])
        THEME = {k: str(allow["theme"][k]) for k in ("ground", "text", "muted", "accent", "font")}
        SITES = tuple((str(n), str(u)) for n, u in allow["sites"])
        SELF = str(allow["self"])
        GROUPS = tuple((str(title), tuple(str(r) for r in repos)) for title, repos in allow["groups"])
        SITE_LINKS = {str(k): str(v) for k, v in allow.get("site_links", {}).items()}
        SITE_LABELS = {str(k): str(v) for k, v in allow.get("site_labels", {}).items()}
        REDIRECTS = {str(k): str(v) for k, v in allow.get("redirects", {}).items()}
        site_owner = str(json.loads((root / "site.json").read_text(encoding="utf-8"))["owner"])
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"FAIL args: {folder}/allow.json is missing or incomplete ({exc.__class__.__name__})")
        sys.exit(2)
    if site_owner != OWNER:
        print(f"FAIL args: {folder}/allow.json owner {OWNER!r} differs from site.json owner {site_owner!r}")
        sys.exit(2)
    if THEME["font"] not in FONT_SPECS or SELF not in {n for n, _ in SITES}:
        print(f"FAIL args: {folder}/allow.json names a font or a current site that the checks do not know")
        sys.exit(2)
    if [n for n, _ in SITES] != list(BAR_NAMES) or dict(SITES)["type"] != TYPE_URL or SELF == "type":
        print(f"FAIL args: {folder}/allow.json sites must be {', '.join(BAR_NAMES)} with type at {TYPE_URL}")
        sys.exit(2)
    if set(SITE_LABELS) - set(SITE_LINKS) or not set(SITE_LABELS.values()) <= {"docs"}:
        print(f"FAIL args: {folder}/allow.json site_labels may only mark a site link as docs")
        sys.exit(2)
    ROOT, DOCS = root, root / "docs"


def main() -> None:
    args = parse_args(sys.argv[1:])
    load_allow(args.site or str(ROOT))
    if args.self_test:
        self_test()
        return
    found = run_checks(load_deny(args.deny))
    if found:
        print("\n".join(found))
        sys.exit(1)
    print("OK")


if __name__ == "__main__":
    main()
