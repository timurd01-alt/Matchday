"""Unit tests for the pure model/derivation logic in fetch_data.py.

These cover the parts of the pipeline that are deterministic and I/O-free
(or can be isolated from disk by seeding module globals): name
normalization and odds matching, the probability helpers that feed the
prediction model, the self-training Elo/H2H stores, and standings
derivation. None of them touch the network or write files — the stateful
tests seed the in-memory caches and stub the save functions.
"""

import unittest

import fetch_data as fd


class NameNormalizationTests(unittest.TestCase):
    def test_canon_strips_accents_punctuation_and_connectors(self):
        # accents dropped, "&" -> "and" then removed as a connector, hyphen -> space
        self.assertEqual(fd._canon("Atlético & the-Real"), "atletico real")

    def test_norm_applies_country_aliases(self):
        self.assertEqual(fd.norm("USA"), "united states")
        self.assertEqual(fd.norm("Korea Republic"), "south korea")
        self.assertEqual(fd.norm("Türkiye"), "turkey")
        self.assertEqual(fd.norm("Czechia"), "czech republic")

    def test_norm_empty_is_empty(self):
        self.assertEqual(fd.norm(""), "")
        self.assertEqual(fd.norm(None), "")

    def test_name_match_handles_subset_and_token_overlap(self):
        self.assertTrue(fd._name_match("Cape Verde", "Cape Verde Islands"))
        self.assertTrue(fd._name_match("USA", "United States"))
        self.assertFalse(fd._name_match("Spain", "France"))

    def test_name_match_blank_name_never_matches(self):
        # A blank/empty name normalizes to "" and must not match anything —
        # otherwise it would be a substring of every team name.
        self.assertFalse(fd._name_match("", "Spain"))
        self.assertFalse(fd._name_match("Spain", ""))
        self.assertFalse(fd._name_match("", ""))


class FindOddsTests(unittest.TestCase):
    def test_exact_pair_lookup(self):
        odds = {fd.pair("Spain", "France"): {"h": 2.0}}
        rec, how = fd.find_odds(odds, "Spain", "France")
        self.assertEqual(rec, {"h": 2.0})
        self.assertEqual(how, "exact")

    def test_exact_is_order_independent(self):
        # pair() is a frozenset, so home/away order should not matter
        odds = {fd.pair("Spain", "France"): {"h": 2.0}}
        _, how = fd.find_odds(odds, "France", "Spain")
        self.assertEqual(how, "exact")

    def test_fuzzy_fallback_tolerates_name_variants(self):
        # "Newcastle" is a subset of the stored "Newcastle United", so the
        # exact frozenset lookup misses but the fuzzy pass recovers it.
        odds = {fd.pair("Newcastle United", "Mexico"): {"h": 1.8}}
        rec, how = fd.find_odds(odds, "Newcastle", "Mexico")
        self.assertEqual(how, "fuzzy")
        self.assertEqual(rec, {"h": 1.8})

    def test_country_alias_still_resolves_as_exact(self):
        # norm() maps "USA" -> "united states", so the alias collapses onto
        # the stored key and resolves exactly rather than via the fuzzy pass.
        odds = {fd.pair("United States", "Mexico"): {"h": 1.8}}
        _, how = fd.find_odds(odds, "USA", "Mexico")
        self.assertEqual(how, "exact")

    def test_no_match_returns_none(self):
        odds = {fd.pair("Spain", "France"): {"h": 2.0}}
        rec, how = fd.find_odds(odds, "Brazil", "Argentina")
        self.assertIsNone(rec)
        self.assertEqual(how, "none")


