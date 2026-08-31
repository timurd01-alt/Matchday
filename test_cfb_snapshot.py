import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parent


class CurrentCfbSnapshotTests(unittest.TestCase):
    def test_snapshot_replaces_old_record_and_stale_bracket(self):
        snapshot = (ROOT / "matchday-cfb-snapshot.js").read_text(encoding="utf-8")
        panels = (ROOT / "app-3-panels.js").read_text(encoding="utf-8")
        self.assertIn("scorecard:{graded:8,model_hits:6,pending:0", snapshot)
        self.assertEqual(snapshot.count("result:'HIT'"), 6)
        self.assertEqual(snapshot.count("result:'MISS'"), 2)
        self.assertIn("payload.bracket=MATCHDAY_CFB_SNAPSHOT.bracket", panels)
        self.assertIn("applyCurrentCfbSnapshot(DATA)", panels)
        self.assertIn("g.group!=='Matchday Top 25'", panels)
        self.assertIn("DATA.comp_key==='NCAAF'?'Conferences'", panels)

    def test_news_is_a_primary_navigation_item(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn('data-primary data-v="news"', html)

    def test_all_college_never_inherits_a_legacy_bracket(self):
        panels = (ROOT / "app-3-panels.js").read_text(encoding="utf-8")
        self.assertIn("competition:'All college'", panels)
        self.assertIn("standings:[],bracket:[],bracketology:null", panels)

    def test_ncaam_keeps_conferences_and_gets_rankings_bracketology(self):
        snapshot = (ROOT / "matchday-cfb-snapshot.js").read_text(encoding="utf-8")
        panels = (ROOT / "app-3-panels.js").read_text(encoding="utf-8")
        self.assertIn("const MATCHDAY_NCAAM_SNAPSHOT", snapshot)
        self.assertIn("buildNcaamBracketology", panels)
        self.assertIn("applyCurrentNcaamSnapshot(DATA)", panels)


if __name__ == "__main__":
    unittest.main()
