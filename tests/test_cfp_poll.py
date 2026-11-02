import datetime as dt
import json
import pathlib
import tempfile
import unittest
import cfp_poll

class CommitteePollTests(unittest.TestCase):
    def payload(self, year=2026, count=25):
        return {"rankings": [{"type": "cfp", "season": {"year": year},
            "date": f"{year}-11-03T23:00Z", "ranks": [
                {"current": i, "team": {"displayName": f"School {i}"}, "recordSummary": "8-0"}
                for i in range(1, count+1)]}]}

    def test_complete_poll_and_failure_preserves_same_season(self):
        with tempfile.TemporaryDirectory() as folder:
            path = pathlib.Path(folder) / "poll.json"
            today = dt.date(2026, 11, 4)
            good = cfp_poll.refresh(path, today, lambda: self.payload())
            self.assertEqual(len(good["rankings"]), 25)
            self.assertEqual(good["published_on"], "2026-11-03")
            self.assertEqual(cfp_poll.refresh(path, today, lambda: self.payload(count=24)), good)
            self.assertEqual(cfp_poll.refresh(path, today, lambda: self.payload(year=2025)), good)
            self.assertEqual(cfp_poll.refresh(path, dt.date(2027, 11, 4), lambda: self.payload()), {})

    def test_no_ap_substitution_or_future_poll(self):
        with tempfile.TemporaryDirectory() as folder:
            path = pathlib.Path(folder) / "poll.json"
            self.assertEqual(cfp_poll.refresh(path, dt.date(2026, 11, 1), lambda: self.payload()), {})
            payload = self.payload(); payload["rankings"][0]["type"] = "ap"
            self.assertEqual(cfp_poll.refresh(path, dt.date(2026, 11, 4), lambda: payload), {})
            self.assertFalse(path.exists())
