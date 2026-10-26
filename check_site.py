#!/usr/bin/env python3
"""Check the built site in docs/. Standard library only.

Prints OK and exits 0 when every rule holds. Otherwise prints one line per failure and exits 1.

Private repository names are not kept in this repository. Rules that need them read a list
from a file outside the repository: `python3 check_site.py --deny FILE` or MM_DENY_FILE=FILE.
FILE has one name per line. Without it, the allowlist rules still reject every link and every
repository-shaped name that is not public.
"""

import json
import os
import re
import sys
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path

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
FILES = {"index.html", "style.css", "mark.svg", "llms.txt", "heroes/machine-made.svg"}
FONT_HOSTS = ("https://fonts.googleapis.com", "https://fonts.gstatic.com")
FRAME = (1408, 469)
FORBIDDEN = re.compile(
    r"[$\u20ac\u00a3]\s?[0-9]|[0-9]\s?(?:usd|chf|eur)\b|tokens|punchcard|night-shift|nexus", re.I
)
VOID = {"meta", "link", "img", "br", "hr", "input", "source", "area", "base", "col", "embed", "wbr"}
GITHUB = re.compile(r"github\.com/[\w.-]+(?:/[\w.-]+)*", re.I)
RS_NAME = re.compile(r"(?<![\w-])[a-z0-9][a-z0-9._-]*-rs(?![\w-])", re.I)
MAX_WORDS = 25

failures = []


def fail(rule, message):
    failures.append(f"FAIL {rule}: {message}")


class Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack, self.ids, self.links, self.imgs, self.tags = [], [], [], [], []
        self.text, self.values, self.headings = [], [], []
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
            if value is not None and key not in ("class", "id", "charset", "name", "rel", "lang"):
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

    def handle_data(self, data):
        if self.stack and self.stack[-1] in ("style", "script"):
            return
        self.text.append(data)
        if self.heading:
            self.heading[1] += data

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


HEX = re.compile(r"#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b")
FUNC = re.compile(r"\b(?:rgba?|hsla?|hwb|lab|lch|oklab|oklch|color)\(")


def colours_of(text, where):
    """Return the set of 6-digit colours in text; fail on forms that hide a colour."""
    found = set()
    for hit in HEX.findall(text):
        h = hit.lstrip("#")
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        found.add("#" + h[:6].lower())
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
    return path.read_text(encoding="utf-8")


def check_files():
    present = {p.relative_to(DOCS).as_posix() for p in DOCS.rglob("*") if p.is_file()}
    for extra in sorted(present - FILES):
        fail("files", f"docs/{extra} is not part of the one-page site")
    for missing in sorted(FILES - present):
        fail("files", f"docs/{missing} is missing; run python3 build.py")


def local_target(href, base=DOCS):
    path = href.split("#", 1)[0].split("?", 1)[0]
    return (base / path) if path else None


def check_html(page, html_text):
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
            fail("links", f"image {img.get('src')} does not resolve")
    for link in page.links:
        href = link.get("href", "")
        if href.startswith("#"):
            if href[1:] not in page.ids:
                fail("links", f"{href} points to no id")
        elif href.startswith("https://"):
            if link.get("tag") == "link":
                if not href.startswith(FONT_HOSTS):
                    fail("links", f"{href} is an external resource that is not a font")
            elif not (
                href in HOUSE_URLS
                or any(href == f"https://github.com/{OWNER}/{repo}" for repo in PUBLIC_REPOS)
            ):
                fail("links", f"{href} is not in the public list")
        elif re.match(r"[a-z][a-z0-9+.-]*:", href):
            fail("links", f"{href} uses a scheme that is not https")
        else:
            target = local_target(href)
            if target is None or not target.is_file():
                fail("links", f"{href} does not resolve")


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
    sentences = re.findall(r"<p>(.*?)</p>", work.group(1)) if work else []
    if not 2 <= len(sentences) <= 3:
        fail("content", "How we work needs two or three sentences")
    for sentence in sentences:
        if len(sentence.split()) > MAX_WORDS:
            fail("voice", f"sentence is longer than {MAX_WORDS} words: {sentence[:40]}")
    visible = text + " " + " ".join(page.values)
    if not visible.isascii():
        fail("voice", "the page has characters that are not plain ASCII")
    return visible


