"""Small, fail-closed AP Top 25 refresh from ESPN's public scoreboard.

Only the published rank and team name are retained.  The raw response is never
written, and an incomplete poll never replaces the last complete snapshot.
"""

from __future__ import annotations

import datetime as dt
import json
import pathlib
import urllib.parse
import urllib.request


SNAPSHOT = pathlib.Path("ap_poll_snapshot.json")
SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/football/college-football/scoreboard"


def _download(day: dt.date) -> dict:
    query = urllib.parse.urlencode({"dates": day.strftime("%Y%m%d"), "groups": "80", "limit": "300"})
    with urllib.request.urlopen(f"{SCOREBOARD}?{query}", timeout=15) as response:
        return json.load(response)


def extract(payloads: list[dict]) -> list[dict]:
    by_rank: dict[int, str] = {}
    conflicts: set[int] = set()
    for payload in payloads:
        for event in payload.get("events") or []:
            for competition in event.get("competitions") or []:
                for competitor in competition.get("competitors") or []:
                    rank = (competitor.get("curatedRank") or {}).get("current")
                    team = competitor.get("team") or {}
                    name = str(team.get("displayName") or "").strip()
                    try:
                        rank = int(rank)
                    except (TypeError, ValueError):
                        continue
                    if not 1 <= rank <= 25 or not name:
                        continue
                    if rank in by_rank and by_rank[rank] != name:
                        conflicts.add(rank)
                    by_rank[rank] = name
    if conflicts or set(by_rank) != set(range(1, 26)):
        return []
    return [{"rank": rank, "name": by_rank[rank]} for rank in range(1, 26)]


def load(path: pathlib.Path = SNAPSHOT) -> dict:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    rows = document.get("rankings") or []
    return document if [r.get("rank") for r in rows] == list(range(1, 26)) else {}


def refresh(path: pathlib.Path = SNAPSHOT, today: dt.date | None = None,
            fetch=_download) -> dict:
    today = today or dt.datetime.now(dt.timezone.utc).date()
    payloads = []
    try:
        for offset in range(-3, 4):
            payloads.append(fetch(today + dt.timedelta(days=offset)))
    except (OSError, TimeoutError, ValueError, json.JSONDecodeError):
        return load(path)
    rows = extract(payloads)
    if not rows:
        return load(path)
    document = {
        "poll_name": "AP Top 25",
        "source": "ESPN scoreboard published AP rank",
        "fetched_on": today.isoformat(),
        "rankings": rows,
    }
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8", newline="\n")
    return document

