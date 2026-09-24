"""Keep the NCAAF schedule moving while CollegeFootballData is dark.

CFBD's monthly allowance runs out, and when the college bundle cache is gone as
well, `fetch_college_bundle()` had nothing to fall back to: the build raised,
multi_fetch reported "exited 0 but never rewrote data_ncaaf.json", and the
payload froze -- 243 hours on 2026-09-23, with 41 of that week's games still
carrying the midnight-Eastern placeholder CFBD uses before a kickoff time is
announced.

Two pieces, both public facts only (owner decision 2026-09-23 in
PROVIDER_COMPLIANCE.md: ESPN's public schedule and score facts are allowed):

* `last_good_bundle()` rebuilds the bundle from the last published payload,
  which CI always keeps, so the build runs instead of raising. The engine
  handoff's settled 2026 results supply the training history the payload's
  short display window lacks.
* `refresh_kickoffs()` asks ESPN's public scoreboard for the kickoff time of
  fixtures already on Matchday's schedule. It never adds a fixture, and it only
  writes a time ESPN marks as valid (`timeValid`), so a placeholder is never
  swapped for another placeholder.
"""

from __future__ import annotations

import datetime as dt
import json
import os
from typing import Any, Callable, Iterable

import score_fallback

# Upcoming fixtures further out than this are left alone: their times are
# mostly unannounced anyway, and each distinct game day costs one request.
LOOKAHEAD_DAYS = 9
SOURCE_LABEL = "ESPN scoreboard (kickoff time only)"

# The fields a raw CFBD fixture carries. Everything else on a published match
# is derived by the build and is recomputed from these.
_CORE_FIELDS = ("id", "provider_id", "stage", "venue", "kickoff", "status", "minute",
                "score", "data_source", "score_source")
_TEAM_FIELDS = ("name", "code", "group")


def _core(match: dict[str, Any]) -> dict[str, Any]:
    out = {key: match.get(key) for key in _CORE_FIELDS if key in match}
    for side in ("home", "away"):
        team = match.get(side) or {}
        out[side] = {key: team.get(key) for key in _TEAM_FIELDS}
        out[side].update({"pts": None, "gd": None, "form": "", "pos": None})
    out.update({"markets": {}, "lineups": None, "h2h": [],
                "injuries": {"home": [], "away": []}})
    return out


def _known_names(matches: Iterable[dict[str, Any]]) -> dict[str, str]:
    from betbetter_handoff import _normalize
    names = {}
    for match in matches:
        for side in ("home", "away"):
            name = (match.get(side) or {}).get("name")
            if name:
                names[_normalize(name)] = name
    return names


def _schedule_name(engine_name: str, known: dict[str, str]) -> str | None:
    """The schedule's own spelling of an engine team name, when exactly one fits."""
    from betbetter_handoff import _compatible, _normalize
    key = _normalize(engine_name)
    if key in known:
        return known[key]
    hits = {name for norm, name in known.items() if _compatible(norm, key)}
    return hits.pop() if len(hits) == 1 else None


def history_from_handoff(document: dict[str, Any] | None, comp: str,
                         known: dict[str, str]) -> list[dict[str, Any]]:
    """The engine's settled results as finished fixtures under schedule names.

    A result whose teams do not both resolve to one schedule name is dropped:
    a rating fed a misattributed game is worse than one fed one game fewer.
    """
    from provider_adapters import normalized_score
    rows = []
    for result in (document or {}).get("results") or []:
        if str(result.get("sport") or "").lower() != comp.lower():
            continue
        home = _schedule_name(str(result.get("home") or ""), known)
        away = _schedule_name(str(result.get("away") or ""), known)
        try:
            home_score, away_score = int(result["home_score"]), int(result["away_score"])
        except (KeyError, TypeError, ValueError):
            continue
        if not home or not away or home == away:
            continue
        rows.append({
            "id": f"bb-{result.get('event_id')}", "kickoff": result.get("kickoff") or result.get("played_on"),
            "status": "FINISHED", "minute": None,
            "score": normalized_score(home_score, away_score, True),
            "home": {"name": home}, "away": {"name": away},
            "neutral": bool(result.get("neutral")), "data_source": "Bet Better results",
        })
    return rows


