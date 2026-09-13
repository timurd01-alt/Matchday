"""Load approved derived profiles and attach them to fixtures as shadow data."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


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

    index = {normalize_team(name): profile for name, profile in payload["profiles"].items()}
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
