import json
import os
import tempfile
import unittest
from unittest import mock

import fetch_data
import forecast_pause
import provider_adapters
import refresh_college_talent


def finished(mid, home, away, hs, aps):
    return {
        "id": mid, "status": "FINISHED", "kickoff": "2026-01-01T00:00:00Z",
        "home": {"name": home}, "away": {"name": away},
        "score": {"home": hs, "away": aps},
    }


class ModelInputTests(unittest.TestCase):
    def test_nflverse_team_code_aliases_cover_live_provider_mismatches(self):
        self.assertEqual(fetch_data.NFLVERSE_TEAM_CODE_MAP["WSH"], "WAS")
        self.assertEqual(fetch_data.NFLVERSE_TEAM_CODE_MAP["LAR"], "LA")

    def test_weekly_awards_use_only_verified_locked_prediction(self):
        kickoff = (fetch_data.datetime.datetime.now(fetch_data.datetime.timezone.utc) -
                   fetch_data.datetime.timedelta(days=1)).isoformat()
        match = {"id": "award-game", "status": "FINISHED", "kickoff": kickoff,
                 "home": {"name": "Alpha"}, "away": {"name": "Beta"},
                 "score": {"home": 2, "away": 1, "winner": "h"},
                 "prediction": {"pick": "a", "pick_name": "Beta", "confidence": 99}}
        locked = {"fixture_id": "award-game", "integrity_eligible": True,
                  "integrity_status": "verified", "legacy": False,
                  "pick": "h", "pick_name": "Alpha", "confidence": 61, "edge": 5,
                  "model_hit": True, "result": "hit",
                  "prediction_snapshot": {"pick": "h", "pick_name": "Alpha",
                                          "confidence": 61, "edge": 5}}
        awards = fetch_data.build_weekly_awards([match], {"picks": [locked]})
        self.assertEqual(awards["best_call"]["pick"], "Alpha")
        self.assertEqual(awards["best_call"]["confidence"], 61)
        self.assertIsNone(fetch_data.build_weekly_awards([match], {"picks": []}))

    def test_weekly_awards_honor_advancement_grade_without_rewriting_tied_score(self):
        kickoff = (fetch_data.datetime.datetime.now(fetch_data.datetime.timezone.utc) -
                   fetch_data.datetime.timedelta(days=1)).isoformat()
        match = {"id": "knockout-game", "status": "FINISHED", "kickoff": kickoff,
                 "home": {"name": "Alpha"}, "away": {"name": "Beta"},
                 "score": {"home": 1, "away": 1, "winner": "d"},
                 "prediction": {"pick": "a", "pick_name": "Beta", "confidence": 99}}
        locked = {"fixture_id": "knockout-game", "integrity_eligible": True,
                  "integrity_status": "verified", "legacy": False,
                  "pick": "h", "pick_name": "Alpha", "confidence": 61, "edge": 5,
                  "model_hit": True, "result": "hit",
                  "prediction_snapshot": {"pick": "h", "pick_name": "Alpha",
                                          "confidence": 61, "edge": 5}}
        awards = fetch_data.build_weekly_awards([match], {"picks": [locked]})
        self.assertEqual(awards["best_call"]["pick"], "Alpha")
        self.assertEqual(match["score"], {"home": 1, "away": 1, "winner": "d"})

    def test_market_ledger_preserves_quote_time_when_replaying_cache(self):
        match = {"id": "cached-odds", "status": "UPCOMING",
                 "kickoff": "2099-01-01T00:00:00Z",
                 "markets": {"1x2": {"home_pct": 60, "away_pct": 40,
                                       "observed_at": "2026-08-03T14:00:00Z"}}}
        with mock.patch.object(fetch_data.market_snapshots, "append_batch",
                               return_value={"created": True} ) as append:
            self.assertEqual(fetch_data.record_market_snapshots([match]), 1)
        payload = append.call_args.args[1]
        self.assertEqual(payload["fetched_at"], "2026-08-03T14:00:00Z")
        self.assertEqual(payload["snapshots"][0]["observed_at"], "2026-08-03T14:00:00Z")

    def test_market_ledger_preserves_the_actual_provider_identity(self):
        match = {"id": "sgo-odds", "status": "UPCOMING",
                 "kickoff": "2099-01-01T00:00:00Z",
                 "markets": {"1x2": {
                     "home_pct": 55, "away_pct": 45,
                     "observed_at": "2026-08-08T14:00:00Z",
                     "source": "SportsGameOdds consensus",
                     "source_reference": "https://sportsgameodds.com/",
                 }}}
        with mock.patch.object(fetch_data.market_snapshots, "append_batch",
                               return_value={"created": True}) as append:
            self.assertEqual(fetch_data.record_market_snapshots([match]), 1)
        payload = append.call_args.args[1]
        self.assertEqual(payload["source"], "SportsGameOdds consensus")
        self.assertEqual(payload["source_reference"], "https://sportsgameodds.com/")

    def test_market_weight_uses_depth_and_disagreement(self):
        self.assertEqual(fetch_data._market_blend_weight(None), 0.0)
        deep_tight = fetch_data._market_blend_weight({"books": 8, "spread": 4})
        thin_split = fetch_data._market_blend_weight({"books": 1, "spread": 24})
        self.assertGreater(deep_tight, thin_split)
        self.assertGreaterEqual(thin_split, 0.30)
        self.assertLessEqual(deep_tight, 0.60)

    def test_market_comparison_requires_quote_observed_by_lock(self):
        base = {"market_snapshot": {"h": 60, "a": 40},
                "locked_at": "2026-09-09T18:00:00Z",
                "kickoff": "2026-09-10T00:20:00Z"}
        valid = dict(base, market_snapshot_receipt={
            "observed_at": "2026-09-09T17:59:00Z",
            "recorded_at": "2026-09-09T18:00:00Z"})
        self.assertTrue(fetch_data._lock_market_comparable(valid))
        late = dict(base, market_snapshot_receipt={
            "observed_at": "2026-09-09T18:00:01Z",
            "recorded_at": "2026-09-09T18:00:01Z"})
        self.assertFalse(fetch_data._lock_market_comparable(late))
        backfilled = dict(valid, market_backfilled_at="2026-09-09T19:00:00Z")
        self.assertFalse(fetch_data._lock_market_comparable(backfilled))

    def test_scorecard_market_agreement_uses_settlement_aware_side(self):
        records = [
            {"pick": "a", "market_comparison_pick": "a", "market_pick": "h",
             "market_comparison_hit": True},
            {"pick": "h", "regulation_pick": "a", "market_comparison_pick": "a",
             "outcome_basis": "ultimate_winner", "market_pick": "a",
             "market_comparison_hit": False},
            {"pick": "h", "market_pick": None, "market_comparison_hit": True},
        ]
        self.assertEqual(fetch_data._market_agreement_split(records), {
            "agree": {"n": 1, "hits": 0},
            "disagree": {"n": 1, "hits": 1},
        })
        older = {"pick": "h", "regulation_pick": "a",
                 "outcome_basis": "ultimate_winner", "market_result": "a"}
        self.assertTrue(fetch_data._refresh_market_comparison_grade(older))
        self.assertTrue(older["market_comparison_hit"])

    def test_advancement_value_chance_uses_regulation_comparison_side(self):
        rec = {"pick": "h", "regulation_pick": "a",
               "outcome_basis": "ultimate_winner", "value_side": "a"}
        self.assertFalse(fetch_data._is_value_chance(rec))
        rec["value_side"] = "h"
        self.assertTrue(fetch_data._is_value_chance(rec))

    def test_pending_value_count_excludes_post_lock_backfills(self):
        valid = {
            "value_side": "a", "pick": "h", "market_comparison_pick": "h",
            "market_snapshot": {"h": 55, "d": 0, "a": 45},
            "market_snapshot_receipt": {"observed_at": "2026-09-09T17:59:00Z",
                                        "recorded_at": "2026-09-09T18:00:00Z"},
            "locked_at": "2026-09-09T18:00:00Z", "kickoff": "2026-09-10T00:20:00Z",
        }
        late = dict(valid, market_backfilled_at="2026-09-09T19:00:00Z")
        self.assertEqual(fetch_data._pending_value_count([valid, late]), 1)

    def test_upset_override_drives_edge_and_market_comparison_side(self):
        home = {"name": "Favorite", "pld": 30, "w": 18}
        away = {"name": "Underdog", "pld": 30, "w": 15}
        market = {"1x2": {"home_pct": 55, "draw_pct": 0, "away_pct": 45}}
        adjusted = {"h": 52, "d": 0, "a": 48}
        upset = {"candidate": "a", "triggered": True, "score": 70}
        with mock.patch.object(fetch_data, "_upset_adjustment",
                               return_value=(adjusted, upset)):
            prediction = fetch_data.predict(home, away, market, {})
        self.assertEqual(prediction["pick"], "a")
        self.assertEqual(prediction["regulation_pick"], "h")
        self.assertEqual(prediction["market_comparison_pick"], "a")
        self.assertEqual(prediction["edge"], 3)

    def test_clv_retries_and_removes_ineligible_stale_values(self):
        base = {
            "pick": "a", "market_comparison_pick": "a", "pick_mkt": 45,
            "market_snapshot": {"h": 55, "d": 0, "a": 45},
            "market_snapshot_receipt": {"observed_at": "2026-09-09T17:59:00Z",
                                        "recorded_at": "2026-09-09T18:00:00Z"},
            "locked_at": "2026-09-09T18:00:00Z", "kickoff": "2026-09-10T00:20:00Z",
        }
        with mock.patch.object(fetch_data, "_closing_market_from_ledger",
                               return_value=({"h": 52, "d": 0, "a": 48}, {"source": "close"})):
            self.assertTrue(fetch_data._refresh_record_clv(base))
        self.assertEqual(base["clv"], 3.0)
        base["market_backfilled_at"] = "2026-09-09T19:00:00Z"
        self.assertTrue(fetch_data._refresh_record_clv(base))
        self.assertNotIn("clv", base)
        self.assertNotIn("closing_market_snapshot", base)

    def test_signal_quality_does_not_treat_draw_pick_as_away(self):
        records = [
            {"pick": "d", "model_hit": True, "factor_snapshot": {"elo": -2}},
            {"pick": "a", "model_hit": True, "factor_snapshot": {"elo": -1}},
            {"pick": "h", "model_hit": False, "factor_snapshot": {"elo": 1}},
        ]
        self.assertEqual(fetch_data._signal_quality(records, "elo"), {"n": 2, "hits": 1})

    def test_probability_metrics_expose_exact_denominators(self):
        metrics = fetch_data._probability_metric_summary([
            {"confidence": 60, "model_hit": True, "brier3": .4, "log_loss": .5},
            {"confidence": 70, "model_hit": False, "brier_advancement": .3,
             "log_loss_advancement": .4},
            {"model_hit": True},
        ])
        self.assertEqual(metrics["brier_graded"], 2)
        self.assertEqual(metrics["brier3_graded"], 1)
        self.assertEqual(metrics["log_loss_graded"], 1)
        self.assertEqual(metrics["advancement_graded"], 1)
        self.assertEqual(metrics["log_loss_advancement_graded"], 1)

    def setUp(self):
        self.old_key = fetch_data.COMP_KEY
        self.old_comp = fetch_data.COMP
        fetch_data.COMP_KEY = "NCAAM"
        fetch_data.COMP = dict(fetch_data.COMPETITIONS["NCAAM"])
        # These cover the per-sport publication and locking gates, which must
        # keep working for the day publication resumes. The site-wide pause that
        # currently sits above them is covered in test_forecast_pause.py.
        pause = mock.patch.object(forecast_pause, "PAUSE_ACTIVE", False)
        pause.start()
        self.addCleanup(pause.stop)

    def tearDown(self):
        fetch_data.COMP_KEY = self.old_key
        fetch_data.COMP = self.old_comp

    def use_college_football(self):
        fetch_data.COMP_KEY = "NCAAF"
        fetch_data.COMP = dict(fetch_data.COMPETITIONS["NCAAF"])

    def test_cached_results_are_backfilled_with_winners(self):
        matches = [finished("one", "Alpha", "Beta", 80, 72)]
        fetch_data.normalize_match_results(matches)
        self.assertEqual(matches[0]["score"]["winner"], "h")

    def test_group_stage_draw_uses_same_result_for_model_and_market(self):
        match = {
            "stage": "Group Stage",
            "score": {
                "home": 1, "away": 1, "winner": "d",
                "reg": {"home": 1, "away": 1},
            },
        }
        self.assertEqual(fetch_data._scorecard_results(match), ("d", "d"))

    def test_football_data_extra_time_is_added_to_regulation(self):
        raw = {"score": {"regularTime": {"home": 1, "away": 1},
                         "extraTime": {"home": 2, "away": 0},
                         "fullTime": {"home": 3, "away": 1},
                         "penalties": {}}}
        self.assertEqual(fetch_data._resolve_score(raw), (3, 1, "h", (None, None), (1, 1)))

    def test_lock_decision_requires_parseable_upcoming_publication_window(self):
        now = fetch_data.datetime.datetime(2026, 7, 24, 12, tzinfo=fetch_data.datetime.timezone.utc)
        base = {"status": "UPCOMING", "kickoff": "2026-07-24T14:00:00Z"}
        self.assertEqual(fetch_data._lock_decision(base, now)["state"], "eligible")
        self.assertEqual(fetch_data._lock_decision({**base, "kickoff": "2026-07-24T12:00:00Z"}, now)["state"], "eligible")
        self.assertEqual(fetch_data._lock_decision({**base, "kickoff": "2026-07-25T00:00:01Z"}, now)["state"], "wait")
        self.assertEqual(fetch_data._lock_decision({**base, "kickoff": "bad"}, now)["state"], "wait")
        self.assertEqual(fetch_data._lock_decision({**base, "kickoff": "2026-07-24T11:59:59Z"}, now)["state"], "quarantine")
        for status in ("LIVE", "FINISHED"):
            self.assertEqual(fetch_data._lock_decision({**base, "status": status}, now)["state"], "quarantine")

    def test_upcoming_mlb_forecast_is_minimal_pause_shell_and_never_lock_eligible(self):
        now = fetch_data.datetime.datetime(2026, 7, 24, 12, tzinfo=fetch_data.datetime.timezone.utc)
        match = {"_comp": "MLB", "status": "UPCOMING",
                 "kickoff": "2026-07-24T14:00:00Z",
                 "pregame_context": {"phase": "lock_window"},
                 "mlb_challenger_shadow": {"home_win_probability": 0.61},
                 "watchability": 88}
        prediction = {"pick": "a", "confidence": 77,
                      "model": {"h": 23, "d": 0, "a": 77},
                      "adjusted": {"h": 35, "d": 0, "a": 65},
                      "edge": 12, "predicted_margin": {"value": -1.2},
                      "upset": {"score": 75}, "totals": {"pick": "over"},
                      "neutral_venue_probs": {"h": 40, "d": 0, "a": 60}}

        # Pin the gate: these assert pause *behaviour*, which must keep working
        # as the rollback path no matter what the committed policy says.
        with mock.patch.object(forecast_pause, "PAUSE_ACTIVE", True):
            fetch_data._set_prediction_publication_state(match, prediction)
            decision = fetch_data._lock_decision(match, now)

        self.assertEqual(decision["state"], "wait")
        self.assertEqual(decision["reason"], "official_forecasts_paused")
        self.assertEqual(prediction["publication_state"], "paused")
        self.assertFalse(prediction["official_publication_eligible"])
        self.assertTrue(prediction["research_shadow_available"])
        self.assertEqual(prediction["publication_message"],
                         forecast_pause.PAUSE_MESSAGE)
        for key in ("pick", "confidence", "model", "adjusted", "edge",
                    "predicted_margin", "upset", "totals", "neutral_venue_probs"):
            self.assertNotIn(key, prediction)
        self.assertNotIn("watchability", match)
        self.assertEqual(match["mlb_challenger_shadow"], {"home_win_probability": 0.61})

    def test_unpaused_upcoming_fixture_publishes_normally(self):
        # With the site-wide pause lifted, an upcoming fixture reaches a normal
        # publication state rather than the paused shell.
        match = {"_comp": "MLB", "status": "UPCOMING",
                 "kickoff": "2026-07-24T14:00:00Z",
                 "pregame_context": {"phase": "lock_window"},
                 "watchability": 88}
        prediction = {"pick": "a", "confidence": 77,
                      "adjusted": {"h": 23, "d": 0, "a": 77}}

        fetch_data._set_prediction_publication_state(match, prediction)

        self.assertNotEqual(prediction["publication_state"], "paused")
        self.assertEqual(prediction["pick"], "a")
        self.assertEqual(prediction["confidence"], 77)
        self.assertEqual(match["watchability"], 88)

    def test_paused_upcoming_mlb_does_not_create_pick_log_entry(self):
        now = fetch_data.datetime.datetime.now(fetch_data.datetime.timezone.utc)
        match = {"id": "mlb-paused", "_comp": "MLB", "status": "UPCOMING",
                 "kickoff": (now + fetch_data.datetime.timedelta(hours=1)).isoformat(),
                 "home": {"name": "Home"}, "away": {"name": "Away"},
                 "markets": {}, "prediction": {"pick": "h", "confidence": 70}}
        picks = {}
        with mock.patch.object(fetch_data, "_load_picks", return_value=picks), \
             mock.patch.object(forecast_pause, "PAUSE_ACTIVE", True), \
             mock.patch.object(fetch_data, "_save_picks") as save:
            fetch_data.update_scorecard([match])
        self.assertEqual(picks, {})
        save.assert_not_called()

    def test_mlb_pause_does_not_interrupt_historical_grading(self):
        picks = {"mlb-finished": {
            "fixture_id": "mlb-finished", "competition": "MLB",
            "pick": "a", "market_pick": "a", "market_comparison_pick": "a",
            "regulation_probs": {"h": 40, "d": 0, "a": 60},
            "result": None,
        }}
        match = {"id": "mlb-finished", "_comp": "MLB", "status": "FINISHED",
                 "home": {"name": "Home"}, "away": {"name": "Away"},
                 "markets": {}, "score": {"home": 2, "away": 4, "winner": "a"}}
        with mock.patch.object(fetch_data, "_load_picks", return_value=picks), \
             mock.patch.object(fetch_data, "_save_picks") as save, \
             mock.patch.object(fetch_data, "_record_is_official", return_value=True), \
             mock.patch.object(fetch_data, "_refresh_record_clv", return_value=False):
            fetch_data.update_scorecard([match])
        self.assertEqual(picks["mlb-finished"]["result"], "a")
        self.assertTrue(picks["mlb-finished"]["model_hit"])
        self.assertEqual(picks["mlb-finished"]["score"], "2-4")
        save.assert_called_once()

    def test_existing_upcoming_mlb_lock_is_not_republished_during_pause(self):
        match = {"id": "old-mlb-lock", "_comp": "MLB", "status": "UPCOMING",
                 "pregame_context": {"phase": "lock_window"},
                 "prediction": {"publication_state": "paused"}}
        rec = {"prediction_snapshot": {
            "pick": "h", "confidence": 72,
            "adjusted": {"h": 72, "d": 0, "a": 28},
            "totals": {"pick": "over"},
        }}
        with mock.patch.object(fetch_data, "_load_picks", return_value={"old-mlb-lock": rec}), \
             mock.patch.object(fetch_data, "_record_is_official", return_value=True):
            fetch_data.apply_locked_picks([match])
        self.assertEqual(match["prediction"]["publication_state"], "locked")

        with mock.patch.object(forecast_pause, "PAUSE_ACTIVE", True):
            self.assertEqual(
                fetch_data._enforce_forecast_pause_after_locked_picks([match]), 1)

        self.assertEqual(match["prediction"]["publication_state"], "paused")
        self.assertNotIn("pick", match["prediction"])
        self.assertNotIn("confidence", match["prediction"])
        self.assertNotIn("adjusted", match["prediction"])
        self.assertNotIn("totals", match["prediction"])

    def test_finished_mlb_locked_prediction_remains_visible_and_locked(self):
        match = {"id": "finished-mlb-lock", "_comp": "MLB", "status": "FINISHED",
                 "prediction": {"publication_state": "preliminary"}}
        rec = {"prediction_snapshot": {
            "pick": "a", "pick_name": "Away", "confidence": 58,
            "adjusted": {"h": 42, "d": 0, "a": 58},
        }}
        with mock.patch.object(fetch_data, "_load_picks", return_value={"finished-mlb-lock": rec}), \
             mock.patch.object(fetch_data, "_record_is_official", return_value=True):
            fetch_data.apply_locked_picks([match])

        self.assertEqual(fetch_data._enforce_forecast_pause_after_locked_picks([match]), 0)

        self.assertEqual(match["prediction"]["publication_state"], "locked")
        self.assertEqual(match["prediction"]["pick"], "a")
        self.assertEqual(match["prediction"]["confidence"], 58)

    def test_publication_and_locking_resume_when_the_pause_lifts(self):
        now = fetch_data.datetime.datetime(2026, 7, 24, 12, tzinfo=fetch_data.datetime.timezone.utc)
        match = {"_comp": "NBA", "status": "UPCOMING",
                 "kickoff": "2026-07-24T14:00:00Z",
                 "pregame_context": {"phase": "lock_window"}}
        prediction = {"pick": "h", "confidence": 55}
        fetch_data._set_prediction_publication_state(match, prediction)
        self.assertEqual(prediction["publication_state"], "lock_candidate")
        self.assertEqual(fetch_data._lock_decision(match, now)["state"], "eligible")
        self.assertNotIn("publication_message", prediction)

    def test_legacy_record_is_moved_and_never_official(self):
        picks = {"fixture-1": {"pick": "h", "result": "h", "home": "A", "away": "B"}}
        self.assertTrue(fetch_data._quarantine_legacy_records(picks))
        self.assertNotIn("fixture-1", picks)
        self.assertIn("legacy:fixture-1", picks)
        self.assertFalse(fetch_data._record_is_official(picks["legacy:fixture-1"]))
        self.assertEqual(picks["legacy:fixture-1"]["quarantine_reason"], "legacy_missing_lock_provenance")

    def test_reseeded_duplicate_pick_is_dropped_not_stored_twice(self):
        # A fixture already quarantined under "legacy:<id>" that reappears
        # under its plain key (an external re-seed/import re-running) must not
        # become a second "legacy:<id>:2" record -- that double-counts one
        # pick in the scorecard's legacy/all-time tally. Observed live
        # 2026-07-27: a repeating seed step grew one 19-pick ledger to 38.
        graded = {"pick": "h", "result": "h", "home": "A", "away": "B",
                  "score": "1-1 (2-4 pens)", "integrity_status": "quarantined"}
        stale_reseed = {"pick": "h", "result": "h", "home": "A", "away": "B",
                        "score": "3-5"}  # pre-self-heal penalty-inflated score
        picks = {"legacy:fixture-1": dict(graded), "fixture-1": dict(stale_reseed)}
        fetch_data._quarantine_legacy_records(picks)
        self.assertEqual(list(picks), ["legacy:fixture-1"])
        self.assertNotIn("legacy:fixture-1:2", picks)
        # the already-graded/self-healed copy is the one that survives
        self.assertEqual(picks["legacy:fixture-1"]["score"], "1-1 (2-4 pens)")

    def test_locked_snapshot_replaces_entire_recomputed_prediction(self):
        self.use_college_football()
        now = fetch_data.datetime.datetime(2026, 7, 24, 12, tzinfo=fetch_data.datetime.timezone.utc)
        match = {"id": "lock-1", "stage": "Final", "status": "UPCOMING",
                 "kickoff": "2026-07-24T13:00:00Z", "venue": "Test",
                 "home": {"name": "Alpha"}, "away": {"name": "Beta"},
                 "markets": {}, "weather": {}, "injuries": {}, "lineups": None,
                 "prediction": {"pick": "h", "pick_name": "Alpha", "confidence": 60,
                                "adjusted": {"h": 60, "d": 0, "a": 40},
                                "regulation_probs": {"h": 44, "d": 26, "a": 30},
                                "regulation_pick": "h", "advancement": {"h": 60, "a": 40},
                                "is_knockout": True, "why": {"class": 1.2},
                                "data_quality": {"level": "early"}, "upset": {}}}
        decision = fetch_data._lock_decision(match, now)
        rec = fetch_data._make_pick_record(match, match["prediction"], {}, decision)
        frozen = json.loads(json.dumps(rec["prediction_snapshot"]))
        match["prediction"] = {"pick": "a", "why": {"live": 999}, "note": "changed"}
        with mock.patch.object(fetch_data, "_load_picks", return_value={"lock-1": rec}):
            fetch_data.apply_locked_picks([match])
        self.assertEqual(match["prediction"], frozen)

    def test_older_locked_snapshot_gets_display_marker_without_mutating_receipt(self):
        self.use_college_football()
        rec = {"prediction_snapshot": {"pick": "h", "confidence": 60}}
        match = {"id": "old-lock", "prediction": {"pick": "a"}}
        with mock.patch.object(fetch_data, "_load_picks", return_value={"old-lock": rec}), \
             mock.patch.object(fetch_data, "_record_is_official", return_value=True):
            fetch_data.apply_locked_picks([match])
        self.assertEqual(match["prediction"]["publication_state"], "locked")
        self.assertNotIn("publication_state", rec["prediction_snapshot"])

    def test_first_seen_finished_fixture_is_not_added_to_ledger(self):
        self.use_college_football()
        match = {"id": "late", "stage": "Final", "status": "FINISHED",
                 "kickoff": "2026-07-19T19:00:00Z", "home": {"name": "A"},
                 "away": {"name": "B"}, "score": {"home": 1, "away": 0, "winner": "h",
                 "reg": {"home": 0, "away": 0}}, "markets": {},
                 "prediction": {"pick": "h", "pick_name": "A", "confidence": 60}}
        saved = []
        with mock.patch.object(fetch_data, "_load_picks", return_value={}), \
             mock.patch.object(fetch_data, "_save_picks", side_effect=lambda value: saved.append(value)):
            scorecard = fetch_data.update_scorecard([match])
        self.assertEqual(scorecard["graded"], 0)
        self.assertEqual(scorecard["quarantined"]["total"], 0)
        self.assertFalse(saved)

    def test_legacy_record_is_reported_separately_from_official_metrics(self):
        self.use_college_football()
        picks = {"old": {"fixture_id": "old", "stage": "Final", "home": "A", "away": "B",
                          "pick": "h", "result": "h", "model_hit": True}}
        with mock.patch.object(fetch_data, "_load_picks", return_value=picks), \
             mock.patch.object(fetch_data, "_save_picks"):
            scorecard = fetch_data.update_scorecard([])
        self.assertEqual(scorecard["graded"], 0)
        self.assertEqual(scorecard["model_hits"], 0)
        self.assertEqual(scorecard["legacy"]["graded"], 1)
        self.assertEqual(scorecard["legacy"]["model_hits"], 1)
        self.assertIn("Legacy/unverified", scorecard["picks"][0]["stage"])

    def test_scorecard_tracks_classified_underdogs_without_requiring_radar_flag(self):
        picks = {
            "dog": {
                "fixture_id": "dog", "home": "A", "away": "B",
                "pick": "h", "result": "h", "model_hit": True,
                "upset_candidate": "a", "upset_hit": False,
                "upset_score": 58, "upset_triggered": False,
                "upset_snapshot": {"class": "solid", "radar": False},
                "integrity_eligible": True, "integrity_status": "verified",
            },
            "pickem": {
                "fixture_id": "pickem", "home": "C", "away": "D",
                "pick": "a", "result": "a", "model_hit": True,
                "upset_candidate": "h", "upset_hit": False,
                "upset_score": 52, "upset_triggered": False,
                "upset_snapshot": {"class": "pickem", "radar": False},
                "integrity_eligible": True, "integrity_status": "verified",
            },
        }
        with mock.patch.object(fetch_data, "_load_picks", return_value=picks), \
             mock.patch.object(fetch_data, "_save_picks"), \
             mock.patch.object(fetch_data, "_record_is_official", return_value=True), \
             mock.patch.object(fetch_data, "_refresh_record_clv", return_value=False):
            scorecard = fetch_data.update_scorecard([])
        self.assertEqual(scorecard["upset"]["watched"], 1)
        self.assertEqual(scorecard["upset"]["hits"], 0)
        self.assertEqual(scorecard["upset"]["avg_score"], 58.0)

    def test_srs_adjusts_margin_for_opponent_strength(self):
        matches = [
            finished("one", "Alpha", "Beta", 80, 70),
            finished("two", "Beta", "Gamma", 80, 70),
            finished("three", "Alpha", "Gamma", 80, 70),
        ]
        fetch_data.normalize_match_results(matches)
        ratings = fetch_data.compute_srs(matches)
        self.assertGreater(ratings["alpha"]["rating"], ratings["beta"]["rating"])
        self.assertGreater(ratings["beta"]["rating"], ratings["gamma"]["rating"])

    def test_rest_days_uses_training_history_beyond_the_display_window(self):
        # The team's only past game is 10 days before kickoff -- outside a
        # narrow ~1-week display window, but present in the wider training set.
        training = [{"kickoff": "2026-01-01T00:00:00Z", "status": "FINISHED",
                     "home": {"name": "Alpha"}, "away": {"name": "Zeta"}}]
        upcoming = {"kickoff": "2026-01-11T00:00:00Z", "status": "UPCOMING",
                    "home": {"name": "Alpha"}, "away": {"name": "Beta"}}
        matches = [upcoming]  # the Jan-1 game is NOT in the narrow display list
        fetch_data.compute_rest(matches, training)
        self.assertEqual(upcoming["home"]["rest_days"], 10)

    def test_rest_days_falls_back_to_matches_when_no_training_set_given(self):
        matches = [
            {"kickoff": "2026-01-01T00:00:00Z", "status": "FINISHED",
             "home": {"name": "Alpha"}, "away": {"name": "Zeta"}},
            {"kickoff": "2026-01-05T00:00:00Z", "status": "UPCOMING",
             "home": {"name": "Alpha"}, "away": {"name": "Beta"}},
        ]
        fetch_data.compute_rest(matches)
        self.assertEqual(matches[1]["home"]["rest_days"], 4)

    def test_american_prediction_reports_sample_and_native_factors(self):
        home = {"name": "Test Alpha", "pld": 12, "w": 9, "l": 3,
                "win_pct": .75, "gf": 960, "ga": 840, "form": "W W L W W",
                "srs": 8.0, "srs_games": 12}
        away = {"name": "Test Beta", "pld": 12, "w": 6, "l": 6,
                "win_pct": .5, "gf": 870, "ga": 870, "form": "L W L W L",
                "srs": 0.0, "srs_games": 12}
        prediction = fetch_data.predict(home, away, {})
        self.assertEqual(prediction["data_quality"]["games"], {"home": 12, "away": 12})
        self.assertIn("record", prediction["why"])
        self.assertIn("margin", prediction["why"])
        self.assertIn("srs", prediction["why"])
        self.assertNotIn("gd", prediction["why"])

    def test_season_stale_record_is_dampened_and_flagged_preseason(self):
        # Regression: CollegeFootballDataAdapter.standings() falls back to
        # last season's FINAL record when the new season has no games yet.
        # That stale record used to get the same ~full reliability weight as
        # an in-progress current-season sample, letting a P4 team's rough
        # prior year swamp a real preseason talent edge (live MSU-vs-Toledo:
        # Toledo got favored over Michigan State on a stale 4-8 alone).
        fetch_data.COMP_KEY = "NCAAF"
        fetch_data.COMP = dict(fetch_data.COMPETITIONS["NCAAF"])
        base = {"pld": 12, "w": 4, "l": 8, "win_pct": 4 / 12, "gf": 0, "ga": 0, "form": ""}
        fresh_home = {**base, "name": "Fresh Team"}
        fresh_away = {**base, "name": "Fresh Opp", "w": 8, "l": 4, "win_pct": 8 / 12}
        fresh_pred = fetch_data.predict(fresh_home, fresh_away, {})
        stale_home = {**fresh_home, "season_stale": True}
        stale_away = {**fresh_away, "season_stale": True}
        stale_pred = fetch_data.predict(stale_home, stale_away, {})
        self.assertLess(abs(stale_pred["why"]["record"]), abs(fresh_pred["why"]["record"]))
        self.assertEqual(stale_pred["data_quality"]["level"], "preseason")
        self.assertNotEqual(fresh_pred["data_quality"]["level"], "preseason")


