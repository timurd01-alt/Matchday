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
        # Two: the site covers NCAAF and NCAAM. The floor guards against the list
        # being emptied or the regex silently matching nothing, not against the
        # pivot that deliberately reduced it.
        self.assertGreaterEqual(len(keys), 2, "sanity check: too few sport keys to be real")
        missing = [f"data_{key}.json" for key in keys if f"data_{key}.json" not in workflow]
        self.assertEqual(missing, [],
                         f"the app fetches {missing} when a visitor picks that sport, "
                         "but deploy.yml never copies it to _site/")




class CacheClobberTests(unittest.TestCase):
    """A git-tracked file must not also be restored by the actions/cache step.

    Fifth instance of one bug class. `actions/cache`'s restore-keys fallback
    hands a run an older copy of every path it manages, and it does so AFTER
    checkout -- so for a tracked file it silently overwrites the committed
    contents with whatever some earlier run happened to save. deploy.yml
    already documents this happening to ratings*.json (stale class ratings
    flipped Alabama negative on the live site), picks_log*.json (pick ledger
    reset to empty), the forecast ledgers, and market_snapshot_ledger.jsonl
    ("a market price cannot be recomputed").

    It then took the hourly deploy down for 13 straight runs: generate_posts.py
    culled the editorial posts out of posts.json, the culled file was cached,
    and the cache restored it over every corrected checkout -- so committing
    the source fix changed nothing, because the test suite never saw the
    committed posts.json.

    Each prior instance was found only after it had already destroyed
    something, so this pins the overlap instead of leaving the next one to be
    discovered the same way.
    """

    # Tracked files still inside the cache step. Each is committed back by the
    # workflow, so git can already supply it and the cache entry buys nothing
    # but the clobber risk above; they are grandfathered rather than removed
    # here only because dropping them also drops the fallback that covers a
    # ledger whose commit-back lost all three push races. Shrinking this set is
    # safe and welcome. Growing it is the bug.
    # The forecast ledgers left this set on 2026-08-21: they were covered by
    # a `forecast_ledger_*.jsonl` cache glob, and the commit-back step globs
    # the same way, so every new competition's ledger became tracked-and-
    # cached on its first write. Ligue 1 opening did that unattended and this
    # test then blocked the hourly deploy. A wildcard cannot be grandfathered
    # -- the set it covers grows without review -- so the glob was dropped
    # from the cache instead.
    KNOWN_CACHED_TRACKED_FILES = {
        "market_snapshot_ledger.jsonl",
        "mlb_shadow_ledger.jsonl",
        "ncaaf_venue_coords.json",
    }

    def _cached_patterns(self):
        workflow = (ROOT / ".github" / "workflows" / "deploy.yml").read_text(encoding="utf-8")
        body = workflow.split("path: |", 1)[1]
        patterns = []
        for line in body.splitlines()[1:]:
            # The block scalar ends at the first line that is not indented
            # into it; blank lines inside it are not a terminator.
            if line.strip() and not line.startswith(" " * 12):
                break
            entry = line.strip()
            if entry and not entry.startswith("#"):
                patterns.append(entry)
        self.assertGreater(len(patterns), 10, "sanity check: cache path list parsed as too short")
        return patterns

    def _tracked_files(self):
        import subprocess
        result = subprocess.run(["git", "ls-files"], cwd=ROOT,
                                capture_output=True, text=True, check=True)
        tracked = result.stdout.split()
        self.assertGreater(len(tracked), 50, "sanity check: git ls-files returned too little")
        return tracked

    def test_no_tracked_file_is_restored_over_by_the_cache(self):
        import fnmatch
        patterns = self._cached_patterns()
        overlap = {name for name in self._tracked_files()
                   for pattern in patterns if fnmatch.fnmatch(name, pattern)}
        self.assertEqual(
            overlap - self.KNOWN_CACHED_TRACKED_FILES, set(),
            "these git-tracked files are also cached, so the cache's restore-keys "
            "fallback will overwrite the committed copy after checkout -- commit "
            "them back instead of caching them, or the fix you just made will be "
            "silently reverted at runtime")

    def test_the_published_editorial_record_is_committed_not_cached(self):
        patterns = self._cached_patterns()
        for entry in ("posts.json", "posts_state.json", "posts/*.html"):
            self.assertNotIn(entry, patterns,
                             f"{entry} is git-tracked; caching it reintroduces the "
                             "clobber that kept the hourly deploy red")
        workflow = (ROOT / ".github" / "workflows" / "deploy.yml").read_text(encoding="utf-8")
        commit_step = workflow.split("Commit updated ratings and picks ledger", 1)[1]
        self.assertIn("posts.json posts_state.json", commit_step)
        self.assertIn("'posts/*.html'", commit_step)

    def test_every_post_in_the_feed_has_a_committed_page(self):
        """posts.json and the rendered pages must travel together in git.

        While the pages were cache-only, two posts
        (friday-model-vs-market-2026-08-07,
        wednesday-availability-tracker-2026-08-05) were listed in the feed with
        no committed HTML -- reachable on the live site only for as long as the
        cache happened to still hold them.
        """
        import json
        import subprocess
        posts = json.loads((ROOT / "posts.json").read_text(encoding="utf-8"))
        self.assertGreater(len(posts), 5, "sanity check: posts.json parsed as too short")
        committed = set(subprocess.run(["git", "ls-files", "posts/"], cwd=ROOT,
                                       capture_output=True, text=True, check=True).stdout.split())
        missing = [post["id"] for post in posts
                   if f"posts/{post.get('slug') or post.get('id')}.html" not in committed]
        self.assertEqual(missing, [],
                         f"posts.json lists {missing} but their pages are not committed; "
                         "the live site will link to a 404 as soon as the cache rolls")


if __name__ == "__main__":
    unittest.main()
