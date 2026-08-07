"""Cross-run request-budget enforcement, so a provider's quota is refused
BEFORE it is exhausted instead of discovered after a 429.

Why this exists
----------------
Confirmed live 2026-07-31: CollegeFootballData, CollegeBasketballData, and
The Odds API were all sitting at zero remaining calls for their current
billing period, with predictions and market comparisons quietly degrading to
"no data" / "Not available" across the live site. Every one of those
providers actually TELLS us how much budget is left on every single response,
via a rate-limit header (or, for The Odds API, a used/remaining header pair) --
but nothing in this codebase ever read or persisted that number. Requests kept
firing blind until the provider itself said no, which is how the quota gets
run all the way to zero with no warning and stays there for the rest of the
billing period.

This module is deliberately NOT a guess at "N requests is safe per day" --
guessing a number that turns out to be wrong just relocates the outage rather
than preventing it. Instead: after every real HTTP response, record_response()
parses whatever quota header(s) that specific provider exposes (see
PROVIDER_SPECS) into a small persisted ledger. Before firing the next request,
check() consults that ledger and refuses the call once remaining budget drops
to a safety reserve, well before the provider's own limit -- self-correcting
from ground truth instead of a fixed estimate, and immediately effective even
without knowing a provider's exact monthly ceiling (CFBD/CBBD have never
published one in this codebase; the reserve-based approach works without it).

A provider not listed in PROVIDER_SPECS, or a caller that never passes
`provider=`, is completely untracked -- existing behavior for anything this
module doesn't yet know how to read.

The reserve alone only guarantees a provider never actually hits zero -- it
says nothing about WHEN in the period that happens. A provider that front-
loads its whole budget in the first few days (exactly how The Odds API got
to zero well before 2026-07-31's billing period ended) would sail past every
check() until the reserve floor, then go dark for the rest of the period.
Where a real numeric ceiling is derivable (The Odds API's remaining+used
pair; see `limit` in _record_one), _pace_reason() adds a second check: refuse
once usage is running meaningfully ahead of an even day-by-day drawdown of
that ceiling, so a hot streak gets throttled while it's happening instead of
only once nothing is left.
"""
from __future__ import annotations

import datetime
import json
import os


class QuotaExceededError(RuntimeError):
    """Raised by check() instead of letting a request fire into a known-empty budget."""


STATE_FILE = "provider_quota_state.json"

# A provider's tracked remaining budget can be low without this run ever
# having asked it for anything -- that alone doesn't mean output degraded
# just now. This instead records providers that were ACTUALLY refused a call
# during the current build(), so the payload can tell users "some data is
# limited this run" rather than only a stale "last updated" timestamp, which
# stays fresh even when every call to a quota-exhausted provider silently
# fails and falls back to "no data" (see AGENTS.md's 2026-07-31 incident).
BLOCKED_THIS_RUN = []


def record_block(provider):
    """Call when `check()` refused a call this run, from the same except
    block that catches QuotaExceededError at each adapter's HTTP getter."""
    if provider not in BLOCKED_THIS_RUN:
        BLOCKED_THIS_RUN.append(provider)

