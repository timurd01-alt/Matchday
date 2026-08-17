import tempfile
import unittest
from pathlib import Path

import forecast_ledger
import market_snapshots
from baseline_tournament import build_report


def record(fixture_id, kickoff, locked_at, result, home_probability, market_home=55):
    shadow = {"mode": "research_only", "production_weight": 0,
              "elo_baseline_home_probability": home_probability - .04,
              "calibrated_elo_home_probability": home_probability - .02}
    return {"integrity_eligible": True, "fixture_id": fixture_id, "competition": "NFL",
            "home": "A", "away": "B", "kickoff": kickoff, "locked_at": locked_at,
            "status_at_lock": "UPCOMING", "prediction_snapshot": {
                "model": {"h": home_probability * 100, "d": 0, "a": (1-home_probability) * 100}},
            "probs": {"h": (home_probability + .01) * 100, "d": 0, "a": (1-home_probability-.01) * 100},
            "market_snapshot": {"h": market_home, "d": 0, "a": 100-market_home},
            "input_snapshot": {"match": {"nfl_challenger_shadow": shadow}},
            "result": result, "score": "24-17",
            "result_snapshot": {"observed_at": kickoff.replace("00:20:00", "04:00:00")}}


class BaselineTournamentTests(unittest.TestCase):
    def test_scores_six_models_on_identical_nfl_fixture(self):
        with tempfile.TemporaryDirectory() as directory:
            forecast_path = Path(directory) / "forecast.jsonl"
            market_path = Path(directory) / "market.jsonl"
            rec = record("g1", "2026-09-10T00:20:00Z", "2026-09-09T18:00:00Z", "h", .62)
            forecast_ledger.sync_pick_records(forecast_path, [rec], "NFL")
            market_snapshots.append_batch(market_path, {"source": "Book A",
                "authorization_basis": "licensed", "source_reference": "contract:odds",
                "fetched_at": "2026-09-09T17:00:00Z", "snapshots": [{
                    "fixture_id": "g1", "competition": "NFL", "kickoff": rec["kickoff"],
                    "observed_at": "2026-09-09T16:59:00Z", "market_type": "moneyline",
                    "participants": {"home": {"id": "A", "name": "A"},
                                     "away": {"id": "B", "name": "B"}},
                    "odds_format": "decimal", "outcomes": {"h": 1.8, "a": 2.1}}]},
                "2026-09-09T17:01:00Z")
            report = build_report([forecast_path], market_path)
            self.assertEqual(report["all_models_common_fixtures"], 1)
            self.assertEqual(report["overall"]["calibrated_elo"]["n"], 1)
            self.assertEqual(report["overall"]["no_vig_lock_market"]["n"], 1)
            self.assertEqual(report["pairwise_vs_matchday_independent"]["calibrated_elo"]
                             ["candidate_same_fixtures"]["n"], 1)
            self.assertEqual(report["production_weight"], 0)

    def test_league_prior_uses_only_grades_known_before_target_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "forecast.jsonl"
            early = record("early", "2026-09-03T00:20:00Z", "2026-09-02T18:00:00Z", "h", .60)
            target = record("target", "2026-09-10T00:20:00Z", "2026-09-09T18:00:00Z", "a", .60)
            future = record("future", "2026-09-17T00:20:00Z", "2026-09-16T18:00:00Z", "h", .60)
            forecast_ledger.sync_pick_records(path, [early, target, future], "NFL")
            report = build_report([path])
            rows = {row["fixture_id"]: row for row in report["rows"]}
            self.assertAlmostEqual(rows["target"]["league_prior"]["h"], 3/5)
            self.assertAlmostEqual(rows["target"]["league_prior"]["a"], 2/5)
            self.assertAlmostEqual(rows["early"]["league_prior"]["h"], .5)

    def test_market_result_is_used_for_three_way_settlement(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "forecast.jsonl"
            rec = record("g1", "2026-09-10T00:20:00Z", "2026-09-09T18:00:00Z", "h", .62)
            rec["prediction_snapshot"]["model"] = {"h": 40, "d": 30, "a": 30}
            rec["probs"] = {"h": 39, "d": 31, "a": 30}
            rec["market_snapshot"] = {"h": 38, "d": 32, "a": 30}
            rec["market_result"] = "d"
            forecast_ledger.sync_pick_records(path, [rec], "SOCCER")
            report = build_report([path])
            self.assertEqual(report["rows"][0]["result"], "d")
            self.assertIsNone(report["rows"][0]["raw_elo"])

    def test_excludes_three_way_knockout_without_regulation_settlement(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "forecast.jsonl"
            rec = record("g1", "2026-09-10T00:20:00Z", "2026-09-09T18:00:00Z", "h", .62)
            rec["prediction_snapshot"]["model"] = {"h": 40, "d": 30, "a": 30}
            rec["probs"] = {"h": 39, "d": 31, "a": 30}
            rec["market_snapshot"] = {"h": 38, "d": 32, "a": 30}
            forecast_ledger.sync_pick_records(path, [rec], "SOCCER")

            report = build_report([path])

            self.assertEqual(report["rows"], [])
            self.assertEqual(report["coverage"]["incompatible_result"], 1)

    def test_excludes_two_way_tie_as_moneyline_push(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "forecast.jsonl"
            rec = record("g1", "2026-09-10T00:20:00Z", "2026-09-09T18:00:00Z", "d", .62)
            rec["market_result"] = "d"
            rec["score"] = "20-20"
            forecast_ledger.sync_pick_records(path, [rec], "NFL")

            report = build_report([path])

            self.assertEqual(report["rows"], [])
            self.assertEqual(report["coverage"]["incompatible_result"], 1)

    def test_same_provider_fixture_id_in_two_competitions_does_not_collide(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "forecast.jsonl"
            first = record("shared-id", "2026-09-10T00:20:00Z", "2026-09-09T18:00:00Z", "h", .62)
            second = record("shared-id", "2026-09-11T00:20:00Z", "2026-09-10T18:00:00Z", "a", .58)
            forecast_ledger.sync_pick_records(path, [first], "NFL")
            forecast_ledger.sync_pick_records(path, [second], "NCAAF")
            report = build_report([path])
            self.assertEqual(report["coverage"]["eligible"], 2)
            self.assertEqual({row["competition"] for row in report["rows"]}, {"NFL", "NCAAF"})


if __name__ == "__main__":
    unittest.main()
