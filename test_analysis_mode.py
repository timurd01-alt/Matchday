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
        self.assertIn("DATA=cached?payload:stripPastSeasonCompetitionViews(payload)", panels)

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
        self.assertIn("hideStaleRecord:_v15CompetitionKey(m)==='NCAAF'", cards)
        self.assertIn("teamStandingsMeta(team,comp,{diff:true,form:true,hideStaleRecord:", panels)

    def test_expanded_football_views_hide_prior_season_records(self):
        core = (ROOT / "app-1-core.js").read_text(encoding="utf-8")
        cards = (ROOT / "app-4-features.js").read_text(encoding="utf-8")
        panels = (ROOT / "app-3-panels.js").read_text(encoding="utf-8")
        self.assertIn("opts.hideStaleRecord&&team?.season_stale", core)
        self.assertIn("_v15CompetitionKey(m)==='NCAAF'&&team?.season_stale", cards)
        self.assertIn("hideStaleRecord:String(comp||'').toUpperCase()==='NCAAF'", panels)
        self.assertIn("teamStandingsMeta(m.home,m._comp).map", cards)
        self.assertIn("teamStandingsMeta(m.away,m._comp).map", cards)

    def test_pregame_gaps_explain_source_and_collection_state(self):
        panels = (ROOT / "app-3-panels.js").read_text(encoding="utf-8")
        self.assertIn("Roster profile unavailable", panels)
        css = (ROOT / "styles.css").read_text(encoding="utf-8")
        self.assertIn(".contextAlert{display:grid", css)

    def test_expanded_match_uses_overall_roster_without_box_score_panel(self):
        panels = (ROOT / "app-3-panels.js").read_text(encoding="utf-8")
        features = (ROOT / "app-4-features.js").read_text(encoding="utf-8")
        self.assertIn("function rosterPanel(m)", panels)
        self.assertIn("Overall roster", panels)
        self.assertIn("m.personnel?.depth_chart", panels)
        details = panels[panels.index("function details(m){"):]
        self.assertIn("${rosterPanel(m)}", details)
        self.assertNotIn("${statsPanel(m)}", details)
        self.assertNotIn("${lineupsPanel(m)}", details)
        fallback = features[features.index("function simpleMatchFallbackPanel(m){"):features.index("/* ===== BRACKET V11")]
        self.assertIn("${rosterPanel(m)}", fallback)
        self.assertNotIn("${statsPanel(m)}", fallback)

    def test_neutral_venue_comparison_has_responsive_layout(self):
        css = (ROOT / "styles.css").read_text(encoding="utf-8")
        self.assertIn(".neutralVenueRow{display:grid", css)
        self.assertIn(".hypotheticalTag{display:inline-flex", css)
        self.assertIn("@media(max-width:540px){.neutralVenueBox", css)

    def test_insight_rail_is_removed_to_leave_the_content_full_width(self):
        markup = (ROOT / "index.html").read_text(encoding="utf-8")
        core = (ROOT / "app-1-core.js").read_text(encoding="utf-8")
        self.assertNotIn('id="railToggle"', markup)
        self.assertNotIn('id="insight"', markup)
        self.assertNotIn("function toggleInsightRail()", core)
        self.assertNotIn("function syncRailToggle()", core)

    def test_team_view_title_comes_from_one_helper(self):
        core = (ROOT / "app-1-core.js").read_text(encoding="utf-8")
        views = (ROOT / "app-2-views.js").read_text(encoding="utf-8")
        self.assertIn("function tottTitle()", core)
        self.assertNotIn('<div class="vhead">Team of the Tournament</div>', views)
        self.assertIn("${esc(tottTitle())}", views)

    def test_match_profile_separates_standings_position_from_rank(self):
        source = (ROOT / "app-4-features.js").read_text(encoding="utf-8")
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

    def test_sport_picker_covers_every_published_sport(self):
        """The sport picker must offer exactly what the deploy ships.

        This used to pin the all-sports merge's key list, which is gone with the
        merged board. The invariant survives it: every sport a visitor can
        select has to have a published data file, or picking it takes a 404.
        """
        core = (ROOT / "app-1-core.js").read_text(encoding="utf-8")
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        workflow = (ROOT / ".github" / "workflows" / "deploy.yml").read_text(encoding="utf-8")

        declared = re.search(r"const ALL_SPORT_KEYS=\[([^\]]*)\]", core)
        self.assertIsNotNone(declared, "app-1-core.js must declare ALL_SPORT_KEYS")
        keys = re.findall(r"'([a-z0-9]+)'", declared.group(1))
        self.assertTrue(keys, "ALL_SPORT_KEYS must not be empty")

        picker = re.search(r'<select id="sportSel".*?</select>', html, re.S)
        self.assertIsNotNone(picker, "index.html must have the sport picker")
        offered = re.findall(r'<option value="([a-z0-9]*)"', picker.group(0))
        self.assertEqual(sorted(offered), sorted(keys),
                         "the sport picker and ALL_SPORT_KEYS have drifted")
        self.assertNotIn("", offered,
                         'the picker must not offer an empty value: the merged '
                         '"All college" board it selected no longer exists')

        shipped = re.search(r"for data_file in ((?:data_\w+\.json ?)+); do", workflow)
        self.assertIsNotNone(shipped, "deploy.yml must copy the data files in a loop")
        published = [name[len("data_"):-len(".json")]
                     for name in shipped.group(1).split()]
        self.assertEqual(
            sorted(published), sorted(keys),
            "the sport picker and the deploy allowlist have drifted: every "
            "selectable sport must have a published data file, or visitors "
            "take a 404 when they pick it",
        )

    def test_scheduled_deploy_is_hourly(self):
        workflow = (ROOT / ".github" / "workflows" / "deploy.yml").read_text(encoding="utf-8")
        self.assertIn("cron: '17 * * * *'", workflow)
        self.assertNotIn("cron: '*/15 * * * *'", workflow)


if __name__ == "__main__":
    unittest.main()
