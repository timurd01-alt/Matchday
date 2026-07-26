import json
import os
import tempfile
import unittest
from unittest import mock

import fetch_data


def finished(mid, home, away, hs, aps):
    return {
        "id": mid, "status": "FINISHED", "kickoff": "2026-01-01T00:00:00Z",
        "home": {"name": home}, "away": {"name": away},
        "score": {"home": hs, "away": aps},
    }


class ModelInputTests(unittest.TestCase):
    def test_market_weight_uses_depth_and_disagreement(self):
        self.assertEqual(fetch_data._market_blend_weight(None), 0.0)
        deep_tight = fetch_data._market_blend_weight({"books": 8, "spread": 4})
        thin_split = fetch_data._market_blend_weight({"books": 1, "spread": 24})
        self.assertGreater(deep_tight, thin_split)
        self.assertGreaterEqual(thin_split, 0.30)
        self.assertLessEqual(deep_tight, 0.60)

    def setUp(self):
        self.old_key = fetch_data.COMP_KEY
        self.old_comp = fetch_data.COMP
        fetch_data.COMP_KEY = "NCAAM"
        fetch_data.COMP = dict(fetch_data.COMPETITIONS["NCAAM"])

    def tearDown(self):
        fetch_data.COMP_KEY = self.old_key
        fetch_data.COMP = self.old_comp

    def use_world_cup(self):
        fetch_data.COMP_KEY = "WC"
        fetch_data.COMP = dict(fetch_data.COMPETITIONS["WC"])

    def test_cached_results_are_backfilled_with_winners(self):
        matches = [finished("one", "Alpha", "Beta", 80, 72)]
        fetch_data.normalize_match_results(matches)
        self.assertEqual(matches[0]["score"]["winner"], "h")

    def test_knockout_extra_time_uses_winner_but_market_uses_regulation(self):
        self.use_world_cup()
        match = {
            "stage": "Quarter Finals",
            "score": {
                "home": 2, "away": 1, "winner": "h",
                "reg": {"home": 1, "away": 1},
            },
        }
        original_score = json.loads(json.dumps(match["score"]))
        self.assertEqual(fetch_data._scorecard_results(match), ("h", "d"))
        self.assertEqual(match["score"], original_score)

    def test_knockout_penalties_use_shootout_winner_without_changing_score(self):
        self.use_world_cup()
        match = {
            "stage": "Last 16",
            "score": {
                "home": 1, "away": 1, "winner": "h",
                "reg": {"home": 1, "away": 1},
                "pens": {"home": 4, "away": 3},
            },
        }
        original_score = json.loads(json.dumps(match["score"]))
        self.assertEqual(fetch_data._scorecard_results(match), ("h", "d"))
        self.assertEqual(match["score"], original_score)

    def test_group_stage_draw_uses_same_result_for_model_and_market(self):
        match = {
            "stage": "Group Stage",
            "score": {
                "home": 1, "away": 1, "winner": "d",
                "reg": {"home": 1, "away": 1},
            },
        }
        self.assertEqual(fetch_data._scorecard_results(match), ("d", "d"))

    def test_model_and_market_hits_use_their_separate_knockout_results(self):
        self.use_world_cup()
        rec = {
            "pick": "h", "market_pick": "d", "value_side": "d",
            "probs": {"h": 55, "d": 30, "a": 15}, "score": "1-1 (4-3 pens)",
        }
        fetch_data._apply_scorecard_grade(rec, "h", "d")
        self.assertEqual(rec["result"], "h")
        self.assertEqual(rec["market_result"], "d")
        self.assertTrue(rec["model_hit"])
        self.assertTrue(rec["market_hit"])
        self.assertTrue(rec["value_hit"])
        self.assertEqual(rec["score"], "1-1 (4-3 pens)")

    def test_missing_soccer_regulation_score_does_not_guess_market_settlement(self):
        self.use_world_cup()
        fetch_data.COMP["has_draws"] = True
        match = {
            "stage": "Final",
            "score": {"home": 2, "away": 1, "winner": "h"},
        }
        self.assertEqual(fetch_data._scorecard_results(match), ("h", None))
        rec = {"pick": "h", "market_pick": "d", "market_hit": True}
        fetch_data._apply_scorecard_grade(rec, "h", None)
        self.assertTrue(rec["model_hit"])
        self.assertIsNone(rec["market_hit"])
        self.assertIsNone(rec["market_result"])

    def test_normalize_preserves_knockout_metadata_on_real_pipeline_shape(self):
        self.use_world_cup()
        match = {
            "stage": "Last 16", "status": "FINISHED",
            "score": {"home": 1, "away": 1, "winner": "h",
                      "reg": {"home": 1, "away": 1},
                      "pens": {"home": 4, "away": 3}},
        }
        fetch_data.normalize_match_results([match])
        self.assertEqual(match["score"]["reg"], {"home": 1, "away": 1})
        self.assertEqual(match["score"]["pens"], {"home": 4, "away": 3})
        self.assertEqual(match["score"]["winner"], "h")
        self.assertEqual(fetch_data._scorecard_results(match), ("h", "d"))

    def test_football_data_extra_time_is_added_to_regulation(self):
        raw = {"score": {"regularTime": {"home": 1, "away": 1},
                         "extraTime": {"home": 2, "away": 0},
                         "fullTime": {"home": 3, "away": 1},
                         "penalties": {}}}
        self.assertEqual(fetch_data._resolve_score(raw), (3, 1, "h", (None, None), (1, 1)))

    def test_lock_decision_requires_parseable_upcoming_two_hour_window(self):
        now = fetch_data.datetime.datetime(2026, 7, 24, 12, tzinfo=fetch_data.datetime.timezone.utc)
        base = {"status": "UPCOMING", "kickoff": "2026-07-24T14:00:00Z"}
        self.assertEqual(fetch_data._lock_decision(base, now)["state"], "eligible")
        self.assertEqual(fetch_data._lock_decision({**base, "kickoff": "2026-07-24T12:00:00Z"}, now)["state"], "eligible")
        self.assertEqual(fetch_data._lock_decision({**base, "kickoff": "2026-07-24T14:00:01Z"}, now)["state"], "wait")
        self.assertEqual(fetch_data._lock_decision({**base, "kickoff": "bad"}, now)["state"], "wait")
        self.assertEqual(fetch_data._lock_decision({**base, "kickoff": "2026-07-24T11:59:59Z"}, now)["state"], "quarantine")
        for status in ("LIVE", "FINISHED"):
            self.assertEqual(fetch_data._lock_decision({**base, "status": status}, now)["state"], "quarantine")

    def test_legacy_record_is_moved_and_never_official(self):
        picks = {"fixture-1": {"pick": "h", "result": "h", "home": "A", "away": "B"}}
        self.assertTrue(fetch_data._quarantine_legacy_records(picks))
        self.assertNotIn("fixture-1", picks)
        self.assertIn("legacy:fixture-1", picks)
        self.assertFalse(fetch_data._record_is_official(picks["legacy:fixture-1"]))
        self.assertEqual(picks["legacy:fixture-1"]["quarantine_reason"], "legacy_missing_lock_provenance")

    def test_locked_snapshot_replaces_entire_recomputed_prediction(self):
        self.use_world_cup()
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

    def test_knockout_prediction_and_metrics_are_two_way(self):
        self.use_world_cup()
        home = {"name": "Alpha", "pts": 6, "gd": 2, "form": "W W"}
        away = {"name": "Beta", "pts": 3, "gd": 0, "form": "W L"}
        prediction = fetch_data.predict(home, away, {}, {"stage": "Final", "weather": {}, "injuries": {}})
        self.assertIn(prediction["pick"], ("h", "a"))
        self.assertEqual(prediction["adjusted"]["d"], 0)
        self.assertEqual(sum(prediction["advancement"].values()), 100)
        self.assertEqual(prediction["confidence"], prediction["advancement"][prediction["pick"]])
        rec = {"stage": "Final", "outcome_basis": "ultimate_winner", "pick": prediction["pick"],
               "advancement_probs": prediction["advancement"], "market_pick": "d"}
        fetch_data._apply_scorecard_grade(rec, prediction["pick"], "d")
        self.assertIsNotNone(rec["brier_advancement"])
        self.assertIsNone(rec["brier3"])
        self.assertTrue(rec["market_hit"])

    def test_first_seen_finished_fixture_is_not_added_to_ledger(self):
        self.use_world_cup()
        match = {"id": "late", "stage": "Final", "status": "FINISHED",
                 "kickoff": "2026-07-19T19:00:00Z", "home": {"name": "A"},
                 "away": {"name": "B"}, "score": {"home": 1, "away": 0, "winner": "h",
                 "reg": {"home": 0, "away": 0}}, "markets": {},
                 "prediction": {"pick": "h", "pick_name": "A", "confidence": 60}}
        saved = []
        with mock.patch.object(fetch_data, "_load_picks", return_value={}), \
             mock.patch.object(fetch_data, "_save_picks", side_effect=lambda value: saved.append(value)), \
             mock.patch.object(fetch_data, "_load_wc_result_migration", return_value={}):
            scorecard = fetch_data.update_scorecard([match])
        self.assertEqual(scorecard["graded"], 0)
        self.assertEqual(scorecard["quarantined"]["total"], 0)
        self.assertFalse(saved)

    def test_wc_migration_verifies_results_but_not_lock_provenance(self):
        self.use_world_cup()
        picks = {"legacy:537390": {"fixture_id": "537390", "stage": "Final",
                                    "home": "Spain", "away": "Argentina",
                                    "pick": "h", "market_pick": "h", "market_hit": True,
                                    "integrity_eligible": False,
                                    "integrity_status": "quarantined"}}
        self.assertTrue(fetch_data._apply_wc_result_migration(picks))
        rec = picks["legacy:537390"]
        self.assertEqual(rec["score"], "1-0")
        self.assertEqual(rec["model_result"], "h")
        self.assertEqual(rec["market_result"], "d")
        self.assertFalse(rec["market_hit"])
        self.assertFalse(fetch_data._record_is_official(rec))

    def test_legacy_record_is_reported_separately_from_official_metrics(self):
        self.use_world_cup()
        picks = {"old": {"fixture_id": "old", "stage": "Final", "home": "A", "away": "B",
                          "pick": "h", "result": "h", "model_hit": True}}
        with mock.patch.object(fetch_data, "_load_picks", return_value=picks), \
             mock.patch.object(fetch_data, "_save_picks"), \
             mock.patch.object(fetch_data, "_load_wc_result_migration", return_value={}):
            scorecard = fetch_data.update_scorecard([])
        self.assertEqual(scorecard["graded"], 0)
        self.assertEqual(scorecard["model_hits"], 0)
        self.assertEqual(scorecard["legacy"]["graded"], 1)
        self.assertEqual(scorecard["legacy"]["model_hits"], 1)
        self.assertIn("Legacy/unverified", scorecard["picks"][0]["stage"])

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


