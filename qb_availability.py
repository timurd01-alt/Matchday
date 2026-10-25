"""Collect public conference QB availability facts, independently of forecasts.

The endpoint is the public viewer embedded by the conference pages below.
Keep only names, statuses, matchup identities and timestamps: no report images,
medical explanations, branding, authenticated functions, or model adjustments.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import urllib.request
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

ENDPOINT = "https://app.hdintelligence.com/api/get-publish-public"
SOURCES = {
    "SEC": "https://www.secsports.com/fbreports",
    "B10": "https://bigten.org/sports/2026/9/10/FB_Availability_Reports.aspx",
    "ACC": "https://theacc.com/sports/2025/8/28/availability-reporting-football.aspx",
    "B12": "https://big12sports.com/FBReporting",
}
ZONES = {"CT": "America/Chicago", "ET": "America/New_York",
         "MT": "America/Denver", "PT": "America/Los_Angeles"}
STATUSES = {s.casefold(): s for s in (
    "Available", "Probable", "Questionable", "Doubtful", "Out",
    "Game Time Decision", "Out (1st Half)")}
LEDGER = Path("archive/availability/ncaaf.jsonl")
SNAPSHOT = Path("qb_availability_snapshot.json")
SCRIPT = Path("qb-availability.js")


def utc_time(day: object, clock: object, zone: object) -> str | None:
    try:
        name = ZONES[str(zone)]
        # The official viewer uses unpadded hours such as "9:30:00".
        value = None
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
            try:
                value = datetime.strptime(f"{day} {clock}", fmt)
                break
            except ValueError:
                pass
        if value is None:
            return None
        value = value.replace(tzinfo=ZoneInfo(name))
        return value.astimezone(timezone.utc).isoformat()
    except (KeyError, ValueError, ZoneInfoNotFoundError):
        return None


def fetch(conference: str) -> dict:
    body = json.dumps({"sport": "Football", "organization": conference,
                       "conference": conference}).encode()
    request = urllib.request.Request(ENDPOINT, data=body, method="POST", headers={
        "Content-Type": "application/json", "User-Agent": "MatchdayTerminal/1.0 (public availability facts)"})
    with urllib.request.urlopen(request, timeout=12) as response:
        raw = response.read(16 * 1024 * 1024 + 1)
    if len(raw) > 16 * 1024 * 1024:
        raise ValueError("Report response exceeds collection limit")
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("Public report response is not an object")
    return payload


def normalize(conference: str, payload: dict, observed_at: str) -> list[dict]:
    if conference not in SOURCES or not isinstance(payload, dict):
        raise ValueError("Unknown conference or report format")
    reports = []
    observed = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
    for report_id, raw in payload.items():
        if not isinstance(raw, dict):
            continue
        games = raw.get("games")
        if not isinstance(games, list) or len(games) != 2:
            continue
        zone = raw.get("conferenceTimeZone")
        footer = raw.get("footer") or {}
        published = utc_time(raw.get("publishDate"), raw.get("postedTime"), zone)
        kickoff = utc_time(footer.get("date"), footer.get("time"), zone)
        if not published or not kickoff or datetime.fromisoformat(published) > observed:
            continue
        teams = []
        for team in games:
            name = str(team.get("teamName") or team.get("teamDisplayName") or "").strip()
            if not name or len(name) > 100 or not isinstance(team.get("rows"), list):
                break
            qbs = []
            seen = set()
            for player in team["rows"]:
                if not isinstance(player, dict):
                    continue
                match = re.fullmatch(r"QB\s+#?(\d+)\s+(.{1,100})", str(player.get("name") or "").strip())
                if not match or str(player.get("exemptStatus")).casefold() == "exempt":
                    continue
                status = STATUSES.get(str(player.get("status") or "").strip().casefold(), "Unknown")
                identity = (match[1], match[2])
                if identity in seen:
                    continue
                seen.add(identity)
                qbs.append({"name": match[2], "jersey": match[1], "position": "QB", "status": status})
            teams.append({"name": name, "quarterbacks": qbs})
        if len(teams) != 2 or teams[0]["name"] == teams[1]["name"]:
            continue
        report = {"conference": conference, "report_id": str(report_id),
                  "source_url": SOURCES[conference], "report_type": str(raw.get("ReportType") or "Report"),
                  "published_at": published, "kickoff": kickoff,
                  "published_local": f"{raw.get('publishDate')} {raw.get('postedTime')} {zone}",
                  "teams": teams}
        report["content_sha256"] = hashlib.sha256(json.dumps(report, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        report["first_observed_at"] = observed_at
        report["observed_before_kickoff"] = observed < datetime.fromisoformat(kickoff)
        reports.append(report)
    return reports


def collect(ledger: Path = LEDGER, snapshot: Path = SNAPSHOT, script: Path = SCRIPT,
            getter=fetch, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    stamp = now.astimezone(timezone.utc).isoformat()
    old = {}
    if snapshot.exists():
        old = json.loads(snapshot.read_text(encoding="utf-8"))
    known, latest = set(), {}
    if ledger.exists():
        for line in ledger.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            known.add(row["content_sha256"])
            latest[(row["conference"], row["report_id"])] = row
    # A failed feed never erases the last collected report.
    sources, additions = {}, []
    def retrieve(conf):
        try:
            payload = getter(conf)
            rows = normalize(conf, payload, stamp)
            if payload and not rows:
                raise ValueError("No report with a verifiable timestamp and matchup")
            return conf, rows, None, len(payload)-len(rows)
        except Exception as error:
            return conf, [], type(error).__name__, 0
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(retrieve, SOURCES))
    for conf, rows, error, rejected in results:
        prior = (old.get("sources") or {}).get(conf) or {}
        sources[conf] = {"source_url": SOURCES[conf], "checked_at": stamp,
                         "state": "unavailable" if error else "ok",
                         "last_success_at": prior.get("last_success_at") if error else stamp,
                         "current_reports": len(rows), "error_kind": error}
        sources[conf]["rejected_reports"] = rejected
        for row in rows:
            key = (conf, row["report_id"])
            if row["content_sha256"] not in known:
                additions.append(row)
                known.add(row["content_sha256"])
            else:
                # Preserve original observation time on an unchanged report.
                row = latest.get(key, row)
            if key not in latest or row["published_at"] >= latest[key]["published_at"]:
                latest[key] = row
    if additions:
        ledger.parent.mkdir(parents=True, exist_ok=True)
        with ledger.open("a", encoding="utf-8", newline="\n") as f:
            for row in additions:
                f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    result = {"schema_version": 1, "generated_at": stamp, "prediction_weight": 0,
              "sources": sources, "reports": sorted(latest.values(), key=lambda r: (r["kickoff"], r["conference"], r["report_id"]))[-700:]}
    snapshot.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    script.write_text("// Official QB availability facts; never a forecast input.\nwindow.MATCHDAY_QB_AVAILABILITY=" +
                      json.dumps(result, ensure_ascii=True, separators=(",", ":")) + ";\n", encoding="utf-8", newline="\n")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", type=Path, default=LEDGER)
    parser.add_argument("--snapshot", type=Path, default=SNAPSHOT)
    parser.add_argument("--script", type=Path, default=SCRIPT)
    args = parser.parse_args()
    report = collect(args.ledger, args.snapshot, args.script)
    print(json.dumps({"reports": len(report["reports"]), "sources": {
        c: s["state"] for c, s in report["sources"].items()}, "prediction_weight": 0}))


if __name__ == "__main__":
    main()
