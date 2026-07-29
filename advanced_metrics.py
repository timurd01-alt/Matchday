"""Pure, provider-neutral advanced metric derivations for shadow research.

No function in this module makes network requests.  Callers must supply data
obtained from an approved source and retain its provenance alongside outputs.
"""

from __future__ import annotations

import math
import re
from collections import defaultdict
from typing import Any, Iterable


def _number(value: Any, default: float | None = 0.0) -> float | None:
    try:
        number = float(value)
        return number if math.isfinite(number) else default
    except (TypeError, ValueError):
        return default


def _mean(values: Iterable[float]) -> float | None:
    clean = [float(value) for value in values if value is not None and math.isfinite(float(value))]
    return sum(clean) / len(clean) if clean else None


def _round(value: float | None, digits: int = 4) -> float | None:
    return round(value, digits) if value is not None and math.isfinite(value) else None


def nflverse_team_profiles(rows: Iterable[dict[str, Any]], min_plays: int = 50) -> dict[str, dict[str, Any]]:
    """Derive pregame NFL team profiles from nflverse play-by-play rows.

    EPA is from the offense's perspective. Defensive EPA is therefore EPA
    allowed. Explosive plays use a documented 20-yard pass / 10-yard rush
    threshold. Pace is measured only when `play_clock`-independent elapsed
    seconds (`time_of_possession` is not a play field) can be reconstructed
    from `game_seconds_remaining` between consecutive offensive snaps.
    """
    offense: dict[str, dict[str, Any]] = defaultdict(lambda: defaultdict(list))
    defense: dict[str, dict[str, Any]] = defaultdict(lambda: defaultdict(list))
    games_by_team: dict[str, set[str]] = defaultdict(set)
    drives: dict[tuple[str, str, str], dict[str, Any]] = {}
    clocks: dict[tuple[str, str], list[float]] = defaultdict(list)

    for raw in rows:
        team = str(raw.get("posteam") or "").strip()
        opponent = str(raw.get("defteam") or "").strip()
        game_id = str(raw.get("game_id") or "").strip()
        if not team or not opponent or not game_id:
            continue
        is_pass = _number(raw.get("pass_attempt"), 0) == 1
        is_rush = _number(raw.get("rush_attempt"), 0) == 1
        if not (is_pass or is_rush):
            continue
        epa = _number(raw.get("epa"), None)
        if epa is None:
            continue
        success = _number(raw.get("success"), None)
        if success is None:
            success = 1.0 if epa > 0 else 0.0
        yards = _number(raw.get("yards_gained"), 0) or 0.0
        explosive = 1.0 if (is_pass and yards >= 20) or (is_rush and yards >= 10) else 0.0
        early_down = 1.0 if int(_number(raw.get("down"), 0) or 0) in (1, 2) else 0.0

        offense[team]["epa"].append(epa)
        games_by_team[team].add(game_id)
        games_by_team[opponent].add(game_id)
        offense[team]["success"].append(success)
        offense[team]["explosive"].append(explosive)
        offense[team]["early_down"].append(early_down)
        defense[opponent]["epa_allowed"].append(epa)
        defense[opponent]["success_allowed"].append(success)
        defense[opponent]["explosive_allowed"].append(explosive)
        if is_pass:
            cpoe = _number(raw.get("cpoe"), None)
            if cpoe is not None:
                offense[team]["cpoe"].append(cpoe)

        drive = str(raw.get("fixed_drive") or raw.get("drive") or "").strip()
        if drive:
            key = (game_id, team, drive)
            record = drives.setdefault(key, {"epa": 0.0, "scored": False})
            record["epa"] += epa
            touchdown = _number(raw.get("touchdown"), 0) == 1
            field_goal = str(raw.get("field_goal_result") or "").lower() == "made"
            record["scored"] = bool(record["scored"] or touchdown or field_goal)

        remaining = _number(raw.get("game_seconds_remaining"), None)
        if remaining is not None:
            clocks[(game_id, team)].append(remaining)

    drive_by_team: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for (_game, team, _drive), record in drives.items():
        drive_by_team[team].append(record)

    pace_by_team: dict[str, list[float]] = defaultdict(list)
    for (_game, team), times in clocks.items():
        ordered = sorted(set(times), reverse=True)
        for before, after in zip(ordered, ordered[1:]):
            elapsed = before - after
            if 1 <= elapsed <= 60:
                pace_by_team[team].append(elapsed)

    profiles = {}
    for team in sorted(set(offense) | set(defense)):
        plays = len(offense[team]["epa"])
        if plays < min_plays:
            continue
        team_drives = drive_by_team.get(team, [])
        profiles[team] = {
            "plays": plays,
            "games": len(games_by_team[team]),
            "epa_per_play": _round(_mean(offense[team]["epa"])),
            "success_rate": _round(_mean(offense[team]["success"])),
            "cpoe": _round(_mean(offense[team]["cpoe"])),
            "explosive_play_rate": _round(_mean(offense[team]["explosive"])),
            "early_down_play_share": _round(_mean(offense[team]["early_down"])),
            "seconds_per_play": _round(_mean(pace_by_team.get(team, [])), 2),
            "epa_per_drive": _round(_mean(record["epa"] for record in team_drives)),
            "drive_score_rate": _round(_mean(float(record["scored"]) for record in team_drives)),
            "def_epa_allowed_per_play": _round(_mean(defense[team]["epa_allowed"])),
            "def_success_rate_allowed": _round(_mean(defense[team]["success_allowed"])),
            "def_explosive_rate_allowed": _round(_mean(defense[team]["explosive_allowed"])),
        }
    return profiles


