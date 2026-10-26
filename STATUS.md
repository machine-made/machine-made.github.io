# STATUS

| Field | Value |
| --- | --- |
| Repo | machine-made/machine-made.github.io |
| House | machine-made |
| Line | identity |
| Visibility | public |
| Stage | draft |
| Gate now | `sh gate.sh` passes |
| Next task | Founder review |
| Blocked by | Founder review |
| Last green CI | none yet |
| Owner model | to assign |

## Proven

- Two builds give byte-identical files.
- `check_site.py` passes: the HTML parses, every local link and image resolves, every image has
  alt text, contrast is 7:1 or better for text, one accent colour, and only the public projects (with the one chaos-atlas site link) and the two houses are linked.
- The punched card in the header encodes the line in 7-bit ASCII, and every row of dots encodes its
  section title. The checker reads the dots back and compares the text.
- `brand/` is what `brand.py` writes, and two runs give the same bytes (`MM_FONTS=DIR sh gate.sh`).
- Screenshots at 1440 px and 375 px, light and dark. No horizontal scroll at 375 px.

## Open risks

- Fonts come from Google Fonts at view time. Offline, the page falls back to system fonts. The
  screenshots used local copies of Geist because the build sandbox cannot reach Google Fonts.
- Publishing is a separate step and needs the founder.
