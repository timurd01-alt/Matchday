"""
multi_fetch.py — one loop that keeps EVERY sport fresh.

Each sport runs as a short one-shot fetch (its own process), on its own cadence:

  game in progress/result due -> hourly
  kickoff within 48 h         -> hourly
  fixtures within 14 days     -> every 6 h
  offseason / no data file    -> probe twice a day

Sports fetch one at a time with spacing between them, so API quotas
(football-data: 10 requests/min) are never spiked no matter how many
sports are enabled. Dormant sports cost almost nothing.

Used automatically by start_app.bat (app.py runs this loop when no
single-sport flag is given). Run standalone with:  python multi_fetch.py
"""
import datetime
import json
import os
import subprocess
import sys
import time

SPORTS = [
    ("wc", "--wc"), ("epl", "--epl"), ("laliga", "--laliga"), ("seriea", "--seriea"),
    ("bundesliga", "--bundesliga"), ("ligue1", "--ligue1"), ("ucl", "--ucl"),
    ("nfl", "--nfl"), ("ncaaf", "--ncaaf"), ("ncaam", "--ncaam"), ("nba", "--nba"),
    ("mlb", "--mlb"),
]
# NHL deliberately excluded: not reachable from the sport picker (see
# app-3-panels.js), and its schedule source (SportsDataIO) has an unresolved
# plan/billing status -- see ROTATE_KEYS.md and PROVIDER_COMPLIANCE.md.
SPACING = 30          # seconds between two sports' fetches (quota safety)
# Bumped 20 -> 30 2026-07-26: EPL/UCL/LaLiga/SerieA/Bundesliga/Ligue1/WC all
# share one football-data.org key with a real published 10-req/min limit --
# forcing 6+ of them to refetch in the same run (see FORCE_REFETCH_ONCE
# above) at 20s spacing risks enough requests landing in the same rolling
# minute to trip that limit; confirmed live 2026-07-26 that a run forcing
# every soccer competition at once left EPL/UCL's data un-refreshed (their
# fetch didn't complete) while other, non-soccer forced sports succeeded in
# the same run.
TICK = 15             # scheduler wake-up interval
RETRY_AFTER_ERROR = 15 * 60
ONCE_RETRIES = 2
ONCE_RETRY_DELAY = 5
_LAST_FAILURE_OUTPUT = {}
# Keep this empty in committed code. Temporary cache-busting entries must be
# removed after one successful run; otherwise every hourly job refetches all
# sports and delays the competitions near the end of the queue.
FORCE_REFETCH_ONCE = set()

RESULT_PENDING_EVERY = 60 * 60
SOON_EVERY = 60 * 60
NEAR_EVERY = 6 * 3600
DORMANT_EVERY = 12 * 3600
PAST_DUE_SCORE_GRACE_HOURS = 8

# When a sport's provider changes in code, a cached data_<key>.json from the
# old one still looks "recently fetched" to the interval check below and
# never gets refreshed. Force a refetch whenever the on-disk file's actual
# source doesn't match what the sport is currently configured to use.
EXPECTED_SOURCE = {"nfl": "BALLDONTLIE", "nba": "BALLDONTLIE", "mlb": "BALLDONTLIE"}


def _stale_source(key):
    expected = EXPECTED_SOURCE.get(key)
    if not expected:
        return False
    try:
        with open(f"data_{key}.json", encoding="utf-8") as f:
            matches = json.load(f).get("matches") or []
        got = (matches[0] or {}).get("data_source", "") if matches else ""
        return expected not in got
    except Exception:
        return True


# Same problem, more general: whenever a new field gets added to every match
# (e.g. "watchability"), a cached data_<key>.json from before that change
# still looks "recently fetched" to the interval check below and never picks
# up the new field until its normal cadence happens to come due -- which,
# for a DORMANT sport, can be up to 12h away. Force a refetch once, right
# away, whenever the on-disk data is missing a field the current code
# expects every match to carry.
REQUIRED_MATCH_FIELDS = ["watchability"]
REQUIRED_MATCH_VALUES = {"model_signal_schema": 6}