class MultiSeasonCollegeSampleTests(unittest.TestCase):
    """College football plays ~13 games a season, so one season is a thin
    sample and preseason there is none at all. The provider layer summarises
    several seasons; predict() may only spend the confidence the current
    season has NOT earned on it."""

    def setUp(self):
        self.old_key, self.old_comp = fetch_data.COMP_KEY, fetch_data.COMP
        fetch_data.COMP_KEY = "NCAAF"
        fetch_data.COMP = dict(fetch_data.COMPETITIONS["NCAAF"])

    def tearDown(self):
        fetch_data.COMP_KEY, fetch_data.COMP = self.old_key, self.old_comp

    def test_established_season_is_completely_unaffected(self):
        """The whole change has to be a no-op once the sample is full."""
        full = {"pld": 12, "w": 9, "l": 3, "win_pct": 9 / 12, "gf": 340, "ga": 240, "form": ""}
        home, away = {**full, "name": "Alpha"}, {**full, "name": "Beta", "w": 4, "l": 8, "win_pct": 4 / 12}
        without = fetch_data.predict(home, away, {})
        deep = {"multi_win_pct": 0.15, "multi_margin": -20.0, "multi_games": 40}
        with_history = fetch_data.predict({**home, **deep}, {**away, **deep}, {})
        self.assertAlmostEqual(without["why"]["record"], with_history["why"]["record"], places=6)
        self.assertAlmostEqual(without["why"]["margin"], with_history["why"]["margin"], places=6)

    def test_preseason_record_comes_from_the_multi_season_sample(self):
        blank = {"pld": 0, "w": 0, "l": 0, "gf": 0, "ga": 0, "form": ""}
        home = {**blank, "name": "Strong", "multi_win_pct": 0.82, "multi_margin": 18.0, "multi_games": 38}
        away = {**blank, "name": "Weak", "multi_win_pct": 0.24, "multi_margin": -14.0, "multi_games": 38}
        bare = fetch_data.predict({**blank, "name": "Strong"}, {**blank, "name": "Weak"}, {})
        deep = fetch_data.predict(home, away, {})
        # With no sample at all, record and margin used to be exactly zero.
        self.assertEqual(bare["why"]["record"], 0.0)
        self.assertEqual(bare["why"]["margin"], 0.0)
        self.assertGreater(deep["why"]["record"], 0.0)
        self.assertGreater(deep["why"]["margin"], 0.0)
        self.assertGreater(deep["confidence"], bare["confidence"])

    def test_thin_history_is_trusted_proportionally(self):
        blank = {"pld": 0, "w": 0, "l": 0, "gf": 0, "ga": 0, "form": ""}
        strong = {"multi_win_pct": 0.9, "multi_margin": 20.0}
        deep = fetch_data.predict({**blank, "name": "A", **strong, "multi_games": 40},
                                  {**blank, "name": "B"}, {})
        thin = fetch_data.predict({**blank, "name": "A", **strong, "multi_games": 4},
                                  {**blank, "name": "B"}, {})
        self.assertGreater(deep["why"]["record"], thin["why"]["record"])
        self.assertGreater(thin["why"]["record"], 0.0)

    def test_missing_history_changes_nothing(self):
        blank = {"pld": 4, "w": 3, "l": 1, "win_pct": 0.75, "gf": 120, "ga": 90, "form": ""}
        home, away = {**blank, "name": "A"}, {**blank, "name": "B", "w": 1, "l": 3, "win_pct": 0.25}
        self.assertEqual(fetch_data.predict(home, away, {})["why"]["record"],
                         fetch_data.predict({**home, "multi_win_pct": None},
                                            {**away, "multi_win_pct": None}, {})["why"]["record"])


