import json
import tempfile
import unittest
from pathlib import Path

from nfl_challenger import FEATURE_NAMES, MODEL_VERSION
from nfl_challenger_store import attach_nfl_challenger_shadows, load_artifact


def summary(value):
    return {"off_epa": value, "success_rate": 0.5, "explosive_rate": 0.1,
            "pass_epa": value, "rush_epa": value, "neutral_epa": value,
            "early_down_epa": value, "cpoe": value, "sack_rate": 0.05,
            "redzone_td_rate": 0.55, "seconds_per_play": 28, "special_teams_epa": 0.0}


def artifact():
    return {
        "schema_version": 1, "model_version": MODEL_VERSION, "source": "nflverse-data pbp release",
        "research_only": True, "shadow_only": True, "production_weight": 0,
        "espn_origin_excluded": True, "promotion_status": "unvalidated_shadow_challenger",
        "elo_calibration_gate": {"decision": "eligible_for_prospective_shadow"},
        "model": {"feature_names": FEATURE_NAMES, "means": {name: 0 for name in FEATURE_NAMES},
                  "scales": {name: 1 for name in FEATURE_NAMES}, "intercept": 0,
                  "coefficients": {name: 0 for name in FEATURE_NAMES}},
        "elo_calibrator": {"feature_names": ["elo_logit"], "means": {"elo_logit": 0},
                           "scales": {"elo_logit": 1}, "intercept": 0,
                           "coefficients": {"elo_logit": 1}},
        "state": {"rolling_games": 16, "trained_through": "2025-12-31",
                  "elo": {"SEA": 1550, "NE": 1500},
                  "last_played": {"SEA": "2025-12-31", "NE": "2025-12-31"},
                  "team_games": {
                      "SEA": [{**summary(0.2), "opponent": "NE", "game_date": "2025-12-31"}],
                      "NE": [{**summary(-0.1), "opponent": "SEA", "game_date": "2025-12-31"}],
                  }},
    }


class NFLChallengerStoreTests(unittest.TestCase):
    def test_attaches_only_to_future_fixture_and_never_changes_prediction(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "model.json"
            path.write_text(json.dumps(artifact()), encoding="utf-8")
            match = {"kickoff": "2026-09-10T00:20:00Z", "status": "UPCOMING",
                     "home": {"name": "Seattle Seahawks"}, "away": {"name": "New England Patriots"},
                     "prediction": {"model": {"h": 60, "a": 40}}}
            before = json.loads(json.dumps(match["prediction"]))
            result = attach_nfl_challenger_shadows([match], path)
            self.assertEqual(result["matches"], 1)
            self.assertEqual(match["prediction"], before)
            self.assertEqual(match["nfl_challenger_shadow"]["production_weight"], 0)
            self.assertIn("quarterback_assumptions", match["nfl_challenger_shadow"])
            self.assertEqual(match["nfl_challenger_shadow"]["elo_calibration_status"],
                             "eligible_for_prospective_shadow")
            self.assertFalse(match["nfl_challenger_shadow"]["quarterback_assumptions"]["home"]["availability_confirmed"])
            self.assertGreaterEqual(match["nfl_challenger_shadow"]["quarterback_assumptions"]["home"]["effective_uncertainty"], 0.75)
            self.assertIn("offseason_roster_and_qb_changes_not_modeled",
                          match["nfl_challenger_shadow"]["uncertainty_flags"])

    def test_rejects_nonzero_production_weight(self):
        payload = artifact(); payload["production_weight"] = 0.1
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "model.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaises(ValueError):
                load_artifact(path)

    def test_provider_code_alias_falls_back_to_full_name(self):
        payload = artifact()
        payload["state"]["team_games"]["LA"] = payload["state"]["team_games"].pop("SEA")
        payload["state"]["elo"]["LA"] = payload["state"]["elo"].pop("SEA")
        payload["state"]["last_played"]["LA"] = payload["state"]["last_played"].pop("SEA")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "model.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            match = {"kickoff": "2026-09-10T00:20:00Z", "status": "UPCOMING",
                     "home": {"code": "LAR", "name": "Los Angeles Rams"},
                     "away": {"code": "NE", "name": "New England Patriots"}}
            self.assertEqual(attach_nfl_challenger_shadows([match], path)["matches"], 1)


if __name__ == "__main__":
    unittest.main()
