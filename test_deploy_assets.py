"""Every script index.html loads must actually be published by the deploy step.

Regression: official-selections.js was added to index.html's <script> tags in
bcacbf1 (2026-07-28) but never added to deploy.yml's file-copy step, so it
404'd on the live site for three days across multiple unrelated deploys --
degraded gracefully (the UCL "Team of the Season" panel silently fell back to
a model-built XI instead of the real official UEFA selection) rather than
crashing, which is exactly how a missing asset can go unnoticed. Caught by
inspecting live network requests, not by any existing test, because nothing
cross-checked the two lists against each other.
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent


class DeployAssetTests(unittest.TestCase):
    def test_every_local_script_tag_is_published(self):
        markup = (ROOT / "index.html").read_text(encoding="utf-8")
        workflow = (ROOT / ".github" / "workflows" / "deploy.yml").read_text(encoding="utf-8")
        scripts = re.findall(r'<script src="([^"?]+)\.js(?:\?[^"]*)?"', markup)
        self.assertGreater(len(scripts), 5, "sanity check: found too few <script> tags to be real")
        missing = [f"{name}.js" for name in scripts if f"{name}.js" not in workflow]
        self.assertEqual(missing, [],
                         f"index.html loads {missing} but deploy.yml never copies "
                         "it to _site/ -- it will 404 on the live site")

class RuntimeDataAssetTests(unittest.TestCase):
    """Same regression class as above, for data the app fetches at runtime.

    The script-tag check cannot see these: board_summary.json and the per-sport
    files are requested by fetch() at runtime, so a missing copy step 404s in
    exactly the quiet, degrade-gracefully way official-selections.js did -- the
    board would silently fall back to merging the full sport files, undoing the
    payload work without anything failing.
    """

    def _workflow(self):
        return (ROOT / ".github" / "workflows" / "deploy.yml").read_text(encoding="utf-8")

    def _app_sources(self):
        return "\n".join(
            path.read_text(encoding="utf-8")
            for path in sorted(ROOT.glob("app-*.js"))
        )

    def test_every_statically_named_json_fetch_is_published(self):
        workflow = self._workflow()
        fetched = set(re.findall(r"fetch\('([A-Za-z0-9_./-]+\.json)", self._app_sources()))
        self.assertIn("board_summary.json", fetched,
                      "sanity check: the board payload should be fetched by name")
        missing = sorted(name for name in fetched if name not in workflow)
        self.assertEqual(missing, [],
                         f"the app fetches {missing} at runtime but deploy.yml never "
                         "publishes it to _site/ -- it will 404 on the live site")

    def test_board_summary_is_built_into_the_published_site(self):
        # Copying it is not enough: it is generated per run from the freshly
        # fetched data files, so the build has to invoke the builder itself.
        workflow = self._workflow()
        self.assertIn("build_board_summary.py", workflow,
                      "deploy.yml never runs the board payload builder, so the "
                      "site would ship whatever stale copy was committed")
        self.assertIn("_site/board_summary.json", workflow,
                      "the board payload builder must write into the published directory")

    def test_every_published_sport_file_is_copied(self):
        workflow = self._workflow()
        core = (ROOT / "app-1-core.js").read_text(encoding="utf-8")
        literal = re.search(r"const ALL_SPORT_KEYS=\[([^\]]*)\]", core)
        self.assertIsNotNone(literal, "ALL_SPORT_KEYS not found in app-1-core.js")
        keys = re.findall(r"'([a-z]+)'", literal.group(1))
        self.assertGreater(len(keys), 5, "sanity check: too few sport keys to be real")
        missing = [f"data_{key}.json" for key in keys if f"data_{key}.json" not in workflow]
        self.assertEqual(missing, [],
                         f"the app fetches {missing} when a visitor picks that sport, "
                         "but deploy.yml never copies it to _site/")


if __name__ == "__main__":
    unittest.main()
