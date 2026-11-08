#!/usr/bin/env python3
"""Build trusted main locally; optionally deploy via CT117's dedicated forced command.

Default is preparation only. This command does not install the target worker or arm CI.
"""
import argparse
import base64
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess

TARGET = "deploy-rethink@10.0.40.5"
MAX_REQUEST = 16 * 1024 * 1024


def preparer():
    path = Path(__file__).with_name("prepare-pr5-native.py")
    spec = importlib.util.spec_from_file_location("rethink_native_preparer", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def digest(data):
    return hashlib.sha256(data).hexdigest()


def load_json(data):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result
    return json.loads(data, object_pairs_hook=pairs)


def artifacts(output, package_hash, lock_hash):
    """Recheck evidence and immutable bytes, not just a success-marker filename."""
    helper = preparer()
    raw = (output / "manifest.json").read_bytes()
    manifest = load_json(raw)
    if (manifest["schema"] != 1 or manifest["repo"] != helper.REPO
            or manifest["package_sha256"] != package_hash
            or manifest["lock_sha256"] != lock_hash
            or manifest["preparer_sha256"] != digest(Path(helper.__file__).read_bytes())):
        raise ValueError("unexpected build manifest identity")
    helper.require_hex(manifest["commit"], 40)
    expected = {"source.tar.gz", "dist.tar.gz", "build.log", "workflow.json", "ci-runs.json", "main.json"}
    if "main-ancestry.json" in manifest["artifacts_sha256"]:
        expected.add("main-ancestry.json")
    if set(manifest["artifacts_sha256"]) != expected:
        raise ValueError("incomplete artifact evidence")
    for name, wanted in manifest["artifacts_sha256"].items():
        helper.require_hex(wanted, 64)
        if digest((output / name).read_bytes()) != wanted:
            raise ValueError("artifact checksum mismatch: " + name)
    captured_main = load_json((output / "main.json").read_bytes())["sha"]
    helper.require_hex(captured_main, 40)
    if "main-ancestry.json" in expected:
        helper.verify_main_ancestor(load_json((output / "main-ancestry.json").read_bytes()),
                                    manifest["commit"], captured_main)
    elif captured_main != manifest["commit"]:
        raise ValueError("captured main differs from manifest without ancestry evidence")
    workflow = load_json((output / "workflow.json").read_bytes())
    runs = load_json((output / "ci-runs.json").read_bytes())
    matches = [run for run in runs["workflow_runs"] if run.get("id") == manifest["ci_run_id"]]
    if len(matches) != 1 or manifest["workflow_id"] != workflow["id"]:
        raise ValueError("CI identity differs from manifest")
    helper.verify_ci(matches[0], workflow, manifest["commit"])
    return manifest, raw, (output / "dist.tar.gz").read_bytes()


def same_inspect(current, approved):
    # Baseline hashes may change as append-only captures grow. The target uses
    # the ORIGINAL approved baseline under lock and verifies monotonic offsets.
    return ({key: value for key, value in current.items() if key != "baseline_sha256"}
            == {key: value for key, value in approved.items() if key != "baseline_sha256"})


def deploy_request(manifest, manifest_raw, dist, baseline, source):
    helper = preparer()
    helper.require_hex(baseline["revision"], 40)
    helper.require_hex(baseline["baseline_sha256"], 64)
    if (baseline.get("schema") != 1 or baseline.get("package_sha256") != manifest["package_sha256"]
            or baseline.get("lock_sha256") != manifest["lock_sha256"]):
        raise ValueError("approved baseline dependencies differ from candidate")
    switches = baseline["enabled_recorders"]
    if set(switches) != {"washer", "dryer", "sidekick"} or any(type(v) is not bool for v in switches.values()):
        raise ValueError("invalid approved recorder switches")
    if baseline["revision"] == manifest["commit"]:
        raise ValueError("candidate already current; replay/no-op prohibited")
    request = {"schema": 1, "expected_current_revision": baseline["revision"],
               "revision": manifest["commit"], "package_sha256": manifest["package_sha256"],
               "lock_sha256": manifest["lock_sha256"], "baseline_sha256": baseline["baseline_sha256"],
               "enabled_recorders": switches, "source_sha256": digest(source),
               "dist_sha256": digest(dist), "manifest_sha256": digest(manifest_raw)}
    return {"op": "deploy", "request": request, "artifacts": {
        name: base64.b64encode(data).decode("ascii") for name, data in
        (("source.tar.gz", source), ("dist.tar.gz", dist), ("manifest.json", manifest_raw))}}


def verify_result(response, request):
    expected = {"schema": 1, "status": "complete", "revision": request["revision"],
                "enabled_recorders": request["enabled_recorders"],
                **{key: request[key] for key in ("source_sha256", "dist_sha256", "manifest_sha256")}}
    if response != expected:
        raise ValueError("target did not attest exact completed release identity; inspect journal")


def ssh_command(identity, known_hosts):
    for path in (identity, known_hosts):
        if not path.is_file():
            raise ValueError("explicit identity and known_hosts files must exist")
    return ["ssh", "-F", "/dev/null", "-T", "-o", "BatchMode=yes",
            "-o", "IdentitiesOnly=yes", "-o", "IdentityAgent=none",
            "-o", "StrictHostKeyChecking=yes", "-o", "UserKnownHostsFile=" + str(known_hosts.resolve()),
            "-o", "GlobalKnownHostsFile=/dev/null", "-o", "ClearAllForwardings=yes",
            "-i", str(identity.resolve()), TARGET]


def transport(command, request):
    raw = (json.dumps(request, sort_keys=True, separators=(",", ":")) + "\n").encode()
    if len(raw) > MAX_REQUEST:
        raise ValueError("release exceeds bounded target request size")
    result = subprocess.run(command, input=raw, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            check=True, timeout=600)
    response = load_json(result.stdout)
    if not isinstance(response, dict):
        raise ValueError("target returned non-object response")
    return response


def journal(path, record):
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, sort_keys=True) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def execute(args):
    helper = preparer()
    helper.require_hex(args.package_sha256, 64)
    helper.require_hex(args.lock_sha256, 64)
    output = Path(args.output).resolve()
    command = None
    baseline = None
    if args.deploy_local_target:
        if not all((args.identity_file, args.known_hosts, args.expected_current)):
            raise ValueError("deployment requires explicit dedicated identity, known_hosts and approved baseline")
        command = ssh_command(Path(args.identity_file), Path(args.known_hosts))
        baseline = load_json(Path(args.expected_current).read_bytes())
        inspect = transport(command, {"op": "inspect"})
        if not same_inspect(inspect, baseline):
            raise ValueError("target differs from operator-approved baseline")
    elif any((args.identity_file, args.known_hosts, args.expected_current)):
        raise ValueError("SSH options require --deploy-local-target")
    # The preparer creates a NEW workspace. Existing output cannot be resumed or replayed.
    helper.prepare(args)
    log = output / "release-journal.jsonl"
    try:
        manifest, manifest_raw, dist = artifacts(output, args.package_sha256, args.lock_sha256)
        journal(log, {"phase": "prepared", "commit": manifest["commit"],
                      "manifest_sha256": digest(manifest_raw)})
        if not command:
            return {"status": "prepared-only", "commit": manifest["commit"], "output": str(output)}
        if not same_inspect(transport(command, {"op": "inspect"}), baseline):
            raise ValueError("target baseline changed during local build")
        request = deploy_request(manifest, manifest_raw, dist, baseline, (output / "source.tar.gz").read_bytes())
        journal(log, {"phase": "sending", "commit": manifest["commit"],
                      "request_sha256": digest(json.dumps(request, sort_keys=True).encode())})
        response = transport(command, request)
        verify_result(response, request["request"])
        journal(log, {"phase": "committed", "result": response})
        return response
    except Exception:
        journal(log, {"phase": "failed-or-unknown", "instruction": "inspect target journal; never blindly retry"})
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package-sha256", required=True)
    parser.add_argument("--lock-sha256", required=True)
    parser.add_argument("--output", required=True, help="new private local build directory")
    parser.add_argument("--revision", help="optional full trusted push/main revision; preparer requires main ancestry")
    parser.add_argument("--deploy-local-target", action="store_true")
    parser.add_argument("--identity-file")
    parser.add_argument("--known-hosts")
    parser.add_argument("--expected-current", help="operator-approved inspect response JSON file")
    args = parser.parse_args()
    os.umask(0o077)
    print(json.dumps(execute(args), sort_keys=True))


if __name__ == "__main__":
    main()
