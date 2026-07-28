import datetime
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import fetch_data
import multi_fetch


class ScoreRefreshTests(unittest.TestCase):
    def test_recent_past_due_upcoming_fixture_uses_hourly_result_check(self):
        now = datetime.datetime.now(datetime.timezone.utc)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "data_mlb.json"
            path.write_text(json.dumps({"matches": [{
                "status": "UPCOMING",
                "kickoff": (now - datetime.timedelta(hours=2)).isoformat(),
            }]}), encoding="utf-8")
            with mock.patch.object(multi_fetch, "__file__", str(Path(folder) / "multi_fetch.py")):
                old_cwd = Path.cwd()
                try:
                    import os
                    os.chdir(folder)
                    self.assertEqual(multi_fetch._interval_for("mlb"), multi_fetch.RESULT_PENDING_EVERY)
                finally:
                    os.chdir(old_cwd)

    def test_odds_are_only_due_for_near_future_upcoming_games(self):
        now = datetime.datetime(2026, 7, 27, 20, 0, tzinfo=datetime.timezone.utc)
        near = {"status": "UPCOMING", "kickoff": "2026-07-27T22:00:00Z"}
        far = {"status": "UPCOMING", "kickoff": "2026-07-28T02:01:00Z"}
        past = {"status": "UPCOMING", "kickoff": "2026-07-27T19:59:00Z"}
        live = {"status": "LIVE", "kickoff": "2026-07-27T19:00:00Z"}
        finished = {"status": "FINISHED", "kickoff": "2026-07-27T17:00:00Z"}

        self.assertTrue(fetch_data._due_for_odds(near, now))
        self.assertFalse(fetch_data._due_for_odds(far, now))
        self.assertFalse(fetch_data._due_for_odds(past, now))
        self.assertFalse(fetch_data._due_for_odds(live, now))
        self.assertFalse(fetch_data._due_for_odds(finished, now))

    def test_odds_market_cache_survives_a_new_process(self):
        now = 1_800_000_000.0
        payload = {"Team A|Team B": {"1x2": {"home_pct": 55}}}
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "odds_cache.json"
            path.write_text(json.dumps({"t": now, "data": payload}), encoding="utf-8")
            with mock.patch.object(fetch_data, "ODDS_CACHE_FILE", str(path)), \
                 mock.patch.object(fetch_data, "_ODDS_CACHE", {"t": 0.0, "data": {}}), \
                 mock.patch.object(fetch_data.time, "time", return_value=now), \
                 mock.patch.object(fetch_data, "_get") as get:
                self.assertEqual(fetch_data.fetch_odds(), payload)
                get.assert_not_called()

    def test_empty_odds_snapshot_is_also_cached(self):
        now = 1_800_000_000.0
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "odds_cache.json"
            path.write_text(json.dumps({"t": now, "data": {}}), encoding="utf-8")
            with mock.patch.object(fetch_data, "ODDS_CACHE_FILE", str(path)), \
                 mock.patch.object(fetch_data, "_ODDS_CACHE", {"t": 0.0, "data": {}}), \
                 mock.patch.object(fetch_data.time, "time", return_value=now), \
                 mock.patch.object(fetch_data, "_get") as get:
                self.assertEqual(fetch_data.fetch_odds(), {})
                get.assert_not_called()

    def test_balldontlie_live_and_near_games_use_short_cache(self):
        now = datetime.datetime(2026, 7, 27, 20, 0, tzinfo=datetime.timezone.utc)
        live = [{"status": "LIVE", "kickoff": "2026-07-27T19:00:00Z"}]
        near = [{"status": "UPCOMING", "kickoff": "2026-07-27T22:00:00Z"}]
        far = [{"status": "UPCOMING", "kickoff": "2026-07-29T22:00:00Z"}]
        short = fetch_data.BALLDONTLIE_ACTIVE_CACHE_MIN * 60
        self.assertEqual(fetch_data._balldontlie_cache_seconds(live, now), short)
        self.assertEqual(fetch_data._balldontlie_cache_seconds(near, now), short)
        self.assertEqual(fetch_data._balldontlie_cache_seconds(far, now), fetch_data.BALLDONTLIE_CACHE_MIN * 60)


if __name__ == "__main__":
    unittest.main()
