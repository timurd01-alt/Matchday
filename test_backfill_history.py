"""Regression tests for backfill_history.py -- the one-time historical Elo
seed script. Covers the four things that would silently corrupt Elo history
if they regressed: chronological ordering, idempotency, the provider-per-
season assignment (no double-counting an overlapping season), and the
sport-scoped Elo keying carrying through the script's own competition loop.

All provider I/O is mocked (backfill_history.fetch_season is patched) --
these tests never touch the network.
"""
import os
import tempfile
import unittest
from unittest import mock

import backfill_history as bh
import fetch_data as fd


def _match(mid, home, away, hs, aps, kickoff, winner):
    return {"id": mid, "status": "FINISHED", "kickoff": kickoff,
            "home": {"name": home}, "away": {"name": away},
            "score": {"home": hs, "away": aps, "winner": winner}}


class PlanAssignmentTests(unittest.TestCase):
    """The provider-per-(competition, season) assignment table itself."""

    def test_every_competitions_seasons_are_oldest_first(self):
        plan = bh.build_plan(last_full_year=2025)
        for comp, entries in plan.items():
            seasons = [s for s, _ in entries]
            self.assertEqual(seasons, sorted(seasons), f"{comp} not oldest-first: {seasons}")

    def test_domestic_leagues_never_double_source_an_overlapping_season(self):
        # football-data.org (2023-2025) and API-FOOTBALL (2022-2024) can
        # BOTH reach seasons 2023/2024 for domestic leagues/UCL -- pulling
        # both into Elo would double-count those two seasons' results. Each
        # season must map to exactly one provider.
        plan = bh.build_plan(last_full_year=2025)
        for comp in ("UCL", "EPL", "LALIGA", "SERIEA", "BUNDESLIGA", "LIGUE1"):
            entries = plan[comp]
            seasons = [s for s, _ in entries]
            self.assertEqual(len(seasons), len(set(seasons)),
                              f"{comp} lists a season more than once: {seasons}")
            by_season = dict(entries)
            # 2022 is the one season football-data.org's free plan can't
            # reach at all (403), so it's the only season assigned to
            # API-FOOTBALL here -- everything football-data.org CAN reach
            # (2023-2025) must come from football-data.org only, never
            # API-FOOTBALL too, even though API-FOOTBALL's free plan can
            # also technically reach 2023/2024.
            self.assertEqual(by_season[2022], "af")
            self.assertEqual(by_season[2023], "fd")
            self.assertEqual(by_season[2024], "fd")
            self.assertEqual(by_season[2025], "fd")

    def test_wc_only_has_the_one_real_past_tournament(self):
        # football-data.org 403s on 2022 and earlier (including the actual
        # 2022 World Cup); API-FOOTBALL is the only provider that can reach
        # it, and no earlier World Cup is reachable on the free plan.
        plan = bh.build_plan(last_full_year=2025)
        self.assertEqual(plan["WC"], [(2022, "af")])

    def test_nfl_starts_2002_not_2000(self):
        # BALLDONTLIE has no NFL games before season 2002 (live-verified with
        # a full per_page=100 request returning zero rows for 2000/2001, not
        # a rate-limit artifact) -- the plan must not silently ask for years
        # that don't exist.
        plan = bh.build_plan(last_full_year=2025)
        self.assertEqual(plan["NFL"][0][0], 2002)

    def test_nba_and_mlb_reach_the_full_2000_floor(self):
        plan = bh.build_plan(last_full_year=2025)
        self.assertEqual(plan["NBA"][0][0], 2000)
        self.assertEqual(plan["MLB"][0][0], 2000)

    def test_ncaaf_and_ncaam_reach_the_full_2000_floor(self):
        plan = bh.build_plan(last_full_year=2025)
        self.assertEqual(plan["NCAAF"][0][0], 2000)
        self.assertEqual(plan["NCAAM"][0][0], 2000)

    def test_last_full_year_bounds_every_range_inclusively(self):
        plan = bh.build_plan(last_full_year=2010)
        self.assertEqual(plan["NCAAF"][-1][0], 2010)
        self.assertEqual(plan["NFL"][-1][0], 2010)
        # soccer's season list is a fixed table, not derived from last_full_year
        self.assertEqual(plan["WC"], [(2022, "af")])


