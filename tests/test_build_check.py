"""The stale-page check in app-1-core.js (Build 1120M).

A browser may keep index.html for ten minutes after a deploy. The app compares
the build named in its own meta tag with a fresh copy and reloads once.
"""
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]


class BuildCheckTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        core = (ROOT / "app-1-core.js").read_text(encoding="utf-8")
        cls.check = core[core.index("/* Stale-page check."):]
        cls.index = (ROOT / "index.html").read_text(encoding="utf-8")

    def test_index_carries_the_build_tag_the_check_reads(self):
        self.assertIn('<meta name="matchday-build-sha" content="__BUILD__">', self.index)
        self.assertIn('name="matchday-build-sha" content="([0-9a-f]{6,40})"', self.check)

    def test_local_pages_never_check(self):
        # Locally the tag is still __BUILD__, which is not a hex SHA.
        self.assertIn("if(!/^[0-9a-f]{6,40}$/.test(mine))return;", self.check)

    def test_reloads_at_most_once_per_build(self):
        self.assertIn("store.getItem('mdReloadedFor')===live", self.check)
        self.assertLess(self.check.index("store.setItem('mdReloadedFor',live)"), self.check.index("location.reload()"))
        # No storage means no loop guard, so it must not run at all.
        self.assertIn("catch(e){return}", self.check)

    def test_fetches_past_the_browser_cache(self):
        self.assertIn("{cache:'no-store'}", self.check)


if __name__ == "__main__":
    unittest.main()