def last_good_bundle(comp: str, data_path: str | None = None,
                     handoff_path: str = "betbetter_picks.json") -> dict[str, Any] | None:
    """A college bundle rebuilt from the last published payload, or None."""
    data_path = data_path or f"data_{comp.lower()}.json"
    try:
        with open(data_path, encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError):
        return None
    matches = [_core(match) for match in payload.get("matches") or []
               if isinstance(match, dict) and match.get("home") and match.get("away")]
    if not matches:
        return None
    document = None
    if os.path.exists(handoff_path):
        try:
            import betbetter_handoff
            document = betbetter_handoff.load(handoff_path)
        except Exception:
            document = None
    history = history_from_handoff(document, comp, _known_names(matches))
    seen = {(m["home"]["name"], m["away"]["name"], str(m.get("kickoff") or "")[:10])
            for m in matches}
    history = [row for row in history
               if (row["home"]["name"], row["away"]["name"], str(row["kickoff"] or "")[:10]) not in seen]
    return {"matches": matches, "history": history, "standings_model": {},
            "tables": payload.get("standings") or [], "rankings": [], "projection": None,
            "fallback": "last_good_payload"}


def _kickoffs(payload) -> list[dict[str, Any]]:
    """Scheduled games from one scoreboard: announced kickoff and names only."""
    games = []
    for event in (payload or {}).get("events") or []:
        for competition in event.get("competitions") or []:
            if competition.get("timeValid") is False:
                continue
            sides = {c.get("homeAway"): c for c in competition.get("competitors") or []}
            home, away = sides.get("home"), sides.get("away")
            kickoff = score_fallback._parse(competition.get("date") or event.get("date"))
            if not home or not away or kickoff is None:
                continue

            def names(side):
                team = side.get("team") or {}
                return {score_fallback._fold(team.get(key)) for key in
                        ("location", "displayName", "shortDisplayName")} - {""}

            games.append({"kickoff": kickoff, "home": names(home), "away": names(away)})
    return games


def refresh_kickoffs(matches: list[dict[str, Any]], comp: str,
                     now: dt.datetime | None = None,
                     fetch: Callable[[str], Any] = score_fallback._fetch) -> dict[str, Any]:
    """Write announced kickoff times onto upcoming fixtures in place."""
    template = score_fallback.SCOREBOARD.get(comp)
    report = {"candidates": 0, "updated": 0, "days": 0, "errors": []}
    if not template:
        return report
    now = now or dt.datetime.now(dt.timezone.utc)
    horizon = now + dt.timedelta(days=LOOKAHEAD_DAYS)
    pending = []
    for match in matches or []:
        if match.get("status") != "UPCOMING":
            continue
        kickoff = score_fallback._parse(match.get("kickoff"))
        if kickoff is not None and now < kickoff <= horizon:
            pending.append((match, kickoff))
    report["candidates"] = len(pending)
    by_day: dict[str, list[dict[str, Any]]] = {}
    for day in sorted({score_fallback._eastern_day(k) for _, k in pending}):
        try:
            by_day[day] = _kickoffs(fetch(template.format(day=day)))
            report["days"] += 1
        except Exception as exc:
            report["errors"].append(f"{day}: {exc}")
    for match, kickoff in pending:
        home = score_fallback._fold((match.get("home") or {}).get("name"))
        away = score_fallback._fold((match.get("away") or {}).get("name"))
        hits = [game["kickoff"] for game in by_day.get(score_fallback._eastern_day(kickoff), [])
                if (home in game["home"] and away in game["away"])
                or (home in game["away"] and away in game["home"])]
        if len(hits) != 1:
            continue
        announced = hits[0].astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        if announced != match.get("kickoff"):
            match["kickoff"] = announced
            match["kickoff_source"] = SOURCE_LABEL
            report["updated"] += 1
    return report