class _ScratchEloTestCase(unittest.TestCase):
    """Shared setup for tests that actually run backfill_history.run()
    against a throwaway ratings_elo.json, mirroring the monkeypatch pattern
    test_model_inputs.py's EloSportScopeTests already established for
    fetch_data.update_elo() directly."""

    def setUp(self):
        self.old_key, self.old_comp = fd.COMP_KEY, fd.COMP
        self.old_elo_file, self.old_elo = fd.ELO_FILE, fd._ELO
        handle, self.tmp_path = tempfile.mkstemp(suffix=".json")
        os.close(handle)
        os.unlink(self.tmp_path)  # start from a clean, nonexistent file
        fd.ELO_FILE = self.tmp_path
        fd._ELO = None

    def tearDown(self):
        fd.COMP_KEY, fd.COMP = self.old_key, self.old_comp
        fd.ELO_FILE, fd._ELO = self.old_elo_file, self.old_elo
        if os.path.exists(self.tmp_path):
            os.unlink(self.tmp_path)

    def _reset_store(self):
        if os.path.exists(self.tmp_path):
            os.unlink(self.tmp_path)
        fd._ELO = None


class ChronologicalOrderTests(_ScratchEloTestCase):
    def test_feeding_seasons_out_of_order_produces_different_final_ratings(self):
        # Team B loses to Team A in season 2000, then beats Team C in
        # season 2001. Team B's rating entering the 2001 game depends on
        # whether the 2000 loss has already been folded in -- so applying
        # 2001 before 2000 (wrong) must land on a different final rating
        # for B than applying 2000 before 2001 (correct), proving
        # cross-season order actually changes the result.
        season_2000 = [_match("s2000-1", "Team A", "Team B", 30, 10,
                               "2000-09-01T00:00:00Z", "h")]
        season_2001 = [_match("s2001-1", "Team B", "Team C", 20, 10,
                               "2001-09-01T00:00:00Z", "h")]
        by_season = {2000: season_2000, 2001: season_2001}

        forward_plan = {"NCAAF": [(2000, "x"), (2001, "x")]}
        with mock.patch.object(bh, "fetch_season",
                               side_effect=lambda comp, season, provider: by_season[season]):
            bh.run(["NCAAF"], plan=forward_plan)
        forward_b = fd._load_elo()["teams"]["football:team b"]["r"]

        self._reset_store()
        reverse_plan = {"NCAAF": [(2001, "x"), (2000, "x")]}
        with mock.patch.object(bh, "fetch_season",
                               side_effect=lambda comp, season, provider: by_season[season]):
            bh.run(["NCAAF"], plan=reverse_plan)
        reverse_b = fd._load_elo()["teams"]["football:team b"]["r"]

        self.assertNotEqual(forward_b, reverse_b,
                             "feeding seasons out of order should change Team B's final rating")

    def test_plan_driven_run_actually_uses_oldest_first_order(self):
        # Guards against run() ever reversing/re-sorting PLAN's order --
        # fetch_season must be called in exactly the order PLAN lists.
        calls = []

        def fake_fetch(comp, season, provider):
            calls.append(season)
            return []

        plan = {"NCAAF": [(2000, "x"), (2005, "x"), (2010, "x")]}
        with mock.patch.object(bh, "fetch_season", side_effect=fake_fetch):
            bh.run(["NCAAF"], plan=plan)
        self.assertEqual(calls, [2000, 2005, 2010])


