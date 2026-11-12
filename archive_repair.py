"""One-off, logged repairs to rows the archive already holds (Build 1112T).

The archive's rule is that a settled score is never rewritten, and nothing
here touches a score. Two defects in rows written by the handoff backfill are
repaired, each change appended to `archive/corrections.jsonl` with the row's
before and after so it can be audited or reversed:

* `names` -- football rows seeded from the handoff on 2026-10-21 had an FCS
  opponent cut down to an FBS school sharing its first word ("Texas" for Texas
  Southern, "Utah" for Utah Tech). Each row's names are recomputed from the
  handoff that seeded it with the corrected `archive_backfill.handoff_name_map`.
  Only `home_name` / `away_name` change, and only when the handoff result for
  that event id has the same final score as the row.
* `foreign-ids` -- basketball rows written under ESPN event ids (the handoff's)
  in a season the pipeline archives under CBBD ids. AGENTS.md keeps one
  provider per (competition, season) and the live pipeline outranks a bulk
  source, so those rows are removed. The pipeline's hook now archives the whole
  fetched season, which re-records any of those games CBBD reports.

Both are idempotent: a second run finds nothing to change.

Usage:
    python archive_repair.py names --handoff trdlab_picks.json --handoff old.json
    python archive_repair.py foreign-ids --handoff trdlab_picks.json
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
from pathlib import Path
from typing import Any, Iterable, Sequence

import archive_backfill
import game_archive

CORRECTIONS_NAME = "corrections.jsonl"   # beside conflicts.jsonl, under ARCHIVE_ROOT


def _results(documents: Iterable[dict[str, Any]], comp: str) -> dict[str, dict[str, Any]]:
    """Handoff results for `comp` by event id; an earlier document wins a tie."""
    found: dict[str, dict[str, Any]] = {}
    for document in documents:
        for result in document.get("results") or []:
            if str(result.get("competition") or "").upper() == comp and result.get("event_id"):
                found.setdefault(str(result["event_id"]), result)
    return found


def _log(entries: list[dict[str, Any]]) -> None:
    if not entries:
        return
    path = Path(game_archive.ARCHIVE_ROOT) / CORRECTIONS_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        for entry in entries:
            handle.write(json.dumps(entry, sort_keys=True, ensure_ascii=False) + "\n")


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")


def _score_matches(row: dict[str, Any], result: dict[str, Any]) -> bool:
    try:
        return (int(float(row["home_score"])) == int(float(result["home_score"]))
                and int(float(row["away_score"])) == int(float(result["away_score"])))
    except (KeyError, TypeError, ValueError):
        return False


def correct_names(documents: Sequence[dict[str, Any]], comp: str = "NCAAF",
                  shorts: Sequence[str] | None = None) -> dict[str, int]:
    """Recompute handoff-seeded team names; never touch a score."""
    results = _results(documents, comp)
    if not results:
        return {"checked": 0, "corrected": 0, "skipped": 0}
    shorts = list(shorts if shorts is not None else archive_backfill._short_names(comp))
    names = archive_backfill.handoff_name_map(
        (result.get(side) for result in results.values() for side in ("home", "away")), shorts)
    prefix = f"{comp.lower()}-"
    stamp = _now()
    log: list[dict[str, Any]] = []
    checked = corrected = skipped = 0
    comp_dir = game_archive.GAMES_DIR / comp.lower()
    for partition in sorted(comp_dir.glob("*.csv")) if comp_dir.exists() else []:
        rows = game_archive.read_partition(partition)
        changed = False
        for row in rows:
            game_id = str(row.get("game_id") or "")
            # Only rows the handoff wrote: its label, and an id it carries.
            if row.get("source") != comp.lower() or not game_id.startswith(prefix):
                continue
            result = results.get(game_id[len(prefix):])
            if result is None:
                continue
            checked += 1
            if not _score_matches(row, result):
                skipped += 1
                log.append({"at": stamp, "kind": "name_correction_skipped", "game_id": game_id,
                            "reason": "handoff final score differs from the archived one",
                            "row": dict(row), "handoff": {k: result.get(k) for k in
                                                          ("home", "away", "home_score", "away_score")}})
                continue
            after = {side: names.get(str(result.get(side) or ""), str(result.get(side) or ""))
                     for side in ("home", "away")}
            before = {"home": row.get("home_name"), "away": row.get("away_name")}
            if before == after:
                continue
            log.append({"at": stamp, "kind": "team_name_correction", "game_id": game_id,
                        "partition": partition.as_posix(), "before": before, "after": after,
                        "handoff": {"home": result.get("home"), "away": result.get("away")},
                        "score": [row.get("home_score"), row.get("away_score")],
                        "reason": "handoff backfill matched an FCS team to an FBS school sharing "
                                  "its first word; score unchanged"})
            row["home_name"], row["away_name"] = after["home"], after["away"]
            corrected += 1
            changed = True
        if changed:
            game_archive._write_partition(partition, game_archive.GAME_FIELDS, rows)
    _log(log)
    return {"checked": checked, "corrected": corrected, "skipped": skipped}


def remove_foreign_ids(documents: Sequence[dict[str, Any]], comp: str = "NCAAM",
                       label: str = "ncaam") -> dict[str, int]:
    """Remove rows filed under the handoff's ESPN ids in seasons the pipeline owns."""
    foreign = {f"{comp.lower()}-{event_id}" for event_id in _results(documents, comp)}
    stamp = _now()
    log: list[dict[str, Any]] = []
    removed = twinned = 0
    comp_dir = game_archive.GAMES_DIR / comp.lower()
    for partition in sorted(comp_dir.glob("*.csv")) if comp_dir.exists() else []:
        rows = game_archive.read_partition(partition)
        doomed = [row for row in rows if row.get("source") == label and row.get("game_id") in foreign]
        if not doomed:
            continue
        keep = [row for row in rows if row not in doomed]
        if not keep:
            # The handoff's rows are the only record of this season; removing
            # them would leave nothing. Not this repair's case.
            continue
        twin_of: dict[str, str] = {}
        for one, two in game_archive.cross_id_duplicates(rows):
            for mine, theirs in ((one, two), (two, one)):
                if mine.get("game_id") in foreign and theirs.get("game_id") not in foreign:
                    twin_of.setdefault(str(mine["game_id"]), str(theirs["game_id"]))
        for row in doomed:
            twins = [twin_of[row["game_id"]]] if row["game_id"] in twin_of else []
            twinned += bool(twins)
            log.append({"at": stamp, "kind": "foreign_id_row_removed", "game_id": row["game_id"],
                        "partition": partition.as_posix(), "row": dict(row),
                        "pipeline_twin": twins[0] if twins else None,
                        "reason": "ESPN event id in a season archived under CBBD ids "
                                  "(one provider per competition-season)"})
            removed += 1
        game_archive._write_partition(partition, game_archive.GAME_FIELDS, keep)
    _log(log)
    return {"removed": removed, "with_pipeline_twin": twinned, "without": removed - twinned}


def _load(paths: Sequence[str]) -> list[dict[str, Any]]:
    documents = []
    for path in paths:
        with open(path, encoding="utf-8") as handle:
            documents.append(json.load(handle))
    return documents


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("repair", choices=("names", "foreign-ids"))
    parser.add_argument("--handoff", action="append", required=True,
                        help="a handoff document; repeatable, earliest first")
    args = parser.parse_args(argv)
    documents = _load(args.handoff)
    result = correct_names(documents) if args.repair == "names" else remove_foreign_ids(documents)
    print(json.dumps(result))
    report = game_archive.validate()
    for problem in report["problems"]:
        print(f"::error::{problem}")
    return 1 if report["problems"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
