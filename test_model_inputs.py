import unittest

import fetch_data


def finished(mid, home, away, hs, aps):
    return {
        "id": mid, "status": "FINISHED", "kickoff": "2026-01-01T00:00:00Z",
        "home": {"name": home}, "away": {"name": away},
        "score": {"home": hs, "away": aps},
    }


class ModelInputTests(unittest.TestCase):
    def setUp(self):
        self.old_key = fetch_data.COMP_KEY
        self.old_comp = fetch_data.COMP
        fetch_data.COMP_KEY = "NCAAM"
        fetch_data.COMP = dict(fetch_data.COMPETITIONS["NCAAM"])

    def tearDown(self):
        fetch_data.COMP_KEY = self.old_key
        fetch_data.COMP = self.old_comp

    def test_cached_results_are_backfilled_with_winners(self):
        matches = [finished("one", "Alpha", "Beta", 80, 72)]
        fetch_data.normalize_match_results(matches)
        self.assertEqual(matches[0]["score"]["winner"], "h")

    def test_srs_adjusts_margin_for_opponent_strength(self):
        matches = [
            finished("one", "Alpha", "Beta", 80, 70),
            finished("two", "Beta", "Gamma", 80, 70),
            finished("three", "Alpha", "Gamma", 80, 70),
        ]
        fetch_data.normalize_match_results(matches)
        ratings = fetch_data.compute_srs(matches)
        self.assertGreater(ratings["alpha"]["rating"], ratings["beta"]["rating"])
        self.assertGreater(ratings["beta"]["rating"], ratings["gamma"]["rating"])

    def test_rest_days_uses_training_history_beyond_the_display_window(self):
        # The team's only past game is 10 days before kickoff -- outside a
        # narrow ~1-week display window, but present in the wider training set.
        training = [{"kickoff": "2026-01-01T00:00:00Z", "status": "FINISHED",
                     "home": {"name": "Alpha"}, "away": {"name": "Zeta"}}]
        upcoming = {"kickoff": "2026-01-11T00:00:00Z", "status": "UPCOMING",
                    "home": {"name": "Alpha"}, "away": {"name": "Beta"}}
        matches = [upcoming]  # the Jan-1 game is NOT in the narrow display list
        fetch_data.compute_rest(matches, training)
        self.assertEqual(upcoming["home"]["rest_days"], 10)

    def test_rest_days_falls_back_to_matches_when_no_training_set_given(self):
        matches = [
            {"kickoff": "2026-01-01T00:00:00Z", "status": "FINISHED",
             "home": {"name": "Alpha"}, "away": {"name": "Zeta"}},
            {"kickoff": "2026-01-05T00:00:00Z", "status": "UPCOMING",
             "home": {"name": "Alpha"}, "away": {"name": "Beta"}},
        ]
        fetch_data.compute_rest(matches)
        self.assertEqual(matches[1]["home"]["rest_days"], 4)

    def test_american_prediction_reports_sample_and_native_factors(self):
        home = {"name": "Test Alpha", "pld": 12, "w": 9, "l": 3,
                "win_pct": .75, "gf": 960, "ga": 840, "form": "W W L W W",
                "srs": 8.0, "srs_games": 12}
        away = {"name": "Test Beta", "pld": 12, "w": 6, "l": 6,
                "win_pct": .5, "gf": 870, "ga": 870, "form": "L W L W L",
                "srs": 0.0, "srs_games": 12}
        prediction = fetch_data.predict(home, away, {})
        self.assertEqual(prediction["data_quality"]["games"], {"home": 12, "away": 12})
        self.assertIn("record", prediction["why"])
        self.assertIn("margin", prediction["why"])
        self.assertIn("srs", prediction["why"])
        self.assertNotIn("gd", prediction["why"])


if __name__ == "__main__":
    unittest.main()
