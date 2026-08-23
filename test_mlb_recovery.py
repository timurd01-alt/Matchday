import json
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import mlb_recovery


def approved_policy(evidence_sha):
    review = {
        "decision": "passed", "reviewed_at": "2026-10-01T00:00:00Z",
        "reviewer": "independent-reviewer", "evidence_sha256": evidence_sha,
        "evidence_file": "evidence.json",
    }
    return {
        "schema_version": 1, "policy_version": "mlb-recovery-1",
        "status": "approved", "publication_approved": True,
        "model_gate": {"status": "approved", "promotion_policy": "promotion.json",
                       "manual_review": dict(review)},
        "personnel_gate": {
            "status": "approved", "confirmed_source": "contracted-source",
            "both_starters_coverage_pct": 95, "consecutive_days": 30,
            "wrong_fixture_or_team_joins": 0,
            "stale_or_inferred_confirmation_observed": False,
            "manual_review": dict(review),
        },
        "release_review": {**review, "model_evidence_sha256": evidence_sha,
                           "personnel_evidence_sha256": evidence_sha},
    }


class MLBRecoveryGateTests(unittest.TestCase):
    def decision(self, payload):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            evidence = root / "evidence.json"
            evidence.write_text("frozen evidence", encoding="utf-8")
            (root / "promotion.json").write_text("{}", encoding="utf-8")
            path = root / "policy.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            approved = {"verified_report_sha256": payload["model_gate"]
                        ["manual_review"]["evidence_sha256"]}
            with mock.patch("mlb_model_promotion.load_mlb_promotion_policy",
                            return_value=approved):
                return mlb_recovery.publication_decision(path)

    @staticmethod
    def policy():
        return approved_policy(hashlib.sha256(b"frozen evidence").hexdigest())

    def test_committed_policy_publishes_the_reviewed_incumbent_only(self):
        decision = mlb_recovery.publication_decision(incumbent=("v6-calibrated", 8))
        self.assertTrue(decision["official_publication_eligible"], decision["reasons"])
        self.assertFalse(decision["model_challenger_weighted"])
        self.assertFalse(decision["personnel_features_weighted"])

    def test_committed_policy_repauses_if_the_shipped_incumbent_changes(self):
        # The approval names the exact artifact it reviewed. A later model
        # version or signal schema is not what was signed off.
        for identity in (("v7-next", 8), ("v6-calibrated", 9)):
            decision = mlb_recovery.publication_decision(incumbent=identity)
            self.assertFalse(decision["official_publication_eligible"])
            self.assertIn("incumbent_artifact_not_the_reviewed_one", decision["reasons"])

    def test_all_three_reviews_and_coverage_are_required(self):
        decision = self.decision(self.policy())
        self.assertTrue(decision["official_publication_eligible"])
        for mutation in (
            lambda p: p["model_gate"].update(status="collecting"),
            lambda p: p["personnel_gate"].update(confirmed_source=None),
            lambda p: p["personnel_gate"].update(both_starters_coverage_pct=94.9),
            lambda p: p["personnel_gate"].update(wrong_fixture_or_team_joins=1),
            lambda p: p["personnel_gate"].update(stale_or_inferred_confirmation_observed=True),
            lambda p: p.pop("release_review"),
        ):
            payload = self.policy()
            mutation(payload)
            self.assertFalse(self.decision(payload)["official_publication_eligible"])

    def test_model_review_must_match_verified_promotion_report(self):
        payload = self.policy()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "evidence.json").write_text("frozen evidence", encoding="utf-8")
            (root / "promotion.json").write_text("{}", encoding="utf-8")
            path = root / "policy.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with mock.patch("mlb_model_promotion.load_mlb_promotion_policy",
                            return_value={"verified_report_sha256": "b" * 64}):
                self.assertFalse(mlb_recovery.publication_eligible(path))

    @staticmethod
    def zero_weight_policy():
        """Publication of a model that reads no personnel data at all.

        The original contract evaluated the confirmed-starter coverage
        requirements unconditionally, so the incumbent -- which consumes no
        personnel feature -- was blocked on the correctness of data it never
        reads, via a contracted source that does not exist today. The zero-
        weight route replaces the coverage evidence with a signed attestation
        that the weight really is zero; every other key is unchanged.
        """
        payload = MLBRecoveryGateTests.policy()
        attestation = dict(payload["personnel_gate"]["manual_review"])
        payload["personnel_gate"] = {
            "status": "not_required_zero_weight",
            "features_weighted": False,
            "confirmed_source": None,
            "zero_weight_attestation": attestation,
        }
        return payload

    def test_zero_weight_personnel_route_can_publish_without_a_confirmed_source(self):
        decision = self.decision(self.zero_weight_policy())
        self.assertTrue(decision["official_publication_eligible"])
        self.assertFalse(decision["personnel_features_weighted"])

    def test_zero_weight_route_still_fails_closed(self):
        for mutation in (
            # An unsigned or unverifiable attestation is not an exemption.
            lambda p: p["personnel_gate"].pop("zero_weight_attestation"),
            lambda p: p["personnel_gate"]["zero_weight_attestation"].update(decision="waived"),
            lambda p: p["personnel_gate"]["zero_weight_attestation"].update(reviewer=""),
            lambda p: p["personnel_gate"]["zero_weight_attestation"].update(
                evidence_sha256="c" * 64),
            # Claiming zero weight while also naming a confirmed source is
            # self-contradictory -- the policy must say which one is true.
            lambda p: p["personnel_gate"].update(confirmed_source="contracted-source"),
            # The release review still has to bind to the attestation hash.
            lambda p: p["release_review"].update(personnel_evidence_sha256="d" * 64),
        ):
            payload = self.zero_weight_policy()
            mutation(payload)
            self.assertFalse(self.decision(payload)["official_publication_eligible"])

    def test_absent_or_malformed_weight_flag_is_treated_as_weighted(self):
        # Fail-closed default: only an explicit `false` takes the zero-weight
        # route, so a typo or a missing field keeps the strict requirements.
        for flag in (None, "false", 0, "", "no"):
            payload = self.zero_weight_policy()
            if flag is None:
                payload["personnel_gate"].pop("features_weighted")
            else:
                payload["personnel_gate"]["features_weighted"] = flag
            decision = self.decision(payload)
            self.assertFalse(decision["official_publication_eligible"])
            self.assertTrue(decision["personnel_features_weighted"])
            self.assertIn("confirmed_personnel_not_approved", decision["reasons"])

    @staticmethod
    def incumbent_policy():
        """Publication of the already-deployed model at zero challenger weight.

        The §2 promotion bar exists to stop an unproven *signal* from moving
        forecasts. When nothing is promoted there is no such signal, and
        applying the bar anyway withholds the incumbent -- the very baseline the
        challenger is measured against -- over evidence about a signal that
        carries no weight. This route drops the promotion policy and binds the
        incumbent's own reviewed evidence instead.
        """
        payload = MLBRecoveryGateTests.zero_weight_policy()
        payload["model_gate"]["challenger_weighted"] = False
        payload["model_gate"]["promotion_policy"] = None
        return payload

    def incumbent_decision(self, payload, promotion=None):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "evidence.json").write_text("frozen evidence", encoding="utf-8")
            path = root / "policy.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with mock.patch("mlb_model_promotion.load_mlb_promotion_policy",
                            return_value=promotion):
                return mlb_recovery.publication_decision(path)

    def test_incumbent_route_publishes_without_a_promoted_challenger(self):
        decision = self.incumbent_decision(self.incumbent_policy())
        self.assertTrue(decision["official_publication_eligible"], decision["reasons"])
        self.assertFalse(decision["model_challenger_weighted"])

    def test_incumbent_route_still_fails_closed(self):
        # An approved promotion carrying production weight contradicts the claim
        # that no challenger is weighted -- the policy must say which is true.
        decision = self.incumbent_decision(
            self.incumbent_policy(), promotion={"verified_report_sha256": "b" * 64})
        self.assertFalse(decision["official_publication_eligible"])
        self.assertIn("model_evidence_not_approved", decision["reasons"])

        for mutation in (
            # Naming a promotion policy is the same contradiction.
            lambda p: p["model_gate"].update(promotion_policy="promotion.json"),
            # The incumbent route still needs its own signed, hash-bound review.
            lambda p: p["model_gate"].pop("manual_review"),
            lambda p: p["model_gate"]["manual_review"].update(decision="waived"),
            lambda p: p["model_gate"]["manual_review"].update(reviewer=""),
            lambda p: p["model_gate"]["manual_review"].update(evidence_sha256="c" * 64),
            lambda p: p["model_gate"].update(status="collecting"),
            # The release review still has to bind to that evidence hash.
            lambda p: p["release_review"].update(model_evidence_sha256="d" * 64),
        ):
            payload = self.incumbent_policy()
            mutation(payload)
            self.assertFalse(self.incumbent_decision(payload)["official_publication_eligible"])

    def test_absent_or_malformed_challenger_flag_is_treated_as_a_promotion(self):
        # Same fail-closed default as the personnel flag: only an explicit
        # `false` takes the incumbent route.
        for flag in (None, "false", 0, "", "no"):
            payload = self.incumbent_policy()
            if flag is None:
                payload["model_gate"].pop("challenger_weighted")
            else:
                payload["model_gate"]["challenger_weighted"] = flag
            decision = self.incumbent_decision(payload)
            self.assertFalse(decision["official_publication_eligible"])
            self.assertTrue(decision["model_challenger_weighted"])
            self.assertIn("model_evidence_not_approved", decision["reasons"])

    def test_missing_or_malformed_policy_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "missing.json"
            self.assertFalse(mlb_recovery.publication_eligible(path))
            path.write_text("not json", encoding="utf-8")
            self.assertFalse(mlb_recovery.publication_eligible(path))


if __name__ == "__main__":
    unittest.main()
