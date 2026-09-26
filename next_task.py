"""Derive the next development task for Matchday from the repository's own state.

The scheduled agent that develops this site needs a prompt. A fixed prompt is
the wrong shape: it says the same thing whether a promotion gate just came
a provider went dark, the interface audit found a defect, or nothing at all
happened, so the agent invents
work to fill the silence. This module instead reads the artifacts the hourly
run already produces (fetch failures, provider quota, the interface audit) and
emits *one* scoped task describing what the site actually needs right now --
or explicitly reports that nothing needs doing, which is a valid and common
answer.

Signals are ranked, not merged. Each candidate carries a fixed priority, and
only the highest-priority live candidate becomes the task; the rest are
reported as context so the agent can see what it is deliberately not doing.

Picks come from the Bet Better engine; this repository no longer forecasts,
so model research and promotion signals are not sources here.
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
    "fetch_failure": 30,
    "provider_quota": 40,
    # An interface blocker is a live defect for a real user right now --
    # keyboard focus that cannot be seen, text that cannot be read -- which
    # puts it above research questions and below anything actively breaking
    # the data the site exists to publish.
    "ui_blocker": 45,
    "ui_warn": 75,
}

def _load_json(path: Path) -> Any | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _candidate(kind: str, title: str, why: str, do: str,
               files: list[str], **extra: Any) -> dict[str, Any]:
    return {"kind": kind, "priority": PRIORITY[kind], "title": title,
            "why": why, "do": do, "files": files, **extra}


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
    # Attach where the budget actually went. A task that says "cfbd is empty"
    # sends someone to guess at cache windows; one that says "/games took 612
    # of 1000 calls" sends them to the line that spent it.
    spend = []
    for key, entry in sorted(state.items()):
        if not isinstance(entry, dict) or not isinstance(entry.get("spent"), int):
            continue
        top = entry.get("by_endpoint")
        if isinstance(top, dict) and top:
            ranked = sorted(top.items(), key=lambda kv: (-kv[1], kv[0]))[:4]
            spend.append(f"{key} spent {entry['spent']} this period ("
                         + ", ".join(f"{name} x{count}" for name, count in ranked) + ")")
        else:
            spend.append(f"{key} spent {entry['spent']} this period")
    advisory = [f"{key}: budget would have declined {entry['budget_would_decline']} call(s)"
                for key, entry in sorted(state.items())
                if isinstance(entry, dict)
                and isinstance(entry.get("budget_would_decline"), int)]
    why = "; ".join(starved)
    if spend:
        why += " | spend: " + "; ".join(spend)
    if advisory:
        why += " | " + "; ".join(advisory)
    return [_candidate(
        "provider_quota",
        f"{len(starved)} provider(s) at their safety reserve",
        why,
        "These providers are being refused before they fire, so the data they feed is "
        "degrading. Use the per-endpoint spend above to find what actually consumed the "
        "budget, then reduce that call's cadence or widen its cache window -- do not "
        "guess at a TTL. Never raise a reserve, relax quota_budget.json, or bypass the "
        "quota check to make calls succeed. If the budget is merely mis-shaped rather "
        "than overspent, say so and propose the allowance change instead of applying it.",
        ["provider_quota.py", "quota_budget.json", "multi_fetch.py",
         ".github/workflows/deploy.yml"])]


def _ui_candidates(base: Path) -> list[dict[str, Any]]:
    """Interface defects found against published accessibility requirements.

    The audit reports only rule violations, so the task can point at a file
    and a line. Judging whether the site looks current is deliberately part of
    the work, not part of the trigger -- a loop that fires on taste fires
    every hour forever.
    """
    report = _load_json(base / "ui_audit_report.json")
    if not isinstance(report, dict):
        return []
    findings = [item for item in report.get("findings") or [] if isinstance(item, dict)]
    if not findings:
        return []
    files = sorted({item.get("file") for item in findings if item.get("file")})
    candidates = []
    for kind, severity, label in (("ui_blocker", "blocker", "accessibility blocker"),
                                  ("ui_warn", "warn", "interface warning")):
        matching = [item for item in findings if item.get("severity") == severity]
        if not matching:
            continue
        leader = matching[0]
        candidates.append(_candidate(
            kind,
            f"Fix {len(matching)} {label}(s) starting at "
            f"{leader.get('file')}:{leader.get('line')}",
            "; ".join(f"{item.get('file')}:{item.get('line')} "
                      f"{item.get('rule')} -- {item.get('detail')}"
                      for item in matching[:3]),
            "Fix the reported violations at their source in the stylesheet or "
            "template, and re-run `python ui_audit.py` to confirm each one "
            "clears. Do not widen a threshold in ui_audit.py to make a "
            "finding go away -- if a rule is genuinely wrong, say why in the "
            "PR and leave the threshold for the owner. While you are in these "
            "files you may also report anything that looks dated or "
            "inconsistent, but ship only the reported fixes in this change; "
            "a redesign is a separate, discussed piece of work.",
            files + ["ui_audit.py"], finding=leader, count=len(matching)))
    return candidates


def collect(root: str | Path = ".") -> list[dict[str, Any]]:
    base = Path(root)
    candidates: list[dict[str, Any]] = []
    for source in (_fetch_failure_candidates, _quota_candidates, _ui_candidates):
        candidates.extend(source(base))
    return sorted(candidates, key=lambda item: (item["priority"], item["title"]))


# The exact test command `deploy.yml` runs, asserted against the workflow by
# test_next_task. This was a hand-maintained 30-name tuple mirroring a
# hand-maintained list in deploy.yml, because the guardrail once named four
# suites while CI ran twenty-seven: an agent that followed the prompt exactly
# ran a fraction of the tests its PR would be judged by, and nothing was
# watching for the divergence.
#
# Both lists became discovery on 2026-08-20 -- the enumeration was itself the
# defect. It fails open (a new test_*.py gates nothing until someone edits two
# files), and it had already drifted: 26 modules / 159 tests existed on disk
# that CI never ran, including the pick-lock and forecast-ledger suites. One
# command that means "all of them" cannot drift, so the three-way sync between
# this constant, deploy.yml, and AGENTS.md collapses to a string comparison.
REQUIRED_TEST_COMMAND = 'python -m unittest discover -p "test_*.py"'


GUARDRAILS = (
    "Work on the designated branch and open a pull request; never push to main.",
    "Never edit a quota reserve or quota enforcement.",
    "Run the full suite before opening the PR -- the same command deploy.yml "
    "runs, not a subset: " + REQUIRED_TEST_COMMAND,
    "Add a new updates/<build>.json release note and run python build_updates.py; never "
    "hand-edit updates.js.",
    "If the task turns out to need a judgement call the evidence cannot settle, stop and "
    "say so in the PR rather than guessing.",
)


def render_prompt(task: dict[str, Any] | None, others: list[dict[str, Any]]) -> str:
    if task is None:
        return ("No action needed. No competition fetch is failing, no provider is at its "
                "safety reserve, and the interface audit found nothing to fix. Do not invent "
                "work: reply that the site is healthy and stop.")
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