class RatingsLookupTests(unittest.TestCase):
    """Regression coverage for the club-suffix mismatch found live: ratings
    files hand-written with short names ("Arsenal") never matched live
    fixture data using official names ("Arsenal FC"), silently zeroing the
    class factor for most club-soccer and all NCAAF/NCAAM matchups."""

    def setUp(self):
        self.old_key, self.old_comp = fetch_data.COMP_KEY, fetch_data.COMP
        self.old_ratings_file, self.old_ratings = fetch_data.RATINGS_FILE, fetch_data._RATINGS
        fetch_data.COMP_KEY = "UCL"
        fetch_data.COMP = dict(fetch_data.COMPETITIONS["UCL"])
        fd, self.tmp_path = tempfile.mkstemp(suffix=".json")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"Arsenal": {"fifa_rank": 5, "squad_value_m": 900, "star_value_m": 90},
                       "Real Madrid": {"fifa_rank": 1, "squad_value_m": 1200, "star_value_m": 150}}, f)
        fetch_data.RATINGS_FILE = self.tmp_path
        fetch_data._RATINGS = None

    def tearDown(self):
        fetch_data.COMP_KEY, fetch_data.COMP = self.old_key, self.old_comp
        fetch_data.RATINGS_FILE, fetch_data._RATINGS = self.old_ratings_file, self.old_ratings
        os.unlink(self.tmp_path)

    def test_official_suffixed_name_matches_a_short_ratings_entry(self):
        self.assertIsNotNone(fetch_data._ratings_lookup("Arsenal FC"))
        self.assertIsNotNone(fetch_data._ratings_lookup("Real Madrid CF"))

    def test_prefixed_suffix_also_matches(self):
        self.assertIsNotNone(fetch_data._ratings_lookup("FC Arsenal"))

    def test_a_team_missing_from_the_file_entirely_still_reports_unknown(self):
        self.assertIsNone(fetch_data._ratings_lookup("Some Club Not In The File FC"))

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


