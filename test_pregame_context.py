import datetime as dt
import unittest

import pregame_context


class PregameContextTests(unittest.TestCase):
    def test_sport_specific_inputs_and_missingness_are_explicit(self):
        now = dt.datetime(2026, 8, 3, 12, tzinfo=dt.timezone.utc)
        match = {
            "status": "UPCOMING", "kickoff": "2026-08-03T13:30:00Z",
            "markets": {"1x2": {"home_pct": 55, "away_pct": 45}},
            "home": {"rest_days": 1}, "away": {"rest_days": 2},
            "injuries": {"home": [], "away": []}, "lineups": None,
            "personnel": {"starting_pitchers": {
                "home": {"name": "Pitcher A"}, "away": {"name": "Pitcher B"}},
                "starting_pitchers_confirmed": True},
        }
        context = pregame_context.build_pregame_context(match, "MLB", "baseball", now)
        self.assertEqual(context["phase"], "lock_window")
        self.assertEqual(context["inputs"]["starting_pitchers"], "confirmed")
        self.assertEqual(context["inputs"]["lineups"], "missing")
        self.assertIn("lineups", context["missing_critical"])
        self.assertEqual(context["production_weight"], 0)

    def test_lock_windows_are_sport_aware(self):
        self.assertEqual(pregame_context.lock_window_hours("MLB"), 2.0)
        self.assertEqual(pregame_context.lock_window_hours("NCAAF"), 3.0)
        self.assertEqual(pregame_context.lock_window_hours("EPL"), 2.0)

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

    def test_successfully_checked_zero_injuries_is_available_not_missing(self):
        match = {"status": "UPCOMING", "kickoff": "2026-08-04T12:00:00Z",
                 "markets": {}, "injuries": {"home": [], "away": []},
                 "personnel": {"injuries_feed_checked": True}, "home": {}, "away": {}}
        context = pregame_context.build_pregame_context(
            match, "NFL", "football", dt.datetime(2026, 8, 3, tzinfo=dt.timezone.utc))
        self.assertEqual(context["inputs"]["injuries"], "available")


if __name__ == "__main__":
    unittest.main()
