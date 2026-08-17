import datetime
import json
import os
import shutil
import tempfile
import unittest

import generate_posts as gp

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
    def test_content_sport_routes_mlb_posts_to_baseball(self):
        self.assertEqual(gp._content_sport("MLB"), "baseball")

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
        self.assertIn("See model prediction", html)
        self.assertIn("Open scorecard", html)
        self.assertIn("Explore similar games", html)
        self.assertIn("sport=nfl&amp;view=edge", html)
        self.assertIn("pregame predictions, market context and postgame grading", html)
        self.assertNotIn("live scores", html.lower())

    def test_regenerate_sitemap_includes_base_pages_and_every_post(self):
        gp.publish_recap_if_due("NFL", "NFL", SCORECARD, AWARDS)
        n = gp.regenerate_sitemap()
        self.assertEqual(n, 10)  # index, legal, qa, content hub, 5 public tactics pages, one post
        with open("sitemap.xml", encoding="utf-8") as f:
            xml = f.read()
        self.assertIn("qa.html", xml)
        self.assertIn("posts/nfl-", xml)
        self.assertIn("tactics-baseball.html", xml)
        import xml.etree.ElementTree as ET
        ET.fromstring(xml)  # raises if malformed

    def test_public_content_feed_is_compact_and_includes_mlb(self):
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