class TeamOfTournamentBackfillTests(unittest.TestCase):
    """Regression coverage for a bug that kept recurring: a prior fix tried
    to make the DEF/GK backfill 'stay dormant' without a real lineup
    provider, but only by relying on the player DB happening to be empty --
    stale entries from when ESPN lineups used to flow kept silently feeding
    it anyway. LINEUP_BACKFILL_ENABLED makes that structurally impossible
    regardless of what the DB file contains: real backfill only happens
    while it's True (now that fetch_api_football_box_scores() is a real,
    currently-fetching lineup source), and flipping it off must still gate
    off backfill even with a populated DB file, exactly like before."""

    def setUp(self):
        self.old_key, self.old_comp = fetch_data.COMP_KEY, fetch_data.COMP
        fetch_data.COMP_KEY = "WC"
        fetch_data.COMP = dict(fetch_data.COMPETITIONS["WC"])
        self.old_player_db_file = fetch_data.PLAYER_DB_FILE
        fd_num, self.tmp_path = tempfile.mkstemp(suffix=".json")
        with os.fdopen(fd_num, "w", encoding="utf-8") as f:
            json.dump({"_matches": ["m1"], "players": {
                "keeper one|team a": {"name": "Keeper One", "team": "Team A", "role": "GK",
                                       "apps": 5, "starts": 5, "clean_sheets": 4},
            }}, f)
        fetch_data.PLAYER_DB_FILE = self.tmp_path
        self.scorers = [{"name": "Striker", "team": "Team B", "goals": 5, "assists": 1,
                         "played": 3, "position": "Forward"}]

    def tearDown(self):
        fetch_data.COMP_KEY, fetch_data.COMP = self.old_key, self.old_comp
        fetch_data.PLAYER_DB_FILE = self.old_player_db_file
        os.unlink(self.tmp_path)

    def test_real_player_db_entries_backfill_while_enabled(self):
        with mock.patch.object(fetch_data, "LINEUP_BACKFILL_ENABLED", True):
            result = fetch_data.build_team_of_tournament([], self.scorers, [])
        self.assertIsNotNone(result)
        self.assertIn("Keeper One", [p["name"] for p in result["xi"]])
        self.assertIn("accumulated lineups", result["note"])

    def test_same_player_db_entries_never_backfill_while_disabled(self):
        with mock.patch.object(fetch_data, "LINEUP_BACKFILL_ENABLED", False):
            result = fetch_data.build_team_of_tournament([], self.scorers, [])
        self.assertIsNotNone(result)
        self.assertNotIn("Keeper One", [p["name"] for p in result["xi"]])
        self.assertIn("don't fake it", result["note"])


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