class ProbabilityHelperTests(unittest.TestCase):
    def test_clamp_bounds_and_bad_input(self):
        self.assertEqual(fd._clamp(5, 0, 10), 5)
        self.assertEqual(fd._clamp(-3, 0, 10), 0)
        self.assertEqual(fd._clamp(99, 0, 10), 10)
        # non-numeric falls back to the low bound
        self.assertEqual(fd._clamp("nope", 1, 10), 1)

    def test_round_triplet_always_sums_to_100(self):
        for vals in ({"h": 33.3, "d": 33.3, "a": 33.3},
                     {"h": 50.5, "d": 24.7, "a": 24.8},
                     {"h": 40, "d": 35, "a": 25},
                     {"h": 99.6, "d": 0.2, "a": 0.2}):
            out = fd._round_triplet(vals)
            self.assertEqual(sum(out.values()), 100, vals)
            self.assertTrue(all(v >= 0 for v in out.values()), vals)

    def test_round_triplet_all_zero_input_falls_back_to_uniform(self):
        # With no probability mass to normalize, fall back to a uniform
        # split that still sums to 100 rather than a degenerate total.
        out = fd._round_triplet({"h": 0, "d": 0, "a": 0})
        self.assertEqual(sum(out.values()), 100)
        self.assertEqual(out, {"h": 34, "d": 33, "a": 33})

    def test_temperature_scale_never_zeroes_a_side(self):
        out = fd._temperature_scale_pct({"h": 98, "d": 1, "a": 1}, temp=2.2)
        self.assertEqual(sum(out.values()), 100)
        # softening a near-certain favourite must leave live mass elsewhere
        self.assertGreater(out["d"] + out["a"], 0)
        self.assertGreater(out["h"], out["d"])

    def test_temperature_two_way_ignores_draw(self):
        out = fd._temperature_scale_pct({"h": 90, "a": 10}, temp=1.5, two_way=True)
        self.assertEqual(out["d"], 0)
        self.assertEqual(out["h"] + out["a"], 100)

    def test_low_goal_probability_prefers_under_market(self):
        p = fd._low_goal_probability({"totals": {"under_pct": 60}}, draw_pct=25)
        self.assertAlmostEqual(p, 0.60, places=6)

    def test_low_goal_probability_proxy_without_market(self):
        # no totals market: derived from draw pressure, still within clamp band
        p = fd._low_goal_probability({}, draw_pct=30)
        self.assertGreaterEqual(p, 0.35)
        self.assertLessEqual(p, 0.72)


class WeightedFormTests(unittest.TestCase):
    def test_run_of_identical_results_matches_flat_sum(self):
        # documented drop-in property: five wins -> 15, same as the old flat sum
        self.assertEqual(fd._weighted_form_score("W W W W W"), 15.0)

    def test_recent_results_weigh_more_than_old_ones(self):
        recent_win = fd._weighted_form_score("L L L L W")
        old_win = fd._weighted_form_score("W L L L L")
        self.assertGreater(recent_win, old_win)

    def test_empty_form_is_zero(self):
        self.assertEqual(fd._weighted_form_score(""), 0.0)
        self.assertEqual(fd._weighted_form_score(None), 0.0)


class EloTests(unittest.TestCase):
    def setUp(self):
        # isolate from disk: seed the in-memory store and stub the writer
        self._orig_elo = fd._ELO
        self._orig_save = fd._save_elo
        fd._ELO = {"teams": {}, "seen": {}}
        fd._save_elo = lambda: None

    def tearDown(self):
        fd._ELO = self._orig_elo
        fd._save_elo = self._orig_save

    def _finished(self, mid, home, away, winner):
        return {"id": mid, "status": "FINISHED", "score": {"winner": winner},
                "home": {"name": home}, "away": {"name": away}}

    def test_home_win_moves_ratings_symmetrically(self):
        fd.update_elo([self._finished("m1", "Alpha", "Beta", "h")])
        rh = fd._ELO["teams"][fd.norm("Alpha")]["r"]
        ra = fd._ELO["teams"][fd.norm("Beta")]["r"]
        self.assertGreater(rh, 1500.0)
        self.assertLess(ra, 1500.0)
        # zero-sum update: what the winner gains, the loser loses
        self.assertAlmostEqual(rh - 1500.0, 1500.0 - ra, places=6)

    def test_update_is_idempotent_on_repeated_match_id(self):
        m = [self._finished("m1", "Alpha", "Beta", "h")]
        fd.update_elo(m)
        after_first = fd._ELO["teams"][fd.norm("Alpha")]["r"]
        fd.update_elo(m)  # same match id — must not double-count
        self.assertEqual(fd._ELO["teams"][fd.norm("Alpha")]["r"], after_first)

    def test_unfinished_and_invalid_results_are_ignored(self):
        fd.update_elo([
            {"id": "x", "status": "IN_PLAY", "score": {"winner": "h"},
             "home": {"name": "Alpha"}, "away": {"name": "Beta"}},
            {"id": "y", "status": "FINISHED", "score": {"winner": None},
             "home": {"name": "Alpha"}, "away": {"name": "Beta"}},
        ])
        self.assertEqual(fd._ELO["teams"], {})

    def test_elo_strength_confidence_ramps_with_games(self):
        fd._ELO["teams"][fd.norm("Green")] = {"r": 1560.0, "n": 20}
        pts, conf = fd.elo_strength("Green")
        self.assertAlmostEqual(pts, 1.0, places=6)   # (1560-1500)/60
        self.assertEqual(conf, 1.0)                   # capped at full trust

    def test_elo_strength_unknown_team_is_neutral(self):
        self.assertEqual(fd.elo_strength("Nobody"), (0.0, 0.0))