class SeasonHistoryAggregationTests(unittest.TestCase):
    def test_finished_games_aggregate_into_record_and_points(self):
        agg = provider_adapters.season_form_from_matches([
            finished("1", "A", "B", 30, 10),
            finished("2", "B", "A", 20, 20),
            {**finished("3", "A", "B", 7, 21), "status": "UPCOMING"},
        ])
        self.assertEqual(agg["A"], {"w": 1, "l": 0, "t": 1, "pf": 50, "pa": 30, "games": 2})
        self.assertEqual(agg["B"]["l"], 1)
        self.assertEqual(agg["B"]["games"], 2)

    def test_recent_seasons_outweigh_older_ones(self):
        recent = {"A": {"w": 10, "l": 0, "t": 0, "pf": 400, "pa": 100, "games": 10}}
        old = {"A": {"w": 0, "l": 10, "t": 0, "pf": 100, "pa": 400, "games": 10}}
        newer_good = provider_adapters.blend_season_history([(2026, recent), (2024, old)])
        newer_bad = provider_adapters.blend_season_history([(2026, old), (2024, recent)])
        self.assertGreater(newer_good["a"]["multi_win_pct"], newer_bad["a"]["multi_win_pct"])
        self.assertGreater(newer_good["a"]["multi_margin"], 0)
        self.assertEqual(newer_good["a"]["multi_games"], 20)
        self.assertEqual(newer_good["a"]["multi_seasons"], [2026, 2024])

    def test_empty_seasons_are_ignored_not_counted_as_zero(self):
        agg = {"A": {"w": 8, "l": 4, "t": 0, "pf": 300, "pa": 200, "games": 12}}
        with_gap = provider_adapters.blend_season_history([(2026, agg), (2025, {}), (2024, None)])
        alone = provider_adapters.blend_season_history([(2026, agg)])
        self.assertAlmostEqual(with_gap["a"]["multi_win_pct"], alone["a"]["multi_win_pct"])
        self.assertEqual(with_gap["a"]["multi_seasons"], [2026])

    def test_history_is_attached_to_standings_rows(self):
        history = {"alpha": {"name": "Alpha", "multi_win_pct": 0.7, "multi_margin": 9.0,
                             "multi_games": 25, "multi_seasons": [2026, 2025]}}
        model = {"alpha": {"name": "Alpha"}}
        tables = [{"group": "SEC", "teams": [{"name": "Alpha"}, {"name": "Nobody"}]}]
        applied = fetch_data.apply_season_history(history, model, tables)
        self.assertEqual(applied, 2)
        self.assertEqual(model["alpha"]["multi_games"], 25)
        self.assertEqual(tables[0]["teams"][0]["multi_seasons"], [2026, 2025])
        self.assertNotIn("multi_games", tables[0]["teams"][1])


class RatingsLookupTests(unittest.TestCase):
    """Regression coverage for the club-suffix mismatch found live: ratings
    files hand-written with short names ("Arsenal") never matched live
    fixture data using official names ("Arsenal FC"), silently zeroing the
    class factor for most club-soccer and all NCAAF/NCAAM matchups."""

    def setUp(self):
        self.old_key, self.old_comp = fetch_data.COMP_KEY, fetch_data.COMP
        self.old_ratings_file, self.old_ratings = fetch_data.RATINGS_FILE, fetch_data._RATINGS
        fetch_data.COMP_KEY = "NCAAF"
        fetch_data.COMP = dict(fetch_data.COMPETITIONS["NCAAF"])
        fd, self.tmp_path = tempfile.mkstemp(suffix=".json")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({}, f)
        fetch_data.RATINGS_FILE = self.tmp_path
        fetch_data._RATINGS = None

    def tearDown(self):
        fetch_data.COMP_KEY, fetch_data.COMP = self.old_key, self.old_comp
        fetch_data.RATINGS_FILE, fetch_data._RATINGS = self.old_ratings_file, self.old_ratings
        os.unlink(self.tmp_path)

    def test_apply_market_strength_creates_an_entry_for_a_college_team(self):
        fetch_data.COMP_KEY = "NCAAM"
        fetch_data.COMP = dict(fetch_data.COMPETITIONS["NCAAM"])
        self.assertIsNone(fetch_data._ratings_lookup("Duke"))
        fetch_data.apply_market_strength([{"team": "Duke", "pct": 18.0}])
        rec = fetch_data._ratings_lookup("Duke")
        self.assertIsNotNone(rec)

    def test_apply_recruiting_strength_covers_teams_with_no_championship_odds(self):
        # Recruiting/talent data covers the whole D1 field, unlike championship
        # odds which only price a handful of contenders -- a mid-major with no
        # title odds should still get a real, non-default rating from this.
        fetch_data.COMP_KEY = "NCAAM"
        fetch_data.COMP = dict(fetch_data.COMPETITIONS["NCAAM"])
        self.assertIsNone(fetch_data._ratings_lookup("Drake"))
        fetch_data.apply_recruiting_strength({"Duke": 70.0, "Drake": 12.0, "Directional State": 4.0})
        duke = fetch_data._ratings_lookup("Duke")
        drake = fetch_data._ratings_lookup("Drake")
        self.assertIsNotNone(drake)
        self.assertGreater(duke["squad_value_m"], drake["squad_value_m"])

    def test_recruiting_and_market_strength_reach_the_full_class_scale(self):
        # squad_value_m/star_value_m feed rating_boost()/rating_parts(), which
        # cap out at 1500/200 respectively ("€1.5B squad -> 10", "€200M player
        # -> 10"). The country's #1-talent team (share == 1.0) should land
        # exactly on that ceiling, not undershoot it -- undershooting is what
        # flattened the gap between a P4 team's talent and a G5 team's almost
        # to nothing (the live MSU-vs-Toledo case).
        fetch_data.COMP_KEY = "NCAAM"
        fetch_data.COMP = dict(fetch_data.COMPETITIONS["NCAAM"])
        fetch_data.apply_recruiting_strength({"Duke": 100.0})
        top = fetch_data._ratings_lookup("Duke")
        self.assertEqual(top["squad_value_m"], 1500)
        self.assertEqual(top["star_value_m"], 200)
        fetch_data.apply_market_strength([{"team": "Gonzaga", "pct": 30.0}])
        market_top = fetch_data._ratings_lookup("Gonzaga")
        self.assertEqual(market_top["squad_value_m"], 1500)
        self.assertEqual(market_top["star_value_m"], 200)

    def test_recruiting_strength_is_refined_by_later_market_strength(self):
        # Market strength (real-time, live) should be able to overwrite a
        # value recruiting strength already set for the same team.
        fetch_data.COMP_KEY = "NCAAM"
        fetch_data.COMP = dict(fetch_data.COMPETITIONS["NCAAM"])
        fetch_data.apply_recruiting_strength({"Duke": 70.0, "Gonzaga": 40.0})
        before = fetch_data._ratings_lookup("Duke")
        self.assertNotIn("market_pct", before)
        fetch_data.apply_market_strength([{"team": "Duke", "pct": 25.0}, {"team": "Gonzaga", "pct": 5.0}])
        after = fetch_data._ratings_lookup("Duke")
        self.assertEqual(after["market_pct"], 25.0)

    def test_sibling_school_does_not_swallow_the_bare_school_s_rating(self):
        # Confirmed live 2026-07-26: a national talent feed covers every D1
        # team, including ones not in this week's schedule (known_names).
        # "Alabama A&M" wasn't playing the week Alabama played East Carolina,
        # so "alabama a m" was never in known_names -- the old prefix-shorten
        # loop kept trimming past "a"/"m" and landed on plain "alabama",
        # silently overwriting real Alabama's talent-share rating with
        # Alabama A&M's much weaker one and flipping Alabama's class score
        # negative against an unranked opponent. Order matters here: the
        # weak sibling must be applied AFTER the real school to prove it
        # doesn't clobber it.
        fetch_data.COMP_KEY = "NCAAF"
        fetch_data.COMP = dict(fetch_data.COMPETITIONS["NCAAF"])
        known_names = {"alabama", "east carolina"}  # Alabama A&M/State not playing this week
        fetch_data.apply_recruiting_strength(
            {"Alabama": 1000.0, "Alabama A&M": 130.0, "Alabama State": 150.0}, known_names)
        alabama = fetch_data._ratings_lookup("Alabama")
        self.assertEqual(alabama["squad_value_m"], 1500)
        self.assertEqual(alabama["star_value_m"], 200)

    def test_mascot_suffix_still_strips_down_to_the_bare_school_name(self):
        # The distinguisher guard must not break the resolver's actual job:
        # a sportsbook/talent feed tacking a real mascot onto the bare name.
        fetch_data.COMP_KEY = "NCAAF"
        fetch_data.COMP = dict(fetch_data.COMPETITIONS["NCAAF"])
        known_names = {"alabama"}
        fetch_data.apply_recruiting_strength({"Alabama Crimson Tide": 1000.0}, known_names)
        self.assertIsNotNone(fetch_data._ratings_lookup("Alabama"))

    def test_sibling_school_playing_this_week_resolves_to_its_own_key(self):
        # When the longer name IS in known_names (it's actually playing this
        # week), it must resolve to itself, not get shortened at all.
        fetch_data.COMP_KEY = "NCAAF"
        fetch_data.COMP = dict(fetch_data.COMPETITIONS["NCAAF"])
        known_names = {"alabama", "alabama a m"}
        fetch_data.apply_recruiting_strength({"Alabama": 1000.0, "Alabama A&M": 130.0}, known_names)
        alabama = fetch_data._ratings_lookup("Alabama")
        aamu = fetch_data._ratings_lookup("Alabama A&M")
        self.assertEqual(alabama["squad_value_m"], 1500)
        self.assertLess(aamu["squad_value_m"], alabama["squad_value_m"])

    def test_college_talent_and_championship_market_are_separate_factors(self):
        fetch_data.COMP_KEY = "NCAAF"
        fetch_data.COMP = dict(fetch_data.COMPETITIONS["NCAAF"])
        fetch_data.apply_recruiting_strength({"Michigan State": 100.0, "Toledo": 50.0})
        fetch_data.apply_market_strength([
            {"team": "Michigan State", "pct": 5.0},
            {"team": "Toledo", "pct": 25.0},
        ])
        pred = fetch_data.predict(
            {"name": "Michigan State", "pld": 0},
            {"name": "Toledo", "pld": 0}, {},
            {"stage": "Week 1", "weather": {}},
        )
        self.assertGreater(pred["why"]["class"], 0)
        self.assertLess(pred["why"]["market_power"], 0)
        self.assertEqual(pred["class_meta"]["label"], "Roster talent edge")
        self.assertEqual(pred["class_meta"]["coverage"], "complete")

    def test_recruiting_enrichment_is_persisted_to_the_tracked_ratings_file(self):
        fetch_data.COMP_KEY = "NCAAF"
        fetch_data.COMP = dict(fetch_data.COMPETITIONS["NCAAF"])
        fetch_data.apply_recruiting_strength({"Georgia": 1002.98, "Michigan State": 717.42})
        with open(self.tmp_path, encoding="utf-8") as handle:
            persisted = json.load(handle)
        self.assertEqual(persisted["michigan state"]["talent_source"], "cfbd_team_talent")
        self.assertGreater(persisted["michigan state"]["talent_strength"], 0)

    def test_persisted_talent_survives_a_new_process_for_msu_toledo(self):
        fetch_data.COMP_KEY = "NCAAF"
        fetch_data.COMP = dict(fetch_data.COMPETITIONS["NCAAF"])
        fetch_data.apply_recruiting_strength({
            "Georgia": 1002.98, "Michigan State": 717.42, "Toledo": 620.13,
        })
        fetch_data._RATINGS = None
        pred = fetch_data.predict(
            {"name": "Michigan State", "pld": 12, "win_pct": 4 / 12, "season_stale": True},
            {"name": "Toledo", "pld": 13, "win_pct": 8 / 13, "season_stale": True},
            {}, {"stage": "Week 1", "weather": {}},
        )
        self.assertEqual(pred["class_meta"]["coverage"], "complete")
        self.assertGreater(pred["why"]["class"], 0)
        self.assertEqual(pred["pick_name"], "Michigan State")

