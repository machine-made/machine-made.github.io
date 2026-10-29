#!/bin/sh
# Build one house site from this generator into the docs/ of its own Pages repository.
# Usage: sh publish.sh HOUSE PAGES_REPO_DIR   (HOUSE is a folder name in houses/)
# Run gate.sh first. Commit and push in the Pages repository through a pull request.
set -eu
cd "$(dirname "$0")"
house=${1:?name a house in houses/}
target=${2:?name the Pages repository folder}
[ -f "houses/$house/site.json" ] || { echo "houses/$house/site.json is missing"; exit 2; }
[ -d "$target/.git" ] || { echo "$target is not a git repository"; exit 2; }
work=$(mktemp -d "${TMPDIR:-/tmp}/mm-publish.XXXXXX")
trap 'rm -rf "$work"' EXIT
cp "houses/$house/site.json" "houses/$house/allow.json" "$work/"
python3 build.py --site "$work" > /dev/null
python3 check_site.py --site "$work"
rm -rf "$target/docs"
cp -R "$work/docs" "$target/docs"
echo "built houses/$house into $target/docs"
