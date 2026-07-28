import json
import shutil
import subprocess
import unittest
from pathlib import Path
from unittest import mock

import fetch_data


ROOT = Path(__file__).resolve().parent
NODE = shutil.which("node")
if not NODE:
    bundled = Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe"
    NODE = str(bundled) if bundled.exists() else None


class OfficialTournamentSelectionTests(unittest.TestCase):
    @unittest.skipUnless(NODE, "Node.js is required to validate the published selection")
    def test_ucl_selection_is_a_balanced_eleven(self):
        source = (ROOT / "official-selections.js").read_text(encoding="utf-8")
        script = source + "\nconsole.log(JSON.stringify(globalThis.MATCHDAY_OFFICIAL_SELECTIONS.ucl_2025_26));"
        completed = subprocess.run([NODE, "-e", script], check=True, capture_output=True, text=True)
        selection = json.loads(completed.stdout)
        roles = [player["role"] for player in selection["xi"]]
        self.assertEqual(len(roles), 11)
        self.assertEqual(roles.count("GK"), 1)
        self.assertEqual(roles.count("DEF"), 4)
        self.assertEqual(roles.count("MID"), 4)
        self.assertEqual(roles.count("FWD"), 2)
        self.assertIn("uefa.com/uefachampionsleague", selection["sourceUrl"])

    def test_ui_distinguishes_official_and_model_output(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        views = (ROOT / "app-2-views.js").read_text(encoding="utf-8")
        legal = (ROOT / "legal.html").read_text(encoding="utf-8")
        self.assertLess(html.index("official-selections.js"), html.index("app-2-views.js"))
        self.assertIn("Official ${esc(t.season)} selection", views)
        self.assertIn("Model attacking leaders — not a complete XI", views)
        self.assertIn("UEFA Technical Observer Group", legal)


class ModelTournamentFormationTests(unittest.TestCase):
    def test_model_generated_team_caps_at_a_true_four_three_three(self):
        scorers = []
        for index in range(3):
            scorers.append({"name": f"Forward {index}", "team": "Team A", "position": "Forward",
                            "goals": 8 - index, "assists": 2, "played": 8})
        for index in range(4):
            scorers.append({"name": f"Midfielder {index}", "team": "Team B", "position": "Midfield",
                            "goals": 5 - index, "assists": 3, "played": 8})
        players = {}
        for index in range(4):
            players[f"defender {index}|team c"] = {
                "name": f"Defender {index}", "team": "Team C", "role": "DEF",
                "starts": 8 - index, "clean_sheets": 6 - index,
            }
        players["keeper|team c"] = {
            "name": "Keeper", "team": "Team C", "role": "GK", "starts": 8, "clean_sheets": 6,
        }
        with mock.patch.object(fetch_data, "LINEUP_BACKFILL_ENABLED", True), \
             mock.patch.object(fetch_data, "_load_player_db", return_value={"players": players}):
            result = fetch_data.build_team_of_tournament([], scorers, [])
        roles = [player["role"] for player in result["xi"]]
        self.assertEqual(len(roles), 11)
        self.assertEqual(roles.count("FWD"), 3)
        self.assertEqual(roles.count("MID"), 3)
        self.assertEqual(roles.count("DEF"), 4)
        self.assertEqual(roles.count("GK"), 1)


if __name__ == "__main__":
    unittest.main()
