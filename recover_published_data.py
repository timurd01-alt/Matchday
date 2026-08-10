"""Restore first-party published fixture snapshots after a cold CI cache miss."""

from __future__ import annotations

import json
import os
import datetime
from pathlib import Path
import urllib.request


PUBLIC_DATA_ORIGIN = "https://matchdayterminal.com"
SPORT_KEYS = (
    "default", "wc", "epl", "laliga", "seriea", "bundesliga", "ligue1", "ucl",
    "nfl", "ncaaf", "ncaam", "nba", "mlb",
)
MAX_DOWNLOAD_BYTES = 25 * 1024 * 1024


def valid_payload(payload, key):
    if not isinstance(payload, dict):
        return False
    expected_comp = str(payload.get("comp_key", "")).upper()
    return ((bool(expected_comp) if key == "default" else expected_comp == key.upper())
            and isinstance(payload.get("updated"), str)
            and isinstance(payload.get("matches"), list))


def read_valid(path, key):
    try:
        return valid_payload(json.loads(path.read_text(encoding="utf-8")), key)
    except Exception:
        return False


def recover_one(root, key, opener=urllib.request.urlopen):
    root = Path(root)
    filename = "data.json" if key == "default" else f"data_{key}.json"
    target = root / filename
    if read_valid(target, key):
        return "present"
    request = urllib.request.Request(
        f"{PUBLIC_DATA_ORIGIN}/{filename}",
        headers={"User-Agent": "Matchday-CI-Last-Good-Recovery/1.0"},
    )
    with opener(request, timeout=30) as response:
        raw = response.read(MAX_DOWNLOAD_BYTES + 1)
    if len(raw) > MAX_DOWNLOAD_BYTES:
        raise ValueError(f"published {filename} exceeds recovery size limit")
    payload = json.loads(raw.decode("utf-8"))
    if not valid_payload(payload, key):
        raise ValueError(f"published {filename} failed structural validation")
    recovered_at = datetime.datetime.now(datetime.timezone.utc)
    snapshot_updated = payload.get("updated")
    try:
        source_time = datetime.datetime.fromisoformat(snapshot_updated.replace("Z", "+00:00"))
        if source_time.tzinfo is None:
            source_time = source_time.replace(tzinfo=datetime.timezone.utc)
        fallback_age_hours = max(0.0, (recovered_at - source_time).total_seconds() / 3600)
    except (AttributeError, TypeError, ValueError):
        fallback_age_hours = None
    payload["source_freshness"] = {
        "state": "fallback",
        "generated_at": payload.get("updated"),
        "last_successful_at": payload.get("updated"),
        "recovered_at": recovered_at.isoformat(timespec="seconds"),
        "fallback_age_hours": (round(fallback_age_hours, 1)
                               if fallback_age_hours is not None else None),
        "note": "Validated last-good public snapshot; the current provider refresh did not replace it.",
    }
    temporary = target.with_suffix(target.suffix + ".recover.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, target)
    return "recovered"


def recover(root=".", keys=SPORT_KEYS, opener=urllib.request.urlopen):
    result = {"present": [], "recovered": [], "failed": {}}
    for key in keys:
        try:
            outcome = recover_one(root, key, opener=opener)
            result[outcome].append(key)
        except Exception as exc:
            result["failed"][key] = str(exc)
    return result


def main():
    result = recover()
    if result["recovered"]:
        print("Recovered published last-good fixtures: " + ", ".join(result["recovered"]))
    if result["present"]:
        print("Last-good fixtures already present: " + ", ".join(result["present"]))
    for key, error in result["failed"].items():
        print(f"Published last-good recovery unavailable for {key}: {error}")


if __name__ == "__main__":
    main()
