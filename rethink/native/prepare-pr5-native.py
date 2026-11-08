#!/usr/bin/env python3
"""Controller-only immutable main native build. Never contacts a deployment target."""
import argparse
import gzip
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import tarfile
import urllib.request

REPO = "martinemde/rethink"
WORKFLOW_PATH = ".github/workflows/ci.yml"


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def require_hex(value, length):
    if not re.fullmatch(r"[0-9a-f]{%d}" % length, value):
        raise ValueError("expected lowercase full hexadecimal identity")
    return value


def get(url):
    request = urllib.request.Request(url, headers={"User-Agent": "rethink-main-preparer",
                                                 "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def verify_workflow(workflow):
    if (workflow.get("path") != WORKFLOW_PATH or workflow.get("state") != "active"
            or type(workflow.get("id")) is not int or workflow["id"] <= 0):
        raise ValueError("expected active trusted ci.yml workflow")


def verify_ci(run, workflow, commit):
    verify_workflow(workflow)
    require_hex(commit, 40)
    repo = run.get("repository", {})
    head_repo = run.get("head_repository", {})
    if (run.get("workflow_id") != workflow["id"] or run.get("path") != WORKFLOW_PATH
            or run.get("event") != "push" or run.get("head_branch") != "main"
            or run.get("head_sha") != commit or run.get("status") != "completed"
            or run.get("conclusion") != "success" or type(run.get("id")) is not int
            or run["id"] <= 0 or repo.get("full_name") != REPO
            or head_repo.get("full_name") != REPO or type(repo.get("id")) is not int
            or repo["id"] <= 0 or head_repo.get("id") != repo["id"]):
        raise ValueError("expected successful trusted ci.yml push/main run for captured SHA")


def select_ci(runs, workflow, commit):
    verify_workflow(workflow)
    for run in runs.get("workflow_runs", []):
        try:
            verify_ci(run, workflow, commit)
        except ValueError:
            continue
        return run
    raise ValueError("no successful trusted ci.yml push/main run for captured SHA; retry later")


def verify_main_ancestor(comparison, revision, main):
    require_hex(revision, 40)
    require_hex(main, 40)
    if (comparison.get("status") not in ("ahead", "identical")
            or comparison.get("base_commit", {}).get("sha") != revision
            or comparison.get("merge_base_commit", {}).get("sha") != revision
            or (comparison.get("status") == "identical" and revision != main)):
        raise ValueError("requested revision must be an ancestor of captured main")


def unpack(data, destination):
    """Only ordinary files/directories under the single archive root; no links."""
    destination = Path(destination)
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
        members = archive.getmembers()
        roots = set()
        names = set()
        for member in members:
            parts = PurePosixPath(member.name).parts
            if (not parts or member.name.startswith("/") or ".." in parts
                    or "\\" in member.name or not (member.isfile() or member.isdir())):
                raise ValueError("unsafe archive member")
            roots.add(parts[0])
            if member.name in names:
                raise ValueError("duplicate archive member")
            names.add(member.name)
        if len(roots) != 1:
            raise ValueError("archive must have one root")
        for member in members:
            parts = PurePosixPath(member.name).parts[1:]
            if not parts:
                if not member.isdir():
                    raise ValueError("archive root must be a directory")
                continue
            target = destination.joinpath(*parts)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.extractfile(member) as source:
                    target.write_bytes(source.read())
                target.chmod(0o755 if member.mode & 0o111 else 0o644)


def verify_manifests(source, package_hash, lock_hash):
    for name, expected in (("package.json", package_hash), ("package-lock.json", lock_hash)):
        require_hex(expected, 64)
        if sha256((source / name).read_bytes()) != expected:
            raise ValueError(name + " differs from the approved installed manifest; dist-only blocked")


def pack_dist(dist, target):
    if not dist.is_dir() or dist.is_symlink():
        raise ValueError("missing ordinary dist directory")
    entries = sorted(dist.rglob("*"))
    files = {}
    for path in entries:
        if path.is_symlink() or not (path.is_dir() or path.is_file()):
            raise ValueError("non-regular dist entry")
        if path.is_file():
            files[path.relative_to(dist).as_posix()] = sha256(path.read_bytes())
    if not files:
        raise ValueError("empty dist")
    with target.open("wb") as output:
        with gzip.GzipFile(filename="", mode="wb", fileobj=output, mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode="w") as archive:
                for path in [dist] + entries:
                    name = "dist" if path == dist else "dist/" + path.relative_to(dist).as_posix()
                    info = tarfile.TarInfo(name)
                    info.mtime = info.uid = info.gid = 0
                    info.uname = info.gname = ""
                    info.mode = 0o755 if path.is_dir() else 0o644
                    if path.is_dir():
                        info.type = tarfile.DIRTYPE
                        archive.addfile(info)
                    else:
                        data = path.read_bytes()
                        info.size = len(data)
                        archive.addfile(info, io.BytesIO(data))
    return files


def run(command, source, log, env):
    # Build commands execute reviewed merged source locally, never via a shell.
    with log.open("ab") as output:
        output.write(("$ " + " ".join(command) + "\n").encode())
        output.flush()
        subprocess.run(command, cwd=source, env=env, stdout=output,
                       stderr=subprocess.STDOUT, check=True)


def prepare(args):
    require_hex(args.package_sha256, 64)
    require_hex(args.lock_sha256, 64)
    api = "https://api.github.com/repos/" + REPO
    # Capture main exactly once. Later main movement cannot change this build identity.
    main_bytes = get(api + "/commits/main")
    main = require_hex(json.loads(main_bytes)["sha"], 40)
    commit = require_hex(getattr(args, "revision", None) or main, 40)
    comparison_bytes = None
    if getattr(args, "revision", None):
        comparison_bytes = get(api + "/compare/" + commit + "..." + main)
        verify_main_ancestor(json.loads(comparison_bytes), commit, main)
    workflow_bytes = get(api + "/actions/workflows/ci.yml")
    workflow = json.loads(workflow_bytes)
    verify_workflow(workflow)
    runs_bytes = get(api + "/actions/workflows/" + str(workflow["id"]) +
                     "/runs?event=push&branch=main&head_sha=" + commit + "&per_page=100")
    ci_run = select_ci(json.loads(runs_bytes), workflow, commit)
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    (output / "workflow.json").write_bytes(workflow_bytes)
    (output / "ci-runs.json").write_bytes(runs_bytes)
    (output / "main.json").write_bytes(main_bytes)
    if comparison_bytes is not None:
        (output / "main-ancestry.json").write_bytes(comparison_bytes)
    archive = get("https://codeload.github.com/" + REPO + "/tar.gz/" + commit)
    (output / "source.tar.gz").write_bytes(archive)
    source = output / "source"
    source.mkdir()
    unpack(archive, source)
    verify_manifests(source, args.package_sha256, args.lock_sha256)
    # Reject checked-in build/dependency output rather than trusting or reusing it.
    if any((source / name).exists() for name in ("dist", "node_modules", ".git")):
        raise ValueError("source includes prebuilt dist, dependencies, or Git metadata")
    env = os.environ.copy()
    env["GIT_REVISION"] = commit
    env["CI"] = "true"
    log = output / "build.log"
    node = subprocess.check_output(["node", "--version"], text=True).strip()
    npm = subprocess.check_output(["npm", "--version"], text=True).strip()
    commands = [["npm", "ci", "--ignore-scripts", "--engine-strict", "--no-audit", "--no-fund"],
                ["npm", "test"], ["npm", "run", "check"], ["npm", "run", "build"]]
    for command in commands:
        run(command, source, log, env)
    verify_manifests(source, args.package_sha256, args.lock_sha256)
    version = (source / "dist/util/version.js").read_text()
    if version != "export const revision = '" + commit[:7] + "'\n":
        raise ValueError("unexpected baked revision; review build script before proceeding")
    files = pack_dist(source / "dist", output / "dist.tar.gz")
    manifest = {"schema": 1, "purpose": "review-only-native-dist", "repo": REPO,
                "workflow_id": workflow["id"], "ci_run_id": ci_run["id"], "commit": commit, "node": node, "npm": npm,
                "preparer_sha256": sha256(Path(__file__).read_bytes()),
                "commands": commands, "package_sha256": args.package_sha256,
                "lock_sha256": args.lock_sha256, "dist_files_sha256": files,
                "artifacts_sha256": {name: sha256((output / name).read_bytes()) for name in
                    (("source.tar.gz", "dist.tar.gz", "build.log", "workflow.json", "ci-runs.json", "main.json")
                     + (("main-ancestry.json",) if comparison_bytes is not None else ()))}}
    # Success marker is written last. No deployment approval is implied.
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(output / "manifest.json")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revision", help="full main-history SHA; default captures current main")
    parser.add_argument("--package-sha256", required=True, help="approved current package.json hash")
    parser.add_argument("--lock-sha256", required=True, help="approved current package-lock.json hash")
    parser.add_argument("--output", required=True, help="new local private workspace directory")
    args = parser.parse_args()
    os.umask(0o077)
    prepare(args)


if __name__ == "__main__":
    main()
