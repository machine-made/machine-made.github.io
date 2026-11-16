#!/usr/bin/env python3
"""Build a house website: site.json in, docs/ out. Standard library only.

The page is the house banner, the house line beside one paragraph on the name, and the projects as
plates (the repository banner, its name, one line), under small group labels.
"""

import html
import json
import re
import sys
from pathlib import Path
from typing import Any, NoReturn

import card

ROOT = Path(__file__).resolve().parent
# The site being built: its site.json and its docs/. --site DIR builds another house from this generator.
SITE = ROOT
DOCS = SITE / "docs"

FILE_NAME = re.compile(r"[a-z0-9][a-z0-9._-]*")
REPO_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
COLOUR = re.compile(r"#[0-9a-f]{6}")
FONTS = ROOT / "fonts"
IMAGES = ROOT / "img"
# The banner of the house, 1408 x 469, and the banner of a repository, 704 x 235: the same images as
# the GitHub profile of the organisation and the repository.
BANNER_SIZE = (1408, 469)
PLATE_SIZE = (704, 235)
# The three sites, in the order of the top bar and the footer. The footer reads as one line.
BAR = ("machine-made", "openfluids", "BoringQuantSystems")
FOOTER = " &middot; ".join(BAR)
# The typefaces a house may use for its text. Weft sets the top bar, the labels and the footer on every
# house. The fonts are files in fonts/ that build.py copies to docs/fonts/, with their licences.
WEFT = "machine-made Weft"
FAMILIES: dict[str, dict[str, str]] = {
    WEFT: {
        "file": "mm-weft", "licence": "mm-weft-OFL.txt", "weight": "100 900",
        "stack": '"machine-made Weft", ui-monospace, "SF Mono", Menlo, Consolas, monospace',
    },
    "Lato": {
        "file": "lato-400", "licence": "lato-OFL.txt", "weight": "400",
        "stack": '"Lato", system-ui, -apple-system, "Segoe UI", Roboto, sans-serif',
    },
    "EB Garamond": {
        "file": "eb-garamond-400", "licence": "eb-garamond-OFL.txt", "weight": "400",
        "stack": '"EB Garamond", Georgia, "Times New Roman", serif',
    },
}


def families_of(site: dict[str, Any]) -> list[str]:
    """The font families the house loads: Weft first, then its own text face when that is not Weft."""
    own = site["theme"]["font"]
    return [WEFT] + ([own] if own != WEFT else [])


def font_files_of(site: dict[str, Any]) -> list[str]:
    """The files in fonts/ that the house ships: each family's woff2 and its licence."""
    return [f for fam in families_of(site) for f in (f"{FAMILIES[fam]['file']}.woff2", FAMILIES[fam]["licence"])]


def edge_of(ground: str) -> str:
    """The 1 px edge of an image: the ground lightened by 10 per cent of the way to white."""
    parts = (int(ground[i : i + 2], 16) for i in (1, 3, 5))
    return "#" + "".join(f"{round(c + (255 - c) * 0.10):02x}" for c in parts)


def rem(px: int) -> str:
    return f"{px / 16:g}rem"


