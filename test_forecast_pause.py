import json
import shutil
import subprocess
import unittest
from pathlib import Path

import forecast_pause


ROOT = Path(__file__).resolve().parent
NODE = shutil.which("node")
if not NODE:
    bundled = Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe"
    NODE = str(bundled) if bundled.exists() else None


class ForecastPausePolicyTests(unittest.TestCase):
    def test_publication_is_restored_for_every_competition(self):
        for comp in ("EPL", "MLB", "NBA", "NFL", "NCAAF", "NHL", "WC", None):
            self.assertFalse(forecast_pause.paused(comp), comp)
            self.assertTrue(forecast_pause.publication_eligible(comp), comp)

    def test_decision_payload_restores_eligibility(self):
        decision = forecast_pause.publication_decision("EPL")
        self.assertEqual(decision["state"], "eligible")
        self.assertIs(decision["official_publication_eligible"], True)


@unittest.skipUnless(NODE, "Node.js is required for frontend behavior tests")
class ForecastPauseFrontendTests(unittest.TestCase):
    def run_pause_gate(self, payload, active=True):
        core = (ROOT / "app-1-core.js").read_text(encoding="utf-8")
        start = core.index("const FORECAST_PAUSE_ACTIVE=")
        end = core.index("// Providers can keep the season", start)
        source = core[start:end]
        source = source.replace("const FORECAST_PAUSE_ACTIVE=false",
                                f"const FORECAST_PAUSE_ACTIVE={str(active).lower()}", 1)
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

    def test_every_sport_loses_its_forecast_surfaces_but_keeps_market(self):
        prediction = {"publication_state": "locked", "pick": "h", "pick_name": "Alpha",
                      "confidence": 81, "edge": 14, "upset": {"radar": True},
                      "predicted_margin": 2.4}
        for comp in ("EPL", "NBA", "NFL", "MLB", "NCAAF"):
            match = {"id": "future", "status": "UPCOMING", "prediction": dict(prediction),
                     "watchability": 91, "predicted_margin": 2.4,
                     "model_vs_market_alert": "large gap",
                     "markets": {"1x2": {"home_pct": 54, "away_pct": 46}}}
            gated = self.run_pause_gate({"comp_key": comp, "matches": [match]})["matches"][0]
            self.assertTrue(gated["_forecast_paused"], comp)
            # Browsing survives the pause: odds stay, the pick does not.
            self.assertEqual(gated["markets"]["1x2"]["home_pct"], 54, comp)
            for key in ("prediction", "watchability", "predicted_margin",
                        "model_vs_market_alert"):
                self.assertNotIn(key, gated, f"{comp}:{key}")

    def test_only_finished_games_keep_the_pick_they_were_graded_on(self):
        # An in-play pick is still an ungraded model call, so it goes too. The
        # graded receipt stays: the record is not scrubbed by a pause.
        matches = [
            {"id": "future", "status": "UPCOMING", "prediction": {"pick": "a"}},
            {"id": "live", "status": "LIVE", "prediction": {"pick": "a", "confidence": 72}},
            {"id": "receipt", "status": "FINISHED", "prediction": {"pick": "h"}},
        ]
        gated = self.run_pause_gate({"comp_key": "EPL", "matches": matches})["matches"]
        self.assertNotIn("prediction", gated[0])
        self.assertNotIn("prediction", gated[1])
        self.assertEqual(gated[2]["prediction"]["pick"], "h")

    def test_backend_eligibility_cannot_override_the_site_wide_switch(self):
        # Fail closed: while the switch is set, an "eligible" dataset marker --
        # stale or otherwise -- must not resurrect a pick.
        for comp in ("EPL", "MLB"):
            match = {"id": "future", "status": "UPCOMING",
                     "prediction": {"publication_state": "locked", "pick": "h"}}
            gated = self.run_pause_gate({"comp_key": comp,
                                         "forecast_publication": {"state": "eligible"},
                                         "matches": [match]})["matches"][0]
            self.assertNotIn("prediction", gated, comp)

    def test_with_the_switch_off_publication_follows_the_dataset_marker(self):
        # No sport has a private exemption in either direction. With the switch
        # cleared, a pick returns only where the backend says it is eligible.
        for comp in ("MLB", "EPL", "NBA"):
            still_paused = self.run_pause_gate(
                {"comp_key": comp, "matches": [{"id": "m", "status": "UPCOMING",
                                                "prediction": {"pick": "h"}}]},
                active=False)["matches"][0]
            self.assertNotIn("prediction", still_paused, comp)

            published = self.run_pause_gate(
                {"comp_key": comp, "forecast_publication": {"state": "eligible"},
                 "matches": [{"id": "m", "status": "UPCOMING",
                              "prediction": {"pick": "h"}}]},
                active=False)["matches"][0]
            self.assertEqual(published["prediction"]["pick"], "h", comp)

    def test_consumers_show_the_pause_notice(self):
        core = (ROOT / "app-1-core.js").read_text(encoding="utf-8")
        panels = (ROOT / "app-3-panels.js").read_text(encoding="utf-8")
        cards = (ROOT / "app-4-features.js").read_text(encoding="utf-8")
        self.assertIn(forecast_pause.PAUSE_MESSAGE, core)
        self.assertIn("forecastPauseHTML(m)", panels)
        self.assertIn("isForecastPaused(m)?forecastPauseHTML(m)", cards)
        # The banner must not be gated on a single competition any more.
        self.assertIn("(DATA.matches||[]).some(m=>isForecastPaused(m))", panels)
        # And no competition keeps a private exemption from the pause.
        self.assertNotIn("isMlbForecastPaused", core)
        self.assertNotIn("comp==='MLB'", core)

    def run_accessors(self, match, payload):
        """Exercise the two functions every percentage on the page reads from."""
        core = (ROOT / "app-1-core.js").read_text(encoding="utf-8")
        gate = core[core.index("const FORECAST_PAUSE_ACTIVE="):
                    core.index("// Providers can keep the season")]
        accessors = core[core.index("function lockedPredictionSnapshot(m){"):
                         core.index("function duo(xl,xv,yl,yv){")]
        script = f"""
let DATA={json.dumps(payload)};
function esc(value){{return String(value ?? '');}}
{gate}
{accessors}
const m={json.dumps(match)};
console.log(JSON.stringify({{pick:officialPrediction(m),
                            probs:officialPredictionProbabilities(m)}}));
"""
        result = subprocess.run([NODE, "-e", script], cwd=ROOT, check=True,
                                capture_output=True, text=True)
        return json.loads(result.stdout)

    def test_no_model_percentage_survives_the_pause(self):
        # The pause has to remove the model's numbers, not just its pick label:
        # confidence, blended probabilities and the locked snapshot behind them
        # are all model output computed from data the rebuild does not have.
        match = {"id": "future", "status": "UPCOMING", "_comp": "EPL",
                 "prediction": {"pick": "h", "pick_name": "Alpha", "confidence": 81,
                                "adjusted": {"h": 81, "d": 0, "a": 19},
                                "blend": {"h": 79, "d": 0, "a": 21},
                                "model": {"h": 77, "d": 0, "a": 23}},
                 "locked_prediction": {"pick": "h", "confidence": 81,
                                       "adjusted": {"h": 81, "d": 0, "a": 19}}}
        out = self.run_accessors(match, {"comp_key": "EPL"})
        self.assertEqual(out["probs"], {})
        self.assertIsNone(out["pick"]["confidence"])
        self.assertEqual(out["pick"]["side"], "")
        self.assertEqual(out["pick"]["name"], "")

    def test_pause_notice_points_readers_at_what_still_works(self):
        core = (ROOT / "app-1-core.js").read_text(encoding="utf-8")
        self.assertIn("Scores, results, stats and market odds are all still here.", core)


