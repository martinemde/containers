"""Select public Rethink main only after its trusted push CI succeeds."""
import hashlib
import json
import re
import urllib.parse
import urllib.request

REPO = "martinemde/rethink"
WORKFLOW = ".github/workflows/ci.yml"
API = "https://api.github.com/repos/" + REPO


def fetch(url):
    request = urllib.request.Request(url, headers={"User-Agent": "rethink-publisher"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def select_source(get=fetch):
    revision = json.loads(get(API + "/branches/main"))["commit"]["sha"]
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("Invalid main revision")
    query = urllib.parse.urlencode(dict(branch="main", event="push", status="success",
                                       head_sha=revision, per_page=100))
    runs = json.loads(get(API + "/actions/workflows/ci.yml/runs?" + query))["workflow_runs"]
    trusted = [run for run in runs if (
        run["head_sha"] == revision and run["head_branch"] == "main"
        and run["event"] == "push" and run["status"] == "completed"
        and run["conclusion"] == "success" and run["path"] == WORKFLOW
        and run["repository"]["full_name"] == REPO
        and run["head_repository"]["full_name"] == REPO)]
    if not trusted:
        raise ValueError("Current application main has no trusted successful push CI")
    archive = get(f"https://github.com/{REPO}/archive/{revision}.tar.gz")
    return {"revision": revision, "archive_sha256": hashlib.sha256(archive).hexdigest(),
            "ci_run": str(trusted[0]["id"])}


if __name__ == "__main__":
    for key, value in select_source().items():
        print(f"{key}={value}")
