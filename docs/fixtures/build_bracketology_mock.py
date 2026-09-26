"""Build illustrative UI fixtures only. This is not a forecast or model."""
import json
from pathlib import Path

REGIONS = {
    "East": ["Duke", "Alabama", "Wisconsin", "Arizona", "Oregon", "BYU", "Saint Mary's", "Mississippi State", "Baylor", "Vanderbilt", "VCU", "Liberty", "Akron", "Montana", "Robert Morris", "American"],
    "West": ["Florida", "St. John's", "Texas Tech", "Maryland", "Memphis", "Missouri", "Kansas", "UConn", "Oklahoma", "Arkansas", "Drake", "Colorado State", "Grand Canyon", "UNC Wilmington", "Omaha", "Norfolk State"],
    "South": ["Auburn", "Michigan State", "Iowa State", "Texas A&M", "Michigan", "Ole Miss", "Marquette", "Louisville", "Creighton", "New Mexico", "North Carolina", "UC San Diego", "Yale", "Lipscomb", "Bryant", "Alabama State"],
    "Midwest": ["Houston", "Tennessee", "Kentucky", "Purdue", "Clemson", "Illinois", "UCLA", "Gonzaga", "Georgia", "Utah State", "Texas", "McNeese", "High Point", "Troy", "Wofford", "SIU Edwardsville"],
}
ROUNDS = [("FF", "First Four"), ("R64", "Round of 64"), ("R32", "Round of 32"), ("S16", "Sweet 16"), ("E8", "Elite Eight"), ("F4", "Final Four"), ("F", "Championship")]
teams, field, games = {}, [], []

def key(name):
    return name.lower().replace(" ", "-").replace("'", "").replace(".", "").replace("&", "and")

def team(name, seed=None, status="in", conference="Illustrative conference", make=0.74):
    k = key(name)
    seed_odds = {str(i): 0 for i in range(1, 17)}
    if seed:
        seed_odds[str(seed)] = make
    else:
        seed_odds["11"] = make
    seed_odds["out"] = round(1 - make, 2)
    teams[k] = {
        "team_key": k, "team_name": name, "conference": conference, "logo_key": name,
        "power_rating": 18.4, "power_rank": 27, "resume_rank": 34,
        "record": "18-8", "conference_record": "9-5",
        "quadrants": {"Q1": [3, 5], "Q2": [4, 2], "Q3": [5, 1], "Q4": [6, 0]},
        "sos_rank": 42, "sor_rank": 36,
        "best_wins": [{"opponent": "Kansas", "opponent_key": "kansas", "site": "road", "date": "2026-02-01"}],
        "bad_losses": [{"opponent": "Dayton", "opponent_key": "dayton", "site": "home", "date": "2026-02-10"}],
        "odds": {"make_field": make, "auto_bid": 0.12 if make >= 0.12 else 0, "seed": seed_odds,
                 "rounds": {"R64": make, "R32": 0.10 if make >= 0.10 else 0, "S16": 0.05 if make >= 0.10 else 0, "E8": 0.02 if make >= 0.10 else 0, "F4": 0.01 if make >= 0.10 else 0, "F": 0.005 if make >= 0.10 else 0, "champion": 0.001 if make >= 0.10 else 0}},
        "movement": {"seed": -1, "make_field": 0.02}, "upset_alert": False,
        "status": status, "eliminated_on": None, "eliminated_reason": None,
    }
    return k

for region_index, (region, names) in enumerate(REGIONS.items()):
    for seed, name in enumerate(names, 1):
        k = team(name, seed, "locked" if seed < 4 else "in")
        field.append({"team_key": k, "team_name": name, "conference": teams[k]["conference"], "seed": seed,
                      "region": region, "overall_seed": (seed - 1) * 4 + region_index + 1,
                      "bid": "auto_clinched" if seed == 16 else "auto" if seed >= 12 else "at_large",
                      "first_four": False, "odds": teams[k]["odds"], "movement": teams[k]["movement"]})

