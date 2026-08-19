import json
import tempfile
import unittest
from pathlib import Path

from independent_value import (MIN_DATE_BLOCKS, MIN_FIXTURES, build_report,
                               extract_rows, summarize)


def pick(fixture_id="f1", competition="MLB", probs=(60, 0, 40), market=(55, 0, 45),
         result="h", kickoff="2026-08-01T23:00:00Z", market_pick=None, drop_market=False):
    record = {"fixture_id": fixture_id, "competition": competition, "kickoff": kickoff,
              "result": result, "pick": "h" if probs[0] >= probs[2] else "a",
              "probs": {"h": probs[0], "d": probs[1], "a": probs[2]}}
    if not drop_market:
        record["market_snapshot"] = {"h": market[0], "d": market[1], "a": market[2]}
    if market_pick:
        record["market_pick"] = market_pick
    return record


def write(records):
    handle = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False,
                                         prefix="picks_log_test")
    json.dump(records, handle)
    handle.close()
    return Path(handle.name)


def many(count, *, agree=True, model_right=True, blocks=None):
    blocks = blocks or count
    records = []
    for index in range(count):
        day = 1 + (index % blocks)
        model = (60, 0, 40)
        market = (55, 0, 45) if agree else (40, 0, 60)
        result = "h" if model_right else "a"
        records.append(pick(f"f{index}", probs=model, market=market, result=result,
                            kickoff=f"2026-08-{day:02d}T23:00:00Z"))
    return records


class ExtractTest(unittest.TestCase):
    def test_graded_pick_with_market_is_kept(self):
        rows, _ = extract_rows([write([pick()])])
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["agrees"])
        self.assertTrue(rows[0]["model_correct"])

    def test_ungraded_picks_are_excluded(self):
        rows, excluded = extract_rows([write([pick(result=None)])])
        self.assertEqual(rows, [])
        self.assertEqual(excluded["ungraded"], 1)

    def test_missing_model_probabilities_are_excluded(self):
        record = pick()
        record["probs"] = {"h": 0, "d": 0, "a": 0}
        rows, excluded = extract_rows([write([record])])
        self.assertEqual(rows, [])
        self.assertEqual(excluded["missing_model_read"], 1)

    def test_row_without_market_probabilities_is_kept_for_the_agreement_split(self):
        """The headline question needs only the market's pick."""
        rows, excluded = extract_rows([write([pick(drop_market=True, market_pick="h")])])
        self.assertEqual(len(rows), 1)
        self.assertFalse(rows[0]["has_market_probabilities"])
        self.assertTrue(rows[0]["agrees"])
        self.assertEqual(excluded["missing_market_probabilities"], 1)

    def test_row_with_no_market_comparison_at_all_is_dropped(self):
        rows, excluded = extract_rows([write([pick(drop_market=True)])])
        self.assertEqual(rows, [])
        self.assertEqual(excluded["no_market_comparison"], 1)

    def test_market_pick_is_inferred_from_the_snapshot_when_absent(self):
        rows, _ = extract_rows([write([pick(probs=(60, 0, 40), market=(30, 0, 70))])])
        self.assertEqual(rows[0]["market_pick"], "a")
        self.assertFalse(rows[0]["agrees"])

    def test_probabilities_are_normalized_from_percentages(self):
        rows, _ = extract_rows([write([pick(probs=(60, 0, 40))])])
        self.assertAlmostEqual(sum(rows[0]["model"].values()), 1.0, places=6)

    def test_unreadable_log_is_counted_not_raised(self):
        path = write([pick()])
        path.write_text("{not json", encoding="utf-8")
        rows, excluded = extract_rows([path])
        self.assertEqual(rows, [])
        self.assertEqual(excluded["unreadable_pick_log"], 1)


