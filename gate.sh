#!/bin/sh
# The gate: deterministic build, self-tests, site checks, forbidden words.
# Prints DETERMINISTIC, SELF-TEST OK, OK and "grep clean"; any failure exits 1.
# MM_DENY_FILE=FILE (outside this repository) also rejects the names listed in FILE.
set -eu
cd "$(dirname "$0")"
export PYTHONDONTWRITEBYTECODE=1
first=$(mktemp)
second=$(mktemp)
trap 'rm -f "$first" "$second"' EXIT
hashes() { find docs -type f | LC_ALL=C sort | xargs sha256sum; }
python3 build.py > /dev/null
hashes > "$first"
python3 build.py > /dev/null
hashes > "$second"
if ! cmp -s "$first" "$second"; then
  echo "the two builds differ"
  diff "$first" "$second" || true
  exit 1
fi
echo DETERMINISTIC
python3 check_site.py --self-test
if [ -n "${MM_DENY_FILE:-}" ]; then
  python3 check_site.py --deny "$MM_DENY_FILE"
else
  python3 check_site.py
fi
if grep -rniE '\$[0-9]|tokens' docs/; then
  echo "grep found a forbidden word"
  exit 1
fi
echo "grep clean"