class ApiFootballInjuryPredictIntegrationTests(unittest.TestCase):
    """predict()'s injury nudge (the `w = {...}.get(COMP_KEY, 1.5)` block)
    only ever ran against empty data for soccer before this build -- every
    soccer adapter path left m['injuries'] at {"home": [], "away": []}.
    These confirm real API-FOOTBALL-shaped data (via _parse_af_injuries)
    actually moves predict(), and that only confirmed "Out" absences count,
    not "Questionable" doubts, per _out_count()'s documented intent."""

    def setUp(self):
        self.old_key, self.old_comp = fetch_data.COMP_KEY, fetch_data.COMP
        fetch_data.COMP_KEY = "WC"
        fetch_data.COMP = dict(fetch_data.COMPETITIONS["WC"])

    def tearDown(self):
        fetch_data.COMP_KEY, fetch_data.COMP = self.old_key, self.old_comp

    def test_only_confirmed_out_status_feeds_the_injury_nudge(self):
        home = {"name": "Alpha", "pts": 6, "gd": 2, "form": "W W"}
        away = {"name": "Beta", "pts": 6, "gd": 2, "form": "W W"}
        m_questionable_only = {"stage": "Final", "weather": {},
                                "injuries": {"home": ["Star Player (Questionable - Illness)"], "away": []}}
        m_confirmed_out = {"stage": "Final", "weather": {},
                            "injuries": {"home": ["Star Player (Out - Injury)"], "away": []}}
        pred_q = fetch_data.predict(dict(home), dict(away), {}, m_questionable_only)
        pred_out = fetch_data.predict(dict(home), dict(away), {}, m_confirmed_out)
        self.assertNotIn("injuries", pred_q["why"])
        self.assertIn("injuries", pred_out["why"])
        # home's confirmed absence should tilt probability toward the away side
        self.assertGreater(pred_out["adjusted"]["a"], pred_q["adjusted"]["a"])

    def test_real_shaped_af_injuries_payload_feeds_predict_end_to_end(self):
        payload = {"response": [
            {"player": {"id": 1, "name": "Home Starter", "type": "Missing Fixture", "reason": "Injury"},
             "team": {"name": "Alpha"}},
            {"player": {"id": 1, "name": "Home Starter", "type": "Missing Fixture", "reason": "Injury"},
             "team": {"name": "Alpha"}},  # duplicate row, same as the live provider quirk
        ]}
        m = {"stage": "Final", "weather": {}, "home": {"name": "Alpha"}, "away": {"name": "Beta"}}
        m["injuries"] = fetch_data._parse_af_injuries(payload, m, "1")
        home = {"name": "Alpha", "pts": 6, "gd": 2, "form": "W W"}
        away = {"name": "Beta", "pts": 6, "gd": 2, "form": "W W"}
        pred = fetch_data.predict(home, away, {}, m)
        self.assertIn("injuries", pred["why"])
        self.assertGreater(pred["adjusted"]["a"], pred["adjusted"]["h"])


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


