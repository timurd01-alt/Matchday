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

    def test_external_ratings_freshness_and_expanded_view(self):
        snapshot = (ROOT / "matchday-cfb-snapshot.js").read_text(encoding="utf-8")
        panels = (ROOT / "app-3-panels.js").read_text(encoding="utf-8")
        features = (ROOT / "app-4-features.js").read_text(encoding="utf-8")
        # The rankings are generated from the Bet Better handoff now, not typed
        # into the file, so the marker and the reference are what to assert on.
        self.assertIn("BEGIN GENERATED RANKINGS", snapshot)
        self.assertIn("rankings:MATCHDAY_CFB_RANKINGS.rankings", snapshot)
        self.assertIn('"sos"', snapshot)
        self.assertIn("rating:ranked?.rating??null", panels)
        # The snapshot's stamp is reconciled with the payload's, not written
        # over it. It used to overwrite, and because the snapshot is rebuilt
        # only when a new handoff arrives while data_*.json is refetched hourly,
        # the board reported itself days stale whenever the handoff was the
        # older of the two -- "data 4 days ago" above fixtures fetched that
        # morning. See test_data_age.py.
        self.assertIn(
            "payload.updated=_freshestUpdated(payload.updated,MATCHDAY_CFB_SNAPSHOT.updated)",
            panels)
        # renderInsight() lives in app-4-features.js, so it cannot bound a slice of
        # app-3-panels.js. _v4TitleRows is the function that actually follows
        # details() in this file.
        details = panels[panels.index("function details(m){"):panels.index("function _v4TitleRows(")]
        self.assertNotIn("pregameContextPanel(m)", details)
        self.assertIn("modernExpandedView", details)
        self.assertIn("modernMatchSheet", features)
        # The caption used to call this rating "context only" and a preseason
        # tiebreaker, which was false -- the model does use it. It now names the
        # rating and ships the schedule beside it.
        self.assertIn("Opponent-adjusted rating and strength of schedule", panels)
        self.assertIn("sosTag", panels)



if __name__ == "__main__":
    unittest.main()