def root_css(site: dict[str, Any]) -> str:
    theme = site["theme"]
    faces = "".join(
        '@font-face{font-family:"%s";src:url(fonts/%s.woff2) format("woff2");font-weight:%s;font-style:normal;'
        "font-display:swap}\n" % (fam, FAMILIES[fam]["file"], FAMILIES[fam]["weight"])
        for fam in families_of(site)
    )
    values = (
        f"--bg:{theme['ground']};--fg:{theme['text']};--muted:{theme['muted']};--accent:{theme['accent']};"
        f"--edge:{edge_of(theme['ground'])};--font:{FAMILIES[theme['font']]['stack']};"
        f"--mono:{FAMILIES[WEFT]['stack']};--fs:{rem(theme['size'])};--ls:{rem(theme['line_size'])};"
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
    for key in ("size", "line_size"):
        need(theme, key, int, "site.theme")
        if not 10 <= theme[key] <= 48:
            fail(f"site.theme.{key} is outside 10 to 48 px", f"Set site.theme.{key} between 10 and 48.")
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
            for key in ("owner", "site"):
                if key in item:
                    need(item, key, str, f"{where}.projects[{i}]")
            if "owner" in item and (not REPO_NAME.fullmatch(item["owner"]) or ".." in item["owner"]):
                fail(f"{where}.projects[{i}].owner is not an owner name", "Use letters, digits, dot, dash or underscore.")
            if "site" in item and not item["site"].startswith("https://"):
                fail(f"{where}.projects[{i}].site is not https", "Use an https URL.")
            if not (IMAGES / "repo" / f"{item['repo']}.jpg").is_file():
                fail(f"img/repo/{item['repo']}.jpg is missing", "Put the 704 x 235 repository banner in img/repo/.")
            repos.append(item["repo"])
    if len(set(repos)) != len(repos):
        fail("two projects share one repo name", "Remove the duplicate from the groups.")
    if not (IMAGES / "org" / f"{site['name']}.jpg").is_file():
        fail(f"img/org/{site['name']}.jpg is missing", "Put the 1408 x 469 organisation banner in img/org/.")
    nav = site["nav"]
    if [t.get("name") for t in nav] != list(BAR) or sum(1 for t in nav if t.get("self")) != 1:
        fail("site.nav must list the three sites in order, one of them self", f"List {', '.join(BAR)}; mark the current one with self.")
    for t in nav:
        if not str(t.get("url", "")).startswith("https://"):
            fail(f"nav {t.get('name')} has no https url", "Give each of the three sites an https url.")
    redirects = site.get("redirects", {})
    if not isinstance(redirects, dict) or not all(
        isinstance(k, str) and isinstance(v, str) and FILE_NAME.fullmatch(k) and ".." not in k
        and v.startswith("https://") and v.isascii() and not set(v) & set("<>\"' ")
        for k, v in redirects.items()
    ):
        fail("site.redirects must map a folder name to an https URL", "Use names like chaos-atlas and plain https URLs.")
    if set(redirects) & ({"fonts", "img"} | set(repos)):
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
    """One plate: the repository banner, its name, one line. The whole plate links to the repository.
    When the project has a site or documentation, the banner links to the repository and the name to that site."""
    name, url = item["repo"], repo_url(site, item)
    img = f'<img src="img/{esc(name)}.jpg" width="{PLATE_SIZE[0]}" height="{PLATE_SIZE[1]}" loading="lazy" alt="{esc(name)}">'
    line = f'<span class="ds">{esc(item["line"])}</span>'
    if "site" in item:
        return (
            f'<li class="plate"><a class="pic" href="{esc(url)}">{img}</a>'
            f'<a class="nm" href="{esc(item["site"])}">{esc(name)}</a>{line}</li>'
        )
    return f'<li class="plate"><a class="whole" href="{esc(url)}">{img}<span class="nm">{esc(name)}</span>{line}</a></li>'


def page_html(site: dict[str, Any]) -> str:
    shown = display_name(site)
    sections = "\n".join(
        f'<section aria-labelledby="g-{slug(g["title"])}">\n<h2 class="lbl" id="g-{slug(g["title"])}">{esc(g["title"])}</h2>\n'
        f'<ul class="grid">\n' + "\n".join(plate(site, p) for p in g["projects"]) + "\n</ul>\n</section>"
        for g in site["groups"]
    )
    preload = "\n".join(
        f'<link rel="preload" href="fonts/{FAMILIES[fam]["file"]}.woff2" as="font" type="font/woff2" crossorigin>'
        for fam in families_of(site)
    )
    bar = "\n".join(
        f'<a href="{esc(t["url"])}"'
        + (' aria-current="page"' if t.get("self") else "")
        + f">{esc(t['name'])}</a>"
        for t in site["nav"]
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
        extra = f" ([site]({p['site']}))" if "site" in p else ""
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
    global SITE, DOCS
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
