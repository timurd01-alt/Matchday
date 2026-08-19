import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from mlb_model_promotion import apply_mlb_promotion, load_mlb_promotion_policy


COHORT = {
    "model_version": "frozen-v1",
    "trained_through": "2025-09-28",
    "artifact_sha256": "a" * 64,
    "feature_schema_version": "mlb-run-strength-features-1.0.0",
    "transformation_version": "mlb-run-strength-transform-1.0.0",
}
BASELINE_COHORT = {"model_version": "official-v1", "model_signal_schema": 7}


def evidence():
    rows = [{
        **COHORT,
        "fixture_id": f"mlb-{index}",
        "lock_event_id": f"lock-{index}",
        "grade_event_id": f"grade-{index}",
        "date_block": f"2026-07-{(index % 30) + 1:02d}",
        "home_win": 1,
        "official_home_probability": .60,
        "challenger_home_probability": .80,
        "capped_blend_home_probability": .62,
        "baseline_model_version": BASELINE_COHORT["model_version"],
        "baseline_model_signal_schema": BASELINE_COHORT["model_signal_schema"],
    } for index in range(500)]
    return {
        "schema_version": 1,
        "protocol_version": "mlb-prospective-shadow-1.0.0",
        "status": "ready_for_frozen_review",
        "cohort": dict(COHORT),
        "baseline_cohort": dict(BASELINE_COHORT),
        "deployment_evaluation": {
            "policy": {"production_weight": .10, "max_shift_points": 3,
                       "allow_pick_flip": False, "probability_rounding": "none"},
            "models": {
                "official": {"n": 500, "log_loss": .510826, "brier": .16},
                "capped_blend": {"n": 500, "log_loss": .478036, "brier": .1444},
            },
            "comparisons": {"capped_blend_vs_official": {
                "n": 500, "blocks": 30, "mean_log_loss_delta": -.03279,
                "ci95": [-.03279, -.03279],
            }},
        },
        # Raw challenger results are informative but are never the promotion target.
        "models": {"run_strength_challenger": {"n": 500, "log_loss": .60, "brier": .20}},
        "rows": rows,
    }


