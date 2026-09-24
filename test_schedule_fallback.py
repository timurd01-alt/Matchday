"""The NCAAF schedule keeps moving while CollegeFootballData is dark."""

import datetime as dt
import json
import os
import tempfile
import unittest

import schedule_fallback

NOW = dt.datetime(2026, 9, 24, 1, 0, tzinfo=dt.timezone.utc)


def fixture(home, away, kickoff, status="UPCOMING"):
    return {"id": f"cfbd-{home}", "kickoff": kickoff, "status": status,
            "home": {"name": home, "code": home[:3].upper()},
            "away": {"name": away, "code": away[:3].upper()},
            "prediction": {"pick": "h"}, "watchability": 9}


def scoreboard(*games):
    events = []
    for home, away, date, valid in games:
        events.append({"competitions": [{
            "date": date, "timeValid": valid,
            "competitors": [
                {"homeAway": "home", "team": {"location": home, "displayName": f"{home} Cats"}},
                {"homeAway": "away", "team": {"location": away, "displayName": f"{away} Dogs"}},
            ]}]})
    return {"events": events}


class RefreshKickoffTests(unittest.TestCase):
    def test_a_placeholder_takes_the_announced_time(self):
        # CFBD's "time TBA" marker is midnight US Eastern on the game's date.
        match = fixture("Louisville", "Wake Forest", "2026-09-26T04:00:00Z")
        board = scoreboard(("Louisville", "Wake Forest", "2026-09-26T16:00Z", True))
        report = schedule_fallback.refresh_kickoffs([match], "NCAAF", NOW, fetch=lambda url: board)
        self.assertEqual(match["kickoff"], "2026-09-26T16:00:00Z")
        self.assertEqual(report["updated"], 1)
        self.assertIn("kickoff time only", match["kickoff_source"])

    def test_an_unannounced_time_is_never_copied(self):
        match = fixture("Louisville", "Wake Forest", "2026-09-26T04:00:00Z")
        board = scoreboard(("Louisville", "Wake Forest", "2026-09-26T05:00Z", False))
        schedule_fallback.refresh_kickoffs([match], "NCAAF", NOW, fetch=lambda url: board)
        self.assertEqual(match["kickoff"], "2026-09-26T04:00:00Z")

    def test_the_scoreboard_never_adds_a_fixture(self):
        matches = [fixture("Louisville", "Wake Forest", "2026-09-26T04:00:00Z")]
        board = scoreboard(("Louisville", "Wake Forest", "2026-09-26T16:00Z", True),
                           ("Florida", "Ole Miss", "2026-09-26T19:30Z", True))
        schedule_fallback.refresh_kickoffs(matches, "NCAAF", NOW, fetch=lambda url: board)
        self.assertEqual(len(matches), 1)

    def test_played_and_distant_games_cost_no_request(self):
        calls = []
        matches = [fixture("Louisville", "Wake Forest", "2026-09-20T16:00:00Z", status="FINISHED"),
                   fixture("Florida", "Ole Miss", "2026-11-21T05:00:00Z")]
        schedule_fallback.refresh_kickoffs(matches, "NCAAF", NOW,
                                           fetch=lambda url: calls.append(url) or {})
        self.assertEqual(calls, [])

    def test_a_failed_day_leaves_the_schedule_alone(self):
        match = fixture("Louisville", "Wake Forest", "2026-09-26T04:00:00Z")

        def broken(url):
            raise OSError("scoreboard down")
        report = schedule_fallback.refresh_kickoffs([match], "NCAAF", NOW, fetch=broken)
        self.assertEqual(match["kickoff"], "2026-09-26T04:00:00Z")
        self.assertEqual(len(report["errors"]), 1)


class LastGoodBundleTests(unittest.TestCase):
    def write(self, name, payload):
        handle = tempfile.NamedTemporaryFile("w", suffix=name, delete=False, encoding="utf-8")
        json.dump(payload, handle)
        handle.close()
        self.addCleanup(os.unlink, handle.name)
        return handle.name

    def test_the_last_payload_becomes_a_bundle_of_raw_fixtures(self):
        data = self.write(".json", {"matches": [fixture("Rutgers", "Howard", "2026-09-25T23:00:00Z")],
                                    "standings": [{"group": "Big Ten", "teams": []}]})
        bundle = schedule_fallback.last_good_bundle("NCAAF", data, handoff_path="missing.json")
        self.assertEqual(len(bundle["matches"]), 1)
        # Derived fields are recomputed by the build, never carried over.
        self.assertNotIn("prediction", bundle["matches"][0])
        self.assertNotIn("watchability", bundle["matches"][0])
        self.assertEqual(bundle["tables"][0]["group"], "Big Ten")

    def test_no_payload_means_no_bundle(self):
        self.assertIsNone(schedule_fallback.last_good_bundle("NCAAF", "missing.json"))

    def test_engine_results_use_the_schedule_spelling(self):
        known = schedule_fallback._known_names([fixture("Rutgers", "Howard", "2026-09-25T23:00:00Z"),
                                                fixture("Indiana", "Iowa", "2026-10-03T16:00:00Z")])
        document = {"results": [
            {"sport": "ncaaf", "event_id": "1", "kickoff": "2026-09-12T16:00Z",
             "home": "Indiana Hoosiers", "away": "Howard Bison", "home_score": 55, "away_score": 0},
            # Not on the schedule: dropped rather than guessed.
            {"sport": "ncaaf", "event_id": "2", "kickoff": "2026-09-12T16:00Z",
             "home": "Oregon Ducks", "away": "Howard Bison", "home_score": 40, "away_score": 7},
        ]}
        rows = schedule_fallback.history_from_handoff(document, "NCAAF", known)
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["home"]["name"], rows[0]["away"]["name"]), ("Indiana", "Howard"))
        self.assertEqual(rows[0]["status"], "FINISHED")


if __name__ == "__main__":
    unittest.main()
