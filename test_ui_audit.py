"""ui_audit.py: report interface defects that can be pointed at, and stay
silent about everything else.

The false-positive tests here matter more than the detection tests. A loop
that cries wolf is worse than no loop: the first run of this module reported
74 contrast "blockers", of which 74 were wrong, and a product loop fed that
report would have spent every hour sending an agent to fix legible badges.
Both original causes have a regression test below.
"""
import json
import os
import tempfile
import unittest
from pathlib import Path

import ui_audit


class ColorTests(unittest.TestCase):
    def test_hex_and_rgb_forms_parse(self):
        self.assertEqual(ui_audit._parse_color("#fff"), (255.0, 255.0, 255.0))
        self.assertEqual(ui_audit._parse_color("#000000"), (0.0, 0.0, 0.0))
        self.assertEqual(ui_audit._parse_color("rgb(58, 209, 122)"), (58.0, 209.0, 122.0))
        self.assertEqual(ui_audit._parse_color("white"), (255.0, 255.0, 255.0))

    def test_unresolvable_values_are_skipped_not_guessed(self):
        for value in ("currentColor", "linear-gradient(90deg,#fff,#000)",
                      "var(--nope)", "", "inherit"):
            self.assertIsNone(ui_audit._parse_color(value), value)

    def test_translucent_colors_are_not_flattened_to_opaque(self):
        """The 74-false-positive bug. A tint over an unknown ancestor is not
        a colour this can compare, and pretending otherwise compares a badge
        against itself."""
        self.assertIsNone(ui_audit._parse_color("rgba(58,209,122,.12)"))
        self.assertIsNone(ui_audit._parse_color("#3ad17a80"))
        self.assertEqual(ui_audit._parse_color("rgba(58,209,122,1)"), (58.0, 209.0, 122.0))

    def test_contrast_ratio_matches_wcag_reference_values(self):
        self.assertAlmostEqual(
            ui_audit.contrast_ratio((0, 0, 0), (255, 255, 255)), 21.0, places=2)
        self.assertAlmostEqual(
            ui_audit.contrast_ratio((255, 255, 255), (255, 255, 255)), 1.0, places=2)

    def test_var_references_resolve_through_the_palette(self):
        variables = {"--brand": "#112233", "--alias": "var(--brand)"}
        self.assertEqual(ui_audit._resolve_vars("var(--alias)", variables), "#112233")
        self.assertEqual(ui_audit._resolve_vars("var(--gone, #abc)", variables), "#abc")

    def test_var_resolution_survives_a_reference_cycle(self):
        variables = {"--a": "var(--b)", "--b": "var(--a)"}
        ui_audit._resolve_vars("var(--a)", variables)  # depth-capped, must not hang


class SelectorTests(unittest.TestCase):
    def test_subject_is_the_final_compound(self):
        self.assertEqual(ui_audit._subject(".pill.LIVE .blink"), ".blink")
        self.assertEqual(ui_audit._subject(".card > button"), "button")
        self.assertEqual(ui_audit._subject(".btn"), ".btn")

    def test_subject_keeps_every_arm_of_a_selector_list(self):
        self.assertEqual(ui_audit._subject(".a .btn, .c summary"), ".btn,summary")


class CssAuditTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(self._cleanup)

    def _cleanup(self):
        for path in sorted(self.dir.rglob("*"), reverse=True):
            path.unlink() if path.is_file() else path.rmdir()
        self.dir.rmdir()

    def _css(self, text, name="styles.css"):
        path = self.dir / name
        path.write_text(text, encoding="utf-8")
        return ui_audit.audit_css(path)

    def _rules_found(self, findings):
        return {item["rule"] for item in findings}

    def test_low_contrast_pair_is_reported(self):
        findings = self._css("a{color:#777777;background-color:#808080}")
        self.assertIn("contrast-below-floor", self._rules_found(findings))

    def test_adequate_contrast_is_silent(self):
        findings = self._css("a{color:#ffffff;background-color:#000000}")
        self.assertNotIn("contrast-below-floor", self._rules_found(findings))

    def test_tinted_badge_over_unknown_backdrop_is_not_reported(self):
        """Regression: `.etag.value` renders as green-on-near-black and was
        reported at 1.00:1 because the tint and the text share a hue."""
        findings = self._css(
            ":root{--win:#3ad17a}.etag.value{color:var(--win);"
            "background:rgba(58,209,122,.12)}")
        self.assertNotIn("contrast-below-floor", self._rules_found(findings))

    def test_decorative_child_of_an_interactive_ancestor_is_not_a_tap_target(self):
        """Regression: a 5px pulsing dot inside a pill is not what gets tapped."""
        findings = self._css(".pill.LIVE .blink{width:5px;height:5px}")
        self.assertNotIn("tap-target-undersized", self._rules_found(findings))

    def test_undersized_interactive_subject_is_reported(self):
        findings = self._css(".btn{height:16px}")
        self.assertIn("tap-target-undersized", self._rules_found(findings))

    def test_focus_outline_removed_without_replacement_is_a_blocker(self):
        findings = self._css(".btn:focus{outline:none}")
        self.assertIn("focus-indicator-removed", self._rules_found(findings))

    def test_focus_outline_removed_with_a_focus_visible_rule_is_accepted(self):
        """This codebase pairs the two 18 times; flagging the pair would make
        the report useless on the first run."""
        findings = self._css(
            ".btn:focus{outline:none}.btn:focus-visible{outline:2px solid #fff}")
        self.assertNotIn("focus-indicator-removed", self._rules_found(findings))

    def test_focus_outline_removed_with_a_box_shadow_ring_is_accepted(self):
        findings = self._css(".btn:focus{outline:none;box-shadow:0 0 0 3px #4cf}")
        self.assertNotIn("focus-indicator-removed", self._rules_found(findings))

    def test_animation_without_reduced_motion_is_reported(self):
        findings = self._css(".x{transition:color .2s}")
        self.assertIn("reduced-motion-unsupported", self._rules_found(findings))

    def test_animation_with_reduced_motion_is_accepted(self):
        findings = self._css(
            ".x{transition:color .2s}"
            "@media(prefers-reduced-motion:reduce){.x{transition:none}}")
        self.assertNotIn("reduced-motion-unsupported", self._rules_found(findings))

    def test_comments_do_not_shift_reported_line_numbers(self):
        findings = self._css("/* a\nb\nc */\na{color:#777777;background-color:#808080}")
        self.assertEqual(findings[0]["line"], 4)


class HtmlAuditTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(self._cleanup)

    def _cleanup(self):
        for path in sorted(self.dir.rglob("*"), reverse=True):
            path.unlink() if path.is_file() else path.rmdir()
        self.dir.rmdir()

    def _html(self, text):
        path = self.dir / "index.html"
        path.write_text(text, encoding="utf-8")
        return {item["rule"] for item in ui_audit.audit_html(path)}

    def test_missing_lang_is_reported(self):
        self.assertIn("html-lang-missing", self._html("<html><body></body></html>"))

    def test_present_lang_is_accepted(self):
        self.assertNotIn("html-lang-missing",
                         self._html('<html lang="en"><body></body></html>'))

    def test_blocked_pinch_zoom_is_reported(self):
        self.assertIn("viewport-zoom-blocked", self._html(
            '<html lang="en"><meta name="viewport" '
            'content="width=device-width, user-scalable=no"></html>'))

    def test_scalable_viewport_is_accepted(self):
        self.assertNotIn("viewport-zoom-blocked", self._html(
            '<html lang="en"><meta name="viewport" '
            'content="width=device-width, initial-scale=1.0, viewport-fit=cover"></html>'))

    def test_image_without_alt_is_reported(self):
        self.assertIn("img-alt-missing", self._html('<html lang="en"><img src="a.png"></html>'))

    def test_empty_alt_is_accepted_as_decorative(self):
        self.assertNotIn("img-alt-missing",
                         self._html('<html lang="en"><img src="a.png" alt=""></html>'))

    def test_image_without_dimensions_is_reported(self):
        self.assertIn("img-dimensions-missing",
                      self._html('<html lang="en"><img src="a.png" alt="x"></html>'))

    def test_image_with_dimensions_is_accepted(self):
        self.assertNotIn("img-dimensions-missing", self._html(
            '<html lang="en"><img src="a.png" alt="x" width="10" height="10"></html>'))

    def test_skipped_heading_level_is_reported(self):
        self.assertIn("heading-level-skipped",
                      self._html('<html lang="en"><h1>a</h1><h3>b</h3></html>'))

    def test_returning_to_a_higher_level_is_not_a_skip(self):
        self.assertNotIn("heading-level-skipped", self._html(
            '<html lang="en"><h1>a</h1><h2>b</h2><h3>c</h3><h2>d</h2></html>'))


class RenderBudgetTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(self._cleanup)

    def _cleanup(self):
        for path in sorted(self.dir.rglob("*"), reverse=True):
            path.unlink() if path.is_file() else path.rmdir()
        self.dir.rmdir()

    def _page(self, head):
        (self.dir / "index.html").write_text(
            f"<html lang='en'><head>{head}</head><body></body></html>", encoding="utf-8")

    def test_oversized_render_blocking_css_is_reported(self):
        (self.dir / "big.css").write_text(
            "a{}" * ui_audit.RENDER_BLOCKING_BUDGET_BYTES, encoding="utf-8")
        self._page('<link rel="stylesheet" href="big.css?v=1">')
        findings = ui_audit.audit_render_budget(self.dir)
        self.assertEqual([item["rule"] for item in findings],
                         ["render-blocking-over-budget"])

    def test_small_page_is_within_budget(self):
        (self.dir / "small.css").write_text("a{color:red}", encoding="utf-8")
        self._page('<link rel="stylesheet" href="small.css">')
        self.assertEqual(ui_audit.audit_render_budget(self.dir), [])

    def test_third_party_and_deferred_assets_are_not_counted(self):
        """Bytes this repo cannot change, and scripts that do not block paint,
        are not a budget the site can be held to."""
        (self.dir / "app.js").write_text(
            "x;" * ui_audit.RENDER_BLOCKING_BUDGET_BYTES, encoding="utf-8")
        self._page('<link rel="stylesheet" href="https://cdn.example/x.css">'
                   '<script defer src="app.js"></script>')
        self.assertEqual(ui_audit.audit_render_budget(self.dir), [])


class ReportTests(unittest.TestCase):
    def test_report_on_the_real_repository_is_serializable_and_sorted(self):
        report = ui_audit.build_report(Path(__file__).parent)
        self.assertEqual(report["schema_version"], ui_audit.SCHEMA_VERSION)
        self.assertIn("index.html", report["scanned"])
        json.dumps(report)
        severities = [ui_audit.SEVERITY_ORDER.get(item["severity"], 9)
                      for item in report["findings"]]
        self.assertEqual(severities, sorted(severities))

    def test_counts_agree_with_the_findings_list(self):
        report = ui_audit.build_report(Path(__file__).parent)
        self.assertEqual(
            report["blockers"],
            sum(1 for item in report["findings"] if item["severity"] == "blocker"))
        self.assertEqual(
            report["warnings"],
            sum(1 for item in report["findings"] if item["severity"] == "warn"))

    def test_a_clean_tree_produces_no_findings(self):
        """The quiet case has to actually be reachable, or the loop always
        has something to say and the agent always has work to invent."""
        empty = Path(tempfile.mkdtemp())
        self.addCleanup(empty.rmdir)
        report = ui_audit.build_report(empty)
        self.assertEqual(report["findings"], [])
        self.assertEqual(report["blockers"], 0)

    def test_fail_on_blocker_is_opt_in(self):
        root = str(Path(__file__).parent)
        temp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        temp.close()
        self.addCleanup(lambda: os.path.exists(temp.name) and os.unlink(temp.name))
        self.assertEqual(ui_audit.main(["--root", root, "--output", temp.name]), 0)
        with open(temp.name, encoding="utf-8") as handle:
            self.assertIn("findings", json.load(handle))


if __name__ == "__main__":
    unittest.main()
