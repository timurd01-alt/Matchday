"""
backfill_lineups.py -- one-time historical lineup/clean-sheet seed, run manually.
---------------------------------------------------------------------------------

BLOCKED right now for the current 2025-26 season, confirmed live 2026-07-26:
API-FOOTBALL's free plan rejects the /fixtures?date= lookup this script needs
for ANY date outside a rolling ~3-day window around today ("Free plans do not
have access to this date, try from 2026-07-25 to 2026-07-27") -- checked
against the UCL final itself (2026-05-30), still rejected. This is not a
quota/patience problem the --max-requests budget can work around; it's a
hard plan-tier wall on historical dates. The script fails fast with this
exact message the moment it hits that error, rather than silently burning
budget on 0-match runs (see the `plan_error` check below). It becomes usable
the moment either (a) a future season's matches age into being "recent" under
the live day-to-day fetch's own 2-day window instead (no backfill needed at
that point), or (b) a paid API-FOOTBALL plan removes the date restriction.

Team of Tournament's defender/goalkeeper slots only ever fill in from real
lineup data accumulated by update_player_db() (fetch_data.py), which itself
only gets fed by fetch_api_football_box_scores()'s narrow "finished within
the last API_FOOTBALL_LINEUP_DAYS_BACK (2) days" window. That's fine for a
season that's still being played -- lineups accumulate as games happen -- but
it structurally can never see a competition that already finished before this
window existed: confirmed live 2026-07-26, UCL's 2025-26 season ended in
March/April, the lineup feature was deployed 2026-07-25, and every one of its
~190 finished matches falls outside any 2-day window that will ever occur.
Team of Tournament's own "note" field was correctly explaining this (no fake
data), but the user asked for the real fix: spend real quota fetching
lineups for the matches that already happened, one deliberate manual pass,
same "run when needed" spirit as backfill_history.py/update_ratings.py.

WHY A SEPARATE SCRIPT (not just widening the 2-day window)
  API-FOOTBALL's free plan does NOT support a bulk season pull for the
  current season (confirmed live 2026-07-26: /fixtures?league=2&season=2025
  -- API-FOOTBALL numbers a season by its STARTING year, so 2025-26 is
  "season 2025" -- returns "Free plans do not have access to this season,
  try from 2022 to 2024."), so this has to use the exact same per-date
  /fixtures lookup + per-fixture /fixtures/lineups pattern the live hourly
  fetch already uses for LIVE/recent matches (fetch_api_football_box_scores
  in fetch_data.py) -- just pointed at every already-finished match instead
  of a 2-day window. That's roughly (unique matchdays) + (matches) requests
  against the SAME shared 100/day API-FOOTBALL budget the live hourly fetch
  also needs for every soccer competition, every day -- far too much for one
  run. --max-requests defaults to a conservative slice so this can run once
  a day for a few days without starving the live fetch, and it's fully
  resumable: every match it successfully processes is folded into
  player_db_<comp>.json and skipped on the next run (same _matches ledger
  update_player_db() already uses for the live path).

USAGE
  python backfill_lineups.py --comp UCL --show-plan
      Print how many finished matches are missing lineup data, with no
      requests spent.

  python backfill_lineups.py --comp UCL --dry-run
      Same, but walks the real request plan (still zero requests) so you can
      see exactly which matches/dates would be spent on first.

  python backfill_lineups.py --comp UCL --max-requests 25
      Spend up to 25 real API-FOOTBALL requests (date lookups + lineup
      fetches combined) this run, folding whatever succeeds into
      player_db_ucl.json. Re-run on subsequent days until "remaining" hits 0.
"""
import argparse
import json
import os
import sys
import time

import fetch_data as fd


