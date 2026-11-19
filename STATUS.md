# STATUS

| Field | Value |
| --- | --- |
| Repo | machine-made/machine-made.github.io |
| House | machine-made |
| Line | identity |
| Visibility | public |
| Stage | live |
| Gate now | `sh gate.sh` passes; `MM_FONTS=brand-fonts sh gate.sh` needs a Playwright browser and was not run for this change |
| Next task | Update the fonts when machine-made/type releases a new version |
| Blocked by | nothing |
| Last green CI | none yet |
| Owner model | to assign |

## Proven

- Live at https://machine-made.github.io/, served by GitHub Pages from `docs/` on main.
  Checked on 2026-11-19 with `shots.py` on the built site: the page loads machine-made Weft from `docs/fonts/`.
- Two builds give byte-identical files, fonts included.
- `check_site.py` passes: the HTML parses, every local link and image resolves, the banner has
  alt text and each plate image is decorative (alt="") beside a named link, contrast is at least 4.5:1 for text and 3:1 for accent marks, one accent colour, and only the public projects and the two houses are linked. The old /chaos-atlas/ path forwards to https://openfluids.github.io/chaos-atlas/ and /dynachaos/ to https://github.com/openfluids/dynachaos.
- The page makes no external request. Every site uses machine-made fonts only, version 0.2.0: Weft, and Sans or Warp
  for the text of openfluids and BoringQuantSystems. They are files in `docs/fonts/` with their licences.
  `check_site.py` fails on any external stylesheet, preload, font or css url, on a font family or file that is not
  machine-made, on a machine-made file that is not the 0.2.0 one (SHA-256), on an `@font-face` without
  `font-display: swap`, and on bold or italic that no loaded face provides. `shots.py` records every request and
  fails on one outside `docs/`.
- `fonts/` holds the release files unchanged (README, Fonts).
- The header shows the weave and the square mark, with one red accent. Every row of dots encodes its
  section title; the checker reads the dots back and compares the text.
- `brand/` was drawn by `brand.py` from the 0.1 cut, now in `brand-fonts/`. The brand gate
  (`MM_FONTS=brand-fonts sh gate.sh`) was last run before the 0.2.0 change and was not run for it.
- Screenshots at 1280 px and 390 px, in the site's own fonts (`shots.py` checks that the fonts the
  text uses loaded). No horizontal scroll from 320 px to 1920 px. Longest line of copy under 70
  characters.

## Open risks

- The site fonts are version 0.2.0. `brand/` and the tracking values in `brand.py` are tuned to the 0.1
  cut, kept in `brand-fonts/`; `brand/` was not rebuilt (README, Fonts).
- Weft has no hinting. Small mono text (project names, footer) can look soft on Windows at low
  resolution.
- Weft covers Latin-1 only. A project name or line with other letters falls back to the system
  monospace for those letters.
- There is no CI in this repository. The gate (`sh gate.sh`) runs by hand before each merge.
