import unittest

from clv_report import (MIN_DATE_BLOCKS, MIN_FIXTURES, MIN_LEAD_MINUTES,
                        _lead_minutes, movement, summarize)


def row(fixture_id="f1", pick="h", lock=.50, close=.55, opening=None,
        kickoff="2026-11-10T23:00:00Z", locked_at="2026-11-10T20:00:00Z",
        competition="NCAAM"):
    other = "a"
    payload = {
        "fixture_id": fixture_id, "lock_event_id": f"lock-{fixture_id}",
        "competition": competition, "kickoff": kickoff, "locked_at": locked_at,
        "model_independent": {pick: .60, other: .40},
        "lock_market": {pick: lock, other: round(1 - lock, 6)},
        "closing_market": {pick: close, other: round(1 - close, 6)},
    }
    if opening is not None:
        payload["opening_market"] = {pick: opening, other: round(1 - opening, 6)}
    return payload


def spread(count, delta, *, blocks=None, lead_hours=3):
    """`count` fixtures each moving `delta`, spread over `blocks` game-dates."""
    blocks = blocks if blocks is not None else count
    out = []
    for index in range(count):
        day = 10 + (index % blocks)
        out.append(row(fixture_id=f"f{index}",
                       lock=.50, close=round(.50 + delta, 6),
                       kickoff=f"2026-11-{day:02d}T23:00:00Z",
                       locked_at=f"2026-11-{day:02d}T{23 - lead_hours:02d}:00:00Z"))
    return out


class MovementTest(unittest.TestCase):
    def test_movement_is_measured_on_the_picked_side(self):
        self.assertAlmostEqual(movement(row(pick="h", lock=.50, close=.57)), .07)

    def test_movement_against_the_pick_is_negative(self):
        self.assertAlmostEqual(movement(row(pick="h", lock=.60, close=.52)), -.08)

    def test_missing_closing_market_yields_none(self):
        item = row()
        del item["closing_market"]
        self.assertIsNone(movement(item))

    def test_movement_from_opening_uses_the_opening_price(self):
        item = row(lock=.50, close=.60, opening=.45)
        self.assertAlmostEqual(movement(item, frm="opening_market"), .15)

    def test_pick_absent_from_market_yields_none(self):
        item = row(pick="h")
        item["closing_market"] = {"a": .5, "d": .5}
        self.assertIsNone(movement(item))

    def test_lead_minutes(self):
        self.assertEqual(_lead_minutes(row(kickoff="2026-11-10T23:00:00Z",
                                           locked_at="2026-11-10T21:30:00Z")), 90.0)


class SummaryTest(unittest.TestCase):
    def test_consistent_positive_movement_is_detected(self):
        summary = summarize(spread(MIN_FIXTURES + 20, .01))
        self.assertEqual(summary["verdict"]["state"], "market_moves_toward_matchday")
        self.assertGreater(summary["ci95"][0], 0)
        self.assertEqual(summary["share_positive"], 1.0)

    def test_consistent_negative_movement_is_detected(self):
        summary = summarize(spread(MIN_FIXTURES + 20, -.01))
        self.assertEqual(summary["verdict"]["state"], "market_moves_against_matchday")
        self.assertLess(summary["ci95"][1], 0)

    def test_noise_reports_no_detectable_edge(self):
        rows = []
        for index in range(MIN_FIXTURES + 20):
            day = 10 + (index % (MIN_DATE_BLOCKS + 5))
            rows.append(row(fixture_id=f"f{index}", lock=.50,
                            close=.51 if index % 2 else .49,
                            kickoff=f"2026-11-{day:02d}T23:00:00Z",
                            locked_at=f"2026-11-{day:02d}T20:00:00Z"))
        self.assertEqual(summarize(rows)["verdict"]["state"], "no_detectable_edge")

    def test_small_sample_gets_no_verdict_even_when_lopsided(self):
        summary = summarize(spread(12, .05))
        self.assertEqual(summary["verdict"]["state"], "insufficient_evidence")

    def test_enough_fixtures_but_too_few_game_dates_is_insufficient(self):
        summary = summarize(spread(MIN_FIXTURES + 20, .01, blocks=3))
        self.assertEqual(summary["verdict"]["state"], "insufficient_evidence")
        self.assertIn("game-dates", summary["verdict"]["detail"])

    def test_late_locks_are_not_measurable_regardless_of_movement(self):
        """A pick locked at the bell has nothing to be right early about."""
        rows = []
        for index in range(MIN_FIXTURES + 20):
            day = 10 + (index % (MIN_DATE_BLOCKS + 5))
            rows.append(row(fixture_id=f"f{index}", lock=.50, close=.60,
                            kickoff=f"2026-11-{day:02d}T23:00:00Z",
                            locked_at=f"2026-11-{day:02d}T22:55:00Z"))
        verdict = summarize(rows)["verdict"]
        self.assertEqual(verdict["state"], "not_measurable")
        self.assertIn("minute floor", verdict["detail"])

    def test_lead_floor_is_applied_on_the_median_not_a_single_late_lock(self):
        rows = spread(MIN_FIXTURES + 20, .01)
        rows[0]["locked_at"] = rows[0]["kickoff"]
        self.assertEqual(summarize(rows)["verdict"]["state"], "market_moves_toward_matchday")

    def test_empty_input_is_safe(self):
        summary = summarize([])
        self.assertEqual(summary["n"], 0)
        self.assertIsNone(summary["mean_movement_toward_pick"])
        self.assertEqual(summary["verdict"]["state"], "insufficient_evidence")

    def test_interval_is_deterministic_across_runs(self):
        rows = spread(MIN_FIXTURES + 20, .008)
        self.assertEqual(summarize(rows)["ci95"], summarize(rows)["ci95"])

    def test_rows_without_market_data_are_excluded_not_counted_as_zero(self):
        rows = spread(MIN_FIXTURES + 20, .01)
        for item in rows[:10]:
            del item["closing_market"]
        summary = summarize(rows)
        self.assertEqual(summary["n"], MIN_FIXTURES + 10)
        self.assertEqual(summary["negative"], 0)

    def test_lead_floor_constant_is_meaningful(self):
        self.assertGreaterEqual(MIN_LEAD_MINUTES, 1.0)


if __name__ == "__main__":
    unittest.main()
