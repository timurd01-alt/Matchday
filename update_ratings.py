"""
update_ratings.py — refresh a curated ratings file from downloaded data, one command.

FIFA rankings and Transfermarkt values change a handful of times a year, so this
is a run-when-needed tool, not a daemon.

Every competition has its own curated ratings file (fetch_data.py picks it the
same way: ratings_<comp>.json, except World Cup/default soccer uses plain
ratings.json) -- --set/--show/--fifa-csv used to always hit ratings.json no
matter what, which meant an operator running e.g. "--set 'Kansas City Chiefs'
squad_value_m 40" intending to update NFL actually wrote into the World Cup
file and silently no-opped for NFL. Pass --comp to target the right one.

USAGE
  python update_ratings.py --fifa-csv rankings.csv
      Merge FIFA ranking positions from a CSV you downloaded (soccer only).
      Expected columns (flexible, case-insensitive): a team-name column
      ("team"/"country"/"team_name") and a rank column ("rank"/"position").
      Good sources: Kaggle "FIFA World Ranking" datasets, or DataHub mirrors —
      download the latest CSV after each FIFA release (next: 20 July 2026).

  python update_ratings.py --comp NFL --set "Kansas City Chiefs" squad_value_m 40
      Set one field for one team in that competition's ratings file, safely.

  python update_ratings.py --comp NCAAF --show
      Print the current NCAAF table sorted by FIFA rank.

  python update_ratings.py --file some/other.json --show
      Target an arbitrary file directly instead of resolving by --comp.

Omitting --comp/--file keeps the historical default (ratings.json, the World
Cup/default-soccer file) so old invocations still do what they always did --
but every run prints which file it actually touched, so that's no longer a
silent assumption.

The script only touches fields it's told to; everything else is preserved.
A backup (<file>.backup.json) is written before any change.
"""
import argparse, csv, json, os, shutil, sys, unicodedata

# Same mapping fetch_data.py uses to pick RATINGS_FILE for a competition
# (COMPETITIONS keys there) -- duplicated here as a small static table rather
# than importing fetch_data.py, since that module expects live API keys/
# config at import time and this is meant to run standalone.
COMPS = ("WC", "UCL", "NFL", "EPL", "LALIGA", "SERIEA", "BUNDESLIGA",
         "LIGUE1", "NCAAF", "NCAAM", "MLB", "NHL", "NBA")

def ratings_file_for(comp):
    comp = (comp or "WC").upper()
    if comp not in COMPS:
        sys.exit(f"unknown --comp {comp!r}; choose one of {', '.join(COMPS)}")
    return "ratings.json" if comp == "WC" else f"ratings_{comp.lower()}.json"

def norm(s):
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode()
    s = s.replace("'", "").replace("\u2019", "")
    return s.lower().replace("-", " ").replace(".", "").strip()

# common alias fixes between datasets and our team names
ALIASES = {
    "usa": "united states", "united states of america": "united states",
    "korea republic": "south korea", "ir iran": "iran", "turkiye": "turkey",
    "cabo verde": "cape verde islands", "cape verde": "cape verde islands",
    "czech republic": "czechia", "bosnia and herzegovina": "bosnia herzegovina",
    "cote divoire": "ivory coast", "congo dr": "congo dr", "dr congo": "congo dr",
}

# Set by __main__ from --comp/--file before any of load/save/merge_fifa/
# set_field/show run. Defaults to the historical "ratings.json" so a bare
# invocation with no flags behaves exactly like it always did.
FILE = "ratings.json"

def load():
    if not os.path.exists(FILE):
        sys.exit(f"{FILE} does not exist -- check --comp/--file (competitions: {', '.join(COMPS)})")
    with open(FILE, encoding="utf-8") as f:
        return json.load(f)

def save(r):
    backup = FILE.rsplit(".json", 1)[0] + ".backup.json"
    shutil.copy(FILE, backup)
    with open(FILE, "w", encoding="utf-8") as f:
        json.dump(r, f, indent=2, ensure_ascii=False)
    print(f"saved {FILE} (backup in {backup})")

def merge_fifa(csv_path):
    r = load()
    lookup = {}
    for team in r:
        if team.startswith("_"): continue
        lookup[norm(team)] = team
    with open(csv_path, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        sys.exit("CSV appears empty")
    cols = {c.lower().strip(): c for c in rows[0].keys()}
    name_col = next((cols[c] for c in ("team", "country", "team_name", "country_full") if c in cols), None)
    rank_col = next((cols[c] for c in ("rank", "position", "rank_position") if c in cols), None)
    if not name_col or not rank_col:
        sys.exit(f"couldn't find team/rank columns in: {list(cols)}")
    hit = miss = 0
    for row in rows:
        n = norm(row[name_col]); n = ALIASES.get(n, n)
        team = lookup.get(n)
        if team:
            try:
                r[team]["fifa_rank"] = int(float(row[rank_col])); hit += 1
            except Exception:
                pass
        else:
            miss += 1
    print(f"merged FIFA ranks: {hit} teams updated ({miss} CSV rows had no match — normal, "
          f"the CSV covers all 200+ FIFA nations)")
    save(r)

def set_field(team, field, value):
    r = load()
    match = next((t for t in r if norm(t) == norm(team)), None)
    if not match:
        sys.exit(f"team not found: {team}")
    try: value = float(value) if "." in str(value) else int(value)
    except Exception: pass
    old = r[match].get(field)
    r[match][field] = value
    print(f"{match}: {field} {old} -> {value}")
    save(r)

def show():
    r = load()
    teams = [(t, d) for t, d in r.items() if not t.startswith("_")]
    teams.sort(key=lambda x: x[1].get("fifa_rank", 999))
    print(f"{'team':22} {'rank':>4} {'squad €M':>9} {'star €M':>8}")
    for t, d in teams:
        print(f"{t:22} {d.get('fifa_rank','?'):>4} {d.get('squad_value_m','?'):>9} {d.get('star_value_m','?'):>8}")

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--comp", choices=COMPS,
                     help="competition whose ratings file to target (default: WC / ratings.json)")
    ap.add_argument("--file", help="explicit ratings file path, overrides --comp")
    ap.add_argument("--fifa-csv")
    ap.add_argument("--set", nargs=3, metavar=("TEAM", "FIELD", "VALUE"))
    ap.add_argument("--show", action="store_true")
    a = ap.parse_args()
    FILE = a.file if a.file else ratings_file_for(a.comp)
    if not (a.comp or a.file):
        print(f"no --comp/--file given -- defaulting to {FILE} (World Cup/default soccer). "
              f"Pass --comp to target NFL/NBA/MLB/NHL/NCAAF/NCAAM/a league instead.")
    else:
        print(f"targeting {FILE}")
    if a.fifa_csv: merge_fifa(a.fifa_csv)
    elif a.set: set_field(*a.set)
    elif a.show: show()
    else: ap.print_help()