class CollegeClassCacheTests(unittest.TestCase):
    def setUp(self):
        self.old_key, self.old_comp = fetch_data.COMP_KEY, fetch_data.COMP
        self.old_ratings_file, self.old_ratings = fetch_data.RATINGS_FILE, fetch_data._RATINGS
        self.old_cwd = os.getcwd()
        self.tmp = tempfile.TemporaryDirectory()
        os.chdir(self.tmp.name)
        fetch_data.COMP_KEY = "NCAAF"
        fetch_data.COMP = dict(fetch_data.COMPETITIONS["NCAAF"])
        fetch_data.RATINGS_FILE = "ratings_ncaaf.json"
        fetch_data._RATINGS = None

    def tearDown(self):
        fetch_data.COMP_KEY, fetch_data.COMP = self.old_key, self.old_comp
        fetch_data.RATINGS_FILE, fetch_data._RATINGS = self.old_ratings_file, self.old_ratings
        os.chdir(self.old_cwd)
        self.tmp.cleanup()

    def test_provider_failure_uses_stale_last_good_talent(self):
        with open("college_ncaaf_talent_cache.json", "w", encoding="utf-8") as handle:
            json.dump({"t": 1, "data": {"Michigan State": 812.4, "Toledo": 512.1}}, handle)
        adapter = mock.Mock()
        adapter.talent.side_effect = fetch_data.ProviderError("rate limited")
        result = fetch_data.fetch_college_class_strength(adapter, "talent")
        self.assertEqual(result["Michigan State"], 812.4)
        self.assertTrue(any("last-good cache" in line for line in fetch_data.DIAG))

    def test_fresh_talent_cache_avoids_another_provider_call(self):
        with open("college_ncaaf_talent_cache.json", "w", encoding="utf-8") as handle:
            json.dump({"t": fetch_data.time.time(), "data": {"Michigan State": 812.4}}, handle)
        adapter = mock.Mock()
        result = fetch_data.fetch_college_class_strength(adapter, "talent")
        self.assertEqual(result, {"Michigan State": 812.4})
        adapter.talent.assert_not_called()
class CollegeTalentRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.old_key, self.old_comp = fetch_data.COMP_KEY, fetch_data.COMP
        self.old_file, self.old_ratings = fetch_data.RATINGS_FILE, fetch_data._RATINGS
        self.old_cwd = os.getcwd()
        self.tmp = tempfile.TemporaryDirectory()
        os.chdir(self.tmp.name)

    def tearDown(self):
        fetch_data.COMP_KEY, fetch_data.COMP = self.old_key, self.old_comp
        fetch_data.RATINGS_FILE, fetch_data._RATINGS = self.old_file, self.old_ratings
        os.chdir(self.old_cwd)
        self.tmp.cleanup()

    def test_quota_light_recovery_persists_broad_talent_coverage(self):
        adapter = mock.Mock()
        adapter.talent.return_value = {
            f"Team {index}": 1000.0 - index for index in range(101)
        }
        coverage = refresh_college_talent.refresh_if_missing(adapter)
        self.assertEqual(coverage, 101)
        adapter.talent.assert_called_once_with(seasons_back=1)
        with open("ratings_ncaaf.json", encoding="utf-8") as handle:
            persisted = json.load(handle)
        self.assertEqual(persisted["team 100"]["talent_source"], "cfbd_team_talent")

    def test_tracked_verified_seed_covers_the_reported_msu_toledo_gap(self):
        ratings_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "ratings_ncaaf.json")
        with open(ratings_path, encoding="utf-8") as handle:
            ratings = json.load(handle)
        msu = ratings["michigan state"]
        toledo = ratings["toledo"]
        self.assertEqual(msu["talent_source"], "cfbd_team_talent")
        self.assertEqual(toledo["talent_source"], "cfbd_team_talent")
        self.assertGreater(msu["talent_strength"], toledo["talent_strength"])

    def test_recovery_skips_provider_after_durable_coverage_exists(self):
        existing = {
            f"team {index}": {"talent_source": "cfbd_team_talent", "talent_strength": 1.0}
            for index in range(100)
        }
        with open("ratings_ncaaf.json", "w", encoding="utf-8") as handle:
            json.dump(existing, handle)
        adapter = mock.Mock()
        coverage = refresh_college_talent.refresh_if_missing(adapter)
        self.assertEqual(coverage, 100)
        adapter.talent.assert_not_called()

    def test_deploy_recovers_talent_before_the_quota_heavy_fetch(self):
        workflow_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), ".github", "workflows", "deploy.yml")
        with open(workflow_path, encoding="utf-8") as handle:
            workflow = handle.read()
        self.assertLess(
            workflow.index("python refresh_college_talent.py"),
            workflow.index("python multi_fetch.py --once"),
        )
        self.assertIn("git add -- 'ratings*.json'", workflow)


class PredictPriorBoostTests(unittest.TestCase):
    """A user-reported symptom on 2026-07-25: preseason predictions looked
    off for objectively mismatched teams (a P4 power vs. a bottom-tier
    program). Root cause: record/margin/form/srs are all correctly at (or
    near) zero with no games played, leaving class/rank/elo -- at their
    normal fixed weight, tuned assuming the other signals also contribute --
    to carry the entire signal alone. predict() now scales those three up as
    the average current-season sample shrinks, tapering back to no change at
    all once the season is established."""

    def setUp(self):
        self.old_key, self.old_comp = fetch_data.COMP_KEY, fetch_data.COMP
        self.old_ratings_file, self.old_ratings = fetch_data.RATINGS_FILE, fetch_data._RATINGS
        fetch_data.COMP_KEY = "NCAAF"
        fetch_data.COMP = dict(fetch_data.COMPETITIONS["NCAAF"])
        fd, self.tmp_path = tempfile.mkstemp(suffix=".json")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"Powerhouse": {"fifa_rank": 45, "squad_value_m": 1400, "star_value_m": 190},
                       "Underdog": {"fifa_rank": 45, "squad_value_m": 200, "star_value_m": 20}}, f)
        fetch_data.RATINGS_FILE = self.tmp_path
        fetch_data._RATINGS = None

    def tearDown(self):
        fetch_data.COMP_KEY, fetch_data.COMP = self.old_key, self.old_comp
        fetch_data.RATINGS_FILE, fetch_data._RATINGS = self.old_ratings_file, self.old_ratings
        os.unlink(self.tmp_path)

    def test_preseason_leans_harder_on_class_than_the_same_gap_in_season(self):
        home = {"name": "Powerhouse", "pts": 0, "gd": 0, "form": "", "pld": 0}
        away = {"name": "Underdog", "pts": 0, "gd": 0, "form": "", "pld": 0}
        preseason = fetch_data.predict(dict(home), dict(away), {}, {"stage": "Week 1", "weather": {}})
        # Same class gap, but with a real in-season sample on both sides --
        # record/margin start contributing, so the boost should ease off.
        home_est = dict(home, pld=10, w=9, l=1, win_pct=0.9, gf=350, ga=150)
        away_est = dict(away, pld=10, w=1, l=9, win_pct=0.1, gf=150, ga=350)
        established = fetch_data.predict(home_est, away_est, {}, {"stage": "Week 11", "weather": {}})
        self.assertGreater(preseason["why"]["class"], established["why"]["class"])
        self.assertGreater(preseason["confidence"], 50)

    def test_established_season_prediction_is_unaffected_by_the_boost(self):
        # avg_reliability == 1.0 once both teams hit american_cfg["full"]
        # games -- prior_boost must be exactly 1.0 (a no-op) at that point,
        # not just "smaller than preseason", so this never regresses any
        # already-tuned established-season behavior.
        home = {"name": "Powerhouse", "pts": 0, "gd": 0, "form": "", "pld": 10,
                "w": 5, "l": 5, "win_pct": 0.5, "gf": 250, "ga": 250}
        away = {"name": "Underdog", "pts": 0, "gd": 0, "form": "", "pld": 10,
                "w": 5, "l": 5, "win_pct": 0.5, "gf": 250, "ga": 250}
        pred = fetch_data.predict(home, away, {}, {"stage": "Week 11", "weather": {}})
        home_class = fetch_data.rating_parts("Powerhouse")
        away_class = fetch_data.rating_parts("Underdog")
        self.assertAlmostEqual(pred["why"]["class"],
                               round(sum(home_class.values()) - sum(away_class.values()), 2))


class ApiFootballInjuryParsingTests(unittest.TestCase):
    """fetch_api_football_injuries() went live 2026-07-25 -- soccer's first
    real injury feed. _parse_af_injuries() is the piece that turns
    API-FOOTBALL's raw /injuries rows into predict()'s m['injuries'] shape."""

    def _match(self):
        return {"home": {"name": "Kristiansund BK"}, "away": {"name": "Start"}}

    def test_dedupes_repeated_provider_rows(self):
        # Regression: confirmed live against a real fixture (1494712) on
        # 2026-07-25 that API-FOOTBALL's own /injuries response repeats
        # every row verbatim -- 14 rows for 7 distinct players, identical
        # player id and fixture id each time. Without a dedupe, the same
        # absence would double-count in predict()'s injury nudge.
        row = {"player": {"id": 544483, "name": "D. Tufekcic", "type": "Missing Fixture",
                           "reason": "Thigh Injury"},
               "team": {"name": "Kristiansund BK"}}
        payload = {"response": [row, dict(row)]}
        out = fetch_data._parse_af_injuries(payload, self._match(), "1494712")
        self.assertEqual(out["home"], ["D. Tufekcic (Out - Thigh Injury)"])

    def test_confirmed_absence_vs_doubtful_labeling(self):
        payload = {"response": [
            {"player": {"id": 1, "name": "Out Player", "type": "Missing Fixture", "reason": "Injury"},
             "team": {"name": "Kristiansund BK"}},
            {"player": {"id": 2, "name": "Doubt Player", "type": "Questionable", "reason": "Illness"},
             "team": {"name": "Start"}},
        ]}
        out = fetch_data._parse_af_injuries(payload, self._match(), "1")
        self.assertEqual(out["home"], ["Out Player (Out - Injury)"])
        self.assertEqual(out["away"], ["Doubt Player (Questionable - Illness)"])

    def test_unmatched_team_and_missing_name_are_dropped(self):
        payload = {"response": [
            {"player": {"id": 1, "name": "Some Player", "type": "Missing Fixture"},
             "team": {"name": "Some Other Club"}},
            {"player": {"id": 2, "name": "", "type": "Missing Fixture"},
             "team": {"name": "Kristiansund BK"}},
        ]}
        out = fetch_data._parse_af_injuries(payload, self._match(), "1")
        self.assertEqual(out["home"], [])
        self.assertEqual(out["away"], [])

    def test_no_reason_omits_the_trailing_dash(self):
        payload = {"response": [
            {"player": {"id": 1, "name": "Bare Player", "type": "Missing Fixture", "reason": ""},
             "team": {"name": "Kristiansund BK"}},
        ]}
        out = fetch_data._parse_af_injuries(payload, self._match(), "1")
        self.assertEqual(out["home"], ["Bare Player (Out)"])


class SportsDataIOCacheConfirmationTests(unittest.TestCase):
    def setUp(self):
        self.old_comp = fetch_data.COMP_KEY
        fetch_data.COMP_KEY = "MLB"
        self.match = {
            "id": "mlb-1", "kickoff": "2026-08-18T20:00:00Z",
            "home": {"name": "Alpha", "code": "ALP"},
            "away": {"name": "Beta", "code": "BET"},
        }

    def tearDown(self):
        fetch_data.COMP_KEY = self.old_comp

    def row(self):
        return {
            "fixture_identity": fetch_data._sportsdataio_cache_identity(self.match),
            "lineups": {
                "scheduled_at": self.match["kickoff"], "confirmed": True,
                "home": {"confirmed": True, "xi": [{"name": "H", "confirmed": True}]},
                "away": {"confirmed": True, "xi": [{"name": "A", "confirmed": True}]},
            },
            "personnel": {
                "starting_pitchers": {
                    "home": {"name": "HP", "confirmed": True},
                    "away": {"name": "AP", "confirmed": True},
                },
                "starting_pitchers_confirmed": True,
                "injuries_confirmed": True,
            },
        }

    def test_stale_cache_downgrades_every_confirmation(self):
        fetch_data._merge_sportsdataio_cached_pregame(self.match, self.row(), stale=True)
        self.assertFalse(self.match["lineups"]["confirmed"])
        self.assertFalse(self.match["lineups"]["home"]["xi"][0]["confirmed"])
        self.assertFalse(self.match["personnel"]["starting_pitchers_confirmed"])
        self.assertFalse(self.match["personnel"]["starting_pitchers"]["home"]["confirmed"])
        self.assertFalse(self.match["personnel"]["injuries_confirmed"])

    def test_fresh_cache_requires_exact_fixture_both_sides_and_pitchers(self):
        row = self.row()
        row["personnel"]["starting_pitchers"]["away"]["confirmed"] = False
        fetch_data._merge_sportsdataio_cached_pregame(self.match, row)
        self.assertFalse(self.match["lineups"]["confirmed"])

        other = self.row()
        other["fixture_identity"]["kickoff"] = "2026-08-18T21:00:00Z"
        fetch_data._merge_sportsdataio_cached_pregame(self.match, other)
        self.assertFalse(self.match["lineups"]["confirmed"])

        fetch_data._merge_sportsdataio_cached_pregame(self.match, self.row())
        self.assertTrue(self.match["lineups"]["confirmed"])
        self.assertTrue(self.match["personnel"]["starting_pitchers_confirmed"])

    def test_licensed_cache_does_not_erase_earlier_personnel(self):
        """This overlay runs last. Replacing the dict dropped what came before.

        The SportsGameOdds overlay and the bullpen-rest proxy both write into
        personnel earlier in the run, so assigning the cached dict wholesale
        deleted starter candidates, market-listed hitters and bullpen rest from
        every fixture the licensed cache also covered.
        """
        self.match["personnel"] = {
            "starter_candidates": {"home": {"name": "Candidate", "confirmed": False}},
            "market_listed_hitters": {"home": [{"name": "Hitter"}], "away": []},
            "bullpen": {"home": {"status": "elevated"}},
            "bullpen_confirmed": False,
        }
        fetch_data._merge_sportsdataio_cached_pregame(self.match, self.row())
        personnel = self.match["personnel"]
        self.assertEqual(personnel["starter_candidates"]["home"]["name"], "Candidate")
        self.assertEqual(personnel["market_listed_hitters"]["home"][0]["name"], "Hitter")
        self.assertEqual(personnel["bullpen"]["home"]["status"], "elevated")
        self.assertTrue(personnel["starting_pitchers_confirmed"])


