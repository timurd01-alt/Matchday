import json
import tempfile
import unittest
from pathlib import Path

import forecast_ledger


def official_record(result=None):
    return {
        "integrity_eligible": True,
        "fixture_id": "fixture-1",
        "competition": "NFL",
        "home": "Alpha",
        "away": "Beta",
        "kickoff": "2026-09-10T00:00:00Z",
        "locked_at": "2026-09-09T18:00:00Z",
        "lead_time_seconds": 21600,
        "status_at_lock": "UPCOMING",
        "outcome_basis": "regulation",
        "model_ver": "test-v1",
        "model_code_marker": "test-marker",
        "pick": "h",
        "confidence": 61,
        "probs": {"h": 61, "d": 0, "a": 39},
        "regulation_probs": {"h": 61, "d": 0, "a": 39},
        "factor_snapshot": {"elo": 1.2},
        "market_snapshot": {"h": 55, "d": 0, "a": 45},
        "market_snapshot_at": "2026-09-09T18:00:00Z",
        "market_basis": "regulation_1x2",
        "prediction_snapshot": {
            "model": {"h": 64, "d": 0, "a": 36},
            "adjusted": {"h": 61, "d": 0, "a": 39},
            "data_quality": {"level": "established"},
        },
        "input_snapshot": {
            "competition": "NFL",
            "match": {
                "data_source": "nflverse (CC BY 4.0)",
                "model_signal_schema": 5,
                "advanced_metrics": {"home": {"epa_per_play": 0.12}},
                "nfl_challenger_shadow": {"model_version": "test-shadow", "production_weight": 0},
                "mlb_challenger_shadow": {"model_version": "test-mlb-shadow", "production_weight": 0},
            },
        },
        "mfti_shadow": {"version": "shadow"},
        "result": result,
    }


class ForecastLedgerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "forecast_ledger_nfl.jsonl"

    def tearDown(self):
        self.temp.cleanup()

    def test_lock_is_append_only_and_idempotent(self):
        first = forecast_ledger.sync_pick_records(self.path, [official_record()], "NFL")
        second = forecast_ledger.sync_pick_records(self.path, [official_record()], "NFL")
        self.assertEqual(first["appended"], 1)
        self.assertEqual(second["appended"], 0)
        self.assertEqual(forecast_ledger.validate(self.path)["events"], 1)
        event = forecast_ledger.read_events(self.path)[0]
        self.assertEqual(event["payload"]["features"]["nfl_challenger_shadow"]["production_weight"], 0)
        self.assertEqual(event["payload"]["features"]["mlb_challenger_shadow"]["production_weight"], 0)

    def test_grade_and_later_correction_append_new_events(self):
        rec = official_record("h")
        rec.update({
            "model_result": "h", "market_result": "h", "score": "24-17",
            "model_hit": True, "market_hit": True, "brier3": 0.304,
            "result_snapshot": {
                "display": {"home": 24, "away": 17},
                "ultimate_winner": "h", "observed_at": "2026-09-10T04:00:00Z",
            },
        })
        forecast_ledger.sync_pick_records(self.path, [rec], "NFL")
        rec["score"] = "27-17"
        rec["result_snapshot"] = {
            "display": {"home": 27, "away": 17},
            "ultimate_winner": "h", "observed_at": "2026-09-10T04:10:00Z",
        }
        forecast_ledger.sync_pick_records(self.path, [rec], "NFL")
        events = forecast_ledger.read_events(self.path)
        self.assertEqual([event["event_type"] for event in events],
                         ["forecast_locked", "forecast_graded", "forecast_graded"])

    def test_tampering_breaks_validation(self):
        forecast_ledger.sync_pick_records(self.path, [official_record()], "NFL")
        event = json.loads(self.path.read_text(encoding="utf-8"))
        event["payload"]["model"]["pick"] = "a"
        self.path.write_text(json.dumps(event) + "\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            forecast_ledger.validate(self.path)

    def test_coverage_reports_missing_lock_and_grade(self):
        rec = official_record("h")
        rec.update({"model_hit": True, "score": "24-17"})
        before = forecast_ledger.coverage(self.path, [rec])
        self.assertEqual(before["missing_locks"], ["fixture-1"])
        self.assertEqual(before["missing_grades"], ["fixture-1"])
        self.assertFalse(before["complete"])

        forecast_ledger.sync_pick_records(self.path, [rec], "NFL")
        after = forecast_ledger.coverage(self.path, [rec])
        self.assertTrue(after["complete"])
        self.assertEqual(after["logged_locks"], 1)
        self.assertEqual(after["logged_grades"], 1)


if __name__ == "__main__":
    unittest.main()
