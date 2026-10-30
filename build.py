#!/usr/bin/env python3
"""Build the machine-made site: site.json in, docs/ out. Standard library only."""

import hashlib
import html
import json
import re
import sys
from collections.abc import Callable
from functools import partial
from pathlib import Path
from typing import Any, NoReturn

import card

ROOT = Path(__file__).resolve().parent
# The site being built: its site.json and its docs/. --site DIR builds another house from this generator.
SITE = ROOT
DOCS = SITE / "docs"
HEROES = DOCS / "heroes"

CELL = 4
COLS, ROWS = 352, 116
EMPTY_COLS = 120
ORIGIN_X = EMPTY_COLS * CELL
ORIGIN_Y = (card.FRAME_H - ROWS * CELL) // 2
REGION_COLS = COLS - EMPTY_COLS
PIXEL = 4
PX, PY = REGION_COLS // PIXEL, ROWS // PIXEL
RED_SPAN = 2
SATINS = ((5, 2), (5, 3), (8, 3), (8, 5))
MASK64 = (1 << 64) - 1

FILE_NAME = re.compile(r"[a-z0-9][a-z0-9._-]*")
REPO_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
COLOUR = re.compile(r"#[0-9a-f]{6}")
FONTS = ROOT / "fonts"
# The web fonts and their licences. fonts.py cuts them from machine-made/type; build.py copies them.
FONT_FILES = ("mm-weft.woff2", "mm-sans.woff2", "mm-weft-OFL.txt", "mm-sans-OFL.txt")
# The fonts that the header uses, so the browser fetches them before it reads style.css.
PRELOAD = ("mm-weft.woff2", "mm-sans.woff2")


class Rng:
    """splitmix64: a small, stable generator. No global state."""

    def __init__(self, seed: int) -> None:
        self.state = seed & MASK64

    def next(self) -> int:
        self.state = (self.state + 0x9E3779B97F4A7C15) & MASK64
        z = self.state
        z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & MASK64
        z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & MASK64
        return z ^ (z >> 31)

    def below(self, n: int) -> int:
        return self.next() % n


def seed_from(name: str) -> int:
    return int.from_bytes(hashlib.sha256(name.encode("utf-8")).digest()[:8], "big")


def fold(rank: int, half: int) -> int:
    rank %= 2 * half
    return rank if rank < half else 2 * half - 1 - rank


