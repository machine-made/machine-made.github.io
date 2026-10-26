# machine-made.github.io

The machine-made website: one page and one `llms.txt`, built from `site.json`.

> **Status: draft, not published.**

## Build

```
python3 build.py        # writes docs/
python3 check_site.py   # prints OK, or one line per failure
python3 check_site.py --self-test   # breaks a copy of docs/ and checks that each break is caught
sh gate.sh              # build twice and compare, self-tests, check, forbidden words
python3 shots.py        # screenshots in shots/, light and dark; needs Playwright
```

`build.py` and `check_site.py` use only the Python 3.11 standard library. The build is
deterministic: the same `site.json` gives the same bytes.

## Files

| Path | Holds |
| --- | --- |
| `site.json` | The content: name, line, how we work, public projects, houses |
| `build.py` | The generator: page, style, mark, `llms.txt`, header weave |
| `src/style.css` | The style. `build.py` adds the colours and writes `docs/style.css` |
| `check_site.py` | The checks for the built site |
| `gate.sh` | The gate |
| `shots.py` | Screenshots at 1440 px and 375 px, the scroll check and the line-length check. Writes `shots/` |
| `DESIGN.md` | The grid, the type, the colour and the weave algorithm |
| `docs/` | The built site. Do not edit by hand |

## Rules

- The page shows the name, the line, how we work, the public projects and the two houses.
- Only public repositories are named or linked. A new public project needs an entry in
  `site.json` and in `PUBLIC_REPOS` in `check_site.py`.
- `check_site.py --deny FILE`, or `MM_DENY_FILE=FILE sh gate.sh`, also rejects any name listed
  in FILE. Keep FILE outside this repository.
- No script, no tracking, no personal names, no costs.

## Licence

To be confirmed (Apache-2.0 proposed).