def statsbomb_team_profiles(events: Iterable[dict[str, Any]], min_matches: int = 1) -> dict[str, dict[str, Any]]:
    """Aggregate StatsBomb Open Data events into coverage-aware team profiles."""
    stats: dict[str, dict[str, Any]] = defaultdict(lambda: defaultdict(float))
    matches: dict[str, set[str]] = defaultdict(set)
    match_teams: dict[str, set[str]] = defaultdict(set)
    possessions: dict[tuple[str, str], set[str]] = defaultdict(set)
    xg_by_match_team: dict[tuple[str, str], float] = defaultdict(float)

    buffered = list(events)
    for event in buffered:
        match_id = str(event.get("match_id") or event.get("match") or "unknown")
        team_obj = event.get("team") or {}
        team = str(team_obj.get("name") if isinstance(team_obj, dict) else team_obj or "").strip()
        if not team:
            continue
        matches[team].add(match_id)
        match_teams[match_id].add(team)
        event_type_obj = event.get("type") or {}
        event_type = str(event_type_obj.get("name") if isinstance(event_type_obj, dict) else event_type_obj).lower()
        possession_team_obj = event.get("possession_team") or {}
        possession_team = str(possession_team_obj.get("name") if isinstance(possession_team_obj, dict)
                              else possession_team_obj or team).strip()
        possession = str(event.get("possession") or "")
        if possession:
            possessions[(match_id, possession_team)].add(possession)
        location = event.get("location") or []
        if isinstance(location, list) and location and _number(location[0], 0) >= 80:
            stats[team]["final_third_events"] += 1
        stats[team]["events"] += 1
        if event_type == "pressure":
            stats[team]["pressures"] += 1
        if event_type == "pass":
            stats[team]["passes"] += 1
            pass_obj = event.get("pass") or {}
            if not pass_obj.get("outcome"):
                stats[team]["completed_passes"] += 1
        if event_type == "shot":
            shot = event.get("shot") or {}
            xg = _number(shot.get("statsbomb_xg"), 0) or 0.0
            stats[team]["shots"] += 1
            stats[team]["xg"] += xg
            xg_by_match_team[(match_id, team)] += xg
            shot_type = shot.get("type") or {}
            shot_type_name = str(shot_type.get("name") if isinstance(shot_type, dict) else shot_type).lower()
            if shot_type_name != "penalty":
                stats[team]["non_penalty_shots"] += 1
                stats[team]["non_penalty_xg"] += xg

    for match_id, teams in match_teams.items():
        if len(teams) != 2:
            continue
        first, second = sorted(teams)
        stats[first]["xg_against"] += xg_by_match_team[(match_id, second)]
        stats[second]["xg_against"] += xg_by_match_team[(match_id, first)]

    profiles = {}
    for team, values in stats.items():
        games = len(matches[team])
        if games < min_matches:
            continue
        team_possessions = sum(len(possessions[(match_id, team)]) for match_id in matches[team])
        all_possessions = sum(len(ids) for (match_id, _team), ids in possessions.items() if match_id in matches[team])
        profiles[team] = {
            "matches": games,
            "xg_for_per90": _round(values["xg"] / games),
            "xg_against_per90": _round(values["xg_against"] / games),
            "xg_difference_per90": _round((values["xg"] - values["xg_against"]) / games),
            "non_penalty_xg_per90": _round(values["non_penalty_xg"] / games),
            "xg_per_shot": _round(values["xg"] / values["shots"] if values["shots"] else None),
            "pressures_per90": _round(values["pressures"] / games, 2),
            "pass_completion_rate": _round(values["completed_passes"] / values["passes"] if values["passes"] else None),
            "final_third_event_share": _round(values["final_third_events"] / values["events"] if values["events"] else None),
            "possession_sequence_share": _round(team_possessions / all_possessions if all_possessions else None),
        }
    return profiles