# --- per-provider header maps -------------------------------------------
# Every mapping below was read directly off a live response on 2026-07-31,
# not guessed from documentation (CFBD/CBBD in particular publish no rate
# limit numbers in their docs at all). "window" decides how record_response
# reconciles an old observation with the current one:
#
#   rolling_seconds : reset_header carries SECONDS remaining in the current
#                      window (football-data.org's X-RequestCounter-Reset).
#   rolling_unix     : reset_header carries a unix timestamp when the window
#                      next resets (BallDontLie's x-ratelimit-reset).
#   calendar_day     : no reset header exists; assume the provider's own
#                       counter resets at UTC midnight (API-Football's daily
#                       bucket, confirmed via its own body: "limit_day").
#   calendar_month   : no reset header exists; assume the provider resets on
#                       the 1st of the UTC month. CFBD's 429 body reads
#                       "Monthly call quota exceeded", so this is
#                       confirmed for CFBD/CBBD; The Odds API's free tier is
#                       commonly monthly but this codebase has never
#                       confirmed that against their docs -- treated the same
#                       way here because being conservative about a reset
#                       that might arrive sooner only costs a few refused
#                       calls, never a real quota overrun.
#
# `reserve` is how much of the provider's own remaining-count is kept
# untouched as a buffer -- calls stop once remaining would fall at or below
# this floor, not when the provider itself would refuse. Loose ends (an
# extra manual debug session, an unusually large one-off backfill) then have
# margin instead of being the call that actually trips the 429.
PROVIDER_SPECS = {
    "cfbd": {
        "remaining_header": "x-calllimit-remaining",
        "limit_header": None,
        "window": "calendar_month",
        "reserve": 25,
        "quota_body_markers": ("monthly call quota exceeded",),
    },
    "cbbd": {
        "remaining_header": "x-calllimit-remaining",
        "limit_header": None,
        "window": "calendar_month",
        "reserve": 25,
        "quota_body_markers": ("monthly call quota exceeded",),
    },
    "football_data": {
        "remaining_header": "x-requests-available-minute",
        "limit_header": None,
        "reset_header": "x-requestcounter-reset",
        "window": "rolling_seconds",
        "reserve": 1,
    },
    "balldontlie": {
        "remaining_header": "x-ratelimit-remaining",
        "limit_header": "x-ratelimit-limit",
        "reset_header": "x-ratelimit-reset",
        "window": "rolling_unix",
        "reserve": 1,
    },
    # Big Balls returns the tighter of its minute/day buckets in the standard
    # X-RateLimit trio on every authenticated response. The reset is a unix
    # timestamp. This enforces the observable bucket; Matchday additionally
    # limits usage structurally to one cached league-wide injury request per
    # supported competition, keeping the 1,000/day free allowance well clear.
    "bigballs": {
        "remaining_header": "x-ratelimit-remaining",
        "limit_header": "x-ratelimit-limit",
        "reset_header": "x-ratelimit-reset",
        "window": "rolling_unix",
        "reserve": 2,
    },
    # API-Football exposes two INDEPENDENT buckets on every response: a
    # per-minute rate limit and a per-day request cap. Both must have room or
    # the call is refused -- see check()/record_response()'s "api_football"
    # special-casing, which updates/consults both sub-keys together.
    "api_football": {
        "sub_keys": {
            "minute": {"remaining_header": "x-ratelimit-remaining",
                       "limit_header": "x-ratelimit-limit",
                       "window": "rolling_seconds_assumed", "assumed_seconds": 60,
                       "reserve": 1},
            "day": {"remaining_header": "x-ratelimit-requests-remaining",
                    "limit_header": "x-ratelimit-requests-limit",
                    "window": "calendar_day", "reserve": 5},
        },
    },
    "odds_api": {
        "remaining_header": "x-requests-remaining",
        "used_header": "x-requests-used",
        "window": "calendar_month",
        "reserve": 5,
    },
}


def _load_state(path=STATE_FILE):
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:
        return {}


def _save_state(state, path=STATE_FILE):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(state, handle)
    os.replace(tmp, path)


def _header(headers, name):
    """Case-insensitive header lookup -- http.client/urllib both preserve
    whatever case the server sent, which varies across these five providers."""
    if not headers:
        return None
    for key, value in headers.items():
        if key.lower() == name.lower():
            return value
    return None


def _now():
    return datetime.datetime.now(datetime.timezone.utc)


def _period_start(window, when):
    if window in ("calendar_month",):
        return when.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if window in ("calendar_day",):
        return when.replace(hour=0, minute=0, second=0, microsecond=0)
    return None


