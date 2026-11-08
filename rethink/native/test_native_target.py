"""Offline transaction tests. No host systemctl, nft, network, credentials or target."""
import base64
import copy
import hashlib
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest import mock

import native_target as native


def sha(data):
    return hashlib.sha256(data).hexdigest()


def archive(path, contents):
    with tarfile.open(path, "w:gz") as output:
        for name, payload in contents.items():
            info = tarfile.TarInfo(name)
            if isinstance(payload, tarfile.TarInfo):
                info = payload
                output.addfile(info)
            else:
                info.size = len(payload)
                info.mode = 0o644
                output.addfile(info, io.BytesIO(payload))


class FakeTarget(native.NativeTarget):
    def __init__(self, root):
        self.app = root / "app"
        self.state = root / "state"
        self.config = root / "config.json"
        self.journals = root / "journals"
        self.app.mkdir()
        self.state.mkdir()
        self.config.write_text("private configuration")
        self.journals.mkdir(mode=0o700)
        (self.app / "dist").mkdir()
        (self.app / "dist/old.js").write_text("old code")
        self.events = []
        self.fail = None
        self.active = {native.APP_UNIT: True}
        self.base = {"schema": 1, "revision": "a" * 40, "release": {"revision": "a" * 40},
                     "source_marker": "old source", "files": {str(self.config): native.file_identity(self.config)},
                     "units": {native.APP_UNIT: {"definition_sha256": "app", "active": True, "enabled": "enabled"}},
                     "nft_sha256": "firewall", "captures": {}, "dist_files_sha256": {"old.js": sha(b"old code")},
                     "runtime": {"pid": "123", "start_ticks": "456", "listeners": ["expected"]}}
        for name in native.NAMES:
            unit = "rethink-" + name + "-capture.service"
            self.active[unit] = True
            self.base["units"][unit] = {"definition_sha256": name, "active": True, "enabled": "enabled"}
            path = self.state / "captures" / name / "passive.jsonl"
            path.parent.mkdir(parents=True)
            path.write_bytes(b'{"historical":true}\n')
        (self.state / "ca.key").write_text("private key fixture")
        (self.state / "laundry-state.json").write_text('{"preserve":true}')
        self.base["captures"] = self.capture_stats()

    def capture_stats(self):
        result = {}
        for name in native.NAMES:
            info = (self.state / "captures" / name / "passive.jsonl").stat()
            result[name] = {"inode": info.st_ino, "device": info.st_dev, "size": info.st_size}
        return result

    def snapshot(self):
        value = copy.deepcopy(self.base)
        value["captures"] = self.capture_stats()
        return value

    def invariants(self, baseline):
        self.events.append("invariants")
        for path, expected in baseline["files"].items():
            native.require(native.file_identity(path) == expected, "invariant changed")

    def health(self):
        self.events.append("health")
        if self.fail == "health" and "start:" + native.APP_UNIT in self.events:
            raise RuntimeError("candidate unhealthy")
        return True

    def properties(self, unit):
        return {"ActiveState": "active" if self.active[unit] else "inactive", "MainPID": "1" if self.active[unit] else "0"}

    def stop(self, units):
        for unit in units:
            self.events.append("stop:" + unit)
            if unit != native.APP_UNIT and self.active[unit]:
                name = unit.removeprefix("rethink-").removesuffix("-capture.service")
                with (self.state / "captures" / name / "passive.jsonl").open("ab") as stream:
                    stream.write(b'{"k":"marker","phase":"stopped"}\n')
            self.active[unit] = False
        if self.fail == "stop":
            raise RuntimeError("failed stop")

    def backup(self, work, baseline):
        self.events.append("backup")
        native.require(not any(self.active.values()), "backup while running")
        if self.fail == "backup":
            raise RuntimeError("failed backup")
        # The real tar backup implementation is tested separately.
        import shutil
        shutil.copytree(self.state, work / "backup-state")

    def start(self, unit):
        self.events.append("start:" + unit)
        if self.fail == "start":
            raise RuntimeError("start may already have consumed an event")
        self.active[unit] = True
        if unit != native.APP_UNIT:
            name = unit.removeprefix("rethink-").removesuffix("-capture.service")
            with (self.state / "captures" / name / "passive.jsonl").open("ab") as stream:
                if self.fail != "connected":
                    stream.write(b'{"k":"marker","phase":"connected"}\n')

    def connected(self, name, before):
        self.events.append("connected:" + name)
        return super().connected(name, before)


class NativeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.artifacts = self.root / "artifacts"
        self.artifacts.mkdir()
        self.package = b'{"name":"test","version":"1.0.0"}\n'
        self.lock = b'{"lockfileVersion":3,"packages":{}}\n'
        self.addCleanup(mock.patch.stopall)
        mock.patch.object(native, "PACKAGE_SHA", sha(self.package)).start()
        mock.patch.object(native, "LOCK_SHA", sha(self.lock)).start()
        mock.patch.object(native.time, "sleep", lambda seconds: None).start()
        self.revision = "b" * 40
        self.source = {"source/package.json": self.package, "source/package-lock.json": self.lock,
                       "source/rethink-cloud.ts": b"reviewed source"}
        self.dist = {"dist/rethink-cloud.js": b"candidate code", "dist/tools/rethink-capture.js": b"recorder",
                     "dist/util/version.js": ("export const revision = '" + self.revision[:7] + "'\n").encode()}
        self.request = {"schema": 1, "expected_current_revision": "a" * 40, "revision": self.revision,
                        "package_sha256": sha(self.package), "lock_sha256": sha(self.lock),
                        "baseline_sha256": "e" * 64, "enabled_recorders": dict.fromkeys(native.NAMES, True)}
        self.pack()
        self.target = FakeTarget(self.root)
        self.baseline = self.target.snapshot()
        self.journal = self.target.journals / "active.json"

    def pack(self):
        archive(self.artifacts / "source.tar.gz", self.source)
        archive(self.artifacts / "dist.tar.gz", self.dist)
        self.request["source_sha256"] = native.digest(self.artifacts / "source.tar.gz")
        self.request["dist_sha256"] = native.digest(self.artifacts / "dist.tar.gz")
        self.manifest = {"schema": 1, "commit": self.revision, "package_sha256": sha(self.package),
                         "lock_sha256": sha(self.lock), "artifacts_sha256": {
                             "source.tar.gz": self.request["source_sha256"], "dist.tar.gz": self.request["dist_sha256"]},
                         "dist_files_sha256": {name.removeprefix("dist/"): sha(data)
                                               for name, data in self.dist.items() if isinstance(data, bytes)}}
        (self.artifacts / "manifest.json").write_text(json.dumps(self.manifest))
        self.request["manifest_sha256"] = native.digest(self.artifacts / "manifest.json")

    def deploy(self):
        return native.deploy(self.target, self.request, self.artifacts, self.baseline, self.journal)

    def test_success_retains_old_dist_and_entire_stopped_state(self):
        before = {name: (self.target.state / "captures" / name / "passive.jsonl").read_bytes() for name in native.NAMES}
        result = self.deploy()
        self.assertEqual(result["phase"], "complete")
        self.assertFalse(result["manual_recovery_required"])
        work = Path(result["work"])
        self.assertEqual((work / "dist/old.js").read_text(), "old code")
        self.assertEqual((work / "backup-state/ca.key").read_text(), "private key fixture")
        self.assertEqual((work / "backup-state/laundry-state.json").read_text(), '{"preserve":true}')
        for name in native.NAMES:
            backed_up = (work / "backup-state/captures" / name / "passive.jsonl").read_bytes()
            self.assertTrue(backed_up.startswith(before[name]))
            self.assertIn(b'"phase":"stopped"', backed_up)
            self.assertTrue((self.target.state / "captures" / name / "passive.jsonl").read_bytes().startswith(before[name]))
        events = self.target.events
        self.assertLess(events.index("stop:rethink-sidekick-capture.service"), events.index("stop:rethink.service"))
        self.assertLess(events.index("backup"), events.index("start:rethink.service"))
        self.assertLess(events.index("start:rethink.service"), events.index("start:rethink-washer-capture.service"))
        self.assertEqual((self.target.app / "dist/rethink-cloud.js").read_bytes(), self.dist["dist/rethink-cloud.js"])

    def test_backup_failure_leaves_old_code_stopped_and_blocks_retry(self):
        self.target.fail = "backup"
        with self.assertRaises(RuntimeError):
            self.deploy()
        self.assertTrue((self.target.app / "dist/old.js").exists())
        self.assertFalse(any(event.startswith("start:") for event in self.target.events))
        intent = json.loads(self.journal.read_text())
        self.assertEqual(intent["phase"], "manual-recovery-required")
        self.assertTrue(intent["manual_recovery_required"])
        with self.assertRaisesRegex(RuntimeError, "Unresolved"):
            self.deploy()

    def test_start_failure_never_rolls_back_or_restores_state(self):
        self.target.fail = "start"
        with self.assertRaises(RuntimeError):
            self.deploy()
        self.assertTrue((self.target.app / "dist/rethink-cloud.js").exists())
        intent = json.loads(self.journal.read_text())
        self.assertEqual(intent["failed_phase"], "candidate-start-intent")
        self.assertEqual(self.target.events.count("start:rethink.service"), 1)
        self.assertEqual((self.target.state / "laundry-state.json").read_text(), '{"preserve":true}')

    def test_missing_fresh_connected_marker_blocks_success_without_rollback(self):
        self.target.fail = "connected"
        with self.assertRaisesRegex(RuntimeError, "timed out"):
            self.deploy()
        self.assertTrue((self.target.app / "dist/rethink-cloud.js").exists())
        self.assertEqual(json.loads(self.journal.read_text())["failed_phase"], "recorders-start-intent")

    def test_disabled_recorder_is_not_started(self):
        name = "dryer"
        unit = "rethink-dryer-capture.service"
        self.target.base["units"][unit]["active"] = False
        self.target.active[unit] = False
        self.request["enabled_recorders"][name] = False
        self.baseline = self.target.snapshot()
        self.deploy()
        self.assertNotIn("start:" + unit, self.target.events)

    def test_bad_artifact_and_stale_revision_fail_before_service_changes(self):
        (self.artifacts / "dist.tar.gz").write_bytes(b"tampered")
        with self.assertRaises(RuntimeError):
            self.deploy()
        self.assertEqual(self.target.events, [])
        self.assertFalse(self.journal.exists())
        self.pack()
        self.request["expected_current_revision"] = "c" * 40
        with self.assertRaises(RuntimeError):
            self.deploy()
        self.assertEqual(self.target.events, [])

    def test_switch_mismatch_fails_before_stop(self):
        self.request["enabled_recorders"]["washer"] = False
        with self.assertRaisesRegex(RuntimeError, "switch/current"):
            self.deploy()
        self.assertEqual(self.target.events, [])

    def test_insufficient_backup_space_fails_before_stop(self):
        with mock.patch.object(native.shutil, "disk_usage", return_value=type("Usage", (), {"free": 0})()):
            with self.assertRaisesRegex(RuntimeError, "backup space"):
                self.deploy()
        self.assertFalse(self.journal.exists())
        self.assertFalse(any(event.startswith("stop:") for event in self.target.events))

    def test_symlink_and_traversal_archive_rejected(self):
        for name in ("dist/../escape", "/absolute", "dist//ambiguous", "dist/./ambiguous", "dist/\\escape"):
            with self.subTest(name=name):
                self.dist[name] = b"bad"
                self.pack()
                with self.assertRaises(RuntimeError):
                    native.validate_artifacts(self.artifacts, self.request)
                del self.dist[name]
        info = tarfile.TarInfo("dist/link")
        info.type = tarfile.SYMTYPE
        info.linkname = "/etc/passwd"
        self.dist["dist/link"] = info
        self.pack()
        with self.assertRaises(RuntimeError):
            native.validate_artifacts(self.artifacts, self.request)

    def test_wrong_version_and_file_inventory_rejected(self):
        self.dist["dist/util/version.js"] = b"export const revision = 'old'\n"
        self.pack()
        with self.assertRaisesRegex(RuntimeError, "baked"):
            native.validate_artifacts(self.artifacts, self.request)
        self.manifest["dist_files_sha256"].pop("tools/rethink-capture.js")
        (self.artifacts / "manifest.json").write_text(json.dumps(self.manifest))
        self.request["manifest_sha256"] = native.digest(self.artifacts / "manifest.json")
        with self.assertRaisesRegex(RuntimeError, "inventory"):
            native.validate_artifacts(self.artifacts, self.request)

    def test_changed_dependency_manifests_rejected(self):
        self.source["source/package.json"] = b"changed"
        self.pack()
        with self.assertRaisesRegex(RuntimeError, "dependencies"):
            native.validate_artifacts(self.artifacts, self.request)

    def test_request_requires_all_exact_booleans(self):
        for value in ({"washer": True}, dict.fromkeys(native.NAMES, 1)):
            self.request["enabled_recorders"] = value
            with self.assertRaises(RuntimeError):
                native.validate_request(self.request)

    def test_real_atomic_exchange_retains_both_directories(self):
        left, right = self.root / "left", self.root / "right"
        left.mkdir()
        right.mkdir()
        (left / "candidate").touch()
        (right / "old").touch()
        native.exchange(left, right)
        self.assertTrue((right / "candidate").exists())
        self.assertTrue((left / "old").exists())

    def test_capture_replacement_is_rejected(self):
        before = self.target.capture_stats()["washer"]
        path = self.target.state / "captures/washer/passive.jsonl"
        path.rename(path.with_suffix(".previous"))
        path.write_bytes(b'{"k":"marker","phase":"connected"}\n')
        with self.assertRaisesRegex(RuntimeError, "replaced"):
            self.target.connected("washer", before)

    def test_state_backup_refuses_symlink_and_includes_captures(self):
        work = self.root / "backup-work"
        work.mkdir()
        # Only tar is delegated to the real backend. No service/network calls.
        with mock.patch.object(self.target, "run", native.NativeTarget.run.__get__(self.target)):
            native.NativeTarget.backup(self.target, work, self.baseline)
        with tarfile.open(work / "backup/state.tar") as saved:
            self.assertEqual(saved.extractfile("state/ca.key").read(), b"private key fixture")
            self.assertIn("state/captures/sidekick/passive.jsonl", saved.getnames())
        (self.target.state / "linked").symlink_to(self.target.config)
        with self.assertRaisesRegex(RuntimeError, "backup cannot"):
            self.target.space_needed()

    def test_serve_inspect_stays_stable_on_capture_growth(self):
        first = native.serve(self.target, {"op": "inspect"})
        with (self.target.state / "captures/washer/passive.jsonl").open("ab") as stream:
            stream.write(b'{"new":true}\n')
        second = native.serve(self.target, {"op": "inspect"})
        self.assertEqual(first, second)
        self.assertNotIn("captures", first)

    def test_serve_rejects_paths_and_blocks_inspect_with_pending_intent(self):
        with self.assertRaises(RuntimeError):
            native.serve(self.target, {"op": "inspect", "output": "/etc/passwd"})
        native.private_json(self.journal, {"phase": "candidate-start-intent", "manual_recovery_required": True})
        with self.assertRaisesRegex(RuntimeError, "Unresolved"):
            native.serve(self.target, {"op": "inspect"})

    def test_serve_offline_envelope_success(self):
        inspected = native.serve(self.target, {"op": "inspect"})
        self.request["baseline_sha256"] = inspected["baseline_sha256"]
        artifacts = {name: base64.b64encode((self.artifacts / name).read_bytes()).decode()
                     for name in ("source.tar.gz", "dist.tar.gz", "manifest.json")}
        result = native.serve(self.target, {"op": "deploy", "request": self.request, "artifacts": artifacts})
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["dist_sha256"], self.request["dist_sha256"])
        self.assertEqual(result["manifest_sha256"], self.request["manifest_sha256"])
        self.assertEqual(result["source_sha256"], self.request["source_sha256"])
        self.assertEqual(result["enabled_recorders"], self.request["enabled_recorders"])

    def test_strict_envelope_rejects_duplicate_keys_and_nonfinite(self):
        for payload in ('{"op":"inspect","op":"deploy"}', '{"value":NaN}'):
            with self.assertRaises(RuntimeError):
                native.strict_json(payload)

    def test_stop_refuses_timeout_and_unclean_recorder_exit(self):
        good = {"ActiveState": "inactive", "MainPID": "0", "Result": "success", "ExecMainCode": "1", "ExecMainStatus": "0"}
        with mock.patch.object(self.target, "run", return_value=""), mock.patch.object(self.target, "properties", return_value=good):
            native.NativeTarget.stop(self.target, ["rethink-washer-capture.service"])
        for key, value in (("Result", "timeout"), ("ExecMainCode", "2"), ("ExecMainStatus", "9")):
            bad = dict(good, **{key: value})
            with mock.patch.object(self.target, "run", return_value=""), mock.patch.object(self.target, "properties", return_value=bad):
                with self.assertRaises(RuntimeError):
                    native.NativeTarget.stop(self.target, ["rethink-washer-capture.service"])

    def test_effective_properties_normalize_only_empty_execstop(self):
        def output(*argv):
            self.assertIn("--all", argv)
            keys = [arg.removeprefix("--property=") for arg in argv if arg.startswith("--property=")]
            values = dict.fromkeys(keys, "")
            values.update(FragmentPath="/etc/systemd/system/rethink.service", Transient="no",
                          User="rethink", Group="rethink", UMask="0077")
            return "\n".join(key + "=" + value for key, value in values.items() if key != "ExecStop")
        with mock.patch.object(self.target, "run", side_effect=output):
            values = native.NativeTarget.properties(self.target, native.APP_UNIT)
        self.assertEqual(values["ExecStop"], "")
        with mock.patch.object(self.target, "run", return_value="ExecStop="):
            with self.assertRaisesRegex(RuntimeError, "Incomplete"):
                native.NativeTarget.properties(self.target, native.APP_UNIT)

    def make_process(self):
        proc = self.root / "proc"
        process = proc / "123"
        process.mkdir(parents=True)
        (process / "cmdline").write_bytes(b"\0".join(part.encode() for part in ["/usr/bin/node", str(self.target.app / "dist/rethink-cloud.js"), str(self.target.config)]) + b"\0")
        (process / "exe").symlink_to(Path("/usr/bin/node").resolve())
        (process / "cwd").symlink_to(self.target.state)
        (process / "status").write_text("Uid:\t997\t997\t997\t997\nGid:\t988\t988\t988\t988\n")
        (process / "stat").write_text("123 (node command) " + " ".join(["S"] + ["0"] * 18 + ["456"]))
        sockets = "\n".join('LISTEN 0 128 ' + endpoint + ' 0.0.0.0:* users:(("node",pid=123,fd=5))'
                            for endpoint in ("10.0.40.5:443", "10.0.40.5:8883", "127.0.0.1:44401"))
        return proc, sockets

    def test_runtime_identity_checks_process_and_exact_listeners(self):
        proc, sockets = self.make_process()
        result = native.runtime_identity(self.target.app, self.target.state, self.target.config, "123", sockets, proc)
        self.assertEqual(result["start_ticks"], "456")
        with self.assertRaisesRegex(RuntimeError, "listeners"):
            native.runtime_identity(self.target.app, self.target.state, self.target.config, "123", sockets.replace("10.0.40.5:8883", "0.0.0.0:8883"), proc)
        (proc / "123/cmdline").write_bytes(b"unexpected\0")
        with self.assertRaisesRegex(RuntimeError, "command mismatch"):
            native.runtime_identity(self.target.app, self.target.state, self.target.config, "123", sockets, proc)

    def test_health_rejects_old_process_and_changed_candidate_tree(self):
        self.target.previous_process = ("123", "456")
        self.target.candidate_files = native.tree_inventory(self.target.app / "dist")
        with mock.patch.object(self.target, "runtime", return_value={"pid": "123", "start_ticks": "456"}):
            with self.assertRaisesRegex(RuntimeError, "replace old process"):
                native.NativeTarget.health(self.target)
        (self.target.app / "dist/old.js").write_text("changed")
        with mock.patch.object(self.target, "runtime", return_value={"pid": "124", "start_ticks": "999"}):
            with self.assertRaisesRegex(RuntimeError, "dist identity"):
                native.NativeTarget.health(self.target)

    def test_full_dist_baseline_detects_changed_file_with_same_version(self):
        current = self.target.snapshot()
        current["dist_files_sha256"]["old.js"] = sha(b"tampered same revision")
        with self.assertRaisesRegex(RuntimeError, "baseline changed"):
            native.compare_baseline(current, self.baseline, self.request)
        (self.target.app / "dist/link").symlink_to(self.target.config)
        with self.assertRaisesRegex(RuntimeError, "Linked/special"):
            native.tree_inventory(self.target.app / "dist")

    def test_missing_fresh_stopped_marker_blocks_before_backup(self):
        original = self.target.stop
        def stop_without_marker(units):
            original(units)
            if units != [native.APP_UNIT]:
                for name in native.NAMES:
                    path = self.target.state / "captures" / name / "passive.jsonl"
                    path.write_bytes(b'{"historical":true}\n')
        with mock.patch.object(self.target, "stop", side_effect=stop_without_marker):
            with self.assertRaisesRegex(RuntimeError, "fresh stopped"):
                self.deploy()
        self.assertNotIn("backup", self.target.events)
        self.assertFalse(any(event.startswith("start:") for event in self.target.events))

    def test_json_comment_parser_preserves_quoted_urls(self):
        text = '{//comment\n"url":"https://example.test/*literal*/",/* comment */"x":true}'
        self.assertEqual(json.loads(native.strip_comments(text)), {"url": "https://example.test/*literal*/", "x": True})


if __name__ == "__main__":
    unittest.main()
