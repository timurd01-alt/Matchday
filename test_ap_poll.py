import datetime as dt
import json
import pathlib
import tempfile
import unittest

import ap_poll


class ApPollTests(unittest.TestCase):
    @staticmethod
    def payload(start=1, stop=26):
        return {"events": [{"competitions": [{"competitors": [
            {"curatedRank": {"current": rank}, "team": {"displayName": f"Team {rank}"}}
            for rank in range(start, stop)
        ]}]}]}

    def test_extract_requires_one_complete_unambiguous_top_25(self):
        rows = ap_poll.extract([self.payload()])
        self.assertEqual([row["rank"] for row in rows], list(range(1, 26)))
        self.assertEqual(rows[0]["name"], "Team 1")
        self.assertEqual(ap_poll.extract([self.payload(1, 25)]), [])

    def test_refresh_keeps_last_good_when_fetch_fails(self):
        with tempfile.TemporaryDirectory() as folder:
            path = pathlib.Path(folder) / "poll.json"
            expected = {"poll_name": "AP Top 25", "rankings": [
                {"rank": rank, "name": f"Old {rank}"} for rank in range(1, 26)]}
            path.write_text(json.dumps(expected), encoding="utf-8")
            def broken(_day):
                raise OSError("offline")
            self.assertEqual(ap_poll.refresh(path, dt.date(2026, 9, 18), broken), expected)

    def test_refresh_stores_only_normalized_poll_fields(self):
        with tempfile.TemporaryDirectory() as folder:
            path = pathlib.Path(folder) / "poll.json"
            result = ap_poll.refresh(path, dt.date(2026, 9, 18), lambda _day: self.payload())
            self.assertEqual(result["fetched_on"], "2026-09-18")
            self.assertNotIn("events", path.read_text(encoding="utf-8"))

    def test_refresh_calculates_and_preserves_weekly_movement(self):
        with tempfile.TemporaryDirectory() as folder:
            path = pathlib.Path(folder) / "poll.json"
            previous = {"poll_name": "AP Top 25", "rankings": [
                {"rank": rank, "name": f"Team {rank}"} for rank in range(1, 26)]}
            path.write_text(json.dumps(previous), encoding="utf-8")
            moved = self.payload()
            competitors = moved["events"][0]["competitions"][0]["competitors"]
            competitors[0]["team"]["displayName"] = "Team 2"
            competitors[1]["team"]["displayName"] = "Team 1"
            result = ap_poll.refresh(path, dt.date(2026, 9, 19), lambda _day: moved)
            self.assertEqual(result["rankings"][0]["previous_rank"], 2)
            self.assertEqual(result["rankings"][0]["movement"], 1)
            self.assertEqual(result["rankings"][1]["movement"], -1)
            repeated = ap_poll.refresh(path, dt.date(2026, 9, 20), lambda _day: moved)
            self.assertEqual(repeated, result)