playins = [("East", 16, "Mount St. Mary's"), ("South", 16, "Saint Francis"), ("South", 11, "San Diego State"), ("Midwest", 11, "Xavier")]
first_four = []
playin_ids = {}
for index, (region, seed, name) in enumerate(playins, 1):
    existing = next(t for t in field if t["region"] == region and t["seed"] == seed)
    existing["first_four"] = True
    k = team(name, seed, "bubble" if seed == 11 else "in")
    field.append({**existing, "team_key": k, "team_name": name, "odds": teams[k]["odds"], "movement": teams[k]["movement"]})
    gid = f"ff-{index}"
    playin_ids[(region, seed)] = gid
    first_four.append({"game_id": gid, "region": region, "seed": seed, "kind": "at_large" if seed == 11 else "auto", "teams": [existing["team_key"], k], "win_prob": [0.54, 0.46]})
    games.append({"id": gid, "round": "FF", "region": "First Four", "slots": [{"team_key": existing["team_key"]}, {"team_key": k}], "next_game": None, "next_slot": None, "status": "projected", "winner_key": None, "score": None})

pairings = [(1, 16), (8, 9), (5, 12), (4, 13), (6, 11), (3, 14), (7, 10), (2, 15)]
for region, names in REGIONS.items():
    previous = []
    for index, pairing in enumerate(pairings, 1):
        gid = f"{region.lower()}-r64-{index}"
        slots = []
        for slot_index, seed in enumerate(pairing):
            feeder = playin_ids.get((region, seed))
            slots.append({"source_game": feeder, "label": "First Four winner"} if feeder else {"team_key": key(names[seed - 1])})
            if feeder:
                g = next(g for g in games if g["id"] == feeder)
                g.update(next_game=gid, next_slot=slot_index)
        games.append({"id": gid, "round": "R64", "region": region, "slots": slots, "next_game": None, "next_slot": None, "status": "projected", "winner_key": None, "score": None})
        previous.append(gid)
    for rnd in ["R32", "S16", "E8"]:
        current = []
        for i in range(0, len(previous), 2):
            gid = f"{region.lower()}-{rnd.lower()}-{i // 2 + 1}"
            games.append({"id": gid, "round": rnd, "region": region, "slots": [{"source_game": source, "label": "Projected winner"} for source in previous[i:i+2]], "next_game": None, "next_slot": None, "status": "projected", "winner_key": None, "score": None})
            for slot, source in enumerate(previous[i:i+2]):
                next(g for g in games if g["id"] == source).update(next_game=gid, next_slot=slot)
            current.append(gid)
        previous = current

for i, regions in enumerate([("East", "West"), ("South", "Midwest")], 1):
    gid = f"national-f4-{i}"
    sources = [f"{r.lower()}-e8-1" for r in regions]
    games.append({"id": gid, "round": "F4", "region": "National", "slots": [{"source_game": s, "label": f"{r} winner"} for s, r in zip(sources, regions)], "next_game": "national-final", "next_slot": i-1, "status": "projected", "winner_key": None, "score": None})
    for slot, source in enumerate(sources):
        next(g for g in games if g["id"] == source).update(next_game=gid, next_slot=slot)
games.append({"id": "national-final", "round": "F", "region": "National", "slots": [{"source_game": f"national-f4-{i}", "label": "Semifinal winner"} for i in (1, 2)], "next_game": None, "next_slot": None, "status": "projected", "winner_key": None, "score": None})

bubble = {"last_four_byes": [key(n) for n in ["Baylor", "Oklahoma", "New Mexico", "Utah State"]],
          "last_four_in": [key(n) for n in ["North Carolina", "San Diego State", "Texas", "Xavier"]],
          "first_four_out": [], "next_four_out": []}
