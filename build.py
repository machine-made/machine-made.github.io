#!/usr/bin/env python3
"""Build a house website: site.json and the GitHub facts in, docs/ out.

  uv run --with fonttools==4.68.0 --with brotli==1.2.1 --with pillow==13.0.0 python3 build.py [--site DIR] [--data FILE]

--site DIR   the folder that holds site.json; the site goes to DIR/docs. Default: this repository (machine-made).
--data FILE  the GitHub facts that fetch.py wrote. Without it, build.py runs fetch.py first; a failed fetch stops
             the build, so a stale page cannot ship.

The page is the one design system of the four sites (src/system.css): bar 1 (the four sites), bar 2 (the house
logo and its sections), the banner, the house line, Latest, the project plates under their group labels, the
houses row and the footer. Every plate carries its live facts: language, latest release, last commit. The build
writes index.html, 404.html, llms.txt, the social image og.jpg, the icons, the image variants (AVIF and JPEG at
two widths) and a subset of each font with every feature and axis kept.
"""

import datetime
import html
import io
import json
import re
import subprocess
import sys
import tempfile
from html.parser import HTMLParser
from pathlib import Path
from typing import TYPE_CHECKING, Any, NoReturn

import card

if TYPE_CHECKING:
    from fontTools.ttLib import TTFont
    from PIL import Image

ROOT = Path(__file__).resolve().parent
# The site being built: its site.json and its docs/. --site DIR builds another house from this generator.
SITE = ROOT
DOCS = SITE / "docs"
FONTS = ROOT / "fonts"
IMAGES = ROOT / "img"
SYSTEM_CSS = ROOT / "src" / "system.css"

FILE_NAME = re.compile(r"[a-z0-9][a-z0-9._-]*")
REPO_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
COLOUR = re.compile(r"#[0-9a-f]{6}")
# The word of the small link after a description: the project's own site, or its documentation.
SITE_LABELS = ("site", "docs")
# The banner of a house, 1408 x 469, and the banner of a repository, 704 x 235: the same images as the GitHub
# profile of the organisation and the repository. Each ships as AVIF and JPEG at two widths.
BANNER_SIZE = (1408, 469)
PLATE_SIZE = (704, 235)
BANNER_WIDTHS = (704, 1408)
PLATE_WIDTHS = (352, 704)
OG_SIZE = (1200, 630)
ICON, TOUCH, AVATAR = 64, 180, 56
# The three sites, in the order of bar 1 and the footer. The type site comes last on every house.
BAR = ("machine-made", "openfluids", "BoringQuantSystems")
TYPE_BAR = ("type", "https://machine-made.github.io/type/")
TYPE_LINE = "Four typefaces, made by code."
# The house faces and the fonts: file in fonts/, CSS family, the @font-face descriptors. Every page loads Weft
# (bars, labels, facts) and Sans (reading text); the house line is set in the house face.
FACES = ("weft", "heddle", "warp")
FONT_FILES = {"weft": "mm-weft", "sans": "mm-sans", "heddle": "mm-heddle", "warp": "mm-warp-regular"}
FAMILY_CSS = {
    "weft": ('"mm Weft"', "font-weight:100 900"),
    "sans": ('"mm Sans"', "font-weight:200 800"),
    "heddle": ('"mm Heddle"', "font-weight:100 900;font-stretch:70% 140%"),
    "warp": ('"mm Warp"', "font-weight:400"),
}
# Characters every subset keeps: digits for dates and versions, the space, the middle dot that the style draws
# between facts and the dash of the 404 title.
KEEP = "0123456789 ·–"
# The OpenType features the style asks for (ss01, tabular, old-style and proportional figures, small capitals)
# and kerning. A subset keeps every feature that still has a glyph to act on; these must survive.
USED_FEATURES = {"ss01", "tnum", "onum", "pnum", "smcp", "c2sc", "kern"}
THEME_KEYS = ("ground", "surface", "line", "text", "muted", "accent")
# Contrast floors, WCAG 2 ratios: text and muted on the ground and on the surface; the accent marks only.
PAIRS = (("text", "ground", 7.0), ("muted", "ground", 4.5), ("text", "surface", 7.0), ("muted", "surface", 4.5), ("accent", "ground", 3.0))
PLATE_SIZES = "(min-width: 1264px) 282px, (min-width: 1000px) 22vw, (min-width: 520px) 46vw, calc(100vw - 32px)"
BANNER_SIZES = "(min-width: 1264px) 1200px, calc(100vw - 32px)"
MONTHS = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()
NEVER = {"homebrew-tap"}
# Ids of the built-in sections of every page; a group title may not take them (its id is g-<slug>).
RESERVED_IDS = {"latest", "houses"}


def fail(message: str, fix: str) -> NoReturn:
    print(json.dumps({"error": message, "fix": fix}), file=sys.stderr)
    sys.exit(2)


def printable_ascii(text: str) -> bool:
    return bool(text.strip()) and all(32 <= ord(c) < 127 for c in text)


