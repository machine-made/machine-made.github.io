# Algebraic Patterns, the machine-made lab log

Source of the lab log. Drafts live in `drafts/` until they are approved; they are not
built into `docs/` yet.

## Rules for a post

- One claim in the title, one figure or table, a **What failed** box, and the data
  files behind it.
- Every number comes from a committed file. The front matter names it under `data:`.
- Byline: Jac. No personal names, no private repositories linked.

## Before the first post goes live

- `build.py` gains a log page and one page per post, in the site's type and grid;
  `check_site.py` learns the new files.
- The site rules say "no costs", and the gate rejects `$` followed by a digit and the
  word "tokens". Posts 1 to 3 respect that. The pilot post will report costs and tokens,
  so the rule needs a scoped exception for `docs/log/`.
