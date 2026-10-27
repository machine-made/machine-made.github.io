#!/usr/bin/env python3
"""Check the built site in docs/. Standard library only.

Prints OK and exits 0 when every rule holds. Otherwise prints one line per failure and exits 1.
`python3 check_site.py --self-test` breaks a copy of docs/ in many ways and checks that each
break is caught.

Private repository names are not kept in this repository. Rules that need them read a list
from a file outside the repository: `python3 check_site.py --deny FILE` or MM_DENY_FILE=FILE.
FILE has one name per line. Without it, the allowlist rules still reject every link and every
repository-shaped name that is not public.
"""

import argparse
import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from collections.abc import Callable, Iterator
from html.parser import HTMLParser
from pathlib import Path
from typing import Literal, NoReturn
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parent
DOCS = ROOT / "docs"

OWNER = "machine-made"
GROUPS = (
    ("Science and numerics", ("minuit2-rs", "libsvm-rs", "nebula-quanta", "dynachaos", "chaos-atlas", "nanochat-rs")),
    ("Desktop and editor tools", ("pdf-next", "vscode-pdf-next", "vscode-diff-next", "homebrew-tap")),
    ("Tools for agents", ("bun-do", "fortran-lsp", "pi-effort")),
    ("Type", ("type",)),
)
PUBLIC_REPOS = tuple(repo for _, repos in GROUPS for repo in repos)
SITE_LINKS = {"chaos-atlas": "https://machine-made.github.io/chaos-atlas/"}
HOUSE_URLS = ("https://github.com/openfluids", "https://github.com/BoringQuantSystems")
TAGLINE = "Made by machines. Proven for machines."
SUBTITLE = "A lab run by machines."
FOOTER = "Made by agents. Directed by a person, in spare time."
BASE_FILES = {"index.html", "style.css", "mark.svg", "llms.txt"}
# The two fonts of the site and their licences, served from docs/fonts/. The page loads nothing else.
FONT_FAMILIES = {"machine-made Weft": "mm-weft", "machine-made Sans": "mm-sans"}
FONT_FILES = {f"fonts/{slug}{end}" for slug in FONT_FAMILIES.values() for end in (".woff2", "-OFL.txt")}
# Public sites of third parties that a licence text names. Only the licences may name them.
LICENCE_URLS = {"fonts/mm-sans-OFL.txt": ("github.com/tokotype/PlusJakartaSans",)}
RULE_PITCH = 8
CODE_BITS = 7
FILE_NAME = re.compile(r"[a-z0-9][a-z0-9._-]*")
FRAME = (1408, 469)
FORBIDDEN = re.compile(
    r"[$\u20ac\u00a3]\s?[0-9]|\b(?:usd|chf|eur)\s?[0-9]|[0-9]\s?(?:usd|chf|eur)\b"
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
    "src", "width", "height", "alt", "loading", "aria-labelledby",
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

failures: list[str] = []


def fail(rule: str, message: str) -> None:
    line = f"FAIL {rule}: {message}"
    if line not in failures:
        failures.append(line)


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


def rule_titles(name: str | None) -> list[str]:
    """The text that each decorative row of dots must encode, in page order: the group titles,
    Houses, and the site name for the footer."""
    return [title for title, _ in GROUPS] + ["Houses"] + ([name] if name else [])


def check_files(name: str | None) -> None:
    wanted = BASE_FILES | FONT_FILES | {f"rules/{slug(title)}.svg" for title in rule_titles(name)}
    if name:
        wanted.add(f"heroes/{name}.svg")
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
    if '<meta name="color-scheme" content="light dark">' not in html_text:
        fail("dark", "no color-scheme meta")
    if re.search(r"<title>[^<]+</title>", html_text) is None:
        fail("a11y", "no title")
    for problem in page.unknown_attrs:
        fail("attrs", f"{problem}; the page uses no other attributes")
    for css in page.styles:
        check_refs(css, "index.html", "css")
        check_colour_names(css, "index.html")
        if split_accent(colours_of(css, "index.html")):
            fail("accent", "index.html has a style block with a colour of its own; colours belong in style.css")
    for forbidden in FORBIDDEN_TAGS:
        if forbidden in page.tags:
            fail("no-js", f"<{forbidden}> is not allowed on a page that needs no script")
    for tag in ("header", "main", "footer", "h1", "h2", "ul"):
        if tag not in page.tags:
            fail("semantic", f"no <{tag}>")
    if page.tags.count("h1") != 1:
        fail("semantic", "the page needs exactly one h1")
    if page.tags.count("main") != 1:
        fail("semantic", "the page needs exactly one main")
    if name and ("h1", name) not in page.headings:
        fail("content", f"the h1 must be the site name, {name}")
    if name and not any(img.get("src") == f"heroes/{name}.svg" for img in page.imgs):
        fail("hero", f"the header must show heroes/{name}.svg")
    first: Attrs = page.first_link or {}
    if first.get("href") != "#main" or "main" not in page.ids:
        fail("a11y", "the first link must be a skip link to #main")
    for img in page.imgs:
        decorative = img.get("alt") == "" and img.get("aria-hidden") == "true"
        if not decorative and not (img.get("alt") or "").strip():
            fail("a11y", f"image {img.get('src')} has no alt text and is not marked aria-hidden")
        if not (img.get("width") and img.get("height")):
            fail("responsive", f"image {img.get('src')} has no width and height")
        target = local_target(img.get("src") or "")
        if target is None or not target.is_file():
            fail("links", f"image {img.get('src')} does not resolve inside docs/")
    for link in page.links:
        href = link.get("href") or ""
        parts = urlsplit(href)
        if href.startswith("#"):
            if href[1:] not in page.ids:
                fail("links", f"{href} points to no id")
        elif parts.scheme or parts.netloc:
            if parts.scheme.lower() != "https":
                fail("links", f"{href} is not an https link")
            elif link.get("tag") == "link":
                fail("links", f"{href} is an external resource; the page loads only files in docs/")
            elif not (
                href in HOUSE_URLS
                or href in SITE_LINKS.values()
                or any(href == f"https://github.com/{OWNER}/{repo}" for repo in PUBLIC_REPOS)
            ):
                fail("links", f"{href} is not in the public list")
        else:
            target = local_target(href)
            if target is None or not target.is_file():
                fail("links", f"{href} does not resolve inside docs/")


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


LOCAL_WOFF2 = re.compile(r"\s*url\(\s*(['\"]?)fonts/([a-z-]+)\.woff2\1\s*\)\s*format\(\s*(['\"])woff2\3\s*\)\s*")


def check_fonts(html_text: str) -> None:
    """The fonts are files in docs/fonts/: one @font-face per family with a local woff2 and
    font-display: swap, each file a real woff2, each preload a local woff2 with crossorigin."""
    css = re.sub(r"/\*.*?\*/", " ", read("style.css"), flags=re.S)
    faces = re.findall(r"@font-face\s*\{([^}]*)\}", css, re.I)
    seen: set[str] = set()
    for face in faces:
        family = re.search(r"font-family\s*:\s*(['\"])(.*?)\1", face)
        src = re.search(r"(?<![\w-])src\s*:\s*([^;]*)", face)
        source = re.fullmatch(LOCAL_WOFF2, src.group(1)) if src else None
        name = family.group(2) if family else "?"
        if name not in FONT_FAMILIES:
            fail("fonts", f"style.css has an @font-face for {name!r}; the site uses only {', '.join(FONT_FAMILIES)}")
            continue
        seen.add(name)
        if not source or source.group(2) != FONT_FAMILIES[name]:
            fail("fonts", f"the @font-face of {name} must load only fonts/{FONT_FAMILIES[name]}.woff2")
        if not re.search(r"font-display\s*:\s*swap\b", face):
            fail("fonts", f"the @font-face of {name} needs font-display: swap")
    for name in sorted(set(FONT_FAMILIES) - seen):
        fail("fonts", f"style.css has no @font-face for {name}")
    for rel in sorted(f for f in FONT_FILES if f.endswith(".woff2")):
        path = DOCS / rel
        if path.is_file() and path.read_bytes()[:4] != b"wOF2":
            fail("fonts", f"docs/{rel} is not a woff2 font")
    preloads = re.findall(r"<link\b[^>]*\brel=\"preload\"[^>]*>", html_text)
    if not preloads:
        fail("fonts", "the page preloads no font; preload the fonts of the header")
    for tag in preloads:
        href = re.search(r'\bhref="([^"]*)"', tag)
        target = href.group(1) if href else ""
        if not target.endswith(".woff2") or target not in FONT_FILES:
            fail("fonts", f"the page preloads {target[:50]!r}, which is not a font of the site")
        if 'as="font"' not in tag or 'type="font/woff2"' not in tag or not re.search(r"\bcrossorigin\b", tag):
            fail("fonts", f"the preload of {target[:50]!r} needs as=\"font\", type=\"font/woff2\" and crossorigin")


def sentences_of(paragraph: str) -> list[str]:
    return re.split(r"(?<=[.!?])\s+", paragraph.strip())


def check_prose(paragraphs: list[str], where: str) -> None:
    for paragraph in paragraphs:
        for sentence in sentences_of(paragraph):
            if len(sentence.split()) > MAX_WORDS:
                fail("voice", f"{where}: a sentence has more than {MAX_WORDS} words: {sentence[:40]}")


def group_lists(source: str, pattern: str) -> list[tuple[str, list[str]]]:
    """(title, repositories) for each group in a page or in llms.txt. pattern captures title and body."""
    return [
        (title, re.findall(rf"{GITHUB_URL}/{OWNER}/([\w.-]+)", body))
        for title, body in re.findall(pattern, source, re.S)
    ]


def check_content(page: Page, html_text: str) -> str:
    text = " ".join(" ".join(page.text).split())
    for needed in (TAGLINE, SUBTITLE, FOOTER):
        if needed not in text:
            fail("content", f'the page lacks "{needed}"')
    if not re.search(
        rf'<p class="tagline">(?:(?!</p>).)*</p>\s*<p class="subtitle">{re.escape(SUBTITLE)}</p>', html_text, re.S
    ):
        fail("content", "the subtitle line must follow the tagline")
    hrefs = [link.get("href") or "" for link in page.links if link.get("tag") != "link"]
    repo_links = [h for h in hrefs if h.startswith(f"https://github.com/{OWNER}/")]
    expected = [f"https://github.com/{OWNER}/{repo}" for repo in PUBLIC_REPOS]
    if sorted(repo_links) != sorted(expected):
        fail("projects", "the project links are not exactly the public repositories")
    for url in [*HOUSE_URLS, *SITE_LINKS.values()]:
        if hrefs.count(url) != 1:
            fail("links", f"{url} must be linked once")
    if any(kind == "h3" for kind, _ in page.headings):
        fail("projects", "the page has headings below h2; each project list is a plain list")
    found = group_lists(html_text, r'<h2 id="[\w-]+">([^<]*)</h2>\s*<ul class="projects">(.*?)</ul>')
    if found != [(title, list(repos)) for title, repos in GROUPS]:
        fail("projects", "the projects are not in the three groups, in order, under their headings")
    if [h for kind, h in page.headings if kind == "h2"] != [t for t, _ in GROUPS] + ["Houses"]:
        fail("projects", "the h2 headings must be the group titles, then Houses")
    for repo, url in SITE_LINKS.items():
        if not re.search(rf'<a href="https://github.com/{OWNER}/{repo}">{repo}</a><p>[^<]*<a class="site" href="{re.escape(url)}">site</a></p>', html_text):
            fail("projects", f"{repo} needs a second link labelled site to {url}")
    for title in [t for t, _ in GROUPS] + ["Houses"]:
        if f'aria-labelledby="{slug(title)}">\n<img class="punch" src="rules/{slug(title)}.svg"' not in html_text:
            fail("hero", f"the section {title} must open with its row of dots, rules/{slug(title)}.svg")
    if not re.search(r'<footer class="section">\n<img class="punch" src="rules/[a-z0-9-]+\.svg"', html_text):
        fail("hero", "the footer must open with a row of dots")
    check_prose(page.paragraphs, "index.html")
    return " ".join([text] + page.values + page.hidden + page.tags)


def emitted(visible: str) -> Iterator[tuple[str, str]]:
    """Every emitted file as (name, text). The page counts as what a reader or a crawler gets."""
    yield "index.html", visible
    for path in sorted(DOCS.rglob("*")):
        name = path.relative_to(DOCS).as_posix()
        if path.is_file() and name != "index.html" and path.suffix != ".woff2":
            yield name, path.read_text(encoding="utf-8", errors="replace")


def decoded(source: str) -> str:
    """source with every character reference decoded, however deeply it is nested."""
    while (plain := html.unescape(source)) != source:
        source = plain
    return source


def check_leaks(visible: str, deny: list[str]) -> None:
    house_hosts = {u.split("//", 1)[1] for u in HOUSE_URLS}
    for name, raw in emitted(visible):
        if not raw.isascii():
            fail("voice", f"docs/{name} has characters that are not plain ASCII")
        # An svg or a page can spell a name with &#x..; references. Match the raw and the decoded text.
        source = raw + "\n" + decoded(raw)
        for match in GITHUB.findall(source):
            ok = match in house_hosts or match in LICENCE_URLS.get(name, ()) or any(
                match == f"github.com/{OWNER}/{repo}" for repo in PUBLIC_REPOS
            )
            if not ok:
                fail("private", f"{match} is not in the public list ({name})")
        for repo in RS_NAME.findall(source):
            if repo.lower() not in PUBLIC_REPOS:
                fail("private", f"{repo} looks like a repository that is not in the public list ({name})")
        for word in deny:
            if re.search(rf"(?<![\w]){re.escape(word)}(?![\w])", source, re.I):
                fail("private", f"a private name appears in docs/{name} ({len(word)} letters)")
    for path in DOCS.rglob("*"):
        for word in deny:
            if path.is_file() and re.search(re.escape(word), path.name, re.I):
                fail("private", f"a private name is part of the file name {path.name}")


def check_forbidden() -> None:
    for path in sorted(DOCS.rglob("*")):
        if path.is_file() and path.suffix != ".woff2":
            hit = FORBIDDEN.search(path.read_text(encoding="utf-8", errors="replace"))
            if hit:
                fail("forbidden", f"docs/{path.relative_to(DOCS).as_posix()} contains {hit.group(0)!r}")


def rule_declarations(css: str) -> Iterator[dict[str, str]]:
    """The declarations of every rule block in css, by lower-case property. The last one wins."""
    css = re.sub(r"/\*.*?\*/", " ", css, flags=re.S)
    for match in re.finditer(r"[^{};]*\{([^{}]*)\}", css):
        found: dict[str, str] = {}
        for declaration in match.group(1).split(";"):
            prop, colon, value = declaration.partition(":")
            if colon:
                found[prop.strip().lower()] = re.sub(r"\s*!important\s*$", "", value.strip(), flags=re.I)
        yield found


def text_colour(value: str, prop: str, mode: dict[str, str]) -> str | None:
    """The hex that a color or background value gives in one mode. None when it takes what is there.

    Only a palette token, black, white or transparent sets a colour. Anything else fails."""
    v = value.lower()
    token = re.fullmatch(r"var\(\s*--([a-z-]+)\s*\)", v)
    if token and token.group(1) in mode:
        return mode[token.group(1)]
    if v in GREY_NAMES:
        return GREY_NAMES[v]
    if v == "transparent":
        return mode["bg"]
    if v in ("inherit", "currentcolor"):
        return None
    fail("contrast", f"style.css sets {prop}: {value[:30]!r}; use a palette token (var(--name)), black, white or transparent")
    return None


def check_text_colours(css: str, light: dict[str, str], night: dict[str, str]) -> None:
    """Measure the colours that text uses: each color and background in style.css, against its partner.

    A rule with only color is measured on --bg. A rule with only a background is measured with --fg."""
    for decls in rule_declarations(css):
        fg = decls.get("color")
        bgs: list[str | None] = [decls[k] for k in ("background-color", "background") if k in decls]
        if fg is None and not bgs:
            continue
        for mode in (light, night):
            fg_hex = text_colour(fg, "color", mode) if fg is not None else None
            for bg in bgs or [None]:
                bg_hex = text_colour(bg, "background", mode) if bg is not None else None
                top, ground = fg_hex or mode["fg"], bg_hex or mode["bg"]
                need = 3.0 if top == mode["red"] else 4.5
                ratio = contrast(top, ground)
                if ratio < need:
                    fail("contrast", f"style.css has text {top} on {ground} at {ratio:.2f}, below {need}")


def check_css() -> None:
    css = read("style.css")
    if not css:
        return
    root = re.search(r":root\{([^}]*)\}", css)
    dark = re.search(r"prefers-color-scheme:\s*dark\)\{:root\{([^}]*)\}", css)
    if not root or not dark:
        fail("dark", "style.css needs :root colours for light and for prefers-color-scheme: dark")
        return

    def vars_of(block: str) -> dict[str, str]:
        found: dict[str, str] = {}
        for key, value in re.findall(r"--([a-z-]+):\s*(#[0-9a-fA-F]+)\b", block):
            if len(value) in (4, 7):
                found[key] = value
            else:
                fail("colour", f"--{key} is {value}; use #rgb or #rrggbb with no alpha")
        return found

    light, night = vars_of(root.group(1)), {**vars_of(root.group(1)), **vars_of(dark.group(1))}
    for mode, v in (("light", light), ("dark", night)):
        for key in ("bg", "fg", "muted", "red"):
            if key not in v:
                fail("contrast", f"{mode} has no --{key}")
                return
        for fg, need in (("fg", 4.5), ("muted", 4.5), ("red", 3.0)):
            ratio = contrast(v[fg], v["bg"])
            if ratio < need:
                fail("contrast", f"{mode} --{fg} on --bg is {ratio:.2f}, below {need}")
    if night["bg"].lower() != "#000000" or night["fg"].lower() != "#ffffff":
        fail("dark", "dark mode needs a black ground and white type")
    if light["red"].lower() != night["red"].lower():
        fail("dark", "the red must be the same in light and dark")
    check_refs(css, "style.css", "css")
    check_colour_names(css, "style.css")
    check_text_colours(css, light, night)
    accents = split_accent(colours_of(css, "style.css"))
    if accents != {light["red"].lower()}:
        fail("accent", f"style.css needs exactly one accent colour, the red; found {sorted(accents)}")
    if re.search(r"\bnowrap\b|(?<![-\w])width:\s*\d{3,}px", css):
        fail("responsive", "style.css forces a width that can scroll")


def rects_of(d: str) -> Iterator[tuple[int, int, int, int]]:
    for m in re.finditer(r"M(-?\d+) (-?\d+)h(\d+)v(\d+)h-\d+z", d):
        x, y, w, h = (int(g) for g in m.groups())
        yield x, y, w, h


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


Dot = tuple[float, float, int]
BIG_DOT = re.compile(r"M(-?[\d.]+) (-?[\d.]+)a([\d.]+) [\d.]+ 0 1 0 [\d.]+ 0")
SMALL_DOT = re.compile(r"M(-?[\d.]+) (-?[\d.]+)h([\d.]+)v")


def dots_of(tree: ET.Element, classes: tuple[str, ...]) -> list[Dot]:
    """Centre and bit of every dot in the paths of these classes. A big dot is a 1, a small one a 0."""
    found: list[Dot] = []
    for el in tree.iter():
        if el.tag.rsplit("}", 1)[-1] == "path" and el.get("class") in classes:
            d = el.get("d", "")
            found += [(float(x) + float(r), float(y), 1) for x, y, r in BIG_DOT.findall(d)]
            found += [(float(x) + float(s) / 2, float(y) + float(s) / 2, 0) for x, y, s in SMALL_DOT.findall(d)]
    return found


def decode_rule(tree: ET.Element) -> str | None:
    """The text a row of dots encodes: 7 slots per character, one empty slot between characters."""
    dots = dots_of(tree, ("d",))
    slots = {int(x // RULE_PITCH): bit for x, _, bit in dots}
    if not slots or len(slots) != len(dots):
        return None
    count = (max(slots) + 2) // RULE_PITCH
    expected = {RULE_PITCH * i + j for i in range(count) for j in range(CODE_BITS)}
    if set(slots) != expected:
        return None
    codes = [sum(slots[RULE_PITCH * i + j] << (CODE_BITS - 1 - j) for j in range(CODE_BITS)) for i in range(count)]
    return "".join(chr(code) for code in codes) if all(32 <= code < 127 for code in codes) else None


def check_svgs(name: str | None) -> None:
    hero_rel = f"heroes/{name}.svg" if name else None
    rules = {f"rules/{slug(title)}.svg": title for title in rule_titles(name)}
    trees: dict[str, ET.Element] = {}
    for rel in ["mark.svg", *([hero_rel] if hero_rel else []), *rules]:
        text = read(rel)
        if not text:
            continue
        try:
            tree = ET.fromstring(text)
        except ET.ParseError as exc:
            fail("parse", f"{rel} is not valid XML: {exc}")
            continue
        trees[rel] = tree
        check_svg_safety(tree, rel)
        accents = split_accent(svg_colours(tree, rel))
        if rel in rules:
            if accents:
                fail("accent", f"{rel} is quiet and must not use an accent; found {sorted(accents)}")
            if decode_rule(tree) != rules[rel]:
                fail("rules", f"{rel} does not encode {rules[rel]!r} in 7-bit ASCII")
            continue
        if accents != {"#e5251c"}:
            fail("accent", f"{rel} needs exactly one accent colour; found {sorted(accents)}")
    hero_tree = trees.get(hero_rel) if hero_rel else None
    if hero_tree is None:
        return
    tree = hero_tree
    if tree.get("viewBox") != f"0 0 {FRAME[0]} {FRAME[1]}":
        fail("hero", f"the hero viewBox is not 0 0 {FRAME[0]} {FRAME[1]}")
    ns = "{http://www.w3.org/2000/svg}"
    third = FRAME[0] / 3
    reds = [e for e in tree.iter(f"{ns}path") if e.get("class") == "r"]
    if len(reds) != 1 or len(list(tree.iter(f"{ns}g"))) != 1:
        fail("hero", "the hero needs exactly one red cell")
    least = FRAME[0]
    for path in tree.iter(f"{ns}path"):
        if path.get("fill", "").startswith("url(#"):
            for x, _, _, _ in rects_of(path.get("d", "")):
                least = min(least, x)
    for g in tree.iter(f"{ns}g"):
        m = re.fullmatch(r"translate\((\d+) (\d+)\)", g.get("transform", ""))
        if not m:
            fail("hero", "the red group has an unexpected transform")
            continue
        for path in g.iter(f"{ns}path"):
            for x, _, _, _ in rects_of(path.get("d", "")):
                least = min(least, int(m.group(1)) + x)
    if least < third:
        fail("hero", f"the weave starts at x={least}, inside the left third (x<{third:.0f})")


def check_llms(name: str | None) -> None:
    text = read("llms.txt")
    if not text:
        return
    links = re.findall(r"\]\((https://[^)]+)\)", text)
    expected = [f"https://github.com/{OWNER}/{r}" for r in PUBLIC_REPOS] + list(HOUSE_URLS) + list(SITE_LINKS.values())
    if sorted(links) != sorted(expected):
        fail("llms", "llms.txt must list exactly the public repositories, the site link and the two houses")
    if name and not text.startswith(f"# {name}\n\n> {TAGLINE}\n\n{SUBTITLE}\n\n## "):
        fail("llms", "llms.txt must start with the name, the line and the subtitle line")
    if not text.endswith(f"\n\n{FOOTER}\n"):
        fail("llms", "llms.txt must end with the footer line")
    found = group_lists(text, r"## ([^\n]+)\n\n((?:- [^\n]*\n?)+)")
    if [(t, r) for t, r in found if t != "Houses"] != [(title, list(repos)) for title, repos in GROUPS]:
        fail("llms", "llms.txt must follow the three groups, in order")
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
    check_files(name)
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
    check_css()
    check_svgs(name)
    check_llms(name)
    return list(failures)


LONG = " ".join(["word"] * 30) + "."
STYLE_LINK = '<link rel="stylesheet" href="style.css">'


def edit(docs: Path, name: str, old: str, new: str) -> None:
    path = docs / name
    text = path.read_text(encoding="utf-8")
    if old not in text:
        raise AssertionError(f"self-test is stale: {old!r} is not in docs/{name}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def edit_all(docs: Path, name: str, *pairs: tuple[str, str]) -> None:
    """Apply several edits to one file, in order."""
    for old, new in pairs:
        edit(docs, name, old, new)


def flip_first_dot(docs: Path, rel: str) -> None:
    """Turn the first big dot of an svg into a small one: one bit flipped."""
    path = docs / rel
    text = path.read_text(encoding="utf-8")
    hit = BIG_DOT.search(text)
    if hit is None:
        raise AssertionError(f"self-test is stale: no big dot in docs/{rel}")
    x, y, r = float(hit.group(1)), float(hit.group(2)), float(hit.group(3))
    end = text.index("Z", hit.end()) + 1
    square = f"M{x + r - 1:.2f} {y - 1:.2f}h2v2h-2Z"
    path.write_text(text[: hit.start()] + square + text[end:], encoding="utf-8")


def move_weave(docs: Path, hero: str) -> None:
    path = docs / hero
    text = path.read_text(encoding="utf-8")
    moved = re.sub(r'(fill="url\(#p\d\)" d="M)\d+', r"\g<1>100", text, count=1)
    if moved == text:
        raise AssertionError("self-test is stale: no weave mask found in the hero")
    path.write_text(moved, encoding="utf-8")


def site_copy(root: Path, changes: dict[str, object]) -> subprocess.CompletedProcess[bytes]:
    """Build a copy of the generator in root, with these keys of site.json changed."""
    (root / "src").mkdir(parents=True)
    for rel in ("build.py", "card.py", "src/style.css"):
        shutil.copy(ROOT / rel, root / rel)
    shutil.copytree(ROOT / "fonts", root / "fonts")
    data = json.loads((ROOT / "site.json").read_text(encoding="utf-8"))
    data.update(changes)
    (root / "site.json").write_text(json.dumps(data), encoding="utf-8")
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    return subprocess.run([sys.executable, str(root / "build.py")], capture_output=True, env=env)


def tagline_keeps_its_tail() -> bool:
    """True when a tagline whose last part has no end mark is still shown in full."""
    name = site_name()
    if name is None:
        return False
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "site"
        done = site_copy(root, {"tagline": "First part. Last part without a stop"})
        page = (root / "docs" / "index.html").read_text(encoding="utf-8") if done.returncode == 0 else ""
        return "<span>First part.</span>" in page and "<span>Last part without a stop</span>" in page


def build_rejects(changes: dict[str, object]) -> bool:
    """True when build.py exits 2 on a site.json with these changes and writes no svg outside docs/."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "site"
        done = site_copy(root, changes)
        outside = [p.name for p in Path(tmp).rglob("*.svg") if root / "docs" not in p.parents]
        return done.returncode == 2 and not outside


def build_needs_fonts() -> bool:
    """True when build.py exits 2 without fonts/ and writes no docs/."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "site"
        site_copy(root, {})
        shutil.rmtree(root / "fonts")
        shutil.rmtree(root / "docs")
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


Case = tuple[str, str | None, list[str], Callable[[Path], object]]


def self_test() -> None:
    global DOCS
    real = DOCS
    name = site_name()
    if not name:
        print("\n".join(failures))
        sys.exit(1)
    hero = f"heroes/{name}.svg"
    alt = f'alt="Weave pattern generated from the name {name}"'
    cases: list[Case] = [
        ("private name in style.css", "private", ["zzprivate"], lambda d: edit(d, "style.css", "box-sizing", "/* zzprivate */ box-sizing")),
        ("private name in the hero svg", "private", ["zzprivate"], lambda d: edit(d, hero, "<title>", "<title>zzprivate ")),
        ("private name in an html comment", "private", ["zzprivate"], lambda d: edit(d, "index.html", "<body>", "<body><!-- zzprivate -->")),
        ("private link", "links", [], lambda d: edit(d, "index.html", f"{OWNER}/bun-do", f"{OWNER}/zzprivate")),
        ("private rs name in llms.txt", "private", [], lambda d: edit(d, "llms.txt", "## Houses", "zz-rs\n\n## Houses")),
        ("long project line", "voice", [], lambda d: edit(d, "index.html", "Homebrew casks for", LONG + " Homebrew casks for")),
        ("long houses line", "voice", [], lambda d: edit(d, "index.html", "(deterministic quant engines)", "(" + LONG[:-1] + ")")),
        ("long line in llms.txt", "voice", [], lambda d: edit(d, "llms.txt", "Homebrew casks for", LONG + " Homebrew casks for")),
        ("alpha hex in a variable", "colour", [], lambda d: edit(d, "style.css", "--muted:#595959", "--muted:#59595980")),
        ("short alpha hex in a rule", "colour", [], lambda d: edit(d, "style.css", "box-sizing", "color:#fff8;box-sizing")),
        ("second accent", "accent", [], lambda d: edit(d, "style.css", "--rule:#d9d9d9", "--rule:#0000ff")),
        ("link leaves docs/", "links", [], lambda d: edit(d, "index.html", 'href="style.css"', 'href="../README.md"')),
        ("image leaves docs/", "links", [], lambda d: edit(d, "index.html", 'src="mark.svg"', 'src="../README.md"')),
        ("absolute local link", "links", [], lambda d: edit(d, "index.html", 'href="style.css"', 'href="/etc/hostname"')),
        ("protocol-relative link", "links", [], lambda d: edit(d, "index.html", 'href="style.css"', 'href="//example.com/x.css"')),
        ("Google Fonts stylesheet", "links", [], lambda d: edit(d, "index.html", STYLE_LINK, '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Other">' + STYLE_LINK)),
        ("font preconnect", "links", [], lambda d: edit(d, "index.html", STYLE_LINK, '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>' + STYLE_LINK)),
        ("remote stylesheet", "links", [], lambda d: edit(d, "index.html", 'href="style.css"', 'href="https://example.net/style.css"')),
        ("preload of a remote font", "links", [], lambda d: edit(d, "index.html", 'href="fonts/mm-weft.woff2"', 'href="https://fonts.gstatic.com/x.woff2"')),
        ("preload of a file that is not a font", "fonts", [], lambda d: edit(d, "index.html", 'href="fonts/mm-weft.woff2"', 'href="mark.svg"')),
        ("preload without crossorigin", "fonts", [], lambda d: edit(d, "index.html", 'type="font/woff2" crossorigin>', 'type="font/woff2">')),
        ("no preload", "fonts", [], lambda d: edit_all(d, "index.html", *[(f'<link rel="preload" href="fonts/{f}.woff2" as="font" type="font/woff2" crossorigin>\n', "") for f in ("mm-weft", "mm-sans")])),
        ("css font face from a font host", "links", [], lambda d: edit(d, "style.css", "url(fonts/mm-weft.woff2)", "url(https://fonts.gstatic.com/s/other/v1/x.woff2)")),
        ("css imports Google Fonts", "links", [], lambda d: edit(d, "style.css", ":root{", '@import url("https://fonts.googleapis.com/css2?family=Other");:root{')),
        ("css font face from a local file that is not the font", "fonts", [], lambda d: edit(d, "style.css", "url(fonts/mm-weft.woff2)", "url(fonts/mm-sans.woff2)")),
        ("css font face for another family", "fonts", [], lambda d: edit(d, "style.css", 'font-family: "machine-made Sans";', 'font-family: "Other";')),
        ("css font face without swap", "fonts", [], lambda d: edit(d, "style.css", "font-display: swap;", "font-display: block;")),
        ("font file is not a woff2", "fonts", [], lambda d: (d / "fonts" / "mm-sans.woff2").write_bytes(b"<svg/>")),
        ("font file missing", "files", [], lambda d: (d / "fonts" / "mm-weft.woff2").unlink()),
        ("font licence missing", "files", [], lambda d: (d / "fonts" / "mm-sans-OFL.txt").unlink()),
        ("extra font file", "files", [], lambda d: (d / "fonts" / "other.woff2").write_bytes(b"wOF2")),
        ("private repo in a font licence", "private", [], lambda d: edit(d, "fonts/mm-weft-OFL.txt", "SIL OPEN FONT", "github.com/machine-made/zzprivate SIL OPEN FONT")),
        ("upstream link outside its licence", "private", [], lambda d: edit(d, "fonts/mm-weft-OFL.txt", "SIL OPEN FONT", "github.com/tokotype/PlusJakartaSans SIL OPEN FONT")),
        ("money amount in a font licence", "forbidden", [], lambda d: edit(d, "fonts/mm-sans-OFL.txt", "SIL OPEN FONT", "$5 SIL OPEN FONT")),
        *[
            (f"{tag} tag", "no-js", [], lambda d, tag=tag: edit(d, "index.html", "<body>", f'<body><{tag} src="https://example.net/x"></{tag}>'))
            for tag in ("audio", "video", "source", "track", "iframe", "object", "embed")
        ],
        ("script tag", "no-js", [], lambda d: edit(d, "index.html", "</body>", "<script>1</script></body>")),
        ("image without alt", "a11y", [], lambda d: edit(d, "index.html", alt, 'alt=" "')),
        ("money amount", "forbidden", [], lambda d: edit(d, "llms.txt", "## Houses", "$5\n\n## Houses")),
        ("second page", "files", [], lambda d: (d / "second.html").write_text("<!doctype html>")),
        ("a row of dots encodes another title", "rules", [], lambda d: flip_first_dot(d, "rules/houses.svg")),
        ("a row of dots uses the accent", "accent", [], lambda d: edit(d, "rules/houses.svg", "<style>", "<style>.d{fill:#e5251c}")),
        ("a row of dots is missing", "files", [], lambda d: (d / "rules" / "houses.svg").unlink()),
        ("a row of dots is extra", "files", [], lambda d: (d / "rules" / "extra.svg").write_text("<svg/>")),
        ("a row of dots without aria-hidden", "a11y", [], lambda d: edit(d, "index.html", 'alt="" aria-hidden="true"', 'alt=""')),
        ("a section without its row of dots", "hero", [], lambda d: edit(d, "index.html", '<img class="punch" src="rules/houses.svg" width="376" height="8" alt="" aria-hidden="true">\n', "")),
        ("weave inside the left third", "hero", [], lambda d: move_weave(d, hero)),
        ("hero file is not valid XML", "parse", [], lambda d: (d / hero).write_text("<svg", encoding="utf-8")),
        ("header shows another image", "hero", [], lambda d: edit(d, "index.html", f'src="{hero}"', 'src="mark.svg"')),
        ("hero file missing", "files", [], lambda d: (d / hero).unlink()),
        ("non-ASCII in llms.txt", "voice", [], lambda d: edit(d, "llms.txt", "## Houses", "caf\u00e9\n\n## Houses")),
        ("subtitle line missing", "content", [], lambda d: edit(d, "index.html", f'<p class="subtitle">{SUBTITLE}</p>', "")),
        ("subtitle line changed", "content", [], lambda d: edit(d, "index.html", "A lab", "A job")),
        ("subtitle line before the tagline", "content", [], lambda d: edit_all(d, "index.html", (f'<p class="subtitle">{SUBTITLE}</p>', ""), ('<p class="tagline">', f'<p class="subtitle">{SUBTITLE}</p><p class="tagline">'))),
        ("subtitle line missing in llms.txt", "llms", [], lambda d: edit(d, "llms.txt", f"{SUBTITLE}\n\n", "")),
        ("old footer on the page", "content", [], lambda d: edit(d, "index.html", ", in spare time.", ".")),
        ("old footer in llms.txt", "llms", [], lambda d: edit(d, "llms.txt", ", in spare time.", ".")),
        ("footer missing in llms.txt", "llms", [], lambda d: edit(d, "llms.txt", f"\n\n{FOOTER}", "")),
        ("old subtitle line", "content", [], lambda d: edit(d, "index.html", "A lab run by machines.", "A hobby: side projects, made in spare time.")),
        ("how we work comes back", "projects", [], lambda d: edit(d, "index.html", '<main id="main">', '<main id="main"><h2 id="work">How we work</h2>')),
        ("a group heading is renamed", "projects", [], lambda d: edit(d, "index.html", ">Tools for agents<", ">Tools<")),
        ("two projects swap groups", "projects", [], lambda d: edit_all(d, "index.html", (f'{OWNER}/bun-do"', f'{OWNER}/tmp"'), (f'{OWNER}/pdf-next"', f'{OWNER}/bun-do"'), (f'{OWNER}/tmp"', f'{OWNER}/pdf-next"'))),
        ("a group heading is renamed in llms.txt", "llms", [], lambda d: edit(d, "llms.txt", "## Tools for agents", "## Tools")),
        ("site link missing", "links", [], lambda d: edit(d, "index.html", ' <a class="site" href="https://machine-made.github.io/chaos-atlas/">site</a>', "")),
        ("site link on another host", "links", [], lambda d: edit(d, "index.html", "https://machine-made.github.io/chaos-atlas/", "https://example.net/chaos-atlas/")),
        ("site link to another path", "links", [], lambda d: edit(d, "index.html", "https://machine-made.github.io/chaos-atlas/", "https://machine-made.github.io/other/")),
        ("accent in a fill attribute", "accent", [], lambda d: edit(d, hero, '<rect class="g"', '<rect fill="#0000ff" class="g"')),
        ("accent in a style attribute", "accent", [], lambda d: edit(d, "mark.svg", '<rect class="k"', '<path style="fill:#00f" class="k"')),
        ("accent in stop-color", "accent", [], lambda d: edit(d, "mark.svg", '<rect class="k"', '<path stop-color="#00ff00" class="k"')),
        ("named colour in a stroke", "accent", [], lambda d: edit(d, "mark.svg", '<rect class="k"', '<path stroke="red" class="k"')),
        ("named colour in an svg rule", "accent", [], lambda d: edit(d, "mark.svg", ".k{fill:", ".k{stroke:red;fill:")),
        ("gradient in the hero", "colour", [], lambda d: edit(d, hero, "<defs>", '<defs><linearGradient id="z"/>')),
        ("private name in a class value", "private", ["zzprivate"], lambda d: edit(d, "index.html", '<main id="main">', '<main id="main" class="zzprivate">')),
        ("private name in an id value", "private", ["zzprivate"], lambda d: edit(d, "index.html", 'id="houses"', 'id="zzprivate"')),
        ("unknown attribute", "attrs", [], lambda d: edit(d, "index.html", '<main id="main">', '<main id="main" data-x="1">')),
        ("css imports a remote file", "links", [], lambda d: edit(d, "style.css", ":root{", '@import url("https://example.net/x.css");:root{')),
        ("css string import", "links", [], lambda d: edit(d, "style.css", ":root{", '@import "https://example.net/x.css";:root{')),
        ("css url on a look-alike font host", "links", [], lambda d: edit(d, "style.css", ":root{", "a{background:url(https://fonts.gstatic.com.example.net/f.woff2)}:root{")),
        ("css url leaves docs/", "links", [], lambda d: edit(d, "style.css", ":root{", "a{background:url(../README.md)}:root{")),
        ("css data url", "links", [], lambda d: edit(d, "style.css", ":root{", "a{background:url(data:image/png;base64,AAAA)}:root{")),
        ("css uses a local file", None, [], lambda d: edit(d, "style.css", ":root{", "a{list-style-image:url(mark.svg)}:root{")),
        ("script in the hero svg", "no-js", [], lambda d: edit(d, hero, "<title>", "<script>1</script><title>")),
        ("event handler in the mark svg", "no-js", [], lambda d: edit(d, "mark.svg", '<rect class="k"', '<path onclick="x()" class="k"')),
        ("external href in the hero svg", "links", [], lambda d: edit(d, hero, "<defs>", '<defs><use href="https://example.net/x.svg#a"/>')),
        ("remote url in an svg rule", "links", [], lambda d: edit(d, hero, "<style>", "<style>.z{fill:url(https://example.net/x.svg#a)}")),
        ("css image-set", "links", [], lambda d: edit(d, "style.css", ":root{", 'a{background:image-set("mark.svg" 1x)}:root{')),
        ("css image()", "links", [], lambda d: edit(d, "style.css", ":root{", 'a{background:image("mark.svg")}:root{')),
        ("css prefixed cross-fade", "links", [], lambda d: edit(d, "style.css", ":root{", "a{background:-webkit-cross-fade(url(mark.svg),url(mark.svg),50%)}:root{")),
        ("css escaped function name", "css", [], lambda d: edit(d, "style.css", ":root{", "a{background:\\69mage-set(mark.svg 1x)}:root{")),
        ("image-set in an svg rule", "links", [], lambda d: edit(d, hero, "<style>", "<style>.z{fill:image-set(x 1x)}")),
        ("named colour in style.css", "accent", [], lambda d: edit(d, "style.css", "box-sizing", "color:red;box-sizing")),
        ("upper-case named colour", "accent", [], lambda d: edit(d, "style.css", "box-sizing", "color:BLUE;box-sizing")),
        ("named colour in a custom property", "accent", [], lambda d: edit(d, "style.css", "--rule:#d9d9d9", "--rule:blue")),
        ("named colour in a border", "accent", [], lambda d: edit(d, "style.css", "box-sizing", "border:1px solid tomato;box-sizing")),
        ("named colour in a var fallback", "accent", [], lambda d: edit(d, "style.css", "box-sizing", "color:var(--fg,navy);box-sizing")),
        ("system colour", "accent", [], lambda d: edit(d, "style.css", "box-sizing", "color:LinkText;box-sizing")),
        ("escaped colour name", "css", [], lambda d: edit(d, "style.css", "box-sizing", "color:\\72 ed;box-sizing")),
        ("colour mix function", "colour", [], lambda d: edit(d, "style.css", "box-sizing", "color:color-mix(in srgb,#fff,#000);box-sizing")),
        ("black, white and transparent are allowed", None, [], lambda d: edit(d, "style.css", "box-sizing", "color:black;background:WHITE;border-color:transparent;outline-color:currentColor;box-sizing")),
        ("a class with a colour name is not a colour", None, [], lambda d: edit(d, "style.css", ":root{", ".red:hover{margin:0}a:not(.tan){margin:0}:root{")),
        ("named colour in a page style block", "accent", [], lambda d: edit(d, "index.html", "<body>", "<body><style>a{color:red}</style>")),
        ("hex accent in a page style block", "accent", [], lambda d: edit(d, "index.html", "<body>", "<body><style>a{color:#00f}</style>")),
        ("accent as the fallback of a fragment paint", "accent", [], lambda d: edit(d, "mark.svg", '<rect class="k"', '<path fill="url(#a) #0000ff" class="k"')),
        ("named fallback of a fragment paint", "accent", [], lambda d: edit(d, "mark.svg", '<rect class="k"', '<path fill="url(#a) red" class="k"')),
        ("function fallback of a fragment paint", "colour", [], lambda d: edit(d, "mark.svg", '<rect class="k"', '<path fill="url(#a) rgb(0,0,255)" class="k"')),
        ("keyword fallback of a fragment paint", None, [], lambda d: edit(d, "mark.svg", '<rect class="k"', '<path fill="url(#a) currentColor" class="k"')),
        ("text colour as a hex grey", "contrast", [], lambda d: edit(d, "style.css", "box-sizing", "color:#777;box-sizing")),
        ("text colour from a low-contrast token", "contrast", [], lambda d: edit(d, "style.css", "box-sizing", "color:var(--rule);box-sizing")),
        ("text on a low-contrast background token", "contrast", [], lambda d: edit(d, "style.css", "box-sizing", "color:var(--fg);background:var(--muted);box-sizing")),
        ("background shorthand with more than a token", "contrast", [], lambda d: edit(d, "style.css", "box-sizing", "background:var(--bg) url(mark.svg);box-sizing")),
        ("text colour from an unknown token", "contrast", [], lambda d: edit(d, "style.css", "box-sizing", "color:var(--nope);box-sizing")),
        ("a pair of palette tokens is allowed", None, [], lambda d: edit(d, "style.css", "box-sizing", "color:var(--muted);background:var(--bg) !important;box-sizing")),
        ("upper-case colour function", "colour", [], lambda d: edit(d, "style.css", "box-sizing", "color:RGB(0,0,255);box-sizing")),
        ("upper-case gradient", "colour", [], lambda d: edit(d, "style.css", "box-sizing", "background:LINEAR-GRADIENT(red,blue);box-sizing")),
        ("base tag", "no-js", [], lambda d: edit(d, "index.html", "<body>", '<body><base href="https://example.net/">')),
        ("private name as a character reference in the hero", "private", ["zzprivate"], lambda d: edit(d, hero, "<title>", "<title>zz&#x70;rivate ")),
        ("private name as a nested reference in an attribute", "private", ["zzprivate"], lambda d: edit(d, "mark.svg", '<rect class="k"', '<path id="zz&amp;#112;rivate" class="k"')),
        ("private repo as a character reference in the hero", "private", [], lambda d: edit(d, hero, "<title>", "<title>github.com/&#x6d;achine-made/zzprivate ")),
        ("remote url in a filter attribute", "links", [], lambda d: edit(d, "mark.svg", '<rect class="k"', '<path filter="url(https://example.net/x.svg#f)" class="k"')),
        ("remote url in a mask attribute", "links", [], lambda d: edit(d, hero, '<rect class="g"', '<rect mask="url(//example.net/x.svg#m)" class="g"')),
        ("remote url in a clip-path attribute", "links", [], lambda d: edit(d, hero, '<rect class="g"', '<rect clip-path="url(x.svg#c)" class="g"')),
        ("remote url in a fill attribute", "links", [], lambda d: edit(d, "mark.svg", '<rect class="k"', '<path fill="url(https://example.net/x.svg#f)" class="k"')),
        ("local fragment in a filter attribute", None, [], lambda d: edit(d, "mark.svg", '<rect class="k"', '<path filter="url(#f)" class="k"')),
        ("USD before an amount", "forbidden", [], lambda d: edit(d, "llms.txt", "## Houses", "USD 5\n\n## Houses")),
        ("CHF before an amount", "forbidden", [], lambda d: edit(d, "llms.txt", "## Houses", "chf 5\n\n## Houses")),
        ("EUR before an amount", "forbidden", [], lambda d: edit(d, "llms.txt", "## Houses", "Eur5\n\n## Houses")),
        ("USD after an amount", "forbidden", [], lambda d: edit(d, "llms.txt", "## Houses", "5 USD\n\n## Houses")),
        ("private name as an element name", "private", ["zzprivate"], lambda d: edit(d, "index.html", "<body>", "<body><zzprivate></zzprivate>")),
    ]
    total, bad = 0, 0

    def report(ok: bool, title: str) -> None:
        nonlocal total, bad
        total += 1
        if not ok:
            bad += 1
            print(f"SELF-TEST FAIL: {title}")

    with tempfile.TemporaryDirectory() as tmp:
        for title, rule, deny, mutate in cases + [("clean copy", None, [], lambda d: None)]:
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
            {"groups": [{"title": "A", "projects": [{"repo": "x", "line": "y"}]}, {"title": "a!", "projects": [{"repo": "z", "line": "y"}]}]},
            {"groups": [{"title": "A", "projects": [{"repo": "x", "line": "y"}, {"repo": "x", "line": "y"}]}]},
            {"groups": [{"title": "A", "projects": [{"repo": "x", "line": "y", "site": "http://x"}]}]},
            {"subtitle": 5},
        ]
        for changes in bad_sites:
            report(build_rejects(changes), f"build.py accepted {str(changes)[:60]}")
        for bad_year in (True, False, "2026", 2026.0, None):
            report(build_rejects({"year": bad_year}), f"build.py accepted the year {bad_year!r}")
        report(renamed_site_passes("loom-x"), "a site under another name does not pass the checks")
        report(build_needs_fonts(), "build.py builds without the fonts in fonts/")
        report(tagline_keeps_its_tail(), "build.py cuts a tagline whose last part has no end mark")
        missing = str(Path(tmp) / "missing")
        denied = Path(tmp) / "deny.txt"
        denied.write_text("# a comment\n\nzz one\n  zz two  \n#zz three\n", encoding="utf-8")
        report(load_deny(str(denied)) == ["zz one", "zz two"], "load_deny does not keep one name per line")
        report(cli_fails(["--deny"], "FAIL args:"), "--deny without a file")
        report(cli_fails(["--deny", missing], "FAIL deny:"), "--deny with a missing file")
        report(cli_fails(["--no-such-flag"], "FAIL args:"), "an unknown flag")
    if bad:
        sys.exit(1)
    print(f"SELF-TEST OK ({total} cases)")


def main() -> None:
    args = parse_args(sys.argv[1:])
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
