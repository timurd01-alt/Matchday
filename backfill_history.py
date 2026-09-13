"""
backfill_history.py -- one-time historical Elo seed, run manually.
--------------------------------------------------------------------

Matchday's self-training Elo store (`ratings_elo.json`, `update_elo()` in
fetch_data.py) only ever learns from whatever the hourly `build()` loop
happens to fetch. This script seeds it with real past completed seasons
instead, in one deliberate, manually-triggered pass -- the same "run when
needed" spirit as `update_ratings.py`, not part of the hourly cron.

PROVIDER-PER-SEASON ASSIGNMENT

  Competition   Seasons            Provider
  ------------------------------------------------------------
  NCAAF         2000-(last full)   CollegeFootballData (CFBD)
  NCAAM         2000-(last full)   CollegeBasketballData (CBBD)

  CFBD reports historical games under each program's *current* name (its
  2015 season lists "Louisiana", not "Louisiana-Lafayette"), so `_elo_key()`
  never splits one program's history across a rename.

CHRONOLOGICAL ORDER + IDEMPOTENCY
  Elo is path-dependent: a team's rating going into game N depends on every
  game before it. `PLAN`'s season lists are always oldest-first, and `run()`
  calls `update_elo()` once per season in that order, reproducing what would
  have happened had Matchday been running continuously since that season.

  `update_elo()` is idempotent (it tracks processed match ids in `seen`), so
  re-running this script -- in part or in full, after a crash or an outage --
  never double-counts a result, and `ratings_elo.json` is written after every
  season so an interrupted run loses no completed work.

REQUEST BUDGET
  NCAAF (CFBD): ~26 requests (one per season) -- a minute or two.
  NCAAM (CBBD): ~104 requests (4 date-windowed calls per season) -- a few minutes.

USAGE
  python backfill_history.py --show-plan
  python backfill_history.py --comp NCAAF --comp NCAAM --dry-run
  python backfill_history.py --comp NCAAF --elo-file scratch_elo.json
  python backfill_history.py
      Run both competitions, writing straight to ratings_elo.json. THIS
      PERMANENTLY CHANGES ratings_elo.json. Back it up first:
      copy ratings_elo.json ratings_elo.backup.json
"""
import argparse
import datetime as dt
import sys
import time

import fetch_data as fd
from provider_adapters import CollegeBasketballDataAdapter, CollegeFootballDataAdapter

# Small courtesy pause between seasons. Not a documented hard requirement --
# CFBD/CBBD's own per-call limits are generous -- just restraint appropriate
# to a bulk historical puller iterating dozens of seasons in a tight loop.
COLLEGE_SEASON_COURTESY_DELAY_SEC = 2


def _last_full_year():
    """One calendar year behind today is always a fully-completed season label
    for both sports (NCAAF finishes by January, NCAAM by April)."""
    return dt.date.today().year - 1


def build_plan(last_full_year=None):
    """(competition -> [(season, provider), ...]) -- always oldest season first.

    provider values: "cfbd" = CollegeFootballData, "cbbd" = CollegeBasketballData.
    """
    end = last_full_year if last_full_year is not None else _last_full_year()
    plan = {
        "NCAAF": [(y, "cfbd") for y in range(2000, end + 1)],
        "NCAAM": [(y, "cbbd") for y in range(2000, end + 1)],
    }
    for comp, entries in plan.items():
        seasons = [s for s, _ in entries]
        assert seasons == sorted(seasons), f"{comp}'s PLAN entries must be oldest-first: {seasons}"
    return plan


COMP_ORDER = ["NCAAF", "NCAAM"]


def fetch_season(comp_key, season, provider):
    """Fetch one competition's one season, normalized to Matchday's match-list shape."""
    if provider == "cfbd":
        adapter = CollegeFootballDataAdapter(fd.CFBD_KEY, today=dt.date(season, 6, 1))
        return adapter.schedule()
    if provider == "cbbd":
        adapter = CollegeBasketballDataAdapter(fd.CBBD_KEY, today=dt.date(season, 6, 1))
        return adapter.schedule()
    raise ValueError(f"unknown provider {provider!r}")


