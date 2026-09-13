import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path

import fetch_data
import pregame_context


class PregameContextTests(unittest.TestCase):
    def test_sport_specific_inputs_and_missingness_are_explicit(self):
        now = dt.datetime(2026, 8, 3, 12, tzinfo=dt.timezone.utc)
        match = {
            "status": "UPCOMING", "kickoff": "2026-08-03T13:30:00Z",
            "markets": {"1x2": {"home_pct": 55, "away_pct": 45}},
            "home": {"rest_days": 6}, "away": {"rest_days": 7},
            "injuries": {"home": [], "away": []}, "lineups": None,
            "personnel": {"key_players": {
                "home": [{"name": "QB A"}], "away": [{"name": "QB B"}]},
                "key_players_confirmed": True},
        }
        context = pregame_context.build_pregame_context(match, "NCAAF", "football", now)
        self.assertEqual(context["phase"], "lock_window")
        self.assertEqual(context["inputs"]["key_players"], "confirmed")
        self.assertEqual(context["inputs"]["weather"], "missing")
        self.assertIn("injuries", context["missing_critical"])
        self.assertEqual(context["production_weight"], 0)

    def test_college_picks_lock_a_day_before_kickoff(self):
        self.assertEqual(pregame_context.lock_window_hours("NCAAF"), 24.0)
        self.assertEqual(pregame_context.lock_window_hours("NCAAM"), 24.0)

    def test_venue_factor_uses_only_prior_games_and_shrinkage(self):
        history = [
            {"status": "FINISHED", "kickoff": "2026-08-01T12:00:00Z", "venue": "Park A",
             "score": {"home": 6, "away": 4}},
            {"status": "FINISHED", "kickoff": "2026-08-02T12:00:00Z", "venue": "Park B",
             "score": {"home": 2, "away": 2}},
            # Future result must not leak into the target fixture.
            {"status": "FINISHED", "kickoff": "2026-08-05T12:00:00Z", "venue": "Park A",
             "score": {"home": 20, "away": 20}},
        ]
        target = {"kickoff": "2026-08-03T12:00:00Z", "venue": "Park A"}
        pregame_context.derive_venue_context([target], history, "baseball")
        self.assertEqual(target["venue_context"]["sample_games"], 1)
        self.assertLess(target["venue_context"]["venue_total_avg"], 10)
        self.assertEqual(target["venue_context"]["production_weight"], 0)

    def test_empty_injury_containers_are_not_treated_as_available(self):
        match = {"status": "UPCOMING", "kickoff": "2026-08-04T12:00:00Z",
                 "markets": {}, "injuries": {"home": [], "away": []},
                 "home": {}, "away": {}}
        context = pregame_context.build_pregame_context(
            match, "NFL", "football", dt.datetime(2026, 8, 3, tzinfo=dt.timezone.utc))
        self.assertEqual(context["inputs"]["injuries"], "missing")

    def test_high_confidence_requires_confirmed_not_merely_available_critical_inputs(self):
        match = {
            "status": "UPCOMING", "kickoff": "2026-08-04T12:00:00Z",
            "markets": {"1x2": {"home_pct": 52, "away_pct": 48}},
            "injuries": {"home": ["X (questionable)"], "away": []},
            "lineups": {"home": {"xi": [{"name": "A"}], "confirmed": False},
                        "away": {"xi": [{"name": "B"}], "confirmed": False}},
        }
        context = pregame_context.build_pregame_context(
            match, "NCAAM", "basketball", dt.datetime(2026, 8, 4, 10, tzinfo=dt.timezone.utc))
        self.assertEqual(context["missing_critical"], [])
        self.assertCountEqual(context["unconfirmed_critical"],
                              ["injuries", "lineups"])
        self.assertFalse(context["confidence_guard"]["high_confidence_label_allowed"])

    def test_successfully_checked_zero_injuries_is_available_not_missing(self):
        match = {"status": "UPCOMING", "kickoff": "2026-08-04T12:00:00Z",
                 "markets": {}, "injuries": {"home": [], "away": []},
                 "personnel": {"injuries_feed_checked": True}, "home": {}, "away": {}}
        context = pregame_context.build_pregame_context(
            match, "NFL", "football", dt.datetime(2026, 8, 3, tzinfo=dt.timezone.utc))
        self.assertEqual(context["inputs"]["injuries"], "available")

    def test_last_known_context_survives_a_fixture_rebuild(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / "pregame_epl_cache.json"
            original = [{
                "id": "fx-1", "status": "UPCOMING", "kickoff": "2026-08-12T18:00:00Z",
                "home": {"name": "Home"}, "away": {"name": "Away"},
                "injuries": {"home": ["Player A (out)"], "away": []},
                "lineups": {"home": {"xi": [{"name": "Player A"}]}, "away": {"xi": []}},
                "personnel": {"injuries_feed_checked": True, "lineups_feed_checked": True},
            }]
            fetch_data.save_pregame_snapshots(original, str(cache), "2026-08-10T12:00:00Z")
            rebuilt = [{
                "id": "fx-1", "status": "UPCOMING", "kickoff": "2026-08-12T18:00:00Z",
                "home": {"name": "Home"}, "away": {"name": "Away"},
                "injuries": {"home": [], "away": []}, "lineups": None,
            }]
            self.assertEqual(fetch_data.restore_pregame_snapshots(rebuilt, str(cache)), 1)
            self.assertEqual(rebuilt[0]["injuries"]["home"], ["Player A (out)"])
            self.assertTrue(rebuilt[0]["personnel"]["lineups_feed_checked"])

    def test_context_snapshot_does_not_cross_a_kickoff_change(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / "pregame_epl_cache.json"
            original = [{
                "id": "fx-1", "status": "UPCOMING", "kickoff": "2026-08-12T18:00:00Z",
                "home": {"name": "Home"}, "away": {"name": "Away"},
                "injuries": {"home": ["Player A (out)"], "away": []},
            }]
            fetch_data.save_pregame_snapshots(original, str(cache), "2026-08-10T12:00:00Z")
            postponed = [{
                "id": "fx-1", "status": "UPCOMING", "kickoff": "2026-08-13T18:00:00Z",
                "home": {"name": "Home"}, "away": {"name": "Away"},
                "injuries": {"home": [], "away": []},
            }]
            self.assertEqual(fetch_data.restore_pregame_snapshots(postponed, str(cache)), 0)
            self.assertEqual(postponed[0]["injuries"]["home"], [])


if __name__ == "__main__":
    unittest.main()
