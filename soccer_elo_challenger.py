"""Leakage-safe cross-season soccer Elo and draw-propensity research model."""

from __future__ import annotations

import hashlib
import json
import math
import random
import unicodedata
from collections import defaultdict
from datetime import datetime
from typing import Any, Iterable


MODEL_VERSION = "soccer-elo-cold-start-0.1.0"
DEFAULT_PARAMS = {"k": 24.0, "home_advantage": 60.0, "scale": 400.0,
                  "draw_base": 0.26, "draw_gap_slope": 0.14}


def normalize_team(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode()
    return " ".join("".join(ch if ch.isalnum() else " " for ch in text.lower()).split())


def _probabilities(home_rating: float, away_rating: float, params: dict[str, float]) -> dict[str, float]:
    scale = max(float(params["scale"]), 1.0)
    decisive_home = 1.0 / (1.0 + 10.0 ** (-(home_rating + params["home_advantage"] - away_rating) / scale))
    gap = abs(decisive_home - 0.5) * 2.0
    draw = min(0.34, max(0.10, params["draw_base"] - params["draw_gap_slope"] * gap))
    return {"h": (1.0 - draw) * decisive_home, "d": draw,
            "a": (1.0 - draw) * (1.0 - decisive_home)}


def _result(match: dict[str, Any]) -> str | None:
    winner = ((match.get("score") or {}).get("winner") or "").lower()
    return winner if winner in {"h", "d", "a"} else None


def replay(matches: Iterable[dict[str, Any]], params: dict[str, float], collect_season: int | None = None):
    ratings: dict[str, float] = {}
    games: dict[str, int] = defaultdict(int)
    rows = []
    last_played: dict[str, str] = {}
    for match in sorted(matches, key=lambda row: (row.get("kickoff") or "", row.get("competition") or "")):
        outcome = _result(match)
        if outcome is None:
            continue
        home, away = normalize_team(match["home"]["name"]), normalize_team(match["away"]["name"])
        home_rating, away_rating = ratings.get(home, 1500.0), ratings.get(away, 1500.0)
        probs = _probabilities(home_rating, away_rating, params)
        if collect_season is not None and int(match.get("season") or -1) == collect_season:
            rows.append({"fixture_id": str(match.get("id") or ""),
                         "competition": match.get("competition"), "kickoff": match.get("kickoff"),
                         "outcome": outcome, "probabilities": probs,
                         "home_games_before": games[home], "away_games_before": games[away]})
        actual = {"h": 1.0, "d": 0.5, "a": 0.0}[outcome]
        expected = probs["h"] + 0.5 * probs["d"]
        change = float(params["k"]) * (actual - expected)
        ratings[home], ratings[away] = home_rating + change, away_rating - change
        games[home] += 1; games[away] += 1
        day = str(match.get("kickoff") or "")[:10]
        last_played[home] = day; last_played[away] = day
    return rows, {"ratings": ratings, "games": dict(games), "last_played": last_played}


def metrics(rows: list[dict[str, Any]], probability_key: str = "probabilities") -> dict[str, Any]:
    if not rows:
        return {"n": 0, "log_loss": None, "brier": None, "accuracy": None}
    log_loss = brier = hits = 0.0
    for row in rows:
        probs, outcome = row[probability_key], row["outcome"]
        log_loss -= math.log(max(float(probs[outcome]), 1e-12))
        brier += sum((float(probs[key]) - int(key == outcome)) ** 2 for key in ("h", "d", "a"))
        hits += int(max(("h", "d", "a"), key=lambda key: probs[key]) == outcome)
    n = len(rows)
    return {"n": n, "log_loss": round(log_loss / n, 6),
            "brier": round(brier / n, 6), "accuracy": round(hits / n, 6)}


def _week(value: Any) -> str:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    iso = parsed.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def paired_week_interval(candidate: list[dict[str, Any]], baseline: list[dict[str, Any]], samples: int = 4000):
    baseline_index = {(row["competition"], row["fixture_id"]): row for row in baseline}
    grouped: dict[str, list[float]] = defaultdict(list)
    material = []
    for row in candidate:
        other = baseline_index.get((row["competition"], row["fixture_id"]))
        if not other:
            continue
        outcome = row["outcome"]
        delta = -math.log(max(row["probabilities"][outcome], 1e-12)) + math.log(
            max(other["probabilities"][outcome], 1e-12))
        grouped[_week(row["kickoff"])].append(delta)
        material.append(f"{row['competition']}:{row['fixture_id']}:{delta:.12f}")
    blocks = sorted(grouped)
    values = [value for block in blocks for value in grouped[block]]
    result = {"n": len(values), "blocks": len(blocks),
              "mean_log_loss_delta": round(sum(values) / len(values), 6) if values else None,
              "ci95": [None, None], "method": "deterministic kickoff-week block bootstrap"}
    if len(blocks) < 2:
        return result
    seed = int(hashlib.sha256("|".join(material).encode()).hexdigest()[:16], 16)
    rng, estimates = random.Random(seed), []
    for _ in range(samples):
        draw = [rng.choice(blocks) for _ in blocks]
        sample_values = [value for block in draw for value in grouped[block]]
        estimates.append(sum(sample_values) / len(sample_values))
    estimates.sort()
    result["ci95"] = [round(estimates[int(samples * .025)], 6),
                      round(estimates[min(int(samples * .975), samples - 1)], 6)]
    return result


def tune(matches: list[dict[str, Any]], validation_season: int = 2024) -> tuple[dict[str, float], dict[str, Any]]:
    best = None
    for k in (16.0, 24.0, 32.0):
        for home_advantage in (35.0, 55.0, 75.0):
            for scale in (320.0, 400.0, 480.0):
                for draw_base in (0.24, 0.27, 0.30):
                    for draw_gap_slope in (0.08, 0.14, 0.20):
                        params = {"k": k, "home_advantage": home_advantage, "scale": scale,
                                  "draw_base": draw_base, "draw_gap_slope": draw_gap_slope}
                        scored = metrics(replay(matches, params, validation_season)[0])
                        candidate = (scored["log_loss"], scored["brier"], params, scored)
                        if best is None or candidate[:2] < best[:2]:
                            best = candidate
    assert best is not None
    return best[2], best[3]


def source_hash(matches: list[dict[str, Any]]) -> str:
    material = [{"competition": row.get("competition"), "season": row.get("season"),
                 "id": row.get("id"), "kickoff": row.get("kickoff"),
                 "home": (row.get("home") or {}).get("name"),
                 "away": (row.get("away") or {}).get("name"), "score": row.get("score")}
                for row in sorted(matches, key=lambda item: (item.get("competition") or "", item.get("id") or ""))]
    raw = json.dumps(material, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
