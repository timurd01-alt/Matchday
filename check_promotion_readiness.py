"""Evaluate frozen promotion gates against the prospective evidence on disk.

Matchday already accumulates prospective evidence every hour (locked pregame
forecasts, graded results, rebuilt scorecards) and already states each model's
promotion bar as data in a policy file. Nothing previously compared the two:
`mlb_model_promotion.json` and `nfl_model_adjustment.json` both sit at
`collecting_prospective_evidence` and only a human reading two large JSON
reports side by side could tell whether the bar had been met, how far away it
was, or whether the accumulated evidence had been quietly invalidated by a
cohort change.

This module answers that question mechanically and writes
`promotion_readiness.json`. It is deliberately read-only with respect to the
gates: it never edits a policy, never promotes anything, and caps its most
positive verdict at `ready_for_manual_review` whenever the policy asks for
manual review. The scorecards' own `status` field checks only the sample-size
minimums; the extra conditions a policy states (exact cohort identity, the
paired interval's upper bound, Brier improvement) are checked here.

Four distinct states matter, because each calls for a different response:

  collecting            -- the bar is real and not yet met; wait.
  evidence_against      -- enough evidence, and it does not support promotion;
                           the honest next step is recording a rejection.
  blocked               -- the evidence cannot be used at all (the artifact or
                           the incumbent baseline drifted away from the cohort
                           the policy froze), so waiting longer accumulates
                           nothing. Needs a human decision now.
  ready_for_manual_review -- every stated requirement is met.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1

# Each gate names the policy file, the scorecard built from the matching
# ledger, and *which* pair of models the policy's requirements are actually
# about. That last part cannot be inferred: the MLB scorecard reports the raw
# challenger and the capped blend side by side, and the policy's
# production_weight/max_shift_points apply to the capped blend -- the thing
# that would really ship -- not to the raw challenger.
GATES: tuple[dict[str, Any], ...] = (
    {
        "id": "mlb-run-strength-challenger",
        "sport": "mlb",
        "policy_path": "mlb_model_promotion.json",
        "scorecard_path": "mlb_prospective_scorecard.json",
        "candidate_model": "capped_blend",
        "baseline_model": "official",
        "comparison_path": ("deployment_evaluation", "comparisons", "capped_blend_vs_official"),
        "block_minimum_key": "minimum_game_date_blocks",
        "block_unit": "game-date blocks",
        "policy_status_key": "status",
    },
    {
        "id": "nfl-calibrated-elo",
        "sport": "nfl",
        "policy_path": "nfl_model_adjustment.json",
        "scorecard_path": "nfl_prospective_scorecard.json",
        "candidate_model": "calibrated_elo",
        "baseline_model": "raw_elo",
        "comparison_path": ("comparisons", "calibrated_elo_vs_raw_elo"),
        "block_minimum_key": "minimum_kickoff_week_blocks",
        "block_unit": "kickoff-week blocks",
        "policy_status_key": "prospective_status",
    },
)

# Ordered worst-first. The overall verdict is the worst state any gate reached,
# which keeps "blocked" from being hidden behind a satisfied sample-size check.
# `policy_missing` leads because a gate whose policy file vanished is a broken
# configuration rather than a slow one; `evidence_missing` sits below
# `collecting` because it is the ordinary state of a cold checkout (the
# scorecards are gitignored and rebuilt from the Actions cache each run).
_STATE_ORDER = ("policy_missing", "blocked", "evidence_against", "collecting",
                "evidence_missing", "ready_for_manual_review", "ready")

# States that warrant a human looking now, as opposed to waiting for more hours
# of evidence to accumulate on their own.
_ACTIONABLE = ("policy_missing", "blocked", "evidence_against",
               "ready_for_manual_review", "ready")


def _load_json(path: Path) -> Any | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _dig(payload: Any, path: tuple[str, ...]) -> Any | None:
    for key in path:
        if not isinstance(payload, dict):
            return None
        payload = payload.get(key)
    return payload


def _requirements(policy: dict[str, Any], scorecard: dict[str, Any]) -> dict[str, Any]:
    """Policy requirements win; the scorecard's own contract fills the gaps.

    `nfl_model_adjustment.json` states no `requirements` block at all, so its
    sample-size bar comes from the scorecard's `evaluation_contract`. Reading
    the contract as a fallback rather than hardcoding 256/16 here means the
    gate cannot silently disagree with the module that computes the evidence.
    """
    contract = scorecard.get("evaluation_contract")
    merged = dict(contract) if isinstance(contract, dict) else {}
    stated = policy.get("requirements")
    if isinstance(stated, dict):
        merged.update(stated)
    return merged


def _check(name: str, state: str, detail: str, **extra: Any) -> dict[str, Any]:
    return {"check": name, "state": state, "detail": detail, **extra}


def _sample_checks(gate: dict[str, Any], requirements: dict[str, Any],
                   scorecard: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    progress: dict[str, Any] = {}

    observed_games = _dig(scorecard, ("models", gate["candidate_model"], "n"))
    minimum_games = requirements.get("minimum_games")
    if isinstance(minimum_games, int) and isinstance(observed_games, int):
        short = max(minimum_games - observed_games, 0)
        progress["games"] = {"observed": observed_games, "required": minimum_games, "short": short}
        checks.append(_check(
            "minimum_games", "collecting" if short else "ready",
            f"{observed_games} of {minimum_games} graded fixtures"
            + (f"; {short} short" if short else "; met"),
            observed=observed_games, required=minimum_games, short=short))
    else:
        checks.append(_check("minimum_games", "collecting",
                             "no graded prospective fixtures recorded yet"))
        progress["games"] = {"observed": observed_games or 0,
                             "required": minimum_games, "short": minimum_games}

    comparison = _dig(scorecard, tuple(gate["comparison_path"])) or {}
    observed_blocks = comparison.get("blocks")
    minimum_blocks = requirements.get(gate["block_minimum_key"])
    if isinstance(minimum_blocks, int) and isinstance(observed_blocks, int):
        short = max(minimum_blocks - observed_blocks, 0)
        progress["blocks"] = {"observed": observed_blocks, "required": minimum_blocks,
                              "short": short, "unit": gate["block_unit"]}
        checks.append(_check(
            gate["block_minimum_key"], "collecting" if short else "ready",
            f"{observed_blocks} of {minimum_blocks} {gate['block_unit']}"
            + (f"; {short} short" if short else "; met"),
            observed=observed_blocks, required=minimum_blocks, short=short))
    else:
        checks.append(_check(gate["block_minimum_key"], "collecting",
                             f"no {gate['block_unit']} recorded yet"))
        progress["blocks"] = {"observed": observed_blocks or 0, "required": minimum_blocks,
                              "short": minimum_blocks, "unit": gate["block_unit"]}
    return checks, progress


def _cohort_checks(requirements: dict[str, Any], policy: dict[str, Any],
                   scorecard: dict[str, Any]) -> list[dict[str, Any]]:
    """Compare the frozen identity in the policy against the evidence's own.

    A mismatch is `blocked`, not `collecting`: evidence paired against a
    different artifact or a different incumbent cannot be pooled, so more hours
    of collection add nothing until someone decides to reset or re-freeze. This
    is exactly the situation `mlb_model_promotion.json`'s own
    `baseline_cohort_note` records happening on 2026-08-18.
    """
    checks: list[dict[str, Any]] = []
    for requirement_key, policy_scope, scorecard_key, label in (
        ("exact_cohort_required", None, "cohort", "candidate cohort"),
        ("exact_incumbent_baseline_required", "baseline_cohort", "baseline_cohort",
         "incumbent baseline cohort"),
    ):
        fields = requirements.get(requirement_key)
        if not isinstance(fields, list) or not fields:
            continue
        expected_source = policy.get(policy_scope) if policy_scope else policy
        expected_source = expected_source if isinstance(expected_source, dict) else {}
        observed_source = scorecard.get(scorecard_key)
        observed_source = observed_source if isinstance(observed_source, dict) else {}
        mismatches = []
        unknown = []
        for field in fields:
            expected = expected_source.get(field)
            observed = observed_source.get(field)
            if observed is None:
                unknown.append(field)
            elif observed != expected:
                mismatches.append(f"{field}: policy {expected!r} vs evidence {observed!r}")
        if mismatches:
            checks.append(_check(requirement_key, "blocked",
                                 f"{label} drifted from the frozen policy -- "
                                 + "; ".join(mismatches), mismatches=mismatches))
        elif unknown:
            checks.append(_check(requirement_key, "collecting",
                                 f"{label} not yet observable in the evidence "
                                 f"({', '.join(unknown)})", pending_fields=unknown))
        else:
            checks.append(_check(requirement_key, "ready",
                                 f"{label} matches the frozen policy exactly"))
    return checks


def _statistical_checks(gate: dict[str, Any], requirements: dict[str, Any],
                        scorecard: dict[str, Any]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    comparison = _dig(scorecard, tuple(gate["comparison_path"])) or {}

    if requirements.get("paired_interval_upper_bound_below_zero"):
        interval = comparison.get("ci95")
        upper = interval[1] if isinstance(interval, list) and len(interval) == 2 else None
        if upper is None:
            checks.append(_check("paired_interval_upper_bound_below_zero", "collecting",
                                 "paired interval not estimable yet"))
        elif upper < 0:
            checks.append(_check("paired_interval_upper_bound_below_zero", "ready",
                                 f"95% upper bound {upper} is below zero", upper_bound=upper))
        else:
            checks.append(_check("paired_interval_upper_bound_below_zero", "evidence_against",
                                 f"95% upper bound {upper} is not below zero", upper_bound=upper))

    if requirements.get("brier_must_improve"):
        candidate = _dig(scorecard, ("models", gate["candidate_model"], "brier"))
        baseline = _dig(scorecard, ("models", gate["baseline_model"], "brier"))
        if candidate is None or baseline is None:
            checks.append(_check("brier_must_improve", "collecting",
                                 "Brier scores not computable yet"))
        elif candidate < baseline:
            checks.append(_check("brier_must_improve", "ready",
                                 f"candidate Brier {candidate} beats baseline {baseline}",
                                 candidate=candidate, baseline=baseline))
        else:
            checks.append(_check("brier_must_improve", "evidence_against",
                                 f"candidate Brier {candidate} does not beat baseline {baseline}",
                                 candidate=candidate, baseline=baseline))
    return checks


def evaluate_gate(gate: dict[str, Any], root: str | Path = ".") -> dict[str, Any]:
    base = Path(root)
    policy = _load_json(base / gate["policy_path"])
    scorecard = _load_json(base / gate["scorecard_path"])

    result: dict[str, Any] = {
        "id": gate["id"], "sport": gate["sport"],
        "policy_path": gate["policy_path"], "scorecard_path": gate["scorecard_path"],
        "candidate_model": gate["candidate_model"], "baseline_model": gate["baseline_model"],
        "auto_promotion": False,
    }
    if not isinstance(policy, dict):
        result.update({"state": "policy_missing", "checks": [], "progress": {},
                       "summary": f"{gate['policy_path']} is missing or unreadable"})
        return result

    result["policy_status"] = policy.get(gate["policy_status_key"])
    result["manual_review_required"] = bool(
        (policy.get("requirements") or {}).get("manual_review_required", True))

    if not isinstance(scorecard, dict):
        result.update({
            "state": "evidence_missing", "checks": [], "progress": {},
            "summary": f"{gate['scorecard_path']} has not been built yet; the hourly run "
                       "writes it once the matching ledger exists",
        })
        return result

    requirements = _requirements(policy, scorecard)
    checks, progress = _sample_checks(gate, requirements, scorecard)
    checks.extend(_cohort_checks(requirements, policy, scorecard))
    checks.extend(_statistical_checks(gate, requirements, scorecard))

    # Sample-size and cohort problems come first: a paired interval computed on
    # 40 of a required 500 fixtures is not evidence against anything, so it must
    # not be reported as `evidence_against` while collection is still pending.
    states = {check["state"] for check in checks}
    if "blocked" in states:
        state = "blocked"
    elif "collecting" in states:
        state = "collecting"
    elif "evidence_against" in states:
        state = "evidence_against"
    else:
        state = "ready_for_manual_review" if result["manual_review_required"] else "ready"

    result.update({"state": state, "checks": checks, "progress": progress,
                   "scorecard_status": scorecard.get("status"),
                   "summary": _summarize(state, gate, progress, checks)})
    return result


def _summarize(state: str, gate: dict[str, Any], progress: dict[str, Any],
               checks: list[dict[str, Any]]) -> str:
    if state == "blocked":
        reasons = "; ".join(check["detail"] for check in checks if check["state"] == "blocked")
        return f"{gate['id']}: accumulated evidence is unusable -- {reasons}"
    if state == "evidence_against":
        reasons = "; ".join(check["detail"] for check in checks
                            if check["state"] == "evidence_against")
        return (f"{gate['id']}: the bar was reached and the evidence does not support "
                f"promotion -- {reasons}")
    if state == "collecting":
        parts = []
        for key in ("games", "blocks"):
            entry = progress.get(key) or {}
            if entry.get("short"):
                parts.append(f"{entry['short']} more {entry.get('unit', 'graded fixtures')}")
        detail = " and ".join(parts) if parts else "more prospective evidence"
        return f"{gate['id']}: collecting -- needs {detail}"
    return (f"{gate['id']}: every stated requirement is met; a human decision is required "
            "because this gate never auto-promotes")


def build_report(root: str | Path = ".", gates: tuple[dict[str, Any], ...] = GATES) -> dict[str, Any]:
    evaluations = [evaluate_gate(gate, root) for gate in gates]
    ranked = [state for state in _STATE_ORDER
              if any(item["state"] == state for item in evaluations)]
    return {
        "schema_version": SCHEMA_VERSION,
        "auto_promotion": False,
        "note": "Read-only. This report never edits a promotion policy and never promotes a "
                "model; its most positive verdict is that a human review is now warranted.",
        "overall_state": ranked[0] if ranked else "evidence_missing",
        "actionable": sorted(item["id"] for item in evaluations
                             if item["state"] in _ACTIONABLE),
        "gates": evaluations,
    }


def write_report(path: str | Path, report: dict[str, Any]) -> None:
    Path(path).write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                          encoding="utf-8", newline="\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", default=".")
    parser.add_argument("--output", default="promotion_readiness.json")
    parser.add_argument("--fail-on-actionable", action="store_true",
                        help="exit non-zero when a gate needs a human decision "
                             "(off by default so the hourly deploy is never blocked)")
    args = parser.parse_args(argv)

    report = build_report(args.root)
    write_report(Path(args.root) / args.output, report)
    for gate in report["gates"]:
        print(f"  {gate['state']:<24} {gate.get('summary', gate['id'])}")
    return 1 if args.fail_on_actionable and report["actionable"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
