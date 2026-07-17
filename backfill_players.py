"""
backfill_players.py — seed the player database with the WHOLE tournament.

The player DB normally accumulates from each fetch going forward. This script
walks back through every finished match since the tournament started (June 11),
pulls each match's lineup + final score from ESPN's public endpoints, and feeds
them through the same accumulator the fetcher uses. Run it ONCE:

    python backfill_players.py

Takes a couple of minutes (one polite request per matchday + one per match).
Re-running is safe — matches already in the DB are skipped automatically.
Works for the currently configured competition (default: World Cup).
"""
import datetime, json, sys, time
import urllib.request

import fetch_data as fd

SB = ("https://site.api.espn.com/apis/site/v2/sports/soccer/"
      f"{fd.COMP['espn']}/scoreboard?dates={{d}}&limit=100")
SUM = ("https://site.api.espn.com/apis/site/v2/sports/soccer/"
       f"{fd.COMP['espn']}/summary?event={{eid}}")

START = datetime.date(2026, 6, 11)


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "matchday-backfill"})
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.loads(r.read().decode())


def main():
    if fd.COMP["sport"] != "soccer":
        sys.exit("backfill currently supports soccer competitions")
    db = fd._load_player_db()
    seen = set(db.get("_matches", []))
    today = datetime.date.today()
    day = START
    fake_matches = []
    while day <= today:
        ds = day.strftime("%Y%m%d")
        try:
            sb = get(SB.format(d=ds))
        except Exception as e:
            print(f"  {ds}: scoreboard failed ({e}) — skipping day")
            day += datetime.timedelta(days=1); continue
        events = sb.get("events") or []
        for ev in events:
            eid = str(ev.get("id"))
            mid = "espn-" + eid
            comp = (ev.get("competitions") or [{}])[0]
            state = ((comp.get("status") or {}).get("type") or {}).get("state")
            if state != "post" or mid in seen:
                continue
            try:
                d = get(SUM.format(eid=eid))
            except Exception as e:
                print(f"  event {eid}: summary failed ({e})"); continue
            # build a match object in the shape the accumulator expects
            comps = ((d.get("header") or {}).get("competitions") or [{}])[0]
            sides = {}
            for c in comps.get("competitors") or []:
                sides[c.get("homeAway")] = {
                    "name": ((c.get("team") or {}).get("displayName")) or "",
                    "score": int(c.get("score") or 0)}
            if "home" not in sides or "away" not in sides:
                continue
            lineups = {"home": None, "away": None}
            for r in d.get("rosters") or []:
                side = r.get("homeAway")
                xi = [{"name": ((p.get("athlete") or {}).get("displayName")) or ""}
                      for p in (r.get("roster") or []) if p.get("starter")]
                if side in ("home", "away") and xi:
                    lineups[side] = {"formation": ((r.get("team") or {}).get("formation")
                                                   or r.get("formation") or ""), "xi": xi}
            if not (lineups["home"] and lineups["away"]):
                continue
            fake_matches.append({
                "id": mid, "status": "FINISHED",
                "score": {"home": sides["home"]["score"], "away": sides["away"]["score"]},
                "home": {"name": sides["home"]["name"]},
                "away": {"name": sides["away"]["name"]},
                "lineups": lineups})
            time.sleep(0.6)  # be polite
        print(f"  {ds}: {len(events)} events scanned, {len(fake_matches)} matches queued so far")
        day += datetime.timedelta(days=1)
        time.sleep(0.4)
    if not fake_matches:
        print("nothing new to add — DB already covers every finished match found")
        return
    fd.update_player_db(fake_matches)
    db = fd._load_player_db()
    gk = sum(1 for p in db["players"].values() if p["role"] == "GK")
    de = sum(1 for p in db["players"].values() if p["role"] == "DEF")
    print(f"\ndone: {len(db['players'])} players in {fd.PLAYER_DB_FILE} "
          f"({gk} goalkeepers, {de} defenders) from {len(db['_matches'])} matches")
    print("run one normal fetch and Team of the Tournament will show the full XI.")


if __name__ == "__main__":
    main()
