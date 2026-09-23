import datetime as dt
import json
import pathlib
import tempfile
import unittest

import ap_poll


def _no_rankings():
    """The rankings endpoint being down, so the scoreboard path is exercised."""
    raise OSError("rankings endpoint unavailable")


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
            self.assertEqual(ap_poll.refresh(path, dt.date(2026, 9, 18), broken, fetch_rankings=_no_rankings), expected)

    def test_refresh_stores_only_normalized_poll_fields(self):
        with tempfile.TemporaryDirectory() as folder:
            path = pathlib.Path(folder) / "poll.json"
            result = ap_poll.refresh(path, dt.date(2026, 9, 18), lambda _day: self.payload(), fetch_rankings=_no_rankings)
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
            result = ap_poll.refresh(path, dt.date(2026, 9, 19), lambda _day: moved, fetch_rankings=_no_rankings)
            self.assertEqual(result["rankings"][0]["previous_rank"], 2)
            self.assertEqual(result["rankings"][0]["movement"], 1)
            self.assertEqual(result["rankings"][1]["movement"], -1)
            repeated = ap_poll.refresh(path, dt.date(2026, 9, 20), lambda _day: moved, fetch_rankings=_no_rankings)
            self.assertEqual(repeated, result)


class RankingsEndpointTests(unittest.TestCase):
    """The poll is read from the poll, not inferred from who is playing."""

    @staticmethod
    def _payload(missing=(), poll_type="ap"):
        ranks = []
        for rank in range(1, 26):
            if rank in missing:
                continue
            ranks.append({"current": rank, "previous": rank + 1 if rank > 1 else 1,
                          "recordSummary": "3-0",
                          "team": {"location": f"Team{rank}", "name": "Tigers"}})
        return {"rankings": [{"type": poll_type, "ranks": ranks}]}

    def test_a_ranked_team_on_a_bye_no_longer_freezes_the_poll(self):
        # The scoreboard route cannot see a team that is not playing, so it
        # held 24 of 25 and kept the previous week's poll indefinitely. This
        # route does not depend on anyone playing.
        rows = ap_poll.extract_poll(self._payload())
        self.assertEqual(len(rows), 25)
        self.assertEqual(rows[0]["name"], "Team1 Tigers")

    def test_an_incomplete_poll_is_still_refused(self):
        self.assertEqual(ap_poll.extract_poll(self._payload(missing={7})), [])

    def test_another_poll_is_not_mistaken_for_the_ap(self):
        self.assertEqual(ap_poll.extract_poll(self._payload(poll_type="usa")), [])

    def test_the_record_and_previous_rank_come_from_the_poll(self):
        row = ap_poll.extract_poll(self._payload())[4]
        self.assertEqual(row["record"], "3-0")
        self.assertEqual(row["previous_rank"], 6)
        self.assertEqual(row["movement"], 1)

    def test_the_scoreboard_is_used_only_when_the_poll_is_unavailable(self):
        with tempfile.TemporaryDirectory() as folder:
            path = pathlib.Path(folder) / "snap.json"
            called = []
            ap_poll.refresh(path, dt.date(2026, 9, 18),
                            lambda day: called.append(day) or {"events": []},
                            fetch_rankings=lambda: self._payload())
            self.assertEqual(called, [], "scoreboard fetched despite a complete poll")
