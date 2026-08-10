"""Reconcile tracked official pick logs into private append-only ledgers.

This runs independently of provider refreshes. A skipped or degraded fetch
must not prevent an already-persisted official pick or grade from reaching the
tamper-evident research ledger restored from the Actions cache.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import forecast_ledger


def _competition_from_path(path: Path) -> str:
    return path.stem.removeprefix("picks_log_").upper()


def reconcile(root: str | Path = ".") -> dict[str, dict]:
    base = Path(root)
    reports: dict[str, dict] = {}
    for picks_path in sorted(base.glob("picks_log_*.json")):
        competition = _competition_from_path(picks_path)
        raw = json.loads(picks_path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError(f"{picks_path.name} must contain an object keyed by fixture id")
        records = list(raw.values())
        ledger_path = base / f"forecast_ledger_{competition.lower()}.jsonl"
        sync = forecast_ledger.sync_pick_records(ledger_path, records, competition)
        audit = forecast_ledger.coverage(ledger_path, records)
        reports[competition] = {**sync, **audit, "ledger": ledger_path.name}
        if not audit["complete"]:
            raise RuntimeError(
                f"{competition} forecast ledger incomplete: "
                f"locks={audit['missing_locks']} grades={audit['missing_grades']}"
            )
    return reports


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    args = parser.parse_args(argv)
    reports = reconcile(args.root)
    for competition, report in reports.items():
        print(
            f"{competition}: {report['logged_locks']}/{report['expected_locks']} locks, "
            f"{report['logged_grades']}/{report['expected_grades']} grades "
            f"({report['appended']} appended)"
        )


if __name__ == "__main__":
    main()
