import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parent


class CommunityPickAvailabilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = (ROOT / "app-2-views.js").read_text(encoding="utf-8")

    def test_probabilities_come_from_bet_better_sides_not_market(self):
        self.assertIn("function communityPickProbs(m)", self.source)
        self.assertIn("betbetterReadFor(m)", self.source)
        self.assertIn("home?.model_pct!=null&&away?.model_pct!=null", self.source)
        self.assertNotIn("function communityMarketProbs", self.source)

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

    def test_model_only_picks_are_labeled_live_and_not_certain(self):
        self.assertIn("Bet Better live model", self.source)
        self.assertIn("communityModelPctLabel(pct)", self.source)
        self.assertIn("Bet Better probabilities pending", self.source)

    def test_todays_call_is_removed(self):
        self.assertNotIn("Today's call", self.source)
        self.assertNotIn("btmChallenge", self.source)

    def test_new_pick_snapshots_bet_better_side(self):
        core = (ROOT / "app-1-core.js").read_text(encoding="utf-8")
        self.assertIn("modelPick:read?.pick||null", core)
        self.assertIn("Math.min(99.9,n)", core)

    def test_research_top_pick_stays_in_current_week(self):
        self.assertIn("const thisWeek=kickoff=>", self.source)
        self.assertIn("m.betbetter_pick&&thisWeek(m.kickoff)", self.source)
        self.assertIn(".filter(p=>thisWeek(p.kickoff))", self.source)

    def test_community_pick_rows_show_school_marks(self):
        self.assertIn("${teamMark(m.home.name)}", self.source)
        self.assertIn("${teamMark(m.away.name)}", self.source)


if __name__ == "__main__":
    unittest.main()