def write_approved_policy(directory: Path, report=None, **updates):
    report_path = directory / "reviewed_evidence.json"
    report_path.write_text(json.dumps(report or evidence(), sort_keys=True), encoding="utf-8")
    policy = {
        "schema_version": 1, "status": "approved_for_capped_production",
        "signal": "run_strength_challenger", **COHORT,
        "baseline_cohort": dict(BASELINE_COHORT),
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


def live_match(home_probability=.90, **cohort_updates):
    cohort = dict(COHORT)
    cohort.update(cohort_updates)
    return {"home": {"name": "Home"}, "away": {"name": "Away"},
            "mlb_challenger_shadow": {
                "mode": "prospective_shadow", "production_weight": 0,
                "home_win_probability": home_probability, **cohort}}


class MLBModelPromotionTests(unittest.TestCase):
    def test_collecting_policy_is_inactive(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "policy.json"
            path.write_text(json.dumps({"schema_version": 1,
                                        "status": "collecting_prospective_evidence",
                                        "production_weight": 0}), encoding="utf-8")
            self.assertIsNone(load_mlb_promotion_policy(path))

    def test_approved_policy_applies_exact_capped_non_flipping_blend(self):
        with tempfile.TemporaryDirectory() as directory:
            policy = load_mlb_promotion_policy(write_approved_policy(Path(directory)))
            prediction = {"adjusted": {"h": 60, "d": 0, "a": 40}, "pick": "h"}
            receipt = apply_mlb_promotion(live_match(), prediction, policy)
            self.assertEqual(prediction["adjusted"], {"h": 63.0, "d": 0, "a": 37.0})
            self.assertEqual(prediction["pick"], "h")
            self.assertEqual(receipt["applied_shift_points"], 3.0)

    def test_final_float_probability_never_rounds_past_cap(self):
        with tempfile.TemporaryDirectory() as directory:
            policy = load_mlb_promotion_policy(write_approved_policy(Path(directory)))
            prediction = {"adjusted": {"h": 60.49, "d": 0, "a": 39.51}, "pick": "h"}
            receipt = apply_mlb_promotion(live_match(.99), prediction, policy)
            self.assertAlmostEqual(prediction["adjusted"]["h"], 63.49)
            self.assertLessEqual(abs(receipt["applied_shift_points"]), 3.0)

    def test_first_stage_cannot_flip_close_away_pick(self):
        with tempfile.TemporaryDirectory() as directory:
            policy = load_mlb_promotion_policy(write_approved_policy(Path(directory)))
            prediction = {"adjusted": {"h": 49.9, "d": 0, "a": 50.1}, "pick": "a"}
            receipt = apply_mlb_promotion(live_match(.99), prediction, policy)
            self.assertLess(prediction["adjusted"]["h"], 50)
            self.assertEqual(prediction["pick"], "a")
            self.assertLessEqual(abs(receipt["applied_shift_points"]), 3.0)

    def test_rejects_mixed_report_cohorts(self):
        with tempfile.TemporaryDirectory() as directory:
            report = evidence()
            report["rows"][271]["artifact_sha256"] = "b" * 64
            with self.assertRaisesRegex(ValueError, "row 271.*cohort"):
                load_mlb_promotion_policy(write_approved_policy(Path(directory), report=report))

    def test_rejects_report_cohort_different_from_policy(self):
        with tempfile.TemporaryDirectory() as directory:
            report = evidence()
            report["cohort"]["transformation_version"] = "other-transform"
            with self.assertRaisesRegex(ValueError, "evidence cohort"):
                load_mlb_promotion_policy(write_approved_policy(Path(directory), report=report))

    def test_rejects_report_for_different_incumbent_baseline(self):
        with tempfile.TemporaryDirectory() as directory:
            report = evidence()
            report["baseline_cohort"]["model_version"] = "official-v2"
            with self.assertRaisesRegex(ValueError, "baseline cohort.*approved incumbent"):
                load_mlb_promotion_policy(write_approved_policy(Path(directory), report=report))

    def test_rejects_row_from_mixed_incumbent_baseline(self):
        with tempfile.TemporaryDirectory() as directory:
            report = evidence()
            report["rows"][319]["baseline_model_signal_schema"] = 8
            with self.assertRaisesRegex(ValueError, "row 319.*incumbent baseline cohort"):
                load_mlb_promotion_policy(write_approved_policy(Path(directory), report=report))

    def test_rejects_policy_without_exact_incumbent_baseline_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "baseline model_version"):
                load_mlb_promotion_policy(write_approved_policy(
                    Path(directory), baseline_cohort={"model_signal_schema": 7}))

    def test_rejects_raw_challenger_win_when_deployable_blend_loses(self):
        with tempfile.TemporaryDirectory() as directory:
            report = evidence()
            report["deployment_evaluation"]["models"]["capped_blend"]["brier"] = .251
            with self.assertRaisesRegex(ValueError, "capped-blend summary brier"):
                load_mlb_promotion_policy(write_approved_policy(Path(directory), report=report))

    def test_rejects_evidence_for_different_deployment_cap(self):
        with tempfile.TemporaryDirectory() as directory:
            report = evidence()
            report["deployment_evaluation"]["policy"]["max_shift_points"] = 2
            with self.assertRaisesRegex(ValueError, "exact deployable"):
                load_mlb_promotion_policy(write_approved_policy(Path(directory), report=report))

    def test_rejects_whole_percent_rounded_deployment_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            report = evidence()
            report["deployment_evaluation"]["policy"]["probability_rounding"] = "whole percent"
            with self.assertRaisesRegex(ValueError, "exact deployable"):
                load_mlb_promotion_policy(write_approved_policy(Path(directory), report=report))

    def test_rejects_evidence_without_significant_capped_blend_improvement(self):
        with tempfile.TemporaryDirectory() as directory:
            report = evidence()
            report["deployment_evaluation"]["comparisons"]["capped_blend_vs_official"]["ci95"] = [-.02, .003]
            with self.assertRaisesRegex(ValueError, "CI.*immutable evidence rows"):
                load_mlb_promotion_policy(write_approved_policy(Path(directory), report=report))

    def test_rejects_ready_status_with_rows_missing_outcomes_and_probabilities(self):
        with tempfile.TemporaryDirectory() as directory:
            report = evidence()
            report["rows"][17].pop("home_win")
            report["rows"][17].pop("official_home_probability")
            with self.assertRaisesRegex(ValueError, "row 17.*outcome"):
                load_mlb_promotion_policy(write_approved_policy(Path(directory), report=report))

    def test_rejects_fabricated_row_level_capped_probability(self):
        with tempfile.TemporaryDirectory() as directory:
            report = evidence()
            report["rows"][42]["capped_blend_home_probability"] = .61
            with self.assertRaisesRegex(ValueError, "row 42.*fabricated"):
                load_mlb_promotion_policy(write_approved_policy(Path(directory), report=report))

    def test_rejects_duplicate_immutable_event_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            report = evidence()
            report["rows"][1]["lock_event_id"] = report["rows"][0]["lock_event_id"]
            with self.assertRaisesRegex(ValueError, "row 1.*duplicates"):
                load_mlb_promotion_policy(write_approved_policy(Path(directory), report=report))

    def test_rejects_truthful_summary_when_deployable_rows_lose(self):
        with tempfile.TemporaryDirectory() as directory:
            report = evidence()
            for row in report["rows"]:
                row["home_win"] = 0
            deployment = report["deployment_evaluation"]
            deployment["models"]["official"].update(log_loss=.916291, brier=.36)
            deployment["models"]["capped_blend"].update(log_loss=.967584, brier=.3844)
            comparison = deployment["comparisons"]["capped_blend_vs_official"]
            comparison.update(mean_log_loss_delta=.051293, ci95=[.051293, .051293])
            with self.assertRaisesRegex(ValueError, "interval does not beat"):
                load_mlb_promotion_policy(write_approved_policy(Path(directory), report=report))

    def test_rejects_live_shadow_from_different_artifact(self):
        with tempfile.TemporaryDirectory() as directory:
            policy = load_mlb_promotion_policy(write_approved_policy(Path(directory)))
            prediction = {"adjusted": {"h": 60, "d": 0, "a": 40}, "pick": "h"}
            with self.assertRaisesRegex(ValueError, "live MLB shadow.*cohort"):
                apply_mlb_promotion(live_match(artifact_sha256="b" * 64), prediction, policy)


class CheckedInCohortIdentityTests(unittest.TestCase):
    """The frozen cohort must name the artifact this repository actually ships.

    mlb_model_promotion.json froze the CRLF rendering of the challenger
    artifact -- a hash produced by a Windows checkout under core.autocrlf --
    while mlb_challenger_store.py hashes raw bytes and CI checks the file out
    with LF. The two never matched, so `exact_cohort_required` was
    unsatisfiable and the gate accumulated prospective evidence that its own
    rule would have thrown away. .gitattributes now pins eol=lf; this test is
    what makes that stick, and it fails on any platform where it stops being
    true rather than waiting for a promotion review to discover it.
    """

    ROOT = Path(__file__).parent

    def test_policy_hash_matches_the_artifact_on_disk(self):
        policy = json.loads(
            (self.ROOT / "mlb_model_promotion.json").read_text(encoding="utf-8"))
        artifact = self.ROOT / "mlb_run_strength_model_v1.json"
        self.assertEqual(
            policy["artifact_sha256"],
            hashlib.sha256(artifact.read_bytes()).hexdigest(),
            "mlb_model_promotion.json's frozen artifact_sha256 does not match "
            "mlb_run_strength_model_v1.json as checked out here. If this fails "
            "on Windows, confirm .gitattributes is in effect and re-check the "
            "file out; do NOT edit the policy to match a local rendering.")

    def test_artifact_has_no_carriage_returns(self):
        """The condition the hash mismatch was a symptom of, asserted directly
        so the cause is named rather than only its consequence."""
        raw = (self.ROOT / "mlb_run_strength_model_v1.json").read_bytes()
        self.assertNotIn(b"\r\n", raw)


if __name__ == "__main__":
    unittest.main()