def stats_for_match(events: Iterable[dict[str, Any]], match_id: str, team_name: str, metric: str) -> float:
    if metric != "xg":
        return 0.0
    total = 0.0
    for event in events:
        if str(event.get("match_id") or event.get("match") or "unknown") != match_id:
            continue
        team_obj = event.get("team") or {}
        team = str(team_obj.get("name") if isinstance(team_obj, dict) else team_obj or "").strip()
        type_obj = event.get("type") or {}
        event_type = str(type_obj.get("name") if isinstance(type_obj, dict) else type_obj).lower()
        if team == team_name and event_type == "shot":
            total += _number((event.get("shot") or {}).get("statsbomb_xg"), 0) or 0.0
    return total


def basketball_game_records(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalize complete paired basketball boxes into team-game metric rows."""
    by_game: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    duplicate_games: set[str] = set()
    for row in rows:
        game_id = str(row.get("game_id") if row.get("game_id") is not None else "").strip()
        team = str(row.get("team") or "").strip()
        if game_id and team:
            if team in by_game[game_id]:
                duplicate_games.add(game_id)
            by_game[game_id][team] = row
    records = []
    required = ("points", "fgm", "fga", "three_pm", "fta", "orb", "drb", "tov")
    for game_id, team_rows in by_game.items():
        if game_id in duplicate_games or len(team_rows) != 2:
            continue
        game_rows = list(team_rows.values())
        if any(_number(row.get(field), None) is None for row in game_rows for field in required):
            continue
        for row, opponent in ((game_rows[0], game_rows[1]), (game_rows[1], game_rows[0])):
            values = {field: _number(row.get(field), None) for field in required}
            opponent_values = {field: _number(opponent.get(field), None) for field in required}
            if any(value is None or value < 0 for value in (*values.values(), *opponent_values.values())):
                continue
            if (values["fgm"] > values["fga"] or values["three_pm"] > values["fgm"]
                    or opponent_values["fgm"] > opponent_values["fga"]
                    or opponent_values["three_pm"] > opponent_values["fgm"]):
                continue
            fga, fgm = values["fga"], values["fgm"]
            three_pm, fta = values["three_pm"], values["fta"]
            orb, tov, points = values["orb"], values["tov"], values["points"]
            opp_drb = opponent_values["drb"]
            own_possessions = fga - orb + tov + 0.44 * fta
            opponent_possessions = (opponent_values["fga"] - opponent_values["orb"]
                                    + opponent_values["tov"] + 0.44 * opponent_values["fta"])
            possessions = max(1.0, (own_possessions + opponent_possessions) / 2.0)
            three_pa = _number(row.get("three_pa"), None)
            date_value = str(row.get("game_date") or row.get("date") or row.get("kickoff") or "")[:10]
            is_home = row.get("is_home")
            if is_home is None and row.get("home_team"):
                is_home = str(row.get("home_team")) == str(row.get("team"))
            records.append({
                "game_id": game_id, "game_date": date_value,
                "team": str(row["team"]),
                "opponent": str(opponent.get("team") or row.get("opponent") or ""),
                "is_home": bool(is_home) if is_home is not None else None,
                "possessions": possessions,
                "off_rating": 100 * points / possessions,
                "def_rating": 100 * opponent_values["points"] / possessions,
                "efg": (fgm + 0.5 * three_pm) / fga if fga else None,
                "tov_rate": tov / possessions,
                "orb_rate": orb / (orb + opp_drb) if orb + opp_drb else None,
                "ft_rate": fta / fga if fga else None,
                "three_point_attempt_rate": (three_pa / fga if three_pa is not None and fga else None),
                "points": points, "opponent_points": opponent_values["points"],
            })
    return sorted(records, key=lambda item: (item["game_date"], item["game_id"], item["team"]))


def basketball_team_profiles(rows: Iterable[dict[str, Any]], min_games: int = 3) -> dict[str, dict[str, Any]]:
    """Derive tempo, efficiency and Dean Oliver's four factors from team-game boxes.

    Expected normalized fields: game_id, team, opponent, points, fgm, fga,
    three_pm, fta, orb, drb, tov. Two rows per game are required so offensive
    rebound percentage can use the opponent's defensive rebounds.
    """
    team_games: dict[str, list[dict[str, float]]] = defaultdict(list)
    for record in basketball_game_records(rows):
        team_games[record["team"]].append(record)
    league_rating = _mean(game["off_rating"] for games in team_games.values() for game in games) or 100.0
    offense = {team: (_mean(game["off_rating"] for game in games) or league_rating) - league_rating
               for team, games in team_games.items()}
    defense = {team: league_rating - (_mean(game["def_rating"] for game in games) or league_rating)
               for team, games in team_games.items()}
    # Alternating ridge updates estimate team attack and defense while
    # accounting for the opponents faced. Positive defense means stronger.
    for _ in range(20):
        next_offense, next_defense = {}, {}
        for team, games in team_games.items():
            shrink = len(games) / (len(games) + 5.0)
            off_values = [game["off_rating"] - league_rating + defense.get(game["opponent"], 0.0) for game in games]
            def_values = [league_rating - game["def_rating"] + offense.get(game["opponent"], 0.0) for game in games]
            next_offense[team] = (_mean(off_values) or 0.0) * shrink
            next_defense[team] = (_mean(def_values) or 0.0) * shrink
        offense, defense = next_offense, next_defense

    profiles = {}
    for team, games in team_games.items():
        if len(games) < min_games:
            continue
        profiles[team] = {"games": len(games)}
        for field in ("possessions", "off_rating", "def_rating", "efg", "tov_rate", "orb_rate", "ft_rate",
                      "three_point_attempt_rate"):
            profiles[team][field] = _round(_mean(game[field] for game in games))
        profiles[team]["tempo"] = profiles[team]["possessions"]
        profiles[team]["net_rating"] = _round(profiles[team]["off_rating"] - profiles[team]["def_rating"])
        profiles[team]["adjusted_off_rating"] = _round(league_rating + offense.get(team, 0.0))
        profiles[team]["adjusted_def_rating"] = _round(league_rating - defense.get(team, 0.0))
        profiles[team]["adjusted_net_rating"] = _round(offense.get(team, 0.0) + defense.get(team, 0.0))
        opponents = [game["opponent"] for game in games]
        profiles[team]["schedule_strength"] = _round(_mean(
            offense.get(opponent, 0.0) + defense.get(opponent, 0.0) for opponent in opponents))
        profiles[team]["coverage"] = {
            "complete_paired_games": len(games),
            "unique_opponents": len(set(opponents)),
            "observed_through": max((game.get("game_date") or "" for game in games), default="") or None,
            "three_point_attempt_games": sum(game.get("three_point_attempt_rate") is not None for game in games),
        }
    return profiles


def cfbd_advanced_team_profiles(rows: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Normalize CollegeFootballData `/stats/season/advanced` output."""
    profiles = {}
    for row in rows:
        team = str(row.get("team") or "").strip()
        if not team:
            continue
        offense = row.get("offense") or {}
        defense = row.get("defense") or {}
        profiles[team] = {
            "plays": int(_number(offense.get("plays"), 0) or 0),
            "drives": int(_number(offense.get("drives"), 0) or 0),
            "ppa": _round(_number(offense.get("ppa"), None)),
            "success_rate": _round(_number(offense.get("successRate"), None)),
            "explosiveness": _round(_number(offense.get("explosiveness"), None)),
            "line_yards": _round(_number(offense.get("lineYards"), None)),
            "power_success": _round(_number(offense.get("powerSuccess"), None)),
            "stuff_rate": _round(_number(offense.get("stuffRate"), None)),
            "def_ppa_allowed": _round(_number(defense.get("ppa"), None)),
            "def_success_rate_allowed": _round(_number(defense.get("successRate"), None)),
            "def_explosiveness_allowed": _round(_number(defense.get("explosiveness"), None)),
        }
    return profiles


def retrosheet_event_profiles(lines: Iterable[str], min_plate_appearances: int = 100) -> dict[str, dict[str, Any]]:
    """Derive simple outcome-rate profiles from Retrosheet event files.

    This deliberately parses only stable event-code prefixes. It does not try
    to reconstruct runs, base states, or Statcast-like batted-ball quality.
    """
    totals: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    away = home = None
    for raw in lines:
        line = raw.strip()
        if line.startswith("id,"):
            away = home = None
            continue
        if line.startswith("info,visteam,"):
            away = line.split(",", 2)[2]
            continue
        if line.startswith("info,hometeam,"):
            home = line.split(",", 2)[2]
            continue
        if not line.startswith("play,") or not away or not home:
            continue
        fields = line.split(",", 6)
        if len(fields) < 7:
            continue
        side, event = fields[2], fields[6].split(".", 1)[0]
        team = away if side == "0" else home
        if not team or event in {"NP", "BK", "DI", "OA"}:
            continue
        totals[team]["pa"] += 1
        primary = event.split("/", 1)[0]
        if re.match(r"^K(?!E)", primary):
            totals[team]["strikeouts"] += 1
        if re.match(r"^(W|IW|HP)", primary):
            totals[team]["free_passes"] += 1
        if re.match(r"^(S(?!B)|D(?!I)|T|HR)", primary):
            totals[team]["hits"] += 1
        if primary.startswith("HR"):
            totals[team]["home_runs"] += 1
    profiles = {}
    for team, values in totals.items():
        pa = int(values["pa"])
        if pa < min_plate_appearances:
            continue
        profiles[team] = {
            "plate_appearances": pa,
            "strikeout_rate": _round(values["strikeouts"] / pa),
            "free_pass_rate": _round(values["free_passes"] / pa),
            "hit_rate": _round(values["hits"] / pa),
            "home_run_rate": _round(values["home_runs"] / pa),
            "contact_proxy": _round(1 - values["strikeouts"] / pa),
        }
    return profiles
