import json
import pathlib
import sys
import unittest


if "--mlb" not in sys.argv:
    sys.argv.append("--mlb")
import fetch_data


LEDGER = pathlib.Path(__file__).with_name("picks_log_mlb.json")
EXPECTED_ARTIFACTS = {
    217: (30290215557, 8662644485, "093cf03fa6de8c7ef9315602500b91d56ba00a48eea32ab257cedf873d34d223"),
    219: (30305460405, 8668629605, "fd9b7b7a78e4da715fc19228aa3b7aaae39584a46d3bbef803eabb4eb6e96d9b"),
    220: (30312540937, 8671064528, "2550ee85c8be679237128619bbfb8e4abe197d81be1a2ef9aac5583b701ac78e"),
    221: (30316183549, 8672343114, "ec1dbb075e17f4397457d0e9cfcef708323c0edb92fd0960bd0296c6996b8944"),
}


class RecoveredMlbPickTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.picks = json.loads(LEDGER.read_text(encoding="utf-8"))
        cls.recovered = {
            fixture_id: record
            for fixture_id, record in cls.picks.items()
            if record.get("artifact_verification")
        }

    def test_all_twelve_records_pass_the_normal_official_gate(self):
        self.assertEqual(len(self.recovered), 12)
        self.assertTrue(all(fetch_data._record_is_official(record) for record in self.picks.values()))

    def test_every_record_points_to_a_verified_github_pages_artifact(self):
        for record in self.recovered.values():
            proof = record["artifact_verification"]
            run_id, artifact_id, data_hash = EXPECTED_ARTIFACTS[proof["workflow_number"]]
            self.assertEqual(proof["run_id"], run_id)
            self.assertEqual(proof["artifact_id"], artifact_id)
            self.assertEqual(proof["data_sha256"], data_hash)
            self.assertEqual(proof["url"], f"https://github.com/timurd01-alt/Matchday/actions/runs/{run_id}")

    def test_recovery_used_only_snapshots_inside_the_two_hour_window(self):
        for record in self.recovered.values():
            self.assertGreaterEqual(record["lead_time_seconds"], 0)
            self.assertLessEqual(record["lead_time_seconds"], fetch_data.LOCK_WINDOW_HOURS * 3600)
            self.assertEqual(record["status_at_lock"], "UPCOMING")
            self.assertIn(record["integrity_reason"], {
                "verified_pregame_window",
                "verified_pregame_github_pages_artifact_recovery",
            })


if __name__ == "__main__":
    unittest.main()
