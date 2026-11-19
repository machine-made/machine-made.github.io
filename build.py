#!/usr/bin/env python3
"""Build a house website: site.json in, docs/ out. Standard library only.

The page is the house banner, the house line beside one paragraph on the name, and the projects as
plates (the repository banner as a link to the repository, and one line), under small group labels.
"""

import html
import json
import re
import sys
from pathlib import Path
from typing import Any, NoReturn, TypedDict

import card

ROOT = Path(__file__).resolve().parent
# The site being built: its site.json and its docs/. --site DIR builds another house from this generator.
SITE = ROOT
DOCS = SITE / "docs"

FILE_NAME = re.compile(r"[a-z0-9][a-z0-9._-]*")
REPO_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
COLOUR = re.compile(r"#[0-9a-f]{6}")
# The word of the small link after a description: the project's own site, or its documentation.
SITE_LABELS = ("site", "docs")
FONTS = ROOT / "fonts"
IMAGES = ROOT / "img"
# The banner of the house, 1408 x 469, and the banner of a repository, 704 x 235: the same images as
# the GitHub profile of the organisation and the repository.
BANNER_SIZE = (1408, 469)
PLATE_SIZE = (704, 235)
# The three sites, in the order of the top bar and the footer. The footer reads as one line.
BAR = ("machine-made", "openfluids", "BoringQuantSystems")
FOOTER = " &middot; ".join(BAR)
# The top bar ends with the type site, on every house.
TYPE_BAR = ("type", "https://machine-made.github.io/type/")
# One type scale for the three houses: the base size and the size of the house line, in px.
SIZE, LINE_SIZE = 16, 24
# The typefaces of the sites, all machine-made (https://machine-made.github.io/type/), version 0.2.0. Weft sets
# the top bar, the labels and the footer on every house; a house sets its text in Weft, Sans or Warp. Each face
# is a file in fonts/ that build.py copies to docs/fonts/, with the licence of the family.
# family -> faces (file stem, font-weight, font-style), licence file, font stack (generic fallbacks only), and the
# word spacing of reading text (Sans has a narrow word space).
WEFT, SANS, WARP = "machine-made Weft", "machine-made Sans", "machine-made Warp"


class Family(TypedDict):
    faces: tuple[tuple[str, str, str], ...]
    licence: str
    stack: str
    spacing: str


FAMILIES: dict[str, Family] = {
    WEFT: {
        "faces": (("mm-weft", "100 900", "normal"),), "licence": "mm-weft-OFL.txt",
        "stack": '"machine-made Weft", ui-monospace, monospace', "spacing": "normal",
    },
    SANS: {
        "faces": (("mm-sans", "200 800", "normal"),), "licence": "mm-sans-OFL.txt",
        "stack": '"machine-made Sans", system-ui, sans-serif', "spacing": "0.05em",
    },
    WARP: {
        "faces": (("mm-warp-regular", "400", "normal"), ("mm-warp-italic", "400", "italic")),
        "licence": "mm-warp-OFL.txt", "stack": '"machine-made Warp", serif', "spacing": "normal",
    },
}


def families_of(site: dict[str, Any]) -> list[str]:
    """The font families the house loads: Weft first, then its own text face when that is not Weft."""
    own = site["theme"]["font"]
    return [WEFT] + ([own] if own != WEFT else [])


def font_files_of(site: dict[str, Any]) -> list[str]:
    """The files in fonts/ that the house ships: each face of each family, and the licence of the family."""
    return [
        name for fam in families_of(site)
        for name in (*(f"{stem}.woff2" for stem, _, _ in FAMILIES[fam]["faces"]), FAMILIES[fam]["licence"])
    ]


def edge_of(ground: str) -> str:
    """The 1 px edge of an image: the ground lightened by 10 per cent of the way to white."""
    parts = (int(ground[i : i + 2], 16) for i in (1, 3, 5))
    return "#" + "".join(f"{round(c + (255 - c) * 0.10):02x}" for c in parts)


