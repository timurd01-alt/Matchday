"""The active competition must switch as one unit, or not at all.

COMP_KEY is a module-level singleton in fetch_data, and ~15 further module
values are derived from it: the two market URLs, seven per-competition cache
paths, the ratings / opening-odds / player / picks ledgers, the news search
term, and the RSS feed set. Those derivations ran inline at import and never
again, so assigning COMP_KEY moved the key and left everything else pointing at
whichever competition was active when the module was first imported.

That was a live defect, not a theoretical one: audit_model_vs_market loops over
twelve competitions calling predict(), and predict() reads the ratings through
RATINGS_FILE -- so every competition after the first was scored against the
wrong ratings file. refresh_college_talent had hand-patched around it by also
resetting RATINGS_FILE and the _RATINGS cache; backfill_history and
audit_model_vs_market had not; nothing anywhere reset RSS_FEEDS.

These tests pin the switch down from both directions: everything moves together
(DerivedStateTests), and callers actually use the switch (CallerDisciplineTests).
"""

import re
import unittest
from pathlib import Path
from urllib.parse import urlsplit

import fetch_data


def _feed_hosts(feeds):
    """The hostnames a feed set actually fetches from.

    Matching "bbci.co.uk" as a substring of the whole URL is the wrong test
    and CodeQL flags it (py/incomplete-url-substring-sanitization): the
    string can sit anywhere in a URL, so a path or query on an unrelated
    host would satisfy it. Comparing the parsed hostname is both precise and
    what this assertion actually means.
    """
    return {(urlsplit(url).hostname or "").lower() for _, url in feeds}


def _serves(hosts, domain):
    return any(host == domain or host.endswith("." + domain) for host in hosts)


# Every module-level name fetch_data derives from the active competition, with
# the fragment of the competition key each one must contain once switched.
DERIVED_PATHS = (
    "ODDS_CACHE_FILE",
    "OUTRIGHTS_CACHE_FILE",
    "API_FOOTBALL_CACHE_FILE",
    "SPORTSDATAIO_PREGAME_CACHE_FILE",
    "BBS_PREGAME_CACHE_FILE",
    "PREGAME_CONTEXT_CACHE_FILE",
    "SPORTSGAMEODDS_CACHE_FILE",
    "OPEN_FILE",
    "PLAYER_DB_FILE",
    "PICKS_FILE",
)


class DerivedStateTests(unittest.TestCase):
    def setUp(self):
        self.original = fetch_data.COMP_KEY
        self.addCleanup(fetch_data.set_competition, self.original)

    def test_every_derived_path_follows_the_competition(self):
        fetch_data.set_competition("NCAAM")
        for name in DERIVED_PATHS:
            with self.subTest(constant=name):
                self.assertIn("ncaam", getattr(fetch_data, name))

    def test_the_ratings_ledger_follows_the_competition(self):
        fetch_data.set_competition("NCAAF")
        self.assertEqual(fetch_data.RATINGS_FILE, "ratings_ncaaf.json")

    def test_the_world_cup_keeps_its_unsuffixed_ratings_filename(self):
        # ratings.json, not ratings_wc.json -- the tracked file predates the
        # per-competition naming and the deploy workflow commits it by name.
        fetch_data.set_competition("WC")
        self.assertEqual(fetch_data.RATINGS_FILE, "ratings.json")

    def test_the_market_urls_follow_the_competition(self):
        fetch_data.set_competition("MLB")
        self.assertIn(fetch_data.COMPETITIONS["MLB"]["odds"], fetch_data.ODDS_URL)
        self.assertIn(fetch_data.COMPETITIONS["MLB"]["outright"], fetch_data.OUTRIGHTS_URL)

    def test_the_news_feed_set_follows_the_competition(self):
        # The one piece of competition-scoped state no caller ever reset,
        # because it was built by inline module-level code rather than by a
        # function anything could call again.
        fetch_data.set_competition("WC")
        world_cup = list(fetch_data.RSS_FEEDS)
        fetch_data.set_competition("NCAAF")
        college = list(fetch_data.RSS_FEEDS)
        self.assertNotEqual(world_cup, college)
        # Soccer gets direct football feeds; a football competition does not.
        self.assertTrue(_serves(_feed_hosts(world_cup), "bbci.co.uk"))
        self.assertFalse(_serves(_feed_hosts(college), "bbci.co.uk"))

    def test_switching_clears_the_previous_competitions_load_caches(self):
        fetch_data.set_competition("WC")
        fetch_data._RATINGS = {"sentinel": True}
        fetch_data._OPEN = {"sentinel": True}
        fetch_data.set_competition("MLB")
        self.assertIsNone(fetch_data._RATINGS)
        self.assertIsNone(fetch_data._OPEN)

    def test_switching_clears_the_previous_competitions_market_and_news_caches(self):
        fetch_data.set_competition("WC")
        fetch_data._ODDS_CACHE.update({"t": 9e9, "data": {"stale": 1}})
        fetch_data._NEWS_CACHE.update({"t": 9e9, "data": ["stale"]})
        fetch_data._OUT_CACHE.update({"t": 9e9, "data": ["stale"]})
        fetch_data.set_competition("NHL")
        self.assertEqual(fetch_data._ODDS_CACHE, {"t": 0.0, "data": {}})
        self.assertEqual(fetch_data._NEWS_CACHE, {"t": 0.0, "data": []})
        self.assertEqual(fetch_data._OUT_CACHE, {"t": 0.0, "data": []})

    def test_an_unknown_competition_falls_back_to_the_world_cup(self):
        self.assertEqual(fetch_data.set_competition("NOT_A_COMPETITION"), "WC")
        self.assertEqual(fetch_data.COMP_KEY, "WC")
        self.assertEqual(fetch_data.RATINGS_FILE, "ratings.json")

    def test_a_lowercase_key_is_accepted(self):
        self.assertEqual(fetch_data.set_competition("mlb"), "MLB")
        self.assertEqual(fetch_data.PICKS_FILE, "picks_log_mlb.json")

    def test_every_competition_switches_without_leaving_a_stale_value(self):
        # The regression in one assertion: no reachable competition may leave a
        # derived path still naming a different one.
        for key in fetch_data.COMPETITIONS:
            with self.subTest(competition=key):
                fetch_data.set_competition(key)
                self.assertEqual(fetch_data.COMP_KEY, key)
                self.assertIs(fetch_data.COMP, fetch_data.COMPETITIONS[key])
                for name in DERIVED_PATHS:
                    self.assertIn(key.lower(), getattr(fetch_data, name))


