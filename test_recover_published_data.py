import io
import json
import tempfile
import unittest
from pathlib import Path

import recover_published_data


class Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


class PublishedDataRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    @staticmethod
    def payload(key="ncaaf"):
        return {
            "updated": "2026-07-29T00:00:00Z",
            "competition": "College Football",
            "comp_key": key.upper(),
            "matches": [],
        }

    def test_recovers_valid_first_party_snapshot(self):
        raw = json.dumps(self.payload()).encode("utf-8")
        calls = []

        def opener(request, timeout):
            calls.append((request.full_url, timeout))
            return Response(raw)

        result = recover_published_data.recover(self.root, ("ncaaf",), opener)
        self.assertEqual(result["recovered"], ["ncaaf"])
        self.assertEqual(calls, [("https://matchdayterminal.com/data_ncaaf.json", 30)])
        saved = json.loads((self.root / "data_ncaaf.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["comp_key"], "NCAAF")

    def test_keeps_valid_local_snapshot_without_network(self):
        path = self.root / "data_ncaaf.json"
        path.write_text(json.dumps(self.payload()), encoding="utf-8")

        def opener(_request, _timeout):
            raise AssertionError("network should not be called")

        result = recover_published_data.recover(self.root, ("ncaaf",), opener)
        self.assertEqual(result["present"], ["ncaaf"])

    def test_rejects_wrong_competition_without_overwriting(self):
        raw = json.dumps(self.payload("ncaam")).encode("utf-8")
        result = recover_published_data.recover(
            self.root, ("ncaaf",), lambda _request, timeout: Response(raw))
        self.assertIn("ncaaf", result["failed"])
        self.assertFalse((self.root / "data_ncaaf.json").exists())


if __name__ == "__main__":
    unittest.main()
