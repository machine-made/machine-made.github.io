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
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parent
DOCS = ROOT / "docs"

OWNER = "machine-made"
PUBLIC_REPOS = (
    "minuit2-rs",
    "libsvm-rs",
    "nebula-quanta",
    "pdf-next",
    "vscode-pdf-next",
    "vscode-diff-next",
    "bun-do",
    "homebrew-tap",
)
HOUSE_URLS = ("https://github.com/openfluids", "https://github.com/BoringQuantSystems")
TAGLINE = "Made by machines. Proven for machines."
FOOTER = "Made by agents. Directed by a person."
BASE_FILES = {"index.html", "style.css", "mark.svg", "llms.txt"}
FILE_NAME = re.compile(r"[a-z0-9][a-z0-9._-]*")
FONT_HOSTS = ("fonts.googleapis.com", "fonts.gstatic.com")
FRAME = (1408, 469)
FORBIDDEN = re.compile(
    r"[$\u20ac\u00a3]\s?[0-9]|[0-9]\s?(?:usd|chf|eur)\b|tokens|punchcard|night-shift|nexus", re.I
)
VOID = {"meta", "link", "img", "br", "hr", "input", "source", "area", "base", "col", "embed", "wbr"}
GITHUB = re.compile(r"github\.com/[\w.-]+(?:/[\w.-]+)*", re.I)
RS_NAME = re.compile(r"(?<![\w-])[a-z0-9][a-z0-9._-]*-rs(?![\w-])", re.I)
MAX_WORDS = 25
ALLOWED_ATTRS = {
    "lang", "charset", "name", "content", "rel", "href", "type", "crossorigin", "class", "id",
    "src", "width", "height", "alt", "loading", "aria-labelledby",
}
PAINT_PROPS = ("fill", "stroke", "stop-color", "flood-color", "lighting-color", "color")
PAINT_DECL = re.compile(r"(?<![\w-])(fill|stroke|stop-color|flood-color|lighting-color|color)\s*:\s*([^;}]+)")
PAINT_KEYWORDS = {"none", "currentcolor", "inherit", "transparent", "initial", "unset", "context-fill", "context-stroke"}
FRAGMENT_URL = re.compile(r"url\(\s*#[\w.-]+\s*\)(\s+\S+)?")
URL_REF = re.compile(r"url\(\s*(['\"]?)(.*?)\1\s*\)", re.I | re.S)
IMPORT_REF = re.compile(r"@import\s+(['\"])(.*?)\1", re.I | re.S)
SVG_FORBIDDEN = {
    "script", "foreignObject", "image", "iframe", "object", "embed", "audio", "video",
    "linearGradient", "radialGradient", "stop",
}

failures = []


def fail(rule, message):
    line = f"FAIL {rule}: {message}"
    if line not in failures:
        failures.append(line)


def site_name():
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


class Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack, self.ids, self.links, self.imgs, self.tags = [], [], [], [], []
        self.text, self.values, self.headings = [], [], []
        self.hidden, self.paragraphs, self.paragraph = [], [], None
        self.styles, self.unknown_attrs = [], []
        self.first_link = None
        self.heading = None
        self.problems = []

    def handle_starttag(self, tag, attrs):
        names = [k for k, _ in attrs]
        if len(set(names)) != len(names):
            self.problems.append(f"<{tag}> repeats an attribute")
        a = dict(attrs)
        self.tags.append(tag)
        if "id" in a:
            self.ids.append(a["id"])
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
            self.links.append({"href": a["href"], "rel": a.get("rel", ""), "tag": "link"})
        if tag == "img":
            self.imgs.append(a)
        if tag in ("h1", "h2", "h3"):
            self.heading = [tag, ""]
        if tag == "p":
            self.paragraph = ""
        if tag not in VOID:
            self.stack.append(tag)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID and self.stack and self.stack[-1] == tag:
            self.stack.pop()

    def handle_endtag(self, tag):
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

    def handle_comment(self, data):
        self.hidden.append(data)

    def handle_data(self, data):
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

    def error(self, message):
        self.problems.append(message)


