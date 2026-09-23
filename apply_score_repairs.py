"""Settle finished scores onto on-disk payloads when the primary fetch is skipped.

score_fallback already runs inside fetch_data.py. When CFBD is quota-held,
multi_fetch skips the rewrite and that path never runs, so every past game
stays UPCOMING and the freshness alarm goes red every hour.

This writes the same finals onto data_ncaaf.json (handoff first, then the
scoreboard fallback) so the published board and the alarm see the same
settled games even when the fixture feed itself is not rebuilt.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import data_freshness
import score_fallback


PAYLOADS = (("ncaaf", "NCAAF", Path("data_ncaaf.json")),)


def _apply_handoff(matches: list[dict], results: list[dict]) -> int:
    import datetime

    settled = 0
    now = datetime.datetime.now(datetime.timezone.utc)
    for match in matches:
        if match.get("status") == "FINISHED":
            continue
        if not data_freshness._unsettled(match, now):
            continue
        if not data_freshness._settled_by_handoff(match, results):
            continue
        day = str(match.get("kickoff") or "")[:10]
        days = {day, data_freshness._shift_day(day, -1), data_freshness._shift_day(day, 1)}
        home = (match.get("home") or {}).get("name")
        away = (match.get("away") or {}).get("name")
        hit = None
        for row in results:
            if str(row.get("played_on") or "")[:10] not in days:
                continue
            if row.get("home_score") is None or row.get("away_score") is None:
                continue
            if data_freshness._name_strength(row.get("home"), home) == data_freshness.MATCH_NONE:
                continue
            if data_freshness._name_strength(row.get("away"), away) == data_freshness.MATCH_NONE:
                continue
            hit = row
            break
        if hit is None:
            continue
        try:
            from provider_adapters import normalized_score
            hs, aws = int(hit["home_score"]), int(hit["away_score"])
        except (TypeError, ValueError):
            continue
        match["status"] = "FINISHED"
        match["minute"] = None
        match["score"] = normalized_score(hs, aws, True)
        match["score_source"] = "betbetter handoff"
        settled += 1
    return settled


def repair_file(path: Path, competition: str) -> dict:
    report = {"path": str(path), "handoff": 0, "scoreboard": 0, "skipped": False}
    if not path.exists():
        report["skipped"] = True
        return report
    payload = json.loads(path.read_text(encoding="utf-8"))
    matches = payload.get("matches") or []
    results, _ = data_freshness.load_handoff_results()
    report["handoff"] = _apply_handoff(matches, results)
    board = score_fallback.settle(matches, competition)
    report["scoreboard"] = board.get("settled") or 0
    if report["handoff"] or report["scoreboard"]:
        tmp = path.with_suffix(path.suffix + ".repair.tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, path)
    return report


def main() -> int:
    for key, competition, path in PAYLOADS:
        report = repair_file(path, competition)
        print(
            f"score repairs [{key}]: handoff={report['handoff']} "
            f"scoreboard={report['scoreboard']} skipped={report['skipped']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
