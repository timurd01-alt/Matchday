import json
import tempfile
import unittest
from pathlib import Path

from nfl_availability import append_batch, fixture_receipt, validate


def batch(status="QUESTIONABLE", source="Licensed Provider"):
    return {"source": source, "authorization_basis": "licensed",
            "source_reference": "provider-contract:nfl-availability",
            "fetched_at": "2026-09-09T15:00:00Z", "observations": [{
                "fixture_id": "game-1", "kickoff": "2026-09-10T00:20:00Z",
                "observed_at": "2026-09-09T14:55:00Z", "team_code": "SEA",
                "player_id": "qb-1", "player_name": "Example QB", "position_group": "QB",
                "role": "STARTER", "status": status, "confidence": .9,
                "source_observation_id": "status-1"}]}


class NFLAvailabilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "availability.jsonl"

    def tearDown(self):
        self.temp.cleanup()

    def test_appends_authorized_batch_and_replay_is_idempotent(self):
        first = append_batch(self.path, batch(), "2026-09-09T15:01:00Z")
        second = append_batch(self.path, batch(), "2026-09-09T15:02:00Z")
        self.assertTrue(first["created"])
        self.assertFalse(second["created"])
        self.assertEqual(validate(self.path)["events"], 1)

    def test_rejects_post_kickoff_future_dated_and_espn_records(self):
        with self.assertRaisesRegex(ValueError, "before kickoff"):
            append_batch(self.path, batch(), "2026-09-10T00:21:00Z")
        future_observation = batch()
        future_observation["fetched_at"] = "2026-09-09T13:55:00Z"
        with self.assertRaisesRegex(ValueError, "after it is recorded"):
            append_batch(self.path, future_observation, "2026-09-09T14:00:00Z")
        with self.assertRaisesRegex(ValueError, "ESPN-origin"):
            append_batch(self.path, batch(source="ESPN"), "2026-09-09T15:01:00Z")

    def test_latest_status_wins_without_changing_probability(self):
        append_batch(self.path, batch(), "2026-09-09T15:01:00Z")
        update = batch("OUT")
        update["fetched_at"] = "2026-09-09T18:00:00Z"
        update["observations"][0]["observed_at"] = "2026-09-09T17:55:00Z"
        update["observations"][0]["source_observation_id"] = "status-2"
        append_batch(self.path, update, "2026-09-09T18:01:00Z")
        receipt = fixture_receipt(self.path, "game-1", "2026-09-10T00:20:00Z",
                                  "2026-09-09T19:00:00Z")
        self.assertEqual(receipt["observations"][0]["status"], "OUT")
        self.assertEqual(receipt["team_summaries"]["SEA"]["starter_out"], 1)
        self.assertEqual(receipt["availability_probability_adjustment"], 0)

    def test_hash_tampering_is_detected(self):
        append_batch(self.path, batch(), "2026-09-09T15:01:00Z")
        event = json.loads(self.path.read_text(encoding="utf-8"))
        event["observations"][0]["status"] = "ACTIVE"
        self.path.write_text(json.dumps(event) + "\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            validate(self.path)


if __name__ == "__main__":
    unittest.main()
