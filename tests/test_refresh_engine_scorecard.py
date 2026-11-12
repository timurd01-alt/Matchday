from copy import deepcopy
from datetime import datetime, timezone
import unittest
from unittest.mock import patch
from pathlib import Path
from tempfile import TemporaryDirectory

from refresh_engine_scorecard import merge_scorecard


class RefreshScorecardTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 11, 18, tzinfo=timezone.utc)
        self.old = {'generated_at': '2026-11-10T21:00:00Z', 'picks': [{'probability': .8}],
                    'scorecard': {'caveat': 'caution', 'scope': {}, 'sports': {
                        'ncaaf': {'record': {'picks': 99}},
                        'ncaam': {'available': True, 'record': {'picks': 1}}}}}
        self.fresh = {'caveat': 'caution', 'scope': {}, 'sports': {'ncaam': {
            'available': True, 'record': {'picks': 2}, 'recent': [],
            'versus_market': {'beat_market_pct': 50.8,
                              'agreed_with_market': {'picks': 1, 'wins': 1, 'losses': 0},
                              'disagreed_with_market': {'picks': 1, 'wins': 0, 'losses': 1}},
            'conviction': {'outright_disagreements': {'picks': 1, 'wins': 0, 'losses': 1}}}}}

    def test_market_agreement_split_is_published(self):
        result = merge_scorecard(self.old, self.fresh, 'ncaam', self.now)
        card = result['scorecard']['sports']['ncaam']
        self.assertEqual(card['versus_market']['agreed_with_market']['picks'], 1)
        self.assertEqual(card['versus_market']['disagreed_with_market']['picks'], 1)
        self.assertEqual(card['conviction']['outright_disagreements']['picks'], 1)

    def test_refuses_card_missing_market_split(self):
        for key in ('agreed_with_market', 'disagreed_with_market'):
            fresh = deepcopy(self.fresh)
            del fresh['sports']['ncaam']['versus_market'][key]
            with self.assertRaisesRegex(ValueError, key):
                merge_scorecard(self.old, fresh, 'ncaam', self.now)
        fresh = deepcopy(self.fresh)
        del fresh['sports']['ncaam']['conviction']
        with self.assertRaisesRegex(ValueError, 'outright'):
            merge_scorecard(self.old, fresh, 'ncaam', self.now)

    def test_refuses_shrinking_market_split(self):
        self.old['scorecard']['sports']['ncaam']['versus_market'] = {'disagreed_with_market': {'picks': 5}}
        with self.assertRaisesRegex(ValueError, 'shrank'):
            merge_scorecard(self.old, self.fresh, 'ncaam', self.now)

    def test_only_requested_scorecard_changes(self):
        saved = deepcopy(self.old)
        result = merge_scorecard(self.old, self.fresh, 'ncaam', self.now)
        self.assertEqual(self.old, saved)
        self.assertEqual(result['generated_at'], saved['generated_at'])
        self.assertEqual(result['picks'], saved['picks'])
        self.assertEqual(result['scorecard']['sports']['ncaaf'], saved['scorecard']['sports']['ncaaf'])
        self.assertEqual(result['scorecard']['sports']['ncaam']['versus_market']['beat_market_pct'], 50.8)

    def test_noop_does_not_redate(self):
        first = merge_scorecard(self.old, self.fresh, 'ncaam', self.now)
        self.assertEqual(merge_scorecard(first, self.fresh, 'ncaam', self.now.replace(hour=19)), first)

    def test_refuses_regression_and_unavailable(self):
        for card in ({'available': False}, {'available': True, 'record': {'picks': 0}}):
            self.fresh['sports']['ncaam'] = card
            with self.assertRaises(ValueError):
                merge_scorecard(self.old, self.fresh, 'ncaam', self.now)

    def test_refuses_overdue_but_allows_upcoming(self):
        row = {'event_name': 'A at B', 'starts_at': '2026-11-10T23:00:00Z', 'result': 'pending'}
        self.fresh['sports']['ncaam']['recent'] = [row]
        with self.assertRaisesRegex(ValueError, 'Overdue'):
            merge_scorecard(self.old, self.fresh, 'ncaam', self.now)
        row['starts_at'] = '2026-11-11T23:00:00Z'
        merge_scorecard(self.old, self.fresh, 'ncaam', self.now)

    def test_methodology_change_requires_full_export(self):
        self.fresh['caveat'] = 'different'
        with self.assertRaisesRegex(ValueError, 'methodology'):
            merge_scorecard(self.old, self.fresh, 'ncaam', self.now)

    def test_snapshot_update_preserves_other_blocks_without_fetching(self):
        import build_cfb_snapshot as builder
        with TemporaryDirectory() as folder:
            path = Path(folder) / 'snapshot.js'
            path.write_text('before\n  const MATCHDAY_TRDLAB_SCORECARD={};\nafter\n', encoding='utf-8')
            with patch.object(builder.trdlab_handoff, 'load', return_value={'scorecard': self.fresh}), patch.object(builder.ap_poll, 'refresh', side_effect=AssertionError('network')):
                builder.build_scorecard(path)
            output = path.read_text(encoding='utf-8')
            self.assertTrue(output.startswith('before\n'))
            self.assertTrue(output.endswith('\nafter\n'))
            self.assertIn('50.8', output)