def luminance(colour: str) -> float:
    channels = [int(colour[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    channels = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def contrast(a: str, b: str) -> float:
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def load_site(path: Path) -> dict[str, Any]:
    try:
        site: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"cannot read {path.name}: {exc}", "Fix site.json so that it is valid JSON.")

    def need(obj: object, key: str, kind: type, where: str) -> None:
        if not isinstance(obj, dict) or type(obj.get(key)) is not kind:
            fail(f"{where}.{key} is missing or has the wrong type", f"Set {where}.{key} in site.json.")

    for key, kind in (("name", str), ("owner", str), ("line", str), ("theme", dict), ("groups", list), ("nav", list)):
        need(site, key, kind, "site")
    if "blurb" in site:
        fail("site.blurb is set", "Remove blurb: the house line stands alone (the approved design, 19 Nov).")
    if not FILE_NAME.fullmatch(site["name"]) or ".." in site["name"]:
        fail(
            "site.name cannot be used as a file name",
            "Use lower-case letters, digits, dot, dash or underscore; start with a letter or digit; no '..'.",
        )
    if not REPO_NAME.fullmatch(site["owner"]):
        fail("site.owner is not an owner name", "Use letters, digits, dot, dash or underscore.")
    if not printable_ascii(site["line"]):
        fail("site.line is empty or not printable ASCII", "Write site.line in printable ASCII.")
    title = site.get("title", site["name"])
    if not isinstance(title, str) or title.lower() != site["name"] or not title.isascii():
        fail("site.title must be the name with capitals only", "Write site.title as site.name with some letters in capitals, or leave it out.")
    theme = site["theme"]
    for key in THEME_KEYS:
        need(theme, key, str, "site.theme")
        if not COLOUR.fullmatch(theme[key]):
            fail(f"site.theme.{key} is not #rrggbb", "Write each colour as lower-case #rrggbb with no alpha.")
    need(theme, "face", str, "site.theme")
    if theme["face"] not in FACES:
        fail(f"site.theme.face {theme['face']!r} is not a house face", f"Use one of: {', '.join(FACES)}.")
    if set(theme) - {*THEME_KEYS, "face"}:
        fail(f"site.theme sets {', '.join(sorted(set(theme) - {*THEME_KEYS, 'face'}))}", "A house sets only its six colours and its face; the type scale is shared.")
    for fg, bg, floor in PAIRS:
        if contrast(theme[fg], theme[bg]) < floor:
            fail(f"site.theme {fg} on {bg} is {contrast(theme[fg], theme[bg]):.2f}, below {floor}", "Pick colours that pass the contrast floors.")
    if not site["groups"]:
        fail("site.groups is empty", "List at least one group of projects.")
    slugs: set[str] = set()
    repos: list[str] = []
    for g, group in enumerate(site["groups"]):
        where = f"groups[{g}]"
        need(group, "title", str, where)
        need(group, "nav", str, where)
        need(group, "projects", list, where)
        if not slug(group["title"]) or slug(group["title"]) in slugs or not group["title"].isascii():
            fail(f"{where}.title gives no unique id", "Give each group its own title of ASCII letters and digits.")
        if slug(group["title"]) in RESERVED_IDS:
            fail(f"{where}.title {group['title']!r} takes the id of a built-in section", "Pick another title: Latest and the houses row are on every page.")
        if not printable_ascii(group["nav"]) or len(group["nav"]) > 12:
            fail(f"{where}.nav is not a short label", "Give each group a bar-2 label of at most 12 ASCII characters.")
        slugs.add(slug(group["title"]))
        if not group["projects"]:
            fail(f"{where} has no projects", "Remove the group or list a project in it.")
        for i, item in enumerate(group["projects"]):
            for key in ("repo", "line"):
                need(item, key, str, f"{where}.projects[{i}]")
            if not REPO_NAME.fullmatch(item["repo"]) or ".." in item["repo"]:
                fail(f"{where}.projects[{i}].repo is not a repository name", "Use letters, digits, dot, dash or underscore; start with a letter or digit; no '..'.")
            if item["repo"] in NEVER:
                fail(f"{where}.projects[{i}] is {item['repo']}", f"{item['repo']} is never listed.")
            if not printable_ascii(item["line"]):
                fail(f"{where}.projects[{i}].line is empty or not printable ASCII", "Write the line in printable ASCII.")
            for key in ("owner", "site", "site_label"):
                if key in item:
                    need(item, key, str, f"{where}.projects[{i}]")
            if "owner" in item and (not REPO_NAME.fullmatch(item["owner"]) or ".." in item["owner"]):
                fail(f"{where}.projects[{i}].owner is not an owner name", "Use letters, digits, dot, dash or underscore.")
            if "site" in item and not item["site"].startswith("https://"):
                fail(f"{where}.projects[{i}].site is not https", "Use an https URL.")
            if item.get("site_label", "site") not in SITE_LABELS or ("site_label" in item and "site" not in item):
                fail(f"{where}.projects[{i}].site_label is not allowed", f"Use one of {', '.join(SITE_LABELS)}, with a site.")
            if not (IMAGES / "repo" / f"{item['repo']}.jpg").is_file():
                fail(f"img/repo/{item['repo']}.jpg is missing", "Put the 704 x 235 repository banner in img/repo/.")
            repos.append(item["repo"])
    if len(set(repos)) != len(repos):
        fail("two projects share one repo name", "Remove the duplicate from the groups.")
    if not (IMAGES / "org" / f"{site['name']}.jpg").is_file():
        fail(f"img/org/{site['name']}.jpg is missing", "Put the 1408 x 469 organisation banner in img/org/.")
    nav = site["nav"]
    if not all(isinstance(t, dict) for t in nav):
        fail("site.nav must hold objects", "Write each nav entry as {name, url} and mark the current one with self.")
    if [t.get("name") for t in nav] != [*BAR, TYPE_BAR[0]] or sum(1 for t in nav if t.get("self")) != 1:
        fail(
            "site.nav must list the three sites and the type site in order, one of the three self",
            f"List {', '.join(BAR)}, {TYPE_BAR[0]}; mark the current one with self.",
        )
    if nav[-1].get("self") or nav[-1].get("url") != TYPE_BAR[1]:
        fail("the last nav entry must be the type site", f"Give {TYPE_BAR[0]} the url {TYPE_BAR[1]} and no self.")
    for t in nav:
        if not str(t.get("url", "")).startswith("https://"):
            fail(f"nav {t.get('name')} has no https url", "Give each entry of bar 1 an https url.")
    if next(t["name"] for t in nav if t.get("self")) != title:
        fail("the nav entry marked self is not this site", "Mark this site's own entry with self.")
    redirects = site.get("redirects", {})
    if not isinstance(redirects, dict) or not all(
        isinstance(k, str) and isinstance(v, str) and FILE_NAME.fullmatch(k) and ".." not in k
        and v.startswith("https://") and v.isascii() and not set(v) & set("<>\"' ")
        for k, v in redirects.items()
    ):
        fail("site.redirects must map a folder name to an https URL", "Use names like chaos-atlas and plain https URLs.")
    if set(redirects) & ({"fonts", "img", "index.html", "404.html", "og.jpg", "mark.svg", "llms.txt"} | set(repos)):
        fail("a redirect folder clashes with a site folder or a project", "Pick another folder name.")
    return site


def slug(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")


def esc(text: str) -> str:
    return html.escape(text, quote=True)


def display_name(site: dict[str, Any]) -> str:
    """The name as people read it: site.title when set (the name with capitals), else site.name."""
    return str(site.get("title", site["name"]))


def full_name(site: dict[str, Any], item: dict[str, str]) -> str:
    return f"{item.get('owner', site['owner'])}/{item['repo']}"


def houses() -> dict[str, dict[str, Any]]:
    """The other houses, by display name, from site.json and houses/*/site.json of this generator."""
    found = {}
    for path in [ROOT / "site.json", *sorted((ROOT / "houses").glob("*/site.json"))]:
        other = load_site(path)
        found[display_name(other)] = other
    if set(found) != set(BAR):
        fail(f"the generator holds the houses {sorted(found)}", f"Keep exactly {', '.join(BAR)} in site.json and houses/.")
    return found


# ------------------------------------------------------------------ the GitHub facts
def load_data(path: Path, sites: list[dict[str, Any]]) -> dict[str, Any]:
    try:
        data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        datetime.date.fromisoformat(data["fetched"])
    except (OSError, ValueError, KeyError, TypeError) as exc:
        fail(f"cannot read the GitHub facts {path}: {exc.__class__.__name__}", "Run python3 fetch.py FILE and pass --data FILE.")
    for site in sites:
        for group in site["groups"]:
            for item in group["projects"]:
                if full_name(site, item) not in data.get("repos", {}):
                    fail(f"the GitHub facts have no entry for {full_name(site, item)}", "Run fetch.py again: the data file is older than site.json.")
    if set(data.get("families", {})) != {"weft", "sans", "heddle", "warp"}:
        fail("the GitHub facts have no release of every type family", "Run fetch.py again.")
    return data


def date_text(iso: str, fetched: str) -> str:
    """'14 Nov', with the year when it is not the year of the fetch. The fetch date, not the clock, keeps two
    builds from one data file equal."""
    d = datetime.date.fromisoformat(iso[:10])
    year = datetime.date.fromisoformat(fetched).year
    return f"{d.day} {MONTHS[d.month - 1]}" + ("" if d.year == year else f" {d.year}")


def time_html(iso: str, fetched: str) -> str:
    return f'<time datetime="{iso[:10]}">{date_text(iso, fetched)}</time>'


def facts(parts: list[str]) -> str:
    return '<p class="facts"><span>' + "".join(f"<span>{p}</span>" for p in parts) + "</span></p>"


def repo_facts(data: dict[str, Any], full: str) -> str:
    r = data["repos"][full]
    parts = [esc(r["lang"])] if r["lang"] else []
    parts.append(esc(r["release"]["tagName"]) if r["release"] else "unreleased")
    parts.append(time_html(r["commit"], data["fetched"]))
    return facts(parts)


def house_releases(site: dict[str, Any], data: dict[str, Any]) -> list[tuple[str, str, dict[str, str]]]:
    """The newest release of each repository of the house, newest first: one entry per repository."""
    found = []
    for group in site["groups"]:
        for item in group["projects"]:
            releases = data["repos"][full_name(site, item)]["releases"]
            if releases:
                newest = max(releases, key=lambda r: r["publishedAt"])
                found.append((newest["publishedAt"], item["repo"], newest))
    return sorted(found, key=lambda x: (x[0], x[1]), reverse=True)


def family_releases(data: dict[str, Any]) -> list[tuple[str, str, dict[str, str]]]:
    found = [(v["publishedAt"], k.capitalize(), v) for k, v in data["families"].items()]
    return sorted(found, key=lambda x: (x[0], x[1]), reverse=True)


# ------------------------------------------------------------------ components
# The section mark before each label: the 3 x 3 cells, the centre one in the accent.
MK = (
    '<svg class="mk" viewBox="0 0 30 30" aria-hidden="true" focusable="false">'
    + "".join(
        f'<rect class="{"on" if (x, y) == (11, 11) else "o"}" x="{x}" y="{y}" width="8" height="8"/>'
        for y in (0, 11, 22) for x in (0, 11, 22)
    )
    + "</svg>"
)
RED_CELL = ' class="r"'
# The machine-made logo in bar 2: the mark, its centre cell in the accent.
LOGO_MARK = (
    '<svg viewBox="0 0 30 30" aria-hidden="true" focusable="false">'
    + "".join(
        f'<rect{RED_CELL if (x, y) == (11, 11) else ""} x="{x}" y="{y}" width="8" height="8"/>'
        for y in (0, 11, 22) for x in (0, 11, 22)
    )
    + "</svg>"
)


def picture(prefix: str, stem: str, widths: tuple[int, int], size: tuple[int, int], alt: str, sizes: str, lazy: bool = True) -> str:
    """AVIF with a JPEG fallback, two widths each. Below the fold the image loads lazily; the banner loads first."""
    load = 'loading="lazy" decoding="async"' if lazy else 'decoding="async" fetchpriority="high"'
    avif = ", ".join(f"{prefix}img/{stem}-{w}.avif {w}w" for w in widths)
    jpeg = ", ".join(f"{prefix}img/{stem}-{w}.jpg {w}w" for w in widths)
    return (
        f'<picture><source type="image/avif" srcset="{avif}" sizes="{sizes}">'
        f'<img src="{prefix}img/{stem}-{widths[1]}.jpg" srcset="{jpeg}" sizes="{sizes}" width="{size[0]}" height="{size[1]}" alt="{esc(alt)}" {load}></picture>'
    )


def label(text: str, ident: str) -> str:
    return f'<h2 class="lbl" id="{ident}">{MK}<span>{esc(text)}</span></h2>'


def row(ident: str, text: str, inner: str, cls: str = "row") -> str:
    return f'<section class="{cls}" aria-labelledby="{ident}">{label(text, ident)}{inner}</section>'


def plate(site: dict[str, Any], item: dict[str, str], data: dict[str, Any], prefix: str) -> str:
    """One plate: the repository banner as a link to the repository (named by aria-label, empty alt text), one line
    under it with an optional site or docs link, and the live facts."""
    full = full_name(site, item)
    more = ""
    if "site" in item:
        word = item.get("site_label", "site")
        more = f' <a href="{esc(item["site"])}" aria-label="{esc(item["repo"])} {word}">{word}</a>'
    return (
        f'<li class="plate"><a class="pic" href="https://github.com/{esc(full)}" aria-label="{esc(item["repo"])}">'
        f'{picture(prefix, item["repo"], PLATE_WIDTHS, PLATE_SIZE, "", PLATE_SIZES)}</a>'
        f'<p class="ds">{esc(item["line"])}{more}</p>{repo_facts(data, full)}</li>'
    )


def latest(site: dict[str, Any], data: dict[str, Any]) -> str:
    """The newest releases of the house: distinct repositories, newest first, at most three."""
    items = house_releases(site, data)[:3]
    if len({repo for _, repo, _ in items}) != len(items):
        fail("Latest repeats a repository", "Report this: house_releases must give one entry per repository.")
    if not items:
        return ""
    lis = "".join(
        f'<li><a href="{esc(r["url"])}">{esc(repo)}</a>{facts([esc(r["tagName"]), time_html(r["publishedAt"], data["fetched"])])}</li>'
        for _, repo, r in items
    )
    return row("g-latest", "Latest", f'<ol class="latest n{len(items)}">{lis}</ol>', "row tight")


def houses_row(site: dict[str, Any], others: dict[str, dict[str, Any]], data: dict[str, Any], prefix: str) -> str:
    """The other two houses and the type site: banner, house line and the newest release."""
    lis = []
    for t in site["nav"]:
        if t.get("self"):
            continue
        if t["name"] == TYPE_BAR[0]:
            img = picture(prefix, "type", PLATE_WIDTHS, PLATE_SIZE, "", PLATE_SIZES)
            _, fam, r = family_releases(data)[0]
            fx = facts([f'{esc(fam)} {esc(r["tagName"].split("-")[-1])}', time_html(r["publishedAt"], data["fetched"])])
            caption = TYPE_LINE
        else:
            other = others[t["name"]]
            img = picture(prefix, f"banner-{other['name']}", BANNER_WIDTHS, BANNER_SIZE, "", PLATE_SIZES)
            releases = house_releases(other, data)
            if releases:
                _, repo, r = releases[0]
                fx = facts([f"{esc(repo)} {esc(r['tagName'])}", time_html(r["publishedAt"], data["fetched"])])
            else:
                fx = facts(["unreleased"])
            caption = other["line"]
        lis.append(
            f'<li class="plate"><a class="pic" href="{esc(t["url"])}" aria-label="{esc(t["name"])}">{img}</a>'
            f'<p class="ds">{esc(caption)}</p>{fx}</li>'
        )
    return row("g-houses", "The houses", f'<ul class="grid g3">{"".join(lis)}</ul>')


def bar1(site: dict[str, Any]) -> str:
    lis = "".join(
        f'<li><span aria-current="page">{esc(t["name"])}</span></li>' if t.get("self") else f'<li><a href="{esc(t["url"])}">{esc(t["name"])}</a></li>'
        for t in site["nav"]
    )
    return f'<nav class="b1" aria-label="Sites"><ul class="wrap">{lis}</ul></nav>'


def bar2(site: dict[str, Any], root: str) -> str:
    """The house logo (a link home) and the sections of the page, then the organisation on GitHub. root is "" on
    the home page and "/" on the 404 page."""
    secs = "".join(f'<a href="{root}#g-{slug(g["title"])}">{esc(g["nav"])}</a>' for g in site["groups"])
    secs += f'<a href="https://github.com/{esc(site["owner"])}">GitHub</a>'
    shown = display_name(site)
    if site["name"] == "machine-made":
        logo = LOGO_MARK
    else:
        logo = f'<img src="{root}img/avatar.png" width="28" height="28" alt="">'
    return (
        f'<header class="b2"><div class="wrap"><a class="logo" href="{root or "./"}" aria-label="{esc(shown)} home">{logo}</a>'
        f'<nav class="secs" aria-label="Sections">{secs}</nav></div></header>'
    )


def footer(site: dict[str, Any]) -> str:
    """One line: the four sites, each a link. The style draws the dot before each name."""
    return '<footer class="wrap"><div class="fl"><ul>' + "".join(f'<li><a href="{esc(t["url"])}">{esc(t["name"])}</a></li>' for t in site["nav"]) + "</ul></div></footer>"


def line_html(site: dict[str, Any], tag: str = "p", text: str | None = None) -> str:
    """The house line in the house face. A hyphenated word never breaks; in Warp, capitals are small capitals."""
    face = site["theme"]["face"]
    t = esc(site["line"] if text is None else text)
    t = re.sub(r"\b\w+(?:-\w+)+\b", lambda w: '<span class="nb">' + w.group(0) + "</span>", t)
    if face == "warp":
        t = re.sub(r"\b[A-Z]{2,}\b", lambda w: '<span class="sc">' + w.group(0) + "</span>", t)
    return f'<{tag} class="line {face}">{t}</{tag}>'


def home_url(site: dict[str, Any]) -> str:
    return next(t["url"] for t in site["nav"] if t.get("self"))


def head(site: dict[str, Any], title: str, prefix: str, preload: str) -> str:
    theme = site["theme"]
    shown = display_name(site)
    home = home_url(site)
    if site["name"] == "machine-made":
        icon = f'<link rel="icon" href="{prefix}mark.svg" type="image/svg+xml">'
    else:
        icon = f'<link rel="icon" href="{prefix}img/icon.png" type="image/png" sizes="{ICON}x{ICON}">'
    social = "".join(
        f'<meta {attr}="{key}" content="{esc(value)}">'
        for attr, key, value in (
            ("property", "og:type", "website"),
            ("property", "og:title", shown),
            ("property", "og:description", site["line"]),
            ("property", "og:url", home),
            ("property", "og:image", f"{home}og.jpg"),
            ("property", "og:image:width", str(OG_SIZE[0])),
            ("property", "og:image:height", str(OG_SIZE[1])),
            ("property", "og:image:alt", shown),
            ("name", "twitter:card", "summary_large_image"),
        )
    )
    return (
        '<!doctype html>\n<html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">'
        f'<title>{esc(title)}</title><meta name="description" content="{esc(site["line"])}">'
        f'<meta name="color-scheme" content="dark"><meta name="theme-color" content="{theme["ground"]}">'
        f'{icon}<link rel="apple-touch-icon" href="{prefix}img/touch.png">{social}{preload}'
    )


def styles(site: dict[str, Any], prefix: str, system: str) -> str:
    """Two style blocks: the font faces and the house tokens, then the one system stylesheet. The style is written
    into the page: a linked file cost 0.3 s of render time on the Lighthouse phone run."""
    faces = "".join(
        f'@font-face{{font-family:{FAMILY_CSS[f][0]};src:url({prefix}fonts/{f}.woff2) format("woff2");{FAMILY_CSS[f][1]};font-style:normal;font-display:swap}}'
        for f in uses(site)
    )
    tokens = ":root{" + ";".join(f"--{k}:{site['theme'][k]}" for k in THEME_KEYS) + "}"
    return f"<style>{faces}\n{tokens}</style><style>{system}</style>"


def uses(site: dict[str, Any]) -> list[str]:
    """The fonts a house page loads: Weft and Sans, and the house face when it is not Weft."""
    face = site["theme"]["face"]
    return ["weft", "sans"] + ([face] if face != "weft" else [])


def system_css() -> str:
    """src/system.css without its comments: the page ships the rules, the source file keeps the notes."""
    text = SYSTEM_CSS.read_text(encoding="utf-8")
    if not text.isascii():
        fail("src/system.css is not ASCII", "Write characters as CSS escapes.")
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return "\n".join(line.rstrip() for line in text.splitlines() if line.strip()) + "\n"


def page_html(site: dict[str, Any], others: dict[str, dict[str, Any]], data: dict[str, Any], system: str) -> str:
    shown = display_name(site)
    face = site["theme"]["face"]
    sections = "".join(
        row(f"g-{slug(g['title'])}", g["title"], '<ul class="grid">' + "".join(plate(site, p, data, "") for p in g["projects"]) + "</ul>")
        for g in site["groups"]
    )
    preload = (
        f'<link rel="preload" href="fonts/{face}.woff2" as="font" type="font/woff2" crossorigin>'
        f'<link rel="preload" as="image" type="image/avif" fetchpriority="high" imagesizes="{BANNER_SIZES}" '
        f'imagesrcset="img/banner-{site["name"]}-704.avif 704w, img/banner-{site["name"]}-1408.avif 1408w">'
    )
    banner = f'<h1 class="banner">{picture("", "banner-" + site["name"], BANNER_WIDTHS, BANNER_SIZE, shown, BANNER_SIZES, lazy=False)}</h1>'
    body = banner + line_html(site) + latest(site, data) + sections + houses_row(site, others, data, "")
    return (
        head(site, shown, "", preload) + styles(site, "", system) + "</head>\n"
        f'<body><a class="skip" href="#main">Skip to content</a>{bar1(site)}{bar2(site, "")}'
        f'<main id="main" class="wrap">{body}</main>{footer(site)}</body></html>\n'
    )


def not_found_html(site: dict[str, Any], system: str) -> str:
    """The 404 page. GitHub Pages serves it at any depth, so every address in it starts at the site root."""
    shown = display_name(site)
    face = site["theme"]["face"]
    preload = f'<link rel="preload" href="/fonts/{face}.woff2" as="font" type="font/woff2" crossorigin>'
    body = (
        f'<h1 class="line {face}">Not found</h1><p class="ds">This page does not exist.</p>'
        f'<p class="more"><a class="u" href="/">Back to {esc(shown)}</a></p>'
    )
    return (
        head(site, f"Not found – {shown}", "/", preload).replace("–", "&ndash;") + styles(site, "/", system) + "</head>\n"
        f'<body><a class="skip" href="#main">Skip to content</a>{bar1(site)}{bar2(site, "/")}'
        f'<main id="main" class="wrap nf">{body}</main>{footer(site)}</body></html>\n'
    )


def redirect_html(name: str, url: str) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(name)} has moved</title>
<meta http-equiv="refresh" content="0; url={esc(url)}">
<link rel="canonical" href="{esc(url)}">
</head>
<body>
<p><a href="{esc(url)}">{esc(name)} has moved</a></p>
</body>
</html>
"""


def llms_txt(site: dict[str, Any]) -> str:
    def entry(p: dict[str, str]) -> str:
        extra = f" ([{p.get('site_label', 'site')}]({p['site']}))" if "site" in p else ""
        return f"- [{p['repo']}](https://github.com/{full_name(site, p)}): {p['line']}{extra}"

    groups = "\n\n".join(f"## {g['title']}\n\n" + "\n".join(entry(p) for p in g["projects"]) for g in site["groups"])
    sites = "\n".join(f"- [{t['name']}]({t['url']})" for t in site["nav"])
    return f"# {display_name(site)}\n\n> {site['line']}\n\n{groups}\n\n## Sites\n\n{sites}\n"


# ------------------------------------------------------------------ fonts
class FaceText(HTMLParser):
    """The text inside any element whose class names the face."""

    VOID = {"img", "input", "br", "meta", "link", "source", "rect", "hr"}

    def __init__(self, face: str) -> None:
        super().__init__(convert_charrefs=True)
        self.face, self.stack, self.out = face, [], set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag not in self.VOID:
            self.stack.append(self.face in (dict(attrs).get("class") or "").split())

    def handle_endtag(self, tag: str) -> None:
        if tag not in self.VOID and self.stack:
            self.stack.pop()

    def handle_data(self, data: str) -> None:
        if any(self.stack):
            self.out |= set(data)


def strip_code(page: str) -> str:
    return re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", page, flags=re.S)


def visible_text(page: str) -> str:
    page = strip_code(page)
    page = re.sub(r'(?:aria-label|alt|placeholder|title|content)="([^"]*)"', lambda m: " " + m.group(1) + " ", page)
    return html.unescape(re.sub(r"<[^>]+>", " ", page))


def face_text(page: str, face: str) -> set[str]:
    parser = FaceText(face)
    parser.feed(strip_code(page))
    return parser.out


def font_meta(font: "TTFont") -> tuple[list[tuple[str, float, float]], set[str]]:
    axes = [(a.axisTag, a.minValue, a.maxValue) for a in font["fvar"].axes] if "fvar" in font else []
    feats = {r.FeatureTag for t in ("GSUB", "GPOS") if t in font for r in font[t].table.FeatureList.FeatureRecord}
    return axes, feats


def subset_fonts(site: dict[str, Any], pages: list[str]) -> dict[str, bytes]:
    """One subset per font: the characters of the two pages (and their capitals: labels are set in capitals by the
    style). Weft and Sans keep the text of the whole page; the house face keeps only the text set in it. Every
    layout feature and every variation axis is kept, and the build fails if one is lost."""
    from fontTools import subset as fts

    text = "".join(visible_text(p) for p in pages) + KEEP
    text = "".join(sorted(set(text + text.upper())))
    out = {}
    for f in uses(site):
        source = FONTS / f"{FONT_FILES[f]}.woff2"
        if not source.is_file():
            fail(f"fonts/{source.name} is missing", "Restore the font file in the generator repository.")
        chars = text
        if f in ("heddle", "warp"):
            keep = set(KEEP)
            for p in pages:
                keep |= face_text(p, f)
            chars = "".join(sorted(keep))
        opts = fts.Options()
        opts.flavor = "woff2"
        opts.layout_features = ["*"]
        opts.hinting = False
        opts.desubroutinize = True
        opts.name_IDs = ["*"]
        font = fts.load_font(str(source), opts)
        before = font_meta(font)
        sub = fts.Subsetter(opts)
        sub.populate(text=chars)
        sub.subset(font)
        after = font_meta(font)
        lost = (before[1] & USED_FEATURES) - after[1]
        if after[0] != before[0] or lost:
            fail(f"the subset of {source.name} lost an axis or the features {sorted(lost)}", "Keep layout_features ['*'] in subset_fonts.")
        buf = io.BytesIO()
        fts.save_font(font, buf, opts)
        out[f"fonts/{f}.woff2"] = buf.getvalue()
    return out


# ------------------------------------------------------------------ images
def rgb(colour: str) -> tuple[int, int, int]:
    return tuple(int(colour[i : i + 2], 16) for i in (1, 3, 5))  # type: ignore[return-value]


def variants(source: Path, stem: str, widths: tuple[int, int], cache: dict[Path, Any]) -> dict[str, bytes]:
    from PIL import Image

    if source not in cache:
        cache[source] = Image.open(source).convert("RGB")
    im = cache[source]
    out = {}
    for w in widths:
        r = im if w == im.width else im.resize((w, round(im.height * w / im.width)), Image.LANCZOS)
        for ext, opts in (("avif", {"quality": 62, "speed": 4}), ("jpg", {"quality": 82, "optimize": True, "progressive": True})):
            buf = io.BytesIO()
            r.save(buf, format="AVIF" if ext == "avif" else "JPEG", **opts)
            out[f"img/{stem}-{w}.{ext}"] = buf.getvalue()
    return out


def images(site: dict[str, Any], others: dict[str, dict[str, Any]]) -> dict[str, bytes]:
    from PIL import Image, ImageDraw

    def need(path: Path) -> Path:
        if not path.is_file():
            fail(f"{path.relative_to(ROOT)} is missing", "Restore the image in the generator repository.")
        return path

    cache: dict[Path, Any] = {}
    out = {}
    plates = {p["repo"] for g in site["groups"] for p in g["projects"]} | {"type"}
    for repo in sorted(plates):
        out |= variants(need(IMAGES / "repo" / f"{repo}.jpg"), repo, PLATE_WIDTHS, cache)
    for other in [site, *(others[n] for n in BAR if n != display_name(site))]:
        out |= variants(need(IMAGES / "org" / f"{other['name']}.jpg"), f"banner-{other['name']}", BANNER_WIDTHS, cache)
    ground = rgb(site["theme"]["ground"])
    # og.jpg: the banner at full width, centred on the house ground.
    banner = cache[IMAGES / "org" / f"{site['name']}.jpg"]
    scaled = banner.resize((OG_SIZE[0], round(banner.height * OG_SIZE[0] / banner.width)), Image.LANCZOS)
    og = Image.new("RGB", OG_SIZE, ground)
    og.paste(scaled, (0, (OG_SIZE[1] - scaled.height) // 2))
    buf = io.BytesIO()
    og.save(buf, format="JPEG", quality=84, optimize=True, progressive=True)
    out["og.jpg"] = buf.getvalue()

    def png(im: "Image.Image") -> bytes:
        b = io.BytesIO()
        im.save(b, format="PNG", optimize=True)
        return b.getvalue()

    if site["name"] == "machine-made":
        # The touch icon: the mark on the ground, drawn at twice the size and scaled down.
        big = TOUCH * 2
        im = Image.new("RGB", (big, big), ground)
        draw = ImageDraw.Draw(im)
        pad, unit = big * 0.2, big * 0.6 / 30
        for on, x, y in card.mark_cells():
            colour = card.RED if on else site["theme"]["text"]
            draw.rectangle([pad + x * unit, pad + y * unit, pad + (x + 8) * unit - 1, pad + (y + 8) * unit - 1], fill=colour)
        out["img/touch.png"] = png(im.resize((TOUCH, TOUCH), Image.LANCZOS))
    else:
        # The avatar of the organisation on the house ground: favicon, touch icon and the bar-2 logo.
        avatar = Image.open(need(IMAGES / "org" / f"{site['name']}-avatar.png")).convert("RGBA")
        flat = Image.alpha_composite(Image.new("RGBA", avatar.size, (*ground, 255)), avatar).convert("RGB")
        for size, rel in ((ICON, "img/icon.png"), (TOUCH, "img/touch.png"), (AVATAR, "img/avatar.png")):
            out[rel] = png(flat.resize((size, size), Image.LANCZOS))
    return out


# ------------------------------------------------------------------ main
def write(path: Path, blob: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(blob)


def parse_args(argv: list[str]) -> tuple[Path, Path | None]:
    site, data = ROOT, None
    args = list(argv)
    while args:
        flag = args.pop(0)
        if flag not in ("--site", "--data") or not args:
            fail(f"unknown arguments: {' '.join(argv)}", "Run python3 build.py [--site DIR] [--data FILE].")
        value = Path(args.pop(0)).resolve()
        if flag == "--site":
            if not (value / "site.json").is_file():
                fail(f"{value}/site.json is missing", "Point --site at a folder that holds a site.json.")
            site = value
        else:
            data = value
    return site, data


def fetched(data_path: Path | None, tmp: Path) -> Path:
    if data_path is not None:
        return data_path
    out = tmp / "data.json"
    done = subprocess.run([sys.executable, str(ROOT / "fetch.py"), str(out)], check=False)
    if done.returncode != 0:
        fail("the GitHub fetch failed", "Fix the fetch (gh auth status, network) and build again; no page was written.")
    return out


def main() -> None:
    global SITE, DOCS  # noqa: PLW0603 -- the build state, set once from the command line
    site_dir, data_path = parse_args(sys.argv[1:])
    SITE, DOCS = site_dir, site_dir / "docs"
    site = load_site(SITE / "site.json")
    others = houses()
    if not SYSTEM_CSS.is_file():
        fail("src/system.css is missing", "Restore the stylesheet in the generator repository.")
    system = system_css()
    with tempfile.TemporaryDirectory() as tmp:
        data = load_data(fetched(data_path, Path(tmp)), [site, *others.values()])
    page = page_html(site, others, data, system)
    missing = not_found_html(site, system)
    texts = {"index.html": page, "404.html": missing, "llms.txt": llms_txt(site)}
    if site["name"] == "machine-made":
        texts["mark.svg"] = card.mark_svg()
    for folder, url in site.get("redirects", {}).items():
        texts[f"{folder}/index.html"] = redirect_html(folder, url)
    blobs = {rel: text.encode("utf-8") for rel, text in texts.items()}
    blobs |= subset_fonts(site, [page, missing])
    for f in uses(site):
        licence = FONTS / f"{FONT_FILES[f].replace('-regular', '')}-OFL.txt"
        if not licence.is_file():
            fail(f"fonts/{licence.name} is missing", "Restore the licence of the font.")
        blobs[f"fonts/{licence.name}"] = licence.read_bytes()
    blobs |= images(site, others)
    for rel, blob in blobs.items():
        write(DOCS / rel, blob)
    for stale in sorted(DOCS.rglob("*"), reverse=True):
        if stale.is_file() and stale.relative_to(DOCS).as_posix() not in blobs:
            stale.unlink()
        elif stale.is_dir() and not any(stale.iterdir()):
            stale.rmdir()
    print(json.dumps({"built": len(blobs)}))


if __name__ == "__main__":
    main()
