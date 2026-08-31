"""Build the small payload the landing board actually needs.

The "All sports" board is what every first-time visitor lands on, and it used to
be assembled in the browser by downloading every per-sport data file in full --
3.6 MB across a dozen requests to render one hero fixture and roughly sixteen
match cards. Most of that payload is per-match research detail that only the
expanded match view ever reads, plus seasons of fixtures the board never shows.

This writes board_summary.json: the same merged shape the browser used to build
for itself, minus the fields no board view reads and minus fixtures outside a
near-term window. The full per-sport files are untouched and still published --
the interface escalates to them the moment a visitor opens a match or leaves the
board, so nothing is lost, it is just no longer paid for up front.

Run after the fetch/grade steps have refreshed the data files:

    python build_board_summary.py --output board_summary.json
"""
from __future__ import annotations

import argparse
import datetime as dt
import gzip
import json
import os
from typing import Any

# Kept in step with ALL_SPORT_KEYS in app-1-core.js. A sport listed here but not
# published yet is skipped silently -- an off-season or not-yet-fetched file is a
# normal state, not an error.
SPORT_KEYS = [
    "wc", "ucl", "epl", "laliga", "seriea", "bundesliga", "ligue1",
    "nfl", "ncaaf", "ncaam", "nba", "mlb",
]
COLLEGE_BOARD_KEYS = {"ncaaf", "ncaam"}

# Per-match fields only the expanded match view reads (research-signals.js).
# Dropping them is where most of the saving comes from: on a recent NFL file
# these four accounted for roughly 835 KB of a 1.56 MB payload.
DETAIL_ONLY_FIELDS = {
    "advanced_metrics",
    "advanced_metrics_meta",
    "nfl_challenger_shadow",
    "mlb_challenger_shadow",
}

# How far either side of now a fixture has to fall to reach the board. Back far
# enough that the recent-results rail and "awaiting final" games stay populated,
# forward far enough that a between-seasons sport still has something to show
# (the board widens its own ranking window to 120 days in that case).
PAST_WINDOW_DAYS = 21
FUTURE_WINDOW_DAYS = 45

# Matches the per-competition cap the browser applied to merged news.
NEWS_PER_COMPETITION = 8

# aggregateScorecards() in app-3-panels.js keeps only the newest 80 picks and 20
# misses across all sports, so shipping every sport's complete pick log to the
# board is pure waste -- on a recent production snapshot MLB's alone was 2.7 MB
# of a 3.1 MB total. Keeping each sport's newest 80 guarantees the merged newest
# 80 is unchanged. The Scorecard view, which renders the real pick log, is in
# VIEWS_NEEDING_FULL_DATA and loads the full files anyway.
SCORECARD_PICKS_KEPT = 80
SCORECARD_MISSES_KEPT = 20

# Mirrors SPORT_LABELS in app-1-core.js. Used only for the news "feed" label the
# merged view showed beside each headline.
SPORT_LABELS = {
    "wc": "World Cup", "ucl": "Champions League", "epl": "Premier League",
    "laliga": "La Liga", "seriea": "Serie A", "bundesliga": "Bundesliga",
    "ligue1": "Ligue 1", "nfl": "NFL", "ncaaf": "College Football",
    "ncaam": "Men's College Basketball", "nba": "NBA", "mlb": "MLB",
}


def _kickoff_date(match: dict[str, Any]) -> dt.date | None:
    raw = str(match.get("kickoff") or "")[:10]
    if not raw:
        return None
    try:
        return dt.date.fromisoformat(raw)
    except ValueError:
        return None


def in_window(match: dict[str, Any], today: dt.date) -> bool:
    """Keep live games and anything inside the near-term window.

    A fixture with no parseable kickoff is kept rather than dropped: an unknown
    date is a data gap, and silently hiding the fixture would turn that gap into
    a missing game on the board.
    """
    if str(match.get("status") or "").upper() == "LIVE":
        return True
    kickoff = _kickoff_date(match)
    if kickoff is None:
        return True
    delta = (kickoff - today).days
    return -PAST_WINDOW_DAYS <= delta <= FUTURE_WINDOW_DAYS


def slim_match(match: dict[str, Any], comp: str) -> dict[str, Any]:
    out = {k: v for k, v in match.items() if k not in DETAIL_ONLY_FIELDS}
    # The browser stamped _comp during its own merge; do it here instead so the
    # summary is self-describing and the card can tag the competition.
    out["_comp"] = match.get("_comp") or comp
    return out


