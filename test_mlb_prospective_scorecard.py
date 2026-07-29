import tempfile
import unittest
from pathlib import Path

import forecast_ledger
from mlb_prospective_scorecard import build_report, extract_rows


def event(event_type, fixture_id, payload, effective_at="2026-07-01T12:00:00Z"):
    return {"event_type": event_type, "fixture_id": fixture_id,
            "event_id": f"{event_type}-{fixture_id}-{payload.get('score', '')}",
            "effective_at": effective_at, "payload": payload}


def lock(fixture_id="g1", kickoff="2026-07-01T23:00:00Z", probability=.62):
    return event("forecast_locked", fixture_id, {
        "lock": {"kickoff": kickoff},
        "model": {"regulation_probabilities": {"h": 58, "d": 0, "a": 42}},
        "features": {"mlb_challenger_shadow": {
            "mode": "prospective_shadow", "production_weight": 0,
            "model_version": "frozen-v1", "trained_through": "2025-09-28",
            "home_win_probability": probability,
            "missing_personnel": ["probable_or_confirmed_starter"],
        }},
    })


def grade(fixture_id="g1", result="h", score="5-3"):
    return event("forecast_graded", fixture_id, {"result": result, "score": score},
                 "2026-07-02T03:00:00Z")


class MLBProspectiveScorecardTests(unittest.TestCase):
    def test_extracts_frozen_pregame_binary_forecasts(self):
        rows, counts = extract_rows([lock(), grade(), lock("tie"), grade("tie", "d")])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["home_win"], 1)
        self.assertEqual(rows[0]["official_home_probability"], .58)
        self.assertEqual(rows[0]["challenger_home_probability"], .62)
        self.assertEqual(counts["ties_excluded"], 1)

    def test_latest_grade_correction_wins(self):
        rows, _ = extract_rows([lock(), grade(result="h"), grade(result="a", score="3-5")])
        self.assertEqual(rows[0]["home_win"], 0)
        self.assertEqual(rows[0]["grade_event_id"], "forecast_graded-g1-3-5")

    def test_ambiguous_and_post_kickoff_locks_are_excluded(self):
        late = lock("late", kickoff="2026-06-30T23:00:00Z")
        rows, counts = extract_rows([lock(), lock(), grade(), late, grade("late")])
        self.assertEqual(rows, [])
        self.assertEqual(counts["ambiguous_locks"], 1)
        self.assertEqual(counts["invalid_lock_time"], 1)

    def test_report_validates_ledger_and_scores_both_models(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ledger.jsonl"
            record = {
                "integrity_eligible": True, "fixture_id": "g1", "competition": "MLB",
                "home": "A", "away": "B", "kickoff": "2026-07-01T23:00:00Z",
                "locked_at": "2026-07-01T12:00:00Z", "status_at_lock": "UPCOMING",
                "regulation_probs": {"h": 58, "d": 0, "a": 42},
                "prediction_snapshot": {"model": {"h": 60, "d": 0, "a": 40}},
                "input_snapshot": {"match": {"mlb_challenger_shadow": {
                    "mode": "prospective_shadow", "production_weight": 0,
                    "model_version": "frozen-v1", "trained_through": "2025-09-28",
                    "home_win_probability": .62,
                }}},
                "result": "h", "score": "5-3",
                "result_snapshot": {"observed_at": "2026-07-02T03:00:00Z"},
            }
            forecast_ledger.sync_pick_records(path, [record], "MLB")
            report = build_report([path])
            self.assertEqual(report["status"], "collecting_prospective_evidence")
            self.assertEqual(report["models"]["official"]["n"], 1)
            self.assertEqual(report["models"]["run_strength_challenger"]["brier"], .1444)
            self.assertEqual(report["production_weight"], 0)


if __name__ == "__main__":
    unittest.main()
