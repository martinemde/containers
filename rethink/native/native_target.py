#!/usr/bin/env python3
"""Offline native dist-only transaction for an already provisioned Rethink guest.

No installer, package manager, unit rewrite, remote fetch, or automatic rollback.
An interrupted/failed intent requires operator recovery; never rerun around it.
"""
import argparse
import base64
import ctypes
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import pwd
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tarfile
import time
import urllib.request
import uuid

PACKAGE_SHA = "c20df55c835768bd425aa5fc6b3d234e2764bd4ba8cf94eaa8c7b8cea6a63a0a"
LOCK_SHA = "599e59e87a093010ca0b852ee68f324cd9863c62b787dadee47651acebc708a2"
NAMES = ("washer", "dryer", "sidekick")
APP_UNIT = "rethink.service"
MAX_UNPACKED = 512 * 1024 ** 2
SPACE_RESERVE = 64 * 1024 ** 2


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def hex_value(value, length):
    require(isinstance(value, str) and re.fullmatch(r"[a-f0-9]{%d}" % length, value), "Invalid hexadecimal identity")
    return value


def private_json(path, value):
    """Durable atomic journal/baseline write; caller owns a private parent."""
    path = Path(path)
    temporary = path.with_name(path.name + ".new")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump(value, stream, sort_keys=True, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    sync_dir(path.parent)


def sync_dir(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def strict_json(payload):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, "Duplicate JSON key")
            result[key] = value
        return result
    def invalid_constant(value):
        raise RuntimeError("Non-finite JSON constant")
    return json.loads(payload, object_pairs_hook=pairs, parse_constant=invalid_constant)


def regular(path):
    path = Path(path)
    require(path.is_file() and not path.is_symlink(), "Expected ordinary file")
    # No symlinked ancestor may redirect a pinned absolute path.
    require(path.resolve() == path.absolute(), "Linked ancestor")
    return path


def file_identity(path):
    path = regular(path)
    value = path.stat()
    return {"sha256": digest(path), "uid": value.st_uid, "gid": value.st_gid,
            "mode": stat.S_IMODE(value.st_mode)}


def checked_members(archive, root=None):
    entries = {}
    total = 0
    for item in archive:
        name = item.name.rstrip("/")
        parts = PurePosixPath(name).parts
        require(parts and not name.startswith("/") and ".." not in parts
                and "\\" not in name and name == "/".join(parts)
                and (item.isfile() or item.isdir()) and not item.issparse(), "Unsafe artifact path/type")
        require(root is None or parts[0] == root, "Unexpected artifact root")
        require(name not in entries, "Duplicate artifact path")
        require(not item.mode & 0o7000, "Privileged artifact mode")
        total += item.size
        require(total <= MAX_UNPACKED and len(entries) < 100000, "Oversized artifact")
        entries[name] = item
    for name, item in entries.items():
        for parent in PurePosixPath(name).parents:
            if str(parent) in entries:
                require(entries[str(parent)].isdir(), "Artifact file used as directory")
    require(bool(entries), "Empty artifact")
    return entries


def read_member(archive, members, name):
    require(name in members and members[name].isfile(), "Missing artifact file")
    with archive.extractfile(members[name]) as stream:
        return stream.read()


def validate_request(request):
    require(request.get("schema") == 1, "Unsupported request schema")
    for key in ("expected_current_revision", "revision"):
        hex_value(request.get(key), 40)
    require(request["revision"] != request["expected_current_revision"], "Candidate already current")
    for key in ("source_sha256", "dist_sha256", "manifest_sha256", "baseline_sha256"):
        hex_value(request.get(key), 64)
    require(request.get("package_sha256") == PACKAGE_SHA and request.get("lock_sha256") == LOCK_SHA,
            "Dist-only request changes approved dependencies")
    switches = request.get("enabled_recorders")
    require(isinstance(switches, dict) and set(switches) == set(NAMES)
            and all(type(value) is bool for value in switches.values()), "Explicit three recorder booleans required")


def validate_artifacts(directory, request):
    """Read-only: check every archive member before any extraction or service stop."""
    validate_request(request)
    directory = Path(directory)
    for name, key in (("manifest.json", "manifest_sha256"), ("source.tar.gz", "source_sha256"),
                      ("dist.tar.gz", "dist_sha256")):
        require(digest(regular(directory / name)) == request[key], "Artifact checksum mismatch")
    manifest = strict_json((directory / "manifest.json").read_text())
    require(manifest.get("schema") == 1 and manifest.get("commit") == request["revision"], "Wrong candidate manifest")
    require(manifest.get("package_sha256") == PACKAGE_SHA and manifest.get("lock_sha256") == LOCK_SHA,
            "Artifact dependency manifests changed")
    for name, key in (("source.tar.gz", "source_sha256"), ("dist.tar.gz", "dist_sha256")):
        require(manifest.get("artifacts_sha256", {}).get(name) == request[key], "Manifest artifact identity mismatch")
    with tarfile.open(directory / "source.tar.gz", "r:gz") as archive:
        members = checked_members(archive)
        roots = {PurePosixPath(name).parts[0] for name in members}
        require(len(roots) == 1, "Source must have one archive root")
        prefix = next(iter(roots)) + "/"
        for name, expected in (("package.json", PACKAGE_SHA), ("package-lock.json", LOCK_SHA)):
            payload = read_member(archive, members, prefix + name)
            require(hashlib.sha256(payload).hexdigest() == expected, "Source dependencies changed")
        require(not any(name.startswith(prefix + forbidden + "/") or name == prefix + forbidden
                        for name in members for forbidden in ("dist", "node_modules", ".git")), "Source includes generated runtime")
    with tarfile.open(directory / "dist.tar.gz", "r:gz") as archive:
        members = checked_members(archive, "dist")
        actual = {name.removeprefix("dist/"): hashlib.sha256(read_member(archive, members, name)).hexdigest()
                  for name, item in members.items() if item.isfile()}
        require(actual == manifest.get("dist_files_sha256"), "Dist file inventory mismatch")
        for name in ("dist/rethink-cloud.js", "dist/tools/rethink-capture.js", "dist/util/version.js"):
            read_member(archive, members, name)
        require(read_member(archive, members, "dist/util/version.js") ==
                ("export const revision = '" + request["revision"][:7] + "'\n").encode(), "Wrong baked revision")
    return manifest


def extract_dist(directory, destination, request):
    # Validate again on the private copied artifacts, not the caller's mutable originals.
    validate_artifacts(directory, request)
    with tarfile.open(Path(directory) / "dist.tar.gz", "r:gz") as archive:
        members = checked_members(archive, "dist")
        for name, item in members.items():
            path = Path(destination) / name
            if item.isdir():
                path.mkdir(parents=True, exist_ok=True)
                path.chmod(0o755)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                with archive.extractfile(item) as source, path.open("xb") as output:
                    shutil.copyfileobj(source, output)
                    output.flush()
                    os.fsync(output.fileno())
                path.chmod(0o644)
        for path in sorted((Path(destination) / "dist").rglob("*"), reverse=True):
            if path.is_dir():
                path.chmod(0o755)
                sync_dir(path)
        sync_dir(Path(destination) / "dist")
        sync_dir(destination)


def exchange(left, right):
    """Linux renameat2 exchange: no interval where /opt/rethink/dist is missing."""
    libc = ctypes.CDLL(None, use_errno=True)
    rename = libc.renameat2
    rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    rename.restype = ctypes.c_int
    if rename(-100, os.fsencode(left), -100, os.fsencode(right), 2) != 0:
        error = ctypes.get_errno()
        raise OSError(error, "Atomic dist exchange failed")
    sync_dir(Path(left).parent)
    sync_dir(Path(right).parent)


def strip_comments(text):
    # Config uses strip-json-comments in the app; preserve quoted comment tokens.
    token = re.compile(r'"(?:\\.|[^"\\])*"|//[^\n]*|/\*.*?\*/', re.S)
    return token.sub(lambda match: match[0] if match[0].startswith('"') else " ", text)


def tree_inventory(root):
    root = Path(root)
    require(root.is_dir() and root.resolve() == root.absolute(), "Linked/missing dist root")
    inventory = {}
    for path in root.rglob("*"):
        require(not path.is_symlink() and (path.is_dir() or path.is_file()), "Linked/special dist entry")
        if path.is_file():
            inventory[path.relative_to(root).as_posix()] = digest(path)
    require(bool(inventory), "Empty installed dist")
    return inventory


def appended_marker(path, before, phase):
    info = regular(path).stat()
    require((info.st_ino, info.st_dev) == (before["inode"], before["device"])
            and info.st_size >= before["size"], "Capture replaced/truncated")
    with Path(path).open("rb") as stream:
        stream.seek(before["size"])
        payload = stream.read(8 * 1024 ** 2)
    events = [strict_json(line) for line in payload.split(b"\n")[:-1] if line]
    return any(isinstance(event, dict) and event.get("k") == "marker" and event.get("phase") == phase
               for event in events)


def runtime_identity(app, state, config, pid, socket_output, proc=Path("/proc")):
    require(pid.isdigit() and int(pid) > 0, "Missing app process")
    process = proc / pid
    expected = ["/usr/bin/node", str(app / "dist/rethink-cloud.js"), str(config)]
    require(process.joinpath("cmdline").read_bytes().rstrip(b"\0").split(b"\0") ==
            [part.encode() for part in expected], "Running app command mismatch")
    require(process.joinpath("exe").resolve() == Path("/usr/bin/node").resolve()
            and process.joinpath("cwd").resolve() == state, "Running app executable/cwd mismatch")
    status = dict(line.split(":", 1) for line in process.joinpath("status").read_text().splitlines() if ":" in line)
    require(set(status["Uid"].split()) == {"997"} and set(status["Gid"].split()) == {"988"}, "Running app UID/GID mismatch")
    # comm may contain spaces; fields after the final ')' start at stat field3.
    fields = process.joinpath("stat").read_text().rsplit(")", 1)[1].split()
    start_ticks = fields[19]
    endpoints = set()
    for line in socket_output.splitlines():
        if re.search(r"pid=" + re.escape(pid) + r"(?:,|\))", line):
            pieces = line.split()
            require(len(pieces) >= 5, "Unsupported socket inspection")
            endpoints.add(pieces[3])
    require(endpoints == {"10.0.40.5:443", "10.0.40.5:8883", "127.0.0.1:44401"}, "Unexpected/missing app listeners")
    return {"pid": pid, "start_ticks": start_ticks, "listeners": sorted(endpoints)}


class NativeTarget:
    def __init__(self):
        self.app = Path("/opt/rethink")
        self.state = Path("/var/lib/rethink")
        self.config = Path("/etc/rethink/config.json")
        self.journals = Path("/var/lib/rethink-deploy")

    def run(self, *argv):
        return subprocess.check_output(argv, text=True, stderr=subprocess.PIPE).strip()

    def properties(self, unit):
        keys = ("FragmentPath", "DropInPaths", "Transient", "ActiveState", "SubState", "UnitFileState",
                "User", "Group", "UMask", "KillSignal", "Restart", "ExecStart", "ExecStop", "MainPID",
                "WorkingDirectory", "StandardInput", "StandardOutput", "StandardError", "Result",
                "ExecMainCode", "ExecMainStatus")
        output = self.run("systemctl", "show", "--all", unit, *["--property=" + key for key in keys])
        values = dict(line.split("=", 1) for line in output.splitlines() if "=" in line)
        # systemd omits an empty ExecStop even with --all on some releases.
        # This is the only optional property; never default required identity/state.
        values.setdefault("ExecStop", "")
        require(set(values) == set(keys), "Incomplete unit properties")
        require(values["Transient"] == "no" and values["FragmentPath"] == "/etc/systemd/system/" + unit,
                "Requires existing persistent native units")
        require(values["User"] == "rethink" and values["Group"] == "rethink" and values["UMask"] == "0077",
                "Unexpected runtime identity")
        return values

    def argv(self, values):
        matches = re.findall(r"argv\[\]=(.*?) ;", values["ExecStart"])
        require(len(matches) == 1 and "\\" not in matches[0], "Unsupported effective unit command")
        return shlex.split(matches[0])

    def snapshot(self):
        account = pwd.getpwnam("rethink")
        require((account.pw_uid, account.pw_gid) == (997, 988), "Wrong native account")
        require(self.app.is_dir() and self.app.resolve() == self.app and self.state.is_dir()
                and self.state.resolve() == self.state, "Linked native root")
        release = strict_json(regular(self.app / ".release.json").read_text())
        revision = hex_value(release.get("revision"), 40)
        require(regular(self.app / "dist/util/version.js").read_text() ==
                "export const revision = '" + revision[:7] + "'\n", "Installed release/baked revision mismatch")
        require(digest(regular(self.app / "package.json")) == PACKAGE_SHA and
                digest(regular(self.app / "package-lock.json")) == LOCK_SHA, "Installed dependency manifests changed")
        config = strict_json(strip_comments(regular(self.config).read_text()))
        files = [self.config, self.app / "package.json", self.app / "package-lock.json", Path("/etc/nftables.conf")]
        for key in ("ca_key_file", "ca_cert_file"):
            path = Path(config.get(key, ""))
            require(path.is_absolute() and path.is_relative_to(self.state), "CA must use existing absolute state paths")
            files.append(path)
        if config.get("custom_root_cert_file"):
            path = Path(config["custom_root_cert_file"])
            require(path.is_absolute(), "Custom root must use absolute path")
            files.append(path)
        if config.get("bridge"):
            path = Path(config["bridge"].get("storage_path", ""))
            require(path.is_absolute() and path.is_relative_to(self.state), "Bridge storage must remain in state root")
        units = {}
        captures = {}
        for unit in [APP_UNIT] + ["rethink-" + name + "-capture.service" for name in NAMES]:
            values = self.properties(unit)
            files.append(Path(values["FragmentPath"]))
            for path in shlex.split(values["DropInPaths"]):
                files.append(Path(path))
            argv = self.argv(values)
            if unit == APP_UNIT:
                require(argv == ["/usr/bin/node", str(self.app / "dist/rethink-cloud.js"), str(self.config)]
                        and values["WorkingDirectory"] == str(self.state) and values["ActiveState"] == "active"
                        and values["KillSignal"] in ("15", "SIGTERM") and not values["ExecStop"],
                        "Unexpected/inactive native application")
            else:
                name = unit.removeprefix("rethink-").removesuffix("-capture.service")
                path = self.state / "captures" / name / "passive.jsonl"
                require(len(argv) == 5 and argv[:3] == ["/usr/bin/node", str(self.app / "dist/tools/rethink-capture.js"), "127.0.0.1:44401"]
                        and re.fullmatch(r"[a-f0-9-]{36}", argv[3]) and argv[4] == str(path), "Unexpected recorder command")
                require(values["KillSignal"] in ("2", "SIGINT") and values["Restart"] == "always"
                        and not values["ExecStop"], "Recorder must stop via configured SIGINT")
                require((values["UnitFileState"], values["ActiveState"]) in
                        (("enabled", "active"), ("disabled", "inactive")), "Recorder enablement/runtime mismatch")
                if values["ActiveState"] == "active":
                    actual = Path("/proc") / values["MainPID"] / "cmdline"
                    require(actual.read_bytes().rstrip(b"\0").split(b"\0") == [part.encode() for part in argv], "Recorder process mismatch")
                if path.exists():
                    info = regular(path).stat()
                    require((info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode)) == (997, 988, 0o600), "Capture not private/native")
                    captures[name] = {"inode": info.st_ino, "device": info.st_dev, "size": info.st_size}
                else:
                    require(values["ActiveState"] == "inactive", "Active recorder has no capture")
                    captures[name] = None
            # Preserve effective settings but omit identifiers/argv from baseline output.
            effective = self.run("systemctl", "cat", unit) + "\n" + json.dumps(self.argv(values))
            units[unit] = {"definition_sha256": hashlib.sha256(effective.encode()).hexdigest(),
                           "active": values["ActiveState"] == "active", "enabled": values["UnitFileState"]}
        self.verify_dependencies()
        runtime = self.runtime()
        return {"schema": 1, "revision": revision, "dist_files_sha256": tree_inventory(self.app / "dist"),
                "runtime": runtime, "release": release,
                "source_marker": regular(self.app / ".source-sha256").read_text(),
                "files": {str(path): file_identity(path) for path in files}, "units": units, "captures": captures,
                "nft_sha256": hashlib.sha256(self.run("nft", "-s", "list", "ruleset").encode()).hexdigest()}

    def verify_dependencies(self):
        lock = strict_json((self.app / "package-lock.json").read_text())
        require(lock.get("lockfileVersion") in (2, 3), "Unsupported lock format")
        require((self.app / "node_modules").is_dir() and not (self.app / "node_modules").is_symlink(), "Missing/linked dependencies")
        for name, item in lock["packages"].items():
            if not name or item.get("dev"):
                continue
            path = PurePosixPath(name)
            require(path.parts[0] == "node_modules" and ".." not in path.parts and not path.is_absolute()
                    and not item.get("link"), "Unsupported production dependency")
            installed = self.app / name / "package.json"
            if item.get("optional") and not installed.exists():
                continue
            require(strict_json(regular(installed).read_text()).get("version") == item.get("version"), "Installed dependency mismatch")

    def invariants(self, baseline):
        for path, expected in baseline["files"].items():
            require(file_identity(path) == expected, "Preserved configuration/unit/CA changed")
        require(hashlib.sha256(self.run("nft", "-s", "list", "ruleset").encode()).hexdigest() == baseline["nft_sha256"], "Effective firewall changed")
        for unit, expected in baseline["units"].items():
            values = self.properties(unit)
            effective = self.run("systemctl", "cat", unit) + "\n" + json.dumps(self.argv(values))
            require(hashlib.sha256(effective.encode()).hexdigest() == expected["definition_sha256"]
                    and values["UnitFileState"] == expected["enabled"], "Effective unit changed")
        self.verify_dependencies()

    def stop(self, units):
        # systemctl stop suppresses Restart=always and uses the pinned KillSignal=SIGINT.
        self.run("systemctl", "stop", *units)
        for unit in units:
            values = self.properties(unit)
            require(values["ActiveState"] == "inactive" and values["MainPID"] == "0", "Unit did not stop cleanly")
            require(values["Result"] == "success", "Unit stop failed or timed out")
            if unit != APP_UNIT:
                # Recorder handles SIGINT and exits zero after flushing its append stream.
                require(values["ExecMainCode"] == "1" and values["ExecMainStatus"] == "0",
                        "Recorder did not exit cleanly after SIGINT")

    def start(self, unit):
        self.run("systemctl", "start", unit)

    def runtime(self):
        values = self.properties(APP_UNIT)
        require(values["ActiveState"] == "active", "Application inactive")
        return runtime_identity(self.app, self.state, self.config, values["MainPID"],
                                self.run("ss", "-H", "-lntp"))

    def health(self):
        runtime = self.runtime()
        if hasattr(self, "candidate_files"):
            require(tree_inventory(self.app / "dist") == self.candidate_files, "Candidate dist identity changed")
            require((runtime["pid"], runtime["start_ticks"]) != self.previous_process,
                    "Candidate start did not replace old process")
        # Local management is HTTP, not appliance TLS. No unverified TLS context exists.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open("http://127.0.0.1:44401/", timeout=3) as response:
            require(response.status == 200 and response.url == "http://127.0.0.1:44401/", "Management health failed")

    def space_needed(self):
        total = 0
        device = self.state.stat().st_dev
        for path in self.state.rglob("*"):
            info = path.lstat()
            require(not path.is_symlink() and (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode))
                    and info.st_dev == device, "State backup cannot omit linked/special/mounted data")
            total += info.st_size + 1024
        return total + SPACE_RESERVE

    def backup(self, work, baseline):
        require(shutil.disk_usage(work).free >= self.space_needed(), "Insufficient full state backup space")
        backup = work / "backup"
        backup.mkdir(mode=0o700)
        for index, path in enumerate(baseline["files"]):
            destination = backup / (str(index) + ".preserved")
            shutil.copy2(path, destination)
            with destination.open("rb") as stream:
                os.fsync(stream.fileno())
        private_json(backup / "baseline.json", baseline)
        # Includes CA, all state and captures. Never skip large capture data.
        archive = backup / "state.tar"
        self.run("tar", "--acls", "--xattrs", "--numeric-owner", "-cpf", str(archive), "-C", str(self.state.parent), self.state.name)
        archive.chmod(0o600)
        with archive.open("rb") as stream:
            os.fsync(stream.fileno())
        sync_dir(backup)

    def connected(self, name, before):
        unit = "rethink-" + name + "-capture.service"
        require(self.properties(unit)["ActiveState"] == "active", "Recorder inactive")
        path = self.state / "captures" / name / "passive.jsonl"
        return appended_marker(path, before, "connected")

    def write_release(self, request):
        private_json(self.app / ".release.json", {"revision": request["revision"], "source_sha256": request["source_sha256"], "dist_sha256": request["dist_sha256"]})
        path = self.app / ".source-sha256"
        temporary = self.app / ".source-sha256.new"
        with temporary.open("x") as stream:
            stream.write(request["source_sha256"] + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        sync_dir(self.app)


def compare_baseline(current, baseline, request):
    require(current["revision"] == request["expected_current_revision"], "Installed revision changed")
    for key in ("schema", "revision", "release", "source_marker", "files", "units", "nft_sha256", "dist_files_sha256"):
        require(current[key] == baseline[key], "Inspected baseline changed")
    require(current["runtime"]["listeners"] == baseline["runtime"]["listeners"], "App listener baseline changed")
    for name in NAMES:
        require(current["units"]["rethink-" + name + "-capture.service"]["active"] == request["enabled_recorders"][name],
                "Recorder switch/current state mismatch; switch separately before inspection")
        previous, now = baseline["captures"][name], current["captures"][name]
        if previous is not None:
            require(now is not None and all(now[key] == previous[key] for key in ("inode", "device"))
                    and now["size"] >= previous["size"], "Capture changed since inspection")
        elif request["enabled_recorders"][name]:
            raise RuntimeError("Enabled recorder requires existing capture")


def wait_for(check, attempts=30):
    for attempt in range(attempts):
        try:
            if check() is not False:
                return
        except (RuntimeError, OSError, ValueError):
            if attempt == attempts - 1:
                raise
        if attempt < attempts - 1:
            time.sleep(1)
    raise RuntimeError("Post-start verification timed out")


def deploy(target, request, artifacts, baseline, journal):
    """Caller holds exclusive lock. Every failure after intent blocks future attempts."""
    validate_request(request)
    require(not journal.exists(), "Unresolved transaction journal; manual recovery required")
    manifest = validate_artifacts(artifacts, request)
    current = target.snapshot()
    compare_baseline(current, baseline, request)
    target.health()
    work = target.app / (".native-deploy-" + uuid.uuid4().hex)
    work.mkdir(mode=0o700)
    # Snapshot all artifacts privately to prevent validation/extraction TOCTOU.
    for name in ("manifest.json", "source.tar.gz", "dist.tar.gz"):
        shutil.copyfile(regular(Path(artifacts) / name), work / name)
    extract_dist(work, work, request)
    require((work / "dist").stat().st_dev == (target.app / "dist").stat().st_dev, "Cross-filesystem dist switch")
    require(shutil.disk_usage(work).free >= target.space_needed(), "Insufficient full state backup space")
    target.invariants(baseline)
    intent = {"schema": 1, "phase": "prepared", "request": request, "work": str(work), "manual_recovery_required": True}

    def phase(value):
        intent["phase"] = value
        private_json(journal, intent)

    phase("stop-recorders-intent")
    try:
        units = ["rethink-" + name + "-capture.service" for name in NAMES]
        target.stop(units)
        phase("stop-app-intent")
        target.stop([APP_UNIT])
        # Use stopped offsets: old recorder shutdown may append final lines.
        captures = {}
        for name in NAMES:
            path = target.state / "captures" / name / "passive.jsonl"
            if current["captures"][name] is not None:
                info = regular(path).stat()
                previous = current["captures"][name]
                require((info.st_ino, info.st_dev) == (previous["inode"], previous["device"])
                        and info.st_size >= previous["size"], "Capture changed during stop")
                if request["enabled_recorders"][name]:
                    require(appended_marker(path, previous, "stopped"), "Recorder did not append a fresh stopped marker")
                captures[name] = {"inode": info.st_ino, "device": info.st_dev, "size": info.st_size}
        phase("backup-intent")
        target.backup(work, baseline)
        target.invariants(baseline)
        phase("dist-exchange-intent")
        exchange(work / "dist", target.app / "dist")
        phase("dist-exchanged")
        target.write_release(request)
        # Persist BEFORE start: the candidate can consume events even on start failure.
        phase("candidate-start-intent")
        target.previous_process = (current["runtime"]["pid"], current["runtime"]["start_ticks"])
        target.candidate_files = manifest["dist_files_sha256"]
        target.start(APP_UNIT)
        wait_for(target.health)
        phase("recorders-start-intent")
        for name in NAMES:
            if request["enabled_recorders"][name]:
                target.start("rethink-" + name + "-capture.service")
        for name in NAMES:
            if request["enabled_recorders"][name]:
                wait_for(lambda name=name: target.connected(name, captures[name]))
        target.health()
        target.invariants(baseline)
        for name in NAMES:
            path = target.state / "captures" / name / "passive.jsonl"
            if name in captures:
                info = regular(path).stat()
                before = captures[name]
                require((info.st_ino, info.st_dev) == (before["inode"], before["device"])
                        and info.st_size >= before["size"], "Capture changed after candidate start")
            else:
                require(not path.exists(), "Previously absent disabled capture created")
            if not request["enabled_recorders"][name]:
                require(target.properties("rethink-" + name + "-capture.service")["ActiveState"] == "inactive", "Disabled recorder started")
        intent["manual_recovery_required"] = False
        phase("complete")
    except BaseException:
        # No restart, rollback, state restore, or recorder replay in the failure handler.
        intent["failed_phase"] = intent["phase"]
        intent["manual_recovery_required"] = True
        phase("manual-recovery-required")
        raise
    return intent


def private_directory(path):
    path = Path(path)
    if not path.exists():
        path.mkdir(mode=0o700)
    info = path.stat()
    require(path.resolve() == path.absolute() and info.st_uid == os.geteuid()
            and stat.S_IMODE(info.st_mode) == 0o700, "Private root-owned directory required")
    return path


def serve(target, incoming):
    """One bounded stdin request for a dedicated SSH forced command; no caller paths."""
    require(isinstance(incoming, dict), "Invalid operation envelope")
    private_directory(target.journals)
    lock_fd = os.open(target.journals / "lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(lock_fd, "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        journal = target.journals / "active.json"
        if journal.exists():
            previous = strict_json(regular(journal).read_text())
            require(previous.get("phase") == "complete" and previous.get("manual_recovery_required") is False,
                    "Unresolved transaction; operator recovery required")
        if incoming.get("op") == "inspect":
            require(set(incoming) == {"op"}, "Unexpected inspect fields")
            baseline = target.snapshot()
            parent = private_directory(target.journals / "baselines")
            identity = None
            # Reuse the approved baseline while captures only append. The public
            # inspect response remains stable without exposing capture contents.
            switches = {name: baseline["units"]["rethink-" + name + "-capture.service"]["active"] for name in NAMES}
            for existing in sorted(parent.glob("*.json")):
                candidate = strict_json(regular(existing).read_text())
                try:
                    compare_baseline(baseline, candidate, {"expected_current_revision": baseline["revision"],
                                                         "enabled_recorders": switches})
                except RuntimeError:
                    continue
                require(digest(existing) == existing.stem, "Stored baseline identity changed")
                identity = existing.stem
                break
            if identity is None:
                temporary = parent / (uuid.uuid4().hex + ".json")
                private_json(temporary, baseline)
                identity = digest(temporary)
                temporary.rename(parent / (identity + ".json"))
                sync_dir(parent)
            return {"schema": 1, "revision": baseline["revision"], "package_sha256": PACKAGE_SHA,
                    "lock_sha256": LOCK_SHA, "baseline_sha256": identity,
                    "enabled_recorders": {name: baseline["units"]["rethink-" + name + "-capture.service"]["active"] for name in NAMES}}
        require(incoming.get("op") == "deploy" and set(incoming) == {"op", "request", "artifacts"}, "Invalid deploy envelope")
        request = incoming["request"]
        validate_request(request)
        path = target.journals / "baselines" / (request["baseline_sha256"] + ".json")
        require(digest(regular(path)) == request["baseline_sha256"], "Unknown/changed approved baseline")
        baseline = strict_json(path.read_text())
        artifacts = incoming["artifacts"]
        require(isinstance(artifacts, dict) and set(artifacts) == {"source.tar.gz", "dist.tar.gz", "manifest.json"}, "Exact offline artifact set required")
        inbox = private_directory(target.journals / "inbox") / uuid.uuid4().hex
        inbox.mkdir(mode=0o700)
        for name, value in artifacts.items():
            require(isinstance(value, str), "Artifacts must be base64 text")
            data = base64.b64decode(value, validate=True)
            require(len(data) <= 32 * 1024 ** 2, "Compressed artifact too large")
            (inbox / name).write_bytes(data)
        if journal.exists():
            journal.rename(target.journals / ("complete-" + uuid.uuid4().hex + ".json"))
            sync_dir(target.journals)
        result = deploy(target, request, inbox, baseline, journal)
        return {"schema": 1, "status": "complete", "revision": result["request"]["revision"],
                "source_sha256": request["source_sha256"], "dist_sha256": request["dist_sha256"],
                "manifest_sha256": request["manifest_sha256"], "enabled_recorders": request["enabled_recorders"]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("serve", help="one bounded JSON request on stdin, fixed target paths")
    inspect = commands.add_parser("inspect", help="read-only target baseline, private output")
    inspect.add_argument("--output", type=Path, required=True)
    apply = commands.add_parser("deploy", help="explicit reviewed offline transaction, never automatic rollback")
    apply.add_argument("--request", type=Path, required=True)
    apply.add_argument("--baseline", type=Path, required=True)
    apply.add_argument("--artifacts", type=Path, required=True)
    args = parser.parse_args(argv)
    os.umask(0o077)
    require(os.geteuid() == 0, "Target inspection/deployment requires root")
    target = NativeTarget()
    if args.command == "serve":
        payload = sys.stdin.buffer.read(64 * 1024 ** 2 + 1)
        require(len(payload) <= 64 * 1024 ** 2, "Request too large")
        result = serve(target, strict_json(payload))
        print(json.dumps(result, sort_keys=True))
        return
    if args.command == "inspect":
        require(not args.output.exists(), "Baseline output already exists")
        private_directory(args.output.parent)
        private_json(args.output, target.snapshot())
        print("Baseline written privately; this is not deployment approval.")
        return
    request = strict_json(regular(args.request).read_text())
    validate_request(request)
    require(digest(regular(args.baseline)) == request["baseline_sha256"], "Baseline identity mismatch")
    baseline = strict_json(args.baseline.read_text())
    private_directory(target.journals)
    lock_fd = os.open(target.journals / "lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(lock_fd, "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        journal = target.journals / "active.json"
        if journal.exists():
            previous = strict_json(regular(journal).read_text())
            require(previous.get("phase") == "complete" and previous.get("manual_recovery_required") is False,
                    "Unresolved transaction; operator recovery required")
            journal.rename(target.journals / ("complete-" + uuid.uuid4().hex + ".json"))
            sync_dir(target.journals)
        deploy(target, request, args.artifacts, baseline, journal)
    print("Native deployment verified; old dist and full private state backup retained.")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Avoid leaking UUIDs, config, command stderr, or CA paths.
        print(json.dumps({"schema": 1, "status": "error", "message": "Native target failed; inspect private journal before retry."}))
        raise SystemExit(1)