class SportsGameOddsOverlayTests(unittest.TestCase):
    @staticmethod
    def event():
        def odd(side, home_price, away_price):
            prices = {"fanduel": home_price if side == "home" else away_price,
                      "espnbet": "-500"}
            return {"statID": "points", "periodID": "game", "betTypeID": "ml",
                    "sideID": side, "byBookmaker": {
                        book: {"odds": price, "available": True}
                        for book, price in prices.items()}}
        return {"eventID": "provider-event", "info": {"venue": "Test Park"},
                "teams": {
                    "home": {"teamID": "BOSTON_RED_SOX_MLB",
                             "names": {"long": "Boston Red Sox", "short": "BOS"}},
                    "away": {"teamID": "NEW_YORK_YANKEES_MLB",
                             "names": {"long": "New York Yankees", "short": "NYY"}},
                },
                "players": {"private-raw": {"name": "Not A Confirmed Lineup"}},
                "odds": {"home": odd("home", "+110", "-120"),
                         "away": odd("away", "+110", "-120")}}

    def test_legacy_sgo_cache_cannot_restore_canonical_mlb_personnel(self):
        match = {"id": "mlb-1", "markets": {}, "personnel": {}}
        legacy = {
            "personnel": {
                "starting_pitchers": {"home": {"name": "Prop Pitcher"}},
                "market_listed_hitters": {"home": [{"name": "Listed Hitter"}]},
            },
            "lineups": {"home": {"xi": [{"name": "Prop Batter"}]}},
        }
        fetch_data._merge_sportsgameodds_overlay(match, legacy)
        self.assertNotIn("starting_pitchers", match["personnel"])
        self.assertNotIn("lineups", match)
        self.assertEqual(match["personnel"]["market_listed_hitters"]["home"][0]["name"],
                         "Listed Hitter")

        current = {"personnel": {"starter_candidates": {
            "home": {"name": "Clearly Unconfirmed", "confirmed": False}}}}
        fetch_data._merge_sportsgameodds_overlay(match, current)
        self.assertEqual(match["personnel"]["starter_candidates"]["home"]["name"],
                         "Clearly Unconfirmed")
        self.assertNotIn("starting_pitchers", match["personnel"])


class StandingsAndMarketUpsetRadarTests(unittest.TestCase):
    def _profile(self, home_w, away_w, market_away):
        home = {"name": "Good Team", "pld": 100, "w": home_w, "pts": home_w * 3}
        away = {"name": "Bad Team", "pld": 100, "w": away_w, "pts": away_w * 3}
        markets = {"1x2": {"home_pct": 100 - market_away, "away_pct": market_away}}
        _, info = fetch_data._upset_adjustment(
            home, away, markets, {}, {}, {"h": 62, "d": 0, "a": 38}, two_way=True)
        return info

    def test_radar_requires_both_a_standings_gap_and_large_market_edge(self):
        info = self._profile(home_w=70, away_w=40, market_away=25)
        self.assertTrue(info["radar"])
        self.assertEqual(info["standings_candidate"], "a")
        self.assertEqual(info["standings_gap_pct"], 30.0)
        self.assertGreaterEqual(info["upset_edge"], 8)

    def test_large_market_edge_without_standings_mismatch_is_not_upset_risk(self):
        info = self._profile(home_w=55, away_w=50, market_away=25)
        self.assertFalse(info["radar"])
        self.assertIsNone(info["standings_candidate"])

    def test_standings_mismatch_without_large_market_edge_is_not_upset_risk(self):
        info = self._profile(home_w=70, away_w=40, market_away=35)
        self.assertFalse(info["radar"])
        self.assertLess(info["upset_edge"], 8)

    def test_small_or_missing_season_sample_is_not_upset_risk(self):
        home = {"name": "Good Team", "pld": 4, "w": 4}
        away = {"name": "Bad Team", "pld": 4, "w": 0}
        markets = {"1x2": {"home_pct": 75, "away_pct": 25}}
        _, info = fetch_data._upset_adjustment(
            home, away, markets, {}, {}, {"h": 62, "d": 0, "a": 38}, two_way=True)
        self.assertFalse(info["radar"])
        self.assertFalse(info["standings_sample_ok"])


class OfficialUnderdogSelectionTests(unittest.TestCase):
    def setUp(self):
        self.old_key, self.old_comp = fetch_data.COMP_KEY, fetch_data.COMP

    def tearDown(self):
        fetch_data.COMP_KEY, fetch_data.COMP = self.old_key, self.old_comp

    def _profile(self, competition="NCAAM", *, model=None, why=None, match=None,
                 blend=None, market=None):
        fetch_data.COMP_KEY = competition
        fetch_data.COMP = dict(fetch_data.COMPETITIONS[competition])
        two_way = not fetch_data.COMP.get("has_draws", True)
        home = {"name": "Market Favorite", "pld": 30, "w": 20, "pts": 60}
        away = {"name": "Market Underdog", "pld": 30, "w": 15, "pts": 45}
        market = market or ({"home_pct": 55, "draw_pct": 0, "away_pct": 45,
                             "books": 5, "spread": 6})
        blend = blend or {"h": 52, "d": 0, "a": 48}
        model = model or {"h": 42, "d": 0, "a": 58}
        why = why if why is not None else {"srs": -1.2, "form": -0.8, "elo": -0.5}
        _, info = fetch_data._upset_adjustment(
            home, away, {"1x2": market}, match or {}, why, blend,
            two_way=two_way, model_probs=model,
        )
        return info

    def test_two_way_market_underdog_can_become_official_pick(self):
        info = self._profile()
        self.assertEqual(info["candidate"], "a")
        self.assertTrue(info["independent_pick_gate"])
        self.assertGreaterEqual(info["independent_edge"], info["edge_threshold"])
        self.assertTrue(info["evidence_gate"])
        self.assertTrue(info["triggered"])

    def test_market_underdog_stays_watch_only_when_model_does_not_rank_it_first(self):
        info = self._profile(model={"h": 54, "d": 0, "a": 46})
        self.assertFalse(info["independent_pick_gate"])
        self.assertFalse(info["triggered"])

    def test_two_independent_production_factors_are_required(self):
        info = self._profile(why={"elo": -1.0})
        self.assertFalse(info["evidence_gate"])
        self.assertTrue(info["blocked"])
        self.assertFalse(info["triggered"])

    def test_pickem_market_does_not_invent_an_underdog(self):
        info = self._profile(market={"home_pct": 50, "draw_pct": 0, "away_pct": 50,
                                     "books": 5, "spread": 4})
        self.assertFalse(info["market_quality_gate"])
        self.assertFalse(info["triggered"])

class ProStandingsFormattingTests(unittest.TestCase):
    @staticmethod
    def _flat_table(competition):
        names = []
        for group_names in fetch_data.US_PRO_STANDINGS_GROUPS[competition].values():
            for name in group_names:
                # Avoid aliases that deliberately map to the same franchise.
                if name in {"Athletics", "LA Clippers"}:
                    continue
                names.append(name)
        teams = [{"name": name, "code": "", "pld": 10, "w": i % 8 + 1,
                  "l": 10 - (i % 8 + 1), "d": 0, "gf": 100 + i,
                  "ga": 90, "gd": 10 + i, "rating": 5 + i / 100}
                 for i, name in enumerate(names)]
        return [{"group": "", "teams": teams}]

    def test_matchday_top_25_is_model_sorted_and_separate_from_poll(self):
        tables = [{"group": "Conference", "teams": [
            {"name": "Model One", "rating": 8.4, "record": "8-1"},
            {"name": "AP Number One", "rating": 7.1, "record": "9-0"},
            {"name": "Model Two", "rating": 7.9, "record": "7-2"},
        ]}]
        table = fetch_data._matchday_top_25(tables)
        self.assertEqual(table["group"], "Matchday Top 25")
        self.assertEqual(table["table_type"], "matchday_top_25")
        self.assertEqual([team["name"] for team in table["teams"]],
                         ["Model One", "Model Two", "AP Number One"])
        self.assertEqual([team["pos"] for team in table["teams"]], [1, 2, 3])

    def test_matchday_top_25_adds_sample_weighted_opponent_adjustment(self):
        tables = [{"group": "Conference", "teams": [
            {"name": "Prior Leader", "rating": 9.0, "srs": -10.0, "srs_games": 12},
            {"name": "Strong Schedule", "rating": 8.9, "srs": 12.0, "srs_games": 12},
            {"name": "Thin Sample", "rating": 8.8, "srs": 5.0, "srs_games": 1},
            {"name": "Fourth", "rating": 7.0, "srs": -2.0, "srs_games": 12},
            {"name": "Fifth", "rating": 6.0, "srs": -8.0, "srs_games": 12},
        ]}]
        table = fetch_data._matchday_top_25(tables)
        self.assertEqual(table["teams"][0]["name"], "Strong Schedule")
        self.assertLess(table["teams"][2]["ranking_score"],
                        table["teams"][0]["ranking_score"])

    def test_ncaaf_current_season_weight_reaches_full_strength_in_twelve_games(self):
        original_key = fetch_data.COMP_KEY
        original_ratings = fetch_data._RATINGS
        original_elo = fetch_data._ELO
        try:
            fetch_data.set_competition("NCAAF")
            fetch_data._RATINGS = {"example": {"squad_value_m": 500, "star_value_m": 100}}
            fetch_data._ELO = {"_version": fetch_data.ELO_STORE_VERSION, "teams": {}, "seen": {}}
            twelve = fetch_data.power_rating("Example", {"pld": 12, "w": 12, "d": 0})
            forty = fetch_data.power_rating("Example", {"pld": 40, "w": 40, "d": 0})
            self.assertAlmostEqual(twelve, forty)
        finally:
            fetch_data.set_competition(original_key)
            fetch_data._RATINGS = original_ratings
            fetch_data._ELO = original_elo

    def test_placeholder_side_never_becomes_a_31st_standings_team(self):
        # Live 2026-07-30: data_mlb.json carried 31 MLB "teams" -- the extra
        # one was named "Unknown" with a 1-1 record, both sides of a single
        # game credited to the same phantom key.
        finished = [
            {"status": "FINISHED", "kickoff": "2026-07-15T00:00:00Z",
             "home": {"name": "Unknown"}, "away": {"name": "Unknown"},
             "score": {"home": 0, "away": 4}},
            {"status": "FINISHED", "kickoff": "2026-07-15T00:00:00Z",
             "home": {"name": "Boston Red Sox"}, "away": {"name": "TBD"},
             "score": {"home": 3, "away": 1}},
            {"status": "FINISHED", "kickoff": "2026-07-16T00:00:00Z",
             "home": {"name": "Boston Red Sox"}, "away": {"name": "New York Yankees"},
             "score": {"home": 5, "away": 2}},
        ]
        model, tables = fetch_data.compute_us_sport_standings(finished)
        self.assertEqual(sorted(model), ["boston red sox", "new york yankees"])
        # The one real game is still counted in full.
        self.assertEqual(model["boston red sox"]["pld"], 1)
        self.assertEqual([t["name"] for t in tables[0]["teams"]],
                         ["Boston Red Sox", "New York Yankees"])

    def test_nfl_tie_counts_as_half_a_win_in_standings_percentage(self):
        self.assertEqual(fetch_data._pro_standings_pct({"pld": 2, "w": 1, "d": 1}), 0.75)


class ApiFootballBoxScoreEdgeTests(unittest.TestCase):
    """box_score_edge inside _upset_adjustment() was dead in practice for as
    long as fetch_api_football_box_scores() went uncalled -- m['stats_extra']
    was never populated for soccer. Confirms real API-FOOTBALL stats-shaped
    data (matching _parse_af_stats()'s output) now drives a nonzero edge."""

    def test_underdog_dominating_the_box_score_produces_a_positive_edge(self):
        # Market favors home (Kristiansund) 70/30, but the real box score
        # (shaped exactly like _parse_af_stats()'s output) shows away
        # (Start) dominating -- the scenario strong_box_override exists to
        # catch. Values below mirror what was fetched live from API-FOOTBALL
        # fixture 1494712 on 2026-07-25.
        m = {"stats_extra": {
            "home": {"shots": 7, "shots_on_target": 2, "possession": 44, "corners": 3,
                      "fouls": 11, "offsides": 0, "saves": 3, "yellow_cards": 3, "red_cards": 1},
            "away": {"shots": 22, "shots_on_target": 5, "possession": 56, "corners": 6,
                      "fouls": 15, "offsides": 0, "saves": 1, "yellow_cards": 2, "red_cards": 0},
            "source": "API-FOOTBALL", "fixture_id": "1494712"}}
        home = {"name": "Kristiansund BK"}
        away = {"name": "Start"}
        markets = {"1x2": {"home_pct": 70, "away_pct": 30}}
        blend = {"h": 70, "d": 0, "a": 30}
        why = {"form": 4, "gd": 2, "pts": 3}
        _, info = fetch_data._upset_adjustment(home, away, markets, m, why, blend)
        self.assertEqual(info["candidate"], "a")
        self.assertGreater(info["box_score_edge"], 0.35)

    def test_no_stats_extra_leaves_the_edge_at_zero(self):
        m = {}
        home = {"name": "Kristiansund BK"}
        away = {"name": "Start"}
        markets = {"1x2": {"home_pct": 70, "away_pct": 30}}
        blend = {"h": 70, "d": 0, "a": 30}
        _, info = fetch_data._upset_adjustment(home, away, markets, m, {}, blend)
        self.assertEqual(info["box_score_edge"], 0.0)


class StrengthFloorTests(unittest.TestCase):
    """This session's fix reducing the American branch's flat 'base' anchor
    from 8.0 to 4.0 (see PredictPriorBoostTests' sibling context) had a real
    side effect: parts()'s sh/sa floor-clamp (`max(0.1, sum(ph.values()))`)
    was tuned for the old base, where crossing zero required a huge negative
    swing and the clamp was an almost-never-hit safety net. At base=4.0, a
    merely bad-but-ordinary team's raw sum routinely dips slightly negative
    and got clamped to the exact same 0.1 as a historically dreadful team,
    collapsing the ratio to a false-certainty 99/1 instead of a believable
    reading. Reproduced 2026-07-25 against real cached NFL fixtures
    (data_nfl.json): Jacksonville Jaguars (13-5) vs Cleveland Browns (5-12)
    and LA Chargers (11-7) vs Arizona Cardinals (3-14) both rounded to 99/1
    under base=4.0 with the old 0.1 floor, versus a sane ~80/20 hand-
    reconstructed with the old base=8.0 for the same inputs. Scanning all 224
    cached NFL fixtures: 33/224 (14.7%) rounded to a >=99%/<=1% split with the
    old floor; raising the American branch's floor to 1.5 brings that to
    0/224 while the median favorite-pct improvement from the base reduction
    (60%ish pre-session -> high-60s) is still mostly intact (68%, vs 72%
    with the buggy floor -- the 72% number was itself inflated by the very
    99/1 degenerate cases this fix removes)."""

    def setUp(self):
        self.old_key, self.old_comp = fetch_data.COMP_KEY, fetch_data.COMP
        fetch_data.COMP_KEY = "NCAAF"
        fetch_data.COMP = dict(fetch_data.COMPETITIONS["NCAAF"])

    def tearDown(self):
        fetch_data.COMP_KEY, fetch_data.COMP = self.old_key, self.old_comp

    def test_moderately_bad_team_does_not_collapse_to_a_false_99_1(self):
        # Real season lines (data_nfl.json, 2026-07-25): a clearly-worse-but-
        # not-historically-hopeless team should read as a real underdog, not
        # a mathematical impossibility.
        jaguars = {"name": "Jacksonville Jaguars", "pld": 18, "w": 13, "l": 5,
                   "gf": 498, "ga": 363, "srs": 8.107, "srs_games": 18,
                   "rest_days": 245, "form_home": "W W W W L", "form_away": "L W W W W"}
        browns = {"name": "Cleveland Browns", "pld": 17, "w": 5, "l": 12,
                  "gf": 279, "ga": 379, "srs": -7.093, "srs_games": 17,
                  "rest_days": 252, "form_home": "L L L L W", "form_away": "L L W L W"}
        pred = fetch_data.predict(dict(jaguars), dict(browns), {}, {"stage": "Week 18", "weather": {}})
        fav_pct = max(pred["blend"]["h"], pred["blend"]["a"])
        self.assertLess(fav_pct, 95)
        self.assertGreater(pred["blend"]["a"], 1)

    def test_historically_bad_team_still_reads_as_a_heavy_underdog(self):
        # The floor fix must not flatten a genuinely one-sided matchup into
        # a coin flip -- an 0-17-caliber team should still be a clear dog.
        good = {"name": "Contender", "pld": 17, "w": 15, "l": 2,
                "gf": 500, "ga": 300, "srs": 12.0, "srs_games": 17, "rest_days": 7}
        bad = {"name": "Bottom Feeder", "pld": 17, "w": 1, "l": 16,
               "gf": 250, "ga": 500, "srs": -12.0, "srs_games": 17, "rest_days": 7}
        pred = fetch_data.predict(dict(good), dict(bad), {}, {"stage": "Week 18", "weather": {}})
        self.assertEqual(pred["pick"], "h")
        self.assertGreater(pred["blend"]["h"], 80)


