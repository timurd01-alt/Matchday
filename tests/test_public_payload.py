import json
import tempfile
import unittest
from pathlib import Path

import build_public_payload


class PublicPayloadTests(unittest.TestCase):
    def test_ncaaf_drops_only_browser_redundancy(self):
        payload = {
            "competition": "NCAAF",
            "scorecard": {"graded": 12, "picks": [{"input_snapshot": {"large": True}}]},
            "matches": [{"id": "one", "prediction": {"pick": "h"},
                         "betbetter_pick": {"model_pct": 60.0}}],
        }
        out = build_public_payload.public_payload(payload, "ncaaf")
        self.assertEqual(out["scorecard"], {"graded": 12})
        self.assertEqual(out["matches"][0], {"id": "one", "prediction": {"pick": "h"}})

    def test_ncaam_keeps_attached_pick_until_snapshot_carries_it(self):
        payload = {"matches": [{"betbetter_pick": {"model_pct": 55.0}}]}
        out = build_public_payload.public_payload(payload, "ncaam")
        self.assertIn("betbetter_pick", out["matches"][0])

    def test_writer_uses_compact_json(self):
        with tempfile.TemporaryDirectory() as folder:
            source, destination = Path(folder) / "in.json", Path(folder) / "out.json"
            source.write_text(json.dumps({"matches": [], "scorecard": {"picks": []}}, indent=2))
            build_public_payload.build(source, destination, "ncaaf")
            text = destination.read_text(encoding="utf-8")
            self.assertNotIn("\n", text)
            self.assertEqual(json.loads(text), {"matches": [], "scorecard": {}})


if __name__ == "__main__":
    unittest.main()
