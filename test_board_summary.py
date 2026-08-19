"""Tests for the landing-board payload builder.

The board summary is what every first-time visitor downloads, so the properties
worth pinning are: it drops only fields no board view reads, it keeps the shape
the interface already knows how to consume, and it never publishes an empty file
over a good one.
"""
import datetime as dt
import json
import os
import tempfile
import unittest

import build_board_summary as bbs


def write_sport(root, key, payload):
    with open(os.path.join(root, f"data_{key}.json"), "w", encoding="utf-8") as handle:
        json.dump(payload, handle)


def match(match_id, kickoff, **extra):
    base = {
        "id": match_id,
        "kickoff": kickoff,
        "status": "SCHEDULED",
        "home": {"name": "Home FC", "code": "HOM"},
        "away": {"name": "Away FC", "code": "AWY"},
        "prediction": {"pick_name": "Home FC", "confidence": 55},
    }
    base.update(extra)
    return base


class WindowTests(unittest.TestCase):
    today = dt.date(2026, 8, 19)

    def test_keeps_fixture_inside_the_window(self):
        self.assertTrue(bbs.in_window(match("a", "2026-08-25T18:00:00Z"), self.today))

    def test_drops_fixture_far_in_the_future(self):
        self.assertFalse(bbs.in_window(match("a", "2026-12-25T18:00:00Z"), self.today))

    def test_drops_fixture_long_past(self):
        self.assertFalse(bbs.in_window(match("a", "2026-01-05T18:00:00Z"), self.today))

    def test_keeps_recent_result_for_the_results_rail(self):
        self.assertTrue(bbs.in_window(match("a", "2026-08-10T18:00:00Z"), self.today))

    def test_keeps_live_game_regardless_of_date(self):
        far = match("a", "2027-05-01T18:00:00Z", status="LIVE")
        self.assertTrue(bbs.in_window(far, self.today))

    def test_keeps_fixture_with_unparseable_kickoff(self):
        # An unknown date is a data gap; hiding the fixture would turn that gap
        # into a silently missing game on the board.
        self.assertTrue(bbs.in_window(match("a", "not-a-date"), self.today))
        self.assertTrue(bbs.in_window(match("a", ""), self.today))


class SlimMatchTests(unittest.TestCase):
    def test_strips_detail_only_fields(self):
        raw = match(
            "a", "2026-08-20T18:00:00Z",
            advanced_metrics={"home": {"epa_per_play": 0.1}},
            advanced_metrics_meta={"source": "x"},
            nfl_challenger_shadow={"home_win_probability": 0.6},
            mlb_challenger_shadow={"home_win_probability": 0.4},
        )
        out = bbs.slim_match(raw, "NFL")
        for field in bbs.DETAIL_ONLY_FIELDS:
            self.assertNotIn(field, out)

    def test_keeps_everything_the_board_renders(self):
        raw = match(
            "a", "2026-08-20T18:00:00Z",
            markets={"1x2": {"home_pct": 55}},
            watchability=71,
            injuries=[{"team": "Home FC"}],
            advanced_metrics={"home": {}},
        )
        out = bbs.slim_match(raw, "EPL")
        for field in ("id", "kickoff", "status", "home", "away", "prediction",
                      "markets", "watchability", "injuries"):
            self.assertIn(field, out)
        self.assertEqual(out["prediction"]["confidence"], 55)

    def test_stamps_competition(self):
        out = bbs.slim_match(match("a", "2026-08-20T18:00:00Z"), "NFL")
        self.assertEqual(out["_comp"], "NFL")

    def test_does_not_mutate_the_source_match(self):
        raw = match("a", "2026-08-20T18:00:00Z", advanced_metrics={"home": {}})
        bbs.slim_match(raw, "NFL")
        self.assertIn("advanced_metrics", raw)


class BuildSummaryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.addCleanup(self.tmp.cleanup)

    def test_merges_sports_and_sorts_by_kickoff(self):
        write_sport(self.root, "nfl", {
            "comp_key": "NFL", "competition": "NFL", "updated": "2026-08-19T10:00:00Z",
            "matches": [match("n1", "2026-08-24T18:00:00Z")],
        })
        write_sport(self.root, "epl", {
            "comp_key": "EPL", "competition": "Premier League", "updated": "2026-08-19T12:00:00Z",
            "matches": [match("e1", "2026-08-21T18:00:00Z")],
        })
        summary = bbs.build_summary(self.root, today=dt.date(2026, 8, 19))
        self.assertEqual([m["id"] for m in summary["matches"]], ["e1", "n1"])
        self.assertEqual(summary["comp_key"], "ALL")
        self.assertEqual(summary["competition"], "All sports")
        # latest wins, so the interface's "updated" stamp stays truthful
        self.assertEqual(summary["updated"], "2026-08-19T12:00:00Z")
        self.assertEqual(summary["sports"], ["epl", "nfl"])

    def test_scorecard_sources_carry_the_shape_aggregate_expects(self):
        # aggregateScorecards() in app-3-panels.js reads d.scorecard and
        # d.comp_key off whole datasets, not bare scorecards.
        write_sport(self.root, "mlb", {
            "comp_key": "MLB", "competition": "MLB",
            "matches": [match("m1", "2026-08-20T18:00:00Z")],
            "scorecard": {"graded": 10, "model_hits": 6, "brier": 0.24},
        })
        summary = bbs.build_summary(self.root, today=dt.date(2026, 8, 19))
        self.assertEqual(len(summary["scorecard_sources"]), 1)
        source = summary["scorecard_sources"][0]
        self.assertEqual(source["comp_key"], "MLB")
        self.assertEqual(source["scorecard"]["graded"], 10)

    def test_scorecard_survives_even_when_every_fixture_is_out_of_window(self):
        # An off-season sport still owns a graded record, and dropping it would
        # quietly shrink the public scorecard.
        write_sport(self.root, "nba", {
            "comp_key": "NBA", "competition": "NBA",
            "matches": [match("b1", "2026-12-25T18:00:00Z")],
            "scorecard": {"graded": 40, "model_hits": 22},
        })
        summary = bbs.build_summary(self.root, today=dt.date(2026, 8, 19))
        self.assertEqual(summary["matches"], [])
        self.assertEqual(summary["scorecard_sources"][0]["scorecard"]["graded"], 40)

    def test_news_is_capped_and_labelled_per_competition(self):
        write_sport(self.root, "epl", {
            "comp_key": "EPL", "competition": "Premier League",
            "matches": [match("e1", "2026-08-20T18:00:00Z")],
            "news": [{"title": f"story {i}"} for i in range(12)],
        })
        summary = bbs.build_summary(self.root, today=dt.date(2026, 8, 19))
        self.assertEqual(len(summary["news"]), bbs.NEWS_PER_COMPETITION)
        self.assertEqual(summary["news"][0]["feed"], "Premier League")
        self.assertEqual(summary["news"][0]["_comp"], "EPL")

    def test_missing_sport_files_are_skipped_quietly(self):
        write_sport(self.root, "mlb", {
            "comp_key": "MLB", "matches": [match("m1", "2026-08-20T18:00:00Z")],
        })
        summary = bbs.build_summary(self.root, today=dt.date(2026, 8, 19))
        self.assertEqual(summary["sports"], ["mlb"])
        self.assertEqual(len(summary["matches"]), 1)

    def test_corrupt_sport_file_does_not_sink_the_build(self):
        with open(os.path.join(self.root, "data_nfl.json"), "w", encoding="utf-8") as handle:
            handle.write("{not json")
        write_sport(self.root, "mlb", {
            "comp_key": "MLB", "matches": [match("m1", "2026-08-20T18:00:00Z")],
        })
        summary = bbs.build_summary(self.root, today=dt.date(2026, 8, 19))
        self.assertEqual(summary["sports"], ["mlb"])

    def test_detail_fields_are_absent_from_the_published_payload(self):
        write_sport(self.root, "nfl", {
            "comp_key": "NFL",
            "matches": [match(
                "n1", "2026-08-20T18:00:00Z",
                advanced_metrics={"home": {"epa_per_play": 0.2}},
                nfl_challenger_shadow={"home_win_probability": 0.6},
            )],
        })
        summary = bbs.build_summary(self.root, today=dt.date(2026, 8, 19))
        blob = json.dumps(summary)
        self.assertNotIn("advanced_metrics", blob)
        self.assertNotIn("nfl_challenger_shadow", blob)

    def test_title_by_sport_keeps_the_label_the_view_renders(self):
        write_sport(self.root, "epl", {
            "comp_key": "EPL", "competition": "Premier League",
            "matches": [match("e1", "2026-08-20T18:00:00Z")],
            "title_odds": [{"team": "Arsenal FC", "code": "ARS", "pct": 31}],
        })
        summary = bbs.build_summary(self.root, today=dt.date(2026, 8, 19))
        entry = summary["title_by_sport"][0]
        self.assertEqual(entry["comp"], "EPL")
        self.assertEqual(entry["label"], "Premier League")
        self.assertEqual(entry["team"], "Arsenal FC")


class MainTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.addCleanup(self.tmp.cleanup)

    def test_refuses_to_write_an_empty_summary(self):
        # Falling back to the client-side merge is slow but correct; publishing
        # an empty board over a working one is neither.
        out = os.path.join(self.root, "board_summary.json")
        summary = bbs.build_summary(self.root, today=dt.date(2026, 8, 19))
        self.assertEqual(summary["matches"], [])
        self.assertEqual(summary["scorecard_sources"], [])
        self.assertFalse(os.path.exists(out))

    def test_write_summary_reports_sizes(self):
        out = os.path.join(self.root, "board_summary.json")
        raw, packed = bbs.write_summary({"matches": [match("a", "2026-08-20T18:00:00Z")]}, out)
        self.assertGreater(raw, 0)
        self.assertGreater(packed, 0)
        with open(out, encoding="utf-8") as handle:
            self.assertEqual(json.load(handle)["matches"][0]["id"], "a")


class ContractTests(unittest.TestCase):
    """The Python and JavaScript sides have to agree on two lists."""

    def test_sport_keys_match_the_interface(self):
        with open("app-1-core.js", encoding="utf-8") as handle:
            source = handle.read()
        start = source.index("const ALL_SPORT_KEYS=[")
        literal = source[start:source.index("]", start) + 1]
        keys = [part.strip().strip("'\"") for part in literal.split("[")[1].strip("]").split(",")]
        self.assertEqual(keys, bbs.SPORT_KEYS)

    def test_detail_fields_are_the_ones_only_research_signals_reads(self):
        with open("research-signals.js", encoding="utf-8") as handle:
            source = handle.read()
        for field in bbs.DETAIL_ONLY_FIELDS:
            self.assertIn(field, source, f"{field} is stripped but research-signals.js never reads it")


if __name__ == "__main__":
    unittest.main()


class ScorecardTrimTests(unittest.TestCase):
    """The board needs the scorecard's numbers, not its full pick log."""

    def test_keeps_every_aggregate_number(self):
        raw = {"graded": 268, "model_hits": 139, "brier": 0.263, "log_loss": 0.728,
               "calibration": [{"band": "50-60", "n": 126, "hits": 63}],
               "picks": [], "misses": []}
        out = bbs.slim_scorecard(raw)
        for key in ("graded", "model_hits", "brier", "log_loss", "calibration"):
            self.assertEqual(out[key], raw[key])

    def test_trims_picks_to_the_newest_the_aggregate_can_use(self):
        picks = [{"kickoff": f"2026-01-{day:02d}T00:00:00Z", "n": day} for day in range(1, 32)]
        out = bbs.slim_scorecard({"picks": picks * 8})
        self.assertEqual(len(out["picks"]), bbs.SCORECARD_PICKS_KEPT)
        # newest first, so the merged newest-80 across sports is unchanged
        self.assertEqual(out["picks"][0]["kickoff"], "2026-01-31T00:00:00Z")

    def test_trims_misses(self):
        out = bbs.slim_scorecard({"misses": [{"i": i} for i in range(90)]})
        self.assertEqual(len(out["misses"]), bbs.SCORECARD_MISSES_KEPT)

    def test_leaves_a_short_pick_log_alone(self):
        picks = [{"kickoff": "2026-01-02T00:00:00Z"}, {"kickoff": "2026-01-01T00:00:00Z"}]
        self.assertEqual(len(bbs.slim_scorecard({"picks": picks})["picks"]), 2)

    def test_does_not_mutate_the_source_scorecard(self):
        raw = {"picks": [{"kickoff": f"2026-01-01T00:00:{s:02d}Z"} for s in range(60)] * 3}
        bbs.slim_scorecard(raw)
        self.assertEqual(len(raw["picks"]), 180)

    def test_caps_match_the_interface_slices(self):
        with open("app-3-panels.js", encoding="utf-8") as handle:
            source = handle.read()
        self.assertIn(f".slice(0,{bbs.SCORECARD_PICKS_KEPT})", source)
        self.assertIn(f".slice(0,{bbs.SCORECARD_MISSES_KEPT})", source)
