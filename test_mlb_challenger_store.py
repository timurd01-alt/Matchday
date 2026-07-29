import json
import tempfile
import unittest
from pathlib import Path

from mlb_challenger import MODEL_VERSION
from mlb_challenger_store import attach_mlb_challenger_shadows, load_artifact


def artifact():
    return {
        "schema_version": 1, "model_version": MODEL_VERSION,
        "research_only": True, "shadow_only": True, "production_weight": 0,
        "source": {"notice": "The information used here was obtained free of charge from and is copyrighted by Retrosheet."},
        "historical_validation": {"decision": "eligible_for_prospective_shadow"},
        "promotion_status": "eligible_for_prospective_shadow_not_production",
        "trained_through": "2025-09-28",
        "model": {"feature_names": ["pythagorean_diff", "run_diff_per_game_diff"],
                  "means": {"pythagorean_diff": 0, "run_diff_per_game_diff": 0},
                  "scales": {"pythagorean_diff": .1, "run_diff_per_game_diff": 1},
                  "intercept": .1, "coefficients": {"pythagorean_diff": .2, "run_diff_per_game_diff": .1},
                  "baseline_probability_key": None},
    }


class MlbChallengerStoreTests(unittest.TestCase):
    def test_attaches_only_as_zero_weight_shadow(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "model.json"
            path.write_text(json.dumps(artifact()), encoding="utf-8")
            matches = [{"status": "UPCOMING",
                        "home": {"pld": 50, "gf": 260, "ga": 210},
                        "away": {"pld": 50, "gf": 210, "ga": 260}}]
            result = attach_mlb_challenger_shadows(matches, path)
            self.assertEqual(result["matches"], 1)
            shadow = matches[0]["mlb_challenger_shadow"]
            self.assertEqual(shadow["production_weight"], 0)
            self.assertGreater(shadow["home_win_probability"], .5)
            self.assertIn("probable_or_confirmed_starter", shadow["missing_personnel"])

    def test_rejects_nonzero_weight(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "model.json"
            payload = artifact(); payload["production_weight"] = .1
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaises(ValueError):
                load_artifact(path)


if __name__ == "__main__":
    unittest.main()
