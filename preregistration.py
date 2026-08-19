"""Validate a pre-registered forecasting target that cannot be amended later.

The reason most claims of "I beat the market" are worthless is not bad maths.
It is that the claimant decided what counted as success after seeing how it
went -- which sport, which season, which subset, which metric, what threshold.
Matchday already solved the hardest half of this problem: pregame locks and
append-only ledgers make the *evidence* tamper-evident. This module covers the
other half by making the *terms* tamper-evident too.

The immutable terms -- hypothesis, competition, season, metrics, minimum
sample, lock lead floor, and decision rule -- are hashed at registration into
`terms_sha256`. Any later edit to any of them changes the recomputed hash, and
the declaration is reported `void_amended_after_registration` rather than
quietly carrying on with new goalposts. Git history shows what changed and
when; this makes the change impossible to *not* notice.

Fields deliberately left outside the hash are the ones that must legitimately
change as the season runs: `status`, the frozen model `cohort` (filled in
before the first lock, never after), and free-text notes. The cohort gets its
own protection from the existing evidence machinery -- every lock records the
artifact hash that produced it, so a cohort that drifts from the declaration is
caught the same way `check_promotion_readiness.py` catches it today.

Seal a new declaration with `--seal`; validate one with `--check`.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1

# The declaration. Changing any of these after registration voids it, which is
# the entire point: they are what "success" means, fixed before any result.
IMMUTABLE_TERMS = (
    "competition", "season", "hypothesis", "target",
    "primary_metric", "secondary_metric",
    "minimum_fixtures", "minimum_date_blocks", "minimum_median_lock_lead_minutes",
    "decision_rule", "registered_at", "artifact_freeze_deadline",
)


def _canonical(payload: dict[str, Any]) -> bytes:
    """Serialize only the immutable terms, order-independently."""
    terms = {key: payload.get(key) for key in IMMUTABLE_TERMS}
    return json.dumps(terms, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def terms_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical(payload)).hexdigest()


def _time(value: Any) -> datetime | None:
    try:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def _is_sha256(value: Any) -> bool:
    text = str(value or "").lower()
    return len(text) == 64 and all(char in "0123456789abcdef" for char in text)


def validate(path: str | Path, *, now: datetime | None = None) -> dict[str, Any]:
    """Return the declaration's state. Every malformed or amended state is void."""
    now = now or datetime.now(timezone.utc)
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}

    reasons: list[str] = []
    if payload.get("schema_version") != SCHEMA_VERSION:
        reasons.append("invalid_schema_version")

    missing = [key for key in IMMUTABLE_TERMS if payload.get(key) in (None, "")]
    if missing:
        reasons.append(f"incomplete_terms:{','.join(missing)}")

    recorded = str(payload.get("terms_sha256") or "").lower()
    expected = terms_hash(payload)
    if not _is_sha256(recorded):
        reasons.append("terms_not_sealed")
    elif recorded != expected:
        # The declaration was edited after it was sealed. This is the failure
        # the whole module exists to catch, so it is named explicitly rather
        # than folded into a generic "invalid".
        reasons.append("void_amended_after_registration")

    registered = _time(payload.get("registered_at"))
    deadline = _time(payload.get("artifact_freeze_deadline"))
    if registered is None:
        reasons.append("unparseable_registered_at")
    elif registered > now:
        reasons.append("registered_in_the_future")
    if deadline is None:
        reasons.append("unparseable_artifact_freeze_deadline")
    elif registered is not None and deadline <= registered:
        reasons.append("freeze_deadline_not_after_registration")

    cohort = payload.get("cohort") if isinstance(payload.get("cohort"), dict) else {}
    frozen_at = _time(cohort.get("frozen_at"))
    artifact = cohort.get("artifact_sha256")
    cohort_frozen = bool(artifact) and frozen_at is not None
    if artifact and not _is_sha256(artifact):
        reasons.append("cohort_artifact_sha256_malformed")
    if cohort_frozen and deadline is not None and frozen_at > deadline:
        reasons.append("cohort_frozen_after_deadline")
    if (not cohort_frozen and deadline is not None and now > deadline):
        # The season's evidence would otherwise start accruing against a model
        # that was never named in advance -- exactly the hole this closes.
        reasons.append("freeze_deadline_passed_without_frozen_cohort")

    if reasons:
        state = "void" if any(reason.startswith("void_") for reason in reasons) else "invalid"
    elif cohort_frozen:
        state = "armed"
    else:
        state = "declared_pending_artifact_freeze"

    return {
        "state": state, "valid": not reasons, "reasons": reasons,
        "competition": payload.get("competition"), "season": payload.get("season"),
        "terms_sha256_recorded": recorded or None,
        "terms_sha256_expected": expected,
        "cohort_frozen": cohort_frozen,
        "artifact_freeze_deadline": payload.get("artifact_freeze_deadline"),
        "summary": _summarize(state, reasons, payload, cohort_frozen),
    }


def _summarize(state: str, reasons: list[str], payload: dict[str, Any],
               cohort_frozen: bool) -> str:
    label = f"{payload.get('competition') or '?'} {payload.get('season') or '?'}"
    if state == "void":
        return (f"{label}: VOID -- the sealed terms were changed after registration. "
                "A target edited after evidence exists proves nothing; open a new "
                "declaration instead of amending this one.")
    if state == "invalid":
        return f"{label}: not a valid declaration ({'; '.join(reasons)})"
    if cohort_frozen:
        return f"{label}: armed -- terms sealed and the model artifact is frozen"
    return (f"{label}: terms sealed; the model artifact must be frozen before "
            f"{payload.get('artifact_freeze_deadline')}")


def seal(path: str | Path) -> str:
    """Write terms_sha256 for a declaration. Refuses to reseal an existing one."""
    target = Path(path)
    payload = json.loads(target.read_text(encoding="utf-8"))
    existing = str(payload.get("terms_sha256") or "").lower()
    if _is_sha256(existing):
        if existing == terms_hash(payload):
            return existing
        raise SystemExit(
            "refusing to reseal: this declaration is already sealed and its terms have "
            "changed. Resealing would launder exactly the post-hoc edit the seal exists "
            "to expose. Open a new declaration instead."
        )
    payload["terms_sha256"] = terms_hash(payload)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8", newline="\n")
    return payload["terms_sha256"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("path")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--seal", action="store_true", help="record terms_sha256 once")
    group.add_argument("--check", action="store_true",
                       help="exit non-zero if the declaration is invalid or void")
    args = parser.parse_args(argv)

    if args.seal:
        print(f"sealed {args.path} terms_sha256={seal(args.path)}")
        return 0
    result = validate(args.path)
    print(f"  {result['state']:32} {result['summary']}")
    return 1 if (args.check and not result["valid"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
