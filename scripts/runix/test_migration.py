"""Negative tests for fork migration checks; no storage backend is modified."""

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

from verify_migration import BASELINE, GUARD, PUBLISHERS, verify


class MigrationChecks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        source = Path(__file__).resolve().parents[2]
        for name in (
            "LICENSE", "NOTICE", "README.md", "README.upstream.md", "AGENTS.md",
            "QUICK-LEARN.zh-CN.md",
        ):
            shutil.copyfile(source / name, self.root / name)
        shutil.copytree(source / "specs", self.root / "specs")
        shutil.copytree(source / ".github/workflows", self.root / ".github/workflows")
        originals = {
            "LICENSE": (source / "LICENSE").read_bytes(),
            "README.md": (source / "README.upstream.md").read_bytes(),
        }
        for name in PUBLISHERS:
            key = f".github/workflows/{name}"
            originals[key] = subprocess.check_output(
                ["git", "show", f"{BASELINE}:{key}"], cwd=source
            )

        def git_show(args, cwd):
            self.assertEqual(args[:2], ["git", "show"])
            prefix, name = args[2].split(":", 1)
            self.assertEqual(prefix, BASELINE)
            return originals[name]

        self.mock = patch("verify_migration.subprocess.check_output", side_effect=git_show)
        self.mock.start()
        self.addCleanup(self.mock.stop)

    def test_valid_fork(self):
        self.assertEqual(verify(self.root), [])

    def test_rejects_changed_license(self):
        (self.root / "LICENSE").write_text("replacement license")
        self.assertIn("Upstream LICENSE changed", verify(self.root))

    def test_rejects_lost_original_readme(self):
        (self.root / "README.upstream.md").write_text("replacement readme")
        self.assertIn("Preserved upstream README differs from baseline", verify(self.root))

    def test_rejects_unattributed_notice(self):
        (self.root / "NOTICE").write_text("Runix")
        self.assertIn("NOTICE is missing source attribution", verify(self.root))

    def test_rejects_missing_or_bypassed_publisher_guard(self):
        for condition in (
            None, "always()", GUARD + " || always()",
            "${{ " + GUARD + " && (always()) || always() || (false) }}",
        ):
            with self.subTest(condition=condition):
                path = self.root / ".github/workflows" / PUBLISHERS[0]
                original = path.read_text()
                workflow = yaml.safe_load(original)
                first_job = next(iter(workflow["jobs"].values()))
                if condition is None:
                    first_job.pop("if", None)
                else:
                    first_job["if"] = condition
                path.write_text(yaml.safe_dump(workflow))
                self.assertTrue(any("Unguarded" in error for error in verify(self.root)))
                path.write_text(original)

    def test_rejects_dead_development_link(self):
        with (self.root / "README.md").open("a") as stream:
            stream.write("\n[Development](specs/missing.md)\n")
        self.assertTrue(any("Broken local" in error for error in verify(self.root)))


if __name__ == "__main__":
    unittest.main()
