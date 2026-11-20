# STATUS

| Field | Value |
| --- | --- |
| Repo | machine-made/machine-made.github.io |
| House | machine-made |
| Line | identity |
| Visibility | public |
| Stage | live |
| Gate now | `sh gate.sh` passes with `MM_CHROME` and `MM_AXE` set (one fetch, three houses, self-tests, browser checks); `MM_FONTS=brand-fonts sh gate.sh` was not run for this change |
| Next task | Update the fonts when machine-made/type releases a new version |
| Blocked by | nothing |
| Last green CI | none yet |
| Owner model | to assign |

## Proven

- Live at https://machine-made.github.io/, served by GitHub Pages from `docs/` on main.
- The three house sites share one design system, `src/system.css`, from the approved design of 19 Nov: two bars,
  the banner, the house line, Latest, the plates with live GitHub facts, the houses row, the footer, a 404 page.
- One GitHub fetch per gate; two builds of every house from it give byte-identical files, fonts and images included.
  A failed fetch stops the build before any file is written.
- `check_site.py` passes on every house: the HTML parses, every local link, image and srcset resolves, the facts,
  Latest and the houses row match the fetched data, contrast is at least 7:1 for text and 4.5:1 for muted text on
  the ground and the surface, every size is a step of the type scale and every spacing a token of the spacing
  scale, only the public projects and the four sites are linked. The old /chaos-atlas/ path forwards to
  https://openfluids.github.io/chaos-atlas/ and /dynachaos/ to https://github.com/openfluids/dynachaos.
- Every site uses machine-made fonts only, version 0.2.0, as subsets cut from the release files that `fonts/SOURCES.json`
  and `check_site.py` pin by SHA-256; every subset keeps its axes and the features the style uses.
- `shots.py` passes on every house: no sideways scroll from 320 to 1920 px, no glyph in a system font, no facts line
  wraps at 1280 px, every link at least 44 px high at 390 px, axe-core 0 violations on the home page and the 404 page.
- `brand/` was drawn by `brand.py` from the 0.1 cut, now in `brand-fonts/`.

## Open risks

- The site fonts are version 0.2.0. `brand/` and the tracking values in `brand.py` are tuned to the 0.1
  cut, kept in `brand-fonts/`; `brand/` was not rebuilt (README, Fonts).
- Weft has no hinting. Small mono text (project names, footer) can look soft on Windows at low
  resolution.
- Weft covers Latin-1 only. A project name or line with other letters would fall back to a system font;
  `shots.py` fails on that.
- The facts are as fresh as the last build: the site changes only when someone builds and publishes it.
- There is no CI in this repository. The gate (`sh gate.sh`) runs by hand before each merge.
