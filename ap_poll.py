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
# The poll itself, rather than the poll inferred from which ranked teams happen
# to be playing. The scoreboard route below cannot see a ranked team on a bye:
# it then holds 24 of 25 ranks, fails closed and keeps the previous week's
# poll forever. That is what froze this snapshot on 20 September 2026. This
# endpoint also carries each team's record and its previous rank, both of
# which the scoreboard route had to reconstruct or borrow from elsewhere.
RANKINGS = "https://site.api.espn.com/apis/site/v2/sports/football/college-football/rankings"


def _download_rankings() -> dict:
    with urllib.request.urlopen(RANKINGS, timeout=20) as response:
        return json.load(response)


def _team_name(team: dict) -> str:
    """ESPN gives `location` and `name` here, not the `displayName` the
    scoreboard route returns. Joined so both routes emit the same spelling."""
    display = str(team.get("displayName") or "").strip()
    if display:
        return display
    parts = [str(team.get("location") or "").strip(),
             str(team.get("name") or team.get("nickname") or "").strip()]
    return " ".join(p for p in parts if p)


def extract_poll(payload: dict) -> list[dict]:
    """The AP Top 25 from the rankings endpoint, or [] if it is not complete."""
    polls = [r for r in (payload.get("rankings") or []) if r.get("type") == "ap"]
    if not polls:
        return []
    rows = []
    for entry in polls[0].get("ranks") or []:
        try:
            rank = int(entry.get("current"))
        except (TypeError, ValueError):
            continue
        name = _team_name(entry.get("team") or {})
        if not 1 <= rank <= 25 or not name:
            continue
        previous = entry.get("previous")
        previous = previous if isinstance(previous, int) and previous > 0 else None
        rows.append({
            "rank": rank, "name": name,
            "previous_rank": previous,
            "movement": previous - rank if previous else None,
            "record": str(entry.get("recordSummary") or "") or None,
        })
    rows.sort(key=lambda r: r["rank"])
    if {r["rank"] for r in rows} != set(range(1, 26)):
        return []
    return rows


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
            fetch=_download, fetch_rankings=_download_rankings) -> dict:
    today = today or dt.datetime.now(dt.timezone.utc).date()
    rows: list[dict] = []
    # Ask for the poll directly first; only reconstruct it from the scoreboard
    # if that fails, because the reconstruction cannot see a bye week.
    try:
        rows = extract_poll(fetch_rankings())
    except (OSError, TimeoutError, ValueError, json.JSONDecodeError):
        rows = []
    if not rows:
        payloads = []
        try:
            for offset in range(-3, 4):
                payloads.append(fetch(today + dt.timedelta(days=offset)))
        except (OSError, TimeoutError, ValueError, json.JSONDecodeError):
            return load(path)
        rows = extract(payloads)
    if not rows:
        return load(path)
    previous = load(path)
    previous_rows = previous.get("rankings") or []
    current_signature = [(row["rank"], row["name"]) for row in rows]
    previous_signature = [(row.get("rank"), row.get("name")) for row in previous_rows]
    # Re-fetching the same weekly poll must not erase the movement captured
    # when that poll first replaced its predecessor.
    if current_signature == previous_signature:
        return previous
    # The rankings endpoint publishes the previous rank itself, which is the
    # AP's own answer and survives a week where this file was never written.
    # Only fall back to diffing against the stored snapshot when it does not.
    previous_by_name = {row.get("name"): row.get("rank") for row in previous_rows}
    for row in rows:
        if row.get("previous_rank") is not None:
            continue
        prior = previous_by_name.get(row["name"])
        row["previous_rank"] = prior
        row["movement"] = prior - row["rank"] if isinstance(prior, int) else None
    document = {
        "poll_name": "AP Top 25",
        "source": "ESPN scoreboard published AP rank",
        "fetched_on": today.isoformat(),
        "rankings": rows,
    }
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8", newline="\n")
    return document
