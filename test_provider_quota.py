"""provider_quota.py: refuse a call before a provider's budget is spent to
zero, instead of firing blind and discovering it via a 429.

Every header format tested here was read off a real, live response on
2026-07-31 (see provider_quota.py's module docstring) -- CFBD, CBBD and The
Odds API were all confirmed sitting at zero remaining for the current period
at that time, having quietly degraded predictions/market data across the live
site with nothing recording it happened.
"""
import datetime
import json
import os
import tempfile
import unittest

import provider_quota as pq


class QuotaModuleTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        temp.close()
        os.unlink(temp.name)  # start from "no state file yet", the real cold-start case
        self.path = temp.name
        self.addCleanup(lambda: os.path.exists(self.path) and os.unlink(self.path))

    def _freeze(self, when):
        """Pin pq._now() so a pacing scenario's "how far into the period are
        we" is deterministic regardless of which real calendar day the test
        suite happens to run on -- pacing math is inherently date-relative,
        so leaving it to the real clock would make these tests flaky exactly
        once a month (confirmed while writing them: this suite genuinely
        started failing for real on 2026-08-01, a few minutes into a new
        billing period, with no state or code at fault but the wall clock)."""
        orig = pq._now
        pq._now = lambda: when
        self.addCleanup(setattr, pq, "_now", orig)

    # ---- CFBD/CBBD: calendar-month window, no limit header, body fallback --
    def test_cfbd_remaining_header_is_recorded_and_enforced(self):
        self._freeze(datetime.datetime(2026, 8, 28, 12, 0, tzinfo=datetime.timezone.utc))
        pq.record_response("cfbd", {"X-CallLimit-Remaining": "990"}, state_path=self.path)
        pq.check("cfbd", state_path=self.path)
        pq.record_response("cfbd", {"X-CallLimit-Remaining": "20"}, state_path=self.path)
        with self.assertRaises(pq.QuotaExceededError):
            pq.check("cfbd", state_path=self.path)

    def test_cfbd_header_lookup_is_case_insensitive(self):
        """http.client/urllib preserve whatever case each server actually sent."""
        pq.record_response("cfbd", {"x-calllimit-remaining": "0"}, state_path=self.path)
        with self.assertRaises(pq.QuotaExceededError):
            pq.check("cfbd", state_path=self.path)

    def test_cfbd_quota_body_message_sets_remaining_to_zero(self):
        """Confirmed live: a 429 body reads exactly 'Monthly call quota
        exceeded.' with no numeric header at all on some responses -- the
        message itself is the only signal available then."""
        pq.record_response("cfbd", {}, body='{"message":"Monthly call quota exceeded."}',
                           state_path=self.path)
        with self.assertRaises(pq.QuotaExceededError):
            pq.check("cfbd", state_path=self.path)

    def test_cfbd_calendar_month_reset_clears_a_stale_zero(self):
        now = datetime.datetime(2026, 7, 1, 12, tzinfo=datetime.timezone.utc)
        self._freeze(now)
        past = datetime.datetime(2026, 6, 15, tzinfo=datetime.timezone.utc)
        pq.record_response("cfbd", {"X-CallLimit-Remaining": "0"}, state_path=self.path)
        with open(self.path, encoding="utf-8") as handle:
            state = json.load(handle)
        state["cfbd"]["period_start"] = past.replace(day=1).isoformat()
        state["cfbd"]["observed_at"] = past.isoformat()
        with open(self.path, "w", encoding="utf-8") as handle:
            json.dump(state, handle)
        pq.check("cfbd", state_path=self.path)  # one claimed reset probe
        with self.assertRaises(pq.QuotaExceededError):
            pq.check("cfbd", state_path=self.path)  # cannot fan out before a response records reset

    # ---- header-less responses still spend budget -------------------------
    # CFBD does not return X-CallLimit-Remaining on every response (see
    # test_cfbd_quota_body_message_sets_remaining_to_zero, taken off a real
    # 429). Those calls are real spend, and while the ledger ignored them
    # `remaining` stood still at whatever the last header said -- so check()
    # kept approving calls and the reserve could be stepped over rather than
    # stopped at. Observed live: cfbd at remaining=0 against reserve=25.
    def test_header_less_response_debits_the_local_count(self):
        self._freeze(datetime.datetime(2026, 8, 28, 12, tzinfo=datetime.timezone.utc))
        pq.record_response("cfbd", {"X-CallLimit-Remaining": "100"}, state_path=self.path)
        for _ in range(3):
            pq.record_response("cfbd", {}, state_path=self.path)
        with open(self.path, encoding="utf-8") as handle:
            self.assertEqual(json.load(handle)["cfbd"]["remaining"], 97)

    def test_header_less_responses_cannot_step_over_the_reserve(self):
        """The regression this exists for: without a local debit the ledger
        reads 30 forever and check() never refuses, however many calls fire."""
        self._freeze(datetime.datetime(2026, 8, 28, 12, tzinfo=datetime.timezone.utc))
        pq.record_response("cfbd", {"X-CallLimit-Remaining": "30"}, state_path=self.path)
        for _ in range(5):
            pq.check("cfbd", state_path=self.path)
            pq.record_response("cfbd", {}, state_path=self.path)
        with self.assertRaises(pq.QuotaExceededError):
            pq.check("cfbd", state_path=self.path)

    def test_a_real_header_overrides_the_local_estimate(self):
        """The debit is a stand-in between observations, never a competitor
        to ground truth: the provider's own number wins whenever it arrives."""
        self._freeze(datetime.datetime(2026, 8, 28, 12, tzinfo=datetime.timezone.utc))
        pq.record_response("cfbd", {"X-CallLimit-Remaining": "100"}, state_path=self.path)
        pq.record_response("cfbd", {}, state_path=self.path)
        pq.record_response("cfbd", {"X-CallLimit-Remaining": "500"}, state_path=self.path)
        with open(self.path, encoding="utf-8") as handle:
            self.assertEqual(json.load(handle)["cfbd"]["remaining"], 500)

    def test_local_debit_never_goes_negative(self):
        self._freeze(datetime.datetime(2026, 8, 28, 12, tzinfo=datetime.timezone.utc))
        pq.record_response("cfbd", {"X-CallLimit-Remaining": "1"}, state_path=self.path)
        for _ in range(4):
            pq.record_response("cfbd", {}, state_path=self.path)
        with open(self.path, encoding="utf-8") as handle:
            self.assertEqual(json.load(handle)["cfbd"]["remaining"], 0)

    def test_local_debit_does_not_fire_on_an_unobserved_provider(self):
        """Nothing to debit before a real header has ever been seen -- the
        cold-start path must stay fail-closed rather than inventing a count."""
        pq.record_response("cfbd", {}, state_path=self.path)
        with open(self.path, encoding="utf-8") as handle:
            self.assertIsNone(json.load(handle)["cfbd"].get("remaining"))

    def test_an_entry_without_a_reading_still_fails_closed(self):
        """A header-less response writes observed_at/period_start, so the
        ledger entry exists while carrying no number to enforce against. That
        was enough to pass a truthiness-based fail-closed guard and leave the
        provider permanently unblocked."""
        pq.record_response("cfbd", {}, state_path=self.path)
        with self.assertRaises(pq.QuotaExceededError):
            pq.check("cfbd", state_path=self.path)

    def test_local_debit_is_skipped_on_the_period_crossing_run(self):
        """`remaining` is last month's reading on the run that crosses into a
        new period; debiting it would carry a stale zero forward and keep the
        provider dark after its budget actually reset."""
        self._freeze(datetime.datetime(2026, 8, 1, 0, 30, tzinfo=datetime.timezone.utc))
        pq.record_response("cfbd", {"X-CallLimit-Remaining": "40"}, state_path=self.path)
        with open(self.path, encoding="utf-8") as handle:
            state = json.load(handle)
        state["cfbd"]["period_start"] = "2026-07-01T00:00:00+00:00"
        with open(self.path, "w", encoding="utf-8") as handle:
            json.dump(state, handle)
        pq.record_response("cfbd", {}, state_path=self.path)
        with open(self.path, encoding="utf-8") as handle:
            self.assertEqual(json.load(handle)["cfbd"]["remaining"], 40)

    def test_local_debit_does_not_apply_to_rolling_windows(self):
        """A rolling per-minute bucket refills on its own clock; a missing
        header there means "no fresh reading", not "one more call spent"."""
        pq.record_response("football_data",
                           {"x-requests-available-minute": "8",
                            "X-RequestCounter-Reset": "45"}, state_path=self.path)
        pq.record_response("football_data", {}, state_path=self.path)
        with open(self.path, encoding="utf-8") as handle:
            self.assertEqual(json.load(handle)["football_data"]["remaining"], 8)

    def test_never_observed_monthly_provider_fails_closed(self):
        with self.assertRaises(pq.QuotaExceededError):
            pq.check("cfbd", state_path=self.path)

    def test_explicit_bootstrap_allows_a_cold_monthly_provider_probe(self):
        old = os.environ.get(pq.BOOTSTRAP_ENV)
        os.environ[pq.BOOTSTRAP_ENV] = "1"
        self.addCleanup(lambda: (os.environ.pop(pq.BOOTSTRAP_ENV, None) if old is None
                                 else os.environ.__setitem__(pq.BOOTSTRAP_ENV, old)))
        pq.check("cfbd", state_path=self.path)

    def test_unknown_provider_is_a_silent_no_op(self):
        pq.record_response("not_a_real_provider", {"whatever": "1"}, state_path=self.path)
        pq.check("not_a_real_provider", state_path=self.path)

    # ---- football-data.org: rolling per-minute window, seconds-until-reset -
    def test_football_data_rolling_seconds_window(self):
        pq.record_response("football_data",
                           {"x-requests-available-minute": "0", "X-RequestCounter-Reset": "45"},
                           state_path=self.path)
        with self.assertRaises(pq.QuotaExceededError):
            pq.check("football_data", state_path=self.path)

    def test_football_data_window_expiry_clears_the_block(self):
        pq.record_response("football_data",
                           {"x-requests-available-minute": "0", "X-RequestCounter-Reset": "1"},
                           state_path=self.path)
        with open(self.path, encoding="utf-8") as handle:
            state = json.load(handle)
        # Backdate the reset moment into the past, simulating the 1-second
        # window having actually elapsed since the observation.
        state["football_data"]["reset_at"] = (
            datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=1)
        ).isoformat()
        with open(self.path, "w", encoding="utf-8") as handle:
            json.dump(state, handle)
        pq.check("football_data", state_path=self.path)

    # ---- BallDontLie: rolling window, unix-epoch reset -----------------
    def test_balldontlie_unix_reset_header(self):
        future = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=1)
        pq.record_response("balldontlie",
                           {"x-ratelimit-limit": "5", "x-ratelimit-remaining": "1",
                            "x-ratelimit-reset": str(int(future.timestamp()))},
                           state_path=self.path)
        with self.assertRaises(pq.QuotaExceededError):
            pq.check("balldontlie", state_path=self.path)  # 1 <= reserve(1)

    def test_balldontlie_healthy_remaining_is_not_blocked(self):
        pq.record_response("balldontlie", {"x-ratelimit-limit": "5", "x-ratelimit-remaining": "4",
                                           "x-ratelimit-reset": "9999999999"},
                           state_path=self.path)
        pq.check("balldontlie", state_path=self.path)

    def test_bigballs_uses_observed_unix_reset_bucket(self):
        future = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=1)
        pq.record_response("bigballs",
                           {"x-ratelimit-limit": "100", "x-ratelimit-remaining": "2",
                            "x-ratelimit-reset": str(int(future.timestamp()))},
                           state_path=self.path)
        with self.assertRaises(pq.QuotaExceededError):
            pq.check("bigballs", state_path=self.path)

    # ---- API-Football: two independent buckets from one response ------
    def test_api_football_tracks_minute_and_day_independently(self):
        pq.record_response("api_football",
                           {"x-ratelimit-limit": "10", "x-ratelimit-remaining": "9",
                            "x-ratelimit-requests-limit": "100", "x-ratelimit-requests-remaining": "92"},
                           state_path=self.path)
        pq.check("api_football", state_path=self.path)  # both well above reserve

    def test_api_football_day_bucket_alone_can_block_the_call(self):
        """Confirmed live 2026-07-31: minute bucket healthy (9/10) while the
        day bucket can independently run out -- either one exhausting must
        refuse the call, not just the minute bucket."""
        pq.record_response("api_football",
                           {"x-ratelimit-limit": "10", "x-ratelimit-remaining": "9",
                            "x-ratelimit-requests-limit": "100", "x-ratelimit-requests-remaining": "3"},
                           state_path=self.path)
        with self.assertRaises(pq.QuotaExceededError):
            pq.check("api_football", state_path=self.path)

    def test_api_football_minute_bucket_alone_can_block_the_call(self):
        pq.record_response("api_football",
                           {"x-ratelimit-limit": "10", "x-ratelimit-remaining": "1",
                            "x-ratelimit-requests-limit": "100", "x-ratelimit-requests-remaining": "80"},
                           state_path=self.path)
        with self.assertRaises(pq.QuotaExceededError):
            pq.check("api_football", state_path=self.path)

    # ---- The Odds API: used/remaining pair, no explicit limit header ---
    def test_odds_api_confirmed_live_exhausted_state_is_enforced(self):
        """The exact live response captured 2026-07-31: 0 remaining, 500 used."""
        pq.record_response("odds_api", {"x-requests-remaining": "0", "x-requests-used": "500"},
                           state_path=self.path)
        with self.assertRaises(pq.QuotaExceededError):
            pq.check("odds_api", state_path=self.path)
        with open(self.path, encoding="utf-8") as handle:
            state = json.load(handle)
        self.assertEqual(state["odds_api"]["limit"], 500)  # derived: remaining + used

    def test_odds_api_healthy_remaining_is_not_blocked(self):
        """450/500 used only counts as healthy late in the billing period --
        pinned to day 28 of a 31-day month so this doesn't depend on when in
        the real month the suite happens to run."""
        self._freeze(datetime.datetime(2026, 8, 28, 12, 0, tzinfo=datetime.timezone.utc))
        pq.record_response("odds_api", {"x-requests-remaining": "50", "x-requests-used": "450"},
                           state_path=self.path)
        pq.check("odds_api", state_path=self.path)

    # ---- pacing: catch a fast burn well before the reserve floor would ---
    def test_odds_api_burning_ahead_of_monthly_pace_is_refused(self):
        """Confirmed-live failure mode: The Odds API hit zero before its
        billing period ended. 300 used out of 500 barely into the month is
        nowhere near the reserve(5) floor, but it's wildly ahead of an even
        30-day drawdown -- pacing must catch this, not just the reserve."""
        self._freeze(datetime.datetime(2026, 3, 1, 2, 0, tzinfo=datetime.timezone.utc))
        pq.record_response("odds_api", {"x-requests-remaining": "200", "x-requests-used": "300"},
                           state_path=self.path)
        with self.assertRaises(pq.QuotaExceededError):
            pq.check("odds_api", state_path=self.path)

    def test_odds_api_on_pace_usage_is_not_blocked_by_pacing(self):
        """Same shape as above, but usage tracks the calendar instead of
        outrunning it -- must not be refused just for having used some budget."""
        self._freeze(datetime.datetime(2026, 3, 5, 12, 0, tzinfo=datetime.timezone.utc))
        pq.record_response("odds_api", {"x-requests-remaining": "480", "x-requests-used": "20"},
                           state_path=self.path)
        pq.check("odds_api", state_path=self.path)

    def test_cfbd_known_free_tier_limit_enables_monthly_pacing(self):
        self._freeze(datetime.datetime(2026, 3, 5, 12, 0, tzinfo=datetime.timezone.utc))
        pq.record_response("cfbd", {"X-CallLimit-Remaining": "700"}, state_path=self.path)
        with self.assertRaises(pq.QuotaExceededError):
            pq.check("cfbd", state_path=self.path)
        with open(self.path, encoding="utf-8") as handle:
            self.assertEqual(json.load(handle)["cfbd"]["limit"], 1000)

    def test_cfbd_seasonal_burst_allows_live_582_balance_on_august_10(self):
        self._freeze(datetime.datetime(2026, 8, 11, 2, 40, tzinfo=datetime.timezone.utc))
        pq.record_response("cfbd", {"X-CallLimit-Remaining": "582"}, state_path=self.path)
        pq.check("cfbd", state_path=self.path)

    def test_six_hour_age_does_not_leak_the_reserve(self):
        observed = datetime.datetime(2026, 8, 10, 0, 0, tzinfo=datetime.timezone.utc)
        self._freeze(observed)
        pq.record_response("cfbd", {"X-CallLimit-Remaining": "25"}, state_path=self.path)
        self._freeze(observed + datetime.timedelta(days=2))
        with self.assertRaises(pq.QuotaExceededError):
            pq.check("cfbd", state_path=self.path)

    def test_automatic_reset_reprobes_have_a_hard_call_cap(self):
        now = datetime.datetime(2026, 9, 1, 18, 0, tzinfo=datetime.timezone.utc)
        self._freeze(now)
        pq.record_response("cfbd", {"X-CallLimit-Remaining": "0"}, state_path=self.path)
        with open(self.path, encoding="utf-8") as handle:
            state = json.load(handle)
        entry = state["cfbd"]
        entry["period_start"] = datetime.datetime(2026, 8, 1, tzinfo=datetime.timezone.utc).isoformat()
        entry["reset_pending"] = True
        entry["reset_probe_count"] = pq.RESET_PROBE_MAX_CALLS
        entry["reset_probe_at"] = (now - datetime.timedelta(hours=7)).isoformat()
        with open(self.path, "w", encoding="utf-8") as handle:
            json.dump(state, handle)
        with self.assertRaises(pq.QuotaExceededError):
            pq.check("cfbd", state_path=self.path)

    # ---- persistence: this only matters because CI is one-shot per-run -
    def test_state_persists_across_separate_load_cycles(self):
        pq.record_response("cfbd", {"X-CallLimit-Remaining": "10"}, state_path=self.path)
        # Simulate a brand-new process: nothing in memory, only the file on disk.
        with self.assertRaises(pq.QuotaExceededError):
            pq.check("cfbd", state_path=self.path)

    def test_status_reports_every_tracked_provider(self):
        pq.record_response("cfbd", {"X-CallLimit-Remaining": "10"}, state_path=self.path)
        pq.record_response("balldontlie", {"x-ratelimit-limit": "5", "x-ratelimit-remaining": "3",
                                           "x-ratelimit-reset": "9999999999"}, state_path=self.path)
        lines = pq.status(self.path)
        self.assertEqual(len(lines), 2)
        self.assertTrue(any("cfbd" in line for line in lines))


