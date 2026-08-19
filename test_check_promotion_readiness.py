import json
import tempfile
import unittest
from pathlib import Path

from check_promotion_readiness import GATES, build_report, evaluate_gate


GATE = {
    "id": "test-gate", "sport": "mlb",
    "policy_path": "policy.json", "scorecard_path": "scorecard.json",
    "candidate_model": "capped_blend", "baseline_model": "official",
    "comparison_path": ("deployment_evaluation", "comparisons", "capped_blend_vs_official"),
    "block_minimum_key": "minimum_game_date_blocks", "block_unit": "game-date blocks",
    "policy_status_key": "status",
}


def policy(**overrides):
    base = {
        "status": "collecting_prospective_evidence",
        "model_version": "frozen-v1", "trained_through": "2025-09-28",
        "artifact_sha256": "abc", "feature_schema_version": 1,
        "transformation_version": "t1",
        "baseline_cohort": {"model_version": "v6-calibrated", "model_signal_schema": 8},
        "requirements": {
            "minimum_games": 500, "minimum_game_date_blocks": 30,
            "exact_cohort_required": ["model_version", "artifact_sha256"],
            "exact_incumbent_baseline_required": ["model_version", "model_signal_schema"],
            "paired_interval_upper_bound_below_zero": True,
            "brier_must_improve": True, "manual_review_required": True,
        },
    }
    base.update(overrides)
    return base


def scorecard(*, games=500, blocks=30, upper=-0.01, candidate_brier=.20, baseline_brier=.23,
              artifact="abc", baseline_version="v6-calibrated"):
    return {
        "status": "ready_for_frozen_review",
        "evaluation_contract": {"minimum_games": 500, "minimum_game_date_blocks": 30},
        "cohort": {"model_version": "frozen-v1", "trained_through": "2025-09-28",
                   "artifact_sha256": artifact, "feature_schema_version": 1,
                   "transformation_version": "t1"},
        "baseline_cohort": {"model_version": baseline_version, "model_signal_schema": 8},
        "models": {"capped_blend": {"n": games, "brier": candidate_brier},
                   "official": {"n": games, "brier": baseline_brier}},
        "deployment_evaluation": {"comparisons": {"capped_blend_vs_official": {
            "n": games, "blocks": blocks, "ci95": [-0.05, upper]}}},
    }


class PromotionReadinessTest(unittest.TestCase):
    def evaluate(self, policy_payload, scorecard_payload):
        with tempfile.TemporaryDirectory() as root:
            base = Path(root)
            if policy_payload is not None:
                (base / "policy.json").write_text(json.dumps(policy_payload), encoding="utf-8")
            if scorecard_payload is not None:
                (base / "scorecard.json").write_text(json.dumps(scorecard_payload),
                                                     encoding="utf-8")
            return evaluate_gate(GATE, base)

    def test_all_requirements_met_stops_at_manual_review(self):
        result = self.evaluate(policy(), scorecard())
        self.assertEqual(result["state"], "ready_for_manual_review")
        self.assertFalse(result["auto_promotion"])

    def test_manual_review_waived_reports_ready(self):
        payload = policy()
        payload["requirements"]["manual_review_required"] = False
        self.assertEqual(self.evaluate(payload, scorecard())["state"], "ready")

    def test_short_sample_is_collecting_with_the_remaining_count(self):
        result = self.evaluate(policy(), scorecard(games=120, blocks=8))
        self.assertEqual(result["state"], "collecting")
        self.assertEqual(result["progress"]["games"]["short"], 380)
        self.assertEqual(result["progress"]["blocks"]["short"], 22)

    def test_cohort_drift_blocks_rather_than_collects(self):
        result = self.evaluate(policy(), scorecard(artifact="different"))
        self.assertEqual(result["state"], "blocked")
        check = next(item for item in result["checks"]
                     if item["check"] == "exact_cohort_required")
        self.assertIn("artifact_sha256", check["mismatches"][0])

    def test_incumbent_baseline_drift_blocks(self):
        result = self.evaluate(policy(), scorecard(baseline_version="v5-settlement-aware"))
        self.assertEqual(result["state"], "blocked")

    def test_interval_above_zero_is_evidence_against(self):
        result = self.evaluate(policy(), scorecard(upper=0.004))
        self.assertEqual(result["state"], "evidence_against")

    def test_worse_brier_is_evidence_against(self):
        result = self.evaluate(policy(), scorecard(candidate_brier=.24))
        self.assertEqual(result["state"], "evidence_against")

    def test_pending_sample_outranks_a_failing_interval(self):
        """A losing interval on 40 of 500 fixtures is not yet evidence against anything."""
        result = self.evaluate(policy(), scorecard(games=40, blocks=3, upper=0.5))
        self.assertEqual(result["state"], "collecting")

    def test_blocked_outranks_pending_sample(self):
        result = self.evaluate(policy(), scorecard(games=40, blocks=3, artifact="different"))
        self.assertEqual(result["state"], "blocked")

    def test_missing_scorecard_is_reported_not_raised(self):
        result = self.evaluate(policy(), None)
        self.assertEqual(result["state"], "evidence_missing")

    def test_missing_policy_is_reported_not_raised(self):
        self.assertEqual(self.evaluate(None, scorecard())["state"], "policy_missing")

    def test_unobservable_cohort_is_collecting_not_blocked(self):
        payload = scorecard()
        payload["cohort"]["artifact_sha256"] = None
        self.assertEqual(self.evaluate(policy(), payload)["state"], "collecting")

    def test_requirements_fall_back_to_the_scorecard_contract(self):
        """The NFL policy states no requirements block; the contract supplies the bar."""
        payload = policy()
        del payload["requirements"]
        result = self.evaluate(payload, scorecard(games=100, blocks=4))
        self.assertEqual(result["state"], "collecting")
        self.assertEqual(result["progress"]["games"]["required"], 500)

    def test_report_never_advertises_auto_promotion(self):
        with tempfile.TemporaryDirectory() as root:
            report = build_report(root)
        self.assertFalse(report["auto_promotion"])
        self.assertEqual(report["overall_state"], "policy_missing")

    def test_configured_gates_point_at_real_policy_files(self):
        for gate in GATES:
            self.assertTrue(Path(gate["policy_path"]).is_file(), gate["policy_path"])


if __name__ == "__main__":
    unittest.main()