class ProbabilityCalibrationTests(unittest.TestCase):
    """2026-08-18 ledger audit of all 255 graded MLB fixtures in
    picks_log_mlb.json (2026-07-27 .. 2026-08-17, the entire recorded
    history): the shipped independent read was worse than a coin flip --
    mean log loss 0.7215 against 0.6931 for a flat 50/50, AUC 0.525, and a
    stated 70-74% confidence bucket that hit 54.7% (n=53). The cause is that
    predict()'s sh/(sh+sa) strength ratio is never fitted to outcomes and its
    factor weights were tuned on higher-signal American sports, so it emits an
    NBA-shaped spread for a sport whose true single-game win probability
    rarely leaves 35-65%.

    Leave-one-game-date-out cross-validation over the 22 game-date blocks
    chose a shrink factor inside 0.05-0.30 on every single fold and cut
    held-out log loss from 0.7290 to 0.6986, so the correction's direction is
    robust to the sample even though its exact size is not. PROB_CALIBRATION
    ships 0.35 -- above every fold's choice, i.e. deliberately under-
    correcting rather than claiming more shrinkage than 255 games can prove.
    Replaying the full ledger through the shipped constant gives 0.6960.

    The critical scope guarantee these tests protect: sports with no graded
    evidence are absent from PROB_CALIBRATION and must be bit-for-bit
    unchanged."""

    def test_uncalibrated_sports_are_an_exact_no_op(self):
        for probs in ({"h": 57, "d": 0, "a": 43},
                      {"h": 40, "d": 26, "a": 34},
                      {"h": 91, "d": 0, "a": 9}):
            for comp in ("NFL", "NBA", "NCAAF", "NHL", "EPL"):
                self.assertNotIn(comp, fetch_data.PROB_CALIBRATION)
                factor = fetch_data._calibration_factor(comp)
                self.assertEqual(factor, 1.0)
                self.assertEqual(fetch_data._calibrate_probs(probs, factor), probs)

    def test_calibration_preserves_the_side_and_never_flips_a_pick(self):
        factor = fetch_data._calibration_factor("MLB")
        for h in range(1, 100):
            probs = {"h": h, "d": 0, "a": 100 - h}
            out = fetch_data._calibrate_probs(probs, factor)
            self.assertEqual(sum(out.values()), 100)
            if h > 50:
                self.assertGreaterEqual(out["h"], out["a"])
            elif h < 50:
                self.assertGreaterEqual(out["a"], out["h"])

    def test_draw_leg_is_left_alone(self):
        # The draw rate is derived separately (pre_draw_gap taper) and has its
        # own evidence -- this correction targets the side read only.
        out = fetch_data._calibrate_probs({"h": 50, "d": 26, "a": 24}, 0.35)
        self.assertEqual(out["d"], 26)

    def test_model_identity_moved_with_the_output_change(self):
        # MLB_RECOVERY.md forbids pooling mixed model artifacts, so any change
        # to emitted probabilities must land in a new cohort.
        self.assertEqual(fetch_data.MODEL_SIGNAL_SCHEMA, 8)
        self.assertEqual(fetch_data.PREDICTION_MODEL_VERSION, "v6-calibrated")


class TalentShareCurveTests(unittest.TestCase):
    """2026-07-26 user-reported symptom: real Vegas lines for Week 1 2026
    NCAAF (USC -35.5/-50000ML over San Jose State, Florida State -28.5/
    -10000ML over New Mexico State, etc.) imply 98.5-99.8% favorites, but
    the deployed preseason model topped out around 60-64% for the exact
    same real-shaped CFBD talent gap -- apply_recruiting_strength's flat
    share**0.7 curve (added to fix a DIFFERENT problem, Build 0725B: a
    middling P4 team crushing a good G5 team almost to nothing) also
    over-protects a genuine bottom-of-FBS team, since 0.2**0.7 ~= 0.34 --
    a team at one-fifth of the national ceiling still keeps a third of the
    scaling weight. _talent_share_curve fixes this with a floor: unchanged
    above it (protects the original Build 0725B case), steeper below it
    (real bottom-tier teams pull apart from the pack instead of blurring
    toward it)."""

    def setUp(self):
        self.old_key, self.old_comp = fetch_data.COMP_KEY, fetch_data.COMP
        self.old_ratings_file, self.old_ratings = fetch_data.RATINGS_FILE, fetch_data._RATINGS
        fd, self.tmp_path = tempfile.mkstemp(suffix=".json")
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump({}, handle)
        fetch_data.RATINGS_FILE = self.tmp_path
        fetch_data._RATINGS = None

    def tearDown(self):
        fetch_data.COMP_KEY, fetch_data.COMP = self.old_key, self.old_comp
        fetch_data.RATINGS_FILE, fetch_data._RATINGS = self.old_ratings_file, self.old_ratings
        os.unlink(self.tmp_path)

    def test_at_or_above_the_competitive_floor_is_unchanged_from_the_flat_curve(self):
        for share in (0.58, 0.65, 0.826, 1.0):
            self.assertAlmostEqual(fetch_data._talent_share_curve(share), share ** 0.7, places=9)

    def test_below_the_floor_falls_off_faster_than_the_old_flat_curve(self):
        # San Jose State's real 2025 CFBD talent share (~0.52) vs the old,
        # unconditional share**0.7 curve.
        share = 0.52
        self.assertLess(fetch_data._talent_share_curve(share), share ** 0.7)

    def test_falloff_below_the_floor_is_continuous_at_the_boundary(self):
        # No cliff right at the floor -- a team just below it should land
        # close to a team just above it, not jump discontinuously.
        just_below = fetch_data._talent_share_curve(0.579)
        just_above = fetch_data._talent_share_curve(0.58)
        self.assertAlmostEqual(just_below, just_above, delta=0.01)

    def test_the_further_below_the_floor_the_steeper_the_penalty(self):
        # New Mexico State's real 2025 share (~0.40) is much further below
        # the floor than San Jose State's (~0.52) -- it should lose
        # proportionally more of its scaling weight, not the same fraction.
        near_floor = fetch_data._talent_share_curve(0.52) / (0.52 ** 0.7)
        far_below = fetch_data._talent_share_curve(0.40) / (0.40 ** 0.7)
        self.assertLess(far_below, near_floor)

    def test_ceiling_case_is_unaffected(self):
        # The share==1.0 ceiling test (test_recruiting_and_market_strength_
        # reach_the_full_class_scale) must keep landing exactly on 1500/200.
        fetch_data.COMP_KEY = "NCAAM"
        fetch_data.COMP = dict(fetch_data.COMPETITIONS["NCAAM"])
        fetch_data.apply_recruiting_strength({"Duke": 100.0})
        top = fetch_data._ratings_lookup("Duke")
        self.assertEqual(top["squad_value_m"], 1500)
        self.assertEqual(top["star_value_m"], 200)


class NCAAFBlowoutConfidenceTests(unittest.TestCase):
    """Real 2025 CFBD Team Talent Composite spot check (live-pulled
    2026-07-26, /talent?year=2025) for the exact four matchups in the
    user's proof, plus three real "good G5 vs middling P4" matchups to
    confirm the fix widens the genuinely-separated blowout case without
    dragging the moderate case anywhere near it. National max was Georgia
    at 1002.98; every score below is the real team_scores value CFBD
    returned for that team, fed through the real apply_recruiting_strength
    -> predict() pipeline, at pld=0 (true preseason, matching the real
    screenshots -- Week 1, 0-0 records)."""

    REAL_TALENT_2025 = {
        "Georgia": 1002.98,  # national max, sets share denominator
        "USC": 847.53, "San Jose State": 522.91,
        "Florida State": 828.45, "New Mexico State": 402.9,
        "Illinois": 662.13, "UAB": 540.93,
        "Rutgers": 689.22, "Massachusetts": 488.73,
        "Michigan State": 717.42, "Boise State": 610.65,
        "Kansas": 705.32, "Memphis": 668.63,
        "Purdue": 687.74, "Toledo": 620.13,
    }

    def setUp(self):
        self.old_key, self.old_comp = fetch_data.COMP_KEY, fetch_data.COMP
        self.old_ratings_file, self.old_ratings = fetch_data.RATINGS_FILE, fetch_data._RATINGS
        # Isolate Elo/H2H too -- see NCAAMBlowoutConfidenceTests.setUp for
        # why: both are shared, live, mutable files the historical backfill
        # writes real data into in the background, and these tests assert
        # exact confidence thresholds.
        self.old_elo_file, self.old_elo = fetch_data.ELO_FILE, fetch_data._ELO
        self.old_h2h_file, self.old_h2h = fetch_data.H2H_FILE, fetch_data._H2H
        fetch_data.COMP_KEY = "NCAAF"
        fetch_data.COMP = dict(fetch_data.COMPETITIONS["NCAAF"])
        fd, self.tmp_path = tempfile.mkstemp(suffix=".json")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({}, f)
        fetch_data.RATINGS_FILE = self.tmp_path
        fetch_data._RATINGS = None
        efd, self.elo_tmp_path = tempfile.mkstemp(suffix=".json")
        os.close(efd)
        fetch_data.ELO_FILE = self.elo_tmp_path
        fetch_data._ELO = None
        hfd, self.h2h_tmp_path = tempfile.mkstemp(suffix=".json")
        os.close(hfd)
        fetch_data.H2H_FILE = self.h2h_tmp_path
        fetch_data._H2H = None
        fetch_data.apply_recruiting_strength(dict(self.REAL_TALENT_2025))

    def tearDown(self):
        fetch_data.COMP_KEY, fetch_data.COMP = self.old_key, self.old_comp
        fetch_data.RATINGS_FILE, fetch_data._RATINGS = self.old_ratings_file, self.old_ratings
        fetch_data.ELO_FILE, fetch_data._ELO = self.old_elo_file, self.old_elo
        fetch_data.H2H_FILE, fetch_data._H2H = self.old_h2h_file, self.old_h2h
        os.unlink(self.tmp_path)
        os.unlink(self.elo_tmp_path)
        os.unlink(self.h2h_tmp_path)

    def _confidence(self, home, away):
        h = {"name": home, "pts": 0, "gd": 0, "form": "", "pld": 0}
        a = {"name": away, "pts": 0, "gd": 0, "form": "", "pld": 0}
        pred = fetch_data.predict(dict(h), dict(a), {}, {"stage": "Week 1", "weather": {}})
        return pred["blend"]["h"]

    def test_a_real_wide_talent_gap_reaches_a_clear_favorite_read(self):
        # Florida State (share 0.826) vs New Mexico State (share 0.402) is
        # the widest real gap of the four proof cases -- real books had FSU
        # at ~99%. The recruiting-talent signal alone can't responsibly
        # manufacture that exact number (see the written-up findings), but
        # it should now read as a clear, real favorite instead of a
        # near-coin-flip 56/44.
        self.assertGreater(self._confidence("Florida State", "New Mexico State"), 70)

    def test_every_proof_case_moves_toward_the_favorite_not_away(self):
        for home, away in (("USC", "San Jose State"), ("Florida State", "New Mexico State"),
                            ("Illinois", "UAB"), ("Rutgers", "Massachusetts")):
            self.assertGreater(self._confidence(home, away), 50)

    def test_a_moderate_good_g5_vs_middling_p4_gap_stays_believable(self):
        # Real 2025 shares: Michigan State 0.715 vs Boise State 0.609,
        # Kansas 0.703 vs Memphis 0.667, Purdue 0.686 vs Toledo 0.618 --
        # all comfortably above _talent_share_curve's competitive floor, so
        # none of them should be dragged anywhere near the blowout cases
        # above just because the extreme end got more dynamic range.
        for home, away in (("Michigan State", "Boise State"), ("Kansas", "Memphis"),
                            ("Purdue", "Toledo")):
            conf = self._confidence(home, away)
            self.assertLess(conf, 60, f"{home} vs {away} should stay believable, got {conf}")

    def test_moderate_case_is_untouched_by_the_extremity_gate(self):
        # The base-shrink only engages once the class gap clears GAP_LO --
        # every moderate real case above sits well under that, so it must
        # be bit-for-bit identical to a run with the gate forced off.
        with_gate = self._confidence("Michigan State", "Boise State")
        pred = fetch_data.predict(
            {"name": "Michigan State", "pts": 0, "gd": 0, "form": "", "pld": 0},
            {"name": "Boise State", "pts": 0, "gd": 0, "form": "", "pld": 0},
            {}, {"stage": "Week 1", "weather": {}})
        self.assertLess(abs(pred["why"]["class"]), 3.0)  # confirms it's really under GAP_LO
        self.assertEqual(with_gate, self._confidence("Michigan State", "Boise State"))


class NCAAMBlowoutConfidenceTests(unittest.TestCase):
    """Same investigation as NCAAFBlowoutConfidenceTests, extended to
    NCAAM: apply_recruiting_strength is shared code (CollegeBasketballData
    Adapter.recruiting() feeds the identical function CFBD's talent() does),
    so the same curve-compression root cause applies here too -- confirmed
    with a real 2025 CBBD /recruiting/teams spot check (live-pulled
    2026-07-26) rather than assumed. Unlike NCAAF's four proof cases,
    NCAAM's real recruiting-rating data has much more genuine separation
    between a true blue-blood and a true bottom-of-D1 team (Duke sat at the
    national max this cycle; several real bottom-tier teams reported the
    provider's own floor value), so this is the case where the fix can
    responsibly reach the 90%+ neighborhood without inventing signal that
    isn't there -- see the module docstring's before/after numbers."""

    REAL_RECRUITING_2025 = {
        "Duke": 70.04, "Morehead State": 10.0, "UC Irvine": 12.0,
        "Gonzaga": 45.33, "Wake Forest": 37.17,
        "Houston": 68.54, "Boston College": 43.81,
    }

    def setUp(self):
        self.old_key, self.old_comp = fetch_data.COMP_KEY, fetch_data.COMP
        self.old_ratings_file, self.old_ratings = fetch_data.RATINGS_FILE, fetch_data._RATINGS
        # Isolate Elo/H2H too, not just ratings -- these tests assert exact
        # confidence thresholds, and both stores are shared, live, mutable
        # files (the historical backfill script writes real data into them
        # in the background). Without resetting these, whatever the
        # backfill happens to have reached for "Duke"/"Houston"/etc. at test
        # time silently changes the result out from under a fixed threshold.
        self.old_elo_file, self.old_elo = fetch_data.ELO_FILE, fetch_data._ELO
        self.old_h2h_file, self.old_h2h = fetch_data.H2H_FILE, fetch_data._H2H
        fetch_data.COMP_KEY = "NCAAM"
        fetch_data.COMP = dict(fetch_data.COMPETITIONS["NCAAM"])
        fd, self.tmp_path = tempfile.mkstemp(suffix=".json")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({}, f)
        fetch_data.RATINGS_FILE = self.tmp_path
        fetch_data._RATINGS = None
        efd, self.elo_tmp_path = tempfile.mkstemp(suffix=".json")
        os.close(efd)
        fetch_data.ELO_FILE = self.elo_tmp_path
        fetch_data._ELO = None
        hfd, self.h2h_tmp_path = tempfile.mkstemp(suffix=".json")
        os.close(hfd)
        fetch_data.H2H_FILE = self.h2h_tmp_path
        fetch_data._H2H = None
        fetch_data.apply_recruiting_strength(dict(self.REAL_RECRUITING_2025))

    def tearDown(self):
        fetch_data.COMP_KEY, fetch_data.COMP = self.old_key, self.old_comp
        fetch_data.RATINGS_FILE, fetch_data._RATINGS = self.old_ratings_file, self.old_ratings
        fetch_data.ELO_FILE, fetch_data._ELO = self.old_elo_file, self.old_elo
        fetch_data.H2H_FILE, fetch_data._H2H = self.old_h2h_file, self.old_h2h
        os.unlink(self.tmp_path)
        os.unlink(self.elo_tmp_path)
        os.unlink(self.h2h_tmp_path)

    def _confidence(self, home, away):
        h = {"name": home, "pts": 0, "gd": 0, "form": "", "pld": 0}
        a = {"name": away, "pts": 0, "gd": 0, "form": "", "pld": 0}
        pred = fetch_data.predict(dict(h), dict(a), {}, {"stage": "Non-Conference", "weather": {}})
        return pred["blend"]["h"]

    def test_a_true_blue_blood_vs_bottom_of_d1_reaches_the_90_plus_neighborhood(self):
        # Real 2025 CBBD shares: Duke at the national max (1.0) vs Morehead
        # State at the provider's own reported floor (~0.14) -- a genuine,
        # data-backed blowout, unlike three of NCAAF's four proof cases.
        self.assertGreater(self._confidence("Duke", "Morehead State"), 80)
        self.assertGreater(self._confidence("Duke", "UC Irvine"), 80)

    def test_moderate_mid_major_vs_bottom_half_power_stays_believable(self):
        # Gonzaga (elite mid-major-turned-power, share 0.647) vs Wake
        # Forest (bottom-half ACC, share 0.531) and Houston (blue-blood
        # tier, 0.979) vs Boston College (bottom-half ACC, 0.625) are both
        # real, meaningfully-favored-but-not-a-lock matchups -- neither
        # should be dragged toward the Duke-tier read above.
        for home, away in (("Gonzaga", "Wake Forest"), ("Houston", "Boston College")):
            conf = self._confidence(home, away)
            self.assertLess(conf, 65, f"{home} vs {away} should stay believable, got {conf}")


