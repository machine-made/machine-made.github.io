#!/bin/sh
# The gate: deterministic build, self-tests, site checks, forbidden words.
# Prints DETERMINISTIC, SELF-TEST OK, OK and "grep clean"; any failure exits 1.
# MM_DENY_FILE=FILE (outside this repository) also rejects the names listed in FILE.
# MM_FONTS=DIR (the site fonts, fonts/ in this repository; needs Playwright, fontTools and brotli)
# also builds brand/ twice, compares the hashes and compares the result with the brand/ in this
# repository.
set -eu
cd "$(dirname "$0")"
export PYTHONDONTWRITEBYTECODE=1
first=$(mktemp "${TMPDIR:-/tmp}/mm-gate.XXXXXX")
second=$(mktemp "${TMPDIR:-/tmp}/mm-gate.XXXXXX")
brand_one=$(mktemp -d "${TMPDIR:-/tmp}/mm-gate.XXXXXX")
brand_two=$(mktemp -d "${TMPDIR:-/tmp}/mm-gate.XXXXXX")
trap 'rm -rf "$first" "$second" "$brand_one" "$brand_two"' EXIT
hashes() {
  python3 - "$1" <<'PY'
import hashlib
import sys
from pathlib import Path

root = Path(sys.argv[1])
for path in sorted(root.rglob("*")):
    if path.is_file():
        print(hashlib.sha256(path.read_bytes()).hexdigest(), path.relative_to(root).as_posix())
PY
}
python3 build.py > /dev/null
hashes docs > "$first"
python3 build.py > /dev/null
hashes docs > "$second"
if ! cmp -s "$first" "$second"; then
  echo "the two builds differ"
  diff "$first" "$second" || true
  exit 1
fi
echo DETERMINISTIC
if [ -n "${MM_FONTS:-}" ]; then
  python3 brand.py --fonts "$MM_FONTS" --out "$brand_one" > /dev/null
  python3 brand.py --fonts "$MM_FONTS" --out "$brand_two" > /dev/null
  hashes "$brand_one" > "$first"
  hashes "$brand_two" > "$second"
  if ! cmp -s "$first" "$second"; then
    echo "the two brand builds differ"
    diff "$first" "$second" || true
    exit 1
  fi
  if ! diff -rq "$brand_one" brand; then
    echo "brand/ is not what brand.py writes; run python3 brand.py --fonts DIR"
    exit 1
  fi
  echo "BRAND DETERMINISTIC"
else
  echo "BRAND SKIPPED: set MM_FONTS=fonts to check brand/"
fi
python3 check_site.py --self-test
if [ -n "${MM_DENY_FILE:-}" ]; then
  python3 check_site.py --deny "$MM_DENY_FILE"
else
  python3 check_site.py
fi
# Every house in houses/ builds from this generator: twice, the same, then its own checks.
for house in houses/*/; do
  copy=$(mktemp -d "${TMPDIR:-/tmp}/mm-house.XXXXXX")
  cp "$house/site.json" "$house/allow.json" "$copy/"
  python3 build.py --site "$copy" > /dev/null
  hashes "$copy/docs" > "$first"
  python3 build.py --site "$copy" > /dev/null
  hashes "$copy/docs" > "$second"
  if ! cmp -s "$first" "$second"; then
    echo "the two builds of $house differ"
    rm -rf "$copy"
    exit 1
  fi
  if ! python3 check_site.py --site "$copy"; then
    echo "the house site $house fails its checks"
    rm -rf "$copy"
    exit 1
  fi
  rm -rf "$copy"
done
echo "HOUSES OK"
# -I skips the font files: binary data is not copy. check_site.py reads the licences.
if grep -rniIE '\$[0-9]|tokens' docs/; then
  echo "grep found a forbidden word"
  exit 1
fi
echo "grep clean"