def _record_one(state, key, spec, headers, body, now):
    remaining_raw = _header(headers, spec["remaining_header"]) if spec.get("remaining_header") else None
    entry = state.get(key, {})
    quota_hit = False
    if remaining_raw is not None:
        try:
            entry["remaining"] = int(float(remaining_raw))
        except (TypeError, ValueError):
            pass
    limit_raw = _header(headers, spec.get("limit_header") or "") if spec.get("limit_header") else None
    if limit_raw is not None:
        try:
            entry["limit"] = int(float(limit_raw))
        except (TypeError, ValueError):
            pass
    if spec.get("used_header") and remaining_raw is not None:
        used_raw = _header(headers, spec["used_header"])
        try:
            if used_raw is not None:
                entry["limit"] = int(float(used_raw)) + entry["remaining"]
        except (TypeError, ValueError):
            pass
    reset_raw = _header(headers, spec.get("reset_header") or "") if spec.get("reset_header") else None
    if spec["window"] == "rolling_seconds" and reset_raw is not None:
        try:
            entry["reset_at"] = (now + datetime.timedelta(seconds=float(reset_raw))).isoformat()
        except (TypeError, ValueError):
            pass
    elif spec["window"] == "rolling_seconds_assumed":
        entry["reset_at"] = (now + datetime.timedelta(seconds=spec["assumed_seconds"])).isoformat()
    elif spec["window"] == "rolling_unix" and reset_raw is not None:
        try:
            entry["reset_at"] = datetime.datetime.fromtimestamp(
                float(reset_raw), tz=datetime.timezone.utc).isoformat()
        except (TypeError, ValueError):
            pass
    elif spec["window"] in ("calendar_day", "calendar_month"):
        entry["period_start"] = _period_start(spec["window"], now).isoformat()
    entry["observed_at"] = now.isoformat()
    markers = spec.get("quota_body_markers")
    if markers and body:
        low = str(body).lower()
        if any(marker in low for marker in markers):
            entry["remaining"] = 0
            quota_hit = True
    state[key] = entry
    return quota_hit


def record_response(provider, headers, body=None, state_path=STATE_FILE):
    """Update the persisted ledger from one real HTTP response's headers
    (and, for CFBD/CBBD, the response body -- they carry no numeric total,
    only a "Monthly call quota exceeded" message once actually exhausted)."""
    spec = PROVIDER_SPECS.get(provider)
    if not spec:
        return
    state = _load_state(state_path)
    now = _now()
    if "sub_keys" in spec:
        for sub_name, sub_spec in spec["sub_keys"].items():
            _record_one(state, f"{provider}:{sub_name}", sub_spec, headers, body, now)
    else:
        _record_one(state, provider, spec, headers, body, now)
    _save_state(state, state_path)


def _period_end(window, period_start):
    if window == "calendar_month":
        if period_start.month == 12:
            return period_start.replace(year=period_start.year + 1, month=1)
        return period_start.replace(month=period_start.month + 1)
    if window == "calendar_day":
        return period_start + datetime.timedelta(days=1)
    return None


# How far ahead of an even day-by-day drawdown of the period's budget a
# provider is allowed to run before pacing refuses further calls -- e.g. 1.15
# lets a provider that's used 40% of its budget 20% of the way through the
# period keep going (a real, plausible burst: a busy multi-sport day), while
# one that's used 90% after 20% of the period (confirmed live 2026-07-31 for
# The Odds API, spent to zero long before the month was out) gets refused
# well before the hard RESERVE floor at the very end would have caught it.
PACE_SLACK = 1.15


def _pace_reason(key, spec, entry, now):
    """None if usage is roughly on track to last the rest of the period, else
    a refusal reason. Only engages when a real numeric ceiling is known (the
    `limit` derived from a provider's own remaining/used headers -- see
    _record_one) -- CFBD/CBBD publish no such number, so this silently never
    applies to them, same as every other check in this module: only ever
    tightens behavior once real data says to, never guesses one up.

    Scoped to calendar_month only, not calendar_day: API-Football's day
    bucket (the only other spec with a derivable `limit`) legitimately gets
    used in bursts within a single day by design (a batch stats/lineups
    pass), and that bucket already resets in hours, not weeks -- there's
    little for within-day pacing to protect against that the existing
    per-day reserve doesn't already cover, and it would make "how far
    through today are we" -- a time-of-day-dependent quantity -- part of
    whether a call is allowed, which is a sharper edge than this feature is
    meant to add."""
    limit = entry.get("limit")
    if not limit or spec["window"] != "calendar_month":
        return None
    period_start_raw = entry.get("period_start")
    if not period_start_raw:
        return None
    try:
        period_start = datetime.datetime.fromisoformat(period_start_raw)
    except ValueError:
        return None
    period_end = _period_end(spec["window"], period_start)
    total_seconds = (period_end - period_start).total_seconds()
    if total_seconds <= 0:
        return None
    elapsed_fraction = max(0.0, min(1.0, (now - period_start).total_seconds() / total_seconds))
    allowed_used = limit * elapsed_fraction * PACE_SLACK
    used = limit - entry["remaining"]
    if used > allowed_used:
        return (f"{key}: {used}/{limit} used, ahead of the pace needed to last "
                f"the rest of the {spec['window'].split('_')[1]} "
                f"({allowed_used:.0f} allowed by now; observed {entry.get('observed_at', '?')})")
    return None


