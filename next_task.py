"""Derive the next development task for Matchday from the repository's own state.

The scheduled agent that develops this site needs a prompt. A fixed prompt is
the wrong shape: it says the same thing whether a promotion gate just came
ready, a provider went dark, or nothing at all happened, so the agent invents
work to fill the silence. This module instead reads the artifacts the hourly
run already produces and emits *one* scoped task describing what the site
actually needs right now -- or explicitly reports that nothing needs doing,
which is a valid and common answer.

Signals are ranked, not merged. Each candidate carries a fixed priority, and
only the highest-priority live candidate becomes the task; the rest are
reported as context so the agent can see what it is deliberately not doing.

Deliberately excluded from every emitted task:

  * `ratings*.json` and `picks_log*.json` -- bot-owned, committed back to main
    by the hourly workflow (see AGENTS.md); a feature branch touching them goes
    stale within the hour.
  * promotion policy `requirements` blocks -- the frozen bar. An agent that can
    both build a challenger and lower the bar it must clear is not running an
    experiment. Status changes may be *proposed* with evidence; the bar itself
    is the owner's.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1

# Lower sorts first. Gaps left intentionally so a signal can be inserted
# between two existing ones without renumbering the rest.
PRIORITY = {
    "promotion_blocked": 10,
    "promotion_ready": 20,
    "fetch_failure": 30,
    "provider_quota": 40,
    "promotion_evidence_against": 50,
    "market_segment_loss": 60,
    "experiment_not_yet_run": 70,
}

# A model losing to the closing market by less than this (mean log loss, per
# fixture) is inside the noise a few dozen graded fixtures can produce. Chasing
# it invites exactly the post-hoc tuning `market_benchmark.py` warns about.
SEGMENT_LOSS_THRESHOLD = 0.02
SEGMENT_MIN_FIXTURES = 40


def _load_json(path: Path) -> Any | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _candidate(kind: str, title: str, why: str, do: str,
               files: list[str], **extra: Any) -> dict[str, Any]:
    return {"kind": kind, "priority": PRIORITY[kind], "title": title,
            "why": why, "do": do, "files": files, **extra}


def _promotion_candidates(base: Path) -> list[dict[str, Any]]:
    report = _load_json(base / "promotion_readiness.json")
    if not isinstance(report, dict):
        return []
    candidates = []
    for gate in report.get("gates") or []:
        state, gate_id = gate.get("state"), gate.get("id")
        files = [gate.get("policy_path"), gate.get("scorecard_path"),
                 "docs/PREDICTION_RESEARCH_ROADMAP.md", "docs/experiments.json"]
        files = [name for name in files if name]
        if state == "blocked":
            candidates.append(_candidate(
                "promotion_blocked",
                f"Unblock the {gate_id} promotion gate",
                gate.get("summary", ""),
                "The accumulated prospective evidence cannot satisfy this gate's frozen "
                "cohort requirement, so waiting longer collects nothing usable. Establish "
                "which identity is authoritative -- the policy's frozen values or the "
                "artifact actually producing locks -- and report the discrepancy with the "
                "exact hashes. Do NOT edit the policy's `requirements`; propose the "
                "correction and let the owner decide whether to re-freeze the policy or "
                "reset collection.",
                files, gate=gate_id))
        elif state in ("ready_for_manual_review", "ready"):
            candidates.append(_candidate(
                "promotion_ready",
                f"Prepare the {gate_id} promotion review",
                gate.get("summary", ""),
                "Every stated requirement is met. Write the review packet: observed metrics "
                "against each requirement, the paired interval, the cohort identity, and a "
                "recommendation. Record it in docs/experiments.json and the roadmap. "
                "Propose the policy `status` change in the PR body for the owner to accept "
                "-- do not promote, and do not change production_weight.",
                files, gate=gate_id))
        elif state == "evidence_against":
            candidates.append(_candidate(
                "promotion_evidence_against",
                f"Record the {gate_id} rejection",
                gate.get("summary", ""),
                "The sample-size bar was reached and the evidence does not support "
                "promotion. A rejection recorded honestly is a real result: add the "
                "decision to docs/experiments.json with the observed metrics and update "
                "the roadmap. Propose the policy status change; do not weaken the bar.",
                files, gate=gate_id))
    return candidates


def _fetch_failure_candidates(base: Path) -> list[dict[str, Any]]:
    failures = sorted(base.glob("fetch_failure_*.json"))
    if not failures:
        return []
    details = []
    for path in failures:
        payload = _load_json(path)
        if isinstance(payload, dict):
            details.append(f"{payload.get('comp', path.stem)} at {payload.get('at', '?')}: "
                           f"{str(payload.get('error', ''))[:200]}")
    return [_candidate(
        "fetch_failure",
        f"Repair {len(failures)} failing competition fetch(es)",
        "; ".join(details) or f"{len(failures)} fetch failure file(s) present",
        "A competition is not locking or grading picks. Reproduce the failure, fix the "
        "cause in the fetch/adapter code, and add a regression test. These files are "
        "cleared automatically by the next successful run, so do not delete them by hand.",
        [str(path.name) for path in failures] + ["fetch_data.py", "provider_adapters.py"])]


def _quota_candidates(base: Path) -> list[dict[str, Any]]:
    state = _load_json(base / "provider_quota_state.json")
    if not isinstance(state, dict):
        return []
    try:
        import provider_quota
    except ImportError:
        return []
    starved = []
    for key, entry in sorted(state.items()):
        spec = getattr(provider_quota, "PROVIDER_SPECS", {}).get(key)
        remaining = entry.get("remaining") if isinstance(entry, dict) else None
        if not spec or not isinstance(remaining, int):
            continue
        if remaining <= spec.get("reserve", 0):
            starved.append(f"{key}: {remaining} remaining vs {spec.get('reserve')} reserve "
                           f"(observed {entry.get('observed_at', '?')})")
    if not starved:
        return []
    return [_candidate(
        "provider_quota",
        f"{len(starved)} provider(s) at their safety reserve",
        "; ".join(starved),
        "These providers are being refused before they fire, so the data they feed is "
        "degrading. Check whether the cadence, cache windows, or call sites can be reduced "
        "to fit the real budget. Never raise a reserve or bypass the quota check to make "
        "calls succeed.",
        ["provider_quota.py", "multi_fetch.py", ".github/workflows/deploy.yml"])]


def _market_segment_candidates(base: Path) -> list[dict[str, Any]]:
    report = _load_json(base / "market_benchmark_report.json")
    if not isinstance(report, dict):
        return []
    worst = None
    for family, segments in (report.get("outcome_segments") or {}).items():
        if not isinstance(segments, dict):
            continue
        for label, entry in segments.items():
            if not isinstance(entry, dict):
                continue
            delta = entry.get("matchday_minus_market_log_loss")
            count = entry.get("n")
            if (isinstance(delta, (int, float)) and isinstance(count, int)
                    and count >= SEGMENT_MIN_FIXTURES and delta > SEGMENT_LOSS_THRESHOLD
                    and (worst is None or delta > worst["delta"])):
                worst = {"family": family, "label": label, "delta": delta, "n": count}
    if worst is None:
        return []
    return [_candidate(
        "market_segment_loss",
        f"Investigate the {worst['family']}={worst['label']} market gap",
        f"Matchday trails the closing market by {worst['delta']} mean log loss over "
        f"{worst['n']} graded fixtures in this segment.",
        "Investigate WHY this segment underperforms and write up the finding. Do not tune "
        "the model to the segment: the benchmark is descriptive, and fitting to it is the "
        "post-hoc adjustment the research protocol exists to prevent. Any model change "
        "must go through a frozen challenger and prospective evidence.",
        ["market_benchmark_report.json", "docs/PREDICTION_RESEARCH_ROADMAP.md",
         "docs/experiments.json"],
        segment=worst)]


def _experiment_candidates(base: Path) -> list[dict[str, Any]]:
    payload = _load_json(base / "docs" / "experiments.json")
    if not isinstance(payload, dict):
        return []
    pending = [item for item in payload.get("experiments") or []
               if isinstance(item, dict) and item.get("decision") == "not_yet_run"]
    if not pending:
        return []
    nominee = pending[0]
    return [_candidate(
        "experiment_not_yet_run",
        f"Run the {nominee.get('id', 'next')} experiment",
        f"{len(pending)} roadmap experiment(s) are recorded as not_yet_run. Next: "
        f"{nominee.get('hypothesis', '')}",
        "Follow the Hypothesis / Baseline / Experiment / Evaluation / Decision template in "
        "docs/PREDICTION_RESEARCH_ROADMAP.md. Build the challenger frozen and out-of-sample, "
        "record its artifact hash, and add it as a shadow at production_weight 0. Record the "
        "decision in docs/experiments.json. A challenger never ships in the same change that "
        "creates it.",
        ["docs/PREDICTION_RESEARCH_ROADMAP.md", "docs/experiments.json"],
        experiment=nominee.get("id"), pending_count=len(pending))]


def collect(root: str | Path = ".") -> list[dict[str, Any]]:
    base = Path(root)
    candidates: list[dict[str, Any]] = []
    for source in (_promotion_candidates, _fetch_failure_candidates, _quota_candidates,
                   _market_segment_candidates, _experiment_candidates):
        candidates.extend(source(base))
    return sorted(candidates, key=lambda item: (item["priority"], item["title"]))


GUARDRAILS = (
    "Work on the designated branch and open a pull request; never push to main.",
    "Never edit ratings*.json or picks_log*.json -- the hourly workflow owns them.",
    "Never edit a promotion policy's `requirements` block, reserve, or quota enforcement.",
    "Run the required suite before opening the PR: python -m unittest test_model_inputs "
    "test_provider_adapters test_generate_posts test_provider_quota",
    "Add a new updates/<build>.json release note and run python build_updates.py; never "
    "hand-edit updates.js.",
    "If the task turns out to need a judgement call the evidence cannot settle, stop and "
    "say so in the PR rather than guessing.",
)


def render_prompt(task: dict[str, Any] | None, others: list[dict[str, Any]]) -> str:
    if task is None:
        return ("No action needed. Matchday's promotion gates are collecting evidence on "
                "schedule, no competition fetch is failing, no provider is at its safety "
                "reserve, and no roadmap experiment is pending. Do not invent work: reply "
                "that the site is healthy and stop.")
    lines = [
        f"Task: {task['title']}",
        "",
        f"Why now: {task['why']}",
        "",
        f"What to do: {task['do']}",
        "",
        "Relevant files: " + ", ".join(task["files"]),
        "",
        "Guardrails:",
    ]
    lines.extend(f"  - {rule}" for rule in GUARDRAILS)
    if others:
        lines.extend(["", "Lower-priority signals you are deliberately NOT working on:"])
        lines.extend(f"  - [{item['kind']}] {item['title']}" for item in others)
    return "\n".join(lines)


def build_report(root: str | Path = ".") -> dict[str, Any]:
    candidates = collect(root)
    task = candidates[0] if candidates else None
    others = candidates[1:]
    return {"schema_version": SCHEMA_VERSION, "task": task, "deferred": others,
            "prompt": render_prompt(task, others)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", default=".")
    parser.add_argument("--json", action="store_true",
                        help="emit the full ranked report instead of the prompt text")
    parser.add_argument("--output", help="also write the report JSON to this path")
    args = parser.parse_args(argv)

    report = build_report(args.root)
    if args.output:
        Path(args.output).write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8", newline="\n")
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
          if args.json else report["prompt"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
