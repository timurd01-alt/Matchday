import unittest

from advanced_metrics import (
    basketball_game_records,
    basketball_team_profiles,
    cfbd_advanced_game_records,
    cfbd_advanced_team_profiles,
    nflverse_team_profiles,
    retrosheet_event_profiles,
    statsbomb_match_records,
    statsbomb_team_profiles,
)


class AdvancedMetricTests(unittest.TestCase):
    def test_nflverse_profiles_include_requested_families(self):
        rows = []
        for play in range(4):
            rows.append({"game_id": "g1", "posteam": "AAA", "defteam": "BBB", "pass_attempt": 1,
                         "rush_attempt": 0, "epa": 0.2, "success": 1, "yards_gained": 22,
                         "cpoe": 4, "down": 1, "fixed_drive": 1, "game_seconds_remaining": 3600 - play * 30})
        profile = nflverse_team_profiles(rows, min_plays=1)["AAA"]
        self.assertEqual(profile["epa_per_play"], 0.2)
        self.assertEqual(profile["success_rate"], 1.0)
        self.assertEqual(profile["explosive_play_rate"], 1.0)
        self.assertEqual(profile["cpoe"], 4.0)
        self.assertEqual(profile["seconds_per_play"], 30.0)

    def test_statsbomb_xg_and_pressure(self):
        events = [
            {"match_id": 1, "team": {"name": "A"}, "type": {"name": "Shot"}, "shot": {"statsbomb_xg": 0.3, "type": {"name": "Open Play"}}, "possession": 1, "possession_team": {"name": "A"}},
            {"match_id": 1, "team": {"name": "A"}, "type": {"name": "Pressure"}, "possession": 2, "possession_team": {"name": "B"}},
            {"match_id": 1, "team": {"name": "B"}, "type": {"name": "Shot"}, "shot": {"statsbomb_xg": 0.1, "type": {"name": "Open Play"}}, "possession": 2, "possession_team": {"name": "B"}},
        ]
        profiles = statsbomb_team_profiles(events)
        self.assertEqual(profiles["A"]["xg_difference_per90"], 0.2)
        self.assertEqual(profiles["A"]["pressures_per90"], 1.0)

    def test_statsbomb_records_grade_regulation_not_extra_time(self):
        matches = [{"match_id": 1, "match_date": "2025-01-01",
                    "home_team": {"home_team_name": "A"},
                    "away_team": {"away_team_name": "B"},
                    "home_score": 2, "away_score": 1}]
        events = []
        for team in ("A", "B"):
            events.extend([
                {"match_id": 1, "period": 1, "team": {"name": team},
                 "type": {"name": "Starting XI"}, "tactics": {"lineup": [
                     {"player": {"id": f"{team}-{number}"}} for number in range(11)]}},
                {"match_id": 1, "period": 1, "team": {"name": team},
                 "type": {"name": "Shot"}, "shot": {"statsbomb_xg": .2,
                 "type": {"name": "Open Play"}, "outcome": {"name": "Goal"}}},
            ])
        events.append({"match_id": 1, "period": 3, "team": {"name": "A"},
                       "type": {"name": "Shot"}, "shot": {"statsbomb_xg": .3,
                       "outcome": {"name": "Goal"}}})
        rows = statsbomb_match_records(matches, events)
        self.assertEqual(len(rows), 2)
        self.assertEqual({row["goals"] for row in rows}, {1})
        self.assertEqual(next(row for row in rows if row["is_home"])["lineup_count"], 11)

    def test_basketball_four_factors(self):
        rows = []
        for game in range(3):
            rows.extend([
                {"game_id": game, "game_date": f"2026-01-{game+1:02d}", "team": "A", "opponent": "B", "points": 110, "fgm": 40, "fga": 80, "three_pm": 10, "three_pa": 30, "fta": 20, "orb": 10, "drb": 30, "tov": 10},
                {"game_id": game, "game_date": f"2026-01-{game+1:02d}", "team": "B", "opponent": "A", "points": 100, "fgm": 35, "fga": 80, "three_pm": 8, "three_pa": 28, "fta": 18, "orb": 8, "drb": 30, "tov": 12},
            ])
        profile = basketball_team_profiles(rows)["A"]
        self.assertAlmostEqual(profile["efg"], 0.5625)
        self.assertIn("tov_rate", profile)
        self.assertIn("orb_rate", profile)
        self.assertIn("ft_rate", profile)
        self.assertIn("adjusted_off_rating", profile)
        self.assertIn("adjusted_def_rating", profile)
        self.assertIn("adjusted_net_rating", profile)
        self.assertEqual(profile["three_point_attempt_rate"], .375)
        self.assertEqual(profile["coverage"]["complete_paired_games"], 3)
        self.assertEqual(profile["coverage"]["observed_through"], "2026-01-03")

    def test_basketball_incomplete_pair_is_not_silently_zero_filled(self):
        rows = [{"game_id": "g1", "team": "A", "points": 100, "fgm": 30, "fga": 70,
                 "three_pm": 8, "fta": 20, "orb": 10, "drb": 25, "tov": 12}]
        self.assertEqual(basketball_game_records(rows), [])

    def test_cfbd_normalization(self):
        profiles = cfbd_advanced_team_profiles([{"team": "A", "offense": {"plays": 100, "ppa": 0.2, "successRate": 0.5, "explosiveness": 1.3}, "defense": {"ppa": -0.1}}])
        self.assertEqual(profiles["A"]["ppa"], 0.2)
        self.assertEqual(profiles["A"]["def_ppa_allowed"], -0.1)

    def test_cfbd_advanced_games_require_complete_team_pairs(self):
        games = [{"id": 1, "season": 2025, "week": 1, "completed": True,
                  "homeTeam": "A", "awayTeam": "B", "homePoints": 28,
                  "awayPoints": 21, "startDate": "2025-08-30T16:00:00Z"}]
        offense = {"plays": 70, "ppa": .2, "successRate": .45, "explosiveness": 1.3}
        self.assertEqual(cfbd_advanced_game_records(games, [
            {"gameId": 1, "team": "A", "offense": offense}]), [])
        rows = cfbd_advanced_game_records(games, [
            {"gameId": 1, "team": "A", "offense": offense},
            {"gameId": 1, "team": "B", "offense": {**offense, "ppa": -.1}},
        ])
        self.assertEqual(len(rows), 2)
        home = next(row for row in rows if row["is_home"])
        self.assertEqual(home["ppa"], .2)
        self.assertEqual(home["ppa_allowed"], -.1)
        self.assertEqual(home["game_date"], "2025-08-30")
        self.assertEqual(cfbd_advanced_game_records(games, [
            {"gameId": 1, "team": "A", "offense": offense},
            {"gameId": 1, "team": "A", "offense": offense},
            {"gameId": 1, "team": "B", "offense": offense},
        ]), [])

    def test_retrosheet_event_rates(self):
        lines = ["id,G1", "info,visteam,AAA", "info,hometeam,BBB",
                 "play,1,0,p,00,,K", "play,1,0,p,00,,W", "play,1,0,p,00,,HR",
                 "play,1,1,p,00,,S7"]
        profiles = retrosheet_event_profiles(lines, min_plate_appearances=1)
        self.assertEqual(profiles["AAA"]["plate_appearances"], 3)
        self.assertAlmostEqual(profiles["AAA"]["strikeout_rate"], 1 / 3, places=4)
        self.assertAlmostEqual(profiles["AAA"]["home_run_rate"], 1 / 3, places=4)


if __name__ == "__main__":
    unittest.main()
