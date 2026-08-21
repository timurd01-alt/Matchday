"""
backfill_history.py -- one-time historical Elo seed, run manually.
--------------------------------------------------------------------

Matchday's self-training Elo store (`ratings_elo.json`, `update_elo()` in
fetch_data.py) only ever learns from whatever the hourly `build()` loop
happens to fetch. For most competitions that means Elo starts essentially
blank and only accumulates real signal a few games at a time. This script
seeds it with real past completed seasons instead, in one deliberate,
manually-triggered pass -- the same "run when needed" spirit as
`update_ratings.py`, not part of the hourly cron.

WHY A SEPARATE SCRIPT (not just a `build()` flag)
  A historical backfill fetches orders of magnitude more data in one run
  than an hourly incremental fetch ever does (tens of thousands of games for
  MLB/NBA alone -- see the budget notes below), which is a meaningfully
  different provider-usage pattern worth keeping out of the automatic path
  entirely. See PROVIDER_COMPLIANCE.md's "bulk historical pull" note.

PROVIDER-PER-SEASON ASSIGNMENT (see PLAN below; every fact here is
live-verified, not assumed from docs -- see each fetch function's own
docstring in fetch_data.py / provider_adapters.py for the exact evidence):

  Competition                  Seasons          Provider
  --------------------------------------------------------------
  WC (World Cup)                2022             API-FOOTBALL
  UCL, EPL, LaLiga, SerieA,      2022             API-FOOTBALL
  Bundesliga, Ligue1             2023-2025        football-data.org
  NCAAF                          2000-(last full) CollegeFootballData (CFBD)
  NCAAM                          2000-(last full) CollegeBasketballData (CBBD)
  NFL                            2002-(last full) BALLDONTLIE
  NBA                            2000-(last full) BALLDONTLIE
  MLB                            2000-(last full) BALLDONTLIE

  NHL is excluded (disabled this session, per the parent task).

  Soccer's hard ceiling: neither free-tier provider currently integrated can
  reach further back than 2022 for WC/UCL/domestic leagues. football-data.org's
  free plan 403s on season 2022 and earlier for every competition (confirmed
  live 2026-07-26, including the 2022 World Cup itself); API-FOOTBALL's free
  plan only works for seasons 2022-2024 (2021 and 2025 both fail, confirmed
  live the same day). So 2022-2025 (4 seasons for domestic leagues/UCL, just
  the 1 real tournament for WC) is the realistic achievable range right now
  -- not 2000. This is a genuine provider-tier limit, not something this
  script routes around. Getting further back would need a different (likely
  paid) provider.

  The 2023/2024 overlap: football-data.org (2023-2025) and API-FOOTBALL
  (2022-2024) can BOTH reach seasons 2023 and 2024 for domestic leagues/UCL.
  Pulling both into Elo would double-count those two seasons' results. This
  script always uses exactly one provider per (competition, season) -- see
  PLAN -- API-FOOTBALL only for the season football-data.org can't reach
  (2022), football-data.org for the rest (2023-2025).

  NCAAF/NCAAM/NFL/NBA/MLB genuinely reach back to 2000 (2002 for NFL --
  BALLDONTLIE has no NFL games before season 2002; confirmed live with a
  full per_page=100 request returning zero rows for seasons 2000/2001, not a
  rate-limit artifact). CFBD/CBBD could in principle go back further still
  (CFBD confirmed with no restriction to at least 1970 in an earlier
  investigation this session) but this script caps at 2000 to match what was
  actually asked for; PLAN below is the only thing to edit to go further.

  Team relocations/renames do NOT fragment Elo history on any of these
  providers within this range: BALLDONTLIE and CFBD were both confirmed live
  to report historical games under each franchise's/program's *current*
  name, not the name in use at the time (e.g. BALLDONTLIE's 2003 MLB season
  lists "Washington Nationals", not "Montreal Expos"; a 1980 NBA game lists
  "Oklahoma City Thunder", not "Seattle SuperSonics"; CFBD's 2015 season
  lists "Louisiana", not "Louisiana-Lafayette", the pre-2018 name). So
  `_elo_key()` (sport-scoped `norm(name)`) never splits one program's history
  across a rename/relocation the way it would if providers used
  era-accurate names.

CHRONOLOGICAL ORDER + IDEMPOTENCY
  Elo is path-dependent: a team's rating going into game N depends on every
  game before it. `PLAN`'s season lists are always oldest-first, and `run()`
  processes them in that order, calling `update_elo()` once per season
  immediately (not batching every season into one call at the end) so a
  season's results are folded in using the ratings *as they stood after the
  previous (older) season* -- exactly reproducing what would have happened
  had Matchday been running continuously since that season. Feeding seasons
  newest-first would silently produce different, wrong ratings (a team's
  rating entering an old game would reflect results that, in real time,
  hadn't happened yet).

  `update_elo()` itself is already idempotent (tracks processed match ids
  in `seen`), so re-running this script -- in part or in full, after a
  crash, a provider outage mid-run, or deliberately splitting the work
  across multiple days -- never double-counts a result. Writing
  `ratings_elo.json` after every season (not batching to the end) means a
  Ctrl+C or crash loses no completed work; the next run picks up where it
  left off.

REQUEST BUDGET (see the docstring of each PLAN-driving fetch function for
how these were computed/verified; wall-clock estimates assume the same
pacing already established elsewhere in this codebase):

  Soccer (WC+UCL+5 domestic leagues): 7 API-FOOTBALL requests (one season 2022
    per competition, each returns the whole season/tournament in one call) +
    18 football-data.org requests (3 seasons x 6 competitions). Both well
    within either provider's daily/per-minute limits -- a few minutes total.
  NCAAF (CFBD): ~26 requests (one per season, 2000-2025) -- CFBD's per-call
    limits are generous; this is cheap, a minute or two.
  NCAAM (CBBD): ~104 requests (4 date-windowed calls per season x 26 seasons,
    mirroring schedule()'s existing windowing) -- also cheap, a few minutes.
  NFL (BALLDONTLIE): ~65 requests (2002-2025, 24 seasons, ~270 games/season
    at 100/page) -- at the existing 13s/page pacing, ~15 minutes.
  NBA (BALLDONTLIE): ~340 requests (2000-2025, 26 seasons, ~1300 games/season)
    -- ~75 minutes at the same pacing.
  MLB (BALLDONTLIE): ~640 requests (2000-2025, 26 seasons, ~2470 games/season)
    -- ~140 minutes (over 2 hours) at the same pacing.

  A FULL run (every competition) is therefore dominated by BALLDONTLIE and
  takes roughly 4 hours end to end, mostly waiting out its free-tier 5
  req/min pacing for NBA and MLB specifically -- NOT impractical to run
  unattended in one sitting, but long enough that splitting it across
  multiple invocations (--comp) or multiple days is a completely reasonable
  choice, and safe to do because of the idempotency/incremental-save
  behavior above. `--comp` lets you run the cheap competitions today and
  MLB/NBA another day if you'd rather not leave one long process running.

USAGE
  python backfill_history.py --show-plan
      Print the full season/provider assignment table and estimated request
      counts, without fetching or writing anything.

  python backfill_history.py --comp NCAAF --comp NCAAM --dry-run
      Fetch and normalize NCAAF/NCAAM's configured seasons, print a sample
      result per season, but do NOT call update_elo() or touch
      ratings_elo.json. Good for a first look before committing to a real
      run.

  python backfill_history.py --comp WC --comp UCL --elo-file scratch_elo.json
      Run for real, but against a throwaway file instead of production
      ratings_elo.json -- lets you inspect a real backfilled result without
      touching live ratings.

  python backfill_history.py
      Run every configured competition, oldest season first within each,
      writing straight to ratings_elo.json as it goes (see the request
      budget above before running this unattended -- it is a multi-hour
      job). THIS PERMANENTLY CHANGES ratings_elo.json, which every live
      Elo-derived rating/prediction reads from. Back it up first if you
      want an easy way back:  copy ratings_elo.json ratings_elo.backup.json

  python backfill_history.py --comp NFL
      Just one competition -- the natural way to split a full run across
      multiple sittings.
"""
import argparse
import datetime as dt
import sys
import time

