"""Ingest an authorized batch of timestamped pregame market snapshots."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from market_snapshots import append_batch


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True)
    parser.add_argument("--ledger", default="market_snapshot_ledger.jsonl")
    args = parser.parse_args()
    payload = json.loads(Path(args.input).read_text(encoding="utf-8"))
    result = append_batch(args.ledger, payload)
    print(f"created={result['created']} event_id={result['event_id']} events={result['events']}")


if __name__ == "__main__":
    main()
