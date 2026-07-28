import copy
import datetime
import json
import pathlib
import tempfile
import unittest
from unittest import mock

import fetch_data


def eligible_match():
    kickoff = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=1)
    return {
        "id": "persistence-test-1",
        "status": "UPCOMING",
        "kickoff": kickoff.isoformat().replace("+00:00", "Z"),
        "stage": "Regular Season",
        "home": {"name": "Home", "code": "H"},
        "away": {"name": "Away", "code": "A"},
        "markets": {},
        "prediction": {
            "pick": "h", "pick_name": "Home", "confidence": 60,
            "model": {"h": 60, "d": 0, "a": 40}, "why": {},
        },
    }


class PickLockPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.ledger = pathlib.Path(self.temp.name) / "picks.json"
        patcher = mock.patch.object(fetch_data, "PICKS_FILE", str(self.ledger))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_eligible_pick_is_written_and_reloadable_as_official(self):
        fetch_data.update_scorecard([eligible_match()])
        saved = json.loads(self.ledger.read_text(encoding="utf-8"))
        self.assertTrue(fetch_data._record_is_official(saved["persistence-test-1"]))

    def test_silent_writer_failure_is_rejected_by_postcondition(self):
        with mock.patch.object(fetch_data, "_save_picks", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "persistence check failed"):
                fetch_data.update_scorecard([eligible_match()])

    def test_locked_pick_is_graded_and_prediction_stays_frozen(self):
        match = eligible_match()
        fetch_data.update_scorecard([match])
        locked = json.loads(self.ledger.read_text(encoding="utf-8"))[match["id"]]
        snapshot = copy.deepcopy(locked["prediction_snapshot"])

        finished = copy.deepcopy(match)
        finished["status"] = "FINISHED"
        finished["score"] = {"home": 3, "away": 1, "winner": "h"}
        finished["prediction"] = {"pick": "a", "pick_name": "Away", "confidence": 99}
        scorecard = fetch_data.update_scorecard([finished])

        saved = json.loads(self.ledger.read_text(encoding="utf-8"))[match["id"]]
        self.assertEqual(saved["prediction_snapshot"], snapshot)
        self.assertEqual(saved["result"], "h")
        self.assertTrue(saved["model_hit"])
        self.assertEqual(saved["score"], "3-1")
        self.assertEqual(scorecard["graded"], 1)
        self.assertEqual(scorecard["model_hits"], 1)

    def test_silent_grade_writer_failure_is_rejected_by_postcondition(self):
        match = eligible_match()
        fetch_data.update_scorecard([match])
        finished = copy.deepcopy(match)
        finished["status"] = "FINISHED"
        finished["score"] = {"home": 0, "away": 2, "winner": "a"}

        with mock.patch.object(fetch_data, "_save_picks", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "grading persistence check failed"):
                fetch_data.update_scorecard([finished])

    def test_atomic_replace_error_fails_the_fetch(self):
        with mock.patch.object(fetch_data.os, "replace", side_effect=OSError("disk full")):
            with self.assertRaisesRegex(RuntimeError, "could not persist"):
                fetch_data._save_picks({"fixture": {"pick": "h"}})


if __name__ == "__main__":
    unittest.main()