class ApiFootballInjuryFetchGuardTests(unittest.TestCase):
    """Quota-safety guards on fetch_api_football_injuries(): it must never
    spend a request for a non-soccer competition or without a configured
    key, since it shares API-FOOTBALL's 100/day free-plan budget with box
    stats and lineups."""

    def setUp(self):
        self.old_key, self.old_comp = fetch_data.COMP_KEY, fetch_data.COMP
        self.old_api_key = fetch_data.API_FOOTBALL_KEY

    def tearDown(self):
        fetch_data.COMP_KEY, fetch_data.COMP = self.old_key, self.old_comp
        fetch_data.API_FOOTBALL_KEY = self.old_api_key

    def test_non_soccer_competition_never_calls_the_api(self):
        fetch_data.COMP_KEY = "NBA"
        fetch_data.COMP = dict(fetch_data.COMPETITIONS.get("NBA", {"sport": "basketball"}))
        with mock.patch.object(fetch_data, "_api_football_get") as get_mock:
            fetch_data.fetch_api_football_injuries([{"status": "LIVE"}])
        get_mock.assert_not_called()

    def test_missing_key_logs_diag_and_never_calls_the_api(self):
        fetch_data.COMP_KEY = "WC"
        fetch_data.COMP = dict(fetch_data.COMPETITIONS["WC"])
        fetch_data.API_FOOTBALL_KEY = ""
        with mock.patch.object(fetch_data, "_api_football_get") as get_mock:
            fetch_data.fetch_api_football_injuries([{"status": "LIVE"}])
        get_mock.assert_not_called()
        self.assertTrue(any("missing API_FOOTBALL_KEY" in d for d in fetch_data.DIAG))

    def test_finished_matches_are_never_targeted(self):
        # Injuries are forward-looking team news; a FINISHED match has no
        # predictive value left, so no request should be spent on one, even
        # with a key configured.
        fetch_data.COMP_KEY = "WC"
        fetch_data.COMP = dict(fetch_data.COMPETITIONS["WC"])
        fetch_data.API_FOOTBALL_KEY = "test-key"
        matches = [{"status": "FINISHED", "kickoff": "2020-01-01T00:00:00Z",
                    "home": {"name": "Alpha"}, "away": {"name": "Beta"}}]
        with mock.patch.object(fetch_data, "_api_football_get") as get_mock:
            fetch_data.fetch_api_football_injuries(matches)
        get_mock.assert_not_called()


