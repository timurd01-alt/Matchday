"""Preserve published rows for the other sport when shipping one slate."""
import json
import sys
from pathlib import Path


def merge(sport, fresh, published):
    if fresh["handoff_version"] != published["handoff_version"]:
        raise ValueError("A full update is required for a handoff format change.")
    if set(fresh["sports"]) != {"ncaaf", "ncaam"}:
        raise ValueError("Expected a two-sport export.")
    other = "ncaam" if sport == "ncaaf" else "ncaaf"
    for key in ("picks", "results", "fixtures"):
        fresh[key] = ([row for row in fresh[key] if row["sport"] == sport]
                      + [row for row in published[key] if row["sport"] == other])
        fresh["coverage"][key] = len(fresh[key])
    for key in ("rankings", "ballots", "team_profiles", "upsets"):
        fresh[key].pop(other, None)
        if other in published[key]:
            fresh[key][other] = published[key][other]
    fresh["scorecard"]["sports"].pop(other, None)
    if other in published["scorecard"]["sports"]:
        fresh["scorecard"]["sports"][other] = published["scorecard"]["sports"][other]
    return fresh


if __name__ == "__main__":
    sport, source, destination = sys.argv[1:]
    target = Path(destination)
    data = merge(sport, json.loads(Path(source).read_text(encoding="utf-8-sig")),
                 json.loads(target.read_text(encoding="utf-8-sig")))
    target.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
