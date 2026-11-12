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
  in a season the pipeline archives under CBBD ids. A row whose game CBBD
  already holds is removed; a row that is the only record of its game is
  relabelled `espn` and kept as a provisional placeholder until CBBD's copy is
  archived (`game_archive.retire_provisional`).
* `restore` -- re-adds, as provisional rows, the 215 games Build 1112T removed
  with no CBBD copy, read back from their own `corrections.jsonl` entries.

Both are idempotent: a second run finds nothing to change.

Usage:
    python archive_repair.py names --handoff trdlab_picks.json --handoff old.json
    python archive_repair.py foreign-ids --handoff trdlab_picks.json
    python archive_repair.py restore
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
from pathlib import Path
from typing import Any, Iterable, Sequence

import archive_backfill
import game_archive



def _results(documents: Iterable[dict[str, Any]], comp: str) -> dict[str, dict[str, Any]]:
    """Handoff results for `comp` by event id; an earlier document wins a tie."""
    found: dict[str, dict[str, Any]] = {}
    for document in documents:
        for result in document.get("results") or []:
            if str(result.get("competition") or "").upper() == comp and result.get("event_id"):
                found.setdefault(str(result["event_id"]), result)
    return found


def _log(entries: list[dict[str, Any]]) -> None:
    game_archive.record_corrections(entries)


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


# The label a handoff (ESPN-id) basketball row carries once it is known to be
# one. "ncaam" was the label it was written under, and that label aliases to
# CBBD, which is what hid it from overlap resolution.
PROVISIONAL_LABEL = "espn"


def remove_foreign_ids(documents: Sequence[dict[str, Any]], comp: str = "NCAAM",
                       label: str = "ncaam") -> dict[str, int]:
    """Remove ESPN-id copies of games the pipeline already holds under its own id.

    Only a row with a pipeline twin is removed. A row that is the only record
    of its game is kept and relabelled `espn`, which makes it a provisional
    placeholder that `game_archive.upsert_games` retires once CBBD's copy
    lands. Build 1112T removed those too, on the expectation that CBBD would
    re-record them, and basketball Results lost 215 finals in the meantime.
    """
    foreign = {f"{comp.lower()}-{event_id}" for event_id in _results(documents, comp)}
    stamp = _now()
    log: list[dict[str, Any]] = []
    removed = kept_alone = 0
    comp_dir = game_archive.GAMES_DIR / comp.lower()
    for partition in sorted(comp_dir.glob("*.csv")) if comp_dir.exists() else []:
        rows = game_archive.read_partition(partition)
        doomed = [row for row in rows if row.get("source") == label and row.get("game_id") in foreign]
        if not doomed:
            continue
        twin_of: dict[str, str] = {}
        for one, two in game_archive.cross_id_duplicates(rows):
            for mine, theirs in ((one, two), (two, one)):
                if mine.get("game_id") in foreign and theirs.get("game_id") not in foreign:
                    twin_of.setdefault(str(mine["game_id"]), str(theirs["game_id"]))
        keep = []
        for row in rows:
            if row not in doomed:
                keep.append(row)
            elif row["game_id"] in twin_of:
                log.append({"at": stamp, "kind": "foreign_id_row_removed", "game_id": row["game_id"],
                            "partition": partition.as_posix(), "row": dict(row),
                            "pipeline_twin": twin_of[row["game_id"]],
                            "reason": "ESPN-id copy of a game archived under its CBBD id "
                                      "(one provider per competition-season)"})
                removed += 1
            else:
                log.append({"at": stamp, "kind": "provisional_relabel", "game_id": row["game_id"],
                            "partition": partition.as_posix(), "before": row.get("source"),
                            "after": PROVISIONAL_LABEL,
                            "reason": "only record of this game; kept as a provisional row until "
                                      "CBBD's copy is archived. Label only, row otherwise unchanged"})
                keep.append(dict(row, source=PROVISIONAL_LABEL))
                kept_alone += 1
        game_archive._write_partition(partition, game_archive.GAME_FIELDS, keep)
    _log(log)
    return {"removed": removed, "kept_without_twin": kept_alone}


def restore_removed(log_path: Path | None = None) -> dict[str, int]:
    """Re-add rows Build 1112T removed although no pipeline copy existed.

    Read back from their own log entries, unchanged except for the
    provisional label. `upsert_games` retires any whose CBBD copy has since
    arrived, so this never re-creates a duplicate.
    """
    path = log_path or Path(game_archive.ARCHIVE_ROOT) / game_archive.CORRECTIONS_NAME
    entries = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    present = {str(row["game_id"]) for row in game_archive.load_games()}
    rows = [dict(entry["row"], source=PROVISIONAL_LABEL) for entry in entries
            if entry.get("kind") == "foreign_id_row_removed" and entry.get("pipeline_twin") is None
            and str(entry["game_id"]) not in present]
    if not rows:
        return {"restored": 0}
    before = {str(row["game_id"]) for row in game_archive.load_games()}
    game_archive.upsert_games(rows)
    after = {str(row["game_id"]) for row in game_archive.load_games()}
    restored = sorted((after - before) & {str(row["game_id"]) for row in rows})
    _log([{"at": _now(), "kind": "provisional_row_restored", "game_id": game_id,
           "reason": "removed in Build 1112T with no CBBD copy; restored as a provisional row "
                     "(Build 1112U)"} for game_id in restored])
    return {"restored": len(restored), "offered": len(rows)}


def _load(paths: Sequence[str]) -> list[dict[str, Any]]:
    documents = []
    for path in paths:
        with open(path, encoding="utf-8") as handle:
            documents.append(json.load(handle))
    return documents


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("repair", choices=("names", "foreign-ids", "restore"))
    parser.add_argument("--handoff", action="append", default=[],
                        help="a handoff document; repeatable, earliest first")
    args = parser.parse_args(argv)
    if args.repair != "restore" and not args.handoff:
        parser.error("--handoff is required for this repair")
    documents = _load(args.handoff)
    if args.repair == "names":
        result = correct_names(documents)
    elif args.repair == "foreign-ids":
        result = remove_foreign_ids(documents)
    else:
        result = restore_removed()
    print(json.dumps(result))
    report = game_archive.validate()
    for problem in report["problems"]:
        print(f"::error::{problem}")
    return 1 if report["problems"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
