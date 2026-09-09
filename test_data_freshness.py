"""Tests for the freshness check.

The check exists to fail when the site is serving stale data, so the tests that
matter most are the ones proving it does *not* fire on the cases that are fine
-- a fixture the handoff has already settled, a game that only just kicked off.
A check that cries wolf gets ignored, which is the failure mode it was written
to end.
"""

from __future__ import annotations

import datetime
import json
import pathlib
import tempfile
import unittest

import data_freshness


NOW = datetime.datetime(2026, 9, 5, 12, 0, tzinfo=datetime.timezone.utc)


def _match(home, away, kickoff, status="UPCOMING", score=None):
    return {
        "home": {"name": home},
        "away": {"name": away},
        "kickoff": kickoff,
        "status": status,
        "score": score if score is not None else {"home": None, "away": None},
    }


def _write(root: pathlib.Path, key: str, updated: str, matches: list[dict]) -> None:
    (root / f"data_{key}.json").write_text(
        json.dumps({"updated": updated, "comp_key": key.upper(), "matches": matches}),
        encoding="utf-8",
    )


def _handoff(root: pathlib.Path, results: list[dict], generated: str = "2026-09-05T06:00:00+00:00") -> None:
    (root / "betbetter_picks.json").write_text(
        json.dumps({"source": "betbetter", "generated_at": generated, "results": results}),
        encoding="utf-8",
    )


class UnsettledTests(unittest.TestCase):
    def test_recent_kickoff_is_not_yet_unsettled(self):
        """A game that kicked off an hour ago has not missed anything."""
        m = _match("TCU", "North Carolina", "2026-09-05T11:00:00Z")
        self.assertFalse(data_freshness._unsettled(m, NOW))

    def test_old_upcoming_fixture_is_unsettled(self):
        m = _match("TCU", "North Carolina", "2026-09-03T23:00:00Z")
        self.assertTrue(data_freshness._unsettled(m, NOW))

    def test_zero_zero_placeholder_counts_as_missing(self):
        """The stalled-MLB signature: FINISHED, but scored 0-0 by default."""
        m = _match("A", "B", "2026-09-03T23:00:00Z", status="FINISHED", score={"home": 0, "away": 0})
        self.assertTrue(data_freshness._unsettled(m, NOW))

    def test_real_score_is_settled(self):
        m = _match("A", "B", "2026-09-03T23:00:00Z", status="FINISHED", score={"home": 28, "away": 17})
        self.assertFalse(data_freshness._unsettled(m, NOW))

    def test_missing_kickoff_is_not_reported(self):
        """No kickoff means no expectation; it cannot be judged late."""
        self.assertFalse(data_freshness._unsettled(_match("A", "B", None), NOW))


class HandoffMatchTests(unittest.TestCase):
    def test_mascot_suffix_still_matches(self):
        """Matchday says "TCU"; the handoff says "TCU Horned Frogs"."""
        self.assertTrue(data_freshness._names_match("TCU Horned Frogs", "TCU"))
        self.assertTrue(data_freshness._names_match("TCU", "TCU Horned Frogs"))

    def test_unrelated_teams_do_not_match(self):
        self.assertFalse(data_freshness._names_match("Alabama", "TCU"))
        self.assertFalse(data_freshness._names_match("", "TCU"))

    def test_shared_prefix_is_weaker_than_an_exact_match(self):
        """"Ohio" prefixes "Ohio State", and both are real FBS teams."""
        self.assertEqual(data_freshness._name_strength("Ohio", "Ohio"), data_freshness.MATCH_EXACT)
        self.assertEqual(
            data_freshness._name_strength("Ohio State Buckeyes", "Ohio"), data_freshness.MATCH_PREFIX
        )

    def test_exact_row_wins_over_a_prefix_rival(self):
        """Ohio's game must take Ohio's score, not Ohio State's."""
        m = _match("Ohio", "Buffalo", "2026-09-03T23:00:00Z")
        results = [
            {"played_on": "2026-09-03", "home": "Ohio State Buckeyes", "away": "Buffalo Bulls",
             "home_score": 45.0, "away_score": 3.0},
            {"played_on": "2026-09-03", "home": "Ohio Bobcats", "away": "Buffalo Bulls",
             "home_score": 21.0, "away_score": 17.0},
        ]
        self.assertTrue(data_freshness._settled_by_handoff(m, results))

    def test_ambiguous_prefix_match_settles_nothing(self):
        """Two equally-weak candidates must not settle the game by coin flip."""
        m = _match("Ohio", "Buffalo", "2026-09-03T23:00:00Z")
        results = [
            {"played_on": "2026-09-03", "home": "Ohio State Buckeyes", "away": "Buffalo Bulls",
             "home_score": 45.0, "away_score": 3.0},
            {"played_on": "2026-09-03", "home": "Ohio University Bobcats", "away": "Buffalo Bulls",
             "home_score": 21.0, "away_score": 17.0},
        ]
        self.assertFalse(data_freshness._settled_by_handoff(m, results))

    def test_result_a_day_either_side_still_settles(self):
        """A late kickoff and its result can straddle midnight UTC."""
        m = _match("TCU", "North Carolina", "2026-09-03T23:00:00Z")
        results = [
            {
                "played_on": "2026-09-04",
                "home": "TCU Horned Frogs",
                "away": "North Carolina Tar Heels",
                "home_score": 27.0,
                "away_score": 24.0,
            }
        ]
        self.assertTrue(data_freshness._settled_by_handoff(m, results))

    def test_result_without_scores_does_not_settle(self):
        m = _match("TCU", "North Carolina", "2026-09-03T23:00:00Z")
        results = [{"played_on": "2026-09-03", "home": "TCU", "away": "North Carolina",
                    "home_score": None, "away_score": None}]
        self.assertFalse(data_freshness._settled_by_handoff(m, results))


class ReportTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_fresh_payload_with_settled_games_is_ok(self):
        _write(self.root, "ncaaf", "2026-09-05T11:30:00+00:00",
               [_match("A", "B", "2026-09-03T23:00:00Z", "FINISHED", {"home": 28, "away": 17})])
        _handoff(self.root, [])
        finding = data_freshness.inspect_payload("ncaaf", [], NOW, self.root)
        self.assertEqual(finding["state"], "ok")
        self.assertEqual(finding["problems"], [])

    def test_handoff_repair_keeps_the_payload_out_of_the_stale_bucket(self):
        """The browser renders the repaired game, so it is not a reader-visible fault."""
        _write(self.root, "ncaaf", "2026-09-05T11:30:00+00:00",
               [_match("TCU", "North Carolina", "2026-09-03T23:00:00Z")])
        results = [{"played_on": "2026-09-03", "home": "TCU Horned Frogs",
                    "away": "North Carolina Tar Heels", "home_score": 27.0, "away_score": 24.0}]
        finding = data_freshness.inspect_payload("ncaaf", results, NOW, self.root)
        self.assertEqual(finding["unsettled_in_payload"], 1)
        self.assertEqual(finding["unsettled_after_handoff"], 0)
        self.assertEqual(finding["repaired_by_handoff"], 1)
        self.assertEqual(finding["state"], "ok")

    def test_unrepaired_game_is_stale(self):
        _write(self.root, "ncaaf", "2026-09-05T11:30:00+00:00",
               [_match("Rutgers", "Massachusetts", "2026-09-03T22:00:00Z")])
        finding = data_freshness.inspect_payload("ncaaf", [], NOW, self.root)
        self.assertEqual(finding["state"], "stale")
        self.assertEqual(finding["unsettled_after_handoff"], 1)

    def test_old_payload_is_stale_even_with_no_fixtures(self):
        """The five-day stall had an empty slate for days; age alone must fire."""
        _write(self.root, "ncaam", "2026-07-24T19:53:52+00:00", [])
        finding = data_freshness.inspect_payload("ncaam", [], NOW, self.root)
        self.assertEqual(finding["state"], "stale")

    def test_out_of_season_sport_is_judged_on_its_own_cadence(self):
        """NCAAM out of season is fetched every 12h, so 10h old is not a problem.

        The uniform 3h warning made a dormant sport permanently "aging" for
        obeying the fetcher, and the 12h failure line sat exactly on its 12h
        probe interval -- so an ordinary late probe flipped it to "stale" and
        failed the run.
        """
        _write(self.root, "ncaam", "2026-09-05T01:30:00+00:00",
               [_match("Duke", "Kansas", "2026-11-02T05:00:00Z")])
        finding = data_freshness.inspect_payload("ncaam", [], NOW, self.root)
        self.assertEqual(finding["cadence_hours"], 12.0)
        self.assertEqual(finding["state"], "ok")
        self.assertEqual(finding["problems"], [])

    def test_dormant_sport_still_fails_once_it_misses_four_probes(self):
        """Scaling the threshold must not amount to switching the check off."""
        _write(self.root, "ncaam", "2026-09-03T00:00:00+00:00",
               [_match("Duke", "Kansas", "2026-11-02T05:00:00Z")])
        finding = data_freshness.inspect_payload("ncaam", [], NOW, self.root)
        self.assertEqual(finding["state"], "stale")

    def test_in_season_sport_keeps_the_hourly_thresholds(self):
        """A game inside 48h puts the sport back on an hourly fetch."""
        _write(self.root, "ncaaf", "2026-09-05T07:30:00+00:00",
               [_match("Rutgers", "Massachusetts", "2026-09-06T22:00:00Z")])
        finding = data_freshness.inspect_payload("ncaaf", [], NOW, self.root)
        self.assertEqual(finding["cadence_hours"], 1.0)
        self.assertEqual(finding["state"], "aging")
        self.assertEqual(finding["warn_hours"], 3.0)
        self.assertEqual(finding["fail_hours"], 12.0)

    def test_missing_payload_is_reported_not_crashed(self):
        finding = data_freshness.inspect_payload("ncaaf", [], NOW, self.root)
        self.assertEqual(finding["state"], "missing")

    def test_snapshot_older_than_handoff_is_stale(self):
        _handoff(self.root, [])
        snapshot = self.root / "matchday-cfb-snapshot.js"
        snapshot.write_text("// snapshot", encoding="utf-8")
        handoff = self.root / "betbetter_picks.json"
        import os

        old = NOW.timestamp() - 6 * 3600
        os.utime(snapshot, (old, old))
        new = NOW.timestamp()
        os.utime(handoff, (new, new))
        finding = data_freshness.inspect_patch_layer(NOW, NOW, self.root)
        self.assertEqual(finding["state"], "stale")
        self.assertTrue(any("build_cfb_snapshot" in p for p in finding["problems"]))

    def test_exit_code_is_one_when_stale(self):
        _write(self.root, "ncaaf", "2026-07-24T19:53:18+00:00", [])
        _write(self.root, "ncaam", "2026-07-24T19:53:52+00:00", [])
        _handoff(self.root, [])
        code = data_freshness.main(["--root", str(self.root)])
        self.assertEqual(code, 1)

    def test_warn_only_never_fails(self):
        _write(self.root, "ncaaf", "2026-07-24T19:53:18+00:00", [])
        _write(self.root, "ncaam", "2026-07-24T19:53:52+00:00", [])
        _handoff(self.root, [])
        self.assertEqual(data_freshness.main(["--root", str(self.root), "--warn-only"]), 0)


if __name__ == "__main__":
    unittest.main()
