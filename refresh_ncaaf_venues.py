"""Persist licensed college stadium coordinates for weather lookup.

fetch_data.VENUE_COORDS is a hand-built keyword table that grew out of the
WC2026 venue list. It cannot cover college football: 116 distinct stadium
names appear across one upcoming NCAAF slate, several schools share a bare
"Memorial Stadium", and mapping by home team instead would attach the wrong
forecast to every neutral-site game (measured 2026-08-20: TCU hosting at
Aviva Stadium in Dublin, Auburn at Mercedes-Benz, Notre Dame at Lambeau).

CollegeFootballData publishes venue coordinates directly, so this makes one
licensed request and writes them to a durable, git-tracked file. Stadium
locations do not move, so once the file exists every later run skips the
call entirely -- the same quota-light pattern as refresh_college_talent.py.
"""

import json
import math
import os
import re

from provider_adapters import CollegeFootballDataAdapter, ProviderError


VENUE_COORDS_FILE = "ncaaf_venue_coords.json"
MINIMUM_DURABLE_COVERAGE = 400


def _cfbd_key() -> str:
    """The CollegeFootballData key, read the same way fetch_data reads it.

    This used to be `fetch_data.CFBD_KEY`, fetched through an import deferred
    into the function body -- because fetch_data imports *this* module for its
    venue lookup, so a top-level import was circular. One API key was the
    entire reason for the cycle, and the key does not come from fetch_data in
    the first place: it comes from config_keys, with the same environment
    fallback used here. Reading it at the source removes the back-edge, and
    fetch_data now imports this module normally.
    """
    try:
        from config_keys import CFBD_KEY
    except Exception:
        return os.environ.get("CFBD_KEY", "")
    return CFBD_KEY
SCHEMA_VERSION = 2
# Two stadiums this far apart are different grounds, not one record with
# sloppier coordinates. Below it, duplicate rows are treated as the same place.
DISTINCT_SITE_KM = 5.0


def normalize(name):
    """Fold a venue string to a comparison key."""
    return re.sub(r"[^a-z0-9]+", " ", str(name or "").lower()).strip()


def strip_qualifier(name):
    """The venue name with any trailing "(City, ST)" disambiguator removed."""
    return normalize(re.sub(r"\(.*?\)", "", str(name or "")))


def qualifier_city(name):
    """The city out of a "Memorial Stadium (Lincoln, NE)" style venue string.

    College stadium names are not unique -- three different "Memorial
    Stadium" grounds sit in Terre Haute, Lawrence, and Columbia, and none of
    them is Nebraska's. Feeds disambiguate with this qualifier, so it is the
    only reliable way to tell those apart.
    """
    found = re.search(r"\(([^)]*)\)", str(name or ""))
    if not found:
        return ""
    return normalize(found.group(1).split(",")[0])


def _km(first, second):
    dy = (first[0] - second[0]) * 111.0
    dx = (first[1] - second[1]) * 111.0 * math.cos(math.radians(first[0]))
    return math.hypot(dx, dy)


def _as_points(section):
    points = {}
    for key, value in (section or {}).items():
        try:
            points[str(key)] = (float(value[0]), float(value[1]))
        except (TypeError, ValueError, IndexError):
            continue
    return points


def load(path=VENUE_COORDS_FILE):
    """Return (by_name_city, by_name); empty dicts when nothing is persisted.

    `by_name` deliberately omits every name that maps to more than one real
    site. A shared name with no city qualifier is genuinely unresolvable, and
    an unresolved venue simply has no forecast -- far better than confidently
    attaching another state's weather to a fixture.
    """
    try:
        with open(path, encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError):
        return {}, {}
    if payload.get("schema_version") != SCHEMA_VERSION:
        return {}, {}
    return _as_points(payload.get("by_name_city")), _as_points(payload.get("by_name"))


def refresh_if_missing(adapter=None, path=VENUE_COORDS_FILE):
    _, existing = load(path)
    if len(existing) >= MINIMUM_DURABLE_COVERAGE:
        print(f"NCAAF venue coordinates already durable ({len(existing)} venues); refresh skipped")
        return len(existing)

    if adapter is None:
        adapter = CollegeFootballDataAdapter(_cfbd_key())
    venues = adapter.venues()
    if not venues:
        raise ProviderError("venue endpoint returned no usable coordinates")

    # The provider already disambiguates shared names in the name itself --
    # "Memorial Stadium (Lincoln, NE)" -- and Matchday's fixture feed uses
    # those same strings, so the full name is an exact, sufficient key. The
    # qualifier is deliberately NOT stripped: doing so collapses four
    # unrelated Memorial Stadiums onto one point.
    by_name_city = {}
    grouped = {}
    for venue in venues:
        point = [venue["latitude"], venue["longitude"]]
        name = normalize(venue["name"])
        city = normalize(venue.get("city"))
        if city:
            by_name_city.setdefault(f"{name}|{city}", point)
        grouped.setdefault(name, []).append(point)

    by_name = {}
    ambiguous = 0
    for name, points in grouped.items():
        first = points[0]
        if all(_km(first, other) <= DISTINCT_SITE_KM for other in points[1:]):
            by_name[name] = first
        else:
            # Genuinely different grounds sharing one unqualified name
            # (three "Husky Stadium"s). Nothing in the fixture string can
            # separate them, so they stay unresolved instead of guessed.
            ambiguous += 1

    if len(by_name) < MINIMUM_DURABLE_COVERAGE:
        raise ProviderError(
            f"venue refresh covered only {len(by_name)} unambiguous venues; "
            f"expected at least {MINIMUM_DURABLE_COVERAGE}")

    payload = {"schema_version": SCHEMA_VERSION,
               "source": "CollegeFootballData /venues",
               "source_reference": "https://collegefootballdata.com/",
               "ambiguous_names_excluded": ambiguous,
               "by_name_city": dict(sorted(by_name_city.items())),
               "by_name": dict(sorted(by_name.items()))}
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=1, sort_keys=True)
    os.replace(tmp, path)
    print(f"NCAAF venue coordinates persisted ({len(by_name)} unambiguous, "
          f"{len(by_name_city)} city-qualified, {ambiguous} shared name(s) excluded)")
    return len(by_name)


def main():
    try:
        refresh_if_missing()
    except ProviderError as exc:
        # Weather is an enrichment, never a reason to stop publishing picks.
        # The next run retries until a durable snapshot exists.
        print(f"NCAAF venue coordinate refresh deferred: {exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