def _missing_fields(key):
    try:
        with open(f"data_{key}.json", encoding="utf-8") as f:
            matches = json.load(f).get("matches") or []
        if not matches:
            return False
        sample = matches[0] or {}
        return (any(field not in sample for field in REQUIRED_MATCH_FIELDS)
                or any(sample.get(field) != value for field, value in REQUIRED_MATCH_VALUES.items()))
    except Exception:
        return True


def _interval_for(key):
    """Decide the refetch interval from the sport's own data file."""
    path = f"data_{key}.json"
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
    except Exception:
        return DORMANT_EVERY  # no file yet: probe twice a day until a season exists
    now = datetime.datetime.now(datetime.timezone.utc)
    soonest = None
    for m in d.get("matches", []):
        if m.get("status") == "LIVE":
            return RESULT_PENDING_EVERY
        if m.get("status") == "UPCOMING" and m.get("kickoff"):
            try:
                ko = datetime.datetime.fromisoformat(str(m["kickoff"]).replace("Z", "+00:00"))
            except Exception:
                continue
            # Providers can leave a just-started/completed game marked
            # UPCOMING until the next poll. Treat that recent past-kickoff
            # state as score-urgent instead of waiting the normal hour.
            hours = (ko - now).total_seconds() / 3600.0
            if -PAST_DUE_SCORE_GRACE_HOURS <= hours <= 0:
                return RESULT_PENDING_EVERY
            if soonest is None or ko < soonest:
                soonest = ko
    if soonest is not None:
        hours = (soonest - now).total_seconds() / 3600.0
        if hours <= 48:
            return SOON_EVERY
        if hours <= 14 * 24:
            return NEAR_EVERY
    return DORMANT_EVERY


def _run_one(key, flag):
    """One-shot fetch for a single sport in its own process."""
    _LAST_FAILURE_OUTPUT.pop(key, None)
    data_path = f"data_{key}.json"
    # Confirmed live 2026-07-26: EPL/UCL's data went un-refreshed across
    # multiple deploy runs with no visible error anywhere reachable from
    # outside CI (the job logs aren't fetchable without a GH token) --
    # os.path.exists() alone can't tell a genuinely fresh write from a stale
    # file that was already sitting there before this subprocess ran, so a
    # subprocess that exits 0 without actually reaching its write step would
    # get silently reported as success. Comparing mtime before/after makes
    # that distinguishable and loud instead of invisible.
    mtime_before = os.path.getmtime(data_path) if os.path.exists(data_path) else None
    try:
        r = subprocess.run([sys.executable, "fetch_data.py", flag],
                           capture_output=True, text=True, timeout=600,
                           cwd=os.path.dirname(os.path.abspath(__file__)) or ".")
        out = (r.stdout or "") + "\n" + (r.stderr or "")
        mtime_after = os.path.getmtime(data_path) if os.path.exists(data_path) else None
        wrote_fresh = mtime_after is not None and mtime_after != mtime_before
        ok = r.returncode == 0 and wrote_fresh
        tail = [l for l in out.strip().splitlines() if l.strip()]
        last = tail[-1] if tail else "(no output)"
        if ok:
            _LAST_FAILURE_OUTPUT.pop(key, None)
            print(f"  [{key}] fetched · {last[:100]}")
        elif r.returncode == 0 and not wrote_fresh:
            print(f"  [{key}] FAILED (silent -- exited 0 but never rewrote {data_path}) · {last[:140]}")
        else:
            # show WHY: keys not loaded, network blocked, etc.
            reason = last
            for l in tail:
                if "Stop:" in l or "not found" in l or "could not be loaded" in l or "403" in l or "401" in l:
                    reason = l.strip(); break
            print(f"  [{key}] FAILED · {reason[:140]}")
        if not ok:
            _LAST_FAILURE_OUTPUT[key] = out
        return ok
    except Exception as e:
        _LAST_FAILURE_OUTPUT[key] = str(e)
        print(f"  [{key}] FAILED · {e}")
        return False


