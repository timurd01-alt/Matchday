from copy import deepcopy
from datetime import datetime, timezone
import unittest
from unittest.mock import patch
from pathlib import Path
from tempfile import TemporaryDirectory

from refresh_engine_scorecard import merge_scorecard, overdue_cards


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

    def _week(self, graded, overdue):
        rows = [{'event_name': f'W{i}', 'starts_at': '2026-11-09T23:00:00Z', 'result': 'win'}
                for i in range(graded)]
        rows += [{'event_name': f'P{i}', 'starts_at': '2026-11-10T23:00:00Z', 'result': 'pending'}
                 for i in range(overdue)]
        self.fresh['sports']['ncaam']['recent'] = rows

    def test_a_few_overdue_cards_publish_as_pending(self):
        # 2026-11-15..23: one stuck exhibition froze the whole week's record.
        self._week(graded=330, overdue=22)
        card = merge_scorecard(self.old, self.fresh, 'ncaam', self.now)['scorecard']['sports']['ncaam']
        self.assertEqual(sum(r['result'] == 'pending' for r in card['recent']), 22)
        self._week(graded=0, overdue=10)
        merge_scorecard(self.old, self.fresh, 'ncaam', self.now)

    def test_a_pile_of_overdue_cards_blocks(self):
        self._week(graded=50, overdue=11)
        with self.assertRaisesRegex(ValueError, 'not settling'):
            merge_scorecard(self.old, self.fresh, 'ncaam', self.now)

    def test_upcoming_and_old_pending_are_not_overdue(self):
        self.fresh['sports']['ncaam']['recent'] = [
            {'event_name': f'U{i}', 'starts_at': '2026-11-11T23:00:00Z', 'result': 'pending'} for i in range(20)
        ] + [{'event_name': f'O{i}', 'starts_at': '2026-11-01T23:00:00Z', 'result': 'pending'} for i in range(20)]
        self.assertEqual(overdue_cards(self.fresh['sports']['ncaam'], self.now), ([], 0))
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
