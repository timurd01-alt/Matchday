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

class HomepageReactionTests(unittest.TestCase):
    def test_homepage_hides_empty_feed_and_reads_current_publication(self):
        import shutil
        import subprocess
        node = shutil.which('node')
        if not node:
            self.skipTest('Node is needed to exercise the homepage renderer')
        core = (Path(__file__).resolve().parents[1] / 'app-1-core.js').read_text(encoding='utf-8')
        helper = core.split('function homeLatestReactionHTML(){', 1)[1].split('function renderHome(){', 1)[0]
        script = r'''
const assert=require('node:assert/strict');
const window={MATCHDAY_REACTIONS:[]};
const esc=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
''' + 'function homeLatestReactionHTML(){' + helper + r'''
assert.equal(homeLatestReactionHTML(),'');
window.MATCHDAY_REACTIONS=[{slug:'latest-week',date:'2026-11-09',title:'This week <wins>',summary:'An honest & short reflection.'},{slug:'older-week',date:'2026-11-02',title:'Older article',summary:'Older summary'}];
const card=homeLatestReactionHTML();
assert.ok(card.includes('This week &lt;wins&gt;'));
assert.ok(card.includes('An honest &amp; short reflection.'));
assert.ok(card.includes('datetime="2026-11-09"'));
assert.ok(card.includes('href="reactions/latest-week.html"'));
assert.ok(card.includes('href="?view=reactions"'));
assert.ok(!card.includes('Older article'));
window.MATCHDAY_REACTIONS=[];
assert.equal(homeLatestReactionHTML(),'');
'''
        result = subprocess.run([node, '-e', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('+homeLatestReactionHTML()', core)
