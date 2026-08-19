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
without knowing a provider's exact monthly ceiling. CFBD's configured free
tier is now known to be 1,000/month and is paced explicitly; CBBD still falls
back to reserve enforcement because no verified ceiling is configured here.

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
BOOTSTRAP_ENV = "MATCHDAY_QUOTA_ALLOW_BOOTSTRAP"
FAIL_CLOSED_WITHOUT_STATE = {"cfbd", "odds_api"}
FREE_PROBE_COOLDOWN_HOURS = 6
FREE_PROBE_PROVIDERS = {"cfbd", "odds_api"}

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
        # CFBD's current free tier is 1,000 calls/month.  Unlike The Odds API
        # it does not return a total-limit header, so the known plan ceiling
        # must be supplied here or day-by-day pacing can never engage.
        "known_limit": 1000,
        # CFBD usage is seasonally front-loaded around schedule/model rebuilds.
        # A wider burst allowance still catches a runaway early-month burn,
        # while the adaptive fetch cadence and hard reserve protect the tail.
        "pace_slack": 1.5,
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


def _load_state(path=None):
    path = os.fspath(path or STATE_FILE)
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:
        return {}


def _save_state(state, path=None):
    path = os.fspath(path or STATE_FILE)
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


# How many distinct endpoints to keep per provider. A provider whose URLs
# carry unbounded identifiers would otherwise grow the ledger without limit;
# the point is to see where a budget goes, and the long tail past this many
# endpoints is not where it goes.
USAGE_ENDPOINT_CAP = 24


def endpoint_key(url):
    """A stable, low-cardinality label for what a call was spent on.

    Budget accounting is only useful if the same logical endpoint reports
    under the same name across a month, so the query string goes (that is
    where `year=2026` lives) and path segments that look like identifiers
    collapse to `:id`. `/games?year=2026&classification=fbs` and
    `/games?year=2025` are the same line item; `/teams/42` and `/teams/97`
    are `/teams/:id`.
    """
    text = str(url or "")
    path = text.split("://", 1)[-1]
    path = path.split("/", 1)[1] if "/" in path else ""
    path = path.split("?", 1)[0].split("#", 1)[0]
    parts = []
    for segment in path.split("/"):
        if not segment:
            continue
        looks_like_id = segment.isdigit() or (
            len(segment) > 12 and any(char.isdigit() for char in segment))
        parts.append(":id" if looks_like_id else segment)
    return "/" + "/".join(parts[:3]) if parts else "/"


def _record_spend(entry, spec, endpoint, now, crossed_period):
    """Count what this run actually spent, per period and per endpoint.

    The ledger has always recorded what a provider *said was left*. It never
    recorded what Matchday *spent, or on what*, so every cache TTL in the
    codebase is a guess nobody can check and an exhausted budget cannot be
    traced to the call that drained it. cfbd burned 1,000 calls by 2026-08-10
    and there is still no way to say which endpoint did it.
    """
    period = _period_start(spec["window"], now).isoformat() if spec["window"] in (
        "calendar_day", "calendar_month") else "rolling"
    if entry.get("spend_period") != period or crossed_period:
        entry["spend_period"] = period
        entry["spent"] = 0
        entry["by_endpoint"] = {}
    entry["spent"] = int(entry.get("spent") or 0) + 1
    # Daily spend is tracked separately from period spend: the budget rations
    # a day at a time, and a period total cannot say whether today has already
    # had its share.
    day = _period_start("calendar_day", now).isoformat()
    if entry.get("spend_day") != day:
        entry["spend_day"] = day
        entry["spent_today"] = 0
    entry["spent_today"] = int(entry.get("spent_today") or 0) + 1
    if endpoint:
        usage = entry.get("by_endpoint")
        if not isinstance(usage, dict):
            usage = {}
        if endpoint in usage or len(usage) < USAGE_ENDPOINT_CAP:
            usage[endpoint] = int(usage.get(endpoint) or 0) + 1
        else:
            usage["(other)"] = int(usage.get("(other)") or 0) + 1
        entry["by_endpoint"] = usage


