"""Sport-aware pregame readiness and zero-weight research context.

This module deliberately separates *collecting* late information from using it
in production probabilities.  Newly introduced personnel fields remain shadow
features until Matchday's prospective promotion checks show an improvement.
"""

import datetime as dt


LOCK_WINDOWS_HOURS = {
    "MLB": 2.0,
    "NBA": 2.0,
    "NFL": 2.0,
    "NHL": 2.0,
    "NCAAF": 3.0,
    "NCAAM": 3.0,
    "WC": 2.0,
    "UCL": 2.0,
    "EPL": 2.0,
    "LALIGA": 2.0,
    "SERIEA": 2.0,
    "BUNDESLIGA": 2.0,
    "LIGUE1": 2.0,
}

SPORT_INPUTS = {
    "baseball": ("market", "injuries", "starting_pitchers", "lineups", "bullpen", "weather", "venue"),
    "basketball": ("market", "injuries", "lineups", "rotation"),
    "football": ("market", "injuries", "key_players", "weather"),
    "soccer": ("market", "injuries", "lineups", "weather"),
    "hockey": ("market", "injuries", "starting_goalies", "lineups"),
}

CRITICAL_INPUTS = {
    "baseball": {"market", "starting_pitchers", "lineups"},
    "basketball": {"market", "injuries", "lineups"},
    "football": {"market", "injuries", "key_players"},
    "soccer": {"market", "injuries", "lineups"},
    "hockey": {"market", "injuries", "starting_goalies"},
}


def lock_window_hours(competition):
    return float(LOCK_WINDOWS_HOURS.get(str(competition or "").upper(), 2.0))


def _parse_time(value):
    try:
        parsed = dt.datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(dt.timezone.utc)


def _has_sides(value):
    return isinstance(value, dict) and any(value.get(side) for side in ("home", "away"))


def _lineups_confirmed(lineups):
    if not isinstance(lineups, dict):
        return False
    if lineups.get("confirmed") is True:
        return True
    sides = [lineups.get(side) for side in ("home", "away")]
    return bool(sides) and all(isinstance(side, dict) and
                               (side.get("confirmed") is True or
                                str(side.get("status") or "").lower() == "confirmed")
                               for side in sides)


def _status(match, key):
    personnel = match.get("personnel") or {}
    if key == "market":
        market = (match.get("markets") or {}).get("1x2") or match.get("markets") or {}
        available = market.get("home_pct") is not None
        confirmed = available
    elif key == "injuries":
        available = (_has_sides(match.get("injuries")) or
                     bool(personnel.get("injuries_feed_checked")))
        confirmed = available and bool(personnel.get("injuries_confirmed"))
    elif key == "lineups":
        lineups = match.get("lineups")
        available = _has_sides(lineups)
        confirmed = available and _lineups_confirmed(lineups)
    elif key == "weather":
        available = bool(match.get("weather"))
        confirmed = available
    elif key == "venue":
        available = bool(match.get("venue_context") or match.get("venue"))
        confirmed = available
    else:
        value = personnel.get(key)
        available = bool(value)
        confirmed = available and bool(personnel.get(f"{key}_confirmed"))
    return "confirmed" if confirmed else "available" if available else "missing"


