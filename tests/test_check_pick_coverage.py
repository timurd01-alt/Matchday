"""The ship refuses a handoff that lost a large share of this week's picks."""
import datetime as dt
import unittest

import check_pick_coverage as cpc

NOW = dt.datetime(2026, 9, 28, 22, 0, tzinfo=dt.timezone.utc)


def doc(n, day="2026-10-03T19:00Z"):
    return {"picks": [{"kickoff": day} for _ in range(n)]}


class PickCoverageTests(unittest.TestCase):
    def test_the_2026_09_28_drop_is_refused(self):
        ok, message = cpc.check(doc(17), doc(90), NOW)
        self.assertFalse(ok)
        self.assertIn("REFUSING TO SHIP", message)

    def test_normal_week_passes(self):
        self.assertTrue(cpc.check(doc(88), doc(90), NOW)[0])

    def test_off_season_is_not_judged(self):
        self.assertTrue(cpc.check(doc(0), doc(5), NOW)[0])

    def test_games_outside_the_week_are_ignored(self):
        self.assertTrue(cpc.check(doc(90), doc(90, "2026-11-20T19:00Z"), NOW)[0])


if __name__ == "__main__":
    unittest.main()