class IdempotencyTests(_ScratchEloTestCase):
    def test_rerunning_the_same_season_does_not_double_count(self):
        games = [_match("x-1", "Team A", "Team B", 20, 10, "2015-09-01T00:00:00Z", "h")]
        plan = {"NCAAF": [(2015, "x")]}
        with mock.patch.object(bh, "fetch_season", return_value=games):
            bh.run(["NCAAF"], plan=plan)
            first = fd._load_elo()["teams"]["football:team a"]["r"]
            bh.run(["NCAAF"], plan=plan)  # re-run, identical result set
            second = fd._load_elo()["teams"]["football:team a"]["r"]
        self.assertEqual(first, second)
        self.assertEqual(len(fd._load_elo()["seen"]), 1)

    def test_dry_run_never_touches_the_elo_store(self):
        games = [_match("x-1", "Team A", "Team B", 20, 10, "2015-09-01T00:00:00Z", "h")]
        plan = {"NCAAF": [(2015, "x")]}
        with mock.patch.object(bh, "fetch_season", return_value=games):
            bh.run(["NCAAF"], dry_run=True, plan=plan)
        self.assertEqual(fd._load_elo()["teams"], {})
        self.assertEqual(fd._load_elo()["seen"], {})

    def test_a_failed_season_can_be_retried_without_reprocessing_earlier_ones(self):
        games_2010 = [_match("g-2010", "Team A", "Team B", 20, 10, "2010-09-01T00:00:00Z", "h")]
        games_2011 = [_match("g-2011", "Team A", "Team B", 15, 14, "2011-09-01T00:00:00Z", "h")]
        by_season = {2010: games_2010, 2011: games_2011}

        def flaky(comp, season, provider):
            if season == 2011:
                raise RuntimeError("simulated provider outage")
            return by_season[season]

        plan = {"NCAAF": [(2010, "x"), (2011, "x")]}
        with mock.patch.object(bh, "fetch_season", side_effect=flaky):
            failures = bh.run(["NCAAF"], plan=plan)
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0][:2], ("NCAAF", 2011))
        # 2010's result was still applied despite 2011 failing
        self.assertEqual(len(fd._load_elo()["seen"]), 1)

        # retry: 2011 now succeeds, 2010 must not be double counted
        with mock.patch.object(bh, "fetch_season",
                               side_effect=lambda comp, season, provider: by_season[season]):
            failures = bh.run(["NCAAF"], plan=plan)
        self.assertEqual(failures, [])
        self.assertEqual(len(fd._load_elo()["seen"]), 2)  # one result per season, not 3+


class SportScopedEloKeyingTests(_ScratchEloTestCase):
    def test_run_scopes_elo_keys_by_sport_across_competitions_in_one_process(self):
        # backfill_history.py iterates multiple competitions in a single
        # process; each competition's fetch_season() call must fold results
        # in under that competition's own COMP_KEY/COMP (sport-scoped), or a
        # school with both a football and basketball program (e.g. Kent
        # State) would blend the two sports' Elo into one shared bucket --
        # exactly the bug fixed for update_elo() itself this session
        # (see EloSportScopeTests in test_model_inputs.py).
        ncaam_games = [_match(f"cbbd-{i}", "Kent State", "Some Team", 80, 60,
                               f"2010-01-{i + 1:02d}T00:00:00Z", "h") for i in range(5)]
        ncaaf_games = [_match(f"cfbd-{i}", "Some Team", "Kent State", 40, 10,
                               f"2010-09-{i + 1:02d}T00:00:00Z", "h") for i in range(5)]
        by_comp = {"NCAAM": ncaam_games, "NCAAF": ncaaf_games}
        plan = {"NCAAM": [(2010, "x")], "NCAAF": [(2010, "x")]}
        with mock.patch.object(bh, "fetch_season",
                               side_effect=lambda comp, season, provider: by_comp[comp]):
            bh.run(["NCAAM", "NCAAF"], plan=plan)
        teams = fd._load_elo()["teams"]
        self.assertIn("basketball:kent state", teams)
        self.assertIn("football:kent state", teams)
        self.assertGreater(teams["basketball:kent state"]["r"], 1500)  # won every game
        self.assertLess(teams["football:kent state"]["r"], 1500)      # lost every game


if __name__ == "__main__":
    unittest.main()