def build_pregame_context(match, competition, sport, now=None):
    """Attach transparent readiness/missingness metadata to one fixture."""
    current = now or dt.datetime.now(dt.timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=dt.timezone.utc)
    kickoff = _parse_time(match.get("kickoff"))
    lead_hours = ((kickoff - current.astimezone(dt.timezone.utc)).total_seconds() / 3600
                  if kickoff else None)
    window = lock_window_hours(competition)
    inputs = {key: _status(match, key) for key in SPORT_INPUTS.get(sport, ("market", "injuries"))}
    critical = CRITICAL_INPUTS.get(sport, {"market", "injuries"})
    missing_critical = [key for key in inputs if key in critical and inputs[key] == "missing"]
    unconfirmed_critical = [key for key in inputs if key in critical and inputs[key] != "confirmed"]
    confirmed = sum(value == "confirmed" for value in inputs.values())
    available = sum(value != "missing" for value in inputs.values())
    if str(match.get("status") or "").upper() != "UPCOMING":
        phase = "closed"
    elif lead_hours is None or lead_hours > window:
        phase = "preliminary"
    elif lead_hours >= 0:
        phase = "lock_window"
    else:
        phase = "closed"
    provenance = match.get("pregame_provenance") or []
    context = {
        "schema_ver": 1,
        "sport": sport,
        "competition": competition,
        "phase": phase,
        "lock_window_hours": window,
        "lead_time_hours": round(lead_hours, 2) if lead_hours is not None else None,
        "inputs": inputs,
        "missing_critical": missing_critical,
        "unconfirmed_critical": unconfirmed_critical,
        "coverage_pct": round(100 * available / max(1, len(inputs))),
        "confirmed_pct": round(100 * confirmed / max(1, len(inputs))),
        "provenance": provenance,
        "confidence_guard": {
            "high_confidence_label_allowed": not unconfirmed_critical,
            "reason": (None if not unconfirmed_critical else
                       "critical pregame inputs not confirmed"),
        },
        "production_weight": 0,
        "research_mode": "prospective_shadow",
    }
    match["pregame_context"] = context
    return context


def attach_pregame_context(matches, competition, sport, now=None):
    counts = {"preliminary": 0, "lock_window": 0, "closed": 0}
    for match in matches:
        context = build_pregame_context(match, competition, sport, now)
        counts[context["phase"]] = counts.get(context["phase"], 0) + 1
    return counts


def attach_personnel_shadows(matches, sport):
    """Freeze collected sport-native fields for prospective, zero-weight tests."""
    attached = 0
    for match in matches:
        personnel = match.get("personnel") or {}
        injuries = match.get("injuries") or {}
        lineups = match.get("lineups") or {}
        fields = {
            "injury_counts": {side: len(injuries.get(side) or []) for side in ("home", "away")},
            "lineup_counts": {side: len((lineups.get(side) or {}).get("xi") or [])
                              for side in ("home", "away")},
            "lineups_confirmed": _lineups_confirmed(lineups),
            "rest_days": {side: (match.get(side) or {}).get("rest_days") for side in ("home", "away")},
            "weather": match.get("weather"),
            "venue_context": match.get("venue_context"),
        }
        for key in ("starting_pitchers", "bullpen", "rotation", "key_players", "starting_goalies"):
            if personnel.get(key):
                fields[key] = personnel[key]
        match["personnel_shadow"] = {
            "schema_ver": 1, "sport": sport, "production_weight": 0,
            "mode": "prospective_shadow", "features": fields,
        }
        attached += 1
    return attached


def derive_venue_context(matches, history, sport):
    """Create a leakage-safe, shrunken venue scoring context from prior finals."""
    completed = []
    by_venue = {}
    for match in history or ():
        if match.get("status") != "FINISHED":
            continue
        score = match.get("score") or {}
        try:
            total = float(score.get("home")) + float(score.get("away"))
        except (TypeError, ValueError):
            continue
        kickoff = _parse_time(match.get("kickoff"))
        venue = str(match.get("venue") or "").strip().lower()
        if kickoff and venue:
            completed.append((kickoff, venue, total))
    for target in matches:
        venue = str(target.get("venue") or "").strip().lower()
        kickoff = _parse_time(target.get("kickoff"))
        prior = [total for when, ground, total in completed
                 if venue and ground == venue and (not kickoff or when < kickoff)]
        league_prior = [total for when, _, total in completed if not kickoff or when < kickoff]
        if not league_prior:
            continue
        league_avg = sum(league_prior) / len(league_prior)
        # Ten-game prior prevents one unusual series/fixture from defining a park.
        venue_avg = ((sum(prior) + 10 * league_avg) / (len(prior) + 10)) if prior else league_avg
        target["venue_context"] = {
            "sample_games": len(prior),
            "league_total_avg": round(league_avg, 3),
            "venue_total_avg": round(venue_avg, 3),
            "factor": round(venue_avg / league_avg, 4) if league_avg else 1.0,
            "label": "park factor" if sport == "baseball" else "venue scoring context",
            "production_weight": 0,
            "method": "prior finals, 10-game shrinkage",
        }
        by_venue[venue] = len(prior)
    return {"matches": sum(bool(m.get("venue_context")) for m in matches), "venues": len(by_venue)}
