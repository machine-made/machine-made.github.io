#!/bin/sh
# The gate: one GitHub fetch, then for every house a deterministic build from that fetch, the self-tests, the site
# checks, the browser checks and the forbidden words.
# Prints FETCHED, DETERMINISTIC, SELF-TEST OK, OK, HOUSES OK, SHOTS OK and "grep clean"; any failure exits 1.
# Needs gh (signed in), uv and Chrome or Chromium. MM_CHROME=PATH names the browser for shots.py when Playwright has
# none of its own; MM_AXE=FILE (axe.min.js of axe-core) also runs axe on every page and fails on a violation.
# MM_SHOTS=0 skips the browser checks and prints SHOTS SKIPPED.
# MM_DENY_FILE=FILE (outside this repository) also rejects the names listed in FILE.
# MM_FONTS=DIR (the fonts brand.py draws from, brand-fonts/ in this repository; needs Playwright, fontTools and brotli)
# also builds brand/ twice, compares the hashes and compares the result with the brand/ in this repository.
set -eu
cd "$(dirname "$0")"
export PYTHONDONTWRITEBYTECODE=1
# The build cuts fonts (fontTools, brotli) and encodes images (Pillow); the versions are pinned so that two
# machines write the same bytes. shots.py drives a browser through Playwright.
UV="uv run --quiet --with fonttools==4.68.0 --with brotli==1.2.1 --with pillow==13.0.0"
UV_SHOTS="uv run --quiet --with playwright==1.65.1"
data=$(mktemp "${TMPDIR:-/tmp}/mm-data.XXXXXX")
first=$(mktemp "${TMPDIR:-/tmp}/mm-gate.XXXXXX")
second=$(mktemp "${TMPDIR:-/tmp}/mm-gate.XXXXXX")
brand_one=$(mktemp -d "${TMPDIR:-/tmp}/mm-gate.XXXXXX")
brand_two=$(mktemp -d "${TMPDIR:-/tmp}/mm-gate.XXXXXX")
shots=$(mktemp -d "${TMPDIR:-/tmp}/mm-shots.XXXXXX")
trap 'rm -rf "$data" "$first" "$second" "$brand_one" "$brand_two" "$shots"' EXIT
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
browser() {
  # $1: the folder that holds site.json and docs/; $2: the folder for the shots
  if [ "${MM_SHOTS:-1}" = 0 ]; then
    return 0
  fi
  set -- "$1" "$2"
  if [ -n "${MM_CHROME:-}" ]; then set -- "$@" --chrome "$MM_CHROME"; fi
  if [ -n "${MM_AXE:-}" ]; then set -- "$@" --axe "$MM_AXE"; fi
  site=$1 out=$2
  shift 2
  $UV_SHOTS python3 shots.py --site "$site" --out "$out" "$@"
}
# One fetch for the whole gate: both builds of every house read the same facts, so the comparison means something.
python3 fetch.py "$data" > /dev/null
echo FETCHED
$UV python3 build.py --data "$data" > /dev/null
hashes docs > "$first"
$UV python3 build.py --data "$data" > /dev/null
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
    echo "brand/ is not what brand.py writes; run python3 brand.py --fonts brand-fonts"
    exit 1
  fi
  echo "BRAND DETERMINISTIC"
else
  echo "BRAND SKIPPED: set MM_FONTS=brand-fonts to check brand/"
fi
$UV python3 check_site.py --data "$data" --self-test
if [ -n "${MM_DENY_FILE:-}" ]; then
  $UV python3 check_site.py --data "$data" --deny "$MM_DENY_FILE"
else
  $UV python3 check_site.py --data "$data"
fi
browser . "$shots/machine-made"
# Every house in houses/ builds from this generator: twice, the same, then its own checks.
for house in houses/*/; do
  copy=$(mktemp -d "${TMPDIR:-/tmp}/mm-house.XXXXXX")
  cp "$house/site.json" "$house/allow.json" "$copy/"
  $UV python3 build.py --site "$copy" --data "$data" > /dev/null
  hashes "$copy/docs" > "$first"
  $UV python3 build.py --site "$copy" --data "$data" > /dev/null
  hashes "$copy/docs" > "$second"
  if ! cmp -s "$first" "$second"; then
    echo "the two builds of $house differ"
    rm -rf "$copy"
    exit 1
  fi
  if ! $UV python3 check_site.py --site "$copy" --data "$data"; then
    echo "the house site $house fails its checks"
    rm -rf "$copy"
    exit 1
  fi
  if ! browser "$copy" "$shots/$(basename "$house")"; then
    echo "the house site $house fails its browser checks"
    rm -rf "$copy"
    exit 1
  fi
  rm -rf "$copy"
done
echo "HOUSES OK"
if [ "${MM_SHOTS:-1}" = 0 ]; then
  echo "SHOTS SKIPPED: the browser checks did not run"
fi
# -I skips the font and image files: binary data is not copy. check_site.py reads the licences.
if grep -rniIE '\$[0-9]|tokens' docs/; then
  echo "grep found a forbidden word"
  exit 1
fi
echo "grep clean"
