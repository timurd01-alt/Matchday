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
        self.assertIn("not betting advice", text.lower())
        self.assertEqual(post["slug"], f"nfl-{datetime.date.today().isoformat()}")

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
        start = html.index('<script type="application/ld+json">') + len('<script type="application/ld+json">')
        end = html.index("</script>", start)
        ld = json.loads(html[start:end])
        self.assertEqual(ld["@type"], "Article")
        self.assertEqual(ld["headline"], post["title"])

    def test_regenerate_sitemap_includes_base_pages_and_every_post(self):
        gp.publish_recap_if_due("NFL", "NFL", SCORECARD, AWARDS)
        n = gp.regenerate_sitemap()
        self.assertEqual(n, 10)  # index, legal, qa, content hub, 5 tactics pages, one post
        with open("sitemap.xml", encoding="utf-8") as f:
            xml = f.read()
        self.assertIn("qa.html", xml)
        self.assertIn("posts/nfl-", xml)
        import xml.etree.ElementTree as ET
        ET.fromstring(xml)  # raises if malformed


if __name__ == "__main__":
    unittest.main()
