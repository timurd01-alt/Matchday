import json
import tempfile
import unittest
from pathlib import Path

from next_task import GUARDRAILS, build_report, collect


def write(base, name, payload):
    path = Path(base) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


class NextTaskTest(unittest.TestCase):
    def test_quiet_repository_emits_an_explicit_no_op(self):
        with tempfile.TemporaryDirectory() as root:
            report = build_report(root)
        self.assertIsNone(report["task"])
        self.assertIn("No action needed", report["prompt"])
        self.assertIn("Do not invent work", report["prompt"])

    def test_only_the_top_candidate_becomes_the_task(self):
        with tempfile.TemporaryDirectory() as root:
            write(root, "ui_audit_report.json", {"findings": [
                {"severity": "blocker", "rule": "contrast-below-floor", "file": "styles.css", "line": 1, "detail": "x"},
                {"severity": "warn", "rule": "typography-off-token", "file": "styles.css", "line": 2, "detail": "y"}]})
            report = build_report(root)
        self.assertEqual(report["task"]["kind"], "ui_blocker")
        self.assertEqual([item["kind"] for item in report["deferred"]], ["ui_warn"])
        self.assertIn("deliberately NOT working on", report["prompt"])

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
            (Path(root) / "provider_quota_state.json").write_text("{not json", encoding="utf-8")
            (Path(root) / "ui_audit_report.json").write_text("", encoding="utf-8")
            self.assertEqual(collect(root), [])

    def test_every_prompt_carries_the_guardrails(self):
        with tempfile.TemporaryDirectory() as root:
            write(root, "ui_audit_report.json", {"findings": [
                {"severity": "blocker", "rule": "contrast-below-floor", "file": "styles.css", "line": 1, "detail": "x"}]})
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

    def _audit(self, *findings):
        return {"schema_version": 1, "findings": list(findings)}

    def _finding(self, severity="blocker", rule="contrast-below-floor"):
        return {"rule": rule, "severity": severity, "file": "styles.css",
                "line": 1561, "detail": f"{rule} detail", "snippet": ".x"}

    def test_an_interface_blocker_becomes_a_task(self):
        with tempfile.TemporaryDirectory() as root:
            write(root, "ui_audit_report.json", self._audit(self._finding()))
            report = build_report(root)
        self.assertEqual(report["task"]["kind"], "ui_blocker")
        self.assertIn("styles.css:1561", report["prompt"])

    def test_warn_level_signals_rank_below_critical_ones(self):
        with tempfile.TemporaryDirectory() as root:
            write(root, "ui_audit_report.json",
                  self._audit(self._finding("warn"), self._finding("blocker")))
            report = build_report(root)
        kinds = [report["task"]["kind"]] + [item["kind"] for item in report["deferred"]]
        self.assertEqual(kinds, ["ui_blocker", "ui_warn"])

    def test_empty_reports_produce_no_task(self):
        """A clean audit must leave the loop silent rather than manufacturing
        a low-priority errand."""
        with tempfile.TemporaryDirectory() as root:
            write(root, "ui_audit_report.json", self._audit())
            report = build_report(root)
        self.assertIsNone(report["task"])
        self.assertIn("No action needed", report["prompt"])

    def test_malformed_reports_are_ignored_rather_than_crashing(self):
        with tempfile.TemporaryDirectory() as root:
            Path(root, "ui_audit_report.json").write_text("{oh no", encoding="utf-8")
            self.assertEqual(collect(root), [])

    def test_the_ui_task_forbids_moving_the_threshold_instead_of_fixing(self):
        with tempfile.TemporaryDirectory() as root:
            write(root, "ui_audit_report.json", self._audit(self._finding()))
            prompt = build_report(root)["prompt"]
        self.assertIn("Do not widen a threshold", prompt)

class GuardrailTest(unittest.TestCase):
    def test_guardrails_protect_main_and_quota(self):
        joined = " ".join(GUARDRAILS)
        self.assertIn("never push to main", joined)
        self.assertIn("quota reserve", joined)

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

    def _workflow_test_command(self, workflow="deploy.yml"):
        import re
        text = Path(".github/workflows", workflow).read_text(encoding="utf-8")
        match = re.search(r"run: (python -m unittest .+)", text)
        self.assertIsNotNone(match, f"{workflow} has no `python -m unittest` step")
        return match.group(1).strip()

    def _workflows_running_unittest(self):
        found = []
        for path in sorted(Path(".github/workflows").glob("*.yml")):
            if "python -m unittest" in path.read_text(encoding="utf-8"):
                found.append(path.name)
        return found

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

    def test_every_workflow_that_runs_tests_runs_the_same_command(self):
        # Two workflows run the suite now -- deploy.yml gates the deploy,
        # tests.yml gates branches and pull requests. A subset creeping into
        # either one reopens the original gap from the other side.
        workflows = self._workflows_running_unittest()
        self.assertIn("tests.yml", workflows)
        self.assertIn("deploy.yml", workflows)
        from next_task import REQUIRED_TEST_COMMAND
        for name in workflows:
            with self.subTest(workflow=name):
                self.assertEqual(self._workflow_test_command(name), REQUIRED_TEST_COMMAND)

    def test_branches_and_pull_requests_are_actually_gated(self):
        # The regression this guards: before tests.yml, deploy.yml triggered
        # only on schedule, workflow_dispatch and push to main, so a pull
        # request -- the path AGENTS.md mandates -- ran no tests at all, and
        # the first run against a change was the one already deploying it.
        text = Path(".github/workflows/tests.yml").read_text(encoding="utf-8")
        self.assertIn("pull_request:", text)
        self.assertIn("branches-ignore:", text)
        # and it must stay incapable of deploying or writing to the repo.
        # Checked against the executable lines only -- the header comment
        # explains what deploy.yml does, and naming `git push` there is not
        # the same as running it.
        self.assertIn("contents: read", text)
        directives = "\n".join(line for line in text.split("\n")
                               if not line.lstrip().startswith("#"))
        for forbidden in ("deploy-pages", "git push", "secrets."):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, directives)

    def test_discovery_actually_finds_every_suite_on_disk(self):
        import unittest as _unittest
        on_disk = {p.stem for p in Path("tests").glob("test_*.py")}
        found = set()
        stack = [_unittest.defaultTestLoader.discover(".", pattern="test_*.py")]
        while stack:
            item = stack.pop()
            if isinstance(item, _unittest.TestSuite):
                stack.extend(item)
            else:
                found.add(type(item).__module__.rsplit(".", 1)[-1])
        self.assertEqual(on_disk, found)


if __name__ == "__main__":
    unittest.main()
