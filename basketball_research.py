"""Build current-season basketball pace and efficiency from completed ESPN box scores."""
import datetime as dt
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.request import urlopen

BASE = "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/"
CACHE = Path("basketball_box_totals.json")


def get(path):
    with urlopen(BASE + path, timeout=25) as response:
        return json.load(response)


def totals(event):
    game = event["competitions"][0]
    minutes = 40 + 5 * max(0, game["status"].get("period", 2) - 2)
    scores = {c["team"]["id"]: int(c["score"]) for c in game["competitors"]}
    try:
        sides = []
        for side in get("summary?event=" + event["id"])["boxscore"]["teams"]:
            stats = {s["name"]: s["displayValue"] for s in side["statistics"]}
            attempts = lambda key: int(stats[key].split("-")[1])
            possessions = (attempts("fieldGoalsMade-fieldGoalsAttempted") - int(stats["offensiveRebounds"])
                           + int(stats["totalTurnovers"]) + .475 * attempts("freeThrowsMade-freeThrowsAttempted"))
            if possessions <= 0:
                return None
            sides.append([side["team"]["displayName"], scores[side["team"]["id"]], possessions])
        if len(sides) == 2:
            return event["id"], [minutes, sides]
    except (OSError, KeyError, ValueError, IndexError):
        return None


def refresh():
    today = dt.datetime.now(dt.timezone.utc).date()
    start = dt.date(today.year if today.month >= 8 else today.year - 1, 11, 1)
    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    if cache.get("season_start") != start.isoformat():
        cache = {"season_start": start.isoformat(), "games": {}}
    # Revisit recent finals to collect late box scores. Existing finals need no summary call.
    day = max(start, dt.date.fromisoformat(cache.get("through", start.isoformat())) - dt.timedelta(days=3))
    while day <= today:
        events = get("scoreboard?groups=50&limit=500&dates=" + day.strftime("%Y%m%d"))["events"]
        pending = [e for e in events if e["status"]["type"]["completed"] and e["id"] not in cache["games"]]
        with ThreadPoolExecutor(max_workers=5) as workers:
            cache["games"].update(row for row in workers.map(totals, pending) if row)
        cache["through"] = day.isoformat()
        CACHE.write_text(json.dumps(cache, separators=(",", ":")))
        day += dt.timedelta(days=1)


if __name__ == "__main__":
    refresh()
