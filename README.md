# machine-made.github.io

The machine-made website: one page and one `llms.txt`, built from `site.json`.

> **Status: draft, not published.**

## Build

```
python3 build.py        # writes docs/
python3 check_site.py   # prints OK, or one line per failure
python3 check_site.py --self-test   # breaks a copy of docs/ and checks that each break is caught
sh gate.sh              # build twice and compare, self-tests, check, forbidden words
python3 shots.py        # screenshots in shots/, light and dark; needs Playwright
python3 brand.py --fonts fonts   # the profile hero and the avatar in brand/; needs Playwright, fontTools, brotli
MM_FONTS=fonts sh gate.sh        # the gate, with brand/ built twice and compared
python3 fonts.py --type DIR      # fonts/ from a checkout of machine-made/type; needs fontTools, brotli
```

`build.py`, `card.py` and `check_site.py` use only the Python 3.11 standard library. The build is
deterministic: the same source tree gives the same bytes.

## Files

| Path | Holds |
| --- | --- |
| `site.json` | The content: name, line, subtitle line, the three project groups, houses |
| `card.py` | The marks: the square logo, the punched card of the profile hero and the rows of dots. The palette |
| `build.py` | The generator: page, style, `llms.txt`, the weave; uses `card.py` |
| `brand.py` | The GitHub profile hero and the avatar, drawn from `card.py` and `fonts/`. Writes `brand/` |
| `fonts.py` | Cuts the web fonts from machine-made/type. Writes `fonts/` |
| `fonts/` | The two web fonts and their licences. `build.py` copies them to `docs/fonts/` |
| `brand/` | The profile hero (light and dark: SVG, PNG, PNG @2x) and `avatar.png`. Do not edit by hand |
| `src/style.css` | The style. `build.py` adds the colours and writes `docs/style.css` |
| `check_site.py` | The checks for the built site |
| `gate.sh` | The gate |
| `shots.py` | Screenshots at 1440 px and 375 px, the scroll check and the line-length check. Writes `shots/` |
| `DESIGN.md` | The grid, the type, the colour, the mark, the weave and the rows of dots |
| `docs/` | The built site. Do not edit by hand |

## Fonts

The site is set in machine-made Weft 0.1 (monospace: name, headings, project names) and
machine-made Sans 0.1 (reading text), from [machine-made/type](https://github.com/machine-made/type).
machine-made Sans is based on Plus Jakarta Sans by Gumpita Rahayu, Tokotype. Both are under the
SIL Open Font License 1.1; the licences are `fonts/mm-weft-OFL.txt` and `fonts/mm-sans-OFL.txt`,
and the build ships them next to the fonts in `docs/fonts/`.

`fonts/` is vendored, so the build needs only this repository. To update it, check out
machine-made/type and run `python3 fonts.py --type DIR`, then `python3 brand.py --fonts fonts`
and `MM_FONTS=fonts sh gate.sh`. The cut keeps the variable axes (Weft: wght 100 to 900, FRAG 0
to 15; Sans: wght 200 to 800) and Latin-1 with common punctuation. The same input gives the
same bytes.

| File | Source (machine-made/type a24c99d) | Source size | Cut size |
| --- | --- | --- | --- |
| `fonts/mm-weft.woff2` | `fonts/weft/variable/MachineMadeWeft[FRAG,wght].ttf` | 61,332 bytes as WOFF2 | 23,744 bytes |
| `fonts/mm-sans.woff2` | `fonts/sans/variable/MachineMadeSans[wght].ttf` | 72,172 bytes as WOFF2 | 24,112 bytes |

## Rules

- The page shows the name, the line, the subtitle line, the public projects in three groups and the two houses.
- Only public repositories are named or linked. A new public project needs an entry in
  `site.json` and in `PUBLIC_REPOS` in `check_site.py`.
- `check_site.py --deny FILE`, or `MM_DENY_FILE=FILE sh gate.sh`, also rejects any name listed
  in FILE. Keep FILE outside this repository.
- No script, no tracking, no personal names, no costs.

## Licence

To be confirmed (Apache-2.0 proposed).
