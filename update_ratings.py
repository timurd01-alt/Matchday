"""
update_ratings.py -- set or inspect one field in a curated ratings file.

Every competition has its own ratings file (fetch_data.py picks it the same
way: ratings_<comp>.json). Pass --comp to target the right one.

USAGE
  python update_ratings.py --comp NCAAF --set "Alabama" squad_value_m 40
      Set one field for one team in that competition's ratings file, safely.

  python update_ratings.py --comp NCAAM --show
      Print the current table.

  python update_ratings.py --file some/other.json --show
      Target an arbitrary file directly instead of resolving by --comp.

The script only touches fields it's told to; everything else is preserved.
A backup (<file>.backup.json) is written before any change.
"""
import argparse, json, os, shutil, sys, unicodedata

# Same mapping fetch_data.py uses to pick RATINGS_FILE for a competition
# (COMPETITIONS keys there) -- duplicated here as a small static table rather
# than importing fetch_data.py, since that module expects live API keys/
# config at import time and this is meant to run standalone.
COMPS = ("NCAAF", "NCAAM")

def ratings_file_for(comp):
    comp = (comp or "NCAAF").upper()
    if comp not in COMPS:
        sys.exit(f"unknown --comp {comp!r}; choose one of {', '.join(COMPS)}")
    return f"ratings_{comp.lower()}.json"

def norm(s):
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode()
    s = s.replace("'", "").replace("\u2019", "")
    return s.lower().replace("-", " ").replace(".", "").strip()

# Set by __main__ from --comp/--file before any of load/save/set_field/show run.
FILE = "ratings_ncaaf.json"

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
    teams.sort(key=lambda x: -float(x[1].get("squad_value_m") or 0))
    print(f"{'team':28} {'squad':>9} {'star':>8}")
    for t, d in teams:
        print(f"{t:28} {d.get('squad_value_m','?'):>9} {d.get('star_value_m','?'):>8}")

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--comp", choices=COMPS,
                     help="competition whose ratings file to target (default: NCAAF)")
    ap.add_argument("--file", help="explicit ratings file path, overrides --comp")
    ap.add_argument("--set", nargs=3, metavar=("TEAM", "FIELD", "VALUE"))
    ap.add_argument("--show", action="store_true")
    a = ap.parse_args()
    FILE = a.file if a.file else ratings_file_for(a.comp)
    if not (a.comp or a.file):
        print(f"no --comp/--file given -- defaulting to {FILE}. Pass --comp NCAAM for basketball.")
    else:
        print(f"targeting {FILE}")
    if a.set: set_field(*a.set)
    elif a.show: show()
    else: ap.print_help()
