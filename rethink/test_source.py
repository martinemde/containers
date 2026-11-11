import copy
import hashlib
import json
import unittest

from source import API, REPO, WORKFLOW, select_source


class SourceTest(unittest.TestCase):
    def setUp(self):
        self.revision = "a" * 40
        self.run = dict(id=123, head_sha=self.revision, head_branch="main", event="push",
                        status="completed", conclusion="success", path=WORKFLOW,
                        repository={"full_name": REPO}, head_repository={"full_name": REPO})
        self.runs = [self.run]
        self.archive_calls = 0

    def get(self, url):
        if url == API + "/branches/main":
            return json.dumps({"commit": {"sha": self.revision}}).encode()
        if url.startswith(API + "/actions/workflows/ci.yml/runs?"):
            self.assertIn("head_sha=" + self.revision, url)
            return json.dumps({"workflow_runs": self.runs}).encode()
        self.assertEqual(url, f"https://github.com/{REPO}/archive/{self.revision}.tar.gz")
        self.archive_calls += 1
        return b"exact public source archive"

    def test_exact_main_success_and_archive_hash(self):
        result = select_source(self.get)
        self.assertEqual(result, dict(revision=self.revision, ci_run="123",
                         archive_sha256=hashlib.sha256(b"exact public source archive").hexdigest()))
        self.assertEqual(self.archive_calls, 1)

    def test_pending_main_has_no_success(self):
        self.runs = []
        with self.assertRaises(ValueError):
            select_source(self.get)
        self.assertEqual(self.archive_calls, 0)

    def test_rejects_untrusted_or_stale_runs(self):
        changes = dict(head_sha="b" * 40, head_branch="feature", event="pull_request",
                       status="in_progress", conclusion="failure", path="other.yml",
                       repository={"full_name": "other/repo"},
                       head_repository={"full_name": "other/repo"})
        original = copy.deepcopy(self.run)
        for field, value in changes.items():
            with self.subTest(field=field):
                self.runs = [{**original, field: value}]
                with self.assertRaises(ValueError):
                    select_source(self.get)
        self.assertEqual(self.archive_calls, 0)


if __name__ == "__main__":
    unittest.main()
