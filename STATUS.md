# STATUS

| Field | Value |
| --- | --- |
| Repo | machine-made/machine-made.github.io |
| House | machine-made |
| Line | identity |
| Visibility | public |
| Stage | live |
| Gate now | `sh gate.sh` and `MM_FONTS=fonts sh gate.sh` pass |
| Next task | Update the fonts when machine-made/type releases Weft or Sans 0.2 |
| Blocked by | nothing |
| Last green CI | none yet |
| Owner model | to assign |

## Proven

- Live at https://machine-made.github.io/, served by GitHub Pages from `docs/` on main.
  Checked on 2026-10-27: the page loads machine-made Weft and machine-made Sans from `docs/fonts/`.
- Two builds give byte-identical files, fonts included.
- `check_site.py` passes: the HTML parses, every local link and image resolves, every image has
  alt text, contrast is 7:1 or better for text, one accent colour, and only the public projects and the two houses are linked. The old /chaos-atlas/ and /dynachaos/ paths forward to openfluids.
- The page makes no external request. The two fonts, machine-made Weft and machine-made Sans,
  are files in `docs/fonts/` with their licences. `check_site.py` fails on any external
  stylesheet, preload, font or css url, on an `@font-face` without `font-display: swap`, and on a
  font file that is not WOFF2. `shots.py` records every request and fails on one outside `docs/`.
- `fonts.py` cuts the fonts from machine-made/type a24c99d. Two runs give the same bytes. The
  cut keeps both Weft axes (wght 100 to 900, FRAG 0 to 15) and the Sans weight axis.
- The header shows the weave and the square mark, with one red accent. Every row of dots encodes its
  section title; the checker reads the dots back and compares the text.
- `brand/` is what `brand.py` writes from `fonts/`, and two runs give the same bytes
  (`MM_FONTS=fonts sh gate.sh`).
- Screenshots at 1440 px and 375 px, light and dark, in the site's own fonts (`shots.py` checks
  that both fonts loaded). No horizontal scroll from 320 px to 1920 px. Longest line of copy 62
  characters.

## Open risks

- The fonts are version 0.1. A new release needs `python3 fonts.py --type DIR`, a new `brand/`
  and a look at the screenshots: the tracking values in `src/style.css` and `brand.py` are tuned
  to the 0.1 metrics.
- Weft has no hinting. Small mono text (project names, footer) can look soft on Windows at low
  resolution.
- Weft covers Latin-1 only. A project name or line with other letters falls back to the system
  monospace for those letters.
- There is no CI in this repository. The gate (`sh gate.sh`) runs by hand before each merge.
