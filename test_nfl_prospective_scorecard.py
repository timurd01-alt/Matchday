import tempfile
import unittest
from pathlib import Path

import forecast_ledger
from nfl_prospective_scorecard import build_report, extract_rows


def event(event_type, fixture_id, payload, effective_at="2026-09-01T00:00:00Z"):
    return {"event_type": event_type, "fixture_id": fixture_id,
            "event_id": f"{event_type}-{fixture_id}-{payload.get('score', '')}",
            "effective_at": effective_at, "payload": payload}


def lock(fixture_id="g1", kickoff="2026-09-08T00:00:00Z", probability=.62):
    return event("forecast_locked", fixture_id, {
        "lock": {"kickoff": kickoff}, "features": {"nfl_challenger_shadow": {
            "mode": "research_only", "production_weight": 0, "model_version": "frozen-v1",
            "trained_through": "2026-02-01", "home_win_probability": probability,
            "calibrated_elo_home_probability": .60, "elo_baseline_home_probability": .66}}})


def grade(fixture_id="g1", result="h", score="24-17"):
    return event("forecast_graded", fixture_id, {"result": result, "score": score},
                 "2026-09-08T04:00:00Z")


class NFLProspectiveScorecardTests(unittest.TestCase):
    def test_extracts_only_frozen_pregame_binary_forecasts(self):
        rows, counts = extract_rows([lock(), grade(), lock("tie"), grade("tie", "d")])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["home_win"], 1)
        self.assertEqual(rows[0]["calibrated_elo_home_probability"], .60)
        self.assertEqual(counts["ties_excluded"], 1)

    def test_latest_grade_correction_wins(self):
        rows, _ = extract_rows([lock(), grade(result="h"), grade(result="a", score="24-27")])
        self.assertEqual(rows[0]["home_win"], 0)
        self.assertEqual(rows[0]["grade_event_id"], "forecast_graded-g1-24-27")

    def test_ambiguous_or_post_kickoff_locks_are_excluded(self):
        late = lock("late", kickoff="2026-08-31T00:00:00Z")
        rows, counts = extract_rows([lock(), lock(), grade(), late, grade("late")])
        self.assertEqual(rows, [])
        self.assertEqual(counts["ambiguous_locks"], 1)
        self.assertEqual(counts["invalid_lock_time"], 1)

    def test_report_validates_ledger_and_scores_all_three_models(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ledger.jsonl"
            record = {"integrity_eligible": True, "fixture_id": "g1", "competition": "NFL",
                "home": "A", "away": "B", "kickoff": "2026-09-08T00:00:00Z",
                "locked_at": "2026-09-01T00:00:00Z", "status_at_lock": "UPCOMING",
                "prediction_snapshot": {"model": {"h": 60, "a": 40}},
                "input_snapshot": {"match": {"nfl_challenger_shadow": {
                    "mode": "research_only", "production_weight": 0, "model_version": "frozen-v1",
                    "trained_through": "2026-02-01", "home_win_probability": .62,
                    "calibrated_elo_home_probability": .60, "elo_baseline_home_probability": .66}}},
                "result": "h", "score": "24-17",
                "result_snapshot": {"observed_at": "2026-09-08T04:00:00Z"}}
            forecast_ledger.sync_pick_records(path, [record], "NFL")
            report = build_report([path])
            self.assertEqual(report["status"], "collecting_prospective_evidence")
            self.assertEqual(report["models"]["calibrated_elo"]["n"], 1)
            self.assertEqual(report["models"]["raw_elo"]["brier"], .1156)
            self.assertEqual(report["production_weight"], 0)


if __name__ == "__main__":
    unittest.main()