class ProviderAdaptersWiringTests(unittest.TestCase):
    """The pre-flight refusal must surface as ProviderError -- every existing
    fallback/degraded-handling path in fetch_data.py already catches that
    specific type, not a new quota-only exception it's never heard of."""

    def setUp(self):
        temp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        temp.close()
        os.unlink(temp.name)
        self.path = temp.name
        self.addCleanup(lambda: os.path.exists(self.path) and os.unlink(self.path))
        self._orig_state_file = pq.STATE_FILE
        pq.STATE_FILE = self.path
        self.addCleanup(setattr, pq, "STATE_FILE", self._orig_state_file)

    def test_cfbd_stale_zero_reconciles_through_free_info_endpoint(self):
        import provider_adapters as pa
        pq.record_response("cfbd", {"X-CallLimit-Remaining": "0"})
        called = []

        class Response:
            def __init__(self, headers, body):
                self.headers, self.body = headers, body
            def __enter__(self):
                return self
            def __exit__(self, *_):
                return False
            def read(self):
                return self.body

        def open_response(request, timeout=25):
            called.append(request.full_url)
            if request.full_url == pa.CFBD_FREE_QUOTA_URL:
                return Response({"X-CallLimit-Remaining": "582"}, b'{"remainingCalls":582}')
            return Response({"X-CallLimit-Remaining": "581"}, b"[]")

        real_open = pa.urllib.request.urlopen
        pa.urllib.request.urlopen = open_response
        self.addCleanup(setattr, pa.urllib.request, "urlopen", real_open)
        rows = pa._get_json("https://api.collegefootballdata.com/games",
                            headers={"Authorization": "Bearer test"}, provider="cfbd")
        self.assertEqual(rows, [])
        self.assertEqual(called, [pa.CFBD_FREE_QUOTA_URL,
                                  "https://api.collegefootballdata.com/games"])

    def test_cfbd_info_confirming_zero_still_blocks_paid_request(self):
        import provider_adapters as pa
        pq.record_response("cfbd", {"X-CallLimit-Remaining": "0"})
        called = []

        class Response:
            headers = {"X-CallLimit-Remaining": "0"}
            def __enter__(self):
                return self
            def __exit__(self, *_):
                return False
            def read(self):
                return b'{"remainingCalls":0}'

        real_open = pa.urllib.request.urlopen
        pa.urllib.request.urlopen = lambda request, timeout=25: called.append(request.full_url) or Response()
        self.addCleanup(setattr, pa.urllib.request, "urlopen", real_open)
        with self.assertRaises(pa.ProviderError):
            pa._get_json("https://api.collegefootballdata.com/games",
                         headers={"Authorization": "Bearer test"}, provider="cfbd")
        self.assertEqual(called, [pa.CFBD_FREE_QUOTA_URL])

    def test_get_json_without_provider_is_completely_untracked(self):
        """Existing callers/tests that never pass provider= keep working
        identically -- no behavior change for anything that doesn't opt in."""
        import provider_adapters as pa
        with self.assertRaises(pa.ProviderError):
            pa._get_json("http://127.0.0.1:1/definitely-not-listening")


class FetchDataWiringTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        temp.close()
        os.unlink(temp.name)
        self.path = temp.name
        self.addCleanup(lambda: os.path.exists(self.path) and os.unlink(self.path))
        self._orig_state_file = pq.STATE_FILE
        pq.STATE_FILE = self.path
        self.addCleanup(setattr, pq, "STATE_FILE", self._orig_state_file)

    def test_fetch_data_reconciles_stale_odds_ledger_through_free_endpoint(self):
        import fetch_data as fd
        pq.record_response("odds_api", {"x-requests-remaining": "0", "x-requests-used": "500"})
        called = []

        class Response:
            def __init__(self, headers):
                self.headers = headers
            def __enter__(self):
                return self
            def __exit__(self, *_):
                return False
            def read(self):
                return b"[]"

        def open_response(request, timeout=25):
            called.append(request.full_url)
            if len(called) == 1:
                return Response({"x-requests-remaining": "335", "x-requests-used": "165",
                                 "x-requests-last": "0"})
            return Response({"x-requests-remaining": "334", "x-requests-used": "166",
                             "x-requests-last": "1"})

        real_open = fd.urllib.request.urlopen
        fd.urllib.request.urlopen = open_response
        self.addCleanup(setattr, fd.urllib.request, "urlopen", real_open)
        self.assertEqual(fd._get("https://api.the-odds-api.com/v4/sports/baseball_mlb/odds",
                                 provider="odds_api"), [])
        self.assertTrue(called[0].startswith(fd.ODDS_FREE_QUOTA_URL))
        self.assertEqual(len(called), 2)

    def test_exhausted_odds_account_is_not_reprobed_during_cooldown(self):
        pq.record_response("odds_api", {"x-requests-remaining": "0", "x-requests-used": "500"})
        self.assertTrue(pq.claim_free_probe("odds_api"))
        self.assertFalse(pq.claim_free_probe("odds_api"))

    def test_free_probe_confirming_zero_still_blocks_paid_request(self):
        import fetch_data as fd
        pq.record_response("odds_api", {"x-requests-remaining": "0", "x-requests-used": "500"})
        called = []

        class Response:
            headers = {"x-requests-remaining": "0", "x-requests-used": "500",
                       "x-requests-last": "0"}
            def __enter__(self):
                return self
            def __exit__(self, *_):
                return False
            def read(self):
                return b"[]"

        real_open = fd.urllib.request.urlopen
        fd.urllib.request.urlopen = lambda request, timeout=25: called.append(request.full_url) or Response()
        self.addCleanup(setattr, fd.urllib.request, "urlopen", real_open)
        with self.assertRaises(RuntimeError):
            fd._get("https://api.the-odds-api.com/v4/sports/baseball_mlb/odds",
                    provider="odds_api")
        self.assertEqual(len(called), 1)
        self.assertTrue(called[0].startswith(fd.ODDS_FREE_QUOTA_URL))


