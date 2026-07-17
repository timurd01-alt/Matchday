"""
repair_picks.py — fix historical mis-gradings in your pick log.

Some older picks were graded before the penalty/90-minute rules were finalised.
A few got a wrong `result` — most visibly, a non-level scoreline (like 2-0)
stored as a "draw". That is impossible and it distorted your record.

This script corrects ONLY provably-wrong gradings, using one rule that cannot
be argued with:

    a displayed scoreline that is NOT level cannot be a draw.

For any pick whose shown score is X-Y with X != Y but result == "d", it sets
the result to the real winner and recomputes model_hit / market_hit. Genuine
penalty-shootout draws (score tagged "(4-3 pens)") are left untouched, because
those correctly grade as draws for the 1X2 market.

It writes a backup first (picks_log_wc.backup.json) and prints every change.
Run once:  python repair_picks.py
"""
import json
import os
import shutil
import sys

FILES = ["picks_log_wc.json"] + [f for f in os.listdir(".")
                                 if f.startswith("picks_log_") and f.endswith(".json")
                                 and "backup" not in f]


def parse_shown(score):
    """Return (home_goals, away_goals, is_pens) from a stored score string."""
    if not score or "-" not in str(score):
        return None
    s = str(score)
    is_pens = "pen" in s.lower()
    base = s.split("(")[0].strip()
    try:
        h, a = base.split("-")
        return int(h), int(a), is_pens
    except Exception:
        return None


def repair_file(path):
    try:
        with open(path, encoding="utf-8") as f:
            picks = json.load(f)
    except Exception as e:
        print(f"  skip {path}: {e}")
        return 0
    changed = 0
    for mid, p in picks.items():
        if not isinstance(p, dict) or p.get("result") is None:
            continue
        parsed = parse_shown(p.get("score"))
        if not parsed:
            continue
        hg, ag, is_pens = parsed
        # the only provably-wrong case: non-level score graded as a draw, no pens
        if p.get("result") == "d" and hg != ag and not is_pens:
            true_res = "h" if hg > ag else "a"
            old = p.get("result")
            p["result"] = true_res
            if "pick" in p:
                p["model_hit"] = (p.get("pick") == true_res)
            if p.get("market_pick"):
                p["market_hit"] = (p.get("market_pick") == true_res)
            print(f"  FIXED  {p.get('home','?')} v {p.get('away','?')}  "
                  f"{p.get('score')}  result {old} -> {true_res}  "
                  f"(pick {p.get('pick')}: {'HIT' if p.get('model_hit') else 'miss'})")
            changed += 1
    if changed:
        shutil.copy(path, path.replace(".json", ".backup.json"))
        with open(path, "w", encoding="utf-8") as f:
            json.dump(picks, f, ensure_ascii=False, indent=1)
        print(f"  saved {path} ({changed} corrected; backup written)")
    else:
        print(f"  {path}: nothing to repair — all gradings consistent")
    return changed


def main():
    print("\n=== Pick-log repair ===\n")
    total = 0
    for path in FILES:
        if os.path.exists(path):
            print(f"Checking {path}:")
            total += repair_file(path)
            print()
    if total:
        print(f"Done: corrected {total} mis-graded pick(s). Your record now reflects\n"
              f"the true results. Re-open the app to see the updated scorecard.\n")
    else:
        print("No mis-gradings found — your pick log is already consistent.\n")


if __name__ == "__main__":
    main()
