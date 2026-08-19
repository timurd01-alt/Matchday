import json
import tempfile
import unittest
from pathlib import Path

from next_task import GUARDRAILS, build_report, collect


def write(base, name, payload):
    path = Path(base) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def readiness(*gates):
    return {"schema_version": 1, "auto_promotion": False, "gates": list(gates)}


def gate(gate_id="mlb-run-strength-challenger", state="collecting"):
    return {"id": gate_id, "state": state, "summary": f"{gate_id}: {state}",
            "policy_path": "mlb_model_promotion.json",
            "scorecard_path": "mlb_prospective_scorecard.json"}


class NextTaskTest(unittest.TestCase):
    def test_quiet_repository_emits_an_explicit_no_op(self):
        with tempfile.TemporaryDirectory() as root:
            report = build_report(root)
        self.assertIsNone(report["task"])
        self.assertIn("No action needed", report["prompt"])
        self.assertIn("Do not invent work", report["prompt"])

    def test_collecting_gates_alone_produce_no_task(self):
        with tempfile.TemporaryDirectory() as root:
            write(root, "promotion_readiness.json", readiness(gate()))
            self.assertEqual(collect(root), [])

    def test_blocked_gate_outranks_a_ready_gate(self):
        with tempfile.TemporaryDirectory() as root:
            write(root, "promotion_readiness.json", readiness(
                gate("nfl-calibrated-elo", "ready_for_manual_review"),
                gate("mlb-run-strength-challenger", "blocked")))
            tasks = collect(root)
        self.assertEqual(tasks[0]["kind"], "promotion_blocked")
        self.assertEqual(tasks[1]["kind"], "promotion_ready")

    def test_fetch_failure_outranks_a_pending_experiment(self):
        with tempfile.TemporaryDirectory() as root:
            write(root, "fetch_failure_nfl.json",
                  {"comp": "NFL", "at": "2026-08-19T05:00:00Z", "error": "provider 503"})
            write(root, "docs/experiments.json",
                  {"experiments": [{"id": "e1", "decision": "not_yet_run", "hypothesis": "h"}]})
            tasks = collect(root)
        self.assertEqual(tasks[0]["kind"], "fetch_failure")
        self.assertIn("provider 503", tasks[0]["why"])
        self.assertEqual(tasks[1]["kind"], "experiment_not_yet_run")

    def test_only_the_top_candidate_becomes_the_task(self):
        with tempfile.TemporaryDirectory() as root:
            write(root, "promotion_readiness.json", readiness(gate(state="blocked")))
            write(root, "docs/experiments.json",
                  {"experiments": [{"id": "e1", "decision": "not_yet_run", "hypothesis": "h"}]})
            report = build_report(root)
        self.assertEqual(report["task"]["kind"], "promotion_blocked")
        self.assertEqual([item["kind"] for item in report["deferred"]],
                         ["experiment_not_yet_run"])
        self.assertIn("deliberately NOT working on", report["prompt"])

    def test_settled_experiments_are_not_proposed(self):
        with tempfile.TemporaryDirectory() as root:
            write(root, "docs/experiments.json", {"experiments": [
                {"id": "e1", "decision": "keep_production"},
                {"id": "e2", "decision": "reject"}]})
            self.assertEqual(collect(root), [])

    def test_narrow_market_gap_is_ignored_as_noise(self):
        with tempfile.TemporaryDirectory() as root:
            write(root, "market_benchmark_report.json", {"outcome_segments": {"competition": {
                "nfl": {"n": 200, "matchday_minus_market_log_loss": 0.001}}}})
            self.assertEqual(collect(root), [])

    def test_small_sample_market_gap_is_ignored(self):
        with tempfile.TemporaryDirectory() as root:
            write(root, "market_benchmark_report.json", {"outcome_segments": {"competition": {
                "nfl": {"n": 5, "matchday_minus_market_log_loss": 0.9}}}})
            self.assertEqual(collect(root), [])

    def test_worst_qualifying_market_segment_is_selected(self):
        with tempfile.TemporaryDirectory() as root:
            write(root, "market_benchmark_report.json", {"outcome_segments": {
                "competition": {"nfl": {"n": 100, "matchday_minus_market_log_loss": 0.05},
                                "mlb": {"n": 100, "matchday_minus_market_log_loss": 0.11}}}})
            tasks = collect(root)
        self.assertEqual(tasks[0]["segment"]["label"], "mlb")

    def test_market_task_forbids_fitting_to_the_segment(self):
        with tempfile.TemporaryDirectory() as root:
            write(root, "market_benchmark_report.json", {"outcome_segments": {"competition": {
                "nfl": {"n": 100, "matchday_minus_market_log_loss": 0.09}}}})
            self.assertIn("Do not tune the model to the segment", collect(root)[0]["do"])

    def test_promotion_tasks_propose_but_never_promote(self):
        with tempfile.TemporaryDirectory() as root:
            write(root, "promotion_readiness.json", readiness(
                gate(state="ready_for_manual_review"), gate("nfl", "evidence_against")))
            tasks = {item["kind"]: item for item in collect(root)}
        ready = tasks["promotion_ready"]["do"].lower()
        self.assertIn("do not promote", ready)
        self.assertIn("propose", ready)
        self.assertIn("do not change production_weight", ready)
        rejection = tasks["promotion_evidence_against"]["do"].lower()
        self.assertIn("do not weaken the bar", rejection)

    def test_provider_at_reserve_becomes_a_task(self):
        import provider_quota
        provider, spec = next(iter(provider_quota.PROVIDER_SPECS.items()))
        with tempfile.TemporaryDirectory() as root:
            write(root, "provider_quota_state.json", {provider: {
                "remaining": spec["reserve"], "observed_at": "2026-08-19T05:00:00Z"}})
            tasks = collect(root)
        self.assertEqual(tasks[0]["kind"], "provider_quota")
        self.assertIn(provider, tasks[0]["why"])
        self.assertIn("Never raise a reserve", tasks[0]["do"])

    def test_provider_above_reserve_is_not_a_task(self):
        import provider_quota
        provider, spec = next(iter(provider_quota.PROVIDER_SPECS.items()))
        with tempfile.TemporaryDirectory() as root:
            write(root, "provider_quota_state.json", {provider: {
                "remaining": spec["reserve"] + 500, "observed_at": "2026-08-19T05:00:00Z"}})
            self.assertEqual(collect(root), [])

    def test_unknown_provider_key_is_ignored(self):
        with tempfile.TemporaryDirectory() as root:
            write(root, "provider_quota_state.json", {"not_a_provider": {"remaining": 0}})
            self.assertEqual(collect(root), [])

    def test_unreadable_state_files_are_skipped_not_raised(self):
        with tempfile.TemporaryDirectory() as root:
            (Path(root) / "promotion_readiness.json").write_text("{not json", encoding="utf-8")
            (Path(root) / "market_benchmark_report.json").write_text("", encoding="utf-8")
            self.assertEqual(collect(root), [])

    def test_every_prompt_carries_the_guardrails(self):
        with tempfile.TemporaryDirectory() as root:
            write(root, "promotion_readiness.json", readiness(gate(state="blocked")))
            prompt = build_report(root)["prompt"]
        for rule in GUARDRAILS:
            self.assertIn(rule, prompt)

    def test_guardrails_protect_bot_owned_and_frozen_files(self):
        joined = " ".join(GUARDRAILS)
        self.assertIn("picks_log", joined)
        self.assertIn("ratings*.json", joined)
        self.assertIn("never push to main", joined)
        self.assertIn("`requirements`", joined)


if __name__ == "__main__":
    unittest.main()
