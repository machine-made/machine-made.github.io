# Design

One design system for the four sites: machine-made, openfluids, BoringQuantSystems and type. This generator builds
the first three; the type site copies the same `src/system.css`. The stylesheet is the specification: its header
comment lists the scale, the spacing, the grid and the four uses of the accent. A house sets only its six colours,
its face, its banner, its bar-2 labels and its groups (`site.json`).

## Page

From top to bottom, the same on every house:

1. Bar 1: the four sites, in the same order and face everywhere. The current site is marked, not linked.
2. Bar 2: the house logo (the mark on machine-made, the organisation avatar elsewhere) and one link per group,
   then GitHub. It sticks to the top; its bottom line appears after the first scroll.
3. The banner, in the h1, with the house name as its alt text. It loads first.
4. The house line, in the house face.
5. Latest: the newest release of each repository, distinct repositories, newest first, at most three.
6. The groups: a label (the 3 x 3 section mark and the title) and the plates. A plate is the repository banner as
   a link, one line (with a site or docs link when the project has one) and the live facts: language, latest
   release or "unreleased", last commit.
7. The houses: the other two houses and the type site, each with its banner, its line and its newest release.
8. The footer: the four sites on one line.

The 404 page has the same bars and footer, "Not found" in the house face and a link home. GitHub Pages serves it
at any depth, so its addresses start at the site root.

## Grid and spacing

- 12 columns, 24 px gutter, content 1200 px at most. Side margins 16, 24 and 32 px.
- A row puts its label in columns 1 to 3 and its content in columns 4 to 12; below 860 px both take the full width.
- Plates: three columns, two below 1000 px, one below 520 px. Images are 3:1.
- Spacing: 4, 8, 12, 16, 24, 32, 48, 64, 96 px (`--sp-1` to `--sp-9`), nothing else.

## Type

- Weft for the bars, the labels, the facts and the footer. Sans for all reading text. The house line in the house
  face: Weft on machine-made, Heddle on openfluids, Warp on BoringQuantSystems.
- One scale, ratio 1.25 on 16 px: steps -1 to 5 (12.8 to 48.8 px). The house line is fluid between steps 2 and 3.
- The fonts are machine-made, version 0.2.0 (README, Fonts). Each page ships a subset of each font it uses, with
  every variation axis and every feature the style asks for, and preloads the house face.
- Weights stay inside the range of the variable font, so no weight is faked. No italic.

## Colour

Six colours per house: ground, surface, line, text, muted, accent. Text on the ground and on the surface is at
least 7:1, muted text at least 4.5:1, the accent at least 3:1 on the ground. The accent has four uses: the bar-1
marker, the bar-2 marker, the centre cell of the section mark, the link underline. It never colours text.

| House | Ground | Surface | Line | Text | Muted | Accent |
| --- | --- | --- | --- | --- | --- | --- |
| machine-made | #0a0a0b | #141416 | #26262a | #ecebe6 | #8b8b90 | #e5251c |
| openfluids | #0d1116 | #141a21 | #252c33 | #e6eef2 | #8395a0 | #5cc8d6 |
| BoringQuantSystems | #050507 | #0e0e11 | #1f1f23 | #ecebe6 | #8b8b90 | #3ddc97 |

## Images

Every plate and banner ships as AVIF and JPEG at two widths (352 and 704 px for a plate, 704 and 1408 px for a
banner) with `srcset` and `sizes`; images below the fold load lazily. `og.jpg` is the banner on the house ground at
1200 by 630. Icons: the mark (`mark.svg`) on machine-made, the organisation avatar elsewhere, and a 180 px touch icon.

## Mark

A 3 by 3 grid of squares. The centre square is red. It is the favicon of machine-made, the logo in its bar 2 and,
small, the section mark before every label. `card.py` draws it for the site and for `brand.py`, so they match.

## Profile hero

The GitHub profile hero (`brand.py`) is the one place the whole punched card shows: the square mark, the name and
the lines on the left, and a punched card on the right. The card has seven rows and one column per character, a
cut top-left corner, holes for the 1 bits, and one red dot in the lowest 1 bit of the last column. It encodes
"Made by machines. Proven for machines." (38 columns). The caption, in small mono, says so.

## Quality bar

- Semantic HTML: bars, main, sections with h2, lists, footer. One h1, no skipped heading level.
- Skip link first. Visible focus ring in the accent. Alt text on the banner; every other image is decorative and its
  link carries the name.
- No script. No tracking. No external request: `check_site.py` fails on any external stylesheet, font, preload or
  CSS url, and `shots.py` fails when the page asks for a file outside the site.
- No horizontal scroll from 320 px to 1920 px, and no element past the right edge outside a scrolling box.
- No glyph drawn in a system font, at 390 and 1280 px, on the home page and the 404 page.
- Every link at least 44 px high at 390 px.
