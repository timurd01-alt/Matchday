import datetime
import json
import os
import shutil
import tempfile
import unittest

import forecast_pause
import generate_posts as gp
from unittest import mock

SCORECARD = {
    "graded": 13, "model_hits": 9,
    "market_graded": 10, "market_hits": 6,
    "calibration": [{"band": "45-55", "n": 5, "hits": 3}, {"band": "55-65", "n": 6, "hits": 5}],
    "signal_quality": {
        "srs": {"n": 8, "hits": 6}, "form": {"n": 7, "hits": 2}, "elo": {"n": 3, "hits": 1},
    },
}

AWARDS = {
    "biggest_upset": {"home": "Alpha", "away": "Beta", "score_line": "10-24",
                       "winner": "Beta", "market_pct": 18},
    "best_call": {"home": "Gamma", "away": "Delta", "pick": "Gamma", "confidence": 78},
    "biggest_miss": {"home": "Epsilon", "away": "Zeta", "pick": "Epsilon", "actual": "Zeta"},
}


class RecapContentTests(unittest.TestCase):
    def test_learning_lesson_requires_a_real_pregame_lock_and_factor(self):
        match = {"id": "g1", "kickoff": "2026-08-20T20:00:00Z",
                 "home": {"name": "Alpha"}, "away": {"name": "Beta"},
                 "score": {"home": 2, "away": 1}, "watchability": 70}
        pick = {"pick_name": "Alpha", "confidence": 61, "model_hit": True,
                "locked_at": "2026-08-20T18:00:00Z", "factor_snapshot": {"elo": 24}}
        lesson = gp._learning_lesson("epl", "Premier League", "soccer", match, pick)
        self.assertTrue(lesson["hit"])
        self.assertEqual(lesson["factorLabel"], "Elo rating")
        self.assertIn("one result does not prove", lesson["principle"])
        pick["locked_at"] = "2026-08-20T21:00:00Z"
        self.assertIsNone(gp._learning_lesson("epl", "Premier League", "soccer", match, pick))

    def test_learning_lesson_fails_closed_without_grade_score_or_allowed_factor(self):
        match = {"id": "g1", "kickoff": "2026-08-20T20:00:00Z",
                 "home": {"name": "Alpha"}, "away": {"name": "Beta"},
                 "score": {"home": 2, "away": 1}}
        base = {"pick_name": "Alpha", "locked_at": "2026-08-20T18:00:00Z",
                "model_hit": True, "factor_snapshot": {"elo": 4}}
        for change in ({"model_hit": None}, {"factor_snapshot": {"unknown": 4}}):
            self.assertIsNone(gp._learning_lesson(
                "epl", "Premier League", "soccer", match, base | change))
        self.assertIsNone(gp._learning_lesson(
            "epl", "Premier League", "soccer", match | {"score": {"home": None, "away": 1}}, base))
    def test_content_sport_routes_mlb_posts_to_baseball(self):
        self.assertEqual(gp._content_sport("MLB"), "baseball")

    def test_publication_state_uses_canonical_dataset_eligibility(self):
        # With the site-wide pause lifted, the dataset marker decides -- and it
        # decides the same way for every competition.
        with mock.patch.object(forecast_pause, "PAUSE_ACTIVE", False):
            for comp in ("MLB", "EPL", "NFL"):
                for phase in ("preliminary", "lock_candidate", "locked"):
                    data = {"comp_key": comp,
                            "forecast_publication": {"state": "eligible"}}
                    match = {"status": "UPCOMING",
                             "prediction": {"publication_state": phase}}
                    self.assertFalse(gp._forecast_is_paused(data, match), comp)

    def test_site_wide_pause_withholds_every_upcoming_pick(self):
        # No competition is exempt, and an "eligible" marker cannot override it.
        for comp in ("MLB", "EPL", "NFL", "NBA"):
            data = {"comp_key": comp, "forecast_publication": {"state": "eligible"}}
            match = {"status": "UPCOMING", "prediction": {"publication_state": "locked"}}
            self.assertTrue(gp._forecast_is_paused(data, match), comp)
        # A finished game keeps the pick it was graded on.
        self.assertFalse(gp._forecast_is_paused(
            {"comp_key": "EPL"},
            {"status": "FINISHED", "prediction": {"publication_state": "locked"}}))

    def test_no_post_when_nothing_graded(self):
        self.assertIsNone(gp.build_recap_post("NFL", "NFL", {"graded": 0}, None))

    def test_recap_includes_hit_rate_calibration_signal_and_awards(self):
        post = gp.build_recap_post("NFL", "NFL", SCORECARD, AWARDS)
        self.assertIsNotNone(post)
        text = " ".join(post["body"])
        self.assertIn("9", text)
        self.assertIn("13", text)
        self.assertIn("69%", post["summary"])
        self.assertIn("calibration", text.lower())
        self.assertIn("opponent-adjusted", text)  # srs is the hottest signal (6/8)
        self.assertIn("Beta", text)  # biggest upset winner
        self.assertIn("for anyone to use", text.lower())
        self.assertEqual(post["slug"], f"nfl-{datetime.date.today().isoformat()}")
        self.assertEqual(post["record"], {"hits": 9, "graded": 13, "pct": 69})
        self.assertEqual(post["highlights"]["best_call"]["pick"], "Gamma")

    def test_recap_survives_missing_awards_and_thin_calibration(self):
        thin = {"graded": 6, "model_hits": 4, "market_graded": 0, "market_hits": 0,
                "calibration": [{"band": "55-65", "n": 2, "hits": 1}], "signal_quality": {}}
        post = gp.build_recap_post("NBA", "NBA", thin, None)
        self.assertIsNotNone(post)
        self.assertGreaterEqual(len(post["body"]), 2)  # hit-rate paragraph + disclaimer, at least


class PublishGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.cwd = os.getcwd()
        os.chdir(self.tmp)

    def tearDown(self):
        os.chdir(self.cwd)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_first_post_needs_minimum_graded_picks(self):
        self.assertFalse(gp.should_publish("NFL", {"graded": 2}))
        self.assertTrue(gp.should_publish("NFL", {"graded": 5}))

    def test_second_post_gated_on_days_and_new_results(self):
        today = datetime.date.today().isoformat()
        with open(gp.STATE_FILE, "w", encoding="utf-8") as f:
            json.dump({"NFL": {"last_post_date": today, "graded_at_post": 10}}, f)
        # same day, plenty of new results -- still blocked by the day gate
        self.assertFalse(gp.should_publish("NFL", {"graded": 20}))
        # far enough back in time, but not enough new graded picks
        old = (datetime.date.today() - datetime.timedelta(days=10)).isoformat()
        with open(gp.STATE_FILE, "w", encoding="utf-8") as f:
            json.dump({"NFL": {"last_post_date": old, "graded_at_post": 10}}, f)
        self.assertFalse(gp.should_publish("NFL", {"graded": 12}))
        self.assertTrue(gp.should_publish("NFL", {"graded": 16}))

    def test_publish_recap_if_due_writes_post_json_state_and_html_file(self):
        post = gp.publish_recap_if_due("NFL", "NFL", SCORECARD, AWARDS)
        self.assertIsNotNone(post)
        self.assertEqual(gp.load_posts(), [post])
        state = gp.load_state()
        self.assertEqual(state["NFL"]["graded_at_post"], 13)
        self.assertTrue(os.path.exists(os.path.join(gp.POSTS_DIR, f"{post['slug']}.html")))
        # calling again immediately (same day, gate not met) publishes nothing new
        again = gp.publish_recap_if_due("NFL", "NFL", SCORECARD, AWARDS)
        self.assertIsNone(again)
        self.assertEqual(len(gp.load_posts()), 1)

    def test_publishing_a_recap_keeps_editorial_all_board_posts(self):
        # Regression: publish_recap_if_due rewrites posts.json from a filtered
        # copy of the existing list. That filter used the competition gate,
        # which rejects "all", so every editorial desk post (weekly scorecard,
        # market audit, availability tracker, methodology note) was deleted the
        # first time any competition published -- taking out the post id
        # test_analysis_mode pins and failing the hourly refresh's test gate.
        editorial = {"id": "refining-the-record-2026-07-26", "slug": "refining-the-record",
                     "comp": "all", "type": "methodology", "date": "2026-07-26",
                     "title": "Refining the record", "body": ""}
        private = {"id": "internal-note", "slug": "internal-note", "comp": "internal",
                   "date": "2026-07-26", "title": "Internal", "body": ""}
        with open(gp.POSTS_FILE, "w", encoding="utf-8") as f:
            json.dump([editorial, private], f)

        post = gp.publish_recap_if_due("NFL", "NFL", SCORECARD, AWARDS)
        self.assertIsNotNone(post)

        ids = [p["id"] for p in gp.load_posts()]
        self.assertIn("refining-the-record-2026-07-26", ids)
        self.assertIn(post["id"], ids)
        # the wider retention filter must not become a way to republish
        # anything that is not on the public allowlist
        self.assertNotIn("internal-note", ids)

    def test_editorial_scope_is_not_a_publishable_competition(self):
        # "all" may be RETAINED but must never be treated as a competition that
        # can publish its own recap.
        self.assertFalse(gp._is_public_comp("all"))
        self.assertIsNone(gp.publish_recap_if_due("all", "All sports", SCORECARD, AWARDS))

    def test_mlb_publishes_public_recap(self):
        post = gp.publish_recap_if_due("MLB", "MLB", SCORECARD, AWARDS)
        self.assertIsNotNone(post)
        self.assertEqual(post["comp"], "MLB")
        self.assertEqual(gp.load_posts(), [post])


class RenderAndSitemapTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.cwd = os.getcwd()
        os.chdir(self.tmp)

    def tearDown(self):
        os.chdir(self.cwd)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_render_post_html_has_required_seo_tags_and_valid_json_ld(self):
        post = gp.build_recap_post("NFL", "NFL", SCORECARD, AWARDS)
        html = gp.render_post_html(post)
        self.assertIn("<title>", html)
        self.assertIn('rel="canonical"', html)
        self.assertIn('property="og:title"', html)
        self.assertIn('property="og:image"', html)
        self.assertIn('name="twitter:image"', html)
        start = html.index('<script type="application/ld+json">') + len('<script type="application/ld+json">')
        end = html.index("</script>", start)
        ld = json.loads(html[start:end])
        self.assertEqual(ld["@type"], "Article")
        self.assertEqual(ld["headline"], post["title"])
        self.assertIn("View matchup", html)
        self.assertIn("Open scorecard", html)
        self.assertIn("sport=nfl&amp;view=score", html)
        self.assertIn("pregame predictions, market context and postgame grading", html)
        self.assertNotIn("live scores", html.lower())

    def test_regenerate_sitemap_includes_base_pages_and_every_post(self):
        gp.publish_recap_if_due("NFL", "NFL", SCORECARD, AWARDS)
        n = gp.regenerate_sitemap()
        self.assertEqual(n, 4)  # index, legal, qa, one post
        with open("sitemap.xml", encoding="utf-8") as f:
            xml = f.read()
        self.assertIn("qa.html", xml)
        self.assertIn("posts/nfl-", xml)
        import xml.etree.ElementTree as ET
        ET.fromstring(xml)  # raises if malformed

    def test_public_content_feed_is_compact_and_includes_mlb(self):
        # Feed shape, not pause behaviour: give it a publishable slate to shape.
        pause = mock.patch.object(forecast_pause, "PAUSE_ACTIVE", False)
        pause.start()
        self.addCleanup(pause.stop)
        match = {
            "id": "game-1", "kickoff": "2026-07-25T20:00:00Z", "status": "UPCOMING",
            "home": {"name": "Alpha", "code": "ALP"}, "away": {"name": "Beta", "code": "BET"},
            "score": {"home": None, "away": None, "winner": None, "reg": {}},
            "prediction": {"pick": "h", "pick_name": "Alpha", "confidence": 61,
                           "note": "Small lean", "why": {"elo": 4}, "private": "drop me"},
            "watchability": 72, "news": ["large dashboard-only payload"],
        }
        for key in ("nfl", "mlb"):
            with open(f"data_{key}.json", "w", encoding="utf-8") as f:
                json.dump({"competition": key.upper(), "updated": "2026-07-25T12:00:00Z",
                           # The pipeline now stamps this on every dataset, so
                           # both competitions carry the same marker.
                           "forecast_publication": {"state": "eligible"},
                           "scorecard": SCORECARD, "matches": [match], "standings": ["drop me"]}, f)
        self.assertEqual(gp.generate_public_content_feed(), 2)
        with open(gp.CONTENT_FEED_FILE, encoding="utf-8") as f:
            feed = json.load(f)
        self.assertEqual([item["compKey"] for item in feed["datasets"]], ["nfl", "mlb"])
        public_match = feed["datasets"][0]["matches"][0]
        self.assertNotIn("news", public_match)
        self.assertNotIn("private", public_match["prediction"])

    def test_public_content_feed_keeps_only_verified_fixture_receipts(self):
        matches = []
        picks = []
        for fixture_id, eligible, status in (
                ("verified-game", True, "verified"),
                ("legacy-game", False, "quarantined")):
            matches.append({
                "id": fixture_id, "kickoff": "2026-07-25T20:00:00Z", "status": "FINISHED",
                "stage": "Week 1", "venue": "Example Field",
                "home": {"name": "Alpha"}, "away": {"name": "Beta"},
                # Knockout-style final: display score stays tied while the
                # locked pick is graded on advancement.
                "score": {"home": 1, "away": 1, "winner": "h"},
                "prediction": (None if fixture_id == "verified-game" else
                               {"pick": "a", "pick_name": "Beta", "confidence": 99}),
            })
            picks.append({"fixture_id": fixture_id, "integrity_eligible": eligible,
                          "integrity_status": status, "legacy": not eligible,
                          "pick": "h", "pick_name": "Alpha", "confidence": 61,
                          "model_hit": True, "result": "hit",
                          "factor_snapshot": {"elo": 4}, "locked_at": "2026-07-25T18:00:00Z"})
        with open("data_mlb.json", "w", encoding="utf-8") as f:
            json.dump({"competition": "MLB", "updated": "2026-07-25T20:30:00Z",
                       "scorecard": {"graded": 1, "model_hits": 1, "picks": picks},
                       "matches": matches}, f)
        self.assertEqual(gp.generate_public_content_feed(), 1)
        with open(gp.CONTENT_FEED_FILE, encoding="utf-8") as f:
            dataset = json.load(f)["datasets"][0]
        self.assertEqual(dataset["scorecard"]["verified_fixture_ids"], ["verified-game"])
        self.assertNotIn("picks", dataset["scorecard"])
        compact = {match["id"]: match for match in dataset["matches"]}
        self.assertEqual(compact["verified-game"]["stage"], "Week 1")
        self.assertEqual(compact["verified-game"]["venue"], "Example Field")
        self.assertEqual(compact["verified-game"]["official_pick"]["pick_name"], "Alpha")
        self.assertEqual(compact["verified-game"]["official_pick"]["confidence"], 61)
        self.assertEqual(compact["verified-game"]["score"],
                         {"home": 1, "away": 1, "winner": "h"})
        self.assertTrue(compact["verified-game"]["official_pick"]["model_hit"])
        self.assertNotIn("legacy-game", compact)

    def test_public_content_feed_emits_one_deterministic_lesson_per_sport(self):
        matches, picks = [], []
        for fixture_id, kickoff, watchability in (
                ("older", "2026-08-19T20:00:00Z", 99),
                ("newer", "2026-08-20T20:00:00Z", 40)):
            matches.append({"id": fixture_id, "kickoff": kickoff, "status": "FINISHED",
                            "home": {"name": "Alpha"}, "away": {"name": "Beta"},
                            "score": {"home": 2, "away": 1, "winner": "h"},
                            "watchability": watchability})
            picks.append({"fixture_id": fixture_id, "integrity_eligible": True,
                          "integrity_status": "verified", "legacy": False,
                          "pick": "h", "pick_name": "Alpha", "confidence": 61,
                          "model_hit": True, "result": "hit",
                          "factor_snapshot": {"elo": 20},
                          "locked_at": kickoff.replace("20:00", "18:00")})
        with open("data_epl.json", "w", encoding="utf-8") as f:
            json.dump({"competition": "Premier League", "scorecard": {"picks": picks},
                       "matches": matches}, f)
        gp.generate_public_content_feed()
        with open(gp.CONTENT_FEED_FILE, encoding="utf-8") as f:
            lessons = json.load(f)["learnLessons"]
        self.assertEqual(len(lessons), 1)
        self.assertEqual(lessons[0]["fixtureId"], "newer")
        self.assertEqual(lessons[0]["compKey"], "epl")

    def test_public_content_feed_excludes_in_progress_games(self):
        live = {
            "id": "game-live", "kickoff": "2026-07-25T20:00:00Z", "status": "LIVE",
            "home": {"name": "Alpha"}, "away": {"name": "Beta"},
            "score": {"home": 1, "away": 0},
            "prediction": {"pick": "h", "pick_name": "Alpha", "confidence": 61},
        }
        with open("data_mlb.json", "w", encoding="utf-8") as f:
            json.dump({"competition": "MLB", "updated": "2026-07-25T20:30:00Z",
                       "scorecard": SCORECARD, "matches": [live]}, f)
        self.assertEqual(gp.generate_public_content_feed(), 1)
        with open(gp.CONTENT_FEED_FILE, encoding="utf-8") as f:
            feed = json.load(f)
        self.assertEqual(feed["datasets"][0]["matches"], [])

    def test_public_content_feed_excludes_stale_unmarked_mlb_forecasts_but_keeps_receipts(self):
        upcoming = {
            "id": "future", "kickoff": "2026-08-18T20:00:00Z", "status": "UPCOMING",
            "home": {"name": "Alpha"}, "away": {"name": "Beta"},
            "prediction": {"publication_state": "locked", "pick": "h",
                           "pick_name": "Alpha", "confidence": 88},
        }
        finished = {
            "id": "receipt", "kickoff": "2026-08-16T20:00:00Z", "status": "FINISHED",
            "home": {"name": "Gamma"}, "away": {"name": "Delta"},
            "score": {"home": 4, "away": 2, "winner": "h"},
        }
        receipt = {"fixture_id": "receipt", "integrity_eligible": True,
                   "integrity_status": "verified", "legacy": False,
                   "pick": "h", "pick_name": "Gamma", "confidence": 57,
                   "model_hit": True, "result": "hit", "locked_at": "2026-08-16T18:00:00Z"}
        with open("data_mlb.json", "w", encoding="utf-8") as f:
            json.dump({"comp_key": "MLB", "competition": "MLB",
                       "scorecard": {"graded": 1, "model_hits": 1, "picks": [receipt]},
                       "matches": [upcoming, finished]}, f)
        self.assertEqual(gp.generate_public_content_feed(), 1)
        with open(gp.CONTENT_FEED_FILE, encoding="utf-8") as f:
            matches = json.load(f)["datasets"][0]["matches"]
        self.assertEqual([match["id"] for match in matches], ["receipt"])
        self.assertEqual(matches[0]["official_pick"]["pick_name"], "Gamma")


if __name__ == "__main__":
    unittest.main()