def _resets_since(entry, spec, now):
    """True if the tracked window has rolled over since the last observation,
    meaning a stale low/zero remaining count should no longer block calls."""
    if spec["window"] in ("rolling_seconds", "rolling_seconds_assumed", "rolling_unix"):
        reset_at = entry.get("reset_at")
        if not reset_at:
            return False
        try:
            return now >= datetime.datetime.fromisoformat(reset_at)
        except ValueError:
            return False
    if spec["window"] in ("calendar_day", "calendar_month"):
        period_start = entry.get("period_start")
        if not period_start:
            return False
        try:
            current_start = _period_start(spec["window"], now).isoformat()
            return current_start != period_start
        except ValueError:
            return False
    return False



# Confirmed 2026-08-01: CFBD and The Odds API both still reported 0
# remaining several hours into the new UTC month (04:37), then had
# genuinely reset by early afternoon -- their real billing-cycle rollover
# doesn't land exactly on the 00:00:00 UTC boundary this module assumes.
# record_response() stamps period_start onto the ledger the instant a
# provider is observed in the new period, even if that first observation
# still carries the previous period's near-zero count. Once that happens,
# _resets_since() sees the ledger's period_start already matching the
# current one and stops treating the count as stale, so check() blocks
# every further call for the rest of the period -- and since a blocked
# call never fires, record_response() never gets another real response to
# refresh the ledger with. Without a bounded re-probe, a provider whose
# reset merely lags our assumed boundary by a few hours would otherwise
# read as exhausted for the remaining ~30 days of the period.
PROBE_COOLDOWN_HOURS = 6


def _check_one(state, key, spec, now):
    entry = state.get(key)
    if not entry or entry.get("remaining") is None:
        return None  # never observed -- nothing to enforce yet
    if _resets_since(entry, spec, now):
        return None  # window has rolled over; the stale count no longer applies
    if entry["remaining"] <= spec["reserve"]:
        observed_at = entry.get("observed_at")
        if observed_at:
            try:
                last = datetime.datetime.fromisoformat(observed_at)
                if now - last >= datetime.timedelta(hours=PROBE_COOLDOWN_HOURS):
                    return None  # let one real call through to re-observe the true count
            except ValueError:
                pass
        return (f"{key}: {entry['remaining']} remaining, at or below the "
                f"{spec['reserve']}-call safety reserve (observed {entry.get('observed_at', '?')})")
    return _pace_reason(key, spec, entry, now)


def check(provider, state_path=STATE_FILE):
    """Raise QuotaExceededError if the ledger shows this provider at or below
    its safety reserve for the currently-tracked window. Silent (no-op) for
    any provider never observed yet, or one not in PROVIDER_SPECS at all --
    this only ever tightens behavior once real data says to, never guesses."""
    spec = PROVIDER_SPECS.get(provider)
    if not spec:
        return
    state = _load_state(state_path)
    now = _now()
    if "sub_keys" in spec:
        for sub_name, sub_spec in spec["sub_keys"].items():
            reason = _check_one(state, f"{provider}:{sub_name}", sub_spec, now)
            if reason:
                raise QuotaExceededError(reason)
        return
    reason = _check_one(state, provider, spec, now)
    if reason:
        raise QuotaExceededError(reason)


def status(state_path=STATE_FILE):
    """Human-readable snapshot for diagnostics/status pages."""
    state = _load_state(state_path)
    lines = []
    for key in sorted(state):
        entry = state[key]
        limit = entry.get("limit")
        lines.append(f"{key}: {entry.get('remaining', '?')}"
                     f"{f'/{limit}' if limit is not None else ''} remaining"
                     f" (observed {entry.get('observed_at', '?')})")
    return lines
