import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path

from populate_research_signals import populate


ROOT = Path(__file__).resolve().parent.parent


class ResearchSignalsUITests(unittest.TestCase):
    def test_expanded_view_is_explicitly_zero_weight(self):
        source = (ROOT / "research-signals.js").read_text(encoding="utf-8")
        self.assertIn("advanced_metrics", source)
        self.assertIn("production weight 0", source)
        for gone in ("nfl_challenger_shadow", "mlb_challenger_shadow"):
            self.assertNotIn(gone, source)
        index = (ROOT / "index.html").read_text(encoding="utf-8")
        # The script is injected by startMatchdayApp(), which stamps the build
        # onto every bundle it loads; the stylesheet is still a plain tag.
        self.assertIn("'research-signals.js'", index)
        self.assertIn("function matchdayAsset(file){return file+'?v=__BUILD__'}", index)
        self.assertIn("research-signals.css?v=__BUILD__", index)

    def test_cfb_profile_is_plain_language_and_explicitly_descriptive(self):
        source = (ROOT / "research-signals.js").read_text(encoding="utf-8")
        # The panel no longer claims these metrics are inert. The engine solves
        # its ratings from the same opponent-adjusted work, so "0% weight" and
        # "does not change today's probability" were misleading in the one
        # direction that matters.
        for text in ("Advanced CFB profile", "Team profile", "Predicted Points Added",
                     "Offense", "Defense", "Show ${rows.length-3} more"):
            self.assertIn(text, source)
        panel = source[source.index("cfbResearchTop"):source.index("function coverageText")]
        for gone in ("Used in today's pick", "0% weight", "Descriptive context",
                     "does not change today"):
            self.assertNotIn(gone, panel)
        self.assertIn("advanced_metrics_meta", source)
        self.assertIn("Profile unavailable for", source)

    def test_cfb_profile_has_mobile_and_keyboard_affordances(self):
        css = (ROOT / "research-signals.css").read_text(encoding="utf-8")
        self.assertIn(".cfbMore summary:focus-visible", css)
        self.assertIn("min-height:44px", css)
        self.assertIn("@media(max-width:680px)", css)

    def test_ci_builds_and_publishes_derived_research_assets(self):
        workflow = (ROOT / ".github" / "workflows" / "deploy.yml").read_text(encoding="utf-8")
        self.assertIn("python populate_research_signals.py", workflow)
        self.assertIn("research-signals.js", workflow)
        self.assertIn("research-signals.css", workflow)

    def test_cached_fixture_population_needs_no_provider_refresh(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "data_ncaaf.json").write_text(json.dumps({"matches": [{
                "home": {"name": "Alabama Crimson Tide", "code": "ALA"},
                "away": {"name": "Georgia Bulldogs", "code": "UGA"},
            }]}), encoding="utf-8")
            (root / "advanced_metrics_ncaaf.json").write_text(json.dumps({
                "schema_version": 1, "shadow_only": True, "attach_live": True,
                "source": "CollegeFootballData advanced team stats", "license": "research",
                "profiles": {"Alabama Crimson Tide": {"epa_per_play": .2},
                             "Georgia Bulldogs": {"epa_per_play": .1}},
            }), encoding="utf-8")
            result = populate(root)
            payload = json.loads((root / "data_ncaaf.json").read_text(encoding="utf-8"))
            self.assertEqual(result["ncaaf"]["advanced"], 1)
            self.assertEqual(payload["matches"][0]["research_signal_schema"], 1)
            self.assertEqual(payload["matches"][0]["advanced_metrics"]["home"]["epa_per_play"], .2)

if __name__ == "__main__":
    unittest.main()
