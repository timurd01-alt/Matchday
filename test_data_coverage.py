"""data_coverage.py: report what the models asked for and did not get.

The silence tests carry as much weight as the detection tests. This report
feeds a loop that turns its top finding into work, so a gap reported for a
competition that is simply out of season, or reported twice under two names,
becomes an agent's afternoon.
"""
import datetime
import json
import tempfile
import unittest
from pathlib import Path

import data_coverage as dc

NOW = datetime.datetime(2026, 8, 19, 12, 0, tzinfo=datetime.timezone.utc)


def _match(hours_out=6, status="UPCOMING", **fields):
    kickoff = NOW + datetime.timedelta(hours=hours_out)
    match = {"status": status, "kickoff": kickoff.isoformat().replace("+00:00", "Z"),
             "markets": {}, "lineups": None, "injuries": {"home": [], "away": []},
             "h2h": [], "prediction": {"model": {"h": 50, "a": 50}}}
    match.update(fields)
    return match


def _payload(comp="EPL", matches=None, updated=NOW):
    return {"comp_key": comp,
            "updated": updated.isoformat() if updated else None,
            "matches": matches if matches is not None else []}


class TimeParsingTests(unittest.TestCase):
    def test_trailing_z_and_offsets_both_parse(self):
        self.assertIsNotNone(dc._parse_time("2026-08-19T12:00:00Z"))
        self.assertIsNotNone(dc._parse_time("2026-08-19T12:00:00+00:00"))

    def test_naive_timestamps_are_treated_as_utc(self):
        parsed = dc._parse_time("2026-08-19T12:00:00")
        self.assertEqual(parsed.tzinfo, datetime.timezone.utc)

    def test_unparseable_values_return_none(self):
        for value in ("", None, "not a date", 17):
            self.assertIsNone(dc._parse_time(value))


class HorizonTests(unittest.TestCase):
    def test_only_fixtures_inside_the_horizon_count(self):
        payload = _payload(matches=[_match(hours_out=6), _match(hours_out=500)])
        self.assertEqual(len(dc._imminent(payload, NOW)), 1)

    def test_finished_fixtures_are_not_imminent(self):
        payload = _payload(matches=[_match(hours_out=6, status="FINISHED")])
        self.assertEqual(dc._imminent(payload, NOW), [])

    def test_past_kickoffs_are_not_imminent(self):
        payload = _payload(matches=[_match(hours_out=-6)])
        self.assertEqual(dc._imminent(payload, NOW), [])


class InputGapTests(unittest.TestCase):
    def test_absent_family_below_the_floor_is_reported(self):
        payloads = {"EPL": _payload(matches=[_match() for _ in range(8)])}
        families = {gap["family"] for gap in dc.input_gaps(payloads, NOW)}
        self.assertIn("markets", families)

    def test_a_well_covered_family_is_silent(self):
        matches = [_match(markets={"h": 1.9, "a": 2.1}) for _ in range(8)]
        payloads = {"EPL": _payload(matches=matches)}
        families = {gap["family"] for gap in dc.input_gaps(payloads, NOW)}
        self.assertNotIn("markets", families)

    def test_a_thin_slate_is_not_measured_as_a_percentage(self):
        """Two fixtures cannot establish a coverage rate; reporting 0% off a
        sample of two sends an agent after noise."""
        payloads = {"EPL": _payload(matches=[_match(), _match()])}
        self.assertEqual(dc.input_gaps(payloads, NOW), [])

    def test_an_out_of_season_competition_is_never_reported(self):
        payloads = {"NBA": _payload("NBA", matches=[])}
        self.assertEqual(dc.input_gaps(payloads, NOW), [])

    def test_globally_unsourced_families_are_left_to_the_other_signal(self):
        """Regression: markets absent everywhere was reported once per
        competition AND once globally, and the per-competition wording blames
        a competition for a provider nobody ever wired up."""
        payloads = {"EPL": _payload(matches=[_match() for _ in range(8)])}
        families = {gap["family"]
                    for gap in dc.input_gaps(payloads, NOW, frozenset({"markets"}))}
        self.assertNotIn("markets", families)

    def test_a_missing_prediction_is_critical(self):
        matches = [_match(prediction={}) for _ in range(8)]
        payloads = {"EPL": _payload(matches=matches)}
        gaps = [gap for gap in dc.input_gaps(payloads, NOW)
                if gap["family"] == "prediction"]
        self.assertEqual(gaps[0]["severity"], "critical")


class FreshnessTests(unittest.TestCase):
    def test_a_stale_payload_with_imminent_fixtures_is_reported(self):
        stale = NOW - datetime.timedelta(hours=dc.FRESHNESS_BUDGET_HOURS + 5)
        payloads = {"EPL": _payload(matches=[_match()], updated=stale)}
        self.assertEqual([gap["kind"] for gap in dc.freshness_gaps(payloads, NOW)],
                         ["stale_feed"])

    def test_a_fresh_payload_is_silent(self):
        payloads = {"EPL": _payload(matches=[_match()], updated=NOW)}
        self.assertEqual(dc.freshness_gaps(payloads, NOW), [])

    def test_staleness_is_not_reported_out_of_season(self):
        """A payload nobody is publishing from is allowed to be old. NBA and
        NHL sit at zero fixtures for months."""
        ancient = NOW - datetime.timedelta(days=90)
        payloads = {"NHL": _payload("NHL", matches=[], updated=ancient)}
        self.assertEqual(dc.freshness_gaps(payloads, NOW), [])

    def test_an_unreadable_timestamp_is_reported(self):
        payloads = {"EPL": {"comp_key": "EPL", "updated": "whenever",
                            "matches": [_match()]}}
        gaps = dc.freshness_gaps(payloads, NOW)
        self.assertEqual(gaps[0]["severity"], "critical")


