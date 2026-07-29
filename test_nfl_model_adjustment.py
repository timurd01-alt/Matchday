import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from nfl_model_adjustment import apply_nfl_adjustment, load_nfl_adjustment_policy


class NFLModelAdjustmentTests(unittest.TestCase):
    def _files(self, directory):
        root = Path(directory)
        report = {"full": {"calibrated_elo": {"n": 844, "log_loss": .6405, "brier": .2242},
                           "raw_elo": {"n": 844, "log_loss": .6525, "brier": .2273},
                           "elo_calibration_paired_bootstrap": {"ci95": [-.023, -.001]}}}
        evidence = (json.dumps(report) + "\n").encode()
        (root / "report.json").write_bytes(evidence)
        policy = {"schema_version": 1, "status": "approved_for_capped_historical_pilot",
                  "signal": "calibrated_elo", "basis": "historical_oos_pilot",
                  "model_version": "frozen-v1", "production_weight": .1,
                  "max_shift_points": 3, "allow_pick_flip": False,
                  "approved_at": "2026-07-29T00:00:00Z", "approved_by": "owner",
                  "prospective_status": "collecting_prospective_evidence",
                  "evidence_report": "report.json", "evidence_sha256": hashlib.sha256(evidence).hexdigest()}
        path = root / "policy.json"
        path.write_text(json.dumps(policy), encoding="utf-8")
        return path

    def test_applies_only_ten_percent_and_cannot_flip_pick(self):
        with tempfile.TemporaryDirectory() as directory:
            policy = load_nfl_adjustment_policy(self._files(directory))
            match = {"kickoff": "2026-09-10T00:00:00Z",
                     "home": {"name": "Home"}, "away": {"name": "Away"},
                     "nfl_challenger_shadow": {"mode": "research_only", "production_weight": 0,
                         "model_version": "frozen-v1", "elo_calibration_status": "eligible_for_prospective_shadow",
                         "calibrated_elo_home_probability": .80}}
            prediction = {"adjusted": {"h": 48, "d": 0, "a": 52}, "pick": "a"}
            receipt = apply_nfl_adjustment(match, prediction, policy)
            self.assertEqual(prediction["adjusted"], {"h": 49, "d": 0, "a": 51})
            self.assertEqual(prediction["pick"], "a")
            self.assertEqual(receipt["production_weight"], .1)
            self.assertEqual(receipt["promotion_basis"], "historical_oos_pilot")

    def test_tampered_evidence_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self._files(directory)
            (Path(directory) / "report.json").write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                load_nfl_adjustment_policy(path)


if __name__ == "__main__":
    unittest.main()
