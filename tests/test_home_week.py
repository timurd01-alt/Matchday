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
        data = _section(self.week, "function homeRecapData(", "function homeGradedGame(")
        self.assertIn("trdlabScorecard()", data)
        for banned in ("predict(", "picks_log", "MATCHDAY_TRDLAB_PICKS"):
            self.assertNotIn(banned, data)

    def test_named_calls_need_a_real_final(self):
        data = _section(self.week, "function homeRecapData(", "function homeGradedGame(")
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


    def test_recap_is_a_row_of_tiles_then_ranking_moves(self):
        # Two wide columns left most of each line empty at desktop widths.
        recap = _section(self.week, "function homeRecapHTML(", "function homeStakesGames(")
        self.assertIn('<div class="homeWeekTiles t${tiles.length}" style="--n:${tiles.length}">${tiles.join(' + "''" + ')}</div>${moves}', recap)
        self.assertNotIn("homeWeekCol", recap)

    def test_against_the_market_counts_only_real_disagreements(self):
        # The market made the model's team the underdog: the games that test it.
        data = _section(self.week, "function homeRecapData(", "function homeGradedGame(")
        self.assertIn("const split=graded.filter(r=>homeMarket(r)!=null&&homeMarket(r)<50);", data)
        self.assertIn("const splits=split.filter(scored)", data)
        recap = _section(self.week, "function homeRecapHTML(", "function homeStakesGames(")
        self.assertIn("<span>Against the market</span>", recap)
        # With no priced disagreement that week, the upsets cell stands in.
        self.assertLess(recap.index("if(d.split.length){"), recap.index("if(d.upsets.length)tiles.push("))

    def test_wide_week_cells_carry_more_not_a_gap(self):
        # Wide cells listed one split or one team line with the middle empty.
        recap = _section(self.week, "function homeRecapHTML(", "function homeStakesGames(")
        self.assertIn('<ul class="homeSplits">${d.splits.slice(0,3)', recap)
        self.assertIn("</li>${homeYourNextHTML(y.team)}", recap)
        css = (ROOT / "styles.css").read_text(encoding="utf-8")
        self.assertIn(".homeWeekTile{container-type:inline-size}", css)

    def test_your_team_is_a_cell_of_the_strip_not_a_row(self):
        # One followed team on a row of its own left the rest of the row empty.
        recap = _section(self.week, "function homeRecapHTML(", "function homeStakesGames(")
        self.assertIn('if(yours.length)tiles.push(`<div class="homeWeekTile homeWeekYours">', recap)
        self.assertNotIn("${moves}${mine}", recap)

    def test_stakes_are_a_grid_of_scoreboards(self):
        html = _section(self.week, "function homeStakesRowsHTML(", "function homeWeekHTML(")
        self.assertIn("homeStakesGridOpen(shown.length)", html)
        self.assertIn("result.rows.slice(0,6)", html)
        self.assertIn("homeStakesCardHTML({...r,quiet:true})", html)
        grid = _section(self.week, "function homeStakesGridOpen(", "function homeStakesCardHTML(")
        self.assertIn("n===4?2:Math.max(1,Math.min(3,n))", grid)
        self.assertIn('<div class="homeStakesGrid n${n}" style="--c:${cols}">', grid)
        for builder in ("function homeFootballStakes(", "async function homeBasketballStakes("):
            body = self.week[self.week.index(builder):]
            self.assertIn("teams:", body[:body.index(chr(10) + "}" + chr(10))])

    def test_home_columns_are_balanced_after_every_render(self):
        # A short games list beside a tall side column left ~300px empty.
        home = _section(self.core, "function renderHome(){", "function balanceHomeSupport(")
        self.assertIn("requestAnimationFrame(balanceHomeSupport)", home)
        summary = _section(self.core, "function gamesSummaryHTML(", "function homeLatestReactionHTML(")
        self.assertIn('<div class="gamesSideCol gamesSideSpill"></div>', summary)
        self.assertIn("${gamesNotableHTML()}", summary)

if __name__ == "__main__":
    unittest.main()


class HomeYourTeamTests(unittest.TestCase):
    """The "Your team" tab (Build 1120F)."""

    @classmethod
    def setUpClass(cls):
        core = (ROOT / "app-1-core.js").read_text(encoding="utf-8")
        cls.week = _section(core, "let HOME_WEEK_TAB=", "function gamesFeaturedHTML(")
        cls.yours = _section(cls.week, "function homeOrdinal(", "function homeWeekHTML(")

    def test_tab_is_third_and_the_default_tab_is_unchanged(self):
        self.assertIn("['yours','Your team']]", self.week)
        default = _section(self.week, "function homeWeekDefaultTab(", "function homeWeekTab(")
        self.assertNotIn("yours", default)

    def test_reads_published_data_only(self):
        for banned in ("predict(", "picks_log", "Math.random"):
            self.assertNotIn(banned, self.yours)
        # Neighbours come from the CFP committee ranking and the conference table.
        self.assertIn("MATCHDAY_CFB_CFP_POLL", self.yours)
        self.assertIn("conf?.started", self.yours)

    def test_conference_race_waits_for_conference_play(self):
        spot = _section(self.yours, "function homeConferenceSpot(", "function homeYourTeamData(")
        self.assertIn("(Number(t.cw)||0)+(Number(t.cl)||0)>0", spot)

    def test_watch_list_is_capped_and_excludes_the_teams_own_games(self):
        data = _section(self.yours, "function homeYourTeamData(", "function homeYourChangedHTML(")
        self.assertIn("watch.length>=3", data)
        self.assertIn("!involves(p,name)", data)

    def test_games_to_watch_take_one_of_each_kind_first(self):
        data = _section(self.yours, "function homeYourTeamData(", "function homeYourChangedHTML(")
        for label in ("'Playoff race'", "'Conference race'", "'Future opponent'", "'Past opponent'", "headliner"):
            self.assertIn(label, data)
        self.assertIn("for(const list of kinds){if(watch.length>=3)break;list.some(take)}", data)
        # Never two of a kind.
        self.assertNotIn("while(watch.length<3", data)
        self.assertIn("'Next opponent'", data)
        # The conference race only shows while the team is within a game of the lead.
        self.assertIn("(Number(me.cl)||0)-(Number(lead.cl)||0)<=1", data)

    def test_rating_is_labelled_as_strength_not_resume(self):
        self.assertIn("How good the team is now, not what it has earned.", self.yours)
