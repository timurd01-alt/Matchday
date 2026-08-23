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

    def test_force_rebuild_ignores_recent_cadence_state(self):
        state, runner = self._run([True])
        state.write_text(json.dumps({"mlb": 9e9}), encoding="utf-8")
        with mock.patch.object(multi_fetch, "FORCE_REFETCH_ONCE", set()):
            multi_fetch.run_once(str(state), force=True)
        self.assertEqual(runner.call_count, 1)


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
        # Read the expected schema from the module rather than restating it --
        # every model change that alters emitted probabilities has to bump this
        # constant, and a literal here turns each of those into a test edit.
        self._write_match(
            model_signal_schema=multi_fetch.REQUIRED_MATCH_VALUES["model_signal_schema"],
            pregame_context={"schema_ver": 1})
        self.assertFalse(multi_fetch._missing_fields("ncaaf"))

    def test_missing_pregame_context_forces_one_refresh(self):
        self._write_match(
            model_signal_schema=multi_fetch.REQUIRED_MATCH_VALUES["model_signal_schema"])
        self.assertTrue(multi_fetch._missing_fields("ncaaf"))


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


class LockWindowRefreshTests(unittest.TestCase):
    """An unlocked fixture near kickoff forces a refetch (multi_fetch._lock_window_due).

    Timeline under test is the live one that lost EPL 560548 (Man City v
    Bournemouth) and 560549 (Brighton v Aston Villa): both kicked off
    2026-08-23T13:00Z, EPL was last fetched at 10:38Z, the next CI run fired
    at 11:33:16Z -- 55 min later, inside the 1h SOON_EVERY gate -- and was
    skipped as "not due yet", GitHub dropped the ~12:17Z run, and the 13:00:26Z
    run was already past kickoff. Neither fixture ever reached the ledger.
    """

    KICKOFF = "2026-08-23T13:00:00Z"

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.cwd = os.getcwd()
        os.chdir(self.temp.name)
        self.addCleanup(os.chdir, self.cwd)
        self._fixtures()

    def _fixtures(self, status="UPCOMING"):
        Path("data_epl.json").write_text(json.dumps({
            "competition": "EPL",
            "matches": [{"id": fixture_id, "status": status, "kickoff": self.KICKOFF,
                         "pregame_context": {"lock_window_hours": 2.0}}
                        for fixture_id in ("560548", "560549")],
        }), encoding="utf-8")

    def _picks(self, *fixture_ids):
        Path("picks_log_epl.json").write_text(json.dumps(
            {fid: {"fixture_id": fid, "competition": "EPL"} for fid in fixture_ids}),
            encoding="utf-8")

    def _at(self, iso):
        return datetime.datetime.fromisoformat(iso)

    def test_run_inside_the_lock_window_is_due_despite_the_hourly_gate(self):
        # 11:33:16Z is 1h27m before kickoff: inside EPL's 2h lock window, and
        # only 55 min after the 10:38Z fetch, so the interval gate alone
        # skipped it.
        self.assertTrue(multi_fetch._lock_window_due(
            "epl", self._at("2026-08-23T11:33:16+00:00")))

    def test_run_before_the_lock_window_stays_on_the_normal_cadence(self):
        # The 10:38Z fetch was 2h22m out -- outside the window, so nothing is
        # forced and the sport keeps paying only its usual hourly cost.
        self.assertFalse(multi_fetch._lock_window_due(
            "epl", self._at("2026-08-23T10:38:00+00:00")))

    def test_already_locked_fixtures_do_not_force_a_refetch(self):
        # Quota safety: once both fixtures have a committed pick, the same
        # in-window moment must stop forcing anything.
        self._picks("560548", "560549")
        self.assertFalse(multi_fetch._lock_window_due(
            "epl", self._at("2026-08-23T11:33:16+00:00")))

    def test_one_still_unlocked_fixture_is_enough(self):
        self._picks("560548")
        self.assertTrue(multi_fetch._lock_window_due(
            "epl", self._at("2026-08-23T11:33:16+00:00")))

    def test_past_kickoff_no_longer_forces_a_lock_refresh(self):
        # 13:00:26Z is past kickoff; nothing can be locked any more, and score
        # urgency is _interval_for's job (PAST_DUE_SCORE_GRACE_HOURS).
        self.assertFalse(multi_fetch._lock_window_due(
            "epl", self._at("2026-08-23T13:00:26+00:00")))

    def test_non_upcoming_fixtures_are_ignored(self):
        self._fixtures(status="LIVE")
        self.assertFalse(multi_fetch._lock_window_due(
            "epl", self._at("2026-08-23T11:33:16+00:00")))

    def test_missing_data_file_is_not_due(self):
        Path("data_epl.json").unlink()
        self.assertFalse(multi_fetch._lock_window_due(
            "epl", self._at("2026-08-23T11:33:16+00:00")))

    def test_lock_window_forces_a_sport_the_interval_gate_would_skip(self):
        state = Path("state.json")
        state.write_text(json.dumps({"epl": 9e9}), encoding="utf-8")  # fetched "just now"
        runner = mock.Mock(return_value=True)
        with mock.patch.object(multi_fetch, "SPORTS", [("epl", "--epl")]),              mock.patch.object(multi_fetch, "FORCE_REFETCH_ONCE", set()),              mock.patch.object(multi_fetch, "_missing_fields", return_value=False),              mock.patch.object(multi_fetch, "_run_one", runner),              mock.patch.object(multi_fetch, "_anchor_due", return_value=None),              mock.patch.object(multi_fetch, "_lock_window_due", return_value=True),              mock.patch("generate_posts.generate_public_content_feed", return_value=0),              mock.patch("generate_posts.regenerate_sitemap", return_value=0):
            multi_fetch.run_once(str(state))
        self.assertEqual(runner.call_count, 1)

    def test_no_lock_window_leaves_the_interval_gate_in_charge(self):
        state = Path("state.json")
        state.write_text(json.dumps({"epl": 9e9}), encoding="utf-8")
        runner = mock.Mock(return_value=True)
        with mock.patch.object(multi_fetch, "SPORTS", [("epl", "--epl")]),              mock.patch.object(multi_fetch, "FORCE_REFETCH_ONCE", set()),              mock.patch.object(multi_fetch, "_missing_fields", return_value=False),              mock.patch.object(multi_fetch, "_run_one", runner),              mock.patch.object(multi_fetch, "_anchor_due", return_value=None),              mock.patch.object(multi_fetch, "_lock_window_due", return_value=False),              mock.patch("generate_posts.generate_public_content_feed", return_value=0),              mock.patch("generate_posts.regenerate_sitemap", return_value=0):
            multi_fetch.run_once(str(state))
        self.assertEqual(runner.call_count, 0)

    def test_every_scheduled_sport_has_a_lock_window(self):
        from pregame_context import LOCK_WINDOWS_HOURS
        for key, _ in multi_fetch.SPORTS:
            self.assertIn(key.upper(), LOCK_WINDOWS_HOURS,
                          f"{key} has no lock window to schedule against")


if __name__ == "__main__":
    unittest.main()