def show_plan(plan):
    print(f"{'Competition':<12} {'Seasons':<22} {'Provider(s)':<30}")
    for comp in COMP_ORDER:
        entries = plan.get(comp) or []
        if not entries:
            continue
        seasons = f"{entries[0][0]}-{entries[-1][0]}" if len(entries) > 1 else str(entries[0][0])
        providers = ", ".join(sorted({p for _, p in entries}))
        print(f"{comp:<12} {seasons:<22} {providers:<30} ({len(entries)} season(s))")


def run(comps, dry_run=False, elo_file=None, plan=None):
    plan = plan or build_plan()
    if elo_file:
        fd.ELO_FILE = elo_file
        fd._ELO = None  # force a fresh load from the new path
    failures = []
    for comp_key in comps:
        entries = plan.get(comp_key)
        if not entries:
            print(f"[{comp_key}] no PLAN entry -- skipping")
            continue
        # Equivalent to the COMP_KEY/COMP pair this replaced -- this loop only
        # reads Elo, which is not competition-derived (ELO_FILE is overridden
        # above and set_competition leaves it alone). Routed through the one
        # switch anyway so a future season loop that does touch the ratings or
        # picks ledger gets the right paths instead of the import-time ones.
        fd.set_competition(comp_key)
        is_college = entries[0][1] in {"cfbd", "cbbd"}
        print(f"=== {comp_key}: {len(entries)} season(s), "
              f"{entries[0][0]}-{entries[-1][0]}, oldest first ===")
        for season, provider in entries:
            try:
                matches = fetch_season(comp_key, season, provider)
            except Exception as exc:  # noqa: BLE001 -- long batch job, one bad season shouldn't kill the run
                print(f"  [{comp_key} {season} via {provider}] FAILED: {exc} "
                      f"-- skipping, re-run later to retry (idempotent)")
                failures.append((comp_key, season, provider, str(exc)))
                continue
            fd.normalize_match_results(matches)
            finished = sum(1 for m in matches if m.get("status") == "FINISHED")
            print(f"  [{comp_key} {season} via {provider}] fetched {len(matches)} "
                  f"({finished} finished)")
            if dry_run:
                sample = next((m for m in matches if m.get("status") == "FINISHED"), None)
                if sample:
                    print(f"    sample: {sample['home']['name']} vs {sample['away']['name']} "
                          f"-> {sample['score']}  [id={sample['id']}]")
                continue
            before = len(fd._load_elo()["seen"])
            fd.update_elo(matches)
            after = len(fd._load_elo()["seen"])
            print(f"    elo: +{after - before} new result(s) applied "
                  f"({after} total results tracked)")
            if is_college:
                time.sleep(COLLEGE_SEASON_COURTESY_DELAY_SEC)
    if failures:
        print(f"\n{len(failures)} season(s) failed and were skipped:")
        for comp_key, season, provider, err in failures:
            print(f"  {comp_key} {season} ({provider}): {err}")
        print("Re-run the same command (or --comp for just the failed ones) "
              "to retry -- already-applied results are skipped automatically.")
    return failures


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--comp", action="append", choices=COMP_ORDER,
                     help="competition to backfill (repeatable); default: all")
    ap.add_argument("--dry-run", action="store_true",
                     help="fetch and normalize but do not call update_elo() or write ratings_elo.json")
    ap.add_argument("--elo-file", help="write to this file instead of the real ratings_elo.json")
    ap.add_argument("--show-plan", action="store_true",
                     help="print the season/provider assignment table and exit")
    args = ap.parse_args(argv)

    plan = build_plan()
    if args.show_plan:
        show_plan(plan)
        return 0

    comps = args.comp if args.comp else COMP_ORDER
    comps = [c for c in COMP_ORDER if c in comps]  # keep the cheapest-first run order
    if args.dry_run:
        print("DRY RUN -- fetching and normalizing only, ratings_elo.json will not be touched.\n")
    elif not args.elo_file:
        print("LIVE RUN -- this will write to ratings_elo.json, which every live Elo-derived\n"
              "rating/prediction reads from. Back it up first if you want an easy way back:\n"
              "  copy ratings_elo.json ratings_elo.backup.json\n")
    failures = run(comps, dry_run=args.dry_run, elo_file=args.elo_file, plan=plan)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
