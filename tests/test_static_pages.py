"""The crawlable pages build_static_pages.py writes for teams, games and Learn.

Nothing here names a team or a score: the snapshot is regenerated every week,
so the tests check that the pages agree with whatever it holds.
"""

import pathlib
import re
import shutil
import tempfile
import unittest

import build_static_pages as bsp

ROOT = pathlib.Path(__file__).resolve().parent.parent


class Helpers(unittest.TestCase):
    def test_slug_is_plain_ascii_and_keeps_qualifiers_apart(self):
        self.assertEqual(bsp.slug("Miami (OH) RedHawks"), "miami-oh-redhawks")
        self.assertEqual(bsp.slug("Texas A&M Aggies"), "texas-am-aggies")
        self.assertEqual(bsp.slug("Hawai'i Rainbow Warriors"), "hawaii-rainbow-warriors")
        self.assertEqual(bsp.slug("San José State Spartans"), "san-jose-state-spartans")

    def test_eastern_time_follows_daylight_saving(self):
        # 23:00 UTC is 19:00 in October (daylight) and 18:00 in late November.
        self.assertEqual(bsp.eastern("2026-10-17T23:00:00Z").hour, 19)
        self.assertEqual(bsp.eastern("2026-11-21T23:00Z").hour, 18)
        # The change itself: 06:00 UTC on the first Sunday of November.
        self.assertEqual(bsp.eastern("2026-11-01T05:59Z").hour, 1)
        self.assertEqual(bsp.eastern("2026-11-01T06:00Z").hour, 1)
        self.assertEqual(bsp.eastern("2026-03-08T07:00Z").hour, 3)

    def test_a_late_game_belongs_to_the_evening_it_started(self):
        # 00:00 UTC is the previous evening in the US, which is the date a fan
        # looks the game up by and the date its address must carry.
        self.assertEqual(f"{bsp.eastern('2026-11-17T00:00:00Z'):%Y-%m-%d}", "2026-11-16")

    def test_an_unreadable_time_is_none_not_an_exception(self):
        self.assertIsNone(bsp.eastern(None))
        self.assertIsNone(bsp.eastern("TBD"))


class LearnSource(unittest.TestCase):
    def test_every_lesson_and_term_is_read_from_the_app(self):
        lessons, glossary = bsp.load_learn(ROOT / "app-learn.js")
        self.assertGreaterEqual(len(lessons), 8)
        for lesson in lessons:
            self.assertTrue(lesson["title"] and lesson["hook"], lesson["id"])
            self.assertTrue(lesson["sections"], f"{lesson['id']} has no prose to publish")
        self.assertGreaterEqual(len(glossary), 30)
        self.assertEqual(len({bsp.slug(t) for t, _ in glossary}), len(glossary), "two terms share an anchor")


