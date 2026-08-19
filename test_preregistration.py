import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import preregistration
from preregistration import IMMUTABLE_TERMS, seal, terms_hash, validate


NOW = datetime(2026, 9, 1, tzinfo=timezone.utc)


def declaration(**overrides):
    payload = {
        "schema_version": 1,
        "competition": "NCAAM", "season": "2026-27",
        "hypothesis": "h", "target": "t",
        "primary_metric": "clv", "secondary_metric": "log loss",
        "minimum_fixtures": 400, "minimum_date_blocks": 40,
        "minimum_median_lock_lead_minutes": 60,
        "decision_rule": "evaluate once at season end",
        "registered_at": "2026-08-19T00:00:00Z",
        "artifact_freeze_deadline": "2026-11-01T00:00:00Z",
        "status": "declared_pending_artifact_freeze",
        "cohort": {"model_version": None, "artifact_sha256": None, "frozen_at": None},
        "notes": ["anything here is mutable"],
    }
    payload.update(overrides)
    return payload


def write(payload, *, sealed=True):
    handle = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
    if sealed and "terms_sha256" not in payload:
        payload["terms_sha256"] = terms_hash(payload)
    json.dump(payload, handle)
    handle.close()
    return Path(handle.name)


class SealTest(unittest.TestCase):
    def test_hash_ignores_mutable_fields(self):
        base = declaration()
        moved = declaration(status="armed", notes=["totally different"],
                            cohort={"artifact_sha256": "a" * 64, "frozen_at": "2026-10-01T00:00:00Z"})
        self.assertEqual(terms_hash(base), terms_hash(moved))

    def test_hash_is_order_independent(self):
        base = declaration()
        reordered = dict(reversed(list(base.items())))
        self.assertEqual(terms_hash(base), terms_hash(reordered))

    def test_every_immutable_term_changes_the_hash(self):
        base = terms_hash(declaration())
        for term in IMMUTABLE_TERMS:
            changed = declaration(**{term: "MUTATED"})
            self.assertNotEqual(terms_hash(changed), base, f"{term} did not affect the hash")

    def test_seal_writes_the_hash_and_is_idempotent(self):
        path = write(declaration(), sealed=False)
        first = seal(path)
        self.assertEqual(first, seal(path))

    def test_seal_refuses_to_launder_an_edited_declaration(self):
        path = write(declaration(), sealed=False)
        seal(path)
        payload = json.loads(path.read_text())
        payload["minimum_fixtures"] = 50
        path.write_text(json.dumps(payload))
        with self.assertRaises(SystemExit):
            seal(path)


class ValidateTest(unittest.TestCase):
    def test_sealed_declaration_pending_freeze_is_valid(self):
        result = validate(write(declaration()), now=NOW)
        self.assertEqual(result["state"], "declared_pending_artifact_freeze")
        self.assertTrue(result["valid"])

    def test_frozen_cohort_before_deadline_is_armed(self):
        payload = declaration()
        payload["cohort"] = {"artifact_sha256": "b" * 64, "frozen_at": "2026-10-15T00:00:00Z"}
        result = validate(write(payload), now=datetime(2026, 10, 20, tzinfo=timezone.utc))
        self.assertEqual(result["state"], "armed")

    def test_amending_a_sealed_term_voids_the_declaration(self):
        payload = declaration()
        payload["terms_sha256"] = terms_hash(payload)
        payload["minimum_fixtures"] = 50
        result = validate(write(payload, sealed=False), now=NOW)
        self.assertEqual(result["state"], "void")
        self.assertIn("void_amended_after_registration", result["reasons"])

    def test_changing_the_decision_rule_voids_it(self):
        payload = declaration()
        payload["terms_sha256"] = terms_hash(payload)
        payload["decision_rule"] = "upheld if any month looks good"
        self.assertEqual(validate(write(payload, sealed=False), now=NOW)["state"], "void")

    def test_mutable_fields_may_change_without_voiding(self):
        payload = declaration()
        payload["terms_sha256"] = terms_hash(payload)
        payload["status"] = "armed"
        payload["notes"] = ["revised commentary"]
        payload["cohort"] = {"artifact_sha256": "c" * 64, "frozen_at": "2026-10-01T00:00:00Z"}
        result = validate(write(payload, sealed=False), now=datetime(2026, 10, 5, tzinfo=timezone.utc))
        self.assertTrue(result["valid"])
        self.assertEqual(result["state"], "armed")

    def test_unsealed_declaration_is_invalid(self):
        payload = declaration()
        self.assertIn("terms_not_sealed",
                      validate(write(payload, sealed=False), now=NOW)["reasons"])

    def test_missing_deadline_without_frozen_cohort_is_invalid(self):
        payload = declaration()
        payload["cohort"] = {}
        result = validate(write(payload), now=datetime(2026, 11, 5, tzinfo=timezone.utc))
        self.assertIn("freeze_deadline_passed_without_frozen_cohort", result["reasons"])

    def test_cohort_frozen_after_the_deadline_is_invalid(self):
        payload = declaration()
        payload["cohort"] = {"artifact_sha256": "d" * 64, "frozen_at": "2026-11-20T00:00:00Z"}
        result = validate(write(payload), now=datetime(2026, 11, 25, tzinfo=timezone.utc))
        self.assertIn("cohort_frozen_after_deadline", result["reasons"])

    def test_malformed_artifact_hash_is_rejected(self):
        payload = declaration()
        payload["cohort"] = {"artifact_sha256": "nothex", "frozen_at": "2026-10-01T00:00:00Z"}
        self.assertIn("cohort_artifact_sha256_malformed",
                      validate(write(payload), now=NOW)["reasons"])

    def test_incomplete_terms_are_named(self):
        payload = declaration(decision_rule=None)
        result = validate(write(payload), now=NOW)
        self.assertTrue(any(r.startswith("incomplete_terms") for r in result["reasons"]))

    def test_missing_file_is_invalid_not_raised(self):
        self.assertFalse(validate(Path("/nonexistent/prereg.json"), now=NOW)["valid"])

    def test_future_registration_is_rejected(self):
        result = validate(write(declaration()), now=datetime(2026, 1, 1, tzinfo=timezone.utc))
        self.assertIn("registered_in_the_future", result["reasons"])


class ShippedDeclarationTest(unittest.TestCase):
    """The declaration committed to the repo must itself be valid."""

    def test_ncaam_declaration_is_sealed_and_valid(self):
        path = Path(__file__).with_name("ncaam_preregistration.json")
        result = validate(path, now=datetime.now(timezone.utc))
        self.assertTrue(result["valid"], result["reasons"])
        self.assertEqual(result["competition"], "NCAAM")

    def test_ncaam_declaration_freezes_before_the_season(self):
        payload = json.loads(
            Path(__file__).with_name("ncaam_preregistration.json").read_text(encoding="utf-8"))
        deadline = datetime.fromisoformat(
            payload["artifact_freeze_deadline"].replace("Z", "+00:00"))
        registered = datetime.fromisoformat(
            payload["registered_at"].replace("Z", "+00:00"))
        self.assertGreater(deadline, registered + timedelta(days=30))


if __name__ == "__main__":
    unittest.main()