import fetch_data as fd
from provider_adapters import (BallDontLieAdapter, CollegeBasketballDataAdapter,
                               CollegeFootballDataAdapter)

# Small courtesy pause between *seasons* for providers whose adapters don't
# already pace themselves within a season (CFBD: one request per season;
# CBBD: four date-windowed requests per season, back to back today in
# production too). Not a documented hard requirement -- CFBD/CBBD's own
# per-call limits are generous (confirmed in an earlier investigation this
# session) -- just restraint appropriate to a bulk historical puller
# iterating dozens of seasons in a tight loop, versus production's one
# season at a time. BALLDONTLIE already paces itself much more slowly
# (SEASON_PAGE_DELAY_SEC, inside historical_season()); football-data.org and
# API-FOOTBALL requests are so few in total (25 combined) that no extra
# pacing is added for them.
COLLEGE_SEASON_COURTESY_DELAY_SEC = 2


def _last_full_year():
    """One calendar year behind today is always a fully-completed season
    label for every American sport this script backfills (NFL finishes by
    February, NBA by June, MLB by November, NCAAF by January, NCAAM by
    April -- all well before the following year's midsummer). Simpler and
    safer for a manually-run, occasionally-invoked tool than a per-sport
    month cutoff."""
    return dt.date.today().year - 1


