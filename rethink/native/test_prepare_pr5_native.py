"""Offline unit tests. No network, npm, services, or target access."""
import importlib.util
import io
import json
from pathlib import Path
import tarfile
import tempfile
import types
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("prep", Path(__file__).with_name("prepare-pr5-native.py"))
prep = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(prep)
COMMIT = "a" * 40


def workflow():
    return {"id": 123, "path": prep.WORKFLOW_PATH, "state": "active"}


def evidence():
    return {"id": 456, "workflow_id": 123, "path": prep.WORKFLOW_PATH,
            "event": "push", "head_branch": "main", "head_sha": COMMIT,
            "status": "completed", "conclusion": "success",
            "repository": {"id": 1, "full_name": prep.REPO},
            "head_repository": {"id": 1, "full_name": prep.REPO}}


def responses(data=None):
    values = [{"sha": COMMIT}, workflow(), {"workflow_runs": [evidence()]}]
    return [json.dumps(value).encode() for value in values] + ([] if data is None else [data])


def archive(entries):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz") as tar:
        for name, kind, data in entries:
            member = tarfile.TarInfo(name)
            member.type = kind
            member.size = len(data) if kind == tarfile.REGTYPE else 0
            tar.addfile(member, io.BytesIO(data) if kind == tarfile.REGTYPE else None)
    return output.getvalue()


