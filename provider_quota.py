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
"""
from __future__ import annotations

import datetime
import json
import os


class QuotaExceededError(RuntimeError):
    """Raised by check() instead of letting a request fire into a known-empty budget."""


STATE_FILE = "provider_quota_state.json"

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


def _check_one(state, key, spec, now):
    entry = state.get(key)
    if not entry or entry.get("remaining") is None:
        return None  # never observed -- nothing to enforce yet
    if _resets_since(entry, spec, now):
        return None  # window has rolled over; the stale count no longer applies
    if entry["remaining"] <= spec["reserve"]:
        return (f"{key}: {entry['remaining']} remaining, at or below the "
                f"{spec['reserve']}-call safety reserve (observed {entry.get('observed_at', '?')})")
    return None


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
