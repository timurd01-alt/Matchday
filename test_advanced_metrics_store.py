import json
import tempfile
import unittest
from pathlib import Path

from advanced_metrics_store import attach_shadow_profiles, load_profile_file


class AdvancedMetricStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def _write(self, source="nflverse-data pbp release"):
        path = self.root / "advanced_metrics_nfl.json"
        path.write_text(json.dumps({
            "schema_version": 1, "shadow_only": True, "sport": "NFL",
            "source": source, "license": "CC BY 4.0", "generated_at": "now",
            "profiles": {"KC": {"epa_per_play": 0.2}, "BUF": {"epa_per_play": 0.1}},
        }), encoding="utf-8")
        return path

    def test_attaches_abbreviation_profiles_by_full_name(self):
        self._write()
        matches = [{"home": {"name": "Kansas City Chiefs"}, "away": {"name": "Buffalo Bills"}}]
        result = attach_shadow_profiles(matches, "NFL", "football", self.root)
        self.assertEqual(result["teams"], 2)
        self.assertEqual(matches[0]["advanced_metrics"]["home"]["epa_per_play"], 0.2)
        self.assertTrue(matches[0]["advanced_metrics_meta"]["shadow_only"])
        self.assertEqual(matches[0]["advanced_metrics_meta"]["production_weight"], 0)
        self.assertEqual(matches[0]["research_signal_schema"], 1)

    def test_rejects_espn_origin_profile(self):
        path = self._write("ESPN downstream dump")
        with self.assertRaisesRegex(ValueError, "ESPN-origin"):
            load_profile_file(path)

    def test_historical_research_profile_does_not_attach_live(self):
        path = self._write()
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["attach_live"] = False
        path.write_text(json.dumps(payload), encoding="utf-8")
        matches = [{"home": {"name": "Kansas City Chiefs"}, "away": {"name": "Buffalo Bills"}}]
        result = attach_shadow_profiles(matches, "NFL", "football", self.root)
        self.assertIsNone(result["file"])
        self.assertNotIn("advanced_metrics", matches[0])
        self.assertEqual(matches[0]["research_signal_schema"], 1)


if __name__ == "__main__":
    unittest.main()