class DomesticLeagueKnockoutFalsePositiveTests(unittest.TestCase):
    """A user-reported symptom on 2026-07-25: EPL/LaLiga/SerieA/Bundesliga/
    Ligue1 predictions were almost always flagged "upset watch", even for
    lopsided matchups. Root cause: three separate spots (_low_goal_probability,
    _upset_adjustment's variance term, and predict()'s knockout damp) all
    checked `not stage.startswith("group")` to detect one-off knockout
    fixtures -- correct for WC/UCL's group-vs-knockout format, but a
    domestic league's stage ("Regular Season") never starts with "group"
    either, so every single league match was silently treated as a risky
    knockout fixture. All three now use the real knockout-stage allowlist
    (_is_knockout_stage) instead."""

    def setUp(self):
        self.old_key, self.old_comp = fetch_data.COMP_KEY, fetch_data.COMP
        fetch_data.COMP_KEY = "EPL"
        fetch_data.COMP = dict(fetch_data.COMPETITIONS["EPL"])

    def tearDown(self):
        fetch_data.COMP_KEY, fetch_data.COMP = self.old_key, self.old_comp

    def test_regular_season_stage_is_not_treated_as_knockout(self):
        low_goal = fetch_data._low_goal_probability({}, 26, {"stage": "Regular Season"})
        # 0.42 + 0.26*0.42 with no knockout bonus
        self.assertAlmostEqual(low_goal, 0.5292, places=3)

    def test_real_knockout_stage_still_gets_the_bonus(self):
        low_goal = fetch_data._low_goal_probability({}, 26, {"stage": "Quarterfinal"})
        self.assertAlmostEqual(low_goal, 0.5892, places=3)

    def test_league_match_prediction_is_not_damped_toward_a_coin_flip(self):
        home = {"name": "Strong FC", "pts": 30, "gd": 20, "form": "W W W W W"}
        away = {"name": "Weak FC", "pts": 5, "gd": -20, "form": "L L L L L"}
        league = fetch_data.predict(dict(home), dict(away), {}, {"stage": "Regular Season", "weather": {}})
        cup = fetch_data.predict(dict(home), dict(away), {}, {"stage": "Quarterfinal", "weather": {}})
        self.assertEqual(league["damp_pct"], 0)
        self.assertGreater(cup["damp_pct"], 0)
        self.assertGreaterEqual(league["adjusted"]["h"], cup["adjusted"]["h"])


class DrawProbabilityRespondsToMismatchTests(unittest.TestCase):
    """Draw probability used to be a flat 0.26 for every soccer match
    regardless of the underlying gap between the two sides -- a real blowout
    draws far less often than an even match, and the flat value also fed a
    constant, elevated floor into the upset-variance formula (see
    DomesticLeagueKnockoutFalsePositiveTests). It now tapers down as the
    model's own pre-draw split gets more lopsided."""

    def setUp(self):
        self.old_key, self.old_comp = fetch_data.COMP_KEY, fetch_data.COMP
        fetch_data.COMP_KEY = "EPL"
        fetch_data.COMP = dict(fetch_data.COMPETITIONS["EPL"])

    def tearDown(self):
        fetch_data.COMP_KEY, fetch_data.COMP = self.old_key, self.old_comp

    def test_lopsided_matchup_gets_a_lower_draw_probability_than_an_even_one(self):
        even_home = {"name": "A", "pts": 20, "gd": 0, "form": "W L W L"}
        even_away = {"name": "B", "pts": 20, "gd": 0, "form": "W L W L"}
        lopsided_home = {"name": "C", "pts": 40, "gd": 30, "form": "W W W W W"}
        lopsided_away = {"name": "D", "pts": 5, "gd": -30, "form": "L L L L L"}
        even = fetch_data.predict(even_home, even_away, {}, {"stage": "Regular Season", "weather": {}})
        lopsided = fetch_data.predict(lopsided_home, lopsided_away, {}, {"stage": "Regular Season", "weather": {}})
        self.assertLess(lopsided["model"]["d"], even["model"]["d"])
        self.assertLessEqual(lopsided["model"]["d"], 26)
        self.assertGreaterEqual(lopsided["model"]["d"], 12)


