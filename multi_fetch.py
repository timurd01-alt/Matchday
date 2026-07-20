"""
multi_fetch.py — one loop that keeps EVERY sport fresh.

Each sport runs as a short one-shot fetch (its own process), on its own cadence:

  any match LIVE now          -> refetch that sport every 60 s
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
]
SPACING = 20          # seconds between two sports' fetches (quota safety)
TICK = 15             # scheduler wake-up interval
RETRY_AFTER_ERROR = 15 * 60

LIVE_EVERY = 60
SOON_EVERY = 60 * 60
NEAR_EVERY = 6 * 3600
DORMANT_EVERY = 12 * 3600

# When a sport's provider changes in code, a cached data_<key>.json from the
# old one still looks "recently fetched" to the interval check below and
# never gets refreshed. Force a refetch whenever the on-disk file's actual
# source doesn't match what the sport is currently configured to use.
EXPECTED_SOURCE = {"nfl": "BALLDONTLIE", "nba": "BALLDONTLIE"}


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
            return LIVE_EVERY
        if m.get("status") == "UPCOMING" and m.get("kickoff"):
            try:
                ko = datetime.datetime.fromisoformat(str(m["kickoff"]).replace("Z", "+00:00"))
            except Exception:
                continue
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
    try:
        r = subprocess.run([sys.executable, "fetch_data.py", flag],
                           capture_output=True, text=True, timeout=600,
                           cwd=os.path.dirname(os.path.abspath(__file__)) or ".")
        out = (r.stdout or "") + "\n" + (r.stderr or "")
        ok = r.returncode == 0 and os.path.exists(f"data_{key}.json")
        tail = [l for l in out.strip().splitlines() if l.strip()]
        last = tail[-1] if tail else "(no output)"
        if ok:
            print(f"  [{key}] fetched · {last[:100]}")
        else:
            # show WHY: keys not loaded, network blocked, etc.
            reason = last
            for l in tail:
                if "Stop:" in l or "not found" in l or "could not be loaded" in l or "403" in l or "401" in l:
                    reason = l.strip(); break
            print(f"  [{key}] FAILED · {reason[:140]}")
        return ok
    except Exception as e:
        print(f"  [{key}] FAILED · {e}")
        return False


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
                label = ("live" if iv == LIVE_EVERY else "1h" if iv == SOON_EVERY
                         else "6h" if iv == NEAR_EVERY else "12h")
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
    due = [(k, f) for k, f in SPORTS if not os.path.exists(f"data_{k}.json")
           or _stale_source(k) or time.time() - last_fetched.get(k, 0) >= _interval_for(k)]
    for i, (key, flag) in enumerate(due):
        ok = _run_one(key, flag)
        if ok:
            last_fetched[key] = time.time()
        if i < len(due) - 1:
            time.sleep(SPACING)
    due_keys = {k for k, _ in due}
    skipped = [k for k, _ in SPORTS if k not in due_keys]
    if skipped:
        print(f"  skipped (not due yet): {', '.join(skipped)}")
    with open(state_path, "w", encoding="utf-8") as f:
        json.dump(last_fetched, f)


if __name__ == "__main__":
    try:
        if "--once" in sys.argv:
            run_once()
        else:
            loop()
    except KeyboardInterrupt:
        pass
