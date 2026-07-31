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


if __name__ == "__main__":
    unittest.main()
