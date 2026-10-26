# Design

One page, built by `build.py` from `site.json`. The page has one vertical axis: the left edge of
the weave in the header. Every section starts its text there.

## Grid

- Two columns on screens 720 px and wider. The left column ends at `--split` (34.091% of the
  width). The right column holds the content. Below 720 px, one column.
- Maximum width 1280 px. Side margins 16, 24 and 32 px.
- Spacing scale: 4, 8, 16, 24, 32, 48, 64, 96, 128 px. Sections are 96 or 128 px apart.
- Every section starts with a faint row of dots across the full width (see Rows of dots).
- Below 720 px the header is one column: the mark, the name, the lines and the weave, cropped to its right part so it fills the width.

## Type

- Geist Mono for the name, headings and project names. Geist for reading. Both from Google
  Fonts, linked from the page.
- Scale 1.25 on a 17 px base: 13.6, 17, 21.25, 26.6 px. The name is fluid: 30 to 48 px on small screens, 24 to 52 px beside the weave.
- Sentence case. No capitals for emphasis.
- Body copy is capped at 34rem (the larger intro at 36rem), so a line has fewer than 70 characters.
  `shots.py` counts the longest line at every width and fails at 70 or more.

## Colour

- Light: white ground, black type, grey 595959 for small text, grey D9D9D9 for rules.
- Dark: black ground, white type, grey A6A6A6, grey 2E2E2E.
- One accent, red E5251C, the same in both schemes. It appears twice: the red square in the
  mark and the red cell in the weave. It never colours text.
- The weave, the mark and the rows of dots follow the system scheme through a media query inside
  the SVG.

## Mark

A 3 by 3 grid of squares. The centre square is red. It is the favicon, it stands above the name
in the header and it is the avatar: on white, with about 18% padding. `card.py` draws it for the
site and for `brand.py`, so they match.

## Hero: how the weave is made

The weave is a Jacquard cloth. Each thread is set by a draft, as on a Jacquard loom.

1. Seed. SHA-256 of the name; the first 8 bytes seed a splitmix64 generator. The same name
   always gives the same cloth. There is no other source of randomness.
2. Frame. 1408 by 469 px. A thread cell is 4 px, so the cloth is 352 by 116 threads. The cloth
   starts at x = 480 px. The left third of the frame stays empty for the name.
3. Motif. A pixel is 4 by 4 threads. The cloth is 58 by 29 pixels. The generator picks a half
   tile of 3 to 7 pixels and a distance rule (square, diamond or octagon). Rings 1 to 3 pixels
   wide alternate between two levels; a 1 pixel ring of a third level appears one time in three;
   one pixel in 16 flips. The tile is mirrored on both axes about the centre of the cloth.
4. Draft. Level 0 is weft-faced satin: a warp thread is up one time in 5 or 8. Level 2 is the
   complement, warp-faced. Level 1 is a twill. Satin step and twill width come from the seed.
5. Drawing. Each level is one SVG pattern that holds one repeat of its draft: warp threads in
   ink, weft threads in light grey. The motif masks are merged rectangles that use the patterns.
6. Red cell. The generator picks a 2 by 2 pixel block of one level and draws it from the same
   draft, with red threads. There is at most one.

Result: about 4 KB per hero. The same input gives identical bytes.

## Rows of dots

The punched card is a detail, not the identity. Each section rule is one faint row of dots that
encodes the section title, and the footer rule encodes the site name. 7 slots a character, one
empty slot between characters, 8 px a slot. A big dot is a 1 bit and a small dot is a 0 bit; the
top slot is the high bit of the 7-bit ASCII code. The row is decorative: `aria-hidden`, empty
alt, in the rule colour, with no accent. It is cropped on a narrow screen, not scaled.
`check_site.py` reads the dots back and compares the text.

## Profile hero

The GitHub profile hero (`brand.py`) is the one place the whole card shows: the header of the
site with the square mark, the name and the lines on the left, and a punched card on the right.
The card has seven rows and one column per character, a cut top-left corner, holes for the 1
bits, and one red dot in the lowest 1 bit of the last column. It encodes "Made by machines.
Proven for machines." (38 columns). The caption, in small mono, says so.

## Quality bar

- Semantic HTML: header, main, sections with h2, lists, footer. One h1.
- Skip link first. Visible focus ring. Alt text on every image.
- Contrast: black on white 21:1, grey 595959 on white 7:1, white on black 21:1, grey A6A6A6 on
  black 8.6:1. The gate computes these.
- No script. No tracking. External requests: Google Fonts only.
- No horizontal scroll from 320 px to 1920 px. `shots.py` measures it at 320, 360, 375, 720, 1000,
  1440 and 1920 px, in light and dark.
