# Design

One page, built by `build.py` from `site.json`. The page has one vertical axis: the left edge of
the left edge of the card in the header. Every section starts its text there.

## Grid

- Two columns on screens 720 px and wider. The left column ends at `--split` (36.364% of the
  width, the left edge of the card). The right column holds the content. Below 720 px, one column.
- Maximum width 1280 px. Side margins 16, 24 and 32 px.
- Spacing scale: 4, 8, 16, 24, 32, 48, 64, 96, 128 px. Sections are 96 or 128 px apart.
- Every section starts with a 1 px rule across the full width.
- Below 720 px the header is one column: the name, the line, the narrow card and its caption.

## Type

- Geist Mono for the name, headings and project names. Geist for reading. Both from Google
  Fonts, linked from the page.
- Scale 1.25 on a 17 px base: 13.6, 17, 21.25, 26.6 px. The name is fluid: 30 to 48 px on small screens, 24 to 52 px beside the card.
- Sentence case. No capitals for emphasis.
- Body copy is capped at 34rem (the larger intro at 36rem), so a line has fewer than 70 characters.
  `shots.py` counts the longest line at every width and fails at 70 or more.

## Colour

- Light: white ground, black type, grey 595959 for small text, grey D9D9D9 for rules.
- Dark: black ground, white type, grey A6A6A6, grey 2E2E2E.
- One accent, red E5251C, the same in both schemes. It appears twice: the red hole in the mark
  and the red dot on the card. It never colours text.
- The card, the mark and the rows of dots follow the system scheme through a media query inside
  the SVG.

## The punched card

One identity, drawn by `card.py`. The site (`build.py`) and the GitHub profile (`brand.py`) both
call it, so they match.

- Seven rows, one column per character. A big dot is a 1 bit and a small dot is a 0 bit. The
  top row is the high bit of the 7-bit ASCII code.
- The card is a rectangle with a cut top-left corner. The big dots are holes: the ground shows
  through. In light mode the card is black; in dark mode it is white.
- One red dot, in the lowest 1 bit of the last column.
- The header card encodes "Made by machines. Proven for machines." (38 columns). Below 720 px
  the page shows a narrower card with the first line only, and the caption says so.
- The caption, in small mono: "The card: the line above in 7-bit ASCII."
- The weave of the first draft is gone. The one frame, 1408 by 469 px, is the same on the site and
  on the profile; the card starts at x = 512 px, which is the axis of the page.

## Rules of dots

Each section rule is one faint row of dots that encodes the section title, and the footer rule
encodes the site name. 7 slots a character, one empty slot between characters, 8 px a slot. It is
decorative: `aria-hidden`, empty alt, in the rule colour. It is cropped on a narrow screen, not
scaled. `check_site.py` reads the dots back and compares the text.

## Mark

A small punched card: 34 units, cut corner 8.5, a 3 by 3 grid of holes, the lower right hole red.
It is the favicon and it stands before the name. The avatar is the mark alone on white with
about 18% padding.

## Quality bar

- Semantic HTML: header, main, sections with h2, lists, footer. One h1.
- Skip link first. Visible focus ring. Alt text on every image.
- Contrast: black on white 21:1, grey 595959 on white 7:1, white on black 21:1, grey A6A6A6 on
  black 8.6:1. The gate computes these.
- No script. No tracking. External requests: Google Fonts only.
- No horizontal scroll from 320 px to 1920 px. `shots.py` measures it at 320, 360, 375, 720, 1000,
  1440 and 1920 px, in light and dark.