class PredictedMarginTests(unittest.TestCase):
    """New field requested alongside the blowout-confidence fix: Matchday's
    own predicted point/goal margin (not copied from a sportsbook),
    derived from the same official win/draw/loss probabilities predict()
    already computes via the standard odds<->margin relationship, reusing
    american_cfg["margin"] as the per-sport scale rather than inventing a
    new one."""

    def setUp(self):
        self.old_key, self.old_comp = fetch_data.COMP_KEY, fetch_data.COMP

    def tearDown(self):
        fetch_data.COMP_KEY, fetch_data.COMP = self.old_key, self.old_comp

    def test_american_favorite_is_signed_positive_and_labeled_by_name(self):
        fetch_data.COMP_KEY = "NCAAF"
        fetch_data.COMP = dict(fetch_data.COMPETITIONS["NCAAF"])
        home = {"name": "Contender", "pld": 17, "w": 15, "l": 2,
                "gf": 500, "ga": 300, "srs": 12.0, "srs_games": 17, "rest_days": 7}
        away = {"name": "Bottom Feeder", "pld": 17, "w": 1, "l": 16,
                "gf": 250, "ga": 500, "srs": -12.0, "srs_games": 17, "rest_days": 7}
        pred = fetch_data.predict(dict(home), dict(away), {}, {"stage": "Week 18", "weather": {}})
        margin = pred["predicted_margin"]
        self.assertEqual(margin["unit"], "points")
        self.assertEqual(margin["favored"], "h")
        self.assertGreater(margin["value"], 0)
        self.assertIn("Contender by", margin["label"])

    def test_away_favorite_flips_the_sign_and_the_favored_side(self):
        fetch_data.COMP_KEY = "NCAAF"
        fetch_data.COMP = dict(fetch_data.COMPETITIONS["NCAAF"])
        home = {"name": "Bottom Feeder", "pld": 17, "w": 1, "l": 16,
                "gf": 250, "ga": 500, "srs": -12.0, "srs_games": 17, "rest_days": 7}
        away = {"name": "Contender", "pld": 17, "w": 15, "l": 2,
                "gf": 500, "ga": 300, "srs": 12.0, "srs_games": 17, "rest_days": 7}
        pred = fetch_data.predict(dict(home), dict(away), {}, {"stage": "Week 18", "weather": {}})
        margin = pred["predicted_margin"]
        self.assertEqual(margin["favored"], "a")
        self.assertLess(margin["value"], 0)
        self.assertIn("Contender by", margin["label"])

    def test_a_bigger_probability_gap_produces_a_bigger_margin(self):
        fetch_data.COMP_KEY = "NCAAF"
        fetch_data.COMP = dict(fetch_data.COMPETITIONS["NCAAF"])
        close = {"name": "A", "pld": 10, "w": 6, "l": 4, "gf": 250, "ga": 220,
                 "srs": 2.0, "srs_games": 10, "rest_days": 7}
        weak = {"name": "B", "pld": 10, "w": 4, "l": 6, "gf": 220, "ga": 250,
                "srs": -2.0, "srs_games": 10, "rest_days": 7}
        much_weaker = {"name": "C", "pld": 10, "w": 1, "l": 9, "gf": 150, "ga": 400,
                       "srs": -15.0, "srs_games": 10, "rest_days": 7}
        close_pred = fetch_data.predict(dict(close), dict(weak), {}, {"stage": "Week 11", "weather": {}})
        blowout_pred = fetch_data.predict(dict(close), dict(much_weaker), {}, {"stage": "Week 11", "weather": {}})
        self.assertGreater(blowout_pred["predicted_margin"]["value"], close_pred["predicted_margin"]["value"])

    def test_an_even_matchup_reads_as_even_not_a_fake_precise_number(self):
        fetch_data.COMP_KEY = "NCAAM"
        fetch_data.COMP = dict(fetch_data.COMPETITIONS["NCAAM"])
        a = {"name": "Even A", "pld": 20, "w": 10, "l": 10, "gf": 2200, "ga": 2200,
             "srs": 0.0, "srs_games": 20, "rest_days": 2}
        b = {"name": "Even B", "pld": 20, "w": 10, "l": 10, "gf": 2200, "ga": 2200,
             "srs": 0.0, "srs_games": 20, "rest_days": 2}
        pred = fetch_data.predict(dict(a), dict(b), {}, {"stage": "Regular Season", "weather": {}})
        self.assertAlmostEqual(pred["predicted_margin"]["value"], 0.0, delta=0.5)


class PreseasonTotalsTests(unittest.TestCase):
    """predict_totals() used to return None unconditionally whenever either
    side had pld==0 -- exactly the true-preseason case real sportsbooks
    already post totals lines for (the 2026-07-25 screenshots showed real
    o57.5/o55.5 NCAAF lines on 0-0-record Week 1 games). It now falls back
    to a rating-based estimate via _preseason_expected_total() instead of
    nothing, using power_rating() (the same curated-class + self-training-
    Elo blend predict() itself already reads), while leaving in-season
    behavior (real gf/ga rates) byte-for-byte unchanged."""

    def setUp(self):
        self.old_key, self.old_comp = fetch_data.COMP_KEY, fetch_data.COMP
        fetch_data.COMP_KEY = "NCAAF"
        fetch_data.COMP = dict(fetch_data.COMPETITIONS["NCAAF"])

    def tearDown(self):
        fetch_data.COMP_KEY, fetch_data.COMP = self.old_key, self.old_comp

    def test_preseason_produces_a_real_estimate_instead_of_none(self):
        home = {"name": "Florida State", "pld": 0}
        away = {"name": "New Mexico State", "pld": 0}
        totals = fetch_data.predict_totals(home, away, {})
        self.assertIsNotNone(totals)
        self.assertEqual(totals["basis"], "preseason_rating")
        self.assertGreater(totals["expected"], 0)

    def test_in_season_behavior_and_shape_is_unchanged(self):
        home = {"name": "Team A", "pld": 10, "gf": 350, "ga": 200}
        away = {"name": "Team B", "pld": 10, "gf": 280, "ga": 260}
        totals = fetch_data.predict_totals(home, away, {})
        self.assertEqual(totals["basis"], "season_rate")
        # (h_gf+a_ga)/2 + (a_gf+h_ga)/2 with per-game rates 35/20 and 28/26
        self.assertAlmostEqual(totals["expected"], (35 + 26) / 2 + (28 + 20) / 2, places=2)

    def test_preseason_estimate_still_compares_against_a_real_market_line(self):
        home = {"name": "Florida State", "pld": 0}
        away = {"name": "New Mexico State", "pld": 0}
        totals = fetch_data.predict_totals(home, away, {"totals": {"line": 57.5, "over_pct": 52, "under_pct": 48}})
        self.assertEqual(totals["line"], 57.5)
        self.assertIn(totals["pick"], ("over", "under"))
        self.assertEqual(totals["over_pct"] + totals["under_pct"], 100)

    def test_completely_unrated_teams_still_get_the_league_baseline(self):
        home = {"name": "Totally Unknown School A", "pld": 0}
        away = {"name": "Totally Unknown School B", "pld": 0}
        totals = fetch_data.predict_totals(home, away, {})
        self.assertAlmostEqual(totals["expected"], fetch_data.LEAGUE_AVG_TOTAL["NCAAF"], delta=0.5)


class EstimateTitleOddsTests(unittest.TestCase):
    """New fallback requested alongside the blowout-confidence fix: the
    Title race panel only ever populated from real championship-odds
    market data (fetch_outrights()/apply_market_strength()), which is
    empty for every competition right now (The Odds API's outrights quota
    is exhausted). estimate_title_odds() ranks a competition's own
    schedule by power_rating() and produces a title_odds-shaped list
    (team/code/pct) so the panel still shows something preseason, clearly
    marked as a model estimate rather than a real market read."""

    def setUp(self):
        self.old_key, self.old_comp = fetch_data.COMP_KEY, fetch_data.COMP
        self.old_ratings_file, self.old_ratings = fetch_data.RATINGS_FILE, fetch_data._RATINGS
        fetch_data.COMP_KEY = "NCAAF"
        fetch_data.COMP = dict(fetch_data.COMPETITIONS["NCAAF"])
        fd, self.tmp_path = tempfile.mkstemp(suffix=".json")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"Georgia": {"fifa_rank": 45, "squad_value_m": 1500, "star_value_m": 200},
                       "New Mexico State": {"fifa_rank": 45, "squad_value_m": 300, "star_value_m": 40}}, f)
        fetch_data.RATINGS_FILE = self.tmp_path
        fetch_data._RATINGS = None

    def tearDown(self):
        fetch_data.COMP_KEY, fetch_data.COMP = self.old_key, self.old_comp
        fetch_data.RATINGS_FILE, fetch_data._RATINGS = self.old_ratings_file, self.old_ratings
        os.unlink(self.tmp_path)

    def test_produces_the_same_shape_the_frontend_title_race_panel_expects(self):
        matches = [{"home": {"name": "Georgia"}, "away": {"name": "New Mexico State"}}]
        rows = fetch_data.estimate_title_odds(matches, {"georgia": "GA", "new mexico state": "NMSU"})
        self.assertEqual(len(rows), 2)
        for row in rows:
            self.assertIn("team", row); self.assertIn("code", row); self.assertIn("pct", row)

    def test_every_row_is_clearly_marked_as_a_model_estimate(self):
        matches = [{"home": {"name": "Georgia"}, "away": {"name": "New Mexico State"}}]
        rows = fetch_data.estimate_title_odds(matches, {})
        self.assertTrue(all(row.get("is_estimate") is True for row in rows))
        self.assertTrue(all(row.get("source") == "model" for row in rows))

    def test_the_better_rated_team_ranks_first_and_higher(self):
        matches = [{"home": {"name": "Georgia"}, "away": {"name": "New Mexico State"}}]
        rows = fetch_data.estimate_title_odds(matches, {})
        by_team = {r["team"]: r["pct"] for r in rows}
        self.assertEqual(rows[0]["team"], "Georgia")
        self.assertGreater(by_team["Georgia"], by_team["New Mexico State"])

    def test_no_matches_returns_an_empty_list_not_an_error(self):
        self.assertEqual(fetch_data.estimate_title_odds([], {}), [])


def _finished(mid, home, away, hs, aps, kickoff, winner):
    return {"id": mid, "status": "FINISHED", "kickoff": kickoff,
            "home": {"name": home}, "away": {"name": away},
            "score": {"home": hs, "away": aps, "winner": winner}}


class EloSportScopeTests(unittest.TestCase):
    """A user-reported symptom on 2026-07-25 ('college football ratings' look
    off) traced to a real bug in the self-training Elo store: ELO_FILE is one
    shared JSON file across every competition, keyed only by norm(team name).
    That's fine for club soccer (the same club really should carry its Elo
    between e.g. a domestic league and UCL) but breaks for US college sports,
    where the identical bare school name ("Kansas", "Duke", "Kent State", ...)
    fields both a football team and a basketball team. Confirmed live against
    the real ratings_elo.json (2026-07-25): NCAAM builds had already written
    a pure-basketball rating under e.g. "kent state"; the next NCAAF build
    would have blended football results straight into that same bucket,
    corrupting both sports' signal. Keys are now scoped by COMP["sport"], not
    COMP_KEY, so the intentional soccer cross-competition sharing keeps
    working while football vs basketball no longer collide."""

    def setUp(self):
        self.old_key, self.old_comp = fetch_data.COMP_KEY, fetch_data.COMP
        self.old_elo_file, self.old_elo = fetch_data.ELO_FILE, fetch_data._ELO
        fd, self.tmp_path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        os.unlink(self.tmp_path)  # start from a clean, nonexistent file
        fetch_data.ELO_FILE = self.tmp_path
        fetch_data._ELO = None

    def tearDown(self):
        fetch_data.COMP_KEY, fetch_data.COMP = self.old_key, self.old_comp
        fetch_data.ELO_FILE, fetch_data._ELO = self.old_elo_file, self.old_elo
        if os.path.exists(self.tmp_path):
            os.unlink(self.tmp_path)

    def test_same_school_name_does_not_share_elo_across_football_and_basketball(self):
        # "Kent State" wins repeatedly as a basketball team...
        fetch_data.COMP_KEY = "NCAAM"
        fetch_data.COMP = dict(fetch_data.COMPETITIONS["NCAAM"])
        wins = [_finished(f"cbbd-{i}", "Kent State", "Some Team", 80, 60,
                           f"2026-01-{i+1:02d}T00:00:00Z", "h") for i in range(20)]
        fetch_data.update_elo(wins)
        bball_pts, bball_conf = fetch_data.elo_strength("Kent State")
        self.assertGreater(bball_pts, 0)
        self.assertEqual(bball_conf, 1.0)

        # ...but loses repeatedly as a football team.
        fetch_data.COMP_KEY = "NCAAF"
        fetch_data.COMP = dict(fetch_data.COMPETITIONS["NCAAF"])
        losses = [_finished(f"cfbd-{i}", "Some Team", "Kent State", 40, 10,
                             f"2025-09-{i+1:02d}T00:00:00Z", "h") for i in range(20)]
        fetch_data.update_elo(losses)
        fball_pts, fball_conf = fetch_data.elo_strength("Kent State")
        self.assertLess(fball_pts, 0)  # its own (bad) football record, not basketball's
        self.assertEqual(fball_conf, 1.0)

        # Switching back to NCAAM must show the exact same basketball rating
        # as before the football updates -- no cross-sport bleed either way.
        fetch_data.COMP_KEY = "NCAAM"
        fetch_data.COMP = dict(fetch_data.COMPETITIONS["NCAAM"])
        bball_pts_after, bball_conf_after = fetch_data.elo_strength("Kent State")
        self.assertEqual(bball_pts_after, bball_pts)
        self.assertEqual(bball_conf_after, bball_conf)

    def test_h2h_pair_key_is_also_sport_scoped(self):
        # Same class of bug for the H2H store: two schools that happen to
        # meet in more than one sport (or under the same bare name) shouldn't
        # blend those meetings into one pairwise history.
        fetch_data.COMP_KEY = "NCAAM"
        fetch_data.COMP = dict(fetch_data.COMPETITIONS["NCAAM"])
        key_ncaam = fetch_data._pair_key("kansas", "duke")
        fetch_data.COMP_KEY = "NCAAF"
        fetch_data.COMP = dict(fetch_data.COMPETITIONS["NCAAF"])
        key_ncaaf = fetch_data._pair_key("kansas", "duke")
        self.assertNotEqual(key_ncaam, key_ncaaf)