def luminance(hexcolour):
    h = hexcolour.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    channels = []
    for i in (0, 2, 4):
        c = int(h[i : i + 2], 16) / 255
        channels.append(c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4)
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def contrast(a, b):
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


HEX = re.compile(r"#[0-9a-fA-F]+\b")
FUNC = re.compile(r"\b(?:rgba?|hsla?|hwb|lab|lch|oklab|oklch|color)\(")


def colours_of(text, where):
    """Return the set of 6-digit colours in text; fail on forms that hide a colour."""
    found = set()
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
    if "gradient" in text:
        fail("colour", f"{where} uses a gradient")
    return found


def split_accent(colours, where):
    greys = {c for c in colours if c[1:3] == c[3:5] == c[5:7]}
    accents = colours - greys
    return accents


def read(rel):
    path = DOCS / rel
    if not path.is_file():
        fail("files", f"{rel} is missing; run python3 build.py")
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def check_files(hero_rel):
    wanted = BASE_FILES | ({hero_rel} if hero_rel else set())
    present = {p.relative_to(DOCS).as_posix() for p in DOCS.rglob("*") if p.is_file()}
    for extra in sorted(present - wanted):
        fail("files", f"docs/{extra} is not part of the one-page site")
    for missing in sorted(wanted - present):
        fail("files", f"docs/{missing} is missing; run python3 build.py")


def local_target(href):
    """The file a local link names, or None when it names nothing or leaves docs/."""
    path = unquote(href.split("#", 1)[0].split("?", 1)[0])
    if not path:
        return None
    root = DOCS.resolve()
    target = (DOCS / path).resolve()
    return target if root in target.parents else None


def check_html(page, html_text, name, hero_rel):
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
    for forbidden in ("script", "iframe", "object", "embed", "form", "input", "button"):
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
    if hero_rel and not any(img.get("src") == hero_rel for img in page.imgs):
        fail("hero", f"the header must show {hero_rel}")
    first = page.first_link or {}
    if first.get("href") != "#main" or "main" not in page.ids:
        fail("a11y", "the first link must be a skip link to #main")
    for img in page.imgs:
        if not (img.get("alt") or "").strip():
            fail("a11y", f"image {img.get('src')} has no alt text")
        if not (img.get("width") and img.get("height")):
            fail("responsive", f"image {img.get('src')} has no width and height")
        target = local_target(img.get("src", ""))
        if target is None or not target.is_file():
            fail("links", f"image {img.get('src')} does not resolve inside docs/")
    for link in page.links:
        href = link.get("href", "")
        parts = urlsplit(href)
        if href.startswith("#"):
            if href[1:] not in page.ids:
                fail("links", f"{href} points to no id")
        elif parts.scheme or parts.netloc:
            if parts.scheme.lower() != "https":
                fail("links", f"{href} is not an https link")
            elif link.get("tag") == "link":
                if parts.hostname not in FONT_HOSTS or parts.username or parts.port:
                    fail("links", f"{href} is an external resource that is not a font")
            elif not (
                href in HOUSE_URLS
                or any(href == f"https://github.com/{OWNER}/{repo}" for repo in PUBLIC_REPOS)
            ):
                fail("links", f"{href} is not in the public list")
        else:
            target = local_target(href)
            if target is None or not target.is_file():
                fail("links", f"{href} does not resolve inside docs/")


def check_refs(text, where, kind):
    """url() and @import targets: css may load the two font hosts and local files; svg only #fragments."""
    targets = [m.group(2).strip() for m in URL_REF.finditer(text)]
    targets += [m.group(2).strip() for m in IMPORT_REF.finditer(text)]
    for target in targets:
        if target.startswith("#"):
            continue
        parts = urlsplit(target)
        if kind == "svg":
            fail("links", f"{where} refers to {target[:50]!r}; an svg may refer only to its own ids")
        elif parts.scheme or parts.netloc:
            font = parts.scheme.lower() == "https" and parts.hostname in FONT_HOSTS
            if not font or parts.username or parts.port:
                fail("links", f"{where} loads {target[:50]!r}; only the two font hosts and local files are allowed")
        else:
            local = local_target(target)
            if local is None or not local.is_file():
                fail("links", f"{where} refers to {target[:50]!r}, which is not a file inside docs/")


