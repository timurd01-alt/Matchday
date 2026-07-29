"""Embed approved derived research receipts into cached public fixture JSON."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from advanced_metrics_store import attach_shadow_profiles
from mlb_challenger_store import attach_mlb_challenger_shadows
from nfl_challenger_store import attach_nfl_challenger_shadows


COMPETITIONS = {
    "nfl": ("NFL", "football"), "ncaaf": ("NCAAF", "football"),
    "ncaam": ("NCAAM", "basketball"), "nba": ("NBA", "basketball"),
    "mlb": ("MLB", "baseball"), "wc": ("WC", "soccer"),
    "ucl": ("UCL", "soccer"), "epl": ("EPL", "soccer"),
    "laliga": ("LALIGA", "soccer"), "seriea": ("SERIEA", "soccer"),
    "bundesliga": ("BUNDESLIGA", "soccer"), "ligue1": ("LIGUE1", "soccer"),
}


def populate(directory: str | Path = ".") -> dict[str, dict]:
    root = Path(directory)
    results = {}
    for slug, (competition, sport) in COMPETITIONS.items():
        path = root / f"data_{slug}.json"
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            matches = payload.get("matches") or []
            attached = attach_shadow_profiles(matches, competition, sport, root)
            challenger = {"matches": 0}
            if competition == "NFL":
                challenger = attach_nfl_challenger_shadows(
                    matches, root / "nfl_challenger_model.json",
                    root / "nfl_availability_ledger.jsonl",
                )
            elif competition == "MLB":
                challenger = attach_mlb_challenger_shadows(
                    matches, root / "mlb_run_strength_model_v1.json"
                )
            temporary = path.with_suffix(path.suffix + ".research.tmp")
            temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            os.replace(temporary, path)
            results[slug] = {"matches": len(matches), "advanced": attached.get("matches", 0),
                             "challenger": challenger.get("matches", 0)}
        except Exception as exc:
            results[slug] = {"error": f"{type(exc).__name__}: {exc}"}
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", default=".")
    args = parser.parse_args()
    results = populate(args.directory)
    for slug, result in results.items():
        if "error" in result:
            print(f"{slug}: research population failed: {result['error']}")
        else:
            print(f"{slug}: schema on {result['matches']} matches; "
                  f"advanced={result['advanced']} challenger={result['challenger']}")


if __name__ == "__main__":
    main()