class PreparationTests(unittest.TestCase):
    def test_ci_identity_gate(self):
        prep.verify_ci(evidence(), workflow(), COMMIT)
        for field, value in (("workflow_id", 999), ("path", ".github/workflows/other.yml"),
                             ("event", "pull_request"), ("head_branch", "feature"),
                             ("head_sha", "b" * 40), ("status", "in_progress"),
                             ("conclusion", "failure"), ("id", None),
                             ("repository", {"id": 1, "full_name": "other/rethink"}),
                             ("head_repository", {"id": 2, "full_name": prep.REPO})):
            run = evidence()
            run[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                prep.verify_ci(run, workflow(), COMMIT)
        for field, value in (("path", ".github/workflows/other.yml"),
                             ("id", "123"), ("state", "disabled_manually")):
            wf = workflow()
            wf[field] = value
            with self.subTest(workflow=field), self.assertRaises(ValueError):
                prep.verify_ci(evidence(), wf, COMMIT)

    def test_missing_success_never_allocates_or_builds(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "output"
            args = types.SimpleNamespace(package_sha256="c" * 64,
                                         lock_sha256="d" * 64, output=str(output))
            failed = responses()
            failed[-1] = b'{"workflow_runs": []}'
            with patch.object(prep, "get", side_effect=failed), patch.object(prep, "run") as run:
                with self.assertRaises(ValueError):
                    prep.prepare(args)
                run.assert_not_called()
            self.assertFalse(output.exists())

    def test_archive_rejects_traversal_links_duplicates_and_roots(self):
        cases = [[("root/../escape", tarfile.REGTYPE, b"x")],
                 [("/absolute", tarfile.REGTYPE, b"x")],
                 [("root/link", tarfile.SYMTYPE, b"")],
                 [("root/link", tarfile.LNKTYPE, b"")],
                 [("root/fifo", tarfile.FIFOTYPE, b"")],
                 [("a/x", tarfile.REGTYPE, b"x"), ("b/y", tarfile.REGTYPE, b"y")],
                 [("root/a", tarfile.REGTYPE, b"x")] * 2]
        with tempfile.TemporaryDirectory() as tmp:
            for entries in cases:
                with self.subTest(entries=entries), self.assertRaises(ValueError):
                    prep.unpack(archive(entries), tmp)
            self.assertEqual(list(Path(tmp).iterdir()), [])
            prep.unpack(archive([("root/file", tarfile.REGTYPE, b"source")]), tmp)
            self.assertEqual((Path(tmp) / "file").read_bytes(), b"source")

    def test_main_advance_allowed_and_packages_only_after_native_commands(self):
        self.check_success()

    def test_explicit_main_ancestor_build(self):
        self.check_success(revision=COMMIT)

    def check_success(self, revision=None):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "build"
            digest = prep.sha256(b"{}")
            args = types.SimpleNamespace(package_sha256=digest, revision=revision,
                                         lock_sha256=digest, output=str(output))
            data = archive([("root/package.json", tarfile.REGTYPE, b"{}"),
                            ("root/package-lock.json", tarfile.REGTYPE, b"{}")])
            commands = []

            def fake_run(command, source, log, env):
                commands.append(command)
                self.assertEqual(env["GIT_REVISION"], COMMIT)
                self.assertFalse((output / "manifest.json").exists())
                log.write_text("fake build log")
                if command == ["npm", "run", "build"]:
                    version = source / "dist/util/version.js"
                    version.parent.mkdir(parents=True)
                    version.write_text("export const revision = '" + COMMIT[:7] + "'\n")

            urls = []

            def fake_get(url):
                urls.append(url)
                # The branch advances immediately after capture. A second resolution
                # would return a different SHA; the build must never ask for it.
                if url.endswith("/commits/main"):
                    return json.dumps({"sha": COMMIT if not revision and urls.count(url) == 1 else "b" * 40}).encode()
                if "/compare/" in url:
                    self.assertTrue(url.endswith(COMMIT + "..." + "b" * 40))
                    return json.dumps({"status": "ahead", "base_commit": {"sha": COMMIT},
                                       "merge_base_commit": {"sha": COMMIT}}).encode()
                if url.endswith("/actions/workflows/ci.yml"):
                    return json.dumps(workflow()).encode()
                if "/runs?" in url:
                    self.assertIn("head_sha=" + COMMIT, url)
                    return json.dumps({"workflow_runs": [evidence()]}).encode()
                self.assertTrue(url.endswith("/tar.gz/" + COMMIT))
                return data

            with patch.object(prep, "get", side_effect=fake_get), \
                    patch.object(prep, "run", side_effect=fake_run), \
                    patch.object(prep.subprocess, "check_output", side_effect=["v24.0.0", "11.0.0"]):
                prep.prepare(args)
            self.assertEqual(commands, [["npm", "ci", "--ignore-scripts", "--engine-strict",
                                        "--no-audit", "--no-fund"], ["npm", "test"],
                                       ["npm", "run", "check"], ["npm", "run", "build"]])
            manifest = json.loads((output / "manifest.json").read_text())
            self.assertEqual(manifest["commit"], COMMIT)
            self.assertEqual(manifest["ci_run_id"], 456)
            self.assertEqual("main-ancestry.json" in manifest["artifacts_sha256"], bool(revision))
            self.assertEqual(sum(url.endswith("/commits/main") for url in urls), 1)
            for name, digest in manifest["artifacts_sha256"].items():
                self.assertEqual(prep.sha256((output / name).read_bytes()), digest)

    def test_nonancestor_rejected_before_allocation(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "build"
            args = types.SimpleNamespace(revision=COMMIT, package_sha256="c" * 64,
                                         lock_sha256="d" * 64, output=str(output))
            for status, merge_base in (("diverged", "c" * 40), ("behind", "b" * 40),
                                       ("ahead", "c" * 40), ("identical", COMMIT)):
                comparison = {"status": status, "base_commit": {"sha": COMMIT},
                              "merge_base_commit": {"sha": merge_base}}
                with self.subTest(status=status), patch.object(prep, "get", side_effect=[
                        json.dumps({"sha": "b" * 40}).encode(),
                        json.dumps(comparison).encode()]), patch.object(prep, "run") as run:
                    with self.assertRaises(ValueError):
                        prep.prepare(args)
                    run.assert_not_called()
                    self.assertFalse(output.exists())

    def test_manifest_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp)
            for name in ("package.json", "package-lock.json"):
                (source / name).write_bytes(b"{}")
            digest = prep.sha256(b"{}")
            prep.verify_manifests(source, digest, digest)
            with self.assertRaises(ValueError):
                prep.verify_manifests(source, "0" * 64, digest)

    def test_deterministic_dist_and_reject_symlinks(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            dist = base / "dist"
            dist.mkdir()
            (dist / "app.js").write_bytes(b"native")
            files = prep.pack_dist(dist, base / "a.tar.gz")
            (dist / "app.js").touch()
            prep.pack_dist(dist, base / "b.tar.gz")
            self.assertEqual((base / "a.tar.gz").read_bytes(), (base / "b.tar.gz").read_bytes())
            self.assertEqual(files, {"app.js": prep.sha256(b"native")})
            (dist / "link").symlink_to("app.js")
            with self.assertRaises(ValueError):
                prep.pack_dist(dist, base / "c.tar.gz")


if __name__ == "__main__":
    unittest.main()
