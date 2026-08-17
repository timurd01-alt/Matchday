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

    def test_champions_league_uses_its_own_knockout_shape(self):
        cards = (ROOT / "app-4-features.js").read_text(encoding="utf-8")
        panels = (ROOT / "app-3-panels.js").read_text(encoding="utf-8")
        self.assertIn("function _renderUCLBracket", cards)
        self.assertIn("['Knockout phase play-offs','Round of 16','Quarter-finals','Semi-finals','Final']", cards)
        self.assertIn("if(DATA.comp_key==='UCL'){_renderUCLBracket(host);return}", cards)
        self.assertIn("function _renderUCLLeagueTable", panels)
        self.assertIn("No current league-phase standings yet", panels)
        self.assertIn("eight league-phase matches each", panels)
        renderer = cards.split("function _renderUCLBracket", 1)[1].split("function renderBracket", 1)[0]
        self.assertNotIn("Round of 32", renderer)
        self.assertNotIn("Third-place playoff", renderer)

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

    def test_public_shell_promises_pregame_and_postgame_analysis(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        content = (ROOT / "content.html").read_text(encoding="utf-8")
        manifest = (ROOT / "manifest.json").read_text(encoding="utf-8")
        public_copy = "\n".join((html, content, manifest)).lower()
        self.assertIn("Sports Predictions &amp; Matchup Analysis", html)
        self.assertIn("Pregame model picks, probability forecasts, matchup analysis", html)
        self.assertIn("Sports Prediction Recaps &amp; Analysis", content)
        for unsupported_promise in (
            "live scores", "live scoreboard", "real-time scores", "live feed"
        ):
            self.assertNotIn(unsupported_promise, public_copy)

    def test_content_rewind_uses_locked_receipts_and_renders_every_filter_change(self):
        html = (ROOT / "content.html").read_text(encoding="utf-8")
        js = (ROOT / "content.js").read_text(encoding="utf-8")
        css = (ROOT / "content.css").read_text(encoding="utf-8")
        scheduler = (ROOT / "multi_fetch.py").read_text(encoding="utf-8")
        self.assertIn('id="gameRewindGrid"', html)
        self.assertIn('id="funStatsGrid"', html)
        self.assertIn("function verifiedModelCall", js)
        self.assertIn("match?.official_pick", js)
        self.assertIn("function officialPickHit", js)
        self.assertIn("renderGameRewind()", js)
        self.assertIn("renderFunStats()", js)
        self.assertIn(".rewindVisual", css)
        self.assertIn(".rewindCopy", css)
        self.assertIn(".funStatsGrid", css)
        self.assertIn("generate_public_content_feed()", scheduler)

    def test_content_signal_lab_visualizes_live_model_inputs(self):
        html = (ROOT / "content.html").read_text(encoding="utf-8")
        js = (ROOT / "content.js").read_text(encoding="utf-8")
        css = (ROOT / "content.css").read_text(encoding="utf-8")
        self.assertIn('id="signal-lab"', html)
        self.assertIn('id="signalLabGrid"', html)
        self.assertIn("function renderSignalLab()", js)
        self.assertIn("Confidence terrain", js)
        self.assertIn("Factor fingerprint", js)
        self.assertIn("Board coverage", js)
        self.assertIn("renderSignalLab()", js.split("function renderAll", 1)[1])
        self.assertIn(".signalLabGrid{display:grid", css)
        self.assertIn(".boardDonut", css)
        self.assertIn("role=\"meter\"", js)

    def test_editorial_features_are_not_classified_as_weekly_recaps(self):
        content = (ROOT / "content.js").read_text(encoding="utf-8")
        views = (ROOT / "app-2-views.js").read_text(encoding="utf-8")
        posts = json.loads((ROOT / "posts.json").read_text(encoding="utf-8"))
        refining = next(post for post in posts if post["id"] == "refining-the-record-2026-07-26")
        self.assertIn("const storyType=isRanking?'preview'", content)
        self.assertNotIn("type:'recap',badgeType", content)
        self.assertIn("INSIGHT_FEATURE_TYPES", views)
        self.assertIn('id="featuresList"', views)
        self.assertIn("posts.filter(isWeeklyRecapPost)", views)
        self.assertIn("sort(newestPostFirst)", views)
        self.assertEqual("methodology", refining["type"])

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

    def test_all_sports_scorecard_includes_nhl_and_uses_metric_denominators(self):
        panels = (ROOT / "app-3-panels.js").read_text(encoding="utf-8")
        self.assertIn("'nba','mlb','nhl'", panels)
        self.assertIn("weighted('brier','brier_graded',3,true)", panels)
        self.assertIn("weighted('brier3','brier3_graded',3,true)", panels)
        self.assertIn("weighted('log_loss','log_loss_graded',3,true)", panels)
        self.assertIn("weighted('log_loss_advancement','log_loss_advancement_graded',3,true)", panels)
        self.assertIn("Number(sc.log_loss_advancement_graded)", panels)
        self.assertIn("separate cohorts and sample sizes", panels)

    def test_scorecard_market_copy_uses_compatible_claims(self):
        panels = (ROOT / "app-3-panels.js").read_text(encoding="utf-8")
        self.assertIn("Market agreement", panels)
        self.assertIn("Draws and pick’em prices are not mislabeled as underdogs", panels)
        self.assertIn("Change in the no-vig market probability", panels)
        self.assertNotIn("the sharps' favourite metric", panels)

    def test_scheduled_deploy_is_hourly(self):
        workflow = (ROOT / ".github" / "workflows" / "deploy.yml").read_text(encoding="utf-8")
        self.assertIn("cron: '17 * * * *'", workflow)
        self.assertNotIn("cron: '*/15 * * * *'", workflow)


if __name__ == "__main__":
    unittest.main()