def check_leaks(visible, deny):
    for source in [visible] + [read(f) for f in ("llms.txt", "heroes/machine-made.svg", "mark.svg")]:
        for match in GITHUB.findall(source):
            ok = match in {u.split("//", 1)[1] for u in HOUSE_URLS} or any(
                match == f"github.com/{OWNER}/{repo}" for repo in PUBLIC_REPOS
            )
            if not ok:
                fail("private", f"{match} is not in the public list")
        for name in RS_NAME.findall(source):
            if name.lower() not in PUBLIC_REPOS:
                fail("private", f"{name} looks like a repository that is not in the public list")
        for name in deny:
            if re.search(rf"(?<![\w]){re.escape(name)}(?![\w])", source, re.I):
                fail("private", f"a private repository name appears in the output ({len(name)} letters)")
    for path in DOCS.rglob("*"):
        for name in deny:
            if path.is_file() and re.search(re.escape(name), path.name, re.I):
                fail("private", f"a private name is part of the file name {path.name}")


def check_forbidden():
    for path in sorted(DOCS.rglob("*")):
        if path.is_file():
            hit = FORBIDDEN.search(path.read_text(encoding="utf-8"))
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
        return dict(re.findall(r"--([a-z-]+):\s*(#[0-9a-fA-F]{3,6})", block))

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
    accents = split_accent(colours_of(css, "style.css"), "style.css")
    if accents != {light["red"].lower()}:
        fail("accent", f"style.css needs exactly one accent colour, the red; found {sorted(accents)}")
    if re.search(r"\bnowrap\b|(?<![-\w])width:\s*\d{3,}px", css):
        fail("responsive", "style.css forces a width that can scroll")


def rects_of(d):
    for m in re.finditer(r"M(-?\d+) (-?\d+)h(\d+)v(\d+)h-\d+z", d):
        x, y, w, h = (int(g) for g in m.groups())
        yield x, y, w, h


def check_svgs():
    red = None
    for rel in ("mark.svg", "heroes/machine-made.svg"):
        text = read(rel)
        if not text:
            continue
        try:
            tree = ET.fromstring(text)
        except ET.ParseError as exc:
            fail("parse", f"{rel} is not valid XML: {exc}")
            continue
        style = " ".join(e.text or "" for e in tree.iter("{http://www.w3.org/2000/svg}style"))
        accents = split_accent(colours_of(style, rel), rel)
        if accents != {"#e5251c"}:
            fail("accent", f"{rel} needs exactly one accent colour; found {sorted(accents)}")
        red = red or accents
    hero = read("heroes/machine-made.svg")
    if not hero:
        return
    tree = ET.fromstring(hero)
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


def check_llms():
    text = read("llms.txt")
    if not text:
        return
    links = re.findall(r"\]\((https://[^)]+)\)", text)
    expected = [f"https://github.com/{OWNER}/{r}" for r in PUBLIC_REPOS] + list(HOUSE_URLS)
    if sorted(links) != sorted(expected):
        fail("llms", "llms.txt must list exactly the eight public repositories and the two houses")
    if not text.startswith("# machine-made\n\n> " + TAGLINE):
        fail("llms", "llms.txt must start with the name and the line")


def load_deny():
    path = None
    args = sys.argv[1:]
    if "--deny" in args:
        path = args[args.index("--deny") + 1]
    path = path or os.environ.get("MM_DENY_FILE")
    if not path:
        return []
    names = Path(path).read_text(encoding="utf-8").split()
    return [n for n in names if n and not n.startswith("#")]


def main():
    deny = load_deny()
    check_files()
    html_text = read("index.html")
    if html_text:
        page = Page()
        page.feed(html_text)
        page.close()
        check_html(page, html_text)
        visible = check_content(page, html_text)
        check_leaks(visible, deny)
    check_forbidden()
    check_css()
    check_svgs()
    check_llms()
    if failures:
        print("\n".join(failures))
        sys.exit(1)
    print("OK")


if __name__ == "__main__":
    main()
