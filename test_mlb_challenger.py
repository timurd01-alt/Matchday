import unittest

from mlb_challenger import FEATURE_NAMES, ablation_report, build_point_in_time_rows, parse_event_games


def fixtures(seasons=(2023, 2024, 2025), days=12):
    events, logs = [], []
    teams = ["AAA", "BBB", "CCC", "DDD"]
    for season in seasons:
        for day in range(1, days + 1):
            for number, offset in enumerate((0, 2)):
                away = teams[(day + offset) % 4]
                home = teams[(day + offset + 1) % 4]
                raw_date = f"{season}04{day:02d}"
                game_id = f"{home}{raw_date}0"
                home_runs = 5 if (day + number + season) % 2 else 2
                away_runs = 2 if home_runs == 5 else 4
                log = [raw_date, "0", "Mon", away, "AL", str(day), home, "NL", str(day),
                       str(away_runs), str(home_runs)]
                logs.append(",".join(log))
                events.extend([f"id,{game_id}", f"info,visteam,{away}", f"info,hometeam,{home}",
                               f"start,{away}p,Pitcher,0,9,1", f"start,{home}p,Pitcher,1,9,1"])
                for side in (0, 1):
                    for pa, outcome in enumerate(("K", "W", "S7", "D8", "HR", "63", "SB2", "WP")):
                        events.append(f"play,1,{side},b{pa},00,,{outcome}")
                    events.append(f"sub,{teams[side]}r,Reliever,{side},9,1")
    return events, logs


class MlbChallengerTests(unittest.TestCase):
    def test_event_parser_excludes_non_plate_appearances(self):
        events, _ = fixtures((2025,), 1)
        parsed = parse_event_games(events)
        game = next(iter(parsed.values()))
        for team in (game["away_team"], game["home_team"]):
            self.assertEqual(game["batting"][team]["pa"], 6)
            self.assertEqual(len(game["pitchers"][team]), 2)

    def test_rows_are_prior_date_and_do_not_use_target_personnel(self):
        rows, rejected = build_point_in_time_rows(*fixtures(), min_history=2, rolling_games=8)
        eligible = [row for row in rows if row["eligible"]]
        self.assertTrue(eligible)
        self.assertEqual(rejected, {})
        self.assertEqual(set(eligible[0]["features"]), set(FEATURE_NAMES))
        self.assertLess(eligible[0]["feature_observed_through"], eligible[0]["game_date"])
        self.assertFalse(eligible[0]["target_game_personnel_used"])
        self.assertIn("confirmed_starter", eligible[0]["unavailable_pregame_families"])

    def test_ablation_is_zero_weight_and_requires_live_personnel_source(self):
        rows, _ = build_point_in_time_rows(*fixtures(days=14), min_history=2, rolling_games=8)
        report = ablation_report(rows, min_train=10)
        self.assertGreater(report["full"]["model"]["n"], 0)
        self.assertEqual(report["production_weight"], 0)
        self.assertEqual(set(report["ablations"]), {
            "run_strength", "plate_discipline", "power_contact", "run_prevention",
            "bullpen_workload", "context"})
        self.assertEqual(report["live_personnel_gate"]["decision"], "blocked_without_timestamped_pregame_source")
        self.assertIn(report["standings_compatible_candidate"]["decision"],
                      {"eligible_for_prospective_shadow", "remain_research_only"})
        self.assertEqual(report["promotion_gate"]["decision"], "remain_research_only")


if __name__ == "__main__":
    unittest.main()
