import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import openfootball_history as history


class OpenFootballHistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_parses_dict_and_list_scores_and_skips_unplayed(self):
        path = self.root / "en.1.json"
        path.write_text(json.dumps({"matches": [
            {"round": "1", "date": "2025-08-01", "team1": "Alpha FC", "team2": "Beta FC",
             "score": {"ft": [2, 1]}},
            {"round": "2", "date": "2025-08-02", "team1": "Beta FC", "team2": "Alpha FC",
             "score": [0, 0]},
            {"round": "3", "date": "2025-08-03", "team1": "Alpha FC", "team2": "Beta FC"},
        ]}), encoding="utf-8")
        rows = history.parse_file(path, "EPL", "2025-26")
        self.assertEqual(len(rows), 2)
        self.assertEqual([row["score"]["winner"] for row in rows], ["h", "d"])
        self.assertTrue(all(row["source"]["research_only"] for row in rows))

    def test_duplicate_fixture_is_rejected(self):
        fixture = {"date": "2025-08-01", "team1": "Alpha", "team2": "Beta", "score": [1, 0]}
        path = self.root / "en.1.json"
        path.write_text(json.dumps({"matches": [fixture, fixture]}), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "duplicate"):
            history.parse_file(path, "EPL", "2025-26")

    def test_checkout_must_match_pinned_revision_and_license(self):
        (self.root / "LICENSE.md").write_text("CC0 public domain", encoding="utf-8")
        with mock.patch.object(history, "_checkout_revision", return_value=history.PINNED_REVISION):
            self.assertEqual(history.verify_checkout(self.root), self.root)
        with mock.patch.object(history, "_checkout_revision", return_value="moving-head"):
            with self.assertRaisesRegex(ValueError, "must be pinned"):
                history.verify_checkout(self.root)


if __name__ == "__main__":
    unittest.main()