def rem(px: int) -> str:
    return f"{px / 16:g}rem"


def root_css(site: dict[str, Any]) -> str:
    theme = site["theme"]
    faces = "".join(
        f'@font-face{{font-family:"{fam}";src:url(fonts/{stem}.woff2) format("woff2");'
        f"font-weight:{weight};font-style:{style};font-display:swap}}\n"
        for fam in families_of(site)
        for stem, weight, style in FAMILIES[fam]["faces"]
    )
    values = (
        f"--bg:{theme['ground']};--fg:{theme['text']};--muted:{theme['muted']};--accent:{theme['accent']};"
        f"--edge:{edge_of(theme['ground'])};--font:{FAMILIES[theme['font']]['stack']};"
        f"--mono:{FAMILIES[WEFT]['stack']};--ws:{FAMILIES[theme['font']]['spacing']};--fs:{rem(SIZE)};--ls:{rem(LINE_SIZE)};"
    )
    return f"{faces}:root{{{values}}}\n"


def fail(message: str, fix: str) -> NoReturn:
    print(json.dumps({"error": message, "fix": fix}), file=sys.stderr)
    sys.exit(2)


def printable_ascii(text: str) -> bool:
    return bool(text.strip()) and all(32 <= ord(c) < 127 for c in text)


def load_site() -> dict[str, Any]:
    path = SITE / "site.json"
    try:
        site: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"cannot read site.json: {exc}", "Fix site.json so that it is valid JSON.")

    def need(obj: object, key: str, kind: type, where: str) -> None:
        if not isinstance(obj, dict) or type(obj.get(key)) is not kind:
            fail(f"{where}.{key} is missing or has the wrong type", f"Set {where}.{key} in site.json.")

    for key, kind in (
        ("name", str), ("owner", str), ("line", str), ("blurb", str), ("theme", dict), ("groups", list),
        ("nav", list),
    ):
        need(site, key, kind, "site")
    if not FILE_NAME.fullmatch(site["name"]) or ".." in site["name"]:
        fail(
            "site.name cannot be used as a file name",
            "Use lower-case letters, digits, dot, dash or underscore; start with a letter or digit; no '..'.",
        )
    for key in ("line", "blurb"):
        if not printable_ascii(site[key]):
            fail(f"site.{key} is empty or not printable ASCII", f"Write site.{key} in printable ASCII.")
    title = site.get("title", site["name"])
    if not isinstance(title, str) or title.lower() != site["name"] or not title.isascii():
        fail("site.title must be the name with capitals only", "Write site.title as site.name with some letters in capitals, or leave it out.")
    theme = site["theme"]
    for key in ("ground", "text", "muted", "accent"):
        need(theme, key, str, "site.theme")
        if not COLOUR.fullmatch(theme[key]):
            fail(f"site.theme.{key} is not #rrggbb", "Write each colour as lower-case #rrggbb with no alpha.")
    need(theme, "font", str, "site.theme")
    if theme["font"] not in FAMILIES:
        fail(f"site.theme.font {theme['font']!r} is not a font of the generator", f"Use one of: {', '.join(FAMILIES)}.")
    if {"size", "line_size"} & set(theme):
        fail("site.theme sets a type size", "Remove size and line_size: the three houses share one type scale.")
    if not site["groups"]:
        fail("site.groups is empty", "List at least one group of projects.")
    slugs: set[str] = set()
    repos: list[str] = []
    for g, group in enumerate(site["groups"]):
        where = f"groups[{g}]"
        need(group, "title", str, where)
        need(group, "projects", list, where)
        if not slug(group["title"]) or slug(group["title"]) in slugs or not group["title"].isascii():
            fail(f"{where}.title gives no unique id", "Give each group its own title of ASCII letters and digits.")
        slugs.add(slug(group["title"]))
        if not group["projects"]:
            fail(f"{where} has no projects", "Remove the group or list a project in it.")
        for i, item in enumerate(group["projects"]):
            for key in ("repo", "line"):
                need(item, key, str, f"{where}.projects[{i}]")
            if not REPO_NAME.fullmatch(item["repo"]) or ".." in item["repo"]:
                fail(f"{where}.projects[{i}].repo is not a repository name", "Use letters, digits, dot, dash or underscore; start with a letter or digit; no '..'.")
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
            fail(f"nav {t.get('name')} has no https url", "Give each entry of the top bar an https url.")
    redirects = site.get("redirects", {})
    if not isinstance(redirects, dict) or not all(
        isinstance(k, str) and isinstance(v, str) and FILE_NAME.fullmatch(k) and ".." not in k
        and v.startswith("https://") and v.isascii() and not set(v) & set("<>\"' ")
        for k, v in redirects.items()
    ):
        fail("site.redirects must map a folder name to an https URL", "Use names like chaos-atlas and plain https URLs.")
    if set(redirects) & ({"fonts", "img", "index.html", "style.css", "mark.svg", "llms.txt"} | set(repos)):
        fail("a redirect folder clashes with a site folder or a project", "Pick another folder name.")
    return site


