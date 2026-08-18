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

    def test_private_shadow_report_scores_deployable_blend_and_rejects_mixed_cohorts(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "shadow.jsonl"
            candidate = {
                "model_version": "candidate-v1", "trained_through": "2025-09-28",
                "artifact_sha256": "a" * 64, "feature_schema_version": 1,
                "transformation_version": "transform-v1", "production_weight": 0,
                "mode": "prospective_shadow", "home_win_probability": .62,
            }
            locked, _ = forecast_ledger.append_event(
                path, event_type="mlb_shadow_locked", fixture_id="g1", competition="MLB",
                effective_at="2026-07-01T21:00:00Z",
                identity={"model_version": "candidate-v1"},
                payload={"lock": {"kickoff": "2026-07-01T23:00:00Z"},
                         "baseline": {"home_win_probability": .58,
                                      "model_version": "official-v1",
                                      "model_signal_schema": 7}, "candidate": candidate,
                         "league_home_prior": {"home_win_probability": .535},
                         "independent_official": {"home_win_probability": .57},
                         "market": {"home_win_probability": .56},
                         "personnel_missingness": ["starting_pitchers"]})
            forecast_ledger.append_event(
                path, event_type="mlb_shadow_graded", fixture_id="g1", competition="MLB",
                effective_at="2026-07-02T03:00:00Z",
                identity={"lock_event_id": locked["event_id"], "result": "h"},
                payload={"lock_event_id": locked["event_id"], "result": "h",
                         "score": {"home": 5, "away": 3},
                         "fixture_identity": {"fixture_id": "g1",
                                              "kickoff": "2026-07-01T23:00:00Z",
                                              "participants": {}}})
            report = build_report([path])
            self.assertEqual(report["cohort"]["artifact_sha256"], "a" * 64)
            self.assertEqual(report["baseline_cohort"],
                             {"model_version": "official-v1", "model_signal_schema": 7})
            self.assertEqual(report["rows"][0]["baseline_model_version"], "official-v1")
            self.assertEqual(report["deployment_evaluation"]["models"]["capped_blend"]["n"], 1)
            self.assertEqual(report["coverage"]["market_available"], 1)
            self.assertEqual(report["coverage"]["personnel_missing_reasons"],
                             {"starting_pitchers": 1})

            candidate["artifact_sha256"] = "b" * 64
            forecast_ledger.append_event(
                path, event_type="mlb_shadow_locked", fixture_id="g2", competition="MLB",
                effective_at="2026-07-02T21:00:00Z", identity={"model_version": "candidate-v2"},
                payload={"lock": {"kickoff": "2026-07-02T23:00:00Z"},
                         "baseline": {"home_win_probability": .58,
                                      "model_version": "official-v1",
                                      "model_signal_schema": 7}, "candidate": candidate})
            with self.assertRaisesRegex(ValueError, "mixed MLB challenger artifact cohorts"):
                build_report([path])

    def test_report_rejects_mixed_incumbent_baseline_cohorts(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "shadow.jsonl"
            candidate = {"model_version": "candidate-v1", "trained_through": "2025-09-28",
                         "artifact_sha256": "a" * 64, "feature_schema_version": 1,
                         "transformation_version": "transform-v1", "production_weight": 0,
                         "mode": "prospective_shadow", "home_win_probability": .62}
            for index, baseline_version in enumerate(("official-v1", "official-v2"), 1):
                fixture_id = f"g{index}"
                kickoff = f"2026-07-0{index}T23:00:00Z"
                locked, _ = forecast_ledger.append_event(
                    path, event_type="mlb_shadow_locked", fixture_id=fixture_id,
                    competition="MLB", effective_at=f"2026-07-0{index}T21:00:00Z",
                    identity={"model_version": "candidate-v1", "fixture": fixture_id},
                    payload={"lock": {"kickoff": kickoff}, "participants": {},
                             "baseline": {"home_win_probability": .58,
                                          "model_version": baseline_version,
                                          "model_signal_schema": 7},
                             "candidate": candidate})
                forecast_ledger.append_event(
                    path, event_type="mlb_shadow_graded", fixture_id=fixture_id,
                    competition="MLB", effective_at=f"2026-07-0{index + 1}T03:00:00Z",
                    identity={"lock_event_id": locked["event_id"]},
                    payload={"lock_event_id": locked["event_id"], "result": "h",
                             "score": {"home": 5, "away": 3},
                             "fixture_identity": {"fixture_id": fixture_id,
                                                  "kickoff": kickoff, "participants": {}}})
            with self.assertRaisesRegex(ValueError, "mixed MLB incumbent baseline cohorts"):
                build_report([path])

    def test_reader_rejects_adversarial_grade_identity_time_and_score(self):
        lock_event = event("mlb_shadow_locked", "g1", {
            "lock": {"kickoff": "2026-07-01T23:00:00Z"},
            "participants": {"home": "Alpha", "away": "Beta"},
            "baseline": {"home_win_probability": .58},
            "candidate": {"mode": "prospective_shadow", "production_weight": 0,
                          "model_version": "candidate-v1", "home_win_probability": .62},
        }, "2026-07-01T21:00:00Z")

        def shadow_grade(*, fixture_id="g1", effective_at="2026-07-02T03:00:00Z",
                         result="h", home=5, away=3, identity_fixture="g1"):
            return {"event_type": "mlb_shadow_graded", "fixture_id": fixture_id,
                    "event_id": f"grade-{fixture_id}-{effective_at}-{result}",
                    "effective_at": effective_at,
                    "payload": {"lock_event_id": lock_event["event_id"], "result": result,
                                "score": {"home": home, "away": away},
                                "fixture_identity": {"fixture_id": identity_fixture,
                                                     "kickoff": "2026-07-01T23:00:00Z",
                                                     "participants": {"home": "Alpha", "away": "Beta"}}}}

        rows, counts = extract_rows([lock_event, shadow_grade(fixture_id="reused")])
        self.assertEqual(rows, [])
        self.assertEqual(counts["invalid_grade_fixture_identity"], 1)

        rows, counts = extract_rows([
            lock_event, shadow_grade(effective_at="2026-07-01T22:59:59Z")])
        self.assertEqual(rows, [])
        self.assertEqual(counts["invalid_grade_time"], 1)

        rows, counts = extract_rows([lock_event, shadow_grade(result="a", home=5, away=3)])
        self.assertEqual(rows, [])
        self.assertEqual(counts["score_result_mismatch"], 1)


if __name__ == "__main__":
    unittest.main()