def sentences_of(paragraph):
    return re.split(r"(?<=[.!?])\s+", paragraph.strip())


def check_prose(paragraphs, where):
    for paragraph in paragraphs:
        for sentence in sentences_of(paragraph):
            if len(sentence.split()) > MAX_WORDS:
                fail("voice", f"{where}: a sentence has more than {MAX_WORDS} words: {sentence[:40]}")


def check_content(page, html_text):
    text = " ".join(" ".join(page.text).split())
    for needed in (TAGLINE, FOOTER):
        if needed not in text:
            fail("content", f'the page lacks "{needed}"')
    hrefs = [l.get("href", "") for l in page.links if l.get("tag") != "link"]
    repo_links = [h for h in hrefs if h.startswith(f"https://github.com/{OWNER}/")]
    expected = [f"https://github.com/{OWNER}/{repo}" for repo in PUBLIC_REPOS]
    if sorted(repo_links) != sorted(expected):
        fail("projects", "the project links are not exactly the eight public repositories")
    for url in HOUSE_URLS:
        if hrefs.count(url) != 1:
            fail("houses", f"{url} must be linked once")
    if any(kind == "h3" for kind, _ in page.headings):
        fail("projects", "the page has headings below h2; the project list is a plain list")
    work = re.search(r"How we work.*?</h2>\s*<div class=\"lead\">(.*?)</div>", html_text, re.S)
    lead = re.findall(r"<p>(.*?)</p>", work.group(1)) if work else []
    if not 2 <= sum(len(sentences_of(p)) for p in lead) <= 3:
        fail("content", "How we work needs two or three sentences")
    check_prose(page.paragraphs, "index.html")
    return " ".join([text] + page.values + page.hidden)


def emitted(visible):
    """Every emitted file as (name, text). The page counts as what a reader or a crawler gets."""
    yield "index.html", visible
    for path in sorted(DOCS.rglob("*")):
        name = path.relative_to(DOCS).as_posix()
        if path.is_file() and name != "index.html":
            yield name, path.read_text(encoding="utf-8", errors="replace")