class UnsourcedFamilyTests(unittest.TestCase):
    def test_a_family_empty_everywhere_is_reported_once(self):
        payloads = {"EPL": _payload(matches=[_match()]),
                    "UCL": _payload("UCL", matches=[_match()])}
        gaps = [gap for gap in dc.unsourced_family_gaps(payloads)
                if gap["family"] == "markets"]
        self.assertEqual(len(gaps), 1)
        self.assertEqual(gaps[0]["competition"], "ALL")

    def test_one_populated_fixture_anywhere_clears_it(self):
        payloads = {"EPL": _payload(matches=[_match()]),
                    "UCL": _payload("UCL", matches=[_match(markets={"h": 2.0})])}
        families = {gap["family"] for gap in dc.unsourced_family_gaps(payloads)}
        self.assertNotIn("markets", families)

    def test_no_fixtures_at_all_reports_nothing(self):
        self.assertEqual(dc.unsourced_family_gaps({"NBA": _payload("NBA")}), [])


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(self._cleanup)

    def _cleanup(self):
        for path in sorted(self.dir.rglob("*"), reverse=True):
            path.unlink() if path.is_file() else path.rmdir()
        self.dir.rmdir()

    def _log(self, comp, graded, ungraded=0):
        rows = {f"g{i}": {"result": "h"} for i in range(graded)}
        rows.update({f"u{i}": {"result": None} for i in range(ungraded)})
        (self.dir / f"picks_log_{comp}.json").write_text(
            json.dumps(rows), encoding="utf-8")

    def test_a_competition_with_no_pick_log_is_reported(self):
        payloads = {"EPL": _payload(matches=[_match()])}
        gaps = dc.evidence_gaps(self.dir, payloads)
        self.assertEqual(gaps[0]["graded"], 0)

    def test_a_competition_below_the_bar_is_reported_with_its_count(self):
        self._log("epl", graded=4)
        payloads = {"EPL": _payload(matches=[_match()])}
        self.assertEqual(dc.evidence_gaps(self.dir, payloads)[0]["graded"], 4)

    def test_a_well_evidenced_competition_is_silent(self):
        self._log("epl", graded=dc.MIN_GRADED_FIXTURES + 1)
        payloads = {"EPL": _payload(matches=[_match()])}
        self.assertEqual(dc.evidence_gaps(self.dir, payloads), [])

    def test_ungraded_rows_do_not_count_towards_the_bar(self):
        self._log("epl", graded=2, ungraded=99)
        payloads = {"EPL": _payload(matches=[_match()])}
        self.assertEqual(dc.evidence_gaps(self.dir, payloads)[0]["graded"], 2)

    def test_a_competition_publishing_nothing_is_not_judged(self):
        payloads = {"NBA": _payload("NBA", matches=[])}
        self.assertEqual(dc.evidence_gaps(self.dir, payloads), [])


class ReportTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(self._cleanup)

    def _cleanup(self):
        for path in sorted(self.dir.rglob("*"), reverse=True):
            path.unlink() if path.is_file() else path.rmdir()
        self.dir.rmdir()

    def test_an_empty_tree_reports_no_gaps(self):
        report = dc.build_report(self.dir, NOW)
        self.assertEqual(report["gaps"], [])
        self.assertEqual(report["critical"], 0)

    def test_duplicate_payload_is_counted_once(self):
        """data.json is a copy of whichever competition built last; counting
        it separately double-reports that competition under its own key."""
        payload = _payload("MLB", matches=[_match()])
        (self.dir / "data_mlb.json").write_text(json.dumps(payload), encoding="utf-8")
        (self.dir / "data.json").write_text(json.dumps(payload), encoding="utf-8")
        self.assertEqual(dc.build_report(self.dir, NOW)["competitions"], ["MLB"])

    def test_gaps_are_sorted_critical_first(self):
        stale = NOW - datetime.timedelta(days=30)
        (self.dir / "data_epl.json").write_text(
            json.dumps(_payload("EPL", matches=[_match() for _ in range(8)],
                                updated=stale)), encoding="utf-8")
        report = dc.build_report(self.dir, NOW)
        order = [dc.SEVERITY_ORDER[gap["severity"]] for gap in report["gaps"]]
        self.assertEqual(order, sorted(order))

    def test_report_is_serializable_on_the_real_repository(self):
        report = dc.build_report(Path(__file__).parent, NOW)
        json.dumps(report)
        self.assertEqual(report["schema_version"], dc.SCHEMA_VERSION)

    def test_output_file_is_written(self):
        target = self.dir / "out.json"
        dc.main(["--root", str(self.dir), "--output", str(target)])
        self.assertIn("gaps", json.loads(target.read_text(encoding="utf-8")))


if __name__ == "__main__":
    unittest.main()
