import tempfile
import unittest
from pathlib import Path

import forecast_ledger
import market_snapshots
from market_benchmark import build_report


def pick_record():
    return {"integrity_eligible": True, "fixture_id": "game-1", "competition": "NFL",
            "home": "A", "away": "B", "kickoff": "2026-09-10T00:20:00Z",
            "locked_at": "2026-09-09T18:00:00Z", "status_at_lock": "UPCOMING",
            "prediction_snapshot": {"model": {"h": 60, "d": 0, "a": 40}},
            "input_snapshot": {"match": {}}, "result": "h", "score": "24-17",
            "result_snapshot": {"observed_at": "2026-09-10T04:00:00Z"}}


def odds_batch(observed_at, home_odds, away_odds, source="Book A"):
    return {"source": source, "authorization_basis": "licensed",
            "source_reference": f"contract:{source}", "fetched_at": observed_at,
            "snapshots": [{"fixture_id": "game-1", "competition": "NFL",
                "kickoff": "2026-09-10T00:20:00Z", "observed_at": observed_at,
                "market_type": "moneyline", "odds_format": "decimal",
                "outcomes": {"h": home_odds, "a": away_odds}}]}


class MarketBenchmarkTests(unittest.TestCase):
    def test_reconstructs_open_lock_and_close_without_post_lock_leakage(self):
        with tempfile.TemporaryDirectory() as directory:
            forecast_path = Path(directory) / "forecasts.jsonl"
            market_path = Path(directory) / "markets.jsonl"
            forecast_ledger.sync_pick_records(forecast_path, [pick_record()], "NFL")
            market_snapshots.append_batch(market_path,
                odds_batch("2026-09-09T12:00:00Z", 2.0, 2.0), "2026-09-09T12:01:00Z")
            market_snapshots.append_batch(market_path,
                odds_batch("2026-09-09T17:00:00Z", 1.8, 2.1), "2026-09-09T17:01:00Z")
            market_snapshots.append_batch(market_path,
                odds_batch("2026-09-10T00:00:00Z", 1.6, 2.5), "2026-09-10T00:01:00Z")
            report = build_report([forecast_path], market_path)
            row = report["rows"][0]
            self.assertAlmostEqual(row["opening_market"]["h"], .5)
            self.assertLess(row["lock_market"]["h"], row["closing_market"]["h"])
            self.assertEqual(report["comparisons"]["closing_market"]["market"]["n"], 1)
            self.assertEqual(report["comparisons"]["closing_market"]["paired_log_loss"]["n"], 1)
            self.assertGreater(report["closing_line_movement"]["mean_probability_movement_toward_matchday_pick"], 0)
            self.assertEqual(report["production_weight"], 0)

    def test_consensus_averages_latest_snapshot_from_each_source(self):
        with tempfile.TemporaryDirectory() as directory:
            forecast_path = Path(directory) / "forecasts.jsonl"
            market_path = Path(directory) / "markets.jsonl"
            forecast_ledger.sync_pick_records(forecast_path, [pick_record()], "NFL")
            market_snapshots.append_batch(market_path,
                odds_batch("2026-09-09T17:00:00Z", 2.0, 2.0, "Book A"), "2026-09-09T17:01:00Z")
            market_snapshots.append_batch(market_path,
                odds_batch("2026-09-09T17:30:00Z", 1.5, 3.0, "Book B"), "2026-09-09T17:31:00Z")
            report = build_report([forecast_path], market_path)
            receipt = report["rows"][0]["market_receipts"]["lock"]
            self.assertEqual(receipt["source_count"], 2)
            self.assertAlmostEqual(report["rows"][0]["lock_market"]["h"], .583333335)

    def test_uses_regulation_market_result_when_advancement_differs(self):
        with tempfile.TemporaryDirectory() as directory:
            forecast_path = Path(directory) / "forecasts.jsonl"
            market_path = Path(directory) / "markets.jsonl"
            record = pick_record()
            record["result"] = "h"
            record["market_result"] = "a"
            forecast_ledger.sync_pick_records(forecast_path, [record], "NFL")
            market_snapshots.append_batch(market_path,
                odds_batch("2026-09-09T17:00:00Z", 1.8, 2.1), "2026-09-09T17:01:00Z")
            report = build_report([forecast_path], market_path)
            self.assertEqual(report["rows"][0]["result"], "a")


if __name__ == "__main__":
    unittest.main()
