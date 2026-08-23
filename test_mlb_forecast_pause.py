import json
import shutil
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent
NODE = shutil.which("node")
if not NODE:
    bundled = Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe"
    NODE = str(bundled) if bundled.exists() else None


@unittest.skipUnless(NODE, "Node.js is required for frontend behavior tests")
class MlbForecastPauseTests(unittest.TestCase):
    def run_pause_gate(self, payload):
        core = (ROOT / "app-1-core.js").read_text(encoding="utf-8")
        start = core.index("const MLB_FORECAST_PAUSE_MESSAGE=")
        end = core.index("// Providers can keep the season", start)
        source = core[start:end]
        script = f"""
let DATA={{}};
function esc(value){{return String(value ?? '');}}
{source}
const payload={json.dumps(payload)};
applyForecastPublicationPauses(payload);
console.log(JSON.stringify(payload));
"""
        result = subprocess.run([NODE, "-e", script], cwd=ROOT, check=True,
                                capture_output=True, text=True)
        return json.loads(result.stdout)

    def test_stale_unmarked_upcoming_mlb_loses_every_forecast_surface_but_keeps_market(self):
        prediction = {"publication_state": "locked", "pick": "h", "pick_name": "Alpha",
                      "confidence": 81, "edge": 14, "upset": {"radar": True},
                      "predicted_margin": 2.4}
        match = {"id": "future", "status": "UPCOMING", "prediction": prediction,
                 "watchability": 91, "predicted_margin": 2.4,
                 "model_vs_market_alert": "large gap",
                 "markets": {"1x2": {"home_pct": 54, "away_pct": 46}}}
        gated = self.run_pause_gate({"comp_key": "MLB", "matches": [match]})["matches"][0]
        self.assertTrue(gated["_forecast_paused"])
        self.assertIn("starting-pitcher data", gated["_forecast_pause_message"])
        self.assertEqual(gated["markets"]["1x2"]["home_pct"], 54)
        for key in ("prediction", "watchability", "predicted_margin", "model_vs_market_alert"):
            self.assertNotIn(key, gated)

    def test_dataset_pause_marker_only_affects_upcoming_mlb(self):
        matches = [
            {"id": "future", "status": "UPCOMING", "prediction": {"pick": "a"}},
            {"id": "receipt", "status": "FINISHED", "prediction": {"pick": "h"}},
        ]
        gated = self.run_pause_gate({"comp_key": "MLB",
                                     "forecast_publication": {"state": "paused"},
                                     "matches": matches})["matches"]
        self.assertNotIn("prediction", gated[0])
        self.assertEqual(gated[1]["prediction"]["pick"], "h")

    def test_explicit_backend_eligibility_is_the_only_unpause_path(self):
        for phase in ("preliminary", "lock_candidate", "locked"):
            match = {"id": "future", "status": "UPCOMING",
                     "prediction": {"publication_state": phase, "pick": "h"}}
            gated = self.run_pause_gate({"comp_key": "MLB",
                                         "forecast_publication": {"state": "eligible"},
                                         "matches": [match]})["matches"][0]
            self.assertEqual(gated["prediction"]["pick"], "h")
            self.assertNotIn("_forecast_paused", gated)

    def test_consumers_show_pause_notice(self):
        core = (ROOT / "app-1-core.js").read_text(encoding="utf-8")
        panels = (ROOT / "app-3-panels.js").read_text(encoding="utf-8")
        cards = (ROOT / "app-4-features.js").read_text(encoding="utf-8")
        message = "MLB forecasts are paused pending starting-pitcher data."
        self.assertIn(message, core)
        self.assertIn("forecastPauseHTML(m)", panels)
        self.assertIn("isMlbForecastPaused(m)?forecastPauseHTML(m)", cards)


if __name__ == "__main__":
    unittest.main()