def slug(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")


def esc(text: str) -> str:
    return html.escape(text, quote=True)


def repo_url(site: dict[str, Any], item: dict[str, str]) -> str:
    return f"https://github.com/{item.get('owner', site['owner'])}/{item['repo']}"


def display_name(site: dict[str, Any]) -> str:
    """The name as people read it: site.title when set (the name with capitals), else site.name."""
    return str(site.get("title", site["name"]))


def plate(site: dict[str, Any], item: dict[str, str]) -> str:
    """One plate: the repository banner as a link to the repository, and one line under it. The image has
    no alt text and the link carries the repository name. A project with a site or documentation gets a
    small link, "site" or "docs", after the line."""
    name, url = item["repo"], repo_url(site, item)
    img = f'<img src="img/{esc(name)}.jpg" width="{PLATE_SIZE[0]}" height="{PLATE_SIZE[1]}" loading="lazy" alt="">'
    more = ""
    if "site" in item:
        label = item.get("site_label", "site")
        more = f' <a class="nm" href="{esc(item["site"])}" aria-label="{esc(name)} {label}">{label}</a>'
    return (
        f'<li class="plate"><a class="pic" href="{esc(url)}" aria-label="{esc(name)}">{img}</a>'
        f'<span class="ds">{esc(item["line"])}{more}</span></li>'
    )


def page_html(site: dict[str, Any]) -> str:
    shown = display_name(site)
    sections = "\n".join(
        f'<section aria-labelledby="g-{slug(g["title"])}">\n<h2 class="lbl" id="g-{slug(g["title"])}">{esc(g["title"])}</h2>\n'
        f'<ul class="grid">\n' + "\n".join(plate(site, p) for p in g["projects"]) + "\n</ul>\n</section>"
        for g in site["groups"]
    )
    preload = "\n".join(
        f'<link rel="preload" href="fonts/{FAMILIES[fam]["faces"][0][0]}.woff2" as="font" type="font/woff2" crossorigin>'
        for fam in families_of(site)
    )
    # The current site is marked and is not a link; every other entry links to its site.
    bar = "\n".join(
        f'<span aria-current="page">{esc(t["name"])}</span>' if t.get("self") else f'<a href="{esc(t["url"])}">{esc(t["name"])}</a>'
        for t in site["nav"]
    )
    home = next(t["url"] for t in site["nav"] if t.get("self"))
    social = "\n".join(
        f'<meta {attr}="{key}" content="{esc(value)}">'
        for attr, key, value in (
            ("property", "og:type", "website"),
            ("property", "og:title", shown),
            ("property", "og:description", site["line"]),
            ("property", "og:url", home),
            ("property", "og:image", f"{home.rstrip('/')}/img/banner.jpg"),
            ("property", "og:image:width", str(BANNER_SIZE[0])),
            ("property", "og:image:height", str(BANNER_SIZE[1])),
            ("property", "og:image:alt", shown),
            ("name", "twitter:card", "summary_large_image"),
        )
    )
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(shown)}</title>
<meta name="description" content="{esc(site['line'])}">
<meta name="color-scheme" content="dark">
<meta name="theme-color" content="{site['theme']['ground']}">
<link rel="icon" href="mark.svg" type="image/svg+xml">
{social}
{preload}
<link rel="stylesheet" href="style.css">
</head>
<body>
<a class="skip" href="#main">Skip to content</a>
<header class="wrap">
<nav class="bar" aria-label="Sites">
{bar}
</nav>
<h1><img class="banner" src="img/banner.jpg" width="{BANNER_SIZE[0]}" height="{BANNER_SIZE[1]}" alt="{esc(shown)}"></h1>
</header>
<main id="main" class="wrap">
<div class="duo">
<p class="line">{esc(site['line'])}</p>
<p class="blurb">{esc(site['blurb'])}</p>
</div>
{sections}
</main>
<footer class="wrap">
<p>{FOOTER}</p>
</footer>
</body>
</html>
"""


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
        return f"- [{p['repo']}]({repo_url(site, p)}): {p['line']}{extra}"

    groups = "\n\n".join(
        f"## {g['title']}\n\n" + "\n".join(entry(p) for p in g["projects"]) for g in site["groups"]
    )
    sites = "\n".join(f"- [{t['name']}]({t['url']})" for t in site["nav"])
    return f"# {display_name(site)}\n\n> {site['line']}\n\n{site['blurb']}\n\n{groups}\n\n## Sites\n\n{sites}\n"


def read_bytes(path: Path, what: str) -> bytes:
    """A file the build copies. A missing file stops the build."""
    if not path.is_file():
        fail(f"{what} is missing", "Restore the file in the generator repository.")
    return path.read_bytes()


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def parse_site(argv: list[str]) -> Path:
    """--site DIR: the folder that holds site.json; the page goes to DIR/docs. Default: this repository."""
    if not argv:
        return ROOT
    if len(argv) != 2 or argv[0] != "--site":
        fail(f"unknown arguments: {' '.join(argv)}", "Run python3 build.py, or python3 build.py --site DIR.")
    site = Path(argv[1]).resolve()
    if not (site / "site.json").is_file():
        fail(f"{argv[1]}/site.json is missing", "Point --site at a folder that holds a site.json.")
    return site


def main() -> None:
    global SITE, DOCS  # noqa: PLW0603 -- the build state, set once from the command line
    SITE = parse_site(sys.argv[1:])
    DOCS = SITE / "docs"
    site = load_site()
    texts = {
        "index.html": page_html(site),
        "style.css": root_css(site) + (ROOT / "src" / "style.css").read_text(encoding="utf-8"),
        "mark.svg": card.mark_svg(),
        "llms.txt": llms_txt(site),
    }
    for folder, url in site.get("redirects", {}).items():
        texts[f"{folder}/index.html"] = redirect_html(folder, url)
    data = {"img/banner.jpg": read_bytes(IMAGES / "org" / f"{site['name']}.jpg", f"img/org/{site['name']}.jpg")}
    for group in site["groups"]:
        for p in group["projects"]:
            data[f"img/{p['repo']}.jpg"] = read_bytes(IMAGES / "repo" / f"{p['repo']}.jpg", f"img/repo/{p['repo']}.jpg")
    for font in font_files_of(site):
        data[f"fonts/{font}"] = read_bytes(FONTS / font, f"fonts/{font}")
    for rel, text in texts.items():
        write(DOCS / rel, text)
    for rel, blob in data.items():
        (DOCS / rel).parent.mkdir(parents=True, exist_ok=True)
        (DOCS / rel).write_bytes(blob)
    built = set(texts) | set(data)
    for stale in sorted(DOCS.rglob("*"), reverse=True):
        if stale.is_file() and stale.relative_to(DOCS).as_posix() not in built:
            stale.unlink()
        elif stale.is_dir() and not any(stale.iterdir()):
            stale.rmdir()
    print(json.dumps({"built": len(built)}))


if __name__ == "__main__":
    main()