def make_levels(rng: Rng) -> list[list[int]]:
    """Motif: tonal level 0 (weft face), 1 (twill), 2 (warp face) per pixel, mirrored on both axes."""
    half = 3 + rng.below(5)
    kind = rng.below(3)

    def distance(rx: int, ry: int) -> int:
        if kind == 0:
            return max(rx, ry)
        if kind == 1:
            return rx + ry
        return max(rx, ry, (rx + ry + 1) * 2 // 3)

    rings: list[int] = []
    main = 2 * rng.below(2)
    while len(rings) <= distance(half - 1, half - 1):
        rings += [main] * (1 + rng.below(3))
        if rng.below(3) == 0:
            rings.append(1)
        main = 2 - main
    flips = {(a, b): rng.below(16) == 0 for a in range(half) for b in range(a, half)}

    def level_at(x: int, y: int) -> int:
        rx = fold(abs(2 * x - (PX - 1)) // 2, half)
        ry = fold(abs(y - PY // 2), half)
        level = rings[distance(rx, ry)]
        if level != 1 and flips[(min(rx, ry), max(rx, ry))]:
            level = 2 - level
        return level

    return [[level_at(x, y) for x in range(PX)] for y in range(PY)]


def make_structure(rng: Rng) -> tuple[Callable[[int, int, int], bool], tuple[int, int, int]]:
    ends, step = SATINS[rng.below(len(SATINS))]
    twill = 1 + rng.below(3)

    def warp_up(level: int, x: int, y: int) -> bool:
        satin = (x + step * y) % ends == 0
        if level == 0:
            return satin
        if level == 2:
            return not satin
        return (x + y) % 4 < twill

    sizes = (ends, 4, ends)
    return warp_up, sizes


def rect(x: int, y: int, w: int, h: int) -> str:
    return f"M{x} {y}h{w}v{h}h-{w}z"


def thread_runs(size: tuple[int, int], up_at: Callable[[int, int], bool]) -> tuple[str, str]:
    """Merge thread cells of one tile or patch into runs: warp up as columns, weft up as rows."""
    warp: list[str] = []
    weft: list[str] = []
    for x in range(size[0]):
        y = 0
        while y < size[1]:
            if not up_at(x, y):
                y += 1
                continue
            start = y
            while y < size[1] and up_at(x, y):
                y += 1
            warp.append(rect(x * CELL, start * CELL, CELL - 1, (y - start) * CELL))
    for y in range(size[1]):
        x = 0
        while x < size[0]:
            if up_at(x, y):
                x += 1
                continue
            start = x
            while x < size[0] and not up_at(x, y):
                x += 1
            weft.append(rect(start * CELL, y * CELL, (x - start) * CELL, CELL - 1))
    return "".join(warp), "".join(weft)


def mask_path(levels: list[list[int]], which: int) -> str:
    """Rectangles of the pixels at one level, merged across rows."""
    open_runs: dict[tuple[int, int], int] = {}
    out: list[tuple[int, int, int, int]] = []
    for y in range(PY + 1):
        runs = set()
        if y < PY:
            x = 0
            while x < PX:
                if levels[y][x] != which:
                    x += 1
                    continue
                start = x
                while x < PX and levels[y][x] == which:
                    x += 1
                runs.add((start, x))
        for run in list(open_runs):
            if run not in runs:
                top = open_runs.pop(run)
                out.append((run[0], top, run[1] - run[0], y - top))
        for run in runs:
            open_runs.setdefault(run, y)
    size = PIXEL * CELL
    return "".join(
        rect(ORIGIN_X + x * size, ORIGIN_Y + y * size, w * size, h * size)
        for x, y, w, h in sorted(out, key=lambda r: (r[1], r[0]))
    )


def place_red(rng: Rng, levels: list[list[int]]) -> tuple[int, int]:
    """The red cell: a spot where the motif is one level, so it never straddles an edge."""
    for _ in range(200):
        x = 3 + rng.below(PX - 6 - RED_SPAN)
        y = 3 + rng.below(PY - 6 - RED_SPAN)
        block = {levels[y + j][x + i] for i in range(RED_SPAN) for j in range(RED_SPAN)}
        if len(block) == 1:
            return x, y
    return PX // 2 - 1, PY // 2 - 1


def hero_svg(name: str) -> str:
    rng = Rng(seed_from(name))
    levels = make_levels(rng)
    warp_up, sizes = make_structure(rng)
    red_x, red_y = place_red(rng, levels)

    defs: list[str] = []
    for level in range(3):
        size = sizes[level]
        warp, weft = thread_runs((size, size), partial(warp_up, level))
        defs.append(
            f'<pattern id="p{level}" patternUnits="userSpaceOnUse" x="{ORIGIN_X}" y="{ORIGIN_Y}" '
            f'width="{size * CELL}" height="{size * CELL}">'
            f'<path class="k" d="{warp}"/><path class="w" d="{weft}"/></pattern>'
        )
    fields = [
        f'<path fill="url(#p{level})" d="{mask_path(levels, level)}"/>'
        for level in range(3)
        if any(level in row for row in levels)
    ]
    left, top = red_x * PIXEL, red_y * PIXEL

    def red_up(x: int, y: int) -> bool:
        return warp_up(levels[(top + y) // PIXEL][(left + x) // PIXEL], left + x, top + y)

    warp, weft = thread_runs((RED_SPAN * PIXEL, RED_SPAN * PIXEL), red_up)
    cell = (
        f'<g transform="translate({ORIGIN_X + left * CELL} {ORIGIN_Y + top * CELL})">'
        f'<path class="r" d="{warp}{weft}"/></g>'
    )
    body = (
        f"<defs>{''.join(defs)}</defs>\n"
        f'<rect class="g" width="{card.FRAME_W}" height="{card.FRAME_H}"/>\n'
        + "\n".join(fields)
        + f"\n{cell}"
    )
    style = card.themed({"g": "bg", "k": "warp", "w": "weft"})
    return card.svg(
        str(card.FRAME_W),
        str(card.FRAME_H),
        f"0 0 {card.FRAME_W} {card.FRAME_H}",
        f"Weave pattern generated from the name {html.escape(name)}",
        style,
        body,
    )


def root_css(name: str) -> str:
    def block(mode: str) -> str:
        p = card.MODES[mode]
        return f"--bg:{p['bg']};--fg:{p['fg']};--muted:{p['muted']};--rule:{p['rule']};--red:{card.RED};"

    split = f"{ORIGIN_X / card.FRAME_W * 100:.3f}%"
    ratios = f"--frame-ratio:{card.FRAME_W} / {card.FRAME_H};--weave-ratio:{card.FRAME_W - ORIGIN_X} / {card.FRAME_H};"
    return (
        f":root{{{block('light')}--split:{split};{ratios}--name-chars:{len(name)};}}\n"
        f"@media (prefers-color-scheme:dark){{:root{{{block('dark')}}}}}\n"
    )


def check_palette() -> None:
    colours = [card.RED] + [v for mode in ("light", "dark") for v in card.MODES[mode].values()]
    for colour in colours:
        if not COLOUR.fullmatch(colour):
            fail(f"palette colour {colour} is not #rrggbb", "Write each palette colour as lower-case #rrggbb with no alpha.")


def fail(message: str, fix: str) -> NoReturn:
    print(json.dumps({"error": message, "fix": fix}), file=sys.stderr)
    sys.exit(2)


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
        ("name", str),
        ("tagline", str),
        ("owner", str),
        ("footer", str),
        ("subtitle", str),
        ("year", int),
        ("groups", list),
        ("houses", list),
        ("nav", list),
    ):
        need(site, key, kind, "site")
    if not FILE_NAME.fullmatch(site["name"]) or ".." in site["name"]:
        fail(
            "site.name cannot be used as a file name",
            "Use lower-case letters, digits, dot, dash or underscore; start with a letter or digit; no '..'.",
        )
    if not site["groups"]:
        fail("site.groups is empty", "List at least one group of projects.")
    for key, text in (("name", site["name"]), ("tagline", site["tagline"]), ("subtitle", site["subtitle"])):
        if not text.strip() or not all(32 <= ord(c) < 127 for c in text):
            fail(f"site.{key} is empty or not printable ASCII", f"Write site.{key} in printable ASCII; the card encodes it.")
    title = site.get("title", site["name"])
    if not isinstance(title, str) or title.lower() != site["name"] or not title.isascii():
        fail("site.title must be the name with capitals only", 'Write site.title as site.name with some letters in capitals, or leave it out.')
    papers = site.get("papers", [])
    if not isinstance(papers, list) or not all(
        isinstance(p, dict) and isinstance(p.get("title"), str) and isinstance(p.get("status"), str) and p["title"].isascii()
        for p in papers
    ):
        fail("site.papers must be a list of {title, status}", "Give each paper a title and a status, in plain ASCII.")
    if not card.sentences(site["tagline"]):
        fail("site.tagline has no sentence", "Write the line as one or two short sentences.")
    slugs: set[str] = {"main", "houses", slug(site["name"])}
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
                fail(f"{where}.projects[{i}].repo is not a repository name", "Use lower-case letters, digits, dot, dash or underscore; start with a letter or digit; no '..'.")
            if "site" in item:
                need(item, "site", str, f"{where}.projects[{i}]")
                if not item["site"].startswith("https://"):
                    fail(f"{where}.projects[{i}].site is not https", "Use an https URL.")
            repos.append(item["repo"])
    for i, item in enumerate(site["houses"]):
        for key in ("name", "line", "url"):
            need(item, key, str, f"houses[{i}]")
        if not item["url"].startswith("https://"):
            fail(f"houses[{i}].url is not https", "Use an https URL.")
    if len(set(repos)) != len(repos):
        fail("two projects share one repo name", "Remove the duplicate from the groups.")
    redirects = site.get("redirects", {})
    if not isinstance(redirects, dict) or not all(
        isinstance(k, str) and isinstance(v, str) and FILE_NAME.fullmatch(k) and ".." not in k
        and v.startswith("https://") and v.isascii() and not set(v) & set("<>\"' ")
        for k, v in redirects.items()
    ):
        fail("site.redirects must map a folder name to an https URL", "Use names like chaos-atlas and plain https URLs.")
    if set(redirects) & ({"fonts", "heroes", "rules"} | set(repos)):
        fail("a redirect folder clashes with a site folder or a project", "Pick another folder name.")
    return site


def slug(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")


def esc(text: str) -> str:
    return html.escape(text, quote=True)


def repo_url(site: dict[str, Any], repo: str) -> str:
    return f"https://github.com/{site['owner']}/{repo}"


def rule_img(text: str) -> str:
    """A decorative row of dots that encodes text in ASCII. It sits where a section rule would."""
    width, height = card.rule_size(text)
    return f'<img class="punch" src="rules/{slug(text)}.svg" width="{width}" height="{height}" alt="" aria-hidden="true">'


def project_items(site: dict[str, Any], projects: list[dict[str, str]]) -> str:
    items = []
    for p in projects:
        extra = f' <a class="site" href="{esc(p["site"])}">site</a>' if "site" in p else ""
        items.append(
            f'<li><a href="{esc(repo_url(site, p["repo"]))}">{esc(p["repo"])}</a>'
            f'<p>{esc(p["line"])}{extra}</p></li>'
        )
    return "\n".join(items)


def display_name(site: dict[str, Any]) -> str:
    """The name as people read it: site.title when set (the name with capitals), else site.name."""
    return str(site.get("title", site["name"]))


def papers_section(site: dict[str, Any]) -> str:
    """The Papers section: each paper with its status, no link until it is public. Empty when there are none."""
    papers = site.get("papers", [])
    if not papers:
        return ""
    items = "\n".join(
        f'<li><span class="status">{esc(p["status"])}</span><p>{esc(p["title"])}</p></li>' for p in papers
    )
    return (
        f'<section class="section" aria-labelledby="papers">\n{rule_img("Papers")}\n'
        f'<div class="wrap split">\n<h2 id="papers">Papers</h2>\n<ul class="papers">\n{items}\n</ul>\n</div>\n</section>\n'
    )


def page_html(site: dict[str, Any]) -> str:
    name = site["name"]
    shown = display_name(site)
    tagline = " ".join(f"<span>{esc(line)}</span>" for line in card.sentences(site["tagline"]))
    groups = "\n".join(
        f'<section class="section" aria-labelledby="{slug(g["title"])}">\n{rule_img(g["title"])}\n'
        f'<div class="wrap split">\n<h2 id="{slug(g["title"])}">{esc(g["title"])}</h2>\n'
        f'<ul class="projects">\n{project_items(site, g["projects"])}\n</ul>\n</div>\n</section>'
        for g in site["groups"]
    )
    preload = "\n".join(
        f'<link rel="preload" href="fonts/{font}" as="font" type="font/woff2" crossorigin>' for font in PRELOAD
    )
    tabs = "\n".join(
        f'<li><a href="index.html" aria-current="page">{esc(t["name"])}</a></li>'
        if t.get("self")
        else f'<li><a href="{esc(t["url"])}">{esc(t["name"])}</a></li>'
        for t in site["nav"]
    )
    houses = " and ".join(
        f'<a href="{esc(h["url"])}">{esc(h["name"])}</a> ({esc(h["line"])})' for h in site["houses"]
    )
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(shown)}</title>
<meta name="description" content="{esc(site['tagline'])}">
<meta name="color-scheme" content="light dark">
<link rel="icon" href="mark.svg" type="image/svg+xml">
{preload}
<link rel="stylesheet" href="style.css">
</head>
<body>
<a class="skip" href="#main">Skip to content</a>
<nav class="tabs wrap" aria-label="Sites">
<ul>
{tabs}
</ul>
</nav>
<header class="masthead wrap">
<div class="masthead-frame">
<div class="masthead-text">
<img class="mark" src="mark.svg" width="56" height="56" alt="Mark of {esc(shown)}: a grid of three by three squares, one of them red">
<div>
<h1>{esc(shown)}</h1>
<p class="tagline">{tagline}</p>
<p class="subtitle">{esc(site['subtitle'])}</p>
</div>
</div>
<img class="hero" src="heroes/{esc(name)}.svg" width="{card.FRAME_W}" height="{card.FRAME_H}" alt="Weave pattern generated from the name {esc(name)}">
</div>
</header>
<main id="main">
{groups}
{papers_section(site)}<section class="section" aria-labelledby="houses">
{rule_img("Houses")}
<div class="wrap split">
<h2 id="houses">Houses</h2>
<p>{houses}.</p>
</div>
</section>
</main>
<footer class="section">
{rule_img(site['name'])}
<div class="wrap">
<p>{esc(site['footer'])}</p>
<p>{site['year']}</p>
</div>
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
        return f"- [{p['repo']}]({repo_url(site, p['repo'])}): {p['line']}{extra}"

    groups = "\n\n".join(
        f"## {g['title']}\n\n" + "\n".join(entry(p) for p in g["projects"]) for g in site["groups"]
    )
    papers = "".join(
        f"- {p['title']} ({p['status']})\n" for p in site.get("papers", [])
    )
    papers = f"## Papers\n\n{papers}\n" if papers else ""
    houses = "\n".join(f"- [{h['name']}]({h['url']}): {h['line']}" for h in site["houses"])
    return (
        f"# {display_name(site)}\n\n> {site['tagline']}\n\n{site['subtitle']}\n\n"
        f"{groups}\n\n{papers}## Houses\n\n{houses}\n\n{site['footer']}\n"
    )


def font_bytes() -> dict[str, bytes]:
    """The files in fonts/, read as bytes. A missing file stops the build."""
    found: dict[str, bytes] = {}
    for name in FONT_FILES:
        path = FONTS / name
        if not path.is_file():
            fail(f"fonts/{name} is missing", "Run python3 fonts.py --type DIR with a checkout of machine-made/type.")
        found[name] = path.read_bytes()
    return found


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
    global SITE, DOCS, HEROES
    SITE = parse_site(sys.argv[1:])
    DOCS = SITE / "docs"
    HEROES = DOCS / "heroes"
    check_palette()
    site = load_site()
    style = (ROOT / "src" / "style.css").read_text(encoding="utf-8")
    name = site["name"]
    files = {
        "index.html": page_html(site),
        "style.css": root_css(display_name(site)) + style,
        "mark.svg": card.mark_svg(),
        "llms.txt": llms_txt(site),
        f"heroes/{name}.svg": hero_svg(name),
    }
    for folder, url in site.get("redirects", {}).items():
        files[f"{folder}/index.html"] = redirect_html(folder, url)
    papers = ["Papers"] if site.get("papers") else []
    for title in [g["title"] for g in site["groups"]] + papers + ["Houses", name]:
        files[f"rules/{slug(title)}.svg"] = card.rule_svg(title)
    fonts = {f"fonts/{font}": data for font, data in font_bytes().items()}
    for rel, text in files.items():
        write(DOCS / rel, text)
    for rel, data in fonts.items():
        (DOCS / rel).parent.mkdir(parents=True, exist_ok=True)
        (DOCS / rel).write_bytes(data)
    built = set(files) | set(fonts)
    for folder in (HEROES, DOCS / "rules", DOCS / "fonts"):
        for stale in sorted(folder.glob("*")):
            if f"{folder.name}/{stale.name}" not in built:
                stale.unlink()
    print(json.dumps({"built": len(built)}))


if __name__ == "__main__":
    main()
