"""Fail-closed publication gate for MLB fixture forecasts.

Three independent keys, each covering a distinct risk: model evidence (is the
forecast good enough), personnel data (is the starter data it reads
trustworthy -- or attested as unread), and a release review binding both.
"""

from __future__ import annotations

import json
import hashlib
from pathlib import Path
from typing import Any


POLICY_PATH = Path(__file__).with_name("mlb_recovery_policy.json")
PAUSE_MESSAGE = (
    "MLB picks are on hold while starting-pitcher coverage clears review."
)


def _sha256(value: Any) -> bool:
    text = str(value or "").lower()
    return len(text) == 64 and all(char in "0123456789abcdef" for char in text)


def _review_passed(value: Any, root: Path) -> bool:
    review = value if isinstance(value, dict) else {}
    if not (
        review.get("decision") == "passed"
        and review.get("reviewed_at")
        and review.get("reviewer")
        and _sha256(review.get("evidence_sha256"))
    ):
        return False
    evidence = (root / str(review.get("evidence_file") or "")).resolve()
    if evidence.parent != root or not evidence.is_file():
        return False
    return hashlib.sha256(evidence.read_bytes()).hexdigest() == str(
        review.get("evidence_sha256")
    ).lower()


def publication_decision(path: str | Path = POLICY_PATH,
                         incumbent: tuple[str, Any] | None = None) -> dict[str, Any]:
    """Return canonical eligibility; every malformed/incomplete state pauses."""
    source = Path(path).resolve()
    root = source.parent
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        payload = {}
    model = payload.get("model_gate") if isinstance(payload, dict) else {}
    personnel = payload.get("personnel_gate") if isinstance(payload, dict) else {}
    release = payload.get("release_review") if isinstance(payload, dict) else {}
    model = model if isinstance(model, dict) else {}
    personnel = personnel if isinstance(personnel, dict) else {}

    reasons = []
    if payload.get("schema_version") != 1:
        reasons.append("invalid_policy_schema")
    if payload.get("status") != "approved" or payload.get("publication_approved") is not True:
        reasons.append("publication_not_approved")
    model_review_ok = _review_passed(model.get("manual_review"), root)
    # The model gate has two routes, mirroring the personnel gate below.
    #
    # The challenger route promotes a new signal into production and must carry
    # the hash-bound §2 promotion policy, whose 500-paired-game bar exists to
    # stop an unproven signal from moving forecasts.
    #
    # The incumbent route publishes the already-deployed model at zero
    # challenger weight. Nothing is being promoted there, so §2's bar has
    # nothing to bind to: applying it anyway would withhold the incumbent's
    # forecasts -- the very baseline the challenger is measured against -- while
    # waiting for evidence about a signal that carries no weight.
    #
    # Fail closed in both directions: a missing, malformed, or non-boolean flag
    # is treated as a challenger promotion; the incumbent route still needs its
    # own signed, hash-bound review of the published model's measured evidence;
    # and it is contradicted outright if anything is approved for production
    # weight while it is in use.
    challenger_weighted = model.get("challenger_weighted") is not False
    promotion_ok = False
    if challenger_weighted:
        promotion_path = (root / str(model.get("promotion_policy") or "")).resolve()
        if promotion_path.parent == root and promotion_path.is_file():
            try:
                from mlb_model_promotion import load_mlb_promotion_policy
                approved_promotion = load_mlb_promotion_policy(promotion_path)
                promotion_ok = bool(
                    approved_promotion
                    and approved_promotion.get("verified_report_sha256")
                    == str((model.get("manual_review") or {}).get("evidence_sha256") or "").lower()
                )
            except (OSError, ValueError, TypeError):
                promotion_ok = False
    else:
        if model.get("promotion_policy"):
            reasons.append("challenger_zero_weight_contradicted_by_promotion")
        try:
            from mlb_model_promotion import load_mlb_promotion_policy
            promotion_ok = load_mlb_promotion_policy(root / "mlb_model_promotion.json") is None
        except (OSError, ValueError, TypeError):
            promotion_ok = False
    if model.get("status") != "approved" or not model_review_ok or not promotion_ok:
        reasons.append("model_evidence_not_approved")
    # The approval names the exact published artifact it reviewed. If the
    # incumbent later changes version or signal schema, the approval no longer
    # covers what would ship, and publication returns to paused until reviewed.
    if incumbent is not None:
        approved_incumbent = (str(model.get("incumbent_model_version") or ""),
                              model.get("incumbent_model_signal_schema"))
        if approved_incumbent != (str(incumbent[0]), incumbent[1]):
            reasons.append("incumbent_artifact_not_the_reviewed_one")
    # The personnel gate exists to stop unverified starter data from reaching a
    # forecast. It was originally evaluated unconditionally, which meant a
    # published model that consumes NO personnel feature was still blocked on a
    # confirmed-starter feed -- gating the incumbent on the correctness of data
    # it never reads. Since no contracted confirmed-personnel source exists
    # today (PROVIDER_COMPLIANCE.md; SportsGameOdds props are market-derived and
    # BALLDONTLIE has no confirmed lineups), that made resumption unreachable
    # for a reason unrelated to forecast quality.
    #
    # The gate now branches on whether personnel features actually carry weight.
    # It stays fail-closed in both directions: the coverage requirements apply
    # unless the policy explicitly attests zero personnel weight, a missing or
    # malformed flag is treated as weighted, and the zero-weight claim itself
    # still needs a signed, hash-bound review -- one that can actually be
    # produced today, because attesting that a feature family is unweighted is
    # verifiable from the model artifact alone.
    personnel_weighted = personnel.get("features_weighted") is not False
    if personnel_weighted:
        if (personnel.get("status") != "approved"
                or not personnel.get("confirmed_source")
                or not _review_passed(personnel.get("manual_review"), root)):
            reasons.append("confirmed_personnel_not_approved")
        try:
            coverage = float(personnel.get("both_starters_coverage_pct"))
            days = int(personnel.get("consecutive_days"))
            wrong_joins = int(personnel.get("wrong_fixture_or_team_joins"))
        except (TypeError, ValueError):
            coverage, days, wrong_joins = 0.0, 0, 1
        if coverage < 95.0 or days < 30 or wrong_joins != 0:
            reasons.append("confirmed_personnel_coverage_not_met")
        if personnel.get("stale_or_inferred_confirmation_observed") is not False:
            reasons.append("personnel_semantics_not_verified")
        personnel_review = personnel.get("manual_review")
    else:
        # Zero-weight route: nothing may claim confirmed personnel status, and
        # the attestation is the artifact the release review must bind to.
        if personnel.get("confirmed_source"):
            reasons.append("personnel_zero_weight_contradicted_by_source")
        if not _review_passed(personnel.get("zero_weight_attestation"), root):
            reasons.append("personnel_zero_weight_not_attested")
        personnel_review = personnel.get("zero_weight_attestation")
    model_evidence_sha = str((model.get("manual_review") or {}).get("evidence_sha256") or "").lower()
    personnel_review = personnel_review if isinstance(personnel_review, dict) else {}
    personnel_evidence_sha = str(personnel_review.get("evidence_sha256") or "").lower()
    if (not _review_passed(release, root)
            or str(release.get("model_evidence_sha256") or "").lower() != model_evidence_sha
            or str(release.get("personnel_evidence_sha256") or "").lower()
            != personnel_evidence_sha):
        reasons.append("release_review_not_approved")

    eligible = not reasons
    return {
        "state": "eligible" if eligible else "paused",
        "official_publication_eligible": eligible,
        "message": None if eligible else PAUSE_MESSAGE,
        "policy_version": payload.get("policy_version"),
        "reason": None if eligible else reasons[0],
        "reasons": reasons,
        "model_gate_status": model.get("status") or "missing",
        "personnel_gate_status": personnel.get("status") or "missing",
        "personnel_features_weighted": personnel_weighted,
        "model_challenger_weighted": challenger_weighted,
    }


def publication_eligible(path: str | Path = POLICY_PATH,
                         incumbent: tuple[str, Any] | None = None) -> bool:
    return publication_decision(path, incumbent)["official_publication_eligible"] is True