class LegacyStoreMigrationTests(unittest.TestCase):
    """The sport-scoping fix above (EloSportScopeTests) only changed how NEW
    keys are derived -- it did nothing about the store files already sitting
    on disk in the OLD unscoped format. Confirmed live 2026-07-26 against the
    real ratings_elo.json/ratings_h2h.json: both files are entirely
    unscoped (867 teams / 5644 pairs, zero keys with a sport prefix), which
    means elo_strength()/h2h_strength() have been silently returning
    (0.0, 0.0) for every team/pair in every sport since the scoping fix
    landed -- not a cross-sport bug anymore, but a total-data-loss bug.
    _migrate_legacy_elo_store()/_migrate_legacy_h2h_store() (triggered from
    _load_elo()/_load_h2h() via a _version field) fix this by archiving the
    old file and starting fresh sport-scoped tracking -- re-keying the old
    data was considered and rejected (see that function's own docstring):
    the stored (r, n) / meeting-log records don't retain which
    competition/sport wrote them, so there's no reliable way to tell a
    genuinely single-sport-safe entry apart from a contaminated
    football/basketball-shared one."""

    def setUp(self):
        self.old_elo_file, self.old_elo = fetch_data.ELO_FILE, fetch_data._ELO
        self.old_h2h_file, self.old_h2h = fetch_data.H2H_FILE, fetch_data._H2H
        fd1, self.elo_path = tempfile.mkstemp(suffix=".json")
        os.close(fd1)
        fd2, self.h2h_path = tempfile.mkstemp(suffix=".json")
        os.close(fd2)
        self.elo_legacy_path = self.elo_path.rsplit(".json", 1)[0] + ".legacy.json"
        self.h2h_legacy_path = self.h2h_path.rsplit(".json", 1)[0] + ".legacy.json"

    def tearDown(self):
        fetch_data.ELO_FILE, fetch_data._ELO = self.old_elo_file, self.old_elo
        fetch_data.H2H_FILE, fetch_data._H2H = self.old_h2h_file, self.old_h2h
        for p in (self.elo_path, self.elo_legacy_path, self.h2h_path, self.h2h_legacy_path):
            if os.path.exists(p):
                os.unlink(p)

    def test_legacy_unscoped_elo_file_is_archived_and_reset_not_silently_kept(self):
        legacy = {"teams": {"kent state": {"r": 1602.0, "n": 34},
                             "mexico": {"r": 1550.0, "n": 10}},
                  "seen": {"NCAAM:abc123": True}}
        with open(self.elo_path, "w", encoding="utf-8") as f:
            json.dump(legacy, f)
        fetch_data.ELO_FILE = self.elo_path
        fetch_data._ELO = None

        store = fetch_data._load_elo()
        # Reset, not re-keyed -- migration must never invent a sport for an
        # old bare-name entry it can't actually verify.
        self.assertEqual(store["teams"], {})
        self.assertEqual(store["seen"], {})
        self.assertEqual(store["_version"], fetch_data.ELO_STORE_VERSION)
        # ...but nothing is thrown away -- the old data is archived, not lost.
        self.assertTrue(os.path.exists(self.elo_legacy_path))
        with open(self.elo_legacy_path, encoding="utf-8") as f:
            archived = json.load(f)
        self.assertEqual(archived["teams"], legacy["teams"])

    def test_migration_is_idempotent_second_load_does_not_re_archive(self):
        legacy = {"teams": {"kent state": {"r": 1602.0, "n": 34}}, "seen": {}}
        with open(self.elo_path, "w", encoding="utf-8") as f:
            json.dump(legacy, f)
        fetch_data.ELO_FILE = self.elo_path
        fetch_data._ELO = None
        fetch_data._load_elo()
        archived_mtime = os.path.getmtime(self.elo_legacy_path)

        # Force a fresh load from disk (simulates the next process/run) --
        # the file on disk is now the migrated v2 format, so this must NOT
        # trigger another archive/reset cycle.
        fetch_data._ELO = None
        store2 = fetch_data._load_elo()
        self.assertEqual(store2.get("_version"), fetch_data.ELO_STORE_VERSION)
        self.assertEqual(os.path.getmtime(self.elo_legacy_path), archived_mtime)

    def test_already_scoped_v2_elo_file_is_left_alone(self):
        current = {"_version": fetch_data.ELO_STORE_VERSION,
                   "teams": {"football:kent state": {"r": 1520.0, "n": 3}},
                   "seen": {"NCAAF:xyz": True}}
        with open(self.elo_path, "w", encoding="utf-8") as f:
            json.dump(current, f)
        fetch_data.ELO_FILE = self.elo_path
        fetch_data._ELO = None
        store = fetch_data._load_elo()
        self.assertEqual(store["teams"], current["teams"])
        self.assertFalse(os.path.exists(self.elo_legacy_path))

    def test_legacy_unscoped_h2h_file_is_archived_and_reset(self):
        legacy = {"pairs": {"kansas|duke": [{"date": "2025-01-01", "home": "kansas", "winner": "h"}]},
                  "seen": {"NCAAM:def456": True}}
        with open(self.h2h_path, "w", encoding="utf-8") as f:
            json.dump(legacy, f)
        fetch_data.H2H_FILE = self.h2h_path
        fetch_data._H2H = None

        store = fetch_data._load_h2h()
        self.assertEqual(store["pairs"], {})
        self.assertEqual(store["seen"], {})
        self.assertEqual(store["_version"], fetch_data.H2H_STORE_VERSION)
        self.assertTrue(os.path.exists(self.h2h_legacy_path))
        with open(self.h2h_legacy_path, encoding="utf-8") as f:
            archived = json.load(f)
        self.assertEqual(archived["pairs"], legacy["pairs"])

    def test_migrated_elo_store_rebuilds_sport_scoped_signal_from_scratch(self):
        # End-to-end: a legacy file with a blended "kent state" entry gets
        # reset, and a fresh sport-scoped result correctly starts the team
        # at neutral and builds its OWN (not the old blended) signal.
        legacy = {"teams": {"kent state": {"r": 1602.0, "n": 34}}, "seen": {}}
        with open(self.elo_path, "w", encoding="utf-8") as f:
            json.dump(legacy, f)
        fetch_data.ELO_FILE = self.elo_path
        fetch_data._ELO = None

        fetch_data.COMP_KEY = "NCAAF"
        fetch_data.COMP = dict(fetch_data.COMPETITIONS["NCAAF"])
        pts_before, conf_before = fetch_data.elo_strength("Kent State")
        self.assertEqual((pts_before, conf_before), (0.0, 0.0))  # neutral, not the old blended rating

        loss = [_finished("cfbd-1", "Some Team", "Kent State", 40, 10,
                           "2025-09-01T00:00:00Z", "h")]
        fetch_data.update_elo(loss)
        pts_after, conf_after = fetch_data.elo_strength("Kent State")
        self.assertLess(pts_after, 0)  # its own fresh result, not inherited noise
        self.assertGreater(conf_after, 0)


class NewsRelevanceTests(unittest.TestCase):
    """Regression coverage for real cross-sport pollution confirmed live on
    the site 2026-07-26: EPL/UCL's News tab was showing NFL fantasy-football
    and MLB trade-deadline articles, and NCAAM's was showing an MLB Royals/
    Tigers recap. Root cause #1: soccer competitions had no entry in
    NEWS_RELEVANCE at all, so _news_relevant() returned True unconditionally
    -- zero filtering. Root cause #2: NCAAM's own relevance term "kansas"
    (for Kansas Jayhawks) is also a whole-word match inside "Kansas City
    Royals" (MLB), a bare-city-name collision with a different sport's
    franchise in the same city."""

    def setUp(self):
        self.old_key = fetch_data.COMP_KEY

    def tearDown(self):
        fetch_data.COMP_KEY = self.old_key

    def test_ncaam_rejects_the_real_mlb_recap_that_matched_on_the_bare_city_name(self):
        fetch_data.COMP_KEY = "NCAAM"
        self.assertFalse(fetch_data._news_relevant(
            {"headline": "Kansas City Royals vs. Detroit Tigers Results, Stats, and Recap", "desc": ""}))

    def test_ncaam_still_accepts_real_kansas_basketball_coverage(self):
        fetch_data.COMP_KEY = "NCAAM"
        self.assertTrue(fetch_data._news_relevant(
            {"headline": "Kansas Jayhawks land 5-star recruit ahead of March Madness", "desc": ""}))

    def test_previous_news_drops_items_that_no_longer_pass_relevance(self):
        # Items accepted before a relevance rule existed were merged forward
        # by fetch_news() forever, since only fresh items were ever checked
        # against _news_relevant(). _load_previous_news() must re-check every
        # carried-forward item too.
        data_path = "data_ncaam.json"
        old_existed = os.path.exists(data_path)
        old_content = None
        if old_existed:
            with open(data_path, encoding="utf-8") as f:
                old_content = f.read()
        published = fetch_data.datetime.datetime.now(fetch_data.datetime.timezone.utc).isoformat()
        with open(data_path, "w", encoding="utf-8") as f:
            json.dump({"news_scope": "NCAAM", "news": [
                {"headline": "MLB rumors: Major trade candidate could miss rest of 2026", "source": "CBS Sports", "published": published},
                {"headline": "Kansas Jayhawks land 5-star recruit ahead of March Madness", "source": "CBS Sports", "published": published},
            ]}, f)
        try:
            fetch_data.COMP_KEY = "NCAAM"
            previous = fetch_data._load_previous_news()
        finally:
            if old_existed:
                with open(data_path, "w", encoding="utf-8") as f:
                    f.write(old_content)
            else:
                os.unlink(data_path)
        headlines = [item["headline"] for item in previous]
        self.assertNotIn("MLB rumors: Major trade candidate could miss rest of 2026", headlines)
        self.assertIn("Kansas Jayhawks land 5-star recruit ahead of March Madness", headlines)


class OffseasonRecordTests(unittest.TestCase):
    def test_nfl_prior_season_record_is_marked_stale_across_long_gap(self):
        standings = {"team": {"w": 12, "l": 5}}
        tables = [{"teams": [{"name": "Team", "w": 12, "l": 5}]}]
        history = [{"status": "FINISHED", "kickoff": "2026-02-08T23:00:00Z"}]
        fixtures = [{"status": "UPCOMING", "kickoff": "2026-09-10T00:20:00Z"}]
        self.assertTrue(fetch_data.mark_stale_offseason_records(
            standings, tables, history, fixtures, "NFL"))
        self.assertTrue(standings["team"]["season_stale"])
        self.assertTrue(tables[0]["teams"][0]["season_stale"])

    def test_inseason_nfl_record_remains_current(self):
        standings = {"team": {"w": 2, "l": 1}}
        history = [{"status": "FINISHED", "kickoff": "2026-09-27T20:00:00Z"}]
        fixtures = [{"status": "UPCOMING", "kickoff": "2026-10-04T20:00:00Z"}]
        self.assertFalse(fetch_data.mark_stale_offseason_records(
            standings, [], history, fixtures, "NFL"))
        self.assertNotIn("season_stale", standings["team"])

    def test_season_context_rejects_nonzero_prior_table_after_rollover(self):
        now = fetch_data.datetime.datetime(2026, 8, 14, tzinfo=fetch_data.datetime.timezone.utc)
        history = [{"status": "FINISHED", "kickoff": "2026-03-15T20:00:00Z"}]
        fixtures = [{"status": "UPCOMING", "kickoff": "2026-09-05T20:00:00Z"}]
        context = fetch_data.competition_season_context(
            history, fixtures, "NCAAF", now=now,
            standings=[{"teams": [{"name": "Old Team", "pld": 13, "w": 10}]}],
        )
        self.assertFalse(context["standings_current"])
        self.assertEqual(context["standings_basis"], "stale_or_unverified")

    def test_current_zero_game_preseason_table_is_preserved(self):
        now = fetch_data.datetime.datetime(2026, 8, 14, tzinfo=fetch_data.datetime.timezone.utc)
        context = fetch_data.competition_season_context(
            [], [{"status": "UPCOMING", "kickoff": "2026-09-05T20:00:00Z"}],
            "NCAAF", now=now,
            standings=[{"teams": [
                {"name": "Team A", "pld": 0, "w": 0, "l": 0},
                {"name": "Team B", "pld": 0, "w": 0, "l": 0},
            ]}],
        )
        self.assertTrue(context["all_zero_preseason"])
        self.assertTrue(context["standings_current"])
        standings = [{"group": "Conference", "teams": [{"name": "Team A", "pld": 0}]}]
        kept, bracket, bracketology, context = fetch_data.filter_current_season_views(
            standings, [], None, context)
        self.assertEqual(kept, standings)
        self.assertEqual(context["suppressed_views"], [])

    def test_stale_views_keep_only_explicitly_current_projection(self):
        context = {"standings_current": False, "projection_current": True}
        projected = {"group": "Way-too-early Top 25 (model projection)",
                     "projection_current": True, "teams": [{"name": "Team A"}]}
        official = {"group": "Conference", "teams": [{"name": "Old Team", "pld": 30}]}
        bracket_projection = {"rounds": [{"name": "First Round"}]}
        standings, bracket, bracketology, context = fetch_data.filter_current_season_views(
            [projected, official], bracket_projection, {"regions": {}}, context,
            bracket_projection_current=True,
        )
        self.assertEqual(standings, [projected])
        self.assertIs(bracket, bracket_projection)
        self.assertIsNone(bracketology)
        self.assertEqual(context["suppressed_views"], ["standings", "bracketology"])

    def test_ucl_knockout_playoff_round_uses_canonical_label(self):
        self.assertEqual(fetch_data.KO_STAGES["PLAYOFFS"], "Knockout phase play-offs")
        self.assertEqual(fetch_data.KO_STAGES["PLAY_OFF_ROUND"], "Knockout phase play-offs")
        self.assertIn("Knockout phase play-offs", fetch_data.KO_ORDER)
        self.assertNotIn("Knockout playoffs", fetch_data.KO_ORDER)
        self.assertEqual(fetch_data.canonical_knockout_round("Knockout playoffs"),
                         "Knockout phase play-offs")

    def test_current_world_cup_keeps_derived_position_views_current(self):
        now = fetch_data.datetime.datetime(2026, 6, 15, tzinfo=fetch_data.datetime.timezone.utc)
        context = fetch_data.competition_season_context(
            [{"status": "FINISHED", "kickoff": "2026-06-12T20:00:00Z"}],
            [{"status": "UPCOMING", "kickoff": "2026-06-20T20:00:00Z"}],
            "WC", now=now,
            standings=[{"teams": [{"name": "Team A", "pld": 1, "w": 1}]}],
        )
        _, _, _, context = fetch_data.filter_current_season_views(
            [{"group": "Group A", "teams": [{"name": "Team A", "pld": 1}]}],
            [], None, context,
        )
        self.assertTrue(context["standings_current"])
        self.assertTrue(context["derived_positions_current"])


if __name__ == "__main__":
    unittest.main()
