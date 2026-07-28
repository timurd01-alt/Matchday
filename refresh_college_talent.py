"""Quota-light recovery for Matchday's durable NCAAF roster-talent state.

The normal build fetches a multi-year talent blend, but it does so after the
broader college bundle has used the shared provider key. If the tracked ratings
file has no prior enrichment, one rate-limited run can therefore publish a
zero talent edge. This recovery runs first in CI and makes exactly one request
for the latest completed Team Talent Composite season. Once at least 100 teams
are persisted, future runs skip the recovery entirely.
"""

import datetime as dt

import fetch_data
from provider_adapters import CollegeFootballDataAdapter, ProviderError


MINIMUM_DURABLE_COVERAGE = 100


def refresh_if_missing(adapter=None):
    fetch_data.COMP_KEY = "NCAAF"
    fetch_data.COMP = dict(fetch_data.COMPETITIONS["NCAAF"])
    fetch_data.RATINGS_FILE = "ratings_ncaaf.json"
    fetch_data._RATINGS = None

    ratings = fetch_data._load_ratings()
    coverage = sum(
        1 for record in ratings.values()
        if isinstance(record, dict) and record.get("talent_source") == "cfbd_team_talent"
        and float(record.get("talent_strength") or 0) > 0
    )
    if coverage >= MINIMUM_DURABLE_COVERAGE:
        print(f"NCAAF roster talent already durable ({coverage} teams); recovery skipped")
        return coverage

    if adapter is None:
        # The current-season composite is not published this far ahead of the
        # season. Pinning the adapter to the previous calendar year lets its
        # public talent(seasons_back=1) method make exactly one licensed call.
        previous_year = dt.date.today().year - 1
        adapter = CollegeFootballDataAdapter(
            fetch_data.CFBD_KEY, today=dt.date(previous_year, 12, 31))
    scores = adapter.talent(seasons_back=1)
    if not scores:
        raise ProviderError("latest completed talent season returned 0 teams")
    fetch_data.apply_recruiting_strength(scores)

    durable = sum(
        1 for record in fetch_data._load_ratings().values()
        if isinstance(record, dict) and record.get("talent_source") == "cfbd_team_talent"
        and float(record.get("talent_strength") or 0) > 0
    )
    if durable < MINIMUM_DURABLE_COVERAGE:
        raise ProviderError(
            f"talent recovery covered only {durable} teams; expected at least {MINIMUM_DURABLE_COVERAGE}")
    print(f"NCAAF roster talent recovered and persisted ({durable} teams)")
    return durable


def main():
    try:
        refresh_if_missing()
    except ProviderError as exc:
        # Do not block scores, grading, or the rest of the site. The normal
        # NCAAF build still gets its own chance, and this step retries next run
        # until a durable snapshot exists.
        print(f"NCAAF roster talent recovery deferred: {exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
