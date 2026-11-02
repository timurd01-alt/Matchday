"""Published committee ranking facts; never reuse another season's poll."""
import datetime as dt
import json
import pathlib
import ap_poll

SNAPSHOT = pathlib.Path("cfp_poll_snapshot.json")

def refresh(path=SNAPSHOT, today=None, fetch=ap_poll._download_rankings):
    today = today or dt.datetime.now(dt.timezone.utc).date()
    season = today.year if today.month >= 7 else today.year - 1
    previous = {}
    try:
        previous = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    if previous.get("season") != season or [r.get("rank") for r in previous.get("rankings", [])] != list(range(1, 26)):
        previous = {}
    try:
        payload = fetch()
        poll = next((p for p in payload.get("rankings", []) if p.get("type") == "cfp"), {})
        published = str(poll.get("date") or "")[:10]
        if (poll.get("season") or {}).get("year") != season or not published or dt.date.fromisoformat(published) > today:
            return previous
        # Reuse the factual rank/name/record parser, never AP as a CFP fallback.
        rows = ap_poll.extract_poll({"rankings": [{**poll, "type": "ap"}]})
        if [r["rank"] for r in rows] != list(range(1, 26)):
            return previous
        if previous.get("published_on", "") > published:
            return previous
        document = {"poll_name": "CFP committee rankings", "season": season,
                    "source": "CFP selection committee via ESPN public rankings",
                    "source_url": "https://collegefootballplayoff.com/rankings",
                    "published_on": published, "fetched_on": today.isoformat(), "rankings": rows}
        path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8", newline="\n")
        return document
    except (OSError, ValueError, TimeoutError):
        return previous