class PauseIsExplainedToReadersTests(unittest.TestCase):
    def test_qa_page_documents_the_pause_and_the_route_back(self):
        qa = (ROOT / "qa.html").read_text(encoding="utf-8")
        self.assertIn('id="pause"', qa)
        self.assertIn("Why are there no predictions right now?", qa)
        self.assertIn("What still works while predictions are paused?", qa)
        self.assertIn("When do predictions come back?", qa)
        self.assertIn("Does the pause change the existing track record?", qa)

    def test_qa_structured_data_stays_valid_and_leads_with_the_pause(self):
        import re
        qa = (ROOT / "qa.html").read_text(encoding="utf-8")
        block = re.search(r'<script type="application/ld\+json">(.*?)</script>',
                          qa, re.S).group(1)
        data = json.loads(block)
        self.assertEqual(data["@type"], "FAQPage")
        names = [q["name"] for q in data["mainEntity"]]
        self.assertEqual(names[0], "Why are there no predictions right now?")
        # Every visible pause question is also in the structured data.
        for question in ("What still works while predictions are paused?",
                         "When do predictions come back?"):
            self.assertIn(question, names)

    def test_front_page_pause_banner_is_removed(self):
        index = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertNotIn("Predictions are paused", index)
        self.assertNotIn("developmentPause", index)
        self.assertNotIn("Development pause", index)


if __name__ == "__main__":
    unittest.main()