for group, names in [("first_four_out", ["Indiana", "Boise State", "Ohio State", "Dayton"]), ("next_four_out", ["SMU", "Wake Forest", "UC Irvine", "San Francisco"])]:
    for name in names:
        bubble[group].append(team(name, status="bubble" if group == "first_four_out" else "out", make=0.25))
for k in bubble["last_four_in"]:
    teams[k]["status"] = "bubble"
auto_only = team("George Mason", status="auto_bid_only", make=0.08)
teams[auto_only]["odds"]["auto_bid"] = 0.08
longshot = team("Bradley", status="out", make=0.005)
teams[longshot]["odds"]["seed"]["out"] = 0.995
bubble["next_four_out"][-1] = longshot
for k in [auto_only, longshot]:
    teams[k]["odds"]["rounds"] = {r: 0 for r in ["R64", "R32", "S16", "E8", "F4", "F", "champion"]}
    teams[k]["odds"]["rounds"]["R64"] = teams[k]["odds"]["make_field"]
eliminated_key = team("Cleveland State", status="eliminated", make=0)
teams[eliminated_key].update(eliminated_on="2026-09-24", eliminated_reason="Illustrative conference semifinal loss with no at-large path")

field.sort(key=lambda entry: (entry["seed"], entry["overall_seed"], entry["team_key"]))
for overall_seed, entry in enumerate(field, 1):
    entry["overall_seed"] = overall_seed
round_labels = dict(ROUNDS)
for game in games:
    if game["round"] == "FF":
        playin = next(p for p in first_four if p["game_id"] == game["id"])
        game["label"] = f"{playin['region']} · Seed {playin['seed']} play-in"
    elif game["id"] == "national-final":
        game["label"] = "National championship"
    elif game["round"] == "F4":
        game["label"] = f"National semifinal {game['id'].rsplit('-', 1)[1]}"
    else:
        game["label"] = f"{game['region']} · {round_labels[game['round']]} · Game {game['id'].rsplit('-', 1)[1]}"

document = {"version": "0.1", "display_contract": "matchday-1", "mock": True,
            "notice": "UI DEMO ONLY. All statistics, dates, seeds, odds and statuses are invented examples, not forecasts or real results.",
            "competition": "NCAAM", "season": "2026-27", "build_id": "mock-layout-001", "as_of": "2026-09-25T12:00:00Z", "valid_until": "2099-01-01T00:00:00Z",
            "phase": "early", "calibrated": False, "simulations": 10000, "field_size": 68, "max_seed": 16,
            "regions": list(REGIONS) + ["First Four", "National"], "rounds": [{"key": k, "label": v} for k, v in ROUNDS],
            "odds_rounds": [{"key": k, "label": label} for k, label in [("R64", "Round of 64"), ("R32", "Round of 32"), ("S16", "Sweet 16"), ("E8", "Elite Eight"), ("F4", "Final Four"), ("F", "Final"), ("champion", "Champion")]],
            "comparison_build_id": "mock-layout-000", "comparison_as_of": "2026-09-24T12:00:00Z",
            "odds_basis": "unconditional_season", "field": field, "teams": teams, "bubble": bubble, "first_four": first_four,
            "bracket": {"kind": "projected", "games": games},
            "bid_thieves": [{"team_key": auto_only, "conference": "Illustrative conference", "auto_bid_odds": 0.08, "at_large_spots_at_risk": 1}],
            "eliminated": [{"team_key": eliminated_key, "eliminated_on": teams[eliminated_key]["eliminated_on"], "eliminated_reason": teams[eliminated_key]["eliminated_reason"]}],
            "conferences": [{"conference": "Illustrative conference", "projected_bids": 8.3, "auto_bid_odds": {auto_only: 0.08}}],
            "matchup_model": None}

if __name__ == "__main__":
    assert len(field) == 68 and len(games) == 67
    ids = {g["id"] for g in games}
    assert len(ids) == 67
    assert all(g["next_game"] in ids or g["next_game"] is None for g in games)
    Path(__file__).with_name("bracketology_ncaam.mock.json").write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8", newline="\n")