def slim_scorecard(scorecard: dict[str, Any]) -> dict[str, Any]:
    """Keep every aggregate number; trim only the two long row lists."""
    out = dict(scorecard)
    picks = out.get("picks")
    if isinstance(picks, list):
        newest = sorted(picks, key=lambda p: str(p.get("kickoff") or ""), reverse=True)
        out["picks"] = newest[:SCORECARD_PICKS_KEPT]
    misses = out.get("misses")
    if isinstance(misses, list):
        out["misses"] = misses[:SCORECARD_MISSES_KEPT]
    return out


def load_sport(key: str, root: str) -> dict[str, Any] | None:
    path = os.path.join(root, f"data_{key}.json")
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError) as exc:
        print(f"board_summary: skipping data_{key}.json ({exc})")
        return None


def build_summary(root: str = ".", today: dt.date | None = None) -> dict[str, Any]:
    today = today or dt.date.today()
    matches: list[dict[str, Any]] = []
    news: list[dict[str, Any]] = []
    scorecard_sources: list[dict[str, Any]] = []
    title_by_sport: list[dict[str, Any]] = []
    base: dict[str, Any] = {}
    latest = ""
    covered: list[str] = []

    for key in SPORT_KEYS:
        data = load_sport(key, root)
        if not data:
            continue
        covered.append(key)
        comp = data.get("comp_key") or key.upper()

        if not base:
            # Non-match scalars the merged view inherited from the first file it
            # saw. Kept to preserve behaviour, not because the board reads all
            # of them.
            base = {
                k: v for k, v in data.items()
                if k not in {"matches", "news", "scorecard", "standings", "third_race",
                             "scorers", "leaders", "title_odds", "bracket", "advancement",
                             "team_of_tournament", "weekly_awards", "bracketology"}
                and not isinstance(v, (list, dict))
            }

        for match in data.get("matches") or []:
            if key in COLLEGE_BOARD_KEYS and in_window(match, today):
                matches.append(slim_match(match, comp))

        label = SPORT_LABELS.get(key) or data.get("competition") or comp
        if key in COLLEGE_BOARD_KEYS:
            for article in (data.get("news") or [])[:NEWS_PER_COMPETITION]:
                item = dict(article)
                item["_comp"] = article.get("competition") or comp
                item["feed"] = label
                news.append(item)

        scorecard = data.get("scorecard")
        if scorecard:
            # aggregateScorecards() in app-3-panels.js reads whole datasets, not
            # bare scorecards, so hand it the shape it already knows.
            scorecard_sources.append({
                "comp_key": comp,
                "competition": data.get("competition") or label,
                "scorecard": slim_scorecard(scorecard),
            })

        updated = str(data.get("updated") or "")
        if updated > latest:
            latest = updated

        top = (data.get("title_odds") or [None])[0]
        if top:
            title_by_sport.append({
                "comp": comp,
                "label": label,
                "team": top.get("team"),
                "code": top.get("code"),
                "pct": top.get("pct"),
            })

    matches.sort(key=lambda m: str(m.get("kickoff") or ""))

    summary = dict(base)
    summary.update({
        "matches": matches,
        "news": news,
        "scorecard_sources": scorecard_sources,
        "title_by_sport": title_by_sport,
        "updated": latest,
        "competition": "All sports",
        "comp_key": "ALL",
        "sports": covered,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "window_days": {"past": PAST_WINDOW_DAYS, "future": FUTURE_WINDOW_DAYS},
    })
    return summary


def write_summary(summary: dict[str, Any], output: str) -> tuple[int, int]:
    payload = json.dumps(summary, separators=(",", ":"), ensure_ascii=False)
    with open(output, "w", encoding="utf-8") as handle:
        handle.write(payload)
    raw = len(payload.encode("utf-8"))
    packed = len(gzip.compress(payload.encode("utf-8")))
    return raw, packed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="board_summary.json")
    parser.add_argument("--root", default=".", help="directory holding the data_*.json files")
    args = parser.parse_args()

    summary = build_summary(args.root)
    if not summary["matches"] and not summary["scorecard_sources"]:
        # Refuse to publish an empty summary over a good one: the interface
        # falls back to merging the full files when this file is missing, which
        # is slow but correct, and that is the better failure.
        print("board_summary: no sport data found — leaving any existing summary in place")
        return 1

    raw, packed = write_summary(summary, args.output)
    print(
        f"board_summary: {len(summary['matches'])} matches across {len(summary['sports'])} sports "
        f"-> {args.output} ({raw/1024:.0f} KB raw, {packed/1024:.0f} KB gzipped)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
