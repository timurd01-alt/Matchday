import datetime
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import fetch_data
import multi_fetch


class ScoreRefreshTests(unittest.TestCase):
    def test_recent_past_due_upcoming_fixture_is_score_urgent(self):
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
                    self.assertEqual(multi_fetch._interval_for("mlb"), multi_fetch.LIVE_EVERY)
                finally:
                    os.chdir(old_cwd)

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
