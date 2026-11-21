"""Home's week section (Build 1120A): "Last week" and "Games that matter".

Static checks on app-1-core.js, the way the other Home tests read it. They pin
the rules the section was built on, not its layout.
"""
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _section(core: str, start: str, end: str) -> str:
    return core[core.index(start):core.index(end)]


class HomeWeekTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.core = (ROOT / "app-1-core.js").read_text(encoding="utf-8")
        cls.week = _section(cls.core, "let HOME_WEEK_TAB=", "function gamesFeaturedHTML(")

    def test_home_renders_the_week_before_the_games_summary(self):
        home = _section(self.core, "function renderHome(){", "let HOME_WEEK_TAB=")
        self.assertIn("+homeWeekHTML()", home)
        self.assertLess(home.index("homeWeekHTML()"), home.index("gamesSummaryHTML(active"))
        self.assertIn("homeWeekHydrate()", home)

    def test_recap_hit_rate_always_sits_beside_the_expected_rate(self):
        recap = _section(self.week, "function homeRecapHTML(", "function homeStakesGames(")
        self.assertIn("% of ${d.graded.length} locked picks · ${d.expected.toFixed(0)}% expected", recap)

    def test_recap_reads_the_graded_scorecard_not_a_second_forecast(self):
        data = _section(self.week, "function homeRecapData(", "function homeWeekShowsCalls(")
        self.assertIn("trdlabScorecard()", data)
        for banned in ("predict(", "picks_log", "MATCHDAY_TRDLAB_PICKS"):
            self.assertNotIn(banned, data)

    def test_named_calls_need_a_real_final(self):
        data = _section(self.week, "function homeRecapData(", "function homeWeekShowsCalls(")
        self.assertIn("h+a>0", data)
        for name in ("const best=", "const miss=", "const upsets="):
            line = data[data.index(name):].split("\n", 1)[0]
            self.assertIn("scored", line, name)

    def test_football_stakes_are_labels_from_public_rankings_not_odds(self):
        football = _section(self.week, "function homeFootballStakes(", "async function homeBasketballStakes(")
        self.assertIn("MATCHDAY_CFB_CFP_POLL", football)
        self.assertIn("MATCHDAY_CFB_AP_BRACKET", football)
        self.assertNotIn("to make the playoff", football)
        self.assertNotIn("odds", football.lower())

    def test_ranking_moves_only_belong_to_the_week_they_were_published_in(self):
        fresh = _section(self.week, "function homeRankingsFresh(", "function homeMovers(")
        self.assertIn("pub>=anchor&&pub<anchor+7*86400000", fresh)
        self.assertIn("homeRankingsFresh(t,anchor)", _section(self.week, "function homeMovers(", "function homeYourTeams("))

    def test_default_tab_follows_the_central_weekday(self):
        default = _section(self.week, "function homeWeekDefaultTab(", "function homeWeekTab(")
        self.assertIn("centralDayKey(now)", default)
        self.assertIn("day<=3?'recap':'stakes'", default)

    def test_tabs_are_a_keyboard_tablist(self):
        html = _section(self.week, "function homeWeekHTML(", "function homeWeekHydrate(")
        for needle in ('role="tablist"', 'role="tab"', 'aria-selected=', 'role="tabpanel"', "homeWeekTabKey(event)"):
            self.assertIn(needle, html)


    def test_recap_record_is_a_strip_and_columns_pair_up(self):
        # The record used to be its own column; beside a taller Calls column it
        # left a block of empty space under the Scorecard link.
        recap = _section(self.week, "function homeRecapHTML(", "function homeStakesGames(")
        self.assertIn("homeWeekRecap${single?' single':''}\">${record}", recap)
        self.assertNotIn('<div class="homeWeekCol">${record}', recap)
        self.assertIn("const single=!(calls.length&&moves)", recap)

    def test_side_column_marks_when_best_call_steps_aside(self):
        summary = _section(self.core, "function gamesSummaryHTML(", "function homeLatestReactionHTML(")
        self.assertIn("gamesSideCol${options.hideNotable?' noNotable':''}", summary)

if __name__ == "__main__":
    unittest.main()
