import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from mlb_model_promotion import apply_mlb_promotion, load_mlb_promotion_policy


def evidence():
    return {
        "schema_version": 1,
        "protocol_version": "mlb-prospective-shadow-1.0.0",
        "status": "ready_for_frozen_review",
        "models": {
            "official": {"n": 500, "log_loss": .69, "brier": .25},
            "run_strength_challenger": {"n": 500, "log_loss": .68, "brier": .24},
        },
        "comparisons": {"run_strength_vs_official": {
            "n": 500, "blocks": 30, "mean_log_loss_delta": -.01,
            "ci95": [-.02, -.001],
        }},
    }


def write_approved_policy(directory: Path, report=None, **updates):
    report_path = directory / "reviewed_evidence.json"
    report_path.write_text(json.dumps(report or evidence(), sort_keys=True), encoding="utf-8")
    policy = {
        "schema_version": 1, "status": "approved_for_capped_production",
        "signal": "run_strength_challenger", "model_version": "frozen-v1",
        "production_weight": .10, "max_shift_points": 3, "allow_pick_flip": False,
        "manual_review": {
            "decision": "passed", "reviewed_at": "2026-09-01T00:00:00Z", "reviewer": "model-review",
            "report": report_path.name, "report_sha256": hashlib.sha256(report_path.read_bytes()).hexdigest(),
        },
    }
    policy.update(updates)
    policy_path = directory / "policy.json"
    policy_path.write_text(json.dumps(policy), encoding="utf-8")
    return policy_path


class MLBModelPromotionTests(unittest.TestCase):
    def test_collecting_policy_is_inactive(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "policy.json"
            path.write_text(json.dumps({"schema_version": 1,
                                        "status": "collecting_prospective_evidence",
                                        "production_weight": 0}), encoding="utf-8")
            self.assertIsNone(load_mlb_promotion_policy(path))

    def test_approved_policy_applies_capped_non_flipping_blend(self):
        with tempfile.TemporaryDirectory() as directory:
            policy = load_mlb_promotion_policy(write_approved_policy(Path(directory)))
            match = {"home": {"name": "Home"}, "away": {"name": "Away"},
                     "mlb_challenger_shadow": {
                         "mode": "prospective_shadow", "production_weight": 0,
                         "model_version": "frozen-v1", "home_win_probability": .90}}
            prediction = {"adjusted": {"h": 60, "d": 0, "a": 40},
                          "regulation_probs": {"h": 60, "d": 0, "a": 40},
                          "pick": "h", "pick_name": "Home", "confidence": 60}
            receipt = apply_mlb_promotion(match, prediction, policy)
            self.assertEqual(prediction["adjusted"], {"h": 63, "d": 0, "a": 37})
            self.assertEqual(prediction["pick"], "h")
            self.assertEqual(receipt["production_weight"], .10)
            self.assertEqual(receipt["applied_shift_points"], 3)

    def test_first_stage_cannot_flip_official_pick(self):
        with tempfile.TemporaryDirectory() as directory:
            policy = load_mlb_promotion_policy(write_approved_policy(Path(directory)))
            match = {"home": {"name": "Home"}, "away": {"name": "Away"},
                     "mlb_challenger_shadow": {
                         "mode": "prospective_shadow", "production_weight": 0,
                         "model_version": "frozen-v1", "home_win_probability": .10}}
            prediction = {"adjusted": {"h": 52, "d": 0, "a": 48}, "pick": "h"}
            apply_mlb_promotion(match, prediction, policy)
            self.assertGreaterEqual(prediction["adjusted"]["h"], 51)
            self.assertEqual(prediction["pick"], "h")

    def test_rejects_evidence_without_significant_improvement(self):
        with tempfile.TemporaryDirectory() as directory:
            report = evidence()
            report["comparisons"]["run_strength_vs_official"]["ci95"] = [-.02, .003]
            with self.assertRaisesRegex(ValueError, "interval"):
                load_mlb_promotion_policy(write_approved_policy(Path(directory), report=report))


if __name__ == "__main__":
    unittest.main()
