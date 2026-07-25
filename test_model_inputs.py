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


class NflverseEpaTests(unittest.TestCase):
    """Coverage for the nflverse play-by-play EPA signal: aggregation from
    raw play rows, and that it only ever applies to NFL predictions."""

    FAKE_ROWS = [
        # two offensive snaps for KC (posteam) against BUF (defteam)
        {"season_type": "REG", "play_type": "pass", "epa": "0.4", "posteam": "KC", "defteam": "BUF"},
        {"season_type": "REG", "play_type": "run", "epa": "-0.2", "posteam": "KC", "defteam": "BUF"},
        # one BUF offensive snap back the other way
        {"season_type": "REG", "play_type": "pass", "epa": "0.1", "posteam": "BUF", "defteam": "KC"},
        # excluded: postseason, non-run/pass, and unresolved epa
        {"season_type": "POST", "play_type": "pass", "epa": "0.9", "posteam": "KC", "defteam": "BUF"},
        {"season_type": "REG", "play_type": "no_play", "epa": "0.9", "posteam": "KC", "defteam": "BUF"},
        {"season_type": "REG", "play_type": "pass", "epa": "NA", "posteam": "KC", "defteam": "BUF"},
        # LA -> Rams code fixup
        {"season_type": "REG", "play_type": "run", "epa": "0.3", "posteam": "LA", "defteam": "SF"},
    ]

    def setUp(self):
        self.old_key, self.old_comp = fetch_data.COMP_KEY, fetch_data.COMP
        self.old_epa = fetch_data._NFLVERSE_EPA
        fetch_data._NFLVERSE_EPA = {fetch_data.norm("Kansas City Chiefs"):
                                     {"off_epa": 0.15, "def_epa": -0.05, "plays": 600}}

    def tearDown(self):
        fetch_data.COMP_KEY, fetch_data.COMP = self.old_key, self.old_comp
        fetch_data._NFLVERSE_EPA = self.old_epa

    def _team(self, name, **overrides):
        base = {"name": name, "pld": 8, "w": 4, "l": 4, "win_pct": .5, "gf": 200, "ga": 200, "form": ""}
        return {**base, **overrides}

    def _fake_csv_bytes(self):
        import csv, gzip, io
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=["season_type", "play_type", "epa", "posteam", "defteam"])
        writer.writeheader()
        writer.writerows(self.FAKE_ROWS)
        return gzip.compress(buf.getvalue().encode("utf-8"))

    def test_aggregates_only_regular_season_run_pass_plays_with_resolved_epa(self):
        with mock.patch.object(fetch_data, "_get_bytes", return_value=self._fake_csv_bytes()):
            teams = fetch_data.fetch_nflverse_epa(2025)
        kc = teams["Kansas City Chiefs"]
        self.assertEqual(kc["plays"], 3)  # 2 offensive + 1 defensive, postseason/no_play/NA excluded
        self.assertAlmostEqual(kc["off_epa"], (0.4 - 0.2) / 2)
        self.assertAlmostEqual(kc["def_epa"], 0.1)
        self.assertIn("Los Angeles Rams", teams)  # LA code resolved via NFLVERSE_CODE_FIXUPS

    def test_unknown_team_has_no_signal(self):
        self.assertEqual(fetch_data.nflverse_epa_strength("Nonexistent Team"), (0.0, 0.0))

    def test_epa_signal_applies_to_nfl_predictions(self):
        fetch_data.COMP_KEY = "NFL"
        fetch_data.COMP = dict(fetch_data.COMPETITIONS["NFL"])
        prediction = fetch_data.predict(self._team("Kansas City Chiefs"), self._team("Test Opponent"), {})
        self.assertIn("epa", prediction["why"])
        self.assertIn("epa", prediction["data_quality"]["signals"])

    def test_epa_signal_is_absent_outside_nfl(self):
        fetch_data.COMP_KEY = "NCAAF"
        fetch_data.COMP = dict(fetch_data.COMPETITIONS["NCAAF"])
        prediction = fetch_data.predict(self._team("Kansas City Chiefs"), self._team("Test Opponent"), {})
        self.assertNotIn("epa", prediction["why"])


if __name__ == "__main__":
    unittest.main()
