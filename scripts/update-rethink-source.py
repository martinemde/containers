#!/usr/bin/env python3
"""Propose an immutable public Rethink main pin; never execute downloaded source."""
import hashlib
import json
from pathlib import Path
import re
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
SOURCE = "https://github.com/martinemde/rethink"


def download(url):
    request = Request(url, headers={"User-Agent": "containers-rethink-source-update"})
    with urlopen(request) as response:
        return response.read()


def update_pin(recipe, readme, revision, checksum):
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("Expected a full source commit SHA")
    old_revision = re.search(r"^ENV GIT_REVISION=([0-9a-f]{40})$", recipe, re.M).group(1)
    old_checksum = re.search(r'echo "([0-9a-f]{64})  /tmp/source.tar.gz"', recipe).group(1)
    if recipe.count(old_revision) != 2 or readme.count(old_revision) != 1:
        raise ValueError("Unexpected source pin layout")
    if recipe.count(old_checksum) != 1 or readme.count(old_checksum) != 1:
        raise ValueError("Unexpected source checksum layout")
    if not re.fullmatch(r"[0-9a-f]{64}", checksum):
        raise ValueError("Expected an archive SHA256")
    return tuple(text.replace(old_revision, revision).replace(old_checksum, checksum)
                 for text in (recipe, readme))


def successful_main_ci(runs, revision):
    return any(run["event"] == "push" and run["head_branch"] == "main"
               and run["head_sha"] == revision and run["conclusion"] == "success"
               and run["status"] == "completed"
               and run["path"] == ".github/workflows/ci.yml"
               and run["repository"]["full_name"] == "martinemde/rethink"
               and run["head_repository"]["full_name"] == "martinemde/rethink"
               for run in runs)


def main():
    revision = json.loads(download("https://api.github.com/repos/martinemde/rethink/commits/main"))["sha"]
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("Expected a full source commit SHA")
    recipe_path = ROOT / "rethink/Containerfile"
    readme_path = ROOT / "rethink/README.md"
    recipe, readme = recipe_path.read_text(), readme_path.read_text()
    # No rebuild or new archive checksum if main has not moved.
    if f"ENV GIT_REVISION={revision}\n" in recipe:
        print(revision)
        return
    runs = json.loads(download(
        "https://api.github.com/repos/martinemde/rethink/actions/workflows/ci.yml/runs"
        f"?branch=main&event=push&head_sha={revision}&status=success&per_page=100"
    ))["workflow_runs"]
    if not successful_main_ci(runs, revision):
        raise RuntimeError(f"No successful trusted push-to-main CI run for {revision}")
    archive = download(f"{SOURCE}/archive/{revision}.tar.gz")
    checksum = hashlib.sha256(archive).hexdigest()
    recipe, readme = update_pin(recipe, readme, revision, checksum)
    recipe_path.write_text(recipe)
    readme_path.write_text(readme)
    print(revision)


if __name__ == "__main__":
    main()
