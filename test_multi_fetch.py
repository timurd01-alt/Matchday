import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import multi_fetch


class RunOnceTests(unittest.TestCase):
    def _run(self, outcomes):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        state = Path(temp.name) / "state.json"
        runner = mock.Mock(side_effect=outcomes)
        patches = [
            mock.patch.object(multi_fetch, "SPORTS", [("mlb", "--mlb")]),
            mock.patch.object(multi_fetch, "ONCE_RETRY_DELAY", 0),
            mock.patch.object(multi_fetch, "FORCE_REFETCH_ONCE", {"mlb"}),
            mock.patch.object(multi_fetch, "_run_one", runner),
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


if __name__ == "__main__":
    unittest.main()
