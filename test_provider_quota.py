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
        pq.record_response("cfbd", {"X-CallLimit-Remaining": "30"}, state_path=self.path)
        pq.check("cfbd", state_path=self.path)  # 30 > reserve(25): must not raise
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
        past = datetime.datetime(2026, 6, 15, tzinfo=datetime.timezone.utc)
        pq.record_response("cfbd", {"X-CallLimit-Remaining": "0"}, state_path=self.path)
        with open(self.path, encoding="utf-8") as handle:
            state = json.load(handle)
        state["cfbd"]["period_start"] = past.replace(day=1).isoformat()
        state["cfbd"]["observed_at"] = past.isoformat()
        with open(self.path, "w", encoding="utf-8") as handle:
            json.dump(state, handle)
        pq.check("cfbd", state_path=self.path)  # now July: June's zero no longer applies

    def test_never_observed_provider_is_not_enforced(self):
        pq.check("cfbd", state_path=self.path)  # no prior record_response call at all

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

    def test_pacing_never_applies_without_a_derivable_limit(self):
        """CFBD/CBBD never carry a `limit` (no total is ever published), so
        pacing must stay a silent no-op for them regardless of how much of
        the reserve-free range remains -- only the reserve floor applies."""
        pq.record_response("cfbd", {"X-CallLimit-Remaining": "26"}, state_path=self.path)
        pq.check("cfbd", state_path=self.path)  # 26 > reserve(25); no limit to pace against

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

    def test_get_json_refuses_before_the_request_when_exhausted(self):
        import provider_adapters as pa
        pq.record_response("cfbd", {"X-CallLimit-Remaining": "0"})
        called = []
        real_request = pa.urllib.request.Request
        pa.urllib.request.Request = lambda *a, **k: called.append(1) or real_request(*a, **k)
        try:
            with self.assertRaises(pa.ProviderError):
                pa._get_json("https://api.collegefootballdata.com/games", provider="cfbd")
        finally:
            pa.urllib.request.Request = real_request
        self.assertEqual(called, [], "the HTTP request must never fire once quota is known exhausted")

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

    def test_fetch_data_get_refuses_before_the_request_when_exhausted(self):
        import fetch_data as fd
        pq.record_response("odds_api", {"x-requests-remaining": "0", "x-requests-used": "500"})
        called = []
        real_request = fd.urllib.request.Request
        fd.urllib.request.Request = lambda *a, **k: called.append(1) or real_request(*a, **k)
        try:
            with self.assertRaises(RuntimeError):
                fd._get("https://api.the-odds-api.com/v4/sports", provider="odds_api")
        finally:
            fd.urllib.request.Request = real_request
        self.assertEqual(called, [])


if __name__ == "__main__":
    unittest.main()
