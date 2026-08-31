import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parent


class CommunityPickAvailabilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = (ROOT / "app-2-views.js").read_text(encoding="utf-8")

    def test_model_probabilities_are_the_market_quota_fallback(self):
        self.assertIn("function communityPickProbs(m)", self.source)
        self.assertIn(
            "prediction.regulation_probs||prediction.adjusted||prediction.blend||prediction.model",
            self.source,
        )

    def test_open_picks_do_not_require_a_market(self):
        eligible_filter = next(
            line for line in self.source.splitlines()
            if "const eligible=(DATA.matches||[]).filter" in line
        )
        self.assertNotIn("m.markets", eligible_filter)
        self.assertNotIn("m.prediction", eligible_filter)

    def test_games_open_one_week_before_kickoff(self):
        core = (ROOT / "app-1-core.js").read_text(encoding="utf-8")
        self.assertIn("kickoff-now<=7*864e5", core)

    def test_model_fallback_is_limited_to_the_next_fixture_slate(self):
        self.assertIn("firstKick+4*864e5", self.source)
        self.assertIn(".slice(0,40)", self.source)

    def test_model_only_picks_explain_missing_market_benchmark(self):
        self.assertIn("No bookmaker line is available", self.source)
        self.assertIn("market unavailable", self.source)
        self.assertIn("model pick pending", self.source)


if __name__ == "__main__":
    unittest.main()
