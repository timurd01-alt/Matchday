"""The Results page must publish whole recent days, not the last 40 fixtures.

College basketball plays 100+ games on a busy night, so a fixed 40-fixture
past window dropped most of the previous day's finals from the site.
"""
import datetime
import unittest

import fetch_data

UTC = datetime.timezone.utc
NOW = datetime.datetime(2026, 11, 18, 22, 0, tzinfo=UTC)


def games(start, count, step_minutes):
    return [(start + datetime.timedelta(minutes=i * step_minutes), {"id": i}) for i in range(count)]


class RecentPastWindowTest(unittest.TestCase):
    def test_busy_basketball_night_is_kept_whole(self):
        # 120 games yesterday evening, 100 the evening before.
        past = (games(NOW - datetime.timedelta(hours=26), 120, 2)
                + games(NOW - datetime.timedelta(hours=50), 100, 2))
        kept = fetch_data.recent_past_window(past, "NCAAM", NOW)
        self.assertEqual(len(kept), 220)
        self.assertEqual([k for k, _ in kept], sorted(k for k, _ in kept))

    def test_games_older_than_the_lookback_are_dropped(self):
        old = games(NOW - datetime.timedelta(days=10), 60, 5)
        recent = games(NOW - datetime.timedelta(days=1), 50, 5)
        kept = fetch_data.recent_past_window(old + recent, "NCAAM", NOW)
        self.assertEqual(len(kept), 50)

    def test_quiet_stretch_still_shows_the_last_40(self):
        old = games(NOW - datetime.timedelta(days=12), 80, 5)
        kept = fetch_data.recent_past_window(old, "NCAAM", NOW)
        self.assertEqual(len(kept), 40)
        self.assertEqual(kept, sorted(old, key=lambda item: item[0])[-40:])

    def test_cap_bounds_the_payload_and_keeps_the_newest(self):
        past = games(NOW - datetime.timedelta(hours=60), 700, 5)
        kept = fetch_data.recent_past_window(past, "NCAAM", NOW)
        cap = fetch_data.PAST_WINDOW["NCAAM"][1]
        self.assertEqual(len(kept), cap)
        self.assertEqual(kept[-1], past[-1])

    def test_football_keeps_the_previous_full_week(self):
        saturday = games(NOW - datetime.timedelta(days=4), 70, 3)
        midweek = games(NOW - datetime.timedelta(days=7, hours=-1), 6, 30)
        kept = fetch_data.recent_past_window(saturday + midweek, "NCAAF", NOW)
        self.assertEqual(len(kept), 76)

    def test_unlisted_competition_keeps_the_fixed_window(self):
        past = games(NOW - datetime.timedelta(days=1), 90, 5)
        self.assertEqual(len(fetch_data.recent_past_window(past, "OTHER", NOW)), 40)


if __name__ == "__main__":
    unittest.main()
