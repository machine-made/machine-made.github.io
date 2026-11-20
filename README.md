[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)

`machine-made.github.io` is the machine-made website and the generator of the three house sites (machine-made,
openfluids, BoringQuantSystems): one page, a 404 page and one `llms.txt` per house, built from `site.json` and the
live GitHub facts of each project.

> **Status: live at https://machine-made.github.io/.**

## Build

The build cuts font subsets (fontTools, brotli) and encodes images (Pillow), so it runs under `uv` with pinned
versions; the browser checks need Playwright. `gh` must be signed in: the build reads the GitHub API.

```
UV="uv run --with fonttools==4.68.0 --with brotli==1.2.1 --with pillow==13.0.0"
python3 fetch.py facts.json                    # the GitHub facts of every project; fails on any API error
$UV python3 build.py --data facts.json         # writes docs/; without --data it runs fetch.py itself
$UV python3 check_site.py --data facts.json    # prints OK, or one line per failure
$UV python3 check_site.py --data facts.json --self-test   # breaks a copy of docs/ and checks that each break is caught
uv run --with playwright==1.65.1 python3 shots.py --chrome PATH --axe axe.min.js   # shots and the browser checks
sh gate.sh              # one fetch, every house built twice and compared, self-tests, checks, browser checks, forbidden words
python3 brand.py --fonts brand-fonts   # the profile hero and the avatar in brand/; needs Playwright, fontTools, brotli
MM_FONTS=brand-fonts sh gate.sh        # the gate, with brand/ built twice and compared
```

`gate.sh` reads `MM_CHROME` (the browser for `shots.py`), `MM_AXE` (axe.min.js; runs axe-core on every page) and
`MM_SHOTS=0` (skip the browser checks). A failed fetch stops the build before any file is written, so a stale page
cannot ship. The build is deterministic: the same source tree and the same facts file give the same bytes.

## Files

| Path | Holds |
| --- | --- |
| `site.json` | The machine-made house: name, owner, line, the six colours and the face, the groups with their bar-2 labels, the four sites, redirects |
| `src/system.css` | The one stylesheet of the four sites: tokens and components. `build.py` writes it into each page without its comments |
| `fetch.py` | The GitHub facts: language, latest release, releases and last commit of every project, and the newest release of each type family |
| `build.py` | The generator: the home page, the 404 page, `llms.txt`, font subsets, image variants, `og.jpg`, icons |
| `card.py` | The marks: the square logo and the punched card of the profile hero. The palette |
| `brand.py` | The GitHub profile hero and the avatar, drawn from `card.py` and `brand-fonts/`. Writes `brand/` |
| `fonts/` | The machine-made web fonts (Weft, Sans, Heddle, Warp 0.2.0), their licences and `SOURCES.json` |
| `brand-fonts/` | The 0.1 cut of Weft and Sans that `brand.py` draws the hero from, with their licences. Only `brand.py` reads it |
| `brand/` | The profile hero (light and dark: SVG, PNG, PNG @2x) and `avatar.png`. Do not edit by hand |
| `img/org/` | The banner of each house (1408 x 469) and the avatar of openfluids and BoringQuantSystems (360 x 360) |
| `img/repo/` | The banner of each project (704 x 235) |
| `check_site.py` | The checks for the built site |
| `gate.sh` | The gate |
| `shots.py` | Screenshots at 390 and 1280 px and the browser checks (README, Build; the docstring lists them). Writes `shots/` |
| `DESIGN.md` | The page, the grid, the type, the colour, the images and the mark |
| `docs/` | The built machine-made site. Do not edit by hand |
| `houses/<name>/site.json` | A house site from this same generator: openfluids, boringquantsystems |
| `houses/<name>/allow.json` | That house's public list, kept apart from its `site.json`: the checks pass only when both agree |
| `publish.sh` | Builds one house into the `docs/` of its own Pages repository. `gate.sh` builds and checks every house |

## Houses