def _record_one(state, key, spec, headers, body, now, endpoint=None):
    remaining_raw = _header(headers, spec["remaining_header"]) if spec.get("remaining_header") else None
    entry = state.get(key, {})
    previous_period = entry.get("period_start")
    previous_remaining = entry.get("remaining")
    quota_hit = False
    crossed_period = False
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
    if spec.get("known_limit"):
        entry.setdefault("limit", int(spec["known_limit"]))
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
        current_period = _period_start(spec["window"], now).isoformat()
        entry["period_start"] = current_period
        crossed_period = previous_period and previous_period != current_period
        still_exhausted = (entry.get("remaining") is not None
                           and entry["remaining"] <= spec["reserve"])
        if still_exhausted and (entry.get("reset_pending") or
                                (crossed_period and previous_remaining is not None
                                 and previous_remaining <= spec["reserve"])):
            entry["reset_pending"] = True
            entry.setdefault("reset_probe_at", now.isoformat())
        elif not still_exhausted:
            entry.pop("reset_pending", None)
            entry.pop("reset_probe_at", None)
            entry.pop("reset_probe_count", None)
    # A response carrying no remaining-count header still spent budget. Until
    # now `remaining` only ever moved when the provider volunteered that
    # header, so calls against header-less endpoints were invisible to the
    # ledger: check() kept seeing the last number the provider happened to
    # report and went on approving calls. That is how a floor can be skipped
    # entirely rather than enforced -- cfbd was observed at remaining=0
    # against reserve=25, which the reserve alone should have made
    # unreachable, and then stayed dark for the rest of the calendar month.
    #
    # Debiting one call per observed response keeps the reserve enforceable
    # from what the ledger can actually see. A real header always overwrites
    # this estimate on the next response that carries one, so the local count
    # is only ever a floor-preserving stand-in between real observations, and
    # it is deliberately one-directional: it never credits budget back and
    # never raises a reserve. Skipped on the run that crosses into a new
    # period, where `remaining` is a stale reading of the period just ended
    # and the reset probe -- not arithmetic here -- establishes the new one.
    if (remaining_raw is None
            and spec["window"] in ("calendar_day", "calendar_month")
            and isinstance(entry.get("remaining"), int)
            and not crossed_period):
        entry["remaining"] = max(0, entry["remaining"] - 1)
    _record_spend(entry, spec, endpoint, now, crossed_period)
    entry["observed_at"] = now.isoformat()
    markers = spec.get("quota_body_markers")
    if markers and body:
        low = str(body).lower()
        if any(marker in low for marker in markers):
            entry["remaining"] = 0
            quota_hit = True
    state[key] = entry
    return quota_hit


def record_response(provider, headers, body=None, state_path=None, url=None):
    """Update the persisted ledger from one real HTTP response's headers
    (and, for CFBD/CBBD, the response body -- they carry no numeric total,
    only a "Monthly call quota exceeded" message once actually exhausted).

    `url`, when given, is reduced to a low-cardinality endpoint label and
    counted, so a month's spend can be attributed to the calls that made it.
    Callers that omit it still update the ledger exactly as before; only the
    per-endpoint breakdown is lost.
    """
    spec = PROVIDER_SPECS.get(provider)
    if not spec:
        return
    state = _load_state(state_path)
    now = _now()
    endpoint = endpoint_key(url) if url else None
    if "sub_keys" in spec:
        for sub_name, sub_spec in spec["sub_keys"].items():
            _record_one(state, f"{provider}:{sub_name}", sub_spec, headers, body,
                        now, endpoint)
    else:
        _record_one(state, provider, spec, headers, body, now, endpoint)
    _save_state(state, state_path)


def claim_free_probe(provider, state_path=None):
    """Claim a provider-documented zero-credit quota receipt refresh.

    Only The Odds API currently has such an endpoint.  The claim is persisted
    before HTTP so parallel competition jobs and a genuinely exhausted account
    cannot turn a free status check into an unbounded polling loop.
    """
    if provider not in FREE_PROBE_PROVIDERS:
        return False
    state = _load_state(state_path)
    now = _now()
    entry = state.get(provider, {})
    last_raw = entry.get("free_probe_at")
    try:
        last = datetime.datetime.fromisoformat(last_raw) if last_raw else None
    except ValueError:
        last = None
    if last is not None and now - last < datetime.timedelta(hours=FREE_PROBE_COOLDOWN_HOURS):
        return False
    entry["free_probe_at"] = now.isoformat()
    state[provider] = entry
    _save_state(state, state_path)
    return True


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
    _record_one), or when a verified ``known_limit`` is configured (CFBD).
    Providers with neither silently retain reserve-only behavior.

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
    allowed_used = limit * elapsed_fraction * float(spec.get("pace_slack", PACE_SLACK))
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
RESET_PROBE_WINDOW_HOURS = 48
RESET_PROBE_MAX_CALLS = 4


def _bootstrap_allowed():
    return str(os.environ.get(BOOTSTRAP_ENV, "")).strip().lower() in {"1", "true", "yes"}


