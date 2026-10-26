#!/usr/bin/env python3
"""Build the machine-made site: site.json in, docs/ out. Standard library only."""

import html
import json
import re
import shutil
import sys
from pathlib import Path
from typing import Any, NoReturn

import card

ROOT = Path(__file__).resolve().parent
DOCS = ROOT / "docs"

FILE_NAME = re.compile(r"[a-z0-9][a-z0-9._-]*")
REPO_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
COLOUR = re.compile(r"#[0-9a-f]{6}")
FONTS_HREF = "https://fonts.googleapis.com/css2?family=Geist:wght@400;500&amp;family=Geist+Mono:wght@400;500&amp;display=swap"


def root_css() -> str:
    def block(mode: str) -> str:
        p = card.MODES[mode]
        return f"--bg:{p['bg']};--fg:{p['fg']};--muted:{p['muted']};--rule:{p['rule']};--red:{card.RED};"

    split = f"{card.CARD_X / card.FRAME_W * 100:.3f}%"
    ratio = f"--frame-ratio:{card.FRAME_W} / {card.FRAME_H};"
    return (
        f":root{{{block('light')}--split:{split};{ratio}}}\n"
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
    path = ROOT / "site.json"
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
                fail(f"{where}.projects[{i}].repo is not a repository name", "Use letters, digits, dot, dash or underscore; start with a letter or digit; no '..'.")
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


def page_html(site: dict[str, Any]) -> str:
    name = site["name"]
    lines = card.sentences(site["tagline"])
    tagline = " ".join(f"<span>{esc(line)}</span>" for line in lines)
    wide_w, wide_h = card.FRAME_W, card.FRAME_H
    narrow_w, narrow_h = round(card.card_width(len(lines[0]))), card.CARD_H
    groups = "\n".join(
        f'<section class="section" aria-labelledby="{slug(g["title"])}">\n{rule_img(g["title"])}\n'
        f'<div class="wrap split">\n<h2 id="{slug(g["title"])}">{esc(g["title"])}</h2>\n'
        f'<ul class="projects">\n{project_items(site, g["projects"])}\n</ul>\n</div>\n</section>'
        for g in site["groups"]
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
<link rel="stylesheet" href="{FONTS_HREF}">
<link rel="stylesheet" href="style.css">
</head>
<body>
<a class="skip" href="#main">Skip to content</a>
<header class="masthead wrap">
<div class="masthead-frame">
<div class="masthead-text">
<div class="brand">
<img class="mark" src="mark.svg" width="{card.MARK_SIZE}" height="{card.MARK_SIZE}" alt="Mark of {esc(name)}: a small punched card with three by three holes, one of them red">
<h1>{esc(name)}</h1>
</div>
<p class="tagline">{tagline}</p>
<p class="subtitle">{esc(site['subtitle'])}</p>
</div>
<img class="hero hero-wide" src="card.svg" width="{wide_w}" height="{wide_h}" alt="A punched card that encodes the line {esc(site['tagline'])} in 7-bit ASCII">
<img class="hero hero-narrow" src="card-narrow.svg" width="{narrow_w}" height="{narrow_h}" alt="A punched card that encodes the first line, {esc(lines[0])}, in 7-bit ASCII">
<p class="caption"><span class="wide">{esc(card.CAPTION)}</span><span class="narrow">{esc(card.CAPTION_NARROW)}</span></p>
</div>
</header>
<main id="main">
{groups}
<section class="section" aria-labelledby="houses">
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


def llms_txt(site: dict[str, Any]) -> str:
    def entry(p: dict[str, str]) -> str:
        extra = f" ([site]({p['site']}))" if "site" in p else ""
        return f"- [{p['repo']}]({repo_url(site, p['repo'])}): {p['line']}{extra}"

    groups = "\n\n".join(
        f"## {g['title']}\n\n" + "\n".join(entry(p) for p in g["projects"]) for g in site["groups"]
    )
    houses = "\n".join(f"- [{h['name']}]({h['url']}): {h['line']}" for h in site["houses"])
    return (
        f"# {site['name']}\n\n> {site['tagline']}\n\n{site['subtitle']}\n\n"
        f"{groups}\n\n## Houses\n\n{houses}\n\n{site['footer']}\n"
    )


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def main() -> None:
    check_palette()
    site = load_site()
    style = (ROOT / "src" / "style.css").read_text(encoding="utf-8")
    lines = card.sentences(site["tagline"])
    files = {
        "index.html": page_html(site),
        "style.css": root_css() + style,
        "mark.svg": card.mark_svg(),
        "llms.txt": llms_txt(site),
        "card.svg": card.card_svg(" ".join(lines), framed=True),
        "card-narrow.svg": card.card_svg(lines[0], framed=False),
    }
    for title in [g["title"] for g in site["groups"]] + ["Houses", site["name"]]:
        files[f"rules/{slug(title)}.svg"] = card.rule_svg(title)
    for rel, text in files.items():
        write(DOCS / rel, text)
    shutil.rmtree(DOCS / "heroes", ignore_errors=True)
    for stale in sorted((DOCS / "rules").glob("*")):
        if f"rules/{stale.name}" not in files:
            stale.unlink()
    print(json.dumps({"built": len(files)}))


if __name__ == "__main__":
    main()