One generator, one design, one bar 1 for every house. A house site is its `site.json` and its `allow.json` in
`houses/`. Each page shows the other two houses and the type site in its houses row, so a build reads the
`site.json` of every house. `gate.sh` builds each house twice from one fetch, compares the bytes and runs its
checks. `publish.sh` writes the built site into the house's own Pages repository; that change lands there through a
pull request.

## Fonts

Every page is set in machine-made typefaces only, from [machine-made/type](https://github.com/machine-made/type)
(https://machine-made.github.io/type/), all at version 0.2.0. Weft sets the bars, the labels, the facts and the
footer; Sans sets the reading text; the house line is in the house face (Weft, Heddle or Warp). machine-made Sans is
based on Plus Jakarta Sans (see its licence file). All are under the SIL Open Font License 1.1; the build ships the
licence of each font it uses next to it in `docs/fonts/`.

`fonts/` holds the release files, unchanged; `fonts/SOURCES.json` records the release, the asset, the size and the
SHA-256 of each, and `check_site.py` pins the same hashes in `SOURCES`. The build cuts one subset per font and page:
the characters of the page (and their capitals, since labels are set in capitals), every layout feature that still
acts on them and every variation axis. The build fails when a subset loses an axis or a feature the style uses
(ss01, tabular, old-style and proportional figures, small capitals, kerning); `check_site.py` checks the same on the
files in `docs/fonts/`, and that every character the page sets in a font is in its subset. To update, copy the new
release files into `fonts/` and change `SOURCES.json`, `SOURCES` in `check_site.py` and the table below.

| File | Family, version | Release asset (machine-made/type) | Bytes | SHA-256 |
| --- | --- | --- | --- | --- |
| `fonts/mm-weft.woff2` | machine-made Weft 0.2.0, variable (wght 100 to 900, FRAG 0 to 100) | `weft-v0.2.0`, `MachineMadeWeft.FRAG.wght.woff2` | 77,208 | `9115be68c727ae8c707eed1097f878fd7e7bd54fa75bd70b099e94e4e5e71e85` |
| `fonts/mm-sans.woff2` | machine-made Sans 0.2.0, variable (wght 200 to 800) | `sans-v0.2.0`, `MachineMadeSans.wght.woff2` | 73,236 | `8ec52cf1b8a799dcda3aab4cf967d681cbd8bffd3f4cb581ed4e5ffa72e0864e` |
| `fonts/mm-heddle.woff2` | machine-made Heddle 0.2.0, variable (wght 100 to 900, wdth 70 to 140) | `heddle-v0.2.0`, `MachineMadeHeddle.wdth.wght.woff2` | 77,600 | `3f7d0bde0d436dc800abc9b9c760938f38f19c627cc3378bb199032c3a6ec0e1` |
| `fonts/mm-warp-regular.woff2` | machine-made Warp 0.2.0, Regular | `warp-v0.2.0`, `MachineMadeWarp-Regular.woff2` | 82,732 | `035042b467e6c138666b2e6b3b3a38eeb8d6dc3602ac4354f1e335e425101481` |

`brand/` was drawn from the 0.1 cut of Weft and Sans, which stays in `brand-fonts/` so that `brand.py` still
reproduces `brand/`. Rebuilding `brand/` from the 0.2.0 fonts changes the profile images and is a separate change.

## Rules

- The page shows the house line, the public projects with their live facts, Latest and the houses.
- Only public repositories are named or linked. A new public project needs an entry in `site.json` and in the
  house's `allow.json`. `homebrew-tap` is never listed.
- `check_site.py --deny FILE`, or `MM_DENY_FILE=FILE sh gate.sh`, also rejects any name listed in FILE. Keep FILE
  outside this repository.
- No script, no tracking, no personal names, no costs.

## Licence

Apache-2.0. See [LICENSE](LICENSE).

The fonts in `fonts/` stay under the SIL Open Font License 1.1. See `fonts/mm-heddle-OFL.txt`, `fonts/mm-sans-OFL.txt`,
`fonts/mm-warp-OFL.txt` and `fonts/mm-weft-OFL.txt`.
