import argparse
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("native_release", Path(__file__).with_name("native_release.py"))
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


class ControllerTests(unittest.TestCase):
    def args(self, output, **kwargs):
        values = dict(package_sha256="a" * 64, lock_sha256="b" * 64, output=str(output),
                      deploy_local_target=False, identity_file=None, known_hosts=None, expected_current=None)
        values.update(kwargs)
        return argparse.Namespace(**values)

    def fixture_artifacts(self, output):
        output.mkdir()
        helper = release.preparer()
        commit = "c" * 40
        workflow = {"id": 123, "path": helper.WORKFLOW_PATH, "state": "active"}
        run = {"id": 456, "workflow_id": 123, "path": helper.WORKFLOW_PATH,
               "event": "push", "head_branch": "main", "head_sha": commit,
               "status": "completed", "conclusion": "success",
               "repository": {"id": 1, "full_name": helper.REPO},
               "head_repository": {"id": 1, "full_name": helper.REPO}}
        for name, value in (("main.json", {"sha": commit}), ("workflow.json", workflow),
                            ("ci-runs.json", {"workflow_runs": [run]})):
            (output / name).write_text(json.dumps(value))
        for name in ("dist.tar.gz", "source.tar.gz", "build.log"):
            (output / name).write_bytes(name.encode())
        manifest = {"schema": 1, "repo": helper.REPO, "commit": commit,
                    "package_sha256": "a" * 64, "lock_sha256": "b" * 64,
                    "preparer_sha256": release.digest(Path(helper.__file__).read_bytes()),
                    "workflow_id": 123, "ci_run_id": 456,
                    "artifacts_sha256": {p.name: release.digest(p.read_bytes()) for p in output.iterdir()}}
        (output / "manifest.json").write_text(json.dumps(manifest))
        return manifest

    def test_artifacts_bind_ci_and_every_retained_byte(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "build"
            manifest = self.fixture_artifacts(output)
            actual, raw, dist = release.artifacts(output, "a" * 64, "b" * 64)
            self.assertEqual(actual, manifest)
            self.assertEqual(dist, b"dist.tar.gz")
            (output / "build.log").write_bytes(b"tampered")
            with self.assertRaises(ValueError):
                release.artifacts(output, "a" * 64, "b" * 64)

    def test_manifest_cannot_substitute_other_ci_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "build"
            manifest = self.fixture_artifacts(output)
            manifest["ci_run_id"] = 999
            (output / "manifest.json").write_text(json.dumps(manifest))
            with self.assertRaises(ValueError):
                release.artifacts(output, "a" * 64, "b" * 64)

    def test_deploy_envelope_and_complete_result_bind_exact_artifacts(self):
        manifest = {"commit": "c" * 40, "package_sha256": "a" * 64, "lock_sha256": "b" * 64}
        baseline = {"schema": 1, "revision": "d" * 40, "baseline_sha256": "e" * 64,
                    "package_sha256": "a" * 64, "lock_sha256": "b" * 64,
                    "enabled_recorders": {"washer": True, "dryer": False, "sidekick": False}}
        envelope = release.deploy_request(manifest, b"manifest", b"dist", baseline, b"source")
        request = envelope["request"]
        self.assertEqual(request["baseline_sha256"], baseline["baseline_sha256"])
        self.assertEqual(request["dist_sha256"], release.digest(b"dist"))
        self.assertEqual(set(envelope["artifacts"]), {"manifest.json", "source.tar.gz", "dist.tar.gz"})
        result = {"schema": 1, "status": "complete", "revision": manifest["commit"],
                  "enabled_recorders": request["enabled_recorders"],
                  **{key: request[key] for key in ("manifest_sha256", "dist_sha256", "source_sha256")}}
        release.verify_result(result, request)
        result["dist_sha256"] = "f" * 64
        with self.assertRaises(ValueError):
            release.verify_result(result, request)
        changed = dict(baseline, baseline_sha256="f" * 64)
        self.assertTrue(release.same_inspect(changed, baseline))
        changed["revision"] = "f" * 40
        self.assertFalse(release.same_inspect(changed, baseline))

    def test_local_end_to_end_preserves_approved_baseline_and_journals_completion(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "build"
            baseline = {"schema": 1, "revision": "d" * 40, "baseline_sha256": "e" * 64,
                        "package_sha256": "a" * 64, "lock_sha256": "b" * 64,
                        "enabled_recorders": {"washer": True, "dryer": False, "sidekick": False}}
            approved = Path(tmp) / "approved.json"
            approved.write_text(json.dumps(baseline))
            args = self.args(output, deploy_local_target=True, identity_file="id", known_hosts="hosts",
                             expected_current=str(approved))
            helper = release.preparer()
            helper.prepare = lambda args: self.fixture_artifacts(output)
            requests = []
            def target(command, envelope):
                requests.append(envelope)
                if envelope["op"] == "inspect":
                    return dict(baseline, baseline_sha256="f" * 64)
                request = envelope["request"]
                self.assertEqual(request["baseline_sha256"], baseline["baseline_sha256"])
                return {"schema": 1, "status": "complete", "revision": request["revision"],
                        "enabled_recorders": request["enabled_recorders"],
                        **{key: request[key] for key in ("manifest_sha256", "dist_sha256", "source_sha256")}}
            with patch.object(release, "preparer", return_value=helper), \
                    patch.object(release, "ssh_command", return_value=["ssh"]), \
                    patch.object(release, "transport", side_effect=target):
                result = release.execute(args)
            self.assertEqual(result["status"], "complete")
            self.assertEqual([r["op"] for r in requests], ["inspect", "inspect", "deploy"])
            records = [json.loads(line) for line in (output / "release-journal.jsonl").read_text().splitlines()]
            self.assertEqual([r["phase"] for r in records], ["prepared", "sending", "committed"])

    def test_controller_envelope_matches_real_worker_validator(self):
        spec = importlib.util.spec_from_file_location("native_target_contract", Path(__file__).with_name("native_target.py"))
        target = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(target)
        manifest = {"commit": "c" * 40, "package_sha256": target.PACKAGE_SHA,
                    "lock_sha256": target.LOCK_SHA}
        baseline = {"schema": 1, "revision": "d" * 40, "baseline_sha256": "e" * 64,
                    "package_sha256": target.PACKAGE_SHA, "lock_sha256": target.LOCK_SHA,
                    "enabled_recorders": {"washer": True, "dryer": False, "sidekick": False}}
        envelope = release.deploy_request(manifest, b"manifest", b"dist", baseline, b"source")
        target.validate_request(envelope["request"])

    def test_historical_revision_requires_hashed_ancestry_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "build"
            manifest = self.fixture_artifacts(output)
            main = "d" * 40
            (output / "main.json").write_text(json.dumps({"sha": main}))
            manifest["artifacts_sha256"]["main.json"] = release.digest((output / "main.json").read_bytes())
            (output / "manifest.json").write_text(json.dumps(manifest))
            with self.assertRaises(ValueError):
                release.artifacts(output, "a" * 64, "b" * 64)
            comparison = {"status": "ahead", "base_commit": {"sha": manifest["commit"]},
                          "merge_base_commit": {"sha": manifest["commit"]}}
            (output / "main-ancestry.json").write_text(json.dumps(comparison))
            manifest["artifacts_sha256"]["main-ancestry.json"] = release.digest((output / "main-ancestry.json").read_bytes())
            (output / "manifest.json").write_text(json.dumps(manifest))
            release.artifacts(output, "a" * 64, "b" * 64)

    def test_duplicate_json_rejected(self):
        with self.assertRaises(ValueError):
            release.load_json('{"op":"inspect","op":"deploy"}')

    def test_ssh_is_fixed_and_has_no_remote_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            identity = Path(tmp) / "identity"
            known = Path(tmp) / "known_hosts"
            identity.touch()
            known.touch()
            command = release.ssh_command(identity, known)
            self.assertEqual(command[-1], "deploy-rethink@10.0.40.5")
            self.assertIn("StrictHostKeyChecking=yes", command)
            self.assertIn("IdentityAgent=none", command)
            self.assertEqual(command[1:3], ["-F", "/dev/null"])

    def test_deployment_requires_explicit_credentials_before_build(self):
        with patch.object(release, "preparer") as helper:
            with self.assertRaises(ValueError):
                release.execute(self.args("unused", deploy_local_target=True))
            helper.return_value.prepare.assert_not_called()

    def test_prepare_default_never_contacts_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "build"
            with patch.object(release, "preparer") as helper, patch.object(release, "transport") as transport:
                helper.return_value.prepare.side_effect = lambda args: output.mkdir()
                with patch.object(release, "artifacts", return_value=({"commit": "c" * 40}, b"manifest", b"dist")):
                    result = release.execute(self.args(output))
            self.assertEqual(result["status"], "prepared-only")
            transport.assert_not_called()
            records = [json.loads(line) for line in (output / "release-journal.jsonl").read_text().splitlines()]
            self.assertEqual(records[0]["phase"], "prepared")

    def test_target_mismatch_prevents_local_build(self):
        with tempfile.TemporaryDirectory() as tmp:
            baseline = Path(tmp) / "baseline"
            baseline.write_text('{"current":"old"}')
            args = self.args(Path(tmp) / "build", deploy_local_target=True,
                             identity_file="id", known_hosts="hosts", expected_current=str(baseline))
            with patch.object(release, "preparer") as helper, patch.object(release, "ssh_command"), \
                    patch.object(release, "transport", return_value={"current": "unexpected"}):
                with self.assertRaises(ValueError):
                    release.execute(args)
                helper.return_value.prepare.assert_not_called()

    def test_changed_target_after_build_is_not_deployed(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "build"
            baseline = Path(tmp) / "baseline"
            baseline.write_text('{"current":"old"}')
            args = self.args(output, deploy_local_target=True, identity_file="id", known_hosts="hosts",
                             expected_current=str(baseline))
            with patch.object(release, "preparer") as helper, patch.object(release, "ssh_command"), \
                    patch.object(release, "transport", side_effect=[{"current": "old"}, {"current": "changed"}]) as transport:
                helper.return_value.prepare.side_effect = lambda args: output.mkdir()
                with patch.object(release, "artifacts", return_value=({"commit": "c" * 40}, b"manifest", b"dist")):
                    with self.assertRaises(ValueError):
                        release.execute(args)
                self.assertEqual(transport.call_count, 2)
            self.assertIn("failed-or-unknown", (output / "release-journal.jsonl").read_text())

    def test_large_request_rejected_before_ssh(self):
        with patch.object(release.subprocess, "run") as run:
            with self.assertRaises(ValueError):
                release.transport(["ssh"], {"data": "x" * release.MAX_REQUEST})
            run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