def _calendar_reset_probe_due(entry, spec, now):
    """Whether one bounded re-observation may fire around a calendar reset.

    A zero balance is not itself permission to probe forever.  Re-probes are
    only allowed during the first 48 hours of a newly expected period, capped
    at four calls, and claimed in the persisted ledger before HTTP starts.
    """
    if spec["window"] not in ("calendar_day", "calendar_month"):
        return False
    current_start = _period_start(spec["window"], now)
    if now - current_start > datetime.timedelta(hours=RESET_PROBE_WINDOW_HOURS):
        return False
    if not _resets_since(entry, spec, now) and not entry.get("reset_pending"):
        return False
    if int(entry.get("reset_probe_count") or 0) >= RESET_PROBE_MAX_CALLS:
        return False
    probe_at = entry.get("reset_probe_at")
    if probe_at:
        try:
            if now - datetime.datetime.fromisoformat(probe_at) < datetime.timedelta(hours=PROBE_COOLDOWN_HOURS):
                return False
        except ValueError:
            pass
    return True


def _check_one(state, key, spec, now):
    entry = state.get(key)
    if not entry or entry.get("remaining") is None:
        return None  # never observed -- nothing to enforce yet
    if _calendar_reset_probe_due(entry, spec, now):
        entry["reset_pending"] = True
        entry["reset_probe_at"] = now.isoformat()
        entry["reset_probe_count"] = int(entry.get("reset_probe_count") or 0) + 1
        return None
    if (_bootstrap_allowed() and spec["window"] in ("calendar_day", "calendar_month")
            and (_resets_since(entry, spec, now) or entry.get("reset_pending")
                 or entry["remaining"] <= spec["reserve"])):
        last_raw = entry.get("manual_probe_at")
        try:
            last = datetime.datetime.fromisoformat(last_raw) if last_raw else None
        except ValueError:
            last = None
        if last is None or now - last >= datetime.timedelta(hours=PROBE_COOLDOWN_HOURS):
            entry["manual_probe_at"] = now.isoformat()
            return None
    if _resets_since(entry, spec, now):
        if spec["window"] in ("rolling_seconds", "rolling_seconds_assumed", "rolling_unix"):
            return None
        return (f"{key}: expected quota reset has not been safely re-observed; "
                f"manual {BOOTSTRAP_ENV}=1 bootstrap required")
    if entry["remaining"] <= spec["reserve"]:
        return (f"{key}: {entry['remaining']} remaining, at or below the "
                f"{spec['reserve']}-call safety reserve (observed {entry.get('observed_at', '?')})")
    return _pace_reason(key, spec, entry, now)


def check(provider, state_path=None, tier=None):
    """Raise QuotaExceededError if the ledger shows this provider at or below
    its safety reserve for the currently-tracked window. Silent (no-op) for
    unknown providers. CFBD and The Odds API fail closed when their persisted
    ledger is missing; a deliberate bootstrap probe requires an explicit
    environment opt-in.

    `tier` states how much this particular call is worth (see quota_budget
    .json): 1 is a fixture inside its lock window, 4 is slow-moving background
    data. Omitted, it takes the policy default. The reserve is checked first
    and independently -- the budget can only ration spending that the reserve
    would already have permitted, never authorise a call it would refuse.
    """
    spec = PROVIDER_SPECS.get(provider)
    if not spec:
        return
    state = _load_state(state_path)
    now = _now()
    # An entry can exist while carrying no usable count: a response that
    # returned no remaining-count header still records observed_at and
    # period_start, and that was enough to satisfy a bare `not state.get(...)`
    # truthiness test. A provider whose very first response omitted the header
    # therefore left a ledger entry that looked like state, passed the
    # fail-closed guard, and then never blocked anything, because _check_one
    # has no number to compare against a reserve. Fail closed on the reading,
    # not on the entry.
    if provider in FAIL_CLOSED_WITHOUT_STATE and not isinstance(
            (state.get(provider) or {}).get("remaining"), int):
        if _bootstrap_allowed():
            return
        raise QuotaExceededError(
            f"{provider}: no persisted quota ledger; refusing blind request "
            f"(set {BOOTSTRAP_ENV}=1 only for one deliberate bootstrap probe)")
    if "sub_keys" in spec:
        for sub_name, sub_spec in spec["sub_keys"].items():
            reason = _check_one(state, f"{provider}:{sub_name}", sub_spec, now)
            if reason:
                raise QuotaExceededError(reason)
        _save_state(state, state_path)
        return
    reason = _check_one(state, provider, spec, now)
    if reason is None:
        budget = load_budget()
        effective_tier = tier if tier is not None else (
            (budget.get("defaults") or {}).get("tier", 3))
        verdict = budget_decision(provider, effective_tier, state, spec, now, budget)
        if verdict:
            # Advisory mode records the refusal it would have made instead of
            # making it. The allowances are derived from a ceiling and a
            # calendar rather than from measured behaviour, so enforcing them
            # before a period of accounting exists would ration real calls
            # against a guess -- the same mistake as the fixed cache TTLs this
            # is meant to replace. The counter is the evidence for flipping
            # `enforce` later.
            if budget.get("enforce") is True:
                reason = verdict
            else:
                entry = state.setdefault(provider, {})
                entry["budget_would_decline"] = int(
                    entry.get("budget_would_decline") or 0) + 1
                entry["budget_last_advice"] = verdict
    _save_state(state, state_path)
    if reason:
        raise QuotaExceededError(reason)


