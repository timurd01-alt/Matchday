import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent


class AnalysisModeTests(unittest.TestCase):
    def test_public_shell_promises_pregame_and_postgame_analysis(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn("Pregame Picks &amp; Postgame Model Analysis", html)
        self.assertNotIn("Live Scores", html)
        self.assertNotIn("LIVE FEED", html)

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

    def test_scheduled_deploy_is_hourly(self):
        workflow = (ROOT / ".github" / "workflows" / "deploy.yml").read_text(encoding="utf-8")
        self.assertIn("cron: '17 * * * *'", workflow)
        self.assertNotIn("cron: '*/15 * * * *'", workflow)


if __name__ == "__main__":
    unittest.main()
