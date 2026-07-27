import unittest

import fetch_data
import mfti_research as mfti


class MftiResearchTests(unittest.TestCase):
    def test_missing_inputs_never_become_confidence(self):
        receipt = mfti.build_shadow_receipt(
            {}, {"adjusted": {"h": 60, "a": 40}}, [], "2026-07-26T12:00:00Z"
        )
        self.assertEqual(receipt["status"], "incomplete")
        self.assertIsNone(receipt["score"])
        self.assertFalse(receipt["affects_prediction"])
        self.assertFalse(receipt["user_visible"])
        self.assertIn("scenario_stability", receipt["missing_components"])

    def test_official_pick_record_contains_non_influential_shadow_receipt(self):
        match = {
            "id": "research-1", "status": "UPCOMING", "stage": "Regular Season",
            "kickoff": "2026-07-26T13:00:00Z", "venue": None,
            "home": {"name": "Alpha"}, "away": {"name": "Beta"},
            "markets": {}, "weather": {}, "injuries": {}, "lineups": None,
        }
        prediction = {
            "pick": "h", "pick_name": "Alpha", "confidence": 60,
            "adjusted": {"h": 60, "d": 0, "a": 40},
            "regulation_probs": {"h": 60, "d": 0, "a": 40},
        }
        decision = {
            "locked_at": fetch_data.datetime.datetime(
                2026, 7, 26, 12, tzinfo=fetch_data.datetime.timezone.utc
            ),
            "lead_seconds": 3600, "status_at_lock": "UPCOMING",
            "reason": "verified_pregame_window",
        }
        record = fetch_data._make_pick_record(match, prediction, {}, decision)
        self.assertIn("mfti_shadow", record)
        self.assertIsNone(record["mfti_shadow"]["score"])
        self.assertFalse(record["mfti_shadow"]["affects_prediction"])
        self.assertEqual(record["prediction_snapshot"], prediction)

    def test_identical_scenarios_are_perfectly_stable(self):
        result = mfti.scenario_stability([
            {"label": "one", "probability": 0.7, "probabilities": {"h": 60, "a": 40}},
            {"label": "two", "probability": 0.3, "probabilities": {"h": 60, "a": 40}},
        ])
        self.assertTrue(result["available"])
        self.assertAlmostEqual(result["score"], 1.0)
        self.assertAlmostEqual(result["maximum_probability_swing"], 0.0)

    def test_scenario_disagreement_reduces_stability(self):
        stable = mfti.scenario_stability([
            {"probabilities": {"h": 55, "a": 45}},
            {"probabilities": {"h": 55, "a": 45}},
        ])
        fragile = mfti.scenario_stability([
            {"probabilities": {"h": 90, "a": 10}},
            {"probabilities": {"h": 10, "a": 90}},
        ])
        self.assertLess(fragile["score"], stable["score"])
        self.assertAlmostEqual(fragile["maximum_probability_swing"], 0.8)

    def test_negative_power_mean_penalizes_weak_link(self):
        components = {
            "scenario_stability": {"available": True, "score": 0.9},
            "availability": {"available": True, "score": 0.2},
            "freshness": {"available": True, "score": 0.9},
            "model_stability": {"available": True, "score": 0.9},
        }
        readiness = mfti.event_readiness(components)
        arithmetic = 0.35 * 0.9 + 0.25 * 0.2 + 0.20 * 0.9 + 0.20 * 0.9
        self.assertTrue(readiness["available"])
        self.assertLess(readiness["score"], arithmetic)

    def test_explicit_inputs_create_event_readiness_but_not_unfitted_final_score(self):
        match = {"mfti_inputs": {
            "scenario_forecasts": [
                {"probability": 0.5, "probabilities": {"h": 60, "a": 40}},
                {"probability": 0.5, "probabilities": {"h": 55, "a": 45}},
            ],
            "availability": [{"importance": 1, "certainty": 0.8}],
            "freshness": [{"importance": 1, "coverage": 1,
                           "age_hours": 1, "half_life_hours": 8}],
            "independent_models": [
                {"family": "one", "independent": True, "probabilities": {"h": 60, "a": 40}},
                {"family": "two", "independent": True, "probabilities": {"h": 58, "a": 42}},
            ],
        }}
        receipt = mfti.build_shadow_receipt(
            match, {"adjusted": {"h": 60, "a": 40}}, [], "2026-07-26T12:00:00Z"
        )
        self.assertTrue(receipt["event_readiness"]["available"])
        self.assertFalse(receipt["historical_evidence"]["available"])
        self.assertIsNone(receipt["score"])


if __name__ == "__main__":
    unittest.main()