def check_leaks(visible, deny):
    house_hosts = {u.split("//", 1)[1] for u in HOUSE_URLS}
    for name, source in emitted(visible):
        if not source.isascii():
            fail("voice", f"docs/{name} has characters that are not plain ASCII")
        for match in GITHUB.findall(source):
            ok = match in house_hosts or any(
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


def check_forbidden():
    for path in sorted(DOCS.rglob("*")):
        if path.is_file():
            hit = FORBIDDEN.search(path.read_text(encoding="utf-8", errors="replace"))
            if hit:
                fail("forbidden", f"docs/{path.relative_to(DOCS).as_posix()} contains {hit.group(0)!r}")


def check_css():
    css = read("style.css")
    if not css:
        return
    root = re.search(r":root\{([^}]*)\}", css)
    dark = re.search(r"prefers-color-scheme:\s*dark\)\{:root\{([^}]*)\}", css)
    if not root or not dark:
        fail("dark", "style.css needs :root colours for light and for prefers-color-scheme: dark")
        return

    def vars_of(block):
        found = {}
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
    accents = split_accent(colours_of(css, "style.css"), "style.css")
    if accents != {light["red"].lower()}:
        fail("accent", f"style.css needs exactly one accent colour, the red; found {sorted(accents)}")
    if re.search(r"\bnowrap\b|(?<![-\w])width:\s*\d{3,}px", css):
        fail("responsive", "style.css forces a width that can scroll")


def rects_of(d):
    for m in re.finditer(r"M(-?\d+) (-?\d+)h(\d+)v(\d+)h-\d+z", d):
        x, y, w, h = (int(g) for g in m.groups())
        yield x, y, w, h


def paint_colours(value, where):
    v = value.strip()
    if v.lower() in PAINT_KEYWORDS or FRAGMENT_URL.fullmatch(v):
        return set()
    if re.fullmatch(r"#[0-9a-fA-F]+", v):
        return colours_of(v, where)
    fail("colour", f"{where} paints with {v[:30]!r}; write the colour as hex")
    return set()


def svg_colours(tree, where):
    """Every colour an svg sets: style rules, style attributes and paint attributes."""
    found = set()
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
            check_refs(text, where, "svg")
    return found


def check_svg_safety(tree, where):
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


def check_svgs(hero_rel):
    trees = {}
    for rel in ("mark.svg", hero_rel):
        text = read(rel) if rel else ""
        if not text:
            continue
        try:
            tree = ET.fromstring(text)
        except ET.ParseError as exc:
            fail("parse", f"{rel} is not valid XML: {exc}")
            continue
        trees[rel] = tree
        check_svg_safety(tree, rel)
        accents = split_accent(svg_colours(tree, rel), rel)
        if accents != {"#e5251c"}:
            fail("accent", f"{rel} needs exactly one accent colour; found {sorted(accents)}")
    tree = trees.get(hero_rel)
    if tree is None:
        return
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


def check_llms(name):
    text = read("llms.txt")
    if not text:
        return
    links = re.findall(r"\]\((https://[^)]+)\)", text)
    expected = [f"https://github.com/{OWNER}/{r}" for r in PUBLIC_REPOS] + list(HOUSE_URLS)
    if sorted(links) != sorted(expected):
        fail("llms", "llms.txt must list exactly the eight public repositories and the two houses")
    if name and not text.startswith(f"# {name}\n\n> {TAGLINE}"):
        fail("llms", "llms.txt must start with the name and the line")
    lines = (re.sub(r"^[#>-]+\s*", "", line) for line in text.splitlines())
    check_prose([re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", line) for line in lines], "llms.txt")


class Args(argparse.ArgumentParser):
    def error(self, message):
        print(f"FAIL args: {message}")
        sys.exit(2)


def parse_args(argv):
    parser = Args(description="Check the built site in docs/.", allow_abbrev=False)
    parser.add_argument("--deny", metavar="FILE", help="names that must not appear in the output")
    parser.add_argument("--self-test", action="store_true", help="break a copy of docs/ and check the breaks are caught")
    return parser.parse_args(argv)


def load_deny(path):
    path = path or os.environ.get("MM_DENY_FILE")
    if not path:
        return []
    try:
        names = Path(path).read_text(encoding="utf-8").split()
    except OSError as exc:
        print(f"FAIL deny: cannot read the deny file: {exc.strerror}")
        sys.exit(2)
    return [n for n in names if n and not n.startswith("#")]


def run_checks(deny):
    del failures[:]
    name = site_name()
    hero_rel = f"heroes/{name}.svg" if name else None
    check_files(hero_rel)
    html_text = read("index.html")
    if html_text:
        page = Page()
        page.feed(html_text)
        page.close()
        check_html(page, html_text, name, hero_rel)
        visible = check_content(page, html_text)
        check_leaks(visible, deny)
    check_forbidden()
    check_css()
    check_svgs(hero_rel)
    check_llms(name)
    return list(failures)


LONG = " ".join(["word"] * 30) + "."


def edit(docs, name, old, new):
    path = docs / name
    text = path.read_text(encoding="utf-8")
    if old not in text:
        raise AssertionError(f"self-test is stale: {old!r} is not in docs/{name}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def move_weave(docs, hero):
    path = docs / hero
    text = path.read_text(encoding="utf-8")
    moved = re.sub(r'(fill="url\(#p\d\)" d="M)\d+', r"\g<1>100", text, count=1)
    if moved == text:
        raise AssertionError("self-test is stale: no weave mask found in the hero")
    path.write_text(moved, encoding="utf-8")


def site_copy(root, name, tagline=None):
    """Build a copy of the generator in root, with another name and, if given, another tagline."""
    (root / "src").mkdir(parents=True)
    for rel in ("build.py", "src/style.css"):
        shutil.copy(ROOT / rel, root / rel)
    data = json.loads((ROOT / "site.json").read_text(encoding="utf-8"))
    data["name"] = name
    if tagline is not None:
        data["tagline"] = tagline
    (root / "site.json").write_text(json.dumps(data), encoding="utf-8")
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    return subprocess.run([sys.executable, str(root / "build.py")], capture_output=True, env=env)


def tagline_keeps_its_tail():
    """True when a tagline whose last part has no end mark is still shown in full."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "site"
        done = site_copy(root, site_name(), tagline="First part. Last part without a stop")
        page = (root / "docs" / "index.html").read_text(encoding="utf-8") if done.returncode == 0 else ""
        return "<span>First part.</span>" in page and "<span>Last part without a stop</span>" in page


def build_rejects(bad_name):
    """True when build.py exits 2 on bad_name and writes no svg outside docs/."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "site"
        done = site_copy(root, bad_name)
        outside = [p.name for p in Path(tmp).rglob("*.svg") if root / "docs" not in p.parents]
        return done.returncode == 2 and not outside


def renamed_site_passes(new_name):
    """True when a site built under another name passes every check."""
    global ROOT, DOCS
    real_root, real_docs = ROOT, DOCS
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "site"
        if site_copy(root, new_name).returncode != 0:
            return False
        ROOT, DOCS = root, root / "docs"
        try:
            return not run_checks([])
        finally:
            ROOT, DOCS = real_root, real_docs


def cli_fails(args, prefix):
    """True when check_site.py exits 2 with exactly one line that starts with prefix."""
    env = {k: v for k, v in os.environ.items() if k != "MM_DENY_FILE"}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    done = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), *args], capture_output=True, text=True, env=env
    )
    lines = done.stdout.splitlines()
    return done.returncode == 2 and len(lines) == 1 and lines[0].startswith(prefix) and not done.stderr


def self_test():
    global DOCS
    real = DOCS
    name = site_name()
    if not name:
        print("\n".join(failures))
        sys.exit(1)
    hero = f"heroes/{name}.svg"
    alt = f'alt="Weave pattern generated from the name {name}"'
    cases = [
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
        ("look-alike font host", "links", [], lambda d: edit(d, "index.html", 'href="https://fonts.gstatic.com"', 'href="https://fonts.gstatic.com.example.net"')),
        ("font host with userinfo", "links", [], lambda d: edit(d, "index.html", 'href="https://fonts.googleapis.com"', 'href="https://fonts.googleapis.com@example.net"')),
        ("script tag", "no-js", [], lambda d: edit(d, "index.html", "</body>", "<script>1</script></body>")),
        ("image without alt", "a11y", [], lambda d: edit(d, "index.html", alt, 'alt=" "')),
        ("money amount", "forbidden", [], lambda d: edit(d, "llms.txt", "## Houses", "$5\n\n## Houses")),
        ("second page", "files", [], lambda d: (d / "second.html").write_text("<!doctype html>")),
        ("weave inside the left third", "hero", [], lambda d: move_weave(d, hero)),
        ("hero file is not valid XML", "parse", [], lambda d: (d / hero).write_text("<svg", encoding="utf-8")),
        ("header shows another image", "hero", [], lambda d: edit(d, "index.html", f'src="{hero}"', 'src="mark.svg"')),
        ("hero file missing", "files", [], lambda d: (d / hero).unlink()),
        ("non-ASCII in llms.txt", "voice", [], lambda d: edit(d, "llms.txt", "## Houses", "caf\u00e9\n\n## Houses")),
        ("four sentences in how we work", "content", [], lambda d: edit(d, "index.html", "A benchmark has a script and a claim has a test.", "A benchmark has a script. A claim has a test.")),
        ("accent in a fill attribute", "accent", [], lambda d: edit(d, hero, '<rect class="g"', '<rect fill="#0000ff" class="g"')),
        ("accent in a style attribute", "accent", [], lambda d: edit(d, "mark.svg", '<rect class="k"', '<rect style="fill:#00f" class="k"')),
        ("accent in stop-color", "accent", [], lambda d: edit(d, "mark.svg", '<rect class="k"', '<rect stop-color="#00ff00" class="k"')),
        ("named colour in a stroke", "colour", [], lambda d: edit(d, "mark.svg", '<rect class="k"', '<rect stroke="red" class="k"')),
        ("named colour in an svg rule", "colour", [], lambda d: edit(d, "mark.svg", ".k{fill:", ".k{stroke:red;fill:")),
        ("gradient in the hero", "colour", [], lambda d: edit(d, hero, "<defs>", '<defs><linearGradient id="z"/>')),
        ("private name in a class value", "private", ["zzprivate"], lambda d: edit(d, "index.html", '<main id="main">', '<main id="main" class="zzprivate">')),
        ("private name in an id value", "private", ["zzprivate"], lambda d: edit(d, "index.html", 'id="work"', 'id="zzprivate"')),
        ("unknown attribute", "attrs", [], lambda d: edit(d, "index.html", '<main id="main">', '<main id="main" data-x="1">')),
        ("css imports a remote file", "links", [], lambda d: edit(d, "style.css", ":root{", '@import url("https://example.net/x.css");:root{')),
        ("css string import", "links", [], lambda d: edit(d, "style.css", ":root{", '@import "https://example.net/x.css";:root{')),
        ("css url on a look-alike font host", "links", [], lambda d: edit(d, "style.css", ":root{", "a{background:url(https://fonts.gstatic.com.example.net/f.woff2)}:root{")),
        ("css url leaves docs/", "links", [], lambda d: edit(d, "style.css", ":root{", "a{background:url(../README.md)}:root{")),
        ("css data url", "links", [], lambda d: edit(d, "style.css", ":root{", "a{background:url(data:image/png;base64,AAAA)}:root{")),
        ("css uses a font host and a local file", None, [], lambda d: edit(d, "style.css", ":root{", '@import url("https://fonts.googleapis.com/css2?family=Geist");a{background:url(mark.svg)}:root{')),
        ("script in the hero svg", "no-js", [], lambda d: edit(d, hero, "<title>", "<script>1</script><title>")),
        ("event handler in the mark svg", "no-js", [], lambda d: edit(d, "mark.svg", '<rect class="k"', '<rect onclick="x()" class="k"')),
        ("external href in the hero svg", "links", [], lambda d: edit(d, hero, "<defs>", '<defs><use href="https://example.net/x.svg#a"/>')),
        ("remote url in an svg rule", "links", [], lambda d: edit(d, hero, "<style>", "<style>.z{fill:url(https://example.net/x.svg#a)}")),
    ]
    total, bad = 0, 0

    def report(ok, title):
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
            report(build_rejects(bad_name), f"build.py accepted the site name {bad_name!r}")
        report(renamed_site_passes("loom-x"), "a site under another name does not pass the checks")
        report(tagline_keeps_its_tail(), "build.py cuts a tagline whose last part has no end mark")
        missing = str(Path(tmp) / "missing")
        report(cli_fails(["--deny"], "FAIL args:"), "--deny without a file")
        report(cli_fails(["--deny", missing], "FAIL deny:"), "--deny with a missing file")
        report(cli_fails(["--no-such-flag"], "FAIL args:"), "an unknown flag")
    if bad:
        sys.exit(1)
    print(f"SELF-TEST OK ({total} cases)")


def main():
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