class SoccerPreseasonPriorBoostTests(unittest.TestCase):
    """Same fix as PredictPriorBoostTests, extended to soccer: pts/gd/form
    are read with no reliability gate at all for soccer, so a team with zero
    games played contributes nothing there either, leaving class/elo to
    carry the whole signal -- but they previously had no equivalent boost to
    the American branch's, so a real preseason class gap (e.g. a big club vs
    a newly-promoted one) stayed muted until games started."""

    def setUp(self):
        self.old_key, self.old_comp = fetch_data.COMP_KEY, fetch_data.COMP
        self.old_ratings_file, self.old_ratings = fetch_data.RATINGS_FILE, fetch_data._RATINGS
        fetch_data.COMP_KEY = "EPL"
        fetch_data.COMP = dict(fetch_data.COMPETITIONS["EPL"])
        fd, self.tmp_path = tempfile.mkstemp(suffix=".json")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"Big Club": {"fifa_rank": 3, "squad_value_m": 900, "star_value_m": 120},
                       "Newly Promoted": {"fifa_rank": 45, "squad_value_m": 60, "star_value_m": 8}}, f)
        fetch_data.RATINGS_FILE = self.tmp_path
        fetch_data._RATINGS = None

    def tearDown(self):
        fetch_data.COMP_KEY, fetch_data.COMP = self.old_key, self.old_comp
        fetch_data.RATINGS_FILE, fetch_data._RATINGS = self.old_ratings_file, self.old_ratings
        os.unlink(self.tmp_path)

    def test_preseason_class_gap_is_boosted_versus_an_identical_in_season_gap(self):
        home = {"name": "Big Club", "pts": 0, "gd": 0, "form": "", "pld": 0}
        away = {"name": "Newly Promoted", "pts": 0, "gd": 0, "form": "", "pld": 0}
        preseason = fetch_data.predict(dict(home), dict(away), {}, {"stage": "Regular Season", "weather": {}})
        home_est = dict(home, pld=12, pts=28, gd=20, form="W W W L W")
        away_est = dict(away, pld=12, pts=10, gd=-15, form="L L W L L")
        established = fetch_data.predict(home_est, away_est, {}, {"stage": "Regular Season", "weather": {}})
        self.assertGreater(preseason["why"]["class"], established["why"]["class"])


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
        fetch_data.COMP_KEY = "NFL"
        fetch_data.COMP = dict(fetch_data.COMPETITIONS["NFL"])

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


class SoccerKnownRatingGateTests(unittest.TestCase):
    """Root-cause fix for a 2026-07-25 report ('strong teams undervalued in
    domestic soccer'): rating_boost()/rating_parts() fall back to flat
    neutral defaults (fifa_rank=45, squad_value_m=120, star_value_m=25) for
    any team with no ratings_<league>.json entry -- and most hand-curated
    domestic-league files only cover a handful of teams (8 of 18 for
    Bundesliga/Ligue1 at the time of this report). The American branch of
    predict() already refused to invent a "class" prior for an unrated team
    (known_rating gate); soccer's fifa/value/star were applied unconditionally,
    so every uncurated team silently got the exact same non-zero class figure
    -- indistinguishable from a real rating. predict() now gates soccer's
    fifa/value/star the same way.

    The two magnitudes below are deliberately IDENTICAL (the curated entry's
    numbers equal rating_boost()'s own neutral-default numbers) so this test
    isolates the known/unknown gate itself, not a difference in the numbers:
    before this fix an uncurated team was numerically indistinguishable from
    one curated with exactly the neutral defaults, so this test could not
    have failed under the old code -- it fails now only if the gate regresses."""

    def setUp(self):
        self.old_key, self.old_comp = fetch_data.COMP_KEY, fetch_data.COMP
        self.old_ratings_file, self.old_ratings = fetch_data.RATINGS_FILE, fetch_data._RATINGS
        fetch_data.COMP_KEY = "EPL"
        fetch_data.COMP = dict(fetch_data.COMPETITIONS["EPL"])
        fd, self.tmp_path = tempfile.mkstemp(suffix=".json")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            # Same numbers rating_boost()/rating_parts() use as their neutral
            # fallback for a team with NO entry at all.
            json.dump({"Curated Neutral FC": {"fifa_rank": 45, "squad_value_m": 120,
                                               "star_value_m": 25}}, f)
        fetch_data.RATINGS_FILE = self.tmp_path
        fetch_data._RATINGS = None

    def tearDown(self):
        fetch_data.COMP_KEY, fetch_data.COMP = self.old_key, self.old_comp
        fetch_data.RATINGS_FILE, fetch_data._RATINGS = self.old_ratings_file, self.old_ratings
        os.unlink(self.tmp_path)

    def test_uncurated_team_contributes_no_class_even_though_the_numbers_would_match_a_default(self):
        home = {"name": "Curated Neutral FC", "pts": 0, "gd": 0, "form": "", "pld": 0}
        away = {"name": "Totally Uncurated FC", "pts": 0, "gd": 0, "form": "", "pld": 0}
        pred = fetch_data.predict(dict(home), dict(away), {}, {"stage": "Regular Season", "weather": {}})
        # A curated (even if numerically "neutral") entry must count for
        # something -- the whole point of the gate is "has real data" vs
        # "has none", not "is the number impressive".
        self.assertGreater(pred["why"]["class"], 0)

    def test_two_uncurated_teams_get_zero_class_signal_either_side(self):
        home = {"name": "Nobody FC", "pts": 0, "gd": 0, "form": "", "pld": 0}
        away = {"name": "Nobody Else FC", "pts": 0, "gd": 0, "form": "", "pld": 0}
        pred = fetch_data.predict(dict(home), dict(away), {}, {"stage": "Regular Season", "weather": {}})
        self.assertEqual(pred["why"]["class"], 0)


