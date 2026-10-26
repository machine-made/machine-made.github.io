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
  alt text, contrast is 7:1 or better for text, one accent colour, the left third of the weave is
  empty, and only the public projects (with the one chaos-atlas site link) and the two houses are linked.
- Screenshots at 1440 px and 375 px, light and dark. No horizontal scroll at 375 px.

## Open risks

- Fonts come from Google Fonts at view time. Offline, the page falls back to system fonts. The
  screenshots used local copies of Geist because the build sandbox cannot reach Google Fonts.
- Publishing is a separate step and needs the founder.