class BuiltSite(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = pathlib.Path(tempfile.mkdtemp())
        shutil.copy2(ROOT / "sitemap.xml", cls.tmp / "sitemap.xml")
        cls.snap = bsp.load_snapshot(ROOT / "matchday-cfb-snapshot.js")
        site = bsp.render(cls.tmp, "test", keep=True)
        cls.pages, cls.count = site.pages, len(site.urls)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_every_rated_team_has_a_page(self):
        for key, cfg in bsp.SPORTS.items():
            teams = (self.snap.get(cfg["rankings"]) or {}).get("rankings") or []
            self.assertTrue(teams, f"{key} has no rankings in the snapshot")
            slugs = {bsp.slug(t["name"]) for t in teams}
            self.assertEqual(len(slugs), len(teams), f"two {key} teams share an address")
            for s in slugs:
                self.assertIn(f"/{cfg['path']}/teams/{s}/", self.pages)

    def test_no_internal_link_is_broken(self):
        broken = set()
        for html in self.pages.values():
            for href in re.findall(r'href="(/[^"#?]*)', html):
                if href.endswith("/") and href != "/" and href not in self.pages:
                    broken.add(href)
        self.assertFalse(broken, sorted(broken)[:10])

    def test_each_page_names_itself_once(self):
        canonicals = set()
        for path, html in self.pages.items():
            self.assertEqual(html.count("<h1>"), 1, path)
            self.assertRegex(html, r"<title>[^<]{10,}</title>", path)
            self.assertRegex(html, r'<meta name="description" content="[^"]{40,}"', path)
            canonical = re.search(r'<link rel="canonical" href="([^"]+)"', html).group(1)
            self.assertEqual(canonical, bsp.BASE_URL + path.lstrip("/"))
            canonicals.add(canonical)
        self.assertEqual(len(canonicals), len(self.pages))

    def test_a_live_forecast_is_never_presented_as_a_locked_pick(self):
        forecasts = [h for h in self.pages.values()
                     if "live forecast</span>" in h or "forecast, awaiting result</span>" in h]
        self.assertTrue(forecasts, "no upcoming game produced a forecast page")
        for html in forecasts:
            self.assertIn("not a frozen card", html)
            self.assertNotIn("Locked pick", html)

    def test_a_hit_rate_is_always_shown_with_what_was_expected(self):
        # The scorecard's own caveat: the cards are mostly favourites, so the
        # hit rate alone overstates the model.
        for path, html in self.pages.items():
            for tile in re.findall(r'<div class="pgTile"><span>Hit rate</span>.*?</div>', html):
                self.assertIn("expected", tile, path)

    def test_the_sitemap_keeps_what_was_there_and_adds_every_page(self):
        sitemap = (self.tmp / "sitemap.xml").read_text(encoding="utf-8")
        before = re.findall(r"<loc>([^<]+)</loc>", (ROOT / "sitemap.xml").read_text(encoding="utf-8"))
        locs = re.findall(r"<loc>([^<]+)</loc>", sitemap)
        for url in before:
            self.assertIn(url, locs)
        self.assertEqual(len(locs), len(before) + self.count)
        self.assertEqual(len(set(locs)), len(locs))
        self.assertEqual(self.count, len(self.pages))

    def test_writing_the_sitemap_twice_does_not_duplicate_entries(self):
        site = bsp.Site(self.tmp, "test")
        site.urls = [(bsp.BASE_URL + path.lstrip("/"), "", "daily", "0.5") for path in self.pages]
        bsp._write_sitemap(site)
        locs = re.findall(r"<loc>([^<]+)</loc>", (self.tmp / "sitemap.xml").read_text(encoding="utf-8"))
        self.assertEqual(len(set(locs)), len(locs))


class StartedGames(unittest.TestCase):
    def test_a_game_that_has_started_leaves_the_upcoming_lists_but_keeps_its_page(self):
        pick = {"sport": "ncaaf", "home": "Home State Owls", "away": "Away Tech Bears",
                "kickoff": "2026-11-21T20:30:00Z", "model_pct": 60.0, "pick_name": "Home State Owls"}
        snap = {"MATCHDAY_TRDLAB_PICKS": [pick]}
        before = bsp.Sport("ncaaf", snap, now=bsp.eastern("2026-11-21T20:00:00Z"))
        after = bsp.Sport("ncaaf", snap, now=bsp.eastern("2026-11-21T21:00:00Z"))
        self.assertEqual(len(before.upcoming()), 1)
        self.assertEqual(len(after.upcoming()), 0)
        self.assertEqual(list(after.games), ["2026-11-21-away-tech-bears-at-home-state-owls"])


class EmptySnapshot(unittest.TestCase):
    def test_a_snapshot_with_no_ratings_still_builds_the_field_guide(self):
        tmp = pathlib.Path(tempfile.mkdtemp())
        try:
            empty = tmp / "snapshot.js"
            empty.write_text("  const MATCHDAY_CFB_RANKINGS={};\n", encoding="utf-8")
            out = tmp / "site"
            snap = bsp.load_snapshot(empty)
            self.assertEqual(snap, {"MATCHDAY_CFB_RANKINGS": {}})
            site = bsp.Site(out, "test")
            sports = {key: bsp.Sport(key, snap) for key in bsp.SPORTS}
            bsp._learn_pages(site, sports, "2026-01-01T00:00:00")
            self.assertTrue((out / "learn" / "index.html").is_file())
            self.assertTrue((out / "learn" / "glossary" / "index.html").is_file())
            self.assertFalse(any(s.teams or s.games for s in sports.values()))
            # Every lesson lists every lesson beside it, marking the one open,
            # so a lesson page uses its width instead of leaving half empty.
            lessons, _ = bsp.load_learn()
            for i, lesson in enumerate(lessons):
                html = (out / "learn" / bsp.slug(lesson["title"]) / "index.html").read_text(encoding="utf-8")
                self.assertIn('<aside class="pgRail"', html)
                self.assertEqual(html.count("<li><a "), len(lessons))
                self.assertEqual(html.count('aria-current="page"'), 1)
                self.assertIn(f'<li><a href="/learn/{bsp.slug(lesson["title"])}/" aria-current="page">', html)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class Wiring(unittest.TestCase):
    def test_the_deploy_builds_the_pages_after_the_sitemap_is_copied(self):
        workflow = (ROOT / ".github" / "workflows" / "deploy.yml").read_text(encoding="utf-8")
        self.assertIn("python build_static_pages.py _site", workflow)
        self.assertLess(workflow.index("cp robots.txt sitemap.xml _site/"),
                        workflow.index("python build_static_pages.py _site"))

    def test_the_welcome_page_links_to_the_hubs(self):
        # The sitemap lists the pages; a link from the front page is what
        # tells a crawler they belong to the site.
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        for href in ("learn/", "college-football/", "college-basketball/"):
            self.assertIn(f'href="{href}"', html)


if __name__ == "__main__":
    unittest.main()
