import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path

from populate_research_signals import populate
from refresh_nfl_advanced_metrics import candidate_seasons


ROOT = Path(__file__).parent


class ResearchSignalsUITests(unittest.TestCase):
    def test_nfl_refresh_uses_active_or_last_completed_season(self):
        self.assertEqual(candidate_seasons(dt.date(2026, 7, 29)), [2025, 2024])
        self.assertEqual(candidate_seasons(dt.date(2026, 10, 1)), [2026, 2025])

    def test_expanded_view_is_explicitly_zero_weight(self):
        source = (ROOT / "research-signals.js").read_text(encoding="utf-8")
        self.assertIn("advanced_metrics", source)
        self.assertIn("nfl_challenger_shadow", source)
        self.assertIn("mlb_challenger_shadow", source)
        self.assertIn("cleared historical out-of-sample testing", source)
        self.assertIn("Prospective evidence", source)
        self.assertIn("eligible_games", source)
        self.assertIn("research_promotion", source)
        self.assertIn("manually reviewed prospective gate", source)
        self.assertIn("production weight 0", source)
        self.assertIn("failed its promotion gate", source)
        index = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn("research-signals.js?v=__BUILD__", index)
        self.assertIn("research-signals.css?v=__BUILD__", index)

    def test_ci_builds_and_publishes_derived_research_assets(self):
        workflow = (ROOT / ".github" / "workflows" / "deploy.yml").read_text(encoding="utf-8")
        self.assertIn("python refresh_nfl_advanced_metrics.py", workflow)
        self.assertIn("python populate_research_signals.py", workflow)
        self.assertIn("research-signals.js", workflow)
        self.assertIn("research-signals.css", workflow)

    def test_cached_fixture_population_needs_no_provider_refresh(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "data_nfl.json").write_text(json.dumps({"matches": [{
                "home": {"name": "Kansas City Chiefs"},
                "away": {"name": "Buffalo Bills"},
            }]}), encoding="utf-8")
            (root / "advanced_metrics_nfl.json").write_text(json.dumps({
                "schema_version": 1, "shadow_only": True, "attach_live": True,
                "source": "nflverse-data pbp release", "license": "CC BY 4.0",
                "profiles": {"KC": {"epa_per_play": .2}, "BUF": {"epa_per_play": .1}},
            }), encoding="utf-8")
            result = populate(root)
            payload = json.loads((root / "data_nfl.json").read_text(encoding="utf-8"))
            self.assertEqual(result["nfl"]["advanced"], 1)
            self.assertEqual(payload["matches"][0]["research_signal_schema"], 1)
            self.assertEqual(payload["matches"][0]["advanced_metrics"]["home"]["epa_per_play"], .2)

    def test_mlb_population_exposes_only_scorecard_summary(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "data_mlb.json").write_text(json.dumps({"matches": []}), encoding="utf-8")
            (root / "mlb_prospective_scorecard.json").write_text(json.dumps({
                "schema_version": 1, "protocol_version": "mlb-prospective-shadow-1.0.0",
                "status": "collecting_prospective_evidence",
                "evaluation_contract": {"minimum_games": 500, "minimum_game_date_blocks": 30},
                "models": {"official": {"n": 12, "log_loss": .69},
                           "run_strength_challenger": {"n": 12, "log_loss": .68}},
                "comparisons": {"run_strength_vs_official": {"blocks": 3, "ci95": [-.02, .01]}},
            }), encoding="utf-8")
            populate(root)
            payload = json.loads((root / "data_mlb.json").read_text(encoding="utf-8"))
            summary = payload["research_scorecards"]["mlb"]
            self.assertEqual(summary["eligible_games"], 12)
            self.assertEqual(summary["game_date_blocks"], 3)
            self.assertEqual(summary["production_weight"], 0)


if __name__ == "__main__":
    unittest.main()
