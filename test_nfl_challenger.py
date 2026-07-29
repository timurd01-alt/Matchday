import unittest

from nfl_challenger import (
    FEATURE_NAMES,
    aggregate_games,
    build_point_in_time_rows,
    fit_logistic,
    predict_probability,
    promotion_gate,
    quarterback_profile,
    rolling_backtest,
)


def game(game_id, week, home, away, home_score, away_score, home_epa, away_epa):
    def summary(epa, allowed):
        return {
            "off_epa": epa, "def_epa_allowed": allowed,
            "success_rate": 0.5 + epa / 4, "def_success_allowed": 0.5 + allowed / 4,
            "explosive_rate": 0.1 + epa / 10, "def_explosive_allowed": 0.1 + allowed / 10,
            "pass_epa": epa * 1.2, "def_pass_epa_allowed": allowed * 1.2,
            "rush_epa": epa * 0.8, "def_rush_epa_allowed": allowed * 0.8,
            "neutral_epa": epa, "def_neutral_epa_allowed": allowed,
            "early_down_epa": epa, "def_early_down_epa_allowed": allowed,
            "cpoe": epa * 10, "sack_rate": 0.05 - epa / 20,
            "def_sack_rate": 0.05 + epa / 20, "redzone_td_rate": 0.55 + epa / 4,
            "seconds_per_play": 28, "special_teams_epa": epa / 4, "plays": 50,
        }
    return {
        "game_id": game_id, "season": 2025, "season_type": "REG", "week": week,
        "game_date": f"2025-09-{week:02d}", "start_time": "13:00",
        "home_team": home, "away_team": away, "home_score": home_score, "away_score": away_score,
        "teams": {home: summary(home_epa, away_epa), away: summary(away_epa, home_epa)},
    }


