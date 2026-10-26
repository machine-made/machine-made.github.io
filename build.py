#!/usr/bin/env python3
"""Build the machine-made site: site.json in, docs/ out. Standard library only."""

import hashlib
import html
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DOCS = ROOT / "docs"
HEROES = DOCS / "heroes"

PALETTE = {
    "light": {
        "bg": "#ffffff",
        "fg": "#000000",
        "muted": "#595959",
        "rule": "#d9d9d9",
        "warp": "#000000",
        "weft": "#bdbdbd",
    },
    "dark": {
        "bg": "#000000",
        "fg": "#ffffff",
        "muted": "#a6a6a6",
        "rule": "#2e2e2e",
        "warp": "#ffffff",
        "weft": "#383838",
    },
    "red": "#e5251c",
}

FRAME_W, FRAME_H = 1408, 469
CELL = 4
COLS, ROWS = 352, 116
EMPTY_COLS = 120
ORIGIN_X = EMPTY_COLS * CELL
ORIGIN_Y = (FRAME_H - ROWS * CELL) // 2
REGION_COLS = COLS - EMPTY_COLS
PIXEL = 4
PX, PY = REGION_COLS // PIXEL, ROWS // PIXEL
RED_SPAN = 2
SATINS = ((5, 2), (5, 3), (8, 3), (8, 5))
MASK64 = (1 << 64) - 1
FILE_NAME = re.compile(r"[a-z0-9][a-z0-9._-]*")
REPO_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
COLOUR = re.compile(r"#[0-9a-f]{6}")


class Rng:
    """splitmix64: a small, stable generator. No global state."""

    def __init__(self, seed):
        self.state = seed & MASK64

    def next(self):
        self.state = (self.state + 0x9E3779B97F4A7C15) & MASK64
        z = self.state
        z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & MASK64
        z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & MASK64
        return z ^ (z >> 31)

    def below(self, n):
        return self.next() % n


def seed_from(name):
    return int.from_bytes(hashlib.sha256(name.encode("utf-8")).digest()[:8], "big")


def fold(rank, half):
    rank %= 2 * half
    return rank if rank < half else 2 * half - 1 - rank


