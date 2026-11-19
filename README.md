[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)

`machine-made.github.io` is the machine-made website: one page and one `llms.txt`, built from `site.json`.

> **Status: live at https://machine-made.github.io/.**

## Build

```
python3 build.py        # writes docs/
python3 check_site.py   # prints OK, or one line per failure
python3 check_site.py --self-test   # breaks a copy of docs/ and checks that each break is caught
sh gate.sh              # build twice and compare, self-tests, check, forbidden words
python3 shots.py        # screenshots at 390 and 1280 px and the layout, font and tap-target checks; needs Playwright
python3 brand.py --fonts brand-fonts   # the profile hero and the avatar in brand/; needs Playwright, fontTools, brotli
MM_FONTS=brand-fonts sh gate.sh        # the gate, with brand/ built twice and compared
```

`build.py`, `card.py` and `check_site.py` use only the Python 3.11 standard library. The build is
deterministic: the same source tree gives the same bytes.

## Files

| Path | Holds |
| --- | --- |
| `site.json` | The content: name, line, subtitle line, the project groups, papers, lab log entries, houses |
| `card.py` | The marks: the square logo, the punched card of the profile hero and the rows of dots. The palette |
| `build.py` | The generator: page, style, `llms.txt`, the weave; uses `card.py` |
| `brand.py` | The GitHub profile hero and the avatar, drawn from `card.py` and `brand-fonts/`. Writes `brand/` |
| `fonts/` | The machine-made web fonts (Weft, Sans, Warp 0.2.0) and their licences. `build.py` copies them to `docs/fonts/` |
| `brand-fonts/` | The 0.1 cut of Weft and Sans that `brand.py` draws the hero from, with their licences. Only `brand.py` reads it; the sites do not ship it |
| `brand/` | The profile hero (light and dark: SVG, PNG, PNG @2x) and `avatar.png`. Do not edit by hand |
| `src/style.css` | The style. `build.py` adds the colours and writes `docs/style.css` |
| `check_site.py` | The checks for the built site |
| `gate.sh` | The gate |
| `shots.py` | Screenshots at 390 px and 1280 px, the scroll check, the line-length check, the font, plate-geometry and tap-target checks. Writes `shots/` |
| `DESIGN.md` | The grid, the type, the colour, the mark, the weave and the rows of dots |
| `docs/` | The built site. Do not edit by hand |
| `houses/<name>/site.json` | A house site from this same generator: openfluids, boringquantsystems |
| `houses/<name>/allow.json` | That house's public list, kept apart from its `site.json`: the checks pass only when both agree |
| `publish.sh` | Builds one house into the `docs/` of its own Pages repository. `gate.sh` builds and checks every house |

## Houses

One generator, one look, one tab row for every house. A house site is its `site.json` and its
`allow.json` in `houses/`. `gate.sh` builds each house twice, compares the bytes and runs its
checks. `publish.sh` writes the built site into the house's own Pages repository; that change
lands there through a pull request.

## Fonts

Every page is set in machine-made typefaces only, from [machine-made/type](https://github.com/machine-made/type)
(https://machine-made.github.io/type/), all at version 0.2.0. machine-made Weft sets the top bar, the labels and
the footer on every site, and the text of machine-made.github.io. machine-made Sans sets the text of
openfluids.github.io. machine-made Warp sets the text of boringquantsystems.github.io. machine-made Sans is
based on Plus Jakarta Sans by Gumpita Rahayu, Tokotype. All are under the SIL Open Font License 1.1; the licences
are `fonts/mm-weft-OFL.txt`, `fonts/mm-sans-OFL.txt` and `fonts/mm-warp-OFL.txt`, and the build ships each next to
its fonts in `docs/fonts/`.

`fonts/` holds the woff2 files of the 0.2.0 releases, unchanged. Each file is byte-identical to the release asset
and to the file the type site serves. The build copies them; it does not cut or change them. `check_site.py` pins
the SHA-256 of each file and fails on a page that declares another font family, loads another font file, or ships a
machine-made file that is not the 0.2.0 one. To update, copy the new files into `fonts/`, change the hashes in
`FONT_SPECS` of `check_site.py` and the table below.

| File | Family, version | Release asset (machine-made/type) | Bytes | SHA-256 |
| --- | --- | --- | --- | --- |
| `fonts/mm-weft.woff2` | machine-made Weft 0.2.0, variable (wght 100 to 900, FRAG 0 to 100) | `weft-v0.2.0`, `MachineMadeWeft.FRAG.wght.woff2` | 77,208 | `9115be68c727ae8c707eed1097f878fd7e7bd54fa75bd70b099e94e4e5e71e85` |
| `fonts/mm-sans.woff2` | machine-made Sans 0.2.0, variable (wght 200 to 800) | `sans-v0.2.0`, `MachineMadeSans.wght.woff2` | 73,236 | `8ec52cf1b8a799dcda3aab4cf967d681cbd8bffd3f4cb581ed4e5ffa72e0864e` |
| `fonts/mm-warp-regular.woff2` | machine-made Warp 0.2.0, Regular | `warp-v0.2.0`, `MachineMadeWarp-Regular.woff2` | 82,732 | `035042b467e6c138666b2e6b3b3a38eeb8d6dc3602ac4354f1e335e425101481` |
| `fonts/mm-warp-italic.woff2` | machine-made Warp 0.2.0, Italic | `warp-v0.2.0`, `MachineMadeWarp-Italic.woff2` | 67,688 | `4eb9d3abbff429bfc6130fb82790876e8416fe65bab69f11e2d7c35d693d6d53` |

Sans is loaded as roman only: no page uses italic. Warp has no bold in use. The page sets no bold and no
italic, so no face is faked. `shots.py` checks the computed family, weight and style of every text element.

The files are the full fonts, not a cut. `brand/` was drawn from the 0.1 cut of Weft and Sans, which stays in
`brand-fonts/` so that `brand.py` still reproduces `brand/`. Rebuilding `brand/` from the 0.2.0 fonts changes the
profile images and is a separate change.

## Rules

- The page shows the name, the line, the subtitle line, the public projects.
- Only public repositories are named or linked. A new public project needs an entry in
  `site.json` and in `PUBLIC_REPOS` in `check_site.py`.
- `check_site.py --deny FILE`, or `MM_DENY_FILE=FILE sh gate.sh`, also rejects any name listed
  in FILE. Keep FILE outside this repository.
- The Lab log section lists each entry with a status, like Papers. `LOG` in `check_site.py` is the
  allowed list. Drafts of posts and the data behind them do not go in this repository. An entry
  appears here only after the owner has approved its text.
- No script, no tracking, no personal names, no costs.

## Licence

Apache-2.0. See [LICENSE](LICENSE).

The fonts in `fonts/` stay under the SIL Open Font License 1.1. See `fonts/mm-sans-OFL.txt`, `fonts/mm-warp-OFL.txt` and `fonts/mm-weft-OFL.txt`.