class OutrightMarketKeyVerificationTests(unittest.TestCase):
    """Confirmed live against The Odds API's own /v4/sports catalog
    (GET /v4/sports/?all=true, which the API's docs state costs no usage
    credits, checked 2026-07-25 without touching the account's exhausted
    monthly quota): the entire catalog has exactly 12 sport_keys with
    has_outrights=true, covering NFL/NBA/MLB/NHL/NCAAF/NCAAB championship
    winners, four golf majors, the US presidential election, and exactly one
    soccer entry -- "soccer_fifa_world_cup_winner". There is no
    "soccer_uefa_champs_league_winner", "soccer_epl_winner",
    "soccer_spain_la_liga_winner", "soccer_italy_serie_a_winner",
    "soccer_germany_bundesliga_winner", or "soccer_france_ligue_one_winner"
    -- those six keys had been sitting in COMPETITIONS since the initial
    commit, apparently guessed by analogy with the real American-sports keys
    rather than verified, and were removed. This test pins that finding so
    nobody reintroduces an unverified guess without re-checking the live
    catalog first."""

    def test_only_the_real_world_cup_outright_key_survives(self):
        for key in ("UCL", "EPL", "LALIGA", "SERIEA", "BUNDESLIGA", "LIGUE1"):
            self.assertIsNone(
                fetch_data.COMPETITIONS[key]["outright"],
                f"{key} has no verified outright/futures market at The Odds API -- "
                "see this test's docstring before reintroducing a key here.")
        self.assertEqual(fetch_data.COMPETITIONS["WC"]["outright"], "soccer_fifa_world_cup_winner")
        # The American/college sports keep their real, working outright keys --
        # this fix must not touch those.
        for key, expected in (
            ("NFL", "americanfootball_nfl_super_bowl_winner"),
            ("NBA", "basketball_nba_championship_winner"),
            ("MLB", "baseball_mlb_world_series_winner"),
            ("NHL", "icehockey_nhl_championship_winner"),
            ("NCAAF", "americanfootball_ncaaf_championship_winner"),
            ("NCAAM", "basketball_ncaab_championship_winner"),
        ):
            self.assertEqual(fetch_data.COMPETITIONS[key]["outright"], expected)

    def test_fetch_outrights_no_ops_without_a_network_call_for_leagues_with_no_market(self):
        old_key, old_comp = fetch_data.COMP_KEY, fetch_data.COMP
        old_cache = dict(fetch_data._OUT_CACHE)
        try:
            fetch_data.COMP_KEY = "EPL"
            fetch_data.COMP = dict(fetch_data.COMPETITIONS["EPL"])
            fetch_data._OUT_CACHE = {"t": 0.0, "data": []}
            with mock.patch.object(fetch_data, "_get") as get_mock:
                result = fetch_data.fetch_outrights({})
            get_mock.assert_not_called()
            self.assertEqual(result, [])
            self.assertTrue(any("no outright market for this competition" in d for d in fetch_data.DIAG))
        finally:
            fetch_data.COMP_KEY, fetch_data.COMP = old_key, old_comp
            fetch_data._OUT_CACHE = old_cache


if __name__ == "__main__":
    unittest.main()
