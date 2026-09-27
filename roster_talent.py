"""Roster talent tiers for NCAAF, from the 247Sports Team Talent Composite.

The expanded view's roster card showed "Even roster grade" for every team in
every game: its edge was hard-coded to zero after the in-house model (and the
CFBD talent fetch that fed it) was removed on 2026-09-25. This restores the one
licensed input it needs, at the smallest possible cost:

* one CollegeFootballData ``/talent`` request per season, and none once the
  season's tiers are stored (``roster_talent.json`` is committed);
* only a derived tier label per team is kept or published -- never the raw
  composite score (see ``docs/PROVIDER_COMPLIANCE.md``, 2026-09-27).

Tiers rank each FBS team's composite among FBS teams only, so an FCS roster
never shifts where an FBS program lands:

    Elite           top 10%
    Strong          next 20%
    Average         middle 40%
    Below average   next 20%
    Weak            bottom 10%
"""
from __future__ import annotations

import datetime as dt
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent
OUT = ROOT / "roster_talent.json"
SOURCE = "247Sports Team Talent Composite via CollegeFootballData"
TIERS = ((0.10, "Elite"), (0.30, "Strong"), (0.70, "Average"), (0.90, "Below average"), (1.01, "Weak"))
MIN_TEAMS = 100
# Short names that tie between schools and so cannot be matched by words alone.
ALIASES = {"Louisiana": "Louisiana Ragin' Cajuns"}


def _words(name: str) -> list[str]:
    return "".join(ch.lower() if ch.isalnum() else " " for ch in str(name or "")).split()


def match(short: str, full_names: list[str]) -> str | None:
    """CFBD's "Florida" to the handoff's "Florida Gators", word by word.

    Candidates are names that start with every word of the short name; the one
    with the fewest extra words wins, and only if it is unique. So "Florida"
    takes "Florida Gators" (one mascot word) over "Florida State Seminoles" or
    "Florida Atlantic Owls" (two), and "Alabama" still finds "Alabama Crimson
    Tide" when no shorter Alabama is rated.
    """
    want = _words(short)
    if not want:
        return None
    hits = [(len(_words(full)) - len(want), full) for full in full_names
            if _words(full)[:len(want)] == want]
    if not hits:
        return None
    best = min(extra for extra, _ in hits)
    top = [full for extra, full in hits if extra == best]
    return top[0] if len(top) == 1 else None


def fbs_names() -> list[str]:
    handoff = json.loads((ROOT / "betbetter_picks.json").read_text(encoding="utf-8"))
    rows = ((handoff.get("rankings") or {}).get("ncaaf") or {}).get("rankings") or []
    return [row["team_name"] for row in rows if row.get("team_name")]


def tiers_from(scores: dict[str, float], names: list[str]) -> dict[str, str]:
    matched = {}
    for short, score in scores.items():
        full = ALIASES.get(short) if ALIASES.get(short) in names else match(short, names)
        if full and score:
            matched[full] = float(score)
    ordered = sorted(matched, key=lambda team: -matched[team])
    out = {}
    for i, team in enumerate(ordered):
        share = (i + 0.5) / len(ordered)
        out[team] = next(label for cut, label in TIERS if share < cut)
    return out


def load() -> dict:
    try:
        return json.loads(OUT.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def refresh(season: int | None = None, adapter=None, scores: dict | None = None,
            composite_season: int | None = None) -> dict:
    """Fetch once per season; a stored season costs nothing.

    `scores` seeds the tiers from an already-licensed saved copy of the
    composite instead of a request (used 2026-09-27, when CFBD's month was
    spent and Bet Better held the 2025 composite from 2026-09-06).
    """
    season = season or dt.date.today().year
    current = load()
    if scores is None and current.get("season") == season and len(current.get("tiers") or {}) >= MIN_TEAMS:
        print(f"roster talent {season} already stored ({len(current['tiers'])} teams); no request")
        return current
    if scores is None and adapter is None:
        import fetch_data
        from provider_adapters import CollegeFootballDataAdapter
        adapter = CollegeFootballDataAdapter(fetch_data.CFBD_KEY, today=dt.date(season, 12, 31))
    if scores is None:
        scores = adapter.talent(seasons_back=1)
    tiers = tiers_from(scores or {}, fbs_names())
    if len(tiers) < MIN_TEAMS:
        print(f"roster talent: only {len(tiers)} FBS teams matched; keeping the stored file")
        return current
    document = {"season": season, "composite_season": composite_season or season, "source": SOURCE,
                "fetched_on": dt.date.today().isoformat(), "tiers": dict(sorted(tiers.items()))}
    OUT.write_text(json.dumps(document, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"roster talent {season}: {len(tiers)} FBS teams tiered")
    return document


def main() -> int:
    try:
        refresh()
    except Exception as exc:                      # noqa: BLE001 -- never block a deploy
        print(f"roster talent refresh deferred: {exc}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
