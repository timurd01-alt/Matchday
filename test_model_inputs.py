import json
import os
import tempfile
import unittest
from unittest import mock

import fetch_data
import refresh_college_talent


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

    def test_mlb_market_power_is_not_mislabeled_as_personnel_class(self):
        fetch_data.COMP_KEY = "MLB"
        fetch_data.COMP = dict(fetch_data.COMPETITIONS["MLB"])
        fetch_data.apply_market_strength([
            {"team": "New York Yankees", "pct": 20.0},
            {"team": "Oakland Athletics", "pct": 1.0},
        ])
        pred = fetch_data.predict(
            {"name": "New York Yankees", "pld": 0},
            {"name": "Oakland Athletics", "pld": 0}, {},
            {"stage": "Regular", "weather": {}},
        )
        self.assertEqual(pred["why"]["class"], 0)
        self.assertGreater(pred["why"]["market_power"], 0)
        self.assertEqual(pred["class_meta"]["label"], "Personnel edge")
        self.assertEqual(pred["class_meta"]["coverage"], "unavailable")


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


class PlayerDbSeasonResetTests(unittest.TestCase):
    """player_db_<comp>.json never had a season concept at all -- it would
    have kept accumulating one club's clean sheets across every season
    forever, past and future blended into a single number. Dishonest for a
    feature literally named "Team of the TOURNAMENT". update_player_db()
    must reset to a blank slate the first time it runs in a new season."""

    def setUp(self):
        self.old_comp_key, self.old_comp = fetch_data.COMP_KEY, fetch_data.COMP
        fetch_data.COMP_KEY = "UCL"
        fetch_data.COMP = dict(fetch_data.COMPETITIONS["UCL"])
        self.old_player_db_file = fetch_data.PLAYER_DB_FILE
        fd_num, self.tmp_path = tempfile.mkstemp(suffix=".json")
        os.close(fd_num)
        fetch_data.PLAYER_DB_FILE = self.tmp_path

    def tearDown(self):
        fetch_data.COMP_KEY, fetch_data.COMP = self.old_comp_key, self.old_comp
        fetch_data.PLAYER_DB_FILE = self.old_player_db_file
        os.unlink(self.tmp_path)

    def _match(self, mid):
        return {"id": mid, "status": "FINISHED", "score": {"home": 1, "away": 0},
                "home": {"name": "Team A"}, "away": {"name": "Team B"},
                "lineups": {"home": {"formation": "4-3-3",
                                     "xi": [{"name": f"Player {i}"} for i in range(11)]}}}

    def test_stale_season_entries_are_cleared_before_folding_in_new_results(self):
        with open(self.tmp_path, "w", encoding="utf-8") as f:
            json.dump({"_season": "2024-25", "_matches": ["old-m1"],
                       "players": {"stale player|team a": {"name": "Stale Player", "team": "Team A",
                                                            "role": "DEF", "apps": 30, "starts": 30,
                                                            "clean_sheets": 20}}}, f)
        with mock.patch.object(fetch_data, "_current_soccer_season_label", return_value="2025-26"):
            db = fetch_data.update_player_db([self._match("new-m1")])
        self.assertNotIn("stale player|team a", db["players"])
        self.assertEqual(db["_season"], "2025-26")
        self.assertIn("new-m1", db["_matches"])
        self.assertNotIn("old-m1", db["_matches"])

    def test_same_season_entries_are_preserved_across_runs(self):
        with mock.patch.object(fetch_data, "_current_soccer_season_label", return_value="2025-26"):
            first = fetch_data.update_player_db([self._match("m1")])
            self.assertIn("m1", first["_matches"])
            second = fetch_data.update_player_db([self._match("m2")])
        self.assertIn("m1", second["_matches"])
        self.assertIn("m2", second["_matches"])


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

    def test_mlb_is_six_divisions_with_five_teams_each(self):
        tables = fetch_data._group_us_pro_standings(self._flat_table("MLB"), "MLB")
        self.assertEqual(len(tables), 6)
        self.assertTrue(all(t["table_type"] == "official_standings" for t in tables))
        self.assertTrue(all(len(t["teams"]) == 5 for t in tables))
        self.assertEqual({t["group"] for t in tables}, set(fetch_data.US_PRO_STANDINGS_GROUPS["MLB"]))

    def test_nfl_is_eight_divisions_and_nba_is_two_conferences(self):
        nfl = fetch_data._group_us_pro_standings(self._flat_table("NFL"), "NFL")
        nba = fetch_data._group_us_pro_standings(self._flat_table("NBA"), "NBA")
        self.assertEqual([len(t["teams"]) for t in nfl], [4] * 8)
        self.assertEqual([len(t["teams"]) for t in nba], [15, 15])

    def test_power_ratings_are_separate_and_do_not_replace_division_rank(self):
        official = fetch_data._group_us_pro_standings(self._flat_table("MLB"), "MLB")
        division_positions = {t["name"]: t["pos"] for g in official for t in g["teams"]}
        payload = fetch_data._append_power_ratings_table(official)
        self.assertEqual(payload[-1]["table_type"], "power_ratings")
        self.assertEqual(len(payload[-1]["teams"]), 30)
        self.assertEqual(
            division_positions,
            {t["name"]: t["pos"] for g in payload[:-1] for t in g["teams"]})

    def test_placeholder_teams_are_not_rendered_as_a_real_division(self):
        tables = self._flat_table("MLB")
        tables[0]["teams"].append({"name": "Unknown", "pld": 0, "w": 0, "l": 0})
        grouped = fetch_data._group_us_pro_standings(tables, "MLB")
        self.assertFalse(any(t["name"] == "Unknown" for g in grouped for t in g["teams"]))

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
        fetch_data.COMP_KEY = "NFL"
        fetch_data.COMP = dict(fetch_data.COMPETITIONS["NFL"])
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
        fetch_data.COMP_KEY = "NFL"
        fetch_data.COMP = dict(fetch_data.COMPETITIONS["NFL"])
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

    def test_soccer_margin_is_labeled_in_goals_with_an_explicit_sign(self):
        fetch_data.COMP_KEY = "EPL"
        fetch_data.COMP = dict(fetch_data.COMPETITIONS["EPL"])
        home = {"name": "Strong FC", "pts": 30, "gd": 20, "form": "W W W W W"}
        away = {"name": "Weak FC", "pts": 5, "gd": -20, "form": "L L L L L"}
        pred = fetch_data.predict(dict(home), dict(away), {}, {"stage": "Regular Season", "weather": {}})
        margin = pred["predicted_margin"]
        self.assertEqual(margin["unit"], "goals")
        self.assertTrue(margin["label"].endswith("goals"))
        self.assertTrue(margin["label"].startswith("+"))

    def test_an_even_matchup_reads_as_even_not_a_fake_precise_number(self):
        fetch_data.COMP_KEY = "NBA"
        fetch_data.COMP = dict(fetch_data.COMPETITIONS["NBA"])
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

    def test_placeholder_side_is_never_trained_into_the_elo_store(self):
        # Live 2026-07-30: one BALLDONTLIE MLB game arrived with both sides
        # named "Unknown", producing a permanent "baseball:unknown" entry
        # (n=2) in the shared store -- a rating for a team that doesn't exist.
        fetch_data.COMP_KEY = "MLB"
        fetch_data.COMP = dict(fetch_data.COMPETITIONS["MLB"])
        fetch_data.update_elo([
            _finished("bdl-mlb-8712499", "Unknown", "Unknown", 0, 4,
                      "2026-07-15T00:00:00Z", "a"),
            _finished("bdl-mlb-8712500", "Boston Red Sox", "TBD", 3, 1,
                      "2026-07-15T00:00:00Z", "h"),
        ])
        store = fetch_data._load_elo()
        self.assertEqual(store["teams"], {})
        # Not marked seen either -- a placeholder game is skipped, not
        # recorded as processed, so a later resolved copy can still train.
        self.assertEqual(store["seen"], {})
        self.assertEqual(fetch_data.elo_strength("Boston Red Sox"), (0.0, 0.0))

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

    def test_epl_rejects_real_nfl_and_mlb_articles_found_live(self):
        fetch_data.COMP_KEY = "EPL"
        self.assertFalse(fetch_data._news_relevant(
            {"headline": "MLB rumors: Major trade candidate could miss rest of 2026 with injury", "desc": ""}))
        self.assertFalse(fetch_data._news_relevant(
            {"headline": "Fantasy football rankings 2026: Sleepers from the model", "desc": ""}))

    def test_epl_accepts_a_real_premier_league_article(self):
        fetch_data.COMP_KEY = "EPL"
        self.assertTrue(fetch_data._news_relevant(
            {"headline": "Arsenal Mulling Move For Real Madrid Star Vinicius Junior", "desc": ""}))

    def test_ucl_rejects_a_real_scottish_football_article_found_live(self):
        # UCL's own generic BBC/Sky "football" feeds cover every league, not
        # just the Champions League -- this must not accept everything with
        # a ball in it.
        fetch_data.COMP_KEY = "UCL"
        self.assertFalse(fetch_data._news_relevant(
            {"headline": "Holders St Mirren visit Rangers in League Cup last 16", "desc": ""}))

    def test_ucl_accepts_a_real_champions_league_article(self):
        fetch_data.COMP_KEY = "UCL"
        self.assertTrue(fetch_data._news_relevant(
            {"headline": "Real Madrid preparing Champions League squad for Manchester City clash", "desc": ""}))

    def test_ncaam_rejects_the_real_mlb_recap_that_matched_on_the_bare_city_name(self):
        fetch_data.COMP_KEY = "NCAAM"
        self.assertFalse(fetch_data._news_relevant(
            {"headline": "Kansas City Royals vs. Detroit Tigers Results, Stats, and Recap", "desc": ""}))

    def test_ncaam_still_accepts_real_kansas_basketball_coverage(self):
        fetch_data.COMP_KEY = "NCAAM"
        self.assertTrue(fetch_data._news_relevant(
            {"headline": "Kansas Jayhawks land 5-star recruit ahead of March Madness", "desc": ""}))

    def test_mlb_unaffected_by_the_new_soccer_entries(self):
        fetch_data.COMP_KEY = "MLB"
        self.assertTrue(fetch_data._news_relevant(
            {"headline": "With Judge's timeline uncertain, Yankees face a deadline balancing act", "desc": ""}))
        self.assertFalse(fetch_data._news_relevant(
            {"headline": "Chiefs training camp update ahead of the NFL season", "desc": ""}))

    def test_previous_news_drops_items_that_no_longer_pass_relevance(self):
        # Confirmed live 2026-07-26: even after the relevance-filtering gap
        # itself was fixed and fresh EPL/UCL fetches were working again, the
        # News tab kept showing the exact same old NFL/MLB pollution -- items
        # accepted back when soccer had no filtering at all were being
        # merged forward by fetch_news() forever, since only fresh items
        # were ever checked against _news_relevant(). _load_previous_news()
        # must re-check every carried-forward item too.
        data_path = "data_epl.json"
        old_existed = os.path.exists(data_path)
        old_content = None
        if old_existed:
            with open(data_path, encoding="utf-8") as f:
                old_content = f.read()
        published = fetch_data.datetime.datetime.now(fetch_data.datetime.timezone.utc).isoformat()
        with open(data_path, "w", encoding="utf-8") as f:
            json.dump({"news_scope": "EPL", "news": [
                {"headline": "MLB rumors: Major trade candidate could miss rest of 2026", "source": "CBS Sports", "published": published},
                {"headline": "Arsenal Mulling Move For Real Madrid Star Vinicius Junior", "source": "FOX Sports", "published": published},
            ]}, f)
        try:
            fetch_data.COMP_KEY = "EPL"
            previous = fetch_data._load_previous_news()
        finally:
            if old_existed:
                with open(data_path, "w", encoding="utf-8") as f:
                    f.write(old_content)
            else:
                os.unlink(data_path)
        headlines = [item["headline"] for item in previous]
        self.assertNotIn("MLB rumors: Major trade candidate could miss rest of 2026", headlines)
        self.assertIn("Arsenal Mulling Move For Real Madrid Star Vinicius Junior", headlines)


if __name__ == "__main__":
    unittest.main()
