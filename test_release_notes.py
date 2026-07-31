"""Release notes are one file per build so concurrent branches never collide.

See build_updates.py's docstring: a single shared array literal made every pull
request conflict with every other one regardless of what it changed.
"""
import io
import json
import os
import tempfile
import unittest
from pathlib import Path

import build_updates

ROOT = Path(__file__).resolve().parent


class ReleaseNotesTests(unittest.TestCase):
    def test_committed_updates_js_is_in_sync(self):
        """Guards the one hazard of committing a generated file."""
        self.assertEqual(build_updates.main(["--check"]), 0,
                         "updates.js is stale -- run: python build_updates.py")

    def test_entries_are_ordered_newest_first(self):
        entries = build_updates.load_entries(str(ROOT / "updates"))
        self.assertGreater(len(entries), 100)
        ranks = [entry["rank"] for entry in entries]
        self.assertEqual(ranks, sorted(ranks, reverse=True))

    def test_no_shared_array_literal_remains(self):
        core = (ROOT / "app-1-core.js").read_text(encoding="utf-8")
        self.assertNotIn("const SYSTEM_UPDATES=[", core)
        self.assertIn("window.SYSTEM_UPDATES", core)

    def test_build_label_is_derived_not_hardcoded(self):
        """Two hand-maintained build strings had already drifted apart."""
        core = (ROOT / "app-1-core.js").read_text(encoding="utf-8")
        panels = (ROOT / "app-3-panels.js").read_text(encoding="utf-8")
        self.assertIn("function currentBuild()", core)
        self.assertIn("currentBuild()", panels)
        for name, source in (("app-1-core.js", core), ("app-3-panels.js", panels)):
            self.assertNotRegex(source, r"build 0\d{3}[A-Z]",
                                f"{name} still hardcodes a build label")

    def test_updates_js_is_loaded_before_the_app(self):
        markup = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertLess(markup.index("updates.js"), markup.index("app-1-core.js"))

    def test_deploy_publishes_and_regenerates_updates(self):
        workflow = (ROOT / ".github/workflows/deploy.yml").read_text(encoding="utf-8")
        self.assertIn("build_updates.py", workflow)
        self.assertIn("translations.js updates.js", workflow)

    def test_duplicate_ranks_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            for index in (1, 2):
                io.open(os.path.join(temp, f"e{index}.json"), "w", encoding="utf-8").write(
                    json.dumps({"rank": 5, "date": "Build X", "tag": "Fix",
                                "title": "t", "items": ["i"]}))
            with self.assertRaisesRegex(ValueError, "duplicate rank"):
                build_updates.load_entries(temp)

    def test_missing_fields_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            io.open(os.path.join(temp, "bad.json"), "w", encoding="utf-8").write(
                json.dumps({"rank": 1, "date": "Build X"}))
            with self.assertRaisesRegex(ValueError, "missing"):
                build_updates.load_entries(temp)

    def test_rank_gap_is_rejected(self):
        """Confirmed live 2026-07-31: two entries added back-to-back skipped
        rank 115, leaving the true newest entry sorting second instead of
        first -- silent, since a gap doesn't break rendering by itself."""
        with tempfile.TemporaryDirectory() as temp:
            for rank in (1, 3):  # 2 is missing
                io.open(os.path.join(temp, f"e{rank}.json"), "w", encoding="utf-8").write(
                    json.dumps({"rank": rank, "date": "Build X", "tag": "Fix",
                                "title": "t", "items": ["i"]}))
            with self.assertRaisesRegex(ValueError, "gap"):
                build_updates.load_entries(temp)

    def test_every_entry_has_real_content(self):
        for entry in build_updates.load_entries(str(ROOT / "updates")):
            self.assertTrue(entry["date"].strip(), entry["_path"])
            self.assertTrue(entry["title"].strip(), entry["_path"])
            for item in entry["items"]:
                self.assertTrue(item.strip(), entry["_path"])


if __name__ == "__main__":
    unittest.main()