class SummaryTest(unittest.TestCase):
    def test_agreement_split_counts_every_row(self):
        rows, _ = extract_rows([write(many(30, agree=True) + many(10, agree=False))])
        summary = summarize(rows)
        self.assertEqual(summary["n"], 40)
        self.assertEqual(summary["agreement"]["n"], 30)
        self.assertEqual(summary["disagreement"]["n"], 10)
        self.assertAlmostEqual(summary["agreement"]["share"], 0.75)

    def test_scoring_uses_only_rows_with_market_probabilities(self):
        records = many(20, agree=True)
        for record in records[:8]:
            del record["market_snapshot"]
            record["market_pick"] = "h"
        summary = summarize(extract_rows([write(records)])[0])
        self.assertEqual(summary["n"], 20)
        self.assertEqual(summary["n_with_market_probabilities"], 12)
        self.assertEqual(summary["scores"]["market"]["n"], 12)

    def test_verdict_is_gated_on_the_scored_subset_not_the_larger_split(self):
        records = many(MIN_FIXTURES + 50, agree=True, blocks=MIN_DATE_BLOCKS + 5)
        for record in records[:MIN_FIXTURES + 20]:
            del record["market_snapshot"]
            record["market_pick"] = "h"
        summary = summarize(extract_rows([write(records)])[0])
        self.assertGreaterEqual(summary["n"], MIN_FIXTURES)
        self.assertEqual(summary["verdict"]["state"], "insufficient_evidence")
        self.assertIn("market probabilities", summary["verdict"]["detail"])

    def test_confident_and_correct_model_beats_the_market(self):
        records = many(MIN_FIXTURES + 40, agree=True, model_right=True,
                       blocks=MIN_DATE_BLOCKS + 5)
        for record in records:
            record["probs"] = {"h": 80, "d": 0, "a": 20}
            record["market_snapshot"] = {"h": 55, "d": 0, "a": 45}
        summary = summarize(extract_rows([write(records)])[0])
        self.assertEqual(summary["verdict"]["state"], "adds_value_over_market")
        self.assertLess(summary["paired_log_loss_delta"]["mean"], 0)

    def test_confident_and_wrong_model_loses_to_the_market(self):
        records = many(MIN_FIXTURES + 40, agree=True, model_right=False,
                       blocks=MIN_DATE_BLOCKS + 5)
        for record in records:
            record["probs"] = {"h": 85, "d": 0, "a": 15}
            record["market_snapshot"] = {"h": 52, "d": 0, "a": 48}
        summary = summarize(extract_rows([write(records)])[0])
        self.assertEqual(summary["verdict"]["state"], "worse_than_market")

    def test_identical_probabilities_show_no_difference(self):
        records = many(MIN_FIXTURES + 40, blocks=MIN_DATE_BLOCKS + 5)
        for index, record in enumerate(records):
            record["probs"] = {"h": 60, "d": 0, "a": 40}
            record["market_snapshot"] = {"h": 60, "d": 0, "a": 40}
            record["result"] = "h" if index % 2 else "a"
        summary = summarize(extract_rows([write(records)])[0])
        self.assertEqual(summary["verdict"]["state"], "no_detectable_difference")
        self.assertEqual(summary["paired_log_loss_delta"]["mean"], 0.0)

    def test_disagreement_reports_both_sides_head_to_head(self):
        rows, _ = extract_rows([write(many(20, agree=False, model_right=False))])
        disagreement = summarize(rows)["disagreement"]
        self.assertEqual(disagreement["matchday_hit_rate"], 0.0)
        self.assertEqual(disagreement["market_hit_rate"], 1.0)

    def test_interval_is_deterministic(self):
        rows, _ = extract_rows([write(many(60, blocks=25))])
        self.assertEqual(summarize(rows)["paired_log_loss_delta"]["ci95"],
                         summarize(rows)["paired_log_loss_delta"]["ci95"])


class ReportTest(unittest.TestCase):
    def test_report_declares_itself_descriptive_not_authoritative(self):
        report = build_report([write(many(10))])
        self.assertIn("DESCRIPTIVE", report["authority"])
        self.assertIn("market_benchmark_report.json", report["authority"])
        self.assertEqual(report["production_weight"], 0)

    def test_competitions_are_segmented(self):
        records = many(10) + [pick(f"x{i}", competition="NFL") for i in range(5)]
        report = build_report([write(records)])
        self.assertIn("MLB", report["by_competition"])
        self.assertIn("NFL", report["by_competition"])

    def test_no_data_is_safe(self):
        self.assertEqual(build_report([])["overall"], {"n": 0})


if __name__ == "__main__":
    unittest.main()
