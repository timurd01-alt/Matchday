import json
import tempfile
import unittest
from pathlib import Path

import forecast_ledger
import reconcile_forecast_ledgers
from test_forecast_ledger import official_record


class ReconcileForecastLedgersTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_reconciles_every_official_lock_and_grade(self):
        record = official_record("h")
        record.update({"model_hit": True, "score": "24-17"})
        (self.root / "picks_log_nfl.json").write_text(
            json.dumps({"fixture-1": record}), encoding="utf-8"
        )
        report = reconcile_forecast_ledgers.reconcile(self.root)["NFL"]
        self.assertTrue(report["complete"])
        self.assertEqual(report["logged_locks"], 1)
        self.assertEqual(report["logged_grades"], 1)
        self.assertEqual(
            forecast_ledger.validate(self.root / "forecast_ledger_nfl.jsonl")["events"], 2
        )

    def test_replay_is_idempotent(self):
        (self.root / "picks_log_nfl.json").write_text(
            json.dumps({"fixture-1": official_record()}), encoding="utf-8"
        )
        reconcile_forecast_ledgers.reconcile(self.root)
        second = reconcile_forecast_ledgers.reconcile(self.root)["NFL"]
        self.assertEqual(second["appended"], 0)


if __name__ == "__main__":
    unittest.main()