def _load_data_file(comp_key):
    path = f"data_{comp_key.lower()}.json"
    if not os.path.exists(path):
        sys.exit(f"{path} does not exist -- fetch this competition at least once first")
    with open(path, encoding="utf-8") as f:
        return json.load(f).get("matches") or []


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--comp", required=True, help="competition key, e.g. UCL, WC, EPL")
    ap.add_argument("--max-requests", type=int, default=25,
                     help="request budget for this run (date lookups + lineup fetches combined), default 25")
    ap.add_argument("--show-plan", action="store_true", help="just report how many matches are missing lineups")
    ap.add_argument("--dry-run", action="store_true", help="walk the real plan, spend zero requests")
    a = ap.parse_args()

    # Was: set MATCHDAY_COMP, then import fetch_data here rather than at
    # module scope, because fetch_data resolved its competition once at
    # import and never again. set_competition() replaced that, so the
    # import is ordinary and the competition is chosen explicitly.
    fd.set_competition(a.comp)

    if fd.COMP.get("sport") != "soccer":
        sys.exit(f"{a.comp} isn't a soccer competition -- lineups/clean sheets are soccer-only")
    if not fd.API_FOOTBALL_KEY:
        sys.exit("missing API_FOOTBALL_KEY (config_keys.py or environment)")

    matches = _load_data_file(a.comp)
    finished = [m for m in matches if m.get("status") == "FINISHED" and m.get("score", {}).get("home") is not None]
    db = fd._load_player_db()
    seen = set(db.get("_matches", []))
    todo = [m for m in finished if str(m.get("id")) not in seen]
    todo.sort(key=lambda m: m.get("kickoff") or "")

    print(f"{a.comp}: {len(finished)} finished matches, {len(seen)} already have lineup data, "
          f"{len(todo)} remaining")
    if a.show_plan:
        return
    if not todo:
        print("nothing to do")
        return

    cache = fd._load_box_cache()
    now_ts = time.time()
    requests_used = 0
    attached = 0
    matched = 0
    events_by_date = {}
    remaining = len(todo)

    for m in todo:
        remaining -= 1
        if requests_used >= a.max_requests:
            print(f"budget reached ({a.max_requests} requests) -- {remaining + 1} matches left, re-run tomorrow")
            break
        d = fd._match_date_utc(m)
        if not d:
            continue
        if d not in events_by_date:
            rec = (cache.get("dates") or {}).get(d)
            if rec and now_ts - float(rec.get("t") or 0) < 6 * 3600:
                events_by_date[d] = rec.get("events") or []
            else:
                if a.dry_run:
                    print(f"  would fetch fixtures for {d}")
                    events_by_date[d] = []
                    continue
                try:
                    payload = fd._api_football_get("/fixtures", {"date": d})
                    plan_error = (payload.get("errors") or {}).get("plan") if isinstance(payload, dict) else None
                    if plan_error:
                        sys.exit(
                            f"API-FOOTBALL's free plan rejected date {d}: {plan_error!r}\n"
                            "This confirms the free plan only serves a rolling ~3-day window around "
                            "today (and only seasons 2022-2024 for season-based queries) -- a "
                            "historical backfill for an already-finished season is not something "
                            "quota/patience can work around on this plan. See backfill_lineups.py's "
                            "module docstring and PROVIDER_COMPLIANCE.md."
                        )
                    events = payload.get("response") or []
                    events_by_date[d] = events
                    cache.setdefault("dates", {})[d] = {"t": now_ts, "events": events}
                    requests_used += 1
                except Exception as e:
                    print(f"  fixture date {d} FAILED -- {e}")
                    events_by_date[d] = []
                    continue

        fid = fd._af_fixture_id_for_match(m, events_by_date.get(d) or [])
        if not fid:
            continue
        matched += 1
        fid = str(fid)
        if a.dry_run:
            print(f"  would fetch lineups for fixture {fid} ({m['home']['name']} vs {m['away']['name']}, {d})")
            continue
        if requests_used >= a.max_requests:
            break
        try:
            payload = fd._api_football_get("/fixtures/lineups", {"fixture": fid})
            lineups = fd._parse_af_lineups(payload, m)
            cache.setdefault("lineups", {})[fid] = {"t": now_ts, "lineups": lineups}
            requests_used += 1
        except Exception as e:
            print(f"  lineups for fixture {fid} FAILED -- {e}")
            continue
        if lineups:
            m["lineups"] = lineups
            attached += 1

    if a.dry_run:
        print(f"dry run: {matched} of {len(todo)} matches would resolve to a fixture id (zero requests spent)")
        return

    fd._save_box_cache(cache)
    processed = [m for m in todo if m.get("lineups")]
    if processed:
        fd.update_player_db(processed)
    print(f"this run: {requests_used} requests, {matched} matched, {attached} lineups attached, "
          f"{len(todo) - attached} still remaining")


if __name__ == "__main__":
    main()