class NFLChallengerTests(unittest.TestCase):
    def test_play_aggregation_excludes_kneels_and_derives_context(self):
        base = {"game_id": "2025_01_A_B", "season": 2025, "season_type": "REG", "week": 1,
                "game_date": "2025-09-07", "home_team": "A", "away_team": "B",
                "home_score": 24, "away_score": 17, "posteam": "A", "defteam": "B",
                "pass_attempt": 1, "rush_attempt": 0, "qb_dropback": 1, "epa": 0.4,
                "success": 1, "yards_gained": 25, "down": 1, "qtr": 1,
                "score_differential": 0, "yardline_100": 15, "fixed_drive": 1,
                "touchdown": 1, "game_seconds_remaining": 3500, "cpoe": 5, "sack": 0,
                "passer_player_id": "qb-a", "passer_player_name": "Quarterback A"}
        kneel = {**base, "play_id": 2, "pass_attempt": 0, "rush_attempt": 1, "qb_dropback": 0,
                 "qb_kneel": 1, "epa": -2, "game_seconds_remaining": 3470}
        opponent = {**base, "play_id": 3, "posteam": "B", "defteam": "A", "epa": -0.2,
                    "yards_gained": 2, "touchdown": 0, "fixed_drive": 2, "game_seconds_remaining": 3400}
        games = aggregate_games([base, kneel, opponent])
        self.assertEqual(len(games), 1)
        self.assertEqual(games[0]["teams"]["A"]["off_epa"], 0.4)
        self.assertEqual(games[0]["teams"]["A"]["explosive_rate"], 1.0)
        self.assertEqual(games[0]["teams"]["A"]["redzone_td_rate"], 1.0)
        self.assertEqual(games[0]["teams"]["A"]["primary_qb_id"], "qb-a")
        self.assertEqual(games[0]["teams"]["A"]["primary_qb_epa"], 0.4)

    def test_point_in_time_rows_never_use_same_or_future_week(self):
        games = []
        teams = ("A", "B", "C", "D")
        for week in range(1, 8):
            games.append(game(f"g{week}a", week, teams[0], teams[1], 24, 17, 0.2, -0.1))
            games.append(game(f"g{week}b", week, teams[2], teams[3], 20, 16, 0.1, -0.05))
        rows, state = build_point_in_time_rows(games, min_history=2)
        target = next(row for row in rows if row["game_id"] == "g3a")
        self.assertEqual(target["home_history_games"], 2)
        self.assertEqual(target["feature_observed_through"], "2025-09-02")
        self.assertLess(target["feature_observed_through"], target["game_date"])
        self.assertEqual(len(state["team_games"]["A"]), 7)

    def test_regularized_model_learns_probability_direction(self):
        rows = []
        for index in range(80):
            value = -2.0 + 4.0 * index / 79
            features = {name: 0.0 for name in FEATURE_NAMES}
            features["epa_matchup_edge"] = value
            rows.append({"eligible": True, "features": features, "outcome": float(value > 0)})
        model = fit_logistic(rows, iterations=500)
        low = {name: 0.0 for name in FEATURE_NAMES}; low["epa_matchup_edge"] = -1
        high = {name: 0.0 for name in FEATURE_NAMES}; high["epa_matchup_edge"] = 1
        self.assertLess(predict_probability(model, low), 0.5)
        self.assertGreater(predict_probability(model, high), 0.5)
        self.assertEqual(model["training_rows"], 80)

    def test_quarterback_profile_uses_only_latest_prior_assumption(self):
        history = {"A": [
            {"game_date": "2025-09-01", "primary_qb_id": "old", "primary_qb_name": "Old QB",
             "primary_qb_dropbacks": 30, "primary_qb_dropback_share": 1, "primary_qb_epa": -0.1,
             "primary_qb_cpoe": -2},
            {"game_date": "2025-09-08", "primary_qb_id": "new", "primary_qb_name": "New QB",
             "primary_qb_dropbacks": 35, "primary_qb_dropback_share": 0.9, "primary_qb_epa": 0.2,
             "primary_qb_cpoe": 4},
            {"game_date": "2025-09-15", "primary_qb_id": "new", "primary_qb_name": "New QB",
             "primary_qb_dropbacks": 32, "primary_qb_dropback_share": 1, "primary_qb_epa": 0.1,
             "primary_qb_cpoe": 2},
        ]}
        profile = quarterback_profile(history, "A")
        self.assertEqual(profile["qb_id"], "new")
        self.assertEqual(profile["dropbacks"], 67)
        self.assertAlmostEqual(profile["epa"], 0.15)
        self.assertAlmostEqual(profile["continuity"], 2 / 3)

    def test_rolling_backtest_is_out_of_sample(self):
        rows = []
        for index in range(40):
            features = {name: 0.0 for name in FEATURE_NAMES}
            features["epa_matchup_edge"] = 1 if index % 2 else -1
            rows.append({"eligible": True, "game_id": str(index), "block_key": [2025, 1, index // 4],
                         "features": features, "outcome": float(index % 2), "elo_home_probability": 0.5})
        report = rolling_backtest(rows, min_train=20, test_size=5)
        self.assertEqual(report["model"]["n"], 20)
        self.assertLess(report["model"]["log_loss"], report["elo"]["log_loss"])

    def test_promotion_gate_requires_proper_scores_and_confidence_interval(self):
        failed = promotion_gate({"full": {"model": {"n": 800, "log_loss": 0.64, "brier": 0.23},
                                                   "elo": {"log_loss": 0.65, "brier": 0.22},
                                                   "paired_bootstrap": {"ci95": [-0.02, 0.01]}}})
        self.assertFalse(failed["passed"])
        passed = promotion_gate({"full": {"model": {"n": 800, "log_loss": 0.63, "brier": 0.21},
                                                   "elo": {"log_loss": 0.65, "brier": 0.22},
                                                   "paired_bootstrap": {"ci95": [-0.03, -0.005]}}})
        self.assertTrue(passed["passed"])


if __name__ == "__main__":
    unittest.main()
