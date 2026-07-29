import unittest

from basketball_challenger import FEATURE_NAMES, ablation_report, build_point_in_time_rows


def boxes(days=14):
    rows = []
    teams = ["A", "B", "C", "D"]
    for day in range(1, days + 1):
        pairings = [(teams[(day + offset) % 4], teams[(day + offset + 1) % 4])
                    for offset in (0, 2)]
        for game_number, (home, away) in enumerate(pairings):
            game_id = f"{day}-{game_number}"
            home_win = (day + game_number) % 3 != 0
            home_points, away_points = ((108, 99) if home_win else (97, 104))
            common = {"game_id": game_id, "game_date": f"2026-01-{day:02d}",
                      "fga": 80, "fta": 20, "orb": 10, "drb": 28, "tov": 11,
                      "three_pa": 30}
            rows.extend([
                {**common, "team": home, "opponent": away, "is_home": True,
                 "points": home_points, "fgm": 39 if home_win else 34,
                 "three_pm": 11 if home_win else 8},
                {**common, "team": away, "opponent": home, "is_home": False,
                 "points": away_points, "fgm": 35 if home_win else 38,
                 "three_pm": 9 if home_win else 10},
            ])
    return rows


class BasketballChallengerTests(unittest.TestCase):
    def test_rows_are_point_in_time_and_date_blocks_are_sealed(self):
        rows = build_point_in_time_rows(boxes(8), min_history=2, rolling_games=10)
        eligible = [row for row in rows if row["eligible"]]
        self.assertTrue(eligible)
        self.assertEqual(set(eligible[0]["features"]), set(FEATURE_NAMES))
        self.assertLess(eligible[0]["feature_observed_through"], eligible[0]["game_date"])
        same_day = [row for row in rows if row["game_date"] == eligible[0]["game_date"]]
        self.assertEqual(len({row["feature_observed_through"] for row in same_day}), 1)

    def test_ablation_report_is_zero_weight_and_does_not_auto_promote(self):
        rows = build_point_in_time_rows(boxes(), min_history=2, rolling_games=10)
        report = ablation_report(rows, min_train=8)
        self.assertGreater(report["full"]["model"]["n"], 0)
        self.assertEqual(report["production_weight"], 0)
        self.assertEqual(set(report["ablations"]), {
            "adjusted_efficiency", "shooting", "possession", "tempo", "context"})
        self.assertGreater(report["ablations"]["shooting"]["full_vs_without_family"]["n"], 0)
        self.assertEqual(report["promotion_gate"]["decision"], "remain_research_only")


if __name__ == "__main__":
    unittest.main()
