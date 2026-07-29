import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import multi_fetch


class RunOnceTests(unittest.TestCase):
    def _run(self, outcomes, cached_payload=None):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        state = Path(temp.name) / "state.json"
        if cached_payload is not None:
            (Path(temp.name) / "data_mlb.json").write_text(
                json.dumps(cached_payload), encoding="utf-8")
        runner = mock.Mock(side_effect=outcomes)
        patches = [
            mock.patch.object(multi_fetch, "SPORTS", [("mlb", "--mlb")]),
            mock.patch.object(multi_fetch, "ONCE_RETRY_DELAY", 0),
            mock.patch.object(multi_fetch, "FORCE_REFETCH_ONCE", {"mlb"}),
            mock.patch.object(multi_fetch, "_run_one", runner),
            mock.patch.object(multi_fetch, "_deployable_last_good",
                              return_value=cached_payload is not None),
            mock.patch("generate_posts.regenerate_sitemap", return_value=0),
        ]
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)
        return state, runner

    def test_retries_and_fails_instead_of_deploying_stale_data(self):
        state, runner = self._run([False, False])
        with self.assertRaisesRegex(RuntimeError, "mlb"):
            multi_fetch.run_once(str(state))
        self.assertEqual(runner.call_count, 2)
        self.assertEqual(json.loads(state.read_text(encoding="utf-8")), {})

    def test_records_success_after_transient_retry(self):
        state, runner = self._run([False, True])
        multi_fetch.run_once(str(state))
        self.assertEqual(runner.call_count, 2)
        self.assertGreater(json.loads(state.read_text(encoding="utf-8"))["mlb"], 0)

    def test_rate_limit_preserves_valid_last_good_and_does_not_retry(self):
        payload = {"updated": "2026-07-29T00:00:00Z", "competition": "MLB", "matches": []}
        state, runner = self._run([False], cached_payload=payload)
        multi_fetch._LAST_FAILURE_OUTPUT["mlb"] = "HTTP Error 429: Too Many Requests"
        with mock.patch.object(multi_fetch, "_rate_limited_with_last_good", return_value=True):
            multi_fetch.run_once(str(state))
        self.assertEqual(runner.call_count, 1)
        self.assertEqual(json.loads(state.read_text(encoding="utf-8")), {})

    def test_non_rate_limit_still_fails_with_valid_cache(self):
        payload = {"updated": "2026-07-29T00:00:00Z", "competition": "MLB", "matches": []}
        state, runner = self._run([False, False], cached_payload=payload)
        with self.assertRaisesRegex(RuntimeError, "mlb"):
            multi_fetch.run_once(str(state))
        self.assertEqual(runner.call_count, 2)


class ModelSchemaRefreshTests(unittest.TestCase):
    def setUp(self):
        self.old_cwd = os.getcwd()
        self.temp = tempfile.TemporaryDirectory()
        os.chdir(self.temp.name)

    def tearDown(self):
        os.chdir(self.old_cwd)
        self.temp.cleanup()

    def _write_match(self, **extra):
        match = {"watchability": 50, **extra}
        Path("data_ncaaf.json").write_text(
            json.dumps({"matches": [match]}), encoding="utf-8")

    def test_old_model_schema_forces_one_refresh(self):
        self._write_match(model_signal_schema=1)
        self.assertTrue(multi_fetch._missing_fields("ncaaf"))

    def test_current_model_schema_returns_to_normal_cadence(self):
        self._write_match(model_signal_schema=6)
        self.assertFalse(multi_fetch._missing_fields("ncaaf"))


class RateLimitFallbackTests(unittest.TestCase):
    def setUp(self):
        self.old_cwd = os.getcwd()
        self.temp = tempfile.TemporaryDirectory()
        os.chdir(self.temp.name)
        multi_fetch._LAST_FAILURE_OUTPUT.clear()

    def tearDown(self):
        os.chdir(self.old_cwd)
        self.temp.cleanup()
        multi_fetch._LAST_FAILURE_OUTPUT.clear()

    def test_429_uses_structurally_valid_last_good_payload(self):
        Path("data_ncaaf.json").write_text(json.dumps({
            "updated": "2026-07-29T00:00:00Z",
            "competition": "College Football",
            "matches": [],
        }), encoding="utf-8")
        multi_fetch._LAST_FAILURE_OUTPUT["ncaaf"] = "HTTP Error 429: Too Many Requests"
        self.assertTrue(multi_fetch._rate_limited_with_last_good("ncaaf"))

    def test_429_without_valid_cache_remains_fatal(self):
        Path("data_ncaaf.json").write_text("not json", encoding="utf-8")
        multi_fetch._LAST_FAILURE_OUTPUT["ncaaf"] = "HTTP Error 429: Too Many Requests"
        self.assertFalse(multi_fetch._rate_limited_with_last_good("ncaaf"))


if __name__ == "__main__":
    unittest.main()
