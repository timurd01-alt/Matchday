import json
import tempfile
import unittest
from pathlib import Path

from market_snapshots import append_batch, fixture_snapshots, no_vig_probabilities, validate


def batch(outcomes=None, observed_at="2026-09-09T14:55:00Z"):
    return {"source": "Licensed Odds Provider", "authorization_basis": "licensed",
            "source_reference": "provider-contract:odds", "fetched_at": "2026-09-09T15:00:00Z",
            "snapshots": [{"fixture_id": "game-1", "competition": "NFL",
                "kickoff": "2026-09-10T00:20:00Z", "observed_at": observed_at,
                "market_type": "moneyline", "odds_format": "decimal",
                "outcomes": outcomes or {"h": 1.8, "a": 2.1}, "source_snapshot_id": "odds-1"}]}


class MarketSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "markets.jsonl"

    def tearDown(self):
        self.temp.cleanup()

    def test_derives_no_vig_probabilities(self):
        raw, no_vig, overround = no_vig_probabilities({"h": 1.8, "a": 2.1}, "decimal")
        self.assertAlmostEqual(sum(no_vig.values()), 1.0)
        self.assertGreater(overround, 0)
        self.assertAlmostEqual(raw["h"], 1 / 1.8, places=7)

    def test_append_is_idempotent_and_fixture_receipt_is_ordered(self):
        first = append_batch(self.path, batch(), "2026-09-09T15:01:00Z")
        second = append_batch(self.path, batch(), "2026-09-09T15:02:00Z")
        self.assertTrue(first["created"])
        self.assertFalse(second["created"])
        snapshots = fixture_snapshots(self.path, "game-1", "2026-09-10T00:20:00Z")
        self.assertEqual(len(snapshots), 1)
        self.assertEqual(validate(self.path)["events"], 1)

    def test_rejects_unsupported_or_post_kickoff_data(self):
        payload = batch(); payload["authorization_basis"] = "public_web"
        with self.assertRaisesRegex(ValueError, "authorization_basis"):
            append_batch(self.path, payload, "2026-09-09T15:01:00Z")
        with self.assertRaisesRegex(ValueError, "before kickoff"):
            append_batch(self.path, batch(), "2026-09-10T00:21:00Z")
        payload = batch(); payload["source"] = "ESPN odds"
        with self.assertRaisesRegex(ValueError, "ESPN-origin"):
            append_batch(self.path, payload, "2026-09-09T15:01:00Z")

    def test_tampering_breaks_hash_chain(self):
        append_batch(self.path, batch(), "2026-09-09T15:01:00Z")
        event = json.loads(self.path.read_text(encoding="utf-8"))
        event["snapshots"][0]["no_vig_probabilities"]["h"] = .99
        self.path.write_text(json.dumps(event) + "\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            validate(self.path)


if __name__ == "__main__":
    unittest.main()
