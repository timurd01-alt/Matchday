"""Embed approved derived research receipts into cached public fixture JSON."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from advanced_metrics_store import attach_shadow_profiles


COMPETITIONS = {"ncaaf": ("NCAAF", "football"), "ncaam": ("NCAAM", "basketball")}


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
            temporary = path.with_suffix(path.suffix + ".research.tmp")
            temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            os.replace(temporary, path)
            results[slug] = {"matches": len(matches), "advanced": attached.get("matches", 0)}
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
                  f"advanced={result['advanced']}")


if __name__ == "__main__":
    main()