def make_levels(rng):
    """Motif: tonal level 0 (weft face), 1 (twill), 2 (warp face) per pixel, mirrored on both axes."""
    half = 3 + rng.below(5)
    kind = rng.below(3)

    def distance(rx, ry):
        if kind == 0:
            return max(rx, ry)
        if kind == 1:
            return rx + ry
        return max(rx, ry, (rx + ry + 1) * 2 // 3)

    rings = []
    main = 2 * rng.below(2)
    while len(rings) <= distance(half - 1, half - 1):
        rings += [main] * (1 + rng.below(3))
        if rng.below(3) == 0:
            rings.append(1)
        main = 2 - main
    flips = {(a, b): rng.below(16) == 0 for a in range(half) for b in range(a, half)}

    def level_at(x, y):
        rx = fold(abs(2 * x - (PX - 1)) // 2, half)
        ry = fold(abs(y - PY // 2), half)
        level = rings[distance(rx, ry)]
        if level != 1 and flips[(min(rx, ry), max(rx, ry))]:
            level = 2 - level
        return level

    return [[level_at(x, y) for x in range(PX)] for y in range(PY)]


def make_structure(rng):
    ends, step = SATINS[rng.below(len(SATINS))]
    twill = 1 + rng.below(3)

    def warp_up(level, x, y):
        satin = (x + step * y) % ends == 0
        if level == 0:
            return satin
        if level == 2:
            return not satin
        return (x + y) % 4 < twill

    sizes = (ends, 4, ends)
    return warp_up, sizes


def rect(x, y, w, h):
    return f"M{x} {y}h{w}v{h}h-{w}z"


def thread_runs(size, up_at):
    """Merge thread cells of one tile or patch into runs: warp up as columns, weft up as rows."""
    warp, weft = [], []
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


def mask_path(levels, which):
    """Rectangles of the pixels at one level, merged across rows."""
    open_runs, out = {}, []
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


def place_red(rng, levels):
    """The red cell: a spot where the motif is one level, so it never straddles an edge."""
    for _ in range(200):
        x = 3 + rng.below(PX - 6 - RED_SPAN)
        y = 3 + rng.below(PY - 6 - RED_SPAN)
        block = {levels[y + j][x + i] for i in range(RED_SPAN) for j in range(RED_SPAN)}
        if len(block) == 1:
            return x, y
    return PX // 2 - 1, PY // 2 - 1


def hero_svg(name):
    rng = Rng(seed_from(name))
    levels = make_levels(rng)
    warp_up, sizes = make_structure(rng)
    red_x, red_y = place_red(rng, levels)

    defs = []
    for level in range(3):
        size = sizes[level]
        warp, weft = thread_runs((size, size), lambda x, y, lv=level: warp_up(lv, x, y))
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
    warp, weft = thread_runs(
        (RED_SPAN * PIXEL, RED_SPAN * PIXEL),
        lambda x, y: warp_up(
            levels[(top + y) // PIXEL][(left + x) // PIXEL], left + x, top + y
        ),
    )
    cell = (
        f'<g transform="translate({ORIGIN_X + left * CELL} {ORIGIN_Y + top * CELL})">'
        f'<path class="r" d="{warp}{weft}"/></g>'
    )

    def theme(mode):
        p = PALETTE[mode]
        return f".g{{fill:{p['bg']}}}.k{{fill:{p['warp']}}}.w{{fill:{p['weft']}}}"

    style = theme("light") + f".r{{fill:{PALETTE['red']}}}"
    style += "@media (prefers-color-scheme:dark){" + theme("dark") + "}"
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {FRAME_W} {FRAME_H}" '
        f'width="{FRAME_W}" height="{FRAME_H}" role="img">\n'
        f"<title>Weave pattern generated from the name {html.escape(name)}</title>\n"
        f"<style>{style}</style>\n"
        f"<defs>{''.join(defs)}</defs>\n"
        f'<rect class="g" width="{FRAME_W}" height="{FRAME_H}"/>\n'
        + "\n".join(fields)
        + f"\n{cell}\n</svg>\n"
    )


def mark_svg():
    size, gap, cell = 30, 3, 8
    squares = []
    for row in range(3):
        for col in range(3):
            cls = "r" if (row, col) == (1, 1) else "k"
            x, y = col * (cell + gap), row * (cell + gap)
            squares.append(f'<rect class="{cls}" x="{x}" y="{y}" width="{cell}" height="{cell}"/>')
    style = (
        f".k{{fill:{PALETTE['light']['fg']}}}.r{{fill:{PALETTE['red']}}}"
        f"@media (prefers-color-scheme:dark){{.k{{fill:{PALETTE['dark']['fg']}}}}}"
    )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size}" '
        f'width="{size}" height="{size}" role="img">\n'
        "<title>machine-made mark</title>\n"
        f"<style>{style}</style>\n" + "\n".join(squares) + "\n</svg>\n"
    )


def root_css():
    def block(mode):
        p = PALETTE[mode]
        return (
            f"--bg:{p['bg']};--fg:{p['fg']};--muted:{p['muted']};--rule:{p['rule']};"
            f"--red:{PALETTE['red']};"
        )

    split = f"{ORIGIN_X / FRAME_W * 100:.3f}%"
    ratios = f"--frame-ratio:{FRAME_W} / {FRAME_H};--weave-ratio:{FRAME_W - ORIGIN_X} / {FRAME_H};"
    return (
        f":root{{{block('light')}--split:{split};{ratios}}}\n"
        f"@media (prefers-color-scheme:dark){{:root{{{block('dark')}}}}}\n"
    )


def check_palette():
    colours = [PALETTE["red"]] + [v for mode in ("light", "dark") for v in PALETTE[mode].values()]
    for colour in colours:
        if not COLOUR.fullmatch(colour):
            fail(f"palette colour {colour} is not #rrggbb", "Write each palette colour as lower-case #rrggbb with no alpha.")


def fail(message, fix):
    print(json.dumps({"error": message, "fix": fix}), file=sys.stderr)
    sys.exit(2)


def load_site():
    path = ROOT / "site.json"
    try:
        site = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"cannot read site.json: {exc}", "Fix site.json so that it is valid JSON.")

    def need(obj, key, kind, where):
        if not isinstance(obj, dict) or not isinstance(obj.get(key), kind):
            fail(f"{where}.{key} is missing or has the wrong type", f"Set {where}.{key} in site.json.")
        return obj[key]

    for key, kind in (
        ("name", str),
        ("tagline", str),
        ("owner", str),
        ("footer", str),
        ("year", int),
        ("principles", list),
        ("projects", list),
        ("houses", list),
    ):
        need(site, key, kind, "site")
    if not FILE_NAME.fullmatch(site["name"]) or ".." in site["name"]:
        fail(
            "site.name cannot be used as a file name",
            "Use lower-case letters, digits, dot, dash or underscore; start with a letter or digit; no '..'.",
        )
    for i, item in enumerate(site["principles"]):
        if not isinstance(item, str):
            fail(f"principles[{i}] is not a string", "Write each principle as one short sentence.")
    for i, item in enumerate(site["projects"]):
        for key in ("repo", "line"):
            need(item, key, str, f"projects[{i}]")
        if not REPO_NAME.fullmatch(item["repo"]) or ".." in item["repo"]:
            fail(f"projects[{i}].repo is not a repository name", "Use letters, digits, dot, dash or underscore; start with a letter or digit; no '..'.")
    for i, item in enumerate(site["houses"]):
        for key in ("name", "line", "url"):
            need(item, key, str, f"houses[{i}]")
        if not item["url"].startswith("https://"):
            fail(f"houses[{i}].url is not https", "Use an https URL.")
    repos = [p["repo"] for p in site["projects"]]
    if len(set(repos)) != len(repos):
        fail("two projects share one repo name", "Remove the duplicate from projects.")
    return site


def esc(text):
    return html.escape(text, quote=True)


def repo_url(site, repo):
    return f"https://github.com/{site['owner']}/{repo}"


def page_html(site):
    name = site["name"]
    sentences = re.split(r"(?<=[.!?])\s+", site["tagline"].strip())
    tagline = " ".join(f"<span>{esc(s)}</span>" for s in sentences if s)
    principles = "\n".join(f"<p>{esc(line)}</p>" for line in site["principles"])
    projects = "\n".join(
        f'<li><a href="{esc(repo_url(site, p["repo"]))}">{esc(p["repo"])}</a>'
        f'<p>{esc(p["line"])}</p></li>'
        for p in site["projects"]
    )
    houses = " and ".join(
        f'<a href="{esc(h["url"])}">{esc(h["name"])}</a> ({esc(h["line"])})' for h in site["houses"]
    )
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(name)}</title>
<meta name="description" content="{esc(site['tagline'])}">
<meta name="color-scheme" content="light dark">
<link rel="icon" href="mark.svg" type="image/svg+xml">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Geist:wght@400;500&amp;family=Geist+Mono:wght@400;500&amp;display=swap">
<link rel="stylesheet" href="style.css">
</head>
<body>
<a class="skip" href="#main">Skip to content</a>
<header class="masthead wrap">
<div class="masthead-frame">
<div class="masthead-text">
<img class="mark" src="mark.svg" width="56" height="56" alt="Mark of {esc(name)}: a grid of three by three squares, one of them red">
<div>
<h1>{esc(name)}</h1>
<p class="tagline">{tagline}</p>
</div>
</div>
<img class="hero" src="heroes/{esc(name)}.svg" width="{FRAME_W}" height="{FRAME_H}" alt="Weave pattern generated from the name {esc(name)}">
</div>
</header>
<main id="main">
<section class="section" aria-labelledby="work">
<div class="wrap split">
<h2 id="work">How we work</h2>
<div class="lead">
{principles}
</div>
</div>
</section>
<section class="section" aria-labelledby="projects">
<div class="wrap split">
<h2 id="projects">Projects</h2>
<ul class="projects">
{projects}
</ul>
</div>
</section>
<section class="section" aria-labelledby="houses">
<div class="wrap split">
<h2 id="houses">Houses</h2>
<p>{houses}.</p>
</div>
</section>
</main>
<footer class="section">
<div class="wrap">
<p>{esc(site['footer'])}</p>
<p>{site['year']}</p>
</div>
</footer>
</body>
</html>
"""


def llms_txt(site):
    projects = "\n".join(
        f"- [{p['repo']}]({repo_url(site, p['repo'])}): {p['line']}" for p in site["projects"]
    )
    houses = "\n".join(f"- [{h['name']}]({h['url']}): {h['line']}" for h in site["houses"])
    return (
        f"# {site['name']}\n\n> {site['tagline']}\n\n"
        + " ".join(site["principles"])
        + f"\n\n## Projects\n\n{projects}\n\n## Houses\n\n{houses}\n"
    )


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def main():
    check_palette()
    site = load_site()
    style = (ROOT / "src" / "style.css").read_text(encoding="utf-8")
    name = site["name"]
    write(DOCS / "index.html", page_html(site))
    write(DOCS / "style.css", root_css() + style)
    write(DOCS / "mark.svg", mark_svg())
    write(DOCS / "llms.txt", llms_txt(site))
    write(HEROES / f"{name}.svg", hero_svg(name))
    for stale in sorted(HEROES.glob("*.svg")):
        if stale.stem != name:
            stale.unlink()
    print(json.dumps({"built": 5}))


if __name__ == "__main__":
    main()