if __name__ == "__main__":
    unittest.main()


class SpendAccountingTests(unittest.TestCase):
    """What Matchday spent, and on what.

    The ledger recorded only what a provider said was left. It never recorded
    what was spent or on which endpoint, so every cache TTL in the codebase
    was a guess nobody could check, and cfbd's exhausted month could not be
    traced to the call that drained it.
    """

    def setUp(self):
        temp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        temp.close()
        os.unlink(temp.name)
        self.path = temp.name
        self.addCleanup(lambda: os.path.exists(self.path) and os.unlink(self.path))
        orig = pq._now
        pq._now = lambda: datetime.datetime(2026, 8, 12, 9, tzinfo=datetime.timezone.utc)
        self.addCleanup(setattr, pq, "_now", orig)

    def _entry(self):
        with open(self.path, encoding="utf-8") as handle:
            return json.load(handle)["cfbd"]

    def test_endpoint_key_drops_the_query_string(self):
        self.assertEqual(
            pq.endpoint_key("https://api.collegefootballdata.com/games?year=2026&x=1"),
            "/games")

    def test_endpoint_key_collapses_identifiers(self):
        self.assertEqual(pq.endpoint_key("https://x.dev/teams/42"), "/teams/:id")

    def test_endpoint_key_survives_junk(self):
        for value in ("", None, "not a url"):
            self.assertTrue(pq.endpoint_key(value).startswith("/"))

    def test_spend_is_counted_per_endpoint(self):
        for _ in range(3):
            pq.record_response("cfbd", {"X-CallLimit-Remaining": "900"},
                               state_path=self.path, url="https://x.dev/games?year=2026")
        pq.record_response("cfbd", {"X-CallLimit-Remaining": "899"},
                           state_path=self.path, url="https://x.dev/records")
        entry = self._entry()
        self.assertEqual(entry["spent"], 4)
        self.assertEqual(entry["by_endpoint"], {"/games": 3, "/records": 1})

    def test_spend_without_a_url_still_counts_the_call(self):
        pq.record_response("cfbd", {"X-CallLimit-Remaining": "900"}, state_path=self.path)
        self.assertEqual(self._entry()["spent"], 1)

    def test_endpoint_cardinality_is_capped(self):
        for index in range(pq.USAGE_ENDPOINT_CAP + 8):
            pq.record_response("cfbd", {"X-CallLimit-Remaining": "900"},
                               state_path=self.path, url=f"https://x.dev/e{index}")
        usage = self._entry()["by_endpoint"]
        self.assertLessEqual(len(usage), pq.USAGE_ENDPOINT_CAP + 1)
        self.assertIn("(other)", usage)

    def test_spend_resets_when_the_period_rolls_over(self):
        pq.record_response("cfbd", {"X-CallLimit-Remaining": "900"},
                           state_path=self.path, url="https://x.dev/games")
        pq._now = lambda: datetime.datetime(2026, 9, 2, 9, tzinfo=datetime.timezone.utc)
        pq.record_response("cfbd", {"X-CallLimit-Remaining": "999"},
                           state_path=self.path, url="https://x.dev/games")
        self.assertEqual(self._entry()["spent"], 1)

    def test_daily_spend_resets_on_a_new_day(self):
        pq.record_response("cfbd", {"X-CallLimit-Remaining": "900"}, state_path=self.path)
        pq._now = lambda: datetime.datetime(2026, 8, 13, 9, tzinfo=datetime.timezone.utc)
        pq.record_response("cfbd", {"X-CallLimit-Remaining": "899"}, state_path=self.path)
        entry = self._entry()
        self.assertEqual(entry["spent_today"], 1)
        self.assertEqual(entry["spent"], 2)

    def test_usage_report_summarises_the_period(self):
        for _ in range(5):
            pq.record_response("cfbd", {"X-CallLimit-Remaining": "900"},
                               state_path=self.path, url="https://x.dev/games")
        report = pq.usage_report(state_path=self.path)
        self.assertEqual(report["cfbd"]["spent"], 5)
        self.assertEqual(report["cfbd"]["top_endpoints"][0], ("/games", 5))


