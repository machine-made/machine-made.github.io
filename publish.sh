#!/bin/sh
# Build one house site from this generator into the docs/ of its own Pages repository.
# Usage: sh publish.sh HOUSE PAGES_REPO_DIR [FACTS.json]   (HOUSE is a folder name in houses/)
# FACTS.json is the file fetch.py wrote; without it, publish.sh fetches once. Use the same file for every house of
# one change, so the houses show the same facts. Run gate.sh first. Commit and push in the Pages repository through
# a pull request.
set -eu
house=${1:?name a house in houses/}
target=${2:?name the Pages repository folder}
# Resolve the paths before moving into the generator, so a relative path means the caller's folder.
target=$(cd "$target" && pwd)
facts=${3:-}
if [ -n "$facts" ]; then facts=$(cd "$(dirname "$facts")" && pwd)/$(basename "$facts"); fi
cd "$(dirname "$0")"
UV="uv run --quiet --with fonttools==4.68.0 --with brotli==1.2.1 --with pillow==13.0.0"
if [ "$target" = "$(pwd)" ]; then
  echo "the target is this generator repository; name the house's own Pages repository"
  exit 2
fi
[ -f "houses/$house/site.json" ] || { echo "houses/$house/site.json is missing"; exit 2; }
[ -d "$target/.git" ] || { echo "$target is not a git repository"; exit 2; }
work=$(mktemp -d "${TMPDIR:-/tmp}/mm-publish.XXXXXX")
trap 'rm -rf "$work"' EXIT
if [ -z "$facts" ]; then
  facts="$work/facts.json"
  python3 fetch.py "$facts" > /dev/null
fi
cp "houses/$house/site.json" "houses/$house/allow.json" "$work/"
$UV python3 build.py --site "$work" --data "$facts" > /dev/null
$UV python3 check_site.py --site "$work" --data "$facts"
rm -rf "$target/docs"
cp -R "$work/docs" "$target/docs"
echo "built houses/$house into $target/docs"
