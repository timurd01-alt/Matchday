import json
import shutil
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent
NODE = shutil.which("node")
if not NODE:
    bundled_node = Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe"
    NODE = str(bundled_node) if bundled_node.exists() else None


class OutcomeTreeStaticTests(unittest.TestCase):
    def test_view_navigation_and_script_are_wired(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn('data-v="tree"', html)
        self.assertIn('id="view-tree"', html)
        self.assertIn('src="app-5-outcome-tree.js?v=__BUILD__"', html)

    def test_deploy_artifact_includes_the_outcome_tree_script(self):
        workflow = (ROOT / ".github/workflows/deploy.yml").read_text(encoding="utf-8")
        copy_line = next(line for line in workflow.splitlines()
                         if line.strip().startswith("cp app-1-core.js"))
        self.assertIn("app-5-outcome-tree.js", copy_line)

    def test_tree_is_available_in_every_navigation_profile(self):
        core = (ROOT / "app-1-core.js").read_text(encoding="utf-8")
        nav_block = core.split("const NAV_DEF={", 1)[1].split("};", 1)[0]
        profiles = [line for line in nav_block.splitlines() if ":[" in line.replace(" ", "")]
        self.assertGreaterEqual(len(profiles), 7)
        for profile in profiles:
            self.assertIn("'tree'", profile)

    def test_sandbox_is_hidden_from_all_sports_only(self):
        core = (ROOT / "app-1-core.js").read_text(encoding="utf-8")
        nav_block = core.split("const NAV_DEF={", 1)[1].split("};", 1)[0]
        profiles = {
            line.split(":", 1)[0].strip(): line
            for line in nav_block.splitlines()
            if ":[" in line.replace(" ", "")
        }
        self.assertNotIn("'sandbox'", profiles["all"])
        self.assertIn("'sandbox'", profiles["us_sport"])

    def test_renderer_and_disclosures_are_present(self):
        panels = (ROOT / "app-3-panels.js").read_text(encoding="utf-8")
        tree = (ROOT / "app-5-outcome-tree.js").read_text(encoding="utf-8")
        docs = (ROOT / "docs/wiki/How-Predictions-Work.md").read_text(encoding="utf-8")
        self.assertIn("tree:renderOutcomeTree", panels)
        self.assertIn("independent", tree.lower())
        self.assertIn("not a sportsbook price", tree.lower())
        self.assertIn("locked prediction snapshots", docs.lower())
        self.assertIn("only one exact result", docs.lower())

    def test_compact_selector_caps_scenarios_at_five_and_uses_xy_branches(self):
        tree = (ROOT / "app-5-outcome-tree.js").read_text(encoding="utf-8")
        self.assertIn("OUTCOME_TREE_MAX_LEGS=5", tree)
        self.assertIn("data-tree-draft-match", tree)
        self.assertIn("data-tree-draft-side", tree)
        self.assertIn("data-tree-add", tree)
        self.assertIn("data-tree-remove", tree)
        self.assertIn('<b>X</b>', tree)
        self.assertIn('<span>Y</span>', tree)
        self.assertIn("X is the selected exact outcome", tree)
        self.assertNotIn("outcomeMatchList", tree)
        self.assertNotIn("Michigan State wins and Alabama loses", tree)


@unittest.skipUnless(NODE, "Node.js is required for JavaScript math tests")
class OutcomeTreeMathTests(unittest.TestCase):
    def run_math(self, expression):
        source = (ROOT / "app-5-outcome-tree.js").read_text(encoding="utf-8")
        script = source + f"\nconsole.log(JSON.stringify({expression}));\n"
        result = subprocess.run(
            [NODE, "-e", script],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        return json.loads(result.stdout.strip())

    def test_joint_probability_multiplies_exact_events(self):
        value = self.run_math("outcomeTreeJointProbability([49,26])")
        self.assertAlmostEqual(value, 0.1274, places=10)

    def test_fair_odds_for_joint_scenario(self):
        odds = self.run_math("outcomeTreeFairOdds(outcomeTreeJointProbability([49,26]))")
        self.assertAlmostEqual(odds["decimal"], 7.8492935636, places=8)
        self.assertEqual(odds["american"], 685)

    def test_fair_odds_for_favorite(self):
        odds = self.run_math("outcomeTreeFairOdds(0.6)")
        self.assertAlmostEqual(odds["decimal"], 1.6666666667, places=8)
        self.assertEqual(odds["american"], -150)

    def test_invalid_probability_does_not_invent_odds(self):
        odds = self.run_math("outcomeTreeFairOdds(0)")
        self.assertIsNone(odds["decimal"])
        self.assertIsNone(odds["american"])


if __name__ == "__main__":
    unittest.main()
