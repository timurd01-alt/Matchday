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

class ProductLoopSignalTests(unittest.TestCase):
    """The UI audit and the data-coverage report as ranked task sources.

    Both were added so the loop can act on the product itself, not only on the
    models. Their ranking is the substance: an interface blocker is a live
    defect and outranks research, while thin evidence and an unsourced feature
    family are decisions about what to build next and must never outrank a
    gate that is actively broken.
    """

    def _coverage(self, *gaps):
        return {"schema_version": 1, "gaps": list(gaps)}

    def _gap(self, kind="stale_feed", severity="critical", comp="EPL"):
        return {"kind": kind, "severity": severity, "competition": comp,
                "summary": f"{comp}: {kind} ({severity})"}

    def _audit(self, *findings):
        return {"schema_version": 1, "findings": list(findings)}

    def _finding(self, severity="blocker", rule="contrast-below-floor"):
        return {"rule": rule, "severity": severity, "file": "styles.css",
                "line": 1561, "detail": f"{rule} detail", "snippet": ".x"}

    def test_a_critical_data_gap_becomes_a_task(self):
        with tempfile.TemporaryDirectory() as root:
            write(root, "data_coverage_report.json", self._coverage(self._gap()))
            report = build_report(root)
        self.assertEqual(report["task"]["kind"], "data_gap_critical")
        self.assertIn("EPL", report["prompt"])

    def test_an_interface_blocker_becomes_a_task(self):
        with tempfile.TemporaryDirectory() as root:
            write(root, "ui_audit_report.json", self._audit(self._finding()))
            report = build_report(root)
        self.assertEqual(report["task"]["kind"], "ui_blocker")
        self.assertIn("styles.css:1561", report["prompt"])

    def test_a_broken_data_pipeline_outranks_an_interface_blocker(self):
        with tempfile.TemporaryDirectory() as root:
            write(root, "data_coverage_report.json", self._coverage(self._gap()))
            write(root, "ui_audit_report.json", self._audit(self._finding()))
            report = build_report(root)
        self.assertEqual(report["task"]["kind"], "data_gap_critical")
        self.assertIn("ui_blocker", [item["kind"] for item in report["deferred"]])

    def test_an_interface_blocker_outranks_a_pending_experiment(self):
        with tempfile.TemporaryDirectory() as root:
            write(root, "ui_audit_report.json", self._audit(self._finding()))
            write(root, "docs/experiments.json",
                  {"experiments": [{"id": "x", "decision": "not_yet_run"}]})
            report = build_report(root)
        self.assertEqual(report["task"]["kind"], "ui_blocker")

    def test_a_promotion_block_still_outranks_every_product_signal(self):
        with tempfile.TemporaryDirectory() as root:
            write(root, "promotion_readiness.json", readiness(gate(state="blocked")))
            write(root, "data_coverage_report.json", self._coverage(self._gap()))
            write(root, "ui_audit_report.json", self._audit(self._finding()))
            report = build_report(root)
        self.assertEqual(report["task"]["kind"], "promotion_blocked")

    def test_warn_level_signals_rank_below_critical_ones(self):
        with tempfile.TemporaryDirectory() as root:
            write(root, "data_coverage_report.json",
                  self._coverage(self._gap(kind="thin_evidence", severity="warn")))
            write(root, "ui_audit_report.json", self._audit(self._finding("warn")))
            report = build_report(root)
        kinds = [report["task"]["kind"]] + [item["kind"] for item in report["deferred"]]
        self.assertEqual(kinds, ["data_gap_warn", "ui_warn"])

    def test_empty_reports_produce_no_task(self):
        """A clean audit and a clean coverage report must leave the loop
        silent rather than manufacturing a low-priority errand."""
        with tempfile.TemporaryDirectory() as root:
            write(root, "ui_audit_report.json", self._audit())
            write(root, "data_coverage_report.json", self._coverage())
            report = build_report(root)
        self.assertIsNone(report["task"])
        self.assertIn("No action needed", report["prompt"])

    def test_malformed_reports_are_ignored_rather_than_crashing(self):
        with tempfile.TemporaryDirectory() as root:
            Path(root, "ui_audit_report.json").write_text("{oh no", encoding="utf-8")
            Path(root, "data_coverage_report.json").write_text("[]", encoding="utf-8")
            self.assertEqual(collect(root), [])

    def test_the_ui_task_forbids_moving_the_threshold_instead_of_fixing(self):
        with tempfile.TemporaryDirectory() as root:
            write(root, "ui_audit_report.json", self._audit(self._finding()))
            prompt = build_report(root)["prompt"]
        self.assertIn("Do not widen a threshold", prompt)

    def test_the_data_task_forbids_editing_the_measured_files(self):
        with tempfile.TemporaryDirectory() as root:
            write(root, "data_coverage_report.json", self._coverage(self._gap()))
            prompt = build_report(root)["prompt"]
        self.assertIn("changes the measurement rather than the problem", prompt)


class GuardrailTest(unittest.TestCase):
    def test_guardrails_protect_bot_owned_and_frozen_files(self):
        joined = " ".join(GUARDRAILS)
        self.assertIn("picks_log", joined)
        self.assertIn("ratings*.json", joined)
        self.assertIn("never push to main", joined)
        self.assertIn("`requirements`", joined)

class RequiredSuiteDriftTest(unittest.TestCase):
    """The prompt's test command must be the one CI actually runs.

    It named four suites while deploy.yml ran twenty-six. An agent following
    the guardrail exactly ran a fraction of the tests its PR would then be
    judged by, and nothing was watching the gap. Asserting the two against
    each other is what stops it reopening.

    Both sides are now a discovery command rather than an enumeration, so the
    remaining failure mode is one of them being narrowed back to a subset --
    which is exactly what these assertions catch.
    """

    def _workflow_test_command(self):
        import re
        text = Path(".github/workflows/deploy.yml").read_text(encoding="utf-8")
        match = re.search(r"run: (python -m unittest .+)", text)
        self.assertIsNotNone(match, "deploy.yml has no `python -m unittest` step")
        return match.group(1).strip()

    def test_required_command_matches_the_workflow(self):
        from next_task import REQUIRED_TEST_COMMAND
        self.assertEqual(REQUIRED_TEST_COMMAND, self._workflow_test_command())

    def test_the_guardrail_text_names_the_required_command(self):
        from next_task import GUARDRAILS, REQUIRED_TEST_COMMAND
        line = next(rule for rule in GUARDRAILS if "unittest" in rule)
        self.assertIn(REQUIRED_TEST_COMMAND, line)

    def test_the_workflow_runs_discovery_rather_than_a_named_subset(self):
        # The specific regression this guards: 26 modules / 159 tests sat on
        # disk gating nothing while CI ran a hand-typed list of 30 names.
        command = self._workflow_test_command()
        self.assertIn("discover", command)
        self.assertNotRegex(
            command,
            r"\btest_\w+\b",
            "deploy.yml names individual suites again; discovery is what keeps "
            "a newly added test_*.py from gating nothing by default",
        )

    def test_discovery_actually_finds_every_suite_on_disk(self):
        import unittest as _unittest
        on_disk = {p.stem for p in Path(".").glob("test_*.py")}
        found = set()
        stack = [_unittest.defaultTestLoader.discover(".", pattern="test_*.py")]
        while stack:
            item = stack.pop()
            if isinstance(item, _unittest.TestSuite):
                stack.extend(item)
            else:
                found.add(type(item).__module__)
        self.assertEqual(on_disk, found)


if __name__ == "__main__":
    unittest.main()
