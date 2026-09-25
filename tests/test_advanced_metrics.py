import unittest

from advanced_metrics import (
    basketball_game_records,
    basketball_team_profiles,
    cfbd_advanced_game_records,
    cfbd_advanced_team_profiles,
)


class AdvancedMetricTests(unittest.TestCase):
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

if __name__ == "__main__":
    unittest.main()
