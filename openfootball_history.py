"""Pinned CC0 OpenFootball domestic-league history importer.

The importer is intentionally offline: point it at a git checkout whose HEAD
matches ``PINNED_REVISION``. It never scrapes websites or follows a moving
branch, and its normalized output remains research-only until overlap and
prospective model gates are reviewed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from soccer_elo_challenger import normalize_team


SOURCE_REPOSITORY = "https://github.com/openfootball/football.json"
PINNED_REVISION = "a5dd38b3bcbe3aa2477cf400f569264253d51431"
LICENSE = "CC0-1.0"
LEAGUES = {
    "EPL": "en.1.json",
    "BUNDESLIGA": "de.1.json",
    "LALIGA": "es.1.json",
    "SERIEA": "it.1.json",
    "LIGUE1": "fr.1.json",
}
SEASONS = tuple(f"{year}-{str(year + 1)[-2:]}" for year in range(2010, 2026))


def _checkout_revision(root: Path) -> str | None:
    git_dir = root / ".git"
    try:
        head = (git_dir / "HEAD").read_text(encoding="utf-8").strip()
        if head.startswith("ref: "):
            ref = head.removeprefix("ref: ")
            loose = git_dir / ref
            if loose.is_file():
                return loose.read_text(encoding="utf-8").strip()
            for line in (git_dir / "packed-refs").read_text(encoding="utf-8").splitlines():
                if line and not line.startswith(("#", "^")):
                    revision, name = line.split(" ", 1)
                    if name == ref:
                        return revision
            return None
        return head
    except (OSError, ValueError):
        return None


def verify_checkout(root: str | Path, *, revision: str = PINNED_REVISION) -> Path:
    source = Path(root)
    actual = _checkout_revision(source)
    if actual != revision:
        raise ValueError(f"OpenFootball checkout must be pinned to {revision}; found {actual or 'no git revision'}")
    license_text = (source / "LICENSE.md").read_text(encoding="utf-8")
    if "CC0" not in license_text and "public domain" not in license_text.lower():
        raise ValueError("OpenFootball checkout does not carry the expected CC0/public-domain notice")
    return source


def _score(value: Any) -> tuple[int, int] | None:
    if isinstance(value, dict):
        value = value.get("ft")
    if not isinstance(value, list) or len(value) != 2:
        return None
    if not all(isinstance(item, int) and 0 <= item <= 30 for item in value):
        raise ValueError(f"implausible full-time score: {value!r}")
    return value[0], value[1]


def parse_file(path: str | Path, competition: str, season: str) -> list[dict[str, Any]]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    matches = payload.get("matches") if isinstance(payload, dict) else None
    if not isinstance(matches, list):
        raise ValueError(f"{path} has no matches array")
    rows = []
    seen = set()
    for item in matches:
        if not isinstance(item, dict):
            raise ValueError(f"{path} contains a non-object match")
        score = _score(item.get("score"))
        if score is None:  # scheduled/incomplete record; historical model must not infer it
            continue
        home, away = str(item.get("team1") or "").strip(), str(item.get("team2") or "").strip()
        day = str(item.get("date") or "").strip()
        if not day or not home or not away or normalize_team(home) == normalize_team(away):
            raise ValueError(f"invalid fixture identity in {path}: {item!r}")
        material = f"{competition}|{season}|{day}|{normalize_team(home)}|{normalize_team(away)}"
        fixture_id = "openfootball-" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]
        if fixture_id in seen:
            raise ValueError(f"duplicate OpenFootball fixture in {path}: {material}")
        seen.add(fixture_id)
        home_score, away_score = score
        winner = "h" if home_score > away_score else "a" if away_score > home_score else "d"
        rows.append({
            "id": fixture_id,
            "competition": competition,
            "season": int(season[:4]),
            "kickoff": f"{day}T12:00:00Z",
            "status": "FINISHED",
            "stage": item.get("round"),
            "home": {"name": home},
            "away": {"name": away},
            "score": {"home": home_score, "away": away_score, "winner": winner},
            "source": {
                "name": "OpenFootball",
                "repository": SOURCE_REPOSITORY,
                "revision": PINNED_REVISION,
                "license": LICENSE,
                "source_file": f"{season}/{LEAGUES[competition]}",
                "research_only": True,
            },
        })
    return rows


def load_checkout(root: str | Path, seasons=SEASONS, competitions=tuple(LEAGUES)) -> list[dict[str, Any]]:
    source = verify_checkout(root)
    rows = []
    identities = set()
    files_by_competition = {competition: 0 for competition in competitions}
    for season in seasons:
        for competition in competitions:
            filename = LEAGUES[competition]
            path = source / season / filename
            if not path.is_file():
                continue
            files_by_competition[competition] += 1
            parsed = parse_file(path, competition, season)
            for row in parsed:
                if row["id"] in identities:
                    raise ValueError(f"duplicate fixture across files: {row['id']}")
                identities.add(row["id"])
            rows.extend(parsed)
    too_thin = {competition: count for competition, count in files_by_competition.items() if count < 5}
    if too_thin:
        raise ValueError(f"OpenFootball coverage is too thin for research: {too_thin}")
    return sorted(rows, key=lambda row: (row["kickoff"], row["competition"], row["id"]))


def write_cache(path: str | Path, rows: list[dict[str, Any]]) -> dict[str, Any]:
    raw_rows = json.dumps(rows, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    payload = {
        "schema_version": 1,
        "source": "OpenFootball pinned CC0 history",
        "source_repository": SOURCE_REPOSITORY,
        "source_revision": PINNED_REVISION,
        "license": LICENSE,
        "research_only": True,
        "row_count": len(rows),
        "rows_sha256": hashlib.sha256(raw_rows.encode("utf-8")).hexdigest(),
        "rows": rows,
    }
    target = Path(path)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(target)
    return payload


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkout", required=True, help="local checkout at the pinned revision")
    parser.add_argument("--output", default="openfootball_soccer_history_cache.json")
    args = parser.parse_args(argv)
    payload = write_cache(args.output, load_checkout(args.checkout))
    print(f"OpenFootball: {payload['row_count']} validated results at {payload['source_revision']}")
    print(f"rows sha256: {payload['rows_sha256']}")


if __name__ == "__main__":
    main()
