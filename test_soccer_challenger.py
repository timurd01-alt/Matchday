import unittest

from soccer_challenger import FEATURE_NAMES, ablation_report, build_point_in_time_rows


def fixtures(days=14):
    matches, events = [], []
    teams = ["A", "B", "C", "D"]
    for day in range(1, days + 1):
        pairings = [(teams[(day + offset) % 4], teams[(day + offset + 1) % 4])
                    for offset in (0, 2)]
        for number, (home, away) in enumerate(pairings):
            match_id = f"{day}-{number}"
            outcome = (day + number) % 3
            home_score, away_score = ((2, 0) if outcome == 0 else (1, 1) if outcome == 1 else (0, 1))
            matches.append({"match_id": match_id, "match_date": f"2025-01-{day:02d}",
                            "competition": {"competition_id": 1, "competition_name": "Test League"},
                            "season": {"season_id": 10, "season_name": "2025"},
                            "home_team": {"home_team_name": home},
                            "away_team": {"away_team_name": away},
                            "home_score": home_score, "away_score": away_score})
            for team, goals in ((home, home_score), (away, away_score)):
                lineup = [{"player": {"id": f"{team}-{player}"}} for player in range(11)]
                events.append({"match_id": match_id, "period": 1, "team": {"name": team},
                               "type": {"name": "Starting XI"}, "tactics": {"lineup": lineup}})
                for sequence in range(1, 5):
                    events.append({"match_id": match_id, "period": 1, "team": {"name": team},
                                   "type": {"name": "Pass"}, "possession": sequence,
                                   "possession_team": {"name": team}, "location": [70 + sequence * 4, 40],
                                   "pass": {}})
                events.append({"match_id": match_id, "period": 1, "team": {"name": team},
                               "type": {"name": "Pressure"}, "possession": 8,
                               "possession_team": {"name": team}})
                for shot in range(2):
                    is_goal = shot < goals
                    events.append({"match_id": match_id, "period": 2, "team": {"name": team},
                                   "type": {"name": "Shot"}, "location": [102, 40],
                                   "possession": 10 + shot, "possession_team": {"name": team},
                                   "play_pattern": {"name": "Regular Play"},
                                   "shot": {"statsbomb_xg": .25 if is_goal else .10,
                                            "type": {"name": "Open Play"},
                                            "outcome": {"name": "Goal" if is_goal else "Saved"}}})
    return matches, events


class SoccerChallengerTests(unittest.TestCase):
    def test_rows_are_three_way_prior_date_receipts(self):
        rows = build_point_in_time_rows(*fixtures(8), min_history=2)
        eligible = [row for row in rows if row["eligible"]]
        self.assertTrue(eligible)
        self.assertEqual(set(eligible[0]["features"]), set(FEATURE_NAMES))
        self.assertAlmostEqual(sum(eligible[0]["poisson_probabilities"].values()), 1.0)
        self.assertAlmostEqual(sum(eligible[0]["elo_probabilities"].values()), 1.0)
        self.assertLess(eligible[0]["feature_observed_through"], eligible[0]["match_date"])
        same_date = [row for row in rows if row["match_date"] == eligible[0]["match_date"]]
        self.assertEqual(len({row["feature_observed_through"] for row in same_date}), 1)
        self.assertIn(eligible[0]["outcome"], {"home", "draw", "away"})

    def test_ablation_report_is_coverage_aware_and_zero_weight(self):
        rows = build_point_in_time_rows(*fixtures(), min_history=2)
        report = ablation_report(rows, min_train=8)
        self.assertGreater(report["full"]["model"]["n"], 0)
        self.assertEqual(report["production_weight"], 0)
        self.assertEqual(set(report["ablations"]), {
            "xg_strength", "shot_quality", "possession_territory", "pressure",
            "set_piece", "lineup_history", "context"})
        self.assertEqual(report["coverage"]["complete_matches"], len(rows))
        self.assertGreater(report["ablations"]["xg_strength"]["full_vs_without_family"]["n"], 0)
        self.assertEqual(report["promotion_gate"]["decision"], "remain_research_only")


if __name__ == "__main__":
    unittest.main()