def _deployable_last_good(key):
    """Accept only a structurally valid existing fixture payload as fallback."""
    try:
        with open(f"data_{key}.json", encoding="utf-8") as f:
            payload = json.load(f)
        return (isinstance(payload, dict)
                and isinstance(payload.get("matches"), list)
                and isinstance(payload.get("updated"), str)
                and bool(payload.get("competition") or payload.get("comp_key")))
    except Exception:
        return False


def _rate_limited_with_last_good(key):
    detail = str(_LAST_FAILURE_OUTPUT.get(key, "")).lower()
    rate_limited = ("429" in detail or "too many requests" in detail
                    or "rate limit" in detail or "quota exceeded" in detail)
    return rate_limited and _deployable_last_good(key)


def loop():
    print(f"Multi-sport fetcher: {', '.join(k for k, _ in SPORTS)}")
    next_due = {k: 0.0 for k, _ in SPORTS}   # everything due immediately on start
    while True:
        now = time.time()
        for key, flag in SPORTS:
            if now < next_due[key]:
                continue
            ok = _run_one(key, flag)
            if ok:
                iv = _interval_for(key)
                label = ("1h" if iv == SOON_EVERY else "6h" if iv == NEAR_EVERY else "12h")
                print(f"  [{key}] next in {label}")
                next_due[key] = time.time() + iv
            else:
                next_due[key] = time.time() + RETRY_AFTER_ERROR
            time.sleep(SPACING)
            now = time.time()
        time.sleep(TICK)


def run_once(state_path=".ci_fetch_state.json"):
    """One adaptive pass over every sport, for external schedulers (e.g. CI).

    Persists last-fetch times to state_path so repeated calls only refetch
    sports that are actually due (per _interval_for) — same quota safety as
    loop(), just triggered externally instead of via an infinite while True.
    """
    try:
        with open(state_path, encoding="utf-8") as f:
            last_fetched = json.load(f)
    except Exception:
        last_fetched = {}
    print(f"Multi-sport fetcher (one-shot): {', '.join(k for k, _ in SPORTS)}")
    due = [(k, f) for k, f in SPORTS if k in FORCE_REFETCH_ONCE or not os.path.exists(f"data_{k}.json")
           or _stale_source(k) or _missing_fields(k) or time.time() - last_fetched.get(k, 0) >= _interval_for(k)]
    failed = []
    degraded = []
    for i, (key, flag) in enumerate(due):
        _LAST_FAILURE_OUTPUT.pop(key, None)
        ok = False
        for attempt in range(1, ONCE_RETRIES + 1):
            ok = _run_one(key, flag)
            if ok:
                break
            if _rate_limited_with_last_good(key):
                print(f"  [{key}] DEGRADED · provider rate-limited; preserving validated last-good data")
                degraded.append(key)
                break
            if attempt < ONCE_RETRIES:
                print(f"  [{key}] retrying ({attempt + 1}/{ONCE_RETRIES})")
                time.sleep(ONCE_RETRY_DELAY)
        if ok:
            last_fetched[key] = time.time()
        elif key not in degraded:
            failed.append(key)
        if i < len(due) - 1:
            time.sleep(SPACING)
    due_keys = {k for k, _ in due}
    skipped = [k for k, _ in SPORTS if k not in due_keys]
    if skipped:
        print(f"  skipped (not due yet): {', '.join(skipped)}")
    if degraded:
        print(f"  degraded (last-good data retained; still due): {', '.join(degraded)}")
    with open(state_path, "w", encoding="utf-8") as f:
        json.dump(last_fetched, f)
    try:
        from generate_posts import regenerate_sitemap
        n = regenerate_sitemap()
        print(f"  sitemap: {n} URLs")
    except Exception as e:
        print(f"  sitemap regen skipped: {e}")
    if failed:
        # Never assemble and deploy an old data file as a healthy refresh.
        # Successful timestamps persist, while failures stay due next run.
        raise RuntimeError("due sport refresh failed after retry: " + ", ".join(failed))


if __name__ == "__main__":
    try:
        if "--once" in sys.argv:
            run_once()
        else:
            loop()
    except KeyboardInterrupt:
        pass