class BudgetRationingTests(unittest.TestCase):
    """The budget rations a month; the reserve only guards its end.

    cfbd spent its entire 1,000-call month by 2026-08-10 with the reserve
    working exactly as designed, then went dark for three weeks.
    """

    BUDGET = {
        "schema_version": 1,
        "defaults": {"tier": 3, "tier_day_share": {"1": 4.0, "2": 1.0, "3": 0.6, "4": 0.35}},
        "providers": {"cfbd": {"period": "calendar_month", "ceiling": 1000,
                               "daily_floor": 8, "tier1_may_exceed_daily": True}},
    }

    def setUp(self):
        self.now = datetime.datetime(2026, 8, 15, 12, tzinfo=datetime.timezone.utc)
        self.spec = pq.PROVIDER_SPECS["cfbd"]

    def _state(self, spent_today, spent=100):
        return {"cfbd": {"remaining": 500, "limit": 1000, "spent": spent,
                         "spent_today": spent_today,
                         "spend_day": pq._period_start("calendar_day", self.now).isoformat()}}

    def _decide(self, tier, spent_today):
        return pq.budget_decision("cfbd", tier, self._state(spent_today),
                                  self.spec, self.now, self.BUDGET)

    def test_a_low_tier_call_is_refused_once_its_share_is_spent(self):
        self.assertIsNotNone(self._decide(4, spent_today=400))

    def test_a_low_tier_call_is_allowed_while_budget_remains(self):
        self.assertIsNone(self._decide(4, spent_today=0))

    def test_a_lock_window_call_outranks_the_daily_allowance(self):
        """Tier 1 freezes a pick permanently; rationing it to protect a
        talent refresh would be the wrong trade every time."""
        self.assertIsNone(self._decide(1, spent_today=100_000))

    def test_tier_ordering_is_strict(self):
        """On 2026-08-15 with 900 of 1000 left and 17 days to go the allowance
        is ~53/day, so the tier thresholds are ~212 / 53 / 32 / 19. A day that
        has spent 25 has used up tier 4's share and nothing else's."""
        refused = [tier for tier in (1, 2, 3, 4)
                   if self._decide(tier, spent_today=25) is not None]
        self.assertEqual(refused, [4])

    def test_pressure_closes_tiers_from_the_bottom_up(self):
        self.assertEqual(
            [tier for tier in (1, 2, 3, 4) if self._decide(tier, spent_today=35) is not None],
            [3, 4])
        self.assertEqual(
            [tier for tier in (1, 2, 3, 4) if self._decide(tier, spent_today=60) is not None],
            [2, 3, 4])

    def test_no_budget_policy_means_no_rationing(self):
        self.assertIsNone(pq.budget_decision("cfbd", 4, self._state(9999),
                                             self.spec, self.now, {}))

    def test_a_provider_without_a_ceiling_is_not_rationed(self):
        budget = {"schema_version": 1, "defaults": self.BUDGET["defaults"],
                  "providers": {"cfbd": {"ceiling": None, "daily_floor": 8}}}
        state = {"cfbd": {"spent": 10, "spent_today": 9999}}
        self.assertIsNone(pq.budget_decision("cfbd", 4, state, self.spec,
                                             self.now, budget))

    def test_yesterdays_counter_does_not_ration_today(self):
        state = {"cfbd": {"remaining": 500, "limit": 1000, "spent": 100,
                          "spent_today": 9999, "spend_day": "2026-08-14T00:00:00+00:00"}}
        self.assertIsNone(pq.budget_decision("cfbd", 4, state, self.spec,
                                             self.now, self.BUDGET))

    def test_without_accounting_there_is_nothing_to_ration(self):
        self.assertIsNone(pq.budget_decision("cfbd", 4, {"cfbd": {"remaining": 500}},
                                             self.spec, self.now, self.BUDGET))

    def test_the_checked_in_policy_parses_and_covers_metered_providers(self):
        budget = pq.load_budget("quota_budget.json")
        self.assertEqual(budget.get("schema_version"), 1)
        for provider in ("cfbd", "cbbd", "odds_api"):
            self.assertIn(provider, budget["providers"])

    def test_a_missing_policy_file_is_not_an_error(self):
        self.assertEqual(pq.load_budget("no_such_budget_file.json"), {})
