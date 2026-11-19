#!/usr/bin/env python3
"""Fetch the live GitHub facts of the three house sites into one data file. Standard library and gh only.

Usage: python3 fetch.py OUT.json

Reads the projects of site.json and houses/*/site.json, asks the GitHub API (GraphQL through gh: one call,
then one more per further page of type releases) for each repository's language, latest release, recent
releases and last commit on the default branch, and for the newest release of each machine-made type family. Any failed call, error or missing answer stops with
exit 1 and writes nothing, so a stale page cannot ship. build.py reads OUT.json.
"""

import datetime
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
# Never listed on any site.
NEVER = {"homebrew-tap"}
FAMILIES = ("weft", "sans", "heddle", "warp")


def die(message: str) -> None:
    print(json.dumps({"error": message, "fix": "Check gh auth status and the network, then run again."}), file=sys.stderr)
    sys.exit(1)


def site_files() -> list[Path]:
    return [ROOT / "site.json", *sorted((ROOT / "houses").glob("*/site.json"))]


def repositories() -> list[tuple[str, str]]:
    """Every (owner, repo) that a house lists, in a stable order."""
    found: set[tuple[str, str]] = set()
    for path in site_files():
        site = json.loads(path.read_text(encoding="utf-8"))
        for group in site["groups"]:
            for item in group["projects"]:
                found.add((item.get("owner", site["owner"]), item["repo"]))
    return sorted(found)


def gh_graphql(query: str) -> dict[str, Any]:
    done = subprocess.run(["gh", "api", "graphql", "-f", f"query={query}"], capture_output=True, text=True, check=False)
    if done.returncode != 0:
        die(f"gh api graphql failed: {done.stderr.strip()[:300]}")
    try:
        answer = json.loads(done.stdout)
    except ValueError:
        die("gh api graphql did not return JSON")
    if answer.get("errors"):
        die("graphql errors: " + json.dumps(answer["errors"])[:300])
    return answer["data"]


RELEASE = "tagName publishedAt url isPrerelease isDraft"
TYPE_RELEASES = (
    'releases(first:100{after}, orderBy:{{field:CREATED_AT, direction:DESC}})'
    "{{pageInfo{{hasNextPage endCursor}} nodes{{" + RELEASE + "}}}}"
)
FIELDS = """primaryLanguage{name}
 latestRelease{tagName publishedAt url}
 defaultBranchRef{target{... on Commit{committedDate}}}
 releases(first:10, orderBy:{field:CREATED_AT, direction:DESC}){nodes{tagName publishedAt url isPrerelease isDraft}}"""


def main() -> None:
    if len(sys.argv) != 2:
        print("usage: python3 fetch.py OUT.json", file=sys.stderr)
        sys.exit(2)
    out = Path(sys.argv[1])
    repos = repositories()
    if any(name in NEVER for _, name in repos):
        die("a house lists homebrew-tap, which is never listed")
    parts = [f'r{i}: repository(owner:"{o}", name:"{n}"){{ {FIELDS} }}' for i, (o, n) in enumerate(repos)]
    parts.append('typerepo: repository(owner:"machine-made", name:"type"){ ' + TYPE_RELEASES.format(after="") + " }")
    data = gh_graphql("query{" + "\n".join(parts) + "}")
    result: dict[str, Any] = {"fetched": datetime.datetime.now(datetime.UTC).date().isoformat(), "repos": {}, "families": {}}
    for i, (owner, name) in enumerate(repos):
        node = data.get(f"r{i}")
        if not node or not node.get("defaultBranchRef"):
            die(f"no data for {owner}/{name}")
        releases = [r for r in node["releases"]["nodes"] if not r["isDraft"] and not r["isPrerelease"] and r["publishedAt"]]
        latest = node["latestRelease"]
        # The ten newest releases may all be prereleases; the latest stable release still counts.
        if latest and latest["publishedAt"] and latest["tagName"] not in {r["tagName"] for r in releases}:
            releases.append(latest)
        result["repos"][f"{owner}/{name}"] = {
            "lang": (node["primaryLanguage"] or {}).get("name"),
            "release": latest and {k: latest[k] for k in ("tagName", "publishedAt", "url")},
            "commit": node["defaultBranchRef"]["target"]["committedDate"],
            "releases": [{k: r[k] for k in ("tagName", "publishedAt", "url")} for r in releases],
        }
    # Every page of type releases: the newest publication of each family wins, whatever the creation order.
    page = (data.get("typerepo") or {}).get("releases") or {}
    nodes = list(page.get("nodes", []))
    while (page.get("pageInfo") or {}).get("hasNextPage"):
        after = ', after:"' + page["pageInfo"]["endCursor"] + '"'
        more = gh_graphql('query{typerepo: repository(owner:"machine-made", name:"type"){ ' + TYPE_RELEASES.format(after=after) + " }}")
        page = (more.get("typerepo") or {}).get("releases") or {}
        nodes += page.get("nodes", [])
    for r in nodes:
        family = r["tagName"].split("-v")[0]
        if family not in FAMILIES or r["isDraft"] or r["isPrerelease"] or not r["publishedAt"]:
            continue
        if family not in result["families"] or r["publishedAt"] > result["families"][family]["publishedAt"]:
            result["families"][family] = {k: r[k] for k in ("tagName", "publishedAt", "url")}
    missing = [f for f in FAMILIES if f not in result["families"]]
    if missing:
        die(f"no release found for the type families {', '.join(missing)}")
    text = json.dumps(result, indent=1, sort_keys=True) + "\n"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print(json.dumps({"repos": len(result["repos"]), "families": {k: v["tagName"] for k, v in sorted(result["families"].items())}}))


if __name__ == "__main__":
    main()
