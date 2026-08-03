import datetime
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
            mock.patch("generate_posts.generate_public_content_feed", return_value=0),
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
        self._write_match(model_signal_schema=7)
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


class AnchoredWindowTests(unittest.TestCase):
    """Per-sport anchored refresh windows (see multi_fetch.ANCHOR_HOURS)."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.cwd = os.getcwd()
        os.chdir(self.temp.name)
        self.addCleanup(os.chdir, self.cwd)

    def _schedule(self, key, kickoffs):
        Path(f"data_{key}.json").write_text(json.dumps(
            {"matches": [{"kickoff": k} for k in kickoffs]}), encoding="utf-8")

    def _at(self, iso):
        return datetime.datetime.fromisoformat(iso)

    def _eastern(self):
        """Pin the zone so these assertions hold with or without a tz database.

        zoneinfo raises on a bare Windows install with no tzdata package, and
        _zone_for() deliberately degrades to UTC there (see its comment), so
        asserting real Eastern-time behaviour has to state the offset rather
        than depend on the host. CI runs on Linux, where the real zone loads.
        """
        return mock.patch.object(multi_fetch, "_zone_for",
                                 return_value=datetime.timezone(datetime.timedelta(hours=-4)))

    def test_pregame_anchor_fires_on_a_game_day(self):
        # NCAAF anchors at 10:00 ET; 14:17 UTC is 10:17 EDT, inside the grace
        # window, on a day with a scheduled kickoff.
        self._schedule("ncaaf", ["2026-09-05T16:00:00Z"])
        with self._eastern():
            self.assertEqual(
                multi_fetch._anchor_due("ncaaf", None, self._at("2026-09-05T14:17:00+00:00")),
                "2026-09-05:10:00")

    def test_anchor_is_not_served_twice(self):
        self._schedule("ncaaf", ["2026-09-05T16:00:00Z"])
        with self._eastern():
            self.assertIsNone(multi_fetch._anchor_due(
                "ncaaf", "2026-09-05:10:00", self._at("2026-09-05T14:17:00+00:00")))

    def test_no_anchor_without_a_game_that_day(self):
        # Same clock time, but the only kickoff is a week away: an off-day
        # sport must not spend quota on anchored refreshes.
        self._schedule("ncaaf", ["2026-09-12T16:00:00Z"])
        with self._eastern():
            self.assertIsNone(multi_fetch._anchor_due(
                "ncaaf", None, self._at("2026-09-05T14:17:00+00:00")))

    def test_no_anchor_outside_the_grace_window(self):
        self._schedule("ncaaf", ["2026-09-05T16:00:00Z"])
        # 12:30 ET is 2.5h past the 10:00 anchor and still short of the 15:00
        # one, so no window is claimable.
        with self._eastern():
            self.assertIsNone(multi_fetch._anchor_due(
                "ncaaf", None, self._at("2026-09-05T16:30:00+00:00")))

    def test_small_hours_anchor_closes_out_the_previous_game_day(self):
        # MLB's 02:00 ET anchor grades West Coast finals from the day before,
        # so it must match against that game day, not the calendar date it
        # fires on.
        self._schedule("mlb", ["2026-07-29T23:10:00Z"])
        with self._eastern():
            self.assertEqual(
                multi_fetch._anchor_due("mlb", None, self._at("2026-07-30T06:10:00+00:00")),
                "2026-07-29:02:00")

    def test_zone_lookup_never_raises_without_a_tz_database(self):
        with mock.patch.dict("sys.modules", {"zoneinfo": None}):
            self.assertEqual(multi_fetch._zone_for("mlb"), datetime.timezone.utc)

    def test_anchor_forces_a_sport_that_is_not_otherwise_due(self):
        self._schedule("ncaaf", ["2026-09-05T16:00:00Z"])
        state = Path("state.json")
        state.write_text(json.dumps({"ncaaf": 9e9}), encoding="utf-8")  # fetched "just now"
        runner = mock.Mock(return_value=True)
        with mock.patch.object(multi_fetch, "SPORTS", [("ncaaf", "--ncaaf")]), \
             mock.patch.object(multi_fetch, "FORCE_REFETCH_ONCE", set()), \
             mock.patch.object(multi_fetch, "_run_one", runner), \
             mock.patch.object(multi_fetch, "_anchor_due", return_value="2026-09-05:10:00"), \
             mock.patch("generate_posts.generate_public_content_feed", return_value=0), \
             mock.patch("generate_posts.regenerate_sitemap", return_value=0):
            multi_fetch.run_once(str(state))
        self.assertEqual(runner.call_count, 1)
        written = json.loads(state.read_text(encoding="utf-8"))
        self.assertEqual(written["_anchors"], {"ncaaf": "2026-09-05:10:00"})

    def test_failed_refresh_leaves_the_anchor_claimable(self):
        self._schedule("ncaaf", ["2026-09-05T16:00:00Z"])
        state = Path("state.json")
        runner = mock.Mock(return_value=False)
        with mock.patch.object(multi_fetch, "SPORTS", [("ncaaf", "--ncaaf")]), \
             mock.patch.object(multi_fetch, "ONCE_RETRY_DELAY", 0), \
             mock.patch.object(multi_fetch, "FORCE_REFETCH_ONCE", set()), \
             mock.patch.object(multi_fetch, "_run_one", runner), \
             mock.patch.object(multi_fetch, "_anchor_due", return_value="2026-09-05:10:00"), \
             mock.patch("generate_posts.generate_public_content_feed", return_value=0), \
             mock.patch("generate_posts.regenerate_sitemap", return_value=0):
            with self.assertRaises(RuntimeError):
                multi_fetch.run_once(str(state))
        self.assertNotIn("_anchors", json.loads(state.read_text(encoding="utf-8")))

    def test_legacy_state_file_without_anchors_still_loads(self):
        self._schedule("mlb", [])
        state = Path("state.json")
        state.write_text(json.dumps({"mlb": 1.0}), encoding="utf-8")
        runner = mock.Mock(return_value=True)
        with mock.patch.object(multi_fetch, "SPORTS", [("mlb", "--mlb")]), \
             mock.patch.object(multi_fetch, "FORCE_REFETCH_ONCE", set()), \
             mock.patch.object(multi_fetch, "_run_one", runner), \
             mock.patch("generate_posts.generate_public_content_feed", return_value=0), \
             mock.patch("generate_posts.regenerate_sitemap", return_value=0):
            multi_fetch.run_once(str(state))
        self.assertGreater(json.loads(state.read_text(encoding="utf-8"))["mlb"], 1.0)

    def test_every_scheduled_sport_has_anchor_hours(self):
        for key, _ in multi_fetch.SPORTS:
            self.assertIn(key, multi_fetch.ANCHOR_HOURS, f"{key} has no anchored windows")
            self.assertIn(key, multi_fetch.SPORT_ZONE, f"{key} has no schedule zone")
