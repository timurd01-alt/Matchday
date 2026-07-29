import unittest

from cfb_challenger import FEATURE_NAMES, ablation_report, build_point_in_time_rows


def fixtures(weeks=14):
    games, advanced = [], []
    teams = ["A", "B", "C", "D"]
    for week in range(1, weeks + 1):
        pairings = [(teams[(week + offset) % 4], teams[(week + offset + 1) % 4])
                    for offset in (0, 2)]
        for number, (home, away) in enumerate(pairings):
            game_id = f"{week}-{number}"
            home_win = (week + number) % 3 != 0
            games.append({"id": game_id, "season": 2025, "week": week, "completed": True,
                          "startDate": f"2025-09-{min(week * 2, 28):02d}T16:00:00Z",
                          "homeTeam": home, "awayTeam": away,
                          "homePoints": 31 if home_win else 20,
                          "awayPoints": 20 if home_win else 27,
                          "neutralSite": week == 14})
            for team, quality in ((home, .08 if home_win else -.08),
                                  (away, -.08 if home_win else .08)):
                advanced.append({"gameId": game_id, "team": team, "offense": {
                    "plays": 68, "ppa": .12 + quality, "successRate": .43 + quality / 3,
                    "explosiveness": 1.2 + quality,
                }})
    talent = [{"season": 2025, "available_week": 0, "team": team, "talent": score}
              for team, score in zip(teams, (900, 800, 700, 600))]
    return games, advanced, talent


class CollegeFootballChallengerTests(unittest.TestCase):
    def test_rows_are_prior_week_only_and_feature_complete(self):
        rows = build_point_in_time_rows(*fixtures(8), min_history=2)
        eligible = [row for row in rows if row["eligible"]]
        self.assertTrue(eligible)
        self.assertEqual(set(eligible[0]["features"]), set(FEATURE_NAMES))
        self.assertLess(eligible[0]["feature_observed_through"], eligible[0]["block_id"])
        same_week = [row for row in rows if row["block_id"] == eligible[0]["block_id"]]
        self.assertEqual(len({row["feature_observed_through"] for row in same_week}), 1)
        self.assertEqual(eligible[0]["timestamp_quality"], "prior_completed_season_week_boundary")

    def test_talent_is_unavailable_until_its_declared_week(self):
        games, advanced, talent = fixtures(4)
        for row in talent:
            row["available_week"] = 3
        rows = build_point_in_time_rows(games, advanced, talent, min_history=0)
        week_three = next(row for row in rows if row["week"] == 3)
        week_four = next(row for row in rows if row["week"] == 4)
        self.assertEqual(week_three["features"]["talent_coverage_mean"], 0.0)
        self.assertEqual(week_four["features"]["talent_coverage_mean"], 1.0)

    def test_ablation_report_stays_zero_weight(self):
        rows = build_point_in_time_rows(*fixtures(), min_history=2)
        report = ablation_report(rows, min_train=8)
        self.assertGreater(report["full"]["model"]["n"], 0)
        self.assertEqual(report["production_weight"], 0)
        self.assertEqual(set(report["ablations"]), {
            "ppa", "success", "explosiveness", "opponent_adjustment", "talent_prior", "context"})
        self.assertGreater(report["ablations"]["talent_prior"]["full_vs_without_family"]["n"], 0)
        self.assertEqual(report["promotion_gate"]["decision"], "remain_research_only")


if __name__ == "__main__":
    unittest.main()
