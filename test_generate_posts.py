import json
import os
import shutil
import tempfile
import unittest

import generate_posts as gp

POST = {
    "id": "matchday-10-college-football-2026-08-10",
    "slug": "matchday-10-college-football-2026-08-10",
    "comp": "ncaaf", "comp_label": "College Football · Matchday 10",
    "type": "ranking", "date": "2026-08-10",
    "title": "Matchday 10: Ten Names, No New Evidence",
    "summary": "The ten teams worth watching.",
    "body": ["Ten teams."],
}


class RenderAndSitemapTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.cwd = os.getcwd()
        os.chdir(self.tmp)

    def tearDown(self):
        os.chdir(self.cwd)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write_posts(self, posts):
        with open(gp.POSTS_FILE, "w", encoding="utf-8") as f:
            json.dump(posts, f)

    def test_render_post_html_has_required_seo_tags_and_valid_json_ld(self):
        html = gp.render_post_html(POST)
        self.assertIn("<title>", html)
        self.assertIn('rel="canonical"', html)
        self.assertIn('property="og:title"', html)
        self.assertIn('property="og:image"', html)
        self.assertIn('name="twitter:image"', html)
        start = html.index('<script type="application/ld+json">') + len('<script type="application/ld+json">')
        end = html.index("</script>", start)
        ld = json.loads(html[start:end])
        self.assertEqual(ld["@type"], "Article")
        self.assertEqual(ld["headline"], POST["title"])
        self.assertNotIn("live scores", html.lower())

    def test_regenerate_sitemap_includes_base_pages_and_every_public_post(self):
        private = dict(POST, id="internal", slug="internal", comp="internal")
        self._write_posts([POST, private])
        n = gp.regenerate_sitemap()
        self.assertEqual(n, 4)  # index, legal, qa, one public post
        with open("sitemap.xml", encoding="utf-8") as f:
            xml = f.read()
        self.assertIn("qa.html", xml)
        self.assertIn(f"posts/{POST['slug']}.html", xml)
        self.assertNotIn("posts/internal.html", xml)
        self.assertTrue(os.path.exists(os.path.join(gp.POSTS_DIR, f"{POST['slug']}.html")))
        import xml.etree.ElementTree as ET
        ET.fromstring(xml)  # raises if malformed

    def test_an_empty_post_list_still_writes_a_valid_sitemap(self):
        self.assertEqual(gp.regenerate_sitemap(), 3)
        import xml.etree.ElementTree as ET
        with open("sitemap.xml", encoding="utf-8") as f:
            ET.fromstring(f.read())


if __name__ == "__main__":
    unittest.main()