BUDGET_FILE = "quota_budget.json"
_BUDGET_CACHE = {}


def load_budget(path=None):
    """The rationing policy, or {} when it is absent or unreadable.

    Absent means "no budget enforcement", not "refuse everything". A missing
    policy file must never take the site's data down -- the hard reserve in
    check() is the safety mechanism and it does not depend on this.
    """
    target = path or BUDGET_FILE
    try:
        mtime = os.path.getmtime(target)
    except OSError:
        return {}
    cached = _BUDGET_CACHE.get(target)
    if cached and cached[0] == mtime:
        return cached[1]
    try:
        with open(target, encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError):
        return {}
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        return {}
    _BUDGET_CACHE[target] = (mtime, payload)
    return payload


def _days_in_period(spec, now):
    if spec["window"] == "calendar_month":
        start = _period_start("calendar_month", now)
        if start.month == 12:
            nxt = start.replace(year=start.year + 1, month=1)
        else:
            nxt = start.replace(month=start.month + 1)
        return (nxt - start).days
    return 1


def budget_decision(provider, tier, state, spec, now, budget=None):
    """Whether a tier-`tier` call fits today's allowance. None means allowed.

    The allowance is the budget still unspent divided by the days still left
    in the period, so an underspent week raises the daily figure rather than
    expiring, and an overspent one lowers it. Each tier may use a stated
    multiple of that: tier 1 up to 4x (a lock window is worth borrowing
    against a quiet Tuesday for), tier 4 barely a third of it.

    Deliberately advisory-only in one direction: this can refuse a low-tier
    call while budget remains, but it never *grants* one the reserve would
    refuse. check() applies the reserve first and this second.
    """
    budget = load_budget() if budget is None else budget
    providers = budget.get("providers") or {}
    rules = providers.get(provider)
    if not isinstance(rules, dict):
        return None
    entry = state.get(provider) or {}
    spent = entry.get("spent")
    if not isinstance(spent, int):
        return None  # no accounting yet; nothing to ration against
    ceiling = rules.get("ceiling") or entry.get("limit") or spec.get("known_limit")
    if not ceiling:
        return None  # no verified ceiling means no derivable allowance
    remaining_budget = max(0, int(ceiling) - spent)
    days_total = _days_in_period(spec, now)
    day_index = min(days_total, max(1, now.day if spec["window"] == "calendar_month" else 1))
    days_left = max(1, days_total - day_index + 1)
    allowance = max(float(rules.get("daily_floor") or 0),
                    remaining_budget / days_left)
    shares = (budget.get("defaults") or {}).get("tier_day_share") or {}
    share = shares.get(str(tier))
    try:
        share = float(share)
    except (TypeError, ValueError):
        return None
    # A counter from an earlier day is not today's spend. Reading it as such
    # would ration a fresh day against yesterday's total and refuse calls that
    # have a full allowance waiting for them.
    today = _period_start("calendar_day", now).isoformat()
    spent_today = int(entry.get("spent_today") or 0) if entry.get("spend_day") == today else 0
    if spent_today < allowance * share:
        return None
    if tier == 1 and rules.get("tier1_may_exceed_daily"):
        return None
    return (f"{provider}: tier-{tier} call declined by the daily budget "
            f"({spent_today} spent today against an allowance of "
            f"{allowance:.0f} x {share} for this tier; {remaining_budget} of "
            f"{ceiling} left with {days_left} day(s) in the period)")


def usage_report(state_path=None):
    """What each provider has spent this period, and on which endpoints.

    Structured rather than printed so `next_task.py` can rank it and a human
    can read it. This is the evidence every cache-TTL decision in the codebase
    has been made without.
    """
    state = _load_state(state_path)
    report = {}
    for key in sorted(state):
        entry = state[key]
        if not isinstance(entry, dict):
            continue
        spent = entry.get("spent")
        if not isinstance(spent, int):
            continue
        usage = entry.get("by_endpoint") if isinstance(entry.get("by_endpoint"), dict) else {}
        spec = PROVIDER_SPECS.get(key.split(":", 1)[0], {})
        ceiling = entry.get("limit") or spec.get("known_limit")
        report[key] = {
            "spent": spent,
            "period": entry.get("spend_period"),
            "remaining": entry.get("remaining"),
            "ceiling": ceiling,
            "share_of_ceiling": round(spent / ceiling, 4) if ceiling else None,
            "top_endpoints": sorted(usage.items(), key=lambda kv: (-kv[1], kv[0]))[:8],
        }
    return report


def status(state_path=None):
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
