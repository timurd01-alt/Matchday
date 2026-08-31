import re
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent


class AnalysisModeTests(unittest.TestCase):
    def test_past_season_tables_and_brackets_are_suppressed(self):
        core = (ROOT / "app-1-core.js").read_text(encoding="utf-8")
        panels = (ROOT / "app-3-panels.js").read_text(encoding="utf-8")
        self.assertIn("function stripPastSeasonCompetitionViews", core)
        self.assertIn("payload.standings=[]", core)
        self.assertIn("payload.bracket=[]", core)
        self.assertIn("payload.bracketology=null", core)
        self.assertIn("DATA=stripPastSeasonCompetitionViews(await r.json())", panels)

    def test_mobile_metric_help_is_tap_safe_and_stays_onscreen(self):
        core = (ROOT / "app-1-core.js").read_text(encoding="utf-8")
        css = (ROOT / "styles.css").read_text(encoding="utf-8")
        self.assertIn('<button type="button" class="metricHelp"', core)
        self.assertIn("aria-expanded=\"false\"", core)
        self.assertIn('aria-controls="metricHelpPopover"', core)
        self.assertIn("function metricHelpPopover()", core)
        self.assertIn("syncMetricHelpPopover(help,open)", core)
        self.assertIn("function closeMetricHelps(except)", core)
        self.assertIn("event.stopImmediatePropagation()", core)
        self.assertIn("},true);", core)
        self.assertIn(".metricHelp.isOpen::after", css)
        self.assertIn(".metricHelp::after{display:none!important}", css)
        self.assertIn(".metricHelpPopover{position:fixed;display:block;left:12px;right:12px", css)
        self.assertIn(".metricHelpPopover[hidden]{display:none}", css)
        self.assertIn("width:28px;height:28px", css)

    def test_sports_without_table_points_show_a_record_instead(self):
        """No US sport awards standings points; "pts" there was wins x 3."""
        core = (ROOT / "app-1-core.js").read_text(encoding="utf-8")
        cards = (ROOT / "app-4-features.js").read_text(encoding="utf-8")
        panels = (ROOT / "app-3-panels.js").read_text(encoding="utf-8")
        self.assertIn("function teamStandingsMeta(team,comp,opts)", core)
        self.assertIn("const TABLE_POINTS_COMPS=new Set(", core)
        # Soccer keeps real table points, and only once a game has been played.
        self.assertIn("Number.isFinite(pts)&&Number(team?.pld)", core)
        # None of the three surfaces may hardcode a pts figure any more.
        for name, source in (("app-4-features.js", cards), ("app-3-panels.js", panels)):
            self.assertNotIn("pts??0} pts", source, f"{name} still prints a fabricated pts value")
        self.assertIn("teamStandingsMeta(m.home,m._comp)", cards)
        self.assertIn("teamStandingsMeta(m.away,m._comp)", cards)
        self.assertIn("hideStaleRecord:['NCAAF','NFL'].includes(_v15CompetitionKey(m))", cards)
        self.assertIn("teamStandingsMeta(team,comp,{diff:true,form:true,hideStaleRecord:", panels)

    def test_expanded_football_views_hide_prior_season_records(self):
        core = (ROOT / "app-1-core.js").read_text(encoding="utf-8")
        cards = (ROOT / "app-4-features.js").read_text(encoding="utf-8")
        panels = (ROOT / "app-3-panels.js").read_text(encoding="utf-8")
        self.assertIn("opts.hideStaleRecord&&team?.season_stale", core)
        self.assertIn("['NCAAF','NFL'].includes(_v15CompetitionKey(m))&&team?.season_stale", cards)
        self.assertIn("hideStaleRecord:['NCAAF','NFL'].includes(String(comp||'').toUpperCase())", panels)
        self.assertIn("teamStandingsMeta(m.home,m._comp).map", cards)
        self.assertIn("teamStandingsMeta(m.away,m._comp).map", cards)

    def test_pregame_gaps_explain_source_and_collection_state(self):
        panels = (ROOT / "app-3-panels.js").read_text(encoding="utf-8")
        self.assertIn("This published snapshot predates pregame-context tracking", panels)
        self.assertIn("No cleared lineup feed for this competition", panels)
        self.assertIn("Provider checked — no confirmed lineup", panels)
        self.assertIn("Injuries inside 72h · lineups inside 2h", panels)
        self.assertIn("Needed before lock", panels)
        self.assertIn("Bullpen workload", panels)
        css = (ROOT / "styles.css").read_text(encoding="utf-8")
        self.assertIn(".bullpenGrid{display:grid", css)
        self.assertIn(".contextAlert{display:grid", css)

    def test_neutral_venue_comparison_has_responsive_layout(self):
        css = (ROOT / "styles.css").read_text(encoding="utf-8")
        self.assertIn(".neutralVenueRow{display:grid", css)
        self.assertIn(".hypotheticalTag{display:inline-flex", css)
        self.assertIn("@media(max-width:540px){.neutralVenueBox", css)

    def test_talent_edge_row_is_never_silently_dropped(self):
        panels = (ROOT / "app-3-panels.js").read_text(encoding="utf-8")
        self.assertIn("const classListed=", panels)
        self.assertIn("if(!classListed){", panels)
        self.assertIn("classMeta.edge_available===false", panels)
        self.assertIn("not scored", panels)
        self.assertIn("classMeta.coverage_label", panels)
        # "level" and "no data" are different claims and must stay distinct.
        self.assertIn("covered?'level':'no data'", panels)

    def test_insight_rail_has_a_visible_collapse_control(self):
        markup = (ROOT / "index.html").read_text(encoding="utf-8")
        core = (ROOT / "app-1-core.js").read_text(encoding="utf-8")
        css = (ROOT / "styles.css").read_text(encoding="utf-8")
        self.assertIn('id="railToggle"', markup)
        self.assertIn('aria-controls="insight"', markup)
        self.assertIn("function toggleInsightRail()", core)
        self.assertIn("function syncRailToggle()", core)
        # Must stay reachable once collapsed, or the rail can't be reopened.
        self.assertIn(".app.noinsight .railToggle{right:0", css)

    def test_leagues_say_team_of_the_season(self):
        core = (ROOT / "app-1-core.js").read_text(encoding="utf-8")
        views = (ROOT / "app-2-views.js").read_text(encoding="utf-8")
        self.assertIn("function tottTitle()", core)
        self.assertIn("'Team of the Season'", core)
        self.assertNotIn('<div class="vhead">Team of the Tournament</div>', views)
        self.assertIn("${esc(tottTitle())}", views)

    def test_match_profile_separates_standings_position_from_rank(self):
        source = (ROOT / "app-4-features.js").read_text(encoding="utf-8")
        self.assertIn("return 'Table position'", source)
        self.assertIn("return 'Division position'", source)
        self.assertIn("return 'Conference position'", source)
        self.assertIn("_v15CompareRow(_v15PlacementLabel(m),_v15Placement(m?.home),_v15Placement(m?.away))", source)
        self.assertIn("_v15CompareRow(_v15RankLabel(m),_v15Num(m?.home?.model_rank)", source)
        self.assertNotIn("model_rank??m?.home?.pos", source)
        self.assertNotIn("model_rank??m?.away?.pos", source)

    def test_live_aggregate_and_live_filter_are_not_rendered(self):
        panels = (ROOT / "app-3-panels.js").read_text(encoding="utf-8")
        self.assertNotIn("more live", panels)
        self.assertNotIn("No live matches", panels)
        self.assertNotIn("_modelFilterBtn('live'", panels)
        self.assertIn("Awaiting final", panels)

    def test_in_progress_cards_hide_partial_scores_without_squeezing_team_names(self):
        core = (ROOT / "app-1-core.js").read_text(encoding="utf-8")
        cards = (ROOT / "app-4-features.js").read_text(encoding="utf-8")
        css = (ROOT / "styles.css").read_text(encoding="utf-8")
        self.assertIn("if(m.status==='LIVE')return'<span class=\"pendingScore\"", core)
        self.assertIn("pending?'AWAITING FINAL'", cards)
        self.assertIn("pending?'score after final'", cards)
        self.assertIn("grid-template-columns:minmax(0,1fr) 64px minmax(0,1fr)", css)
        self.assertIn("-webkit-line-clamp:2", css)
        self.assertNotIn("liveClock(m)</div>", cards)

    def test_scorecard_only_calls_triggered_underdog_profiles_upset_picks(self):
        panels = (ROOT / "app-3-panels.js").read_text(encoding="utf-8")
        self.assertIn("underdog risk · ${name} ${score}/100", panels)
        self.assertIn("upset pick · ${name} ${score}/100", panels)
        self.assertIn("if(!p.upset_triggered)", panels)
        self.assertNotIn('class="scsplit upsetTag">upset ${esc(', panels)

    def test_model_archive_requires_a_verified_locked_snapshot(self):
        panels = (ROOT / "app-3-panels.js").read_text(encoding="utf-8")
        features = (ROOT / "app-4-features.js").read_text(encoding="utf-8")
        self.assertIn("function _modelHasVerifiedLock", panels)
        self.assertIn("m?.prediction?.publication_state==='locked'", panels)
        self.assertIn("m.prediction&&(!_modelIsPast(m)||_modelHasVerifiedLock(m))", panels)
        self.assertIn("Verified locked pregame picks", panels)
        self.assertIn("const eligible=M.filter(m=>!_modelIsPast(m)||_modelHasVerifiedLock(m))", features)

    def test_all_sports_merge_covers_every_published_sport(self):
        """The all-sports load must request exactly what the deploy ships.

        This pinned the literal key list `'nba','mlb','nhl'`, which broke the
        moment NHL was retired -- data_nhl.json is not in the deploy allowlist,
        so asking for it cost every visitor a 404 on every load. Pin the real
        invariant instead: the merge reads one shared key list, and that list
        matches the data files the workflow actually publishes.
        """
        core = (ROOT / "app-1-core.js").read_text(encoding="utf-8")
        panels = (ROOT / "app-3-panels.js").read_text(encoding="utf-8")
        workflow = (ROOT / ".github" / "workflows" / "deploy.yml").read_text(encoding="utf-8")

        self.assertIn("const keys=ALL_SPORT_KEYS;", panels)
        declared = re.search(r"const ALL_SPORT_KEYS=\[([^\]]*)\]", core)
        self.assertIsNotNone(declared, "app-1-core.js must declare ALL_SPORT_KEYS")
        keys = re.findall(r"'([a-z0-9]+)'", declared.group(1))
        self.assertTrue(keys, "ALL_SPORT_KEYS must not be empty")

        shipped = re.search(r"for data_file in ((?:data_\w+\.json ?)+); do", workflow)
        self.assertIsNotNone(shipped, "deploy.yml must copy the data files in a loop")
        published = [name[len("data_"):-len(".json")]
                     for name in shipped.group(1).split()]
        self.assertEqual(
            sorted(published), sorted(keys),
            "the all-sports merge and the deploy allowlist have drifted: "
            "every requested key must have a published data file, or visitors "
            "take a 404 on every load",
        )
        # Retiring a sport from the fetch must not strip its name, so restoring
        # it stays a one-line change rather than a hunt.
        self.assertIn("nhl:'NHL'", core)

    def test_scheduled_deploy_is_hourly(self):
        workflow = (ROOT / ".github" / "workflows" / "deploy.yml").read_text(encoding="utf-8")
        self.assertIn("cron: '17 * * * *'", workflow)
        self.assertNotIn("cron: '*/15 * * * *'", workflow)


if __name__ == "__main__":
    unittest.main()
