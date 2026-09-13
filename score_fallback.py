"""Final scores for college fixtures the primary feed has stopped settling.

CollegeFootballData is the NCAAF schedule. When its monthly quota is spent the
college bundle is served from cache indefinitely, and every game already
played stays ``UPCOMING`` with no score -- 460 of 460 fixtures on 2026-09-12,
which is what kept failing the freshness alarm.

This fills exactly one gap: a fixture already on Matchday's own schedule, past
kickoff, with no final. It asks ESPN's public scoreboard for the final score of
that game and nothing else. Scope is set by the owner's 2026-09-12 amendment in
PROVIDER_COMPLIANCE.md: home score, away score and "finished" only; no schedule,
odds, statistics, team data or raw payload is taken or stored, and the
scoreboard never adds a fixture.

A game is settled only when the scoreboard reports it completed, both team
names match, and the kickoffs agree. Anything ambiguous is left unsettled: a
missing score is visible and the alarm says so, a wrong one is silent.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import unicodedata
import urllib.request

SCOREBOARD = {
    "NCAAF": ("https://site.api.espn.com/apis/site/v2/sports/football/"
              "college-football/scoreboard?dates={day}&groups=80&limit=300"),
}

# A game is not expected to be final until well after kickoff; asking sooner
# spends a request on a game that is still being played.
SETTLE_AFTER_HOURS = 4.0
# Nothing older than this is looked up. A final that has been missing for
# longer is a real problem to investigate, not something to paper over.
LOOKBACK_DAYS = 10
# Kickoff times move (TV slots, weather) but not by more than this between the
# schedule and the scoreboard for the same game.
KICKOFF_TOLERANCE_HOURS = 6.0
SOURCE_LABEL = "ESPN scoreboard (final score only)"


def _fold(name) -> str:
    text = unicodedata.normalize("NFKD", str(name or "")).encode("ascii", "ignore").decode()
    text = text.lower().replace("&", " and ")
    return re.sub(r"[^a-z0-9()]+", " ", text).strip()


def _parse(value):
    try:
        stamp = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return stamp if stamp.tzinfo else stamp.replace(tzinfo=dt.timezone.utc)


def _eastern_day(kickoff: dt.datetime) -> str:
    """The date ESPN files a game under, which is its US Eastern date."""
    try:
        from zoneinfo import ZoneInfo
        local = kickoff.astimezone(ZoneInfo("America/New_York"))
    except Exception:
        local = kickoff - dt.timedelta(hours=4)
    return local.strftime("%Y%m%d")


def _fetch(url: str):
    # urllib's own User-Agent. The scoreboard answers 403 to the "Matchday/1.0"
    # agent the other adapters send (checked 2026-09-12) and 200 to the default;
    # nothing here dresses the request up as a browser.
    with urllib.request.urlopen(url, timeout=20) as response:
        return json.load(response)


def _finals(payload) -> list[dict]:
    """Completed games from one scoreboard: kickoff, names, scores. Nothing else."""
    finals = []
    for event in (payload or {}).get("events") or []:
        for competition in event.get("competitions") or []:
            status = ((competition.get("status") or {}).get("type") or {})
            if not status.get("completed"):
                continue
            sides = {c.get("homeAway"): c for c in competition.get("competitors") or []}
            home, away = sides.get("home"), sides.get("away")
            kickoff = _parse(competition.get("date") or event.get("date"))
            if not home or not away or kickoff is None:
                continue
            try:
                home_score, away_score = int(home.get("score")), int(away.get("score"))
            except (TypeError, ValueError):
                continue

            def names(side):
                team = side.get("team") or {}
                return {_fold(team.get(key)) for key in
                        ("location", "displayName", "shortDisplayName")} - {""}

            finals.append({"kickoff": kickoff, "home": names(home), "away": names(away),
                           "home_score": home_score, "away_score": away_score})
    return finals


def _unsettled(match: dict, now: dt.datetime) -> dt.datetime | None:
    if match.get("status") == "FINISHED":
        return None
    kickoff = _parse(match.get("kickoff"))
    if kickoff is None:
        return None
    age = (now - kickoff).total_seconds() / 3600.0
    return kickoff if SETTLE_AFTER_HOURS <= age <= LOOKBACK_DAYS * 24 else None


def settle(matches: list[dict], competition: str, now: dt.datetime | None = None,
           fetch=_fetch) -> dict:
    """Write final scores onto past-kickoff fixtures in place. Returns a report."""
    from provider_adapters import normalized_score

    template = SCOREBOARD.get(competition)
    report = {"candidates": 0, "settled": 0, "days": 0, "errors": []}
    if not template:
        return report
    now = now or dt.datetime.now(dt.timezone.utc)
    pending = [(match, kickoff) for match in matches or []
               if (kickoff := _unsettled(match, now)) is not None]
    report["candidates"] = len(pending)
    if not pending:
        return report

    by_day: dict[str, list[dict]] = {}
    for day in sorted({_eastern_day(kickoff) for _, kickoff in pending}):
        try:
            by_day[day] = _finals(fetch(template.format(day=day)))
            report["days"] += 1
        except Exception as exc:
            report["errors"].append(f"{day}: {exc}")

    for match, kickoff in pending:
        home = _fold((match.get("home") or {}).get("name"))
        away = _fold((match.get("away") or {}).get("name"))
        hits = []
        for final in by_day.get(_eastern_day(kickoff), []):
            if abs((final["kickoff"] - kickoff).total_seconds()) > KICKOFF_TOLERANCE_HOURS * 3600:
                continue
            if home in final["home"] and away in final["away"]:
                hits.append((final["home_score"], final["away_score"]))
            elif home in final["away"] and away in final["home"]:
                # A neutral-site game listed the other way round.
                hits.append((final["away_score"], final["home_score"]))
        if len(hits) != 1:
            continue
        home_score, away_score = hits[0]
        match["status"] = "FINISHED"
        match["minute"] = None
        match["score"] = normalized_score(home_score, away_score, True)
        match["score_source"] = SOURCE_LABEL
        report["settled"] += 1
    return report
