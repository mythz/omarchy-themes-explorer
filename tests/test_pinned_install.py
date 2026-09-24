"""Exact-commit installs must ignore a moved branch and fail closed."""

import importlib.util
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("themes_server", REPO / "app/server.py")
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)


def git(path, *args):
    return subprocess.run(["git", *args], cwd=path, check=True, capture_output=True,
                          text=True).stdout.strip()


class PinnedInstallTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.origin = self.root / "origin"
        self.origin.mkdir()
        git(self.origin, "init", "-q")
        git(self.origin, "config", "user.name", "Test")
        git(self.origin, "config", "user.email", "test@example.invalid")
        (self.origin / "colors.toml").write_text('background = "#111111"\n')
        git(self.origin, "add", ".")
        git(self.origin, "commit", "-qm", "reviewed")
        self.reviewed = git(self.origin, "rev-parse", "HEAD")
        (self.origin / "colors.toml").write_text('background = "#eeeeee"\n')
        git(self.origin, "commit", "-qam", "branch moved")
        self.themes = self.root / "themes"
        self.bin = self.root / "bin"
        self.bin.mkdir()
        fake_omarchy = self.bin / "omarchy"
        fake_omarchy.write_text('#!/bin/sh\n[ "$1 $2 $3" = "theme set sample" ]\n')
        fake_omarchy.chmod(0o755)
        self.patch = patch.multiple(server, USER_THEMES=self.themes)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.env_patch = patch.dict(os.environ, PATH=str(self.bin) + os.pathsep + os.environ["PATH"])
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)

    def test_installs_reviewed_commit_after_branch_moves(self):
        server.install_extra_theme("sample", str(self.origin), self.reviewed)
        installed = self.themes / "sample"
        self.assertEqual(git(installed, "rev-parse", "HEAD"), self.reviewed)
        self.assertIn("#111111", (installed / "colors.toml").read_text())
        self.assertEqual([p.name for p in self.themes.iterdir()], ["sample"])

    def test_missing_commit_leaves_no_theme(self):
        with self.assertRaises(RuntimeError):
            server.install_extra_theme("sample", str(self.origin), "0" * 40)
        self.assertEqual(list(self.themes.iterdir()), [])

    def test_existing_theme_is_preserved(self):
        installed = self.themes / "sample"
        installed.mkdir(parents=True)
        (installed / "keep").write_text("untouched")
        with self.assertRaises(FileExistsError):
            server.install_extra_theme("sample", str(self.origin), self.reviewed)
        self.assertEqual((installed / "keep").read_text(), "untouched")

    def test_unpinned_catalogue_entry_is_hidden(self):
        catalogue = self.root / "catalogue.json"
        catalogue.write_text(json.dumps({"themes": [
            {"slug": "sample", "repo": "https://github.com/a/b"},
            {"slug": "pinned", "repo": "https://github.com/a/b", "commit": self.reviewed},
        ]}))
        with patch.object(server, "EXTRA_THEMES", catalogue):
            self.assertEqual([t["slug"] for t in server.extra_themes(set())], ["pinned"])
            self.assertIsNone(server.extra_source("sample"))

    def test_published_catalogue_and_wallpapers_are_pinned(self):
        catalogue = json.loads((REPO / "extra-themes.json").read_text())
        self.assertEqual(catalogue["count"], len(catalogue["themes"]))
        for theme in catalogue["themes"]:
            with self.subTest(theme=theme["slug"]):
                self.assertTrue(server.valid_extra_source(theme))
                self.assertNotIn("install", theme)
                self.assertTrue(all("/blob/%s/" % theme["commit"] in url
                                    for url in theme["backgrounds"]))


if __name__ == "__main__":
    unittest.main()
