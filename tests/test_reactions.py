import json
from pathlib import Path
import tempfile
import unittest

from build_reactions import build


class ReactionsTests(unittest.TestCase):
    def test_only_published_entries_link_to_escaped_articles_in_date_order(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / 'reactions/source'
            source.mkdir(parents=True)
            post = dict(title='A <reaction>', summary='A "summary"', author='Timur', date='2026-11-02', status='published', body=['<script>alert(1)</script>'])
            (source / 'first.json').write_text(json.dumps(post), encoding='utf-8')
            (source / 'second.json').write_text(json.dumps(dict(post, date='2026-11-09')), encoding='utf-8')
            (source / 'draft.json').write_text(json.dumps(dict(post, status='draft')), encoding='utf-8')
            out = root / 'public'
            feed = build(root, out)
            self.assertEqual([p['slug'] for p in feed], ['second', 'first'])
            for p in feed:
                page = (out / 'reactions' / (p['slug']+'.html')).read_text(encoding='utf-8')
                self.assertIn('&lt;script&gt;', page)
                self.assertNotIn('<script>alert', page)
                self.assertIn('../?view=reactions', page)
            self.assertFalse((out / 'reactions/draft.html').exists())
            self.assertFalse((out / 'reactions/source').exists())

    def test_empty_feed_is_valid(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual(build(folder), [])
            self.assertIn('= [];', (Path(folder) / 'reactions-data.js').read_text())

    def test_invalid_publication_fails_before_writing_feed(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'reactions/source'
            source.mkdir(parents=True)
            (source / 'bad.json').write_text(json.dumps(dict(status='published', date='invalid')))
            with self.assertRaises(ValueError):
                build(folder)
            self.assertFalse((Path(folder) / 'reactions-data.js').exists())