def build_plan(last_full_year=None):
    """(competition -> [(season, provider), ...]) -- always oldest season
    first. See the module docstring for how each entry was decided/verified.

    provider values: "af" = API-FOOTBALL, "fd" = football-data.org,
    "cfbd" = CollegeFootballData, "cbbd" = CollegeBasketballData,
    "bdl" = BALLDONTLIE.
    """
    end = last_full_year if last_full_year is not None else _last_full_year()
    # Soccer's season list is a fixed, hand-verified table, not derived from
    # `end` -- it's capped by provider *tier* limits (see module docstring),
    # not by how much time has passed. Re-verify these four years if this
    # script is still in use much later; provider plans can change.
    soccer_domestic = [(2022, "af"), (2023, "fd"), (2024, "fd"), (2025, "fd")]
    plan = {
        "WC": [(2022, "af")],
        "UCL": list(soccer_domestic),
        "EPL": list(soccer_domestic),
        "LALIGA": list(soccer_domestic),
        "SERIEA": list(soccer_domestic),
        "BUNDESLIGA": list(soccer_domestic),
        "LIGUE1": list(soccer_domestic),
        "NCAAF": [(y, "cfbd") for y in range(2000, end + 1)],
        "NCAAM": [(y, "cbbd") for y in range(2000, end + 1)],
        "NFL": [(y, "bdl") for y in range(2002, end + 1)],
        "NBA": [(y, "bdl") for y in range(2000, end + 1)],
        "MLB": [(y, "bdl") for y in range(2000, end + 1)],
    }
    for comp, entries in plan.items():
        seasons = [s for s, _ in entries]
        assert seasons == sorted(seasons), f"{comp}'s PLAN entries must be oldest-first: {seasons}"
    return plan


# Processed cheapest-first so a full run shows progress quickly and the
# multi-hour BALLDONTLIE competitions (NBA, MLB) are last, not first --
# purely an ordering choice for a nicer run experience, not a correctness
# requirement (each competition's own Elo history is independent of the
# others; only the season order *within* one competition matters).
COMP_ORDER = ["WC", "UCL", "EPL", "LALIGA", "SERIEA", "BUNDESLIGA", "LIGUE1",
              "NCAAF", "NCAAM", "NFL", "NBA", "MLB"]


def fetch_season(comp_key, season, provider):
    """Fetch one competition's one season, via the exact provider PLAN
    assigns it, normalized to Matchday's match-list shape."""
    if provider == "cfbd":
        adapter = CollegeFootballDataAdapter(fd.CFBD_KEY, today=dt.date(season, 6, 1))
        return adapter.schedule()
    if provider == "cbbd":
        adapter = CollegeBasketballDataAdapter(fd.CBBD_KEY, today=dt.date(season, 6, 1))
        return adapter.schedule()
    if provider == "bdl":
        adapter = BallDontLieAdapter(fd.BALLDONTLIE_KEY, comp_key)
        return adapter.historical_season(season)
    if provider == "fd":
        return fd.fetch_football_data_historical_season(comp_key, season)
    if provider == "af":
        return fd.fetch_api_football_historical_season(comp_key, season)
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
