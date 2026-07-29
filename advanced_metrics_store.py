"""Load approved derived profiles and attach them to fixtures as shadow data."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


NFL_ALIASES = {
    "ARI": "Arizona Cardinals", "ATL": "Atlanta Falcons", "BAL": "Baltimore Ravens",
    "BUF": "Buffalo Bills", "CAR": "Carolina Panthers", "CHI": "Chicago Bears",
    "CIN": "Cincinnati Bengals", "CLE": "Cleveland Browns", "DAL": "Dallas Cowboys",
    "DEN": "Denver Broncos", "DET": "Detroit Lions", "GB": "Green Bay Packers",
    "HOU": "Houston Texans", "IND": "Indianapolis Colts", "JAX": "Jacksonville Jaguars",
    "JAC": "Jacksonville Jaguars", "KC": "Kansas City Chiefs", "LA": "Los Angeles Rams",
    "LAR": "Los Angeles Rams", "LAC": "Los Angeles Chargers", "LV": "Las Vegas Raiders",
    "MIA": "Miami Dolphins", "MIN": "Minnesota Vikings", "NE": "New England Patriots",
    "NO": "New Orleans Saints", "NYG": "New York Giants", "NYJ": "New York Jets",
    "PHI": "Philadelphia Eagles", "PIT": "Pittsburgh Steelers", "SEA": "Seattle Seahawks",
    "SF": "San Francisco 49ers", "TB": "Tampa Bay Buccaneers", "TEN": "Tennessee Titans",
    "WAS": "Washington Commanders",
}

MLB_ALIASES = {
    "ARI": "Arizona Diamondbacks", "ATL": "Atlanta Braves", "BAL": "Baltimore Orioles",
    "BOS": "Boston Red Sox", "CHA": "Chicago White Sox", "CHN": "Chicago Cubs",
    "CIN": "Cincinnati Reds", "CLE": "Cleveland Guardians", "COL": "Colorado Rockies",
    "DET": "Detroit Tigers", "HOU": "Houston Astros", "KCA": "Kansas City Royals",
    "ANA": "Los Angeles Angels", "LAA": "Los Angeles Angels", "LAN": "Los Angeles Dodgers", "MIA": "Miami Marlins",
    "MIL": "Milwaukee Brewers", "MIN": "Minnesota Twins", "NYA": "New York Yankees",
    "NYN": "New York Mets", "OAK": "Oakland Athletics", "ATH": "Oakland Athletics",
    "PHI": "Philadelphia Phillies", "PIT": "Pittsburgh Pirates", "SDN": "San Diego Padres",
    "SEA": "Seattle Mariners", "SFN": "San Francisco Giants", "SLN": "St. Louis Cardinals",
    "TBA": "Tampa Bay Rays", "TEX": "Texas Rangers", "TOR": "Toronto Blue Jays",
    "WAS": "Washington Nationals",
}


def normalize_team(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def load_profile_file(path: str | Path) -> dict[str, Any] | None:
    source = Path(path)
    if not source.exists():
        return None
    payload = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise ValueError(f"unsupported advanced metrics schema: {source}")
    if payload.get("shadow_only") is not True or not isinstance(payload.get("profiles"), dict):
        raise ValueError(f"advanced metrics must be explicit shadow profiles: {source}")
    provider = str(payload.get("source") or "")
    if "espn" in provider.lower():
        raise ValueError(f"ESPN-origin advanced metrics are prohibited: {source}")
    return payload


def _candidate_files(competition: str, sport: str, directory: str | Path = ".") -> list[Path]:
    root = Path(directory)
    names = [f"advanced_metrics_{competition.lower()}.json"]
    generic = f"advanced_metrics_{sport.lower()}.json"
    if generic not in names:
        names.append(generic)
    return [root / name for name in names]


def attach_shadow_profiles(matches, competition: str, sport: str, directory: str | Path = ".") -> dict[str, Any]:
    for match in matches:
        match["research_signal_schema"] = 1
    payload = None
    selected = None
    for candidate in _candidate_files(competition, sport, directory):
        payload = load_profile_file(candidate)
        if payload:
            if payload.get("attach_live", True) is not True:
                payload = None
                continue
            selected = candidate
            break
    if not payload:
        return {"file": None, "matches": 0, "teams": 0}

    aliases = NFL_ALIASES if competition == "NFL" else MLB_ALIASES if competition == "MLB" else {}
    index = {}
    for name, profile in payload["profiles"].items():
        index[normalize_team(name)] = profile
        if str(name).upper() in aliases:
            index[normalize_team(aliases[str(name).upper()])] = profile
    attached_matches = 0
    attached_teams = 0
    for match in matches:
        sides = {}
        for side in ("home", "away"):
            team = (match.get(side) or {}).get("name")
            profile = index.get(normalize_team(team))
            if profile is not None:
                sides[side] = profile
                attached_teams += 1
        if sides:
            match["advanced_metrics"] = sides
            match["advanced_metrics_meta"] = {
                "schema_version": payload["schema_version"],
                "source": payload.get("source"),
                "license": payload.get("license"),
                "generated_at": payload.get("generated_at"),
                "coverage": payload.get("coverage"),
                "shadow_only": True,
                "production_weight": 0,
                "profile_file": selected.name if selected else None,
            }
            attached_matches += 1
    return {"file": str(selected) if selected else None, "matches": attached_matches, "teams": attached_teams}