class H2HTests(unittest.TestCase):
    def setUp(self):
        self._orig = fd._H2H
        fd._H2H = {"pairs": {}, "seen": {}}

    def tearDown(self):
        fd._H2H = self._orig

    def test_dominant_home_history_gives_positive_capped_nudge(self):
        hn, an = fd.norm("Alpha"), fd.norm("Beta")
        fd._H2H["pairs"][fd._pair_key(hn, an)] = [
            {"date": "2025-01-01", "home": hn, "winner": "h"},
            {"date": "2025-02-01", "home": hn, "winner": "h"},
        ]
        pts, conf = fd.h2h_strength("Alpha", "Beta")
        self.assertGreater(pts, 0)
        self.assertLessEqual(pts, 0.8)  # capped magnitude
        self.assertGreater(conf, 0)

    def test_no_history_is_neutral(self):
        self.assertEqual(fd.h2h_strength("Alpha", "Beta"), (0.0, 0.0))

    def test_perspective_flips_sign(self):
        hn, an = fd.norm("Alpha"), fd.norm("Beta")
        fd._H2H["pairs"][fd._pair_key(hn, an)] = [
            {"date": "2025-01-01", "home": hn, "winner": "h"},
        ]
        from_alpha, _ = fd.h2h_strength("Alpha", "Beta")
        from_beta, _ = fd.h2h_strength("Beta", "Alpha")
        self.assertAlmostEqual(from_alpha, -from_beta, places=6)


class ResolveScoreTests(unittest.TestCase):
    def test_regulation_winner(self):
        m = {"status": "FINISHED", "score": {"fullTime": {"home": 2, "away": 0}}}
        hg, ag, winner, _pens, _r90 = fd._resolve_score(m)
        self.assertEqual((hg, ag, winner), (2, 0, "h"))

    def test_shootout_decides_a_level_match(self):
        m = {"status": "FINISHED", "score": {
            "regularTime": {"home": 1, "away": 1},
            "penalties": {"home": 4, "away": 2}}}
        hg, ag, winner, pens, _r90 = fd._resolve_score(m)
        # displayed scoreline stays level, winner resolved on penalties
        self.assertEqual((hg, ag), (1, 1))
        self.assertEqual(winner, "h")
        self.assertEqual(pens, (4, 2))

    def test_draw_without_penalties(self):
        m = {"status": "FINISHED", "score": {"fullTime": {"home": 1, "away": 1}}}
        _, _, winner, _, _ = fd._resolve_score(m)
        self.assertEqual(winner, "d")

    def test_prefers_extra_time_scoreline(self):
        m = {"status": "FINISHED", "score": {
            "regularTime": {"home": 1, "away": 1},
            "extraTime": {"home": 2, "away": 1}}}
        hg, ag, winner, _, _ = fd._resolve_score(m)
        self.assertEqual((hg, ag, winner), (2, 1, "h"))


class ComputeStandingsTests(unittest.TestCase):
    def _match(self, home, away, hs, as_, group="GROUP_A", status="FINISHED", date="2026-06-01"):
        return {"homeTeam": {"name": home}, "awayTeam": {"name": away},
                "group": group, "status": status, "utcDate": date,
                "score": {"fullTime": {"home": hs, "away": as_}}}

    def test_points_form_and_goal_difference(self):
        raw = [
            self._match("Alpha", "Beta", 2, 0, date="2026-06-01"),
            self._match("Alpha", "Gamma", 1, 1, date="2026-06-05"),
        ]
        T = fd.compute_standings(raw)
        alpha = T[fd.norm("Alpha")]
        self.assertEqual(alpha["pld"], 2)
        self.assertEqual(alpha["pts"], 4)      # win (3) + draw (1)
        self.assertEqual(alpha["gd"], 2)       # +2, then 1-1
        self.assertEqual(alpha["form"], "W D")  # oldest -> newest

    def test_group_positions_ordered_by_points(self):
        raw = [self._match("Alpha", "Beta", 3, 0)]
        T = fd.compute_standings(raw)
        self.assertEqual(T[fd.norm("Alpha")]["pos"], 1)
        self.assertEqual(T[fd.norm("Beta")]["pos"], 2)

    def test_unplayed_matches_do_not_count(self):
        raw = [self._match("Alpha", "Beta", None, None, status="SCHEDULED")]
        T = fd.compute_standings(raw)
        self.assertEqual(T[fd.norm("Alpha")]["pld"], 0)


if __name__ == "__main__":
    unittest.main()
