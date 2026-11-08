import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location("updater", Path(__file__).with_name("update-rethink-source.py"))
updater = importlib.util.module_from_spec(spec)
spec.loader.exec_module(updater)


class SourcePinTests(unittest.TestCase):
    def test_pin_and_checksum_stay_in_sync(self):
        recipe = (updater.ROOT / "rethink/Containerfile").read_text()
        readme = (updater.ROOT / "rethink/README.md").read_text()
        revision, checksum = "1" * 40, "2" * 64
        new_recipe, new_readme = updater.update_pin(recipe, readme, revision, checksum)
        self.assertEqual(new_recipe.count(revision), 2)
        self.assertEqual(new_readme.count(revision), 1)
        self.assertEqual(new_recipe.count(checksum), 1)
        self.assertEqual(new_readme.count(checksum), 1)
        self.assertEqual(updater.update_pin(new_recipe, new_readme, revision, checksum),
                         (new_recipe, new_readme))

    def test_pin_layout_and_moving_ref_are_rejected(self):
        recipe = (updater.ROOT / "rethink/Containerfile").read_text()
        readme = (updater.ROOT / "rethink/README.md").read_text()
        with self.assertRaises(ValueError):
            updater.update_pin(recipe, readme, "main", "2" * 64)
        with self.assertRaises(ValueError):
            updater.update_pin(recipe, readme + recipe, "1" * 40, "2" * 64)

    def test_only_trusted_successful_main_push_ci_counts(self):
        revision = "1" * 40
        run = dict(event="push", head_branch="main", head_sha=revision,
                   conclusion="success", status="completed", path=".github/workflows/ci.yml",
                   repository={"full_name": "martinemde/rethink"},
                   head_repository={"full_name": "martinemde/rethink"})
        self.assertTrue(updater.successful_main_ci([run], revision))
        self.assertFalse(updater.successful_main_ci([], revision))
        for field, value in [("event", "pull_request"), ("head_branch", "feature"),
                             ("head_sha", "2" * 40), ("conclusion", "failure"),
                             ("status", "in_progress"), ("path", ".github/workflows/other.yml"),
                             ("repository", {"full_name": "other/rethink"}),
                             ("head_repository", {"full_name": "other/rethink"})]:
            self.assertFalse(updater.successful_main_ci([dict(run, **{field: value})], revision))


if __name__ == "__main__":
    unittest.main()
