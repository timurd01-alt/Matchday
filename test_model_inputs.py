import json
import os
import tempfile
import unittest

import fetch_data


def finished(mid, home, away, hs, aps):
    return {
        "id": mid, "status": "FINISHED", "kickoff": "2026-01-01T00:00:00Z",
        "home": {"name": home}, "away": {"name": away},
        "score": {"home": hs, "away": aps},
    }


class ModelInputTests(unittest.TestCase):
    def setUp(self):
        self.old_key = fetch_data.COMP_KEY
        self.old_comp = fetch_data.COMP
        fetch_data.COMP_KEY = "NCAAM"
        fetch_data.COMP = dict(fetch_data.COMPETITIONS["NCAAM"])

    def tearDown(self):
        fetch_data.COMP_KEY = self.old_key
        fetch_data.COMP = self.old_comp

    def test_cached_results_are_backfilled_with_winners(self):
        matches = [finished("one", "Alpha", "Beta", 80, 72)]
        fetch_data.normalize_match_results(matches)
        self.assertEqual(matches[0]["score"]["winner"], "h")

    def test_knockout_extra_time_uses_winner_but_market_uses_regulation(self):
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
        fetch_data.COMP["has_draws"] = True
        match = {
            "stage": "Final",
            "score": {"home": 2, "away": 1, "winner": "h"},
        }
        self.assertEqual(fetch_data._scorecard_results(match), ("h", None))
        rec = {"pick": "h", "market_pick": "d", "market_hit": True}
        fetch_data._apply_scorecard_grade(rec, "h", None)
        self.assertTrue(rec["model_hit"])
        self.assertTrue(rec["market_hit"])

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
    it anyway. LINEUP_BACKFILL_ENABLED now makes that structurally
    impossible regardless of what the DB file contains."""

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

    def tearDown(self):
        fetch_data.COMP_KEY, fetch_data.COMP = self.old_key, self.old_comp
        fetch_data.PLAYER_DB_FILE = self.old_player_db_file
        os.unlink(self.tmp_path)

    def test_stale_player_db_entries_never_backfill_while_disabled(self):
        self.assertFalse(fetch_data.LINEUP_BACKFILL_ENABLED,
                          "flip this back on only once a real lineup source is active")
        scorers = [{"name": "Striker", "team": "Team B", "goals": 5, "assists": 1,
                    "played": 3, "position": "Forward"}]
        result = fetch_data.build_team_of_tournament([], scorers, [])
        self.assertIsNotNone(result)
        self.assertNotIn("Keeper One", [p["name"] for p in result["xi"]])
        self.assertIn("don't fake it", result["note"])


if __name__ == "__main__":
    unittest.main()