class CompetitionContextManagerTests(unittest.TestCase):
    def setUp(self):
        self.original = fetch_data.COMP_KEY
        self.addCleanup(fetch_data.set_competition, self.original)

    def test_the_previous_competition_is_restored_on_exit(self):
        fetch_data.set_competition("WC")
        with fetch_data.competition("NCAAF") as active:
            self.assertEqual(active, "NCAAF")
            self.assertEqual(fetch_data.RATINGS_FILE, "ratings_ncaaf.json")
        self.assertEqual(fetch_data.COMP_KEY, "WC")
        self.assertEqual(fetch_data.RATINGS_FILE, "ratings.json")

    def test_the_previous_competition_is_restored_after_an_exception(self):
        # The reason to prefer this over an assignment pair: a failing
        # assertion mid-test must not leak the competition into the next test.
        fetch_data.set_competition("WC")
        with self.assertRaises(RuntimeError):
            with fetch_data.competition("MLB"):
                raise RuntimeError("boom")
        self.assertEqual(fetch_data.COMP_KEY, "WC")
        self.assertEqual(fetch_data.RATINGS_FILE, "ratings.json")

    def test_nesting_restores_each_level(self):
        fetch_data.set_competition("WC")
        with fetch_data.competition("NFL"):
            with fetch_data.competition("NHL"):
                self.assertEqual(fetch_data.COMP_KEY, "NHL")
            self.assertEqual(fetch_data.COMP_KEY, "NFL")
            self.assertEqual(fetch_data.PICKS_FILE, "picks_log_nfl.json")
        self.assertEqual(fetch_data.COMP_KEY, "WC")


class CallerDisciplineTests(unittest.TestCase):
    """Production modules must switch competition through set_competition().

    Assigning the attribute still type-checks and still half-works, so nothing
    but this test stops the original defect being reintroduced by a caller that
    copies the old spelling. Tests are exempt: several deliberately set COMP_KEY
    alone to exercise a single lookup, and RatingsLookupTests additionally
    overrides RATINGS_FILE to a temp path -- an override a full switch would
    correctly discard.
    """

    ASSIGNMENT = re.compile(r"\b(?:fetch_data|fd)\.COMP_KEY\s*=(?!=)")

    def test_no_production_module_assigns_comp_key_directly(self):
        offenders = []
        for path in sorted(Path(".").glob("*.py")):
            if path.name.startswith("test_"):
                continue
            for number, line in enumerate(
                    path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                code = line.split("#", 1)[0]   # the rule is about code, not prose
                if self.ASSIGNMENT.search(code):
                    offenders.append(f"{path.name}:{number}: {line.strip()}")
        self.assertEqual(offenders, [], "use fetch_data.set_competition(key) instead:\n"
                                        + "\n".join(offenders))

    def test_the_three_known_callers_still_switch_competition(self):
        # Guards the opposite mistake from the one above: a caller that stops
        # switching at all reads whatever competition the import happened to
        # resolve, which is the silent-wrong-data failure this whole module is
        # about. Named explicitly because each was a real fix.
        for name in ("refresh_college_talent.py", "backfill_history.py",
                     "audit_model_vs_market.py"):
            with self.subTest(module=name):
                source = Path(name).read_text(encoding="utf-8", errors="replace")
                self.assertIn("set_competition(", source)


class TestFileShapeTests(unittest.TestCase):
    """`python test_x.py` must run the same tests `python -m unittest` does.

    Six files had drifted the other way: a new test class was appended below
    the `if __name__ == "__main__"` block, so running the file directly stopped
    at unittest.main() and silently exercised only the classes above it --
    test_deploy_assets ran 1 of its 4 tests that way, test_provider_quota 59 of
    its 59 only under discovery. CI runs discovery so it was never wrong there,
    but a developer checking their work the obvious way got a fraction of the
    file with a cheerful OK.

    Same shape as the version-suffixed helpers in the front-end bundle: new
    code appended below the old rather than placed with it.
    """

    def test_no_test_class_is_defined_after_the_main_guard(self):
        import ast
        offenders = []
        for path in sorted(Path(".").glob("test_*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
            guards = [n for n in tree.body
                      if isinstance(n, ast.If) and "'__main__'" in ast.dump(n.test)]
            if not guards:
                continue
            guard = guards[-1]
            stranded = [n.name for n in tree.body
                        if isinstance(n, (ast.ClassDef, ast.FunctionDef))
                        and n.lineno > guard.lineno]
            if stranded:
                offenders.append(f"{path.name}: {', '.join(stranded)} "
                                 f"defined after unittest.main() on line {guard.lineno}")
        self.assertEqual(offenders, [],
                         "these never run under `python <file>.py`; move the "
                         "`if __name__` block to the end:\n" + "\n".join(offenders))


if __name__ == "__main__":
    unittest.main()
