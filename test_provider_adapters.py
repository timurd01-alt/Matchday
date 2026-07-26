import datetime as dt
import unittest
import urllib.parse
from unittest import mock

from provider_adapters import (BallDontLieAdapter, CollegeBasketballDataAdapter,
                               CollegeFootballDataAdapter, NflverseAdapter, ProviderError,
                               SportsDataIOAdapter, SportmonksAdapter, normalized_score)


class ScoreNormalizationTests(unittest.TestCase):
    def test_only_final_scores_receive_a_winner(self):
        self.assertEqual(normalized_score(27, 20, True),
                         {"home": 27, "away": 20, "winner": "h"})
        self.assertEqual(normalized_score(20, 20, True),
                         {"home": 20, "away": 20, "winner": "d"})
        self.assertEqual(normalized_score(27, 20, False),
                         {"home": 27, "away": 20})


class SportsDataIOTests(unittest.TestCase):
    def setUp(self):
        self.payloads = {
            "/Games/": [{
                "GameID": 42, "DateTimeUTC": "2026-11-01T20:00:00Z", "Status": "InProgress",
                "HomeTeam": "BOS", "AwayTeam": "NYK", "HomeScore": 71, "AwayScore": 69,
                "Quarter": 3, "TimeRemaining": "04:12", "StadiumName": "Garden",
            }],
            "/Teams": [
                {"Key": "BOS", "FullName": "Boston Celtics"},
                {"Key": "NYK", "FullName": "New York Knicks"},
            ],
            "/Standings/": [
                {"Name": "Boston Celtics", "Team": "BOS", "Conference": "Eastern", "Division": "Atlantic",
                 "Wins": 10, "Losses": 2, "PointsFor": 1410, "PointsAgainst": 1280,
                 "ConferenceRank": 1, "Streak": 4},
                {"Name": "New York Knicks", "Team": "NYK", "Conference": "Eastern", "Division": "Atlantic",
                 "Wins": 8, "Losses": 4, "PointsFor": 1380, "PointsAgainst": 1320,
                 "ConferenceRank": 2, "Streak": -1},
            ],
            "/stats/json/Injuries": [
                {"Team": "BOS", "Name": "Example Player", "InjuryStatus": "Questionable"},
            ],
            "/stats/json/PlayerSeasonStats/": [
                {"Name": "Player One", "Games": 10, "Points": 300, "Rebounds": 90,
                 "Assists": 80, "BlockedShots": 20},
                {"Name": "Player Two", "Games": 10, "Points": 250, "Rebounds": 110,
                 "Assists": 60, "BlockedShots": 30},
            ],
        }

    def getter(self, url, headers):
        self.assertEqual(headers["Ocp-Apim-Subscription-Key"], "test-key")
        for marker, payload in self.payloads.items():
            if marker in url:
                return payload
        raise AssertionError(url)

    def test_schedule_normalizes_match_contract(self):
        adapter = SportsDataIOAdapter("test-key", "NBA", getter=self.getter)
        match = adapter.schedule()[0]
        self.assertEqual(match["home"]["name"], "Boston Celtics")
        self.assertEqual(match["status"], "LIVE")
        self.assertEqual(match["score"], {"home": 71, "away": 69})
        self.assertEqual(match["data_source"], "SportsDataIO")

    def test_standings_normalize_model_and_ui_contracts(self):
        adapter = SportsDataIOAdapter("test-key", "NBA", getter=self.getter)
        model, tables = adapter.standings()
        self.assertIn("boston celtics", model)
        self.assertEqual(tables[0]["group"], "Eastern Atlantic")
        self.assertEqual(tables[0]["teams"][0]["record"], "10-2")

    def test_availability_and_leaders_use_stats_product(self):
        adapter = SportsDataIOAdapter("test-key", "NBA", getter=self.getter)
        matches = adapter.schedule()
        self.assertEqual(adapter.attach_availability(matches), 1)
        self.assertIn("Questionable", matches[0]["injuries"]["home"][0])
        leaders = adapter.leaders()
        self.assertEqual(leaders["source"], "SportsDataIO")
        self.assertEqual(leaders["categories"][0]["leaders"][0]["value"], 30.0)

    def test_nhl_leaders_include_offense_and_defense_extras(self):
        # PlusMinus can be negative -- confirm a real leader (best plus/minus)
        # still ranks correctly and a worse-but-still-nonzero value doesn't
        # get treated as falsy/dropped.
        payloads = {
            "/stats/json/PlayerSeasonStats/": [
                {"Name": "Skater One", "Games": 20, "Points": 30, "Goals": 15, "Assists": 15,
                 "GoaltendingSavePercentage": 0, "PlusMinus": 12, "Hits": 40, "Takeaways": 22,
                 "ShotsOnGoal": 90},
                {"Name": "Skater Two", "Games": 20, "Points": 20, "Goals": 8, "Assists": 12,
                 "GoaltendingSavePercentage": 0, "PlusMinus": -4, "Hits": 60, "Takeaways": 10,
                 "ShotsOnGoal": 70},
            ],
        }
        def getter(url, headers):
            for marker, payload in payloads.items():
                if marker in url:
                    return payload
            raise AssertionError(url)
        adapter = SportsDataIOAdapter("test-key", "NHL", getter=getter)
        leaders = adapter.leaders()
        by_key = {c["key"]: c for c in leaders["categories"]}
        self.assertEqual(by_key["PlusMinus"]["leaders"][0]["name"], "Skater One")
        self.assertEqual(by_key["PlusMinus"]["leaders"][0]["value"], 12)
        self.assertEqual(by_key["Hits"]["leaders"][0]["name"], "Skater Two")


class NflverseAdapterTests(unittest.TestCase):
    def test_leaders_include_offense_and_defense_categories(self):
        rows = [
            {"player_id": "1", "player_display_name": "Passer One", "passing_yards": "3500",
             "passing_tds": "28", "rushing_yards": "0", "rushing_tds": "0",
             "receiving_yards": "0", "receiving_tds": "0", "def_sacks": "0",
             "def_interceptions": "0", "def_tackles_solo": "0", "def_tackles_for_loss": "0",
             "def_qb_hits": "0"},
            {"player_id": "2", "player_display_name": "Backer One", "passing_yards": "0",
             "passing_tds": "0", "rushing_yards": "0", "rushing_tds": "0",
             "receiving_yards": "0", "receiving_tds": "0", "def_sacks": "12.5",
             "def_interceptions": "3", "def_tackles_solo": "85", "def_tackles_for_loss": "14",
             "def_qb_hits": "20"},
            # team-level aggregate artifact row -- no player_id, must be dropped
            {"player_id": "", "player_display_name": "", "def_sacks": "999"},
        ]
        adapter = NflverseAdapter(getter=lambda url, headers: "\r\n".join(
            [",".join(rows[0].keys())] + [",".join(row.values()) for row in rows]
        ), today=dt.date(2026, 7, 25))
        leaders = adapter.leaders()
        by_key = {c["key"]: c for c in leaders["categories"]}
        self.assertEqual(by_key["PassingYards"]["leaders"][0]["name"], "Passer One")
        self.assertEqual(by_key["Sacks"]["leaders"][0]["name"], "Backer One")
        self.assertEqual(by_key["Sacks"]["leaders"][0]["value"], 12.5)
        self.assertEqual(by_key["TacklesForLoss"]["leaders"][0]["value"], 14)
        names = [entry["name"] for cat in leaders["categories"] for entry in cat["leaders"]]
        self.assertNotIn("", names)  # the aggregate artifact row never surfaces


class BallDontLieTests(unittest.TestCase):
    def getter(self, url, headers):
        self.assertEqual(headers["Authorization"], "test-key")
        self.assertIn("dates%5B%5D=", url)
        return {"data": [{
            "id": 501, "date": "2026-07-17T22:00:00.000Z", "season": 2026,
            "status": "STATUS_FINAL", "period": 9, "display_clock": "0:00",
            "venue": "Example Park", "season_type": "regular",
            "home_team": {"display_name": "Boston Red Sox", "abbreviation": "BOS"},
            "away_team": {"display_name": "New York Yankees", "abbreviation": "NYY"},
            "home_team_data": {"runs": 4}, "away_team_data": {"runs": 2},
        }], "meta": {"per_page": 100}}

    def test_free_games_normalize_without_inventing_paid_sections(self):
        adapter = BallDontLieAdapter("test-key", "MLB", getter=self.getter,
                                    today=dt.date(2026, 7, 17))
        match = adapter.schedule()[0]
        self.assertEqual(match["status"], "FINISHED")
        self.assertEqual(match["score"], {"home": 4, "away": 2, "winner": "h"})
        self.assertEqual(match["data_source"], "BALLDONTLIE")
        self.assertEqual(adapter.standings(), ({}, []))
        self.assertEqual(adapter.leaders(), {})

    def test_season_games_pages_through_results_and_drops_preseason(self):
        calls = []

        def paged_getter(url, headers):
            self.assertEqual(headers["Authorization"], "test-key")
            cursor = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query)).get("cursor")
            calls.append(cursor)
            if cursor is None:
                return {"data": [{
                    "id": 1, "date": "2026-04-01T22:00:00.000Z", "season": 2026,
                    "status": "STATUS_FINAL", "season_type": "preseason",
                    "home_team": {"display_name": "Boston Red Sox"},
                    "away_team": {"display_name": "New York Yankees"},
                    "home_team_data": {"runs": 1}, "away_team_data": {"runs": 0},
                }], "meta": {"next_cursor": "page2"}}
            return {"data": [{
                "id": 2, "date": "2026-05-01T22:00:00.000Z", "season": 2026,
                "status": "STATUS_FINAL", "season_type": "regular",
                "home_team": {"display_name": "Boston Red Sox"},
                "away_team": {"display_name": "New York Yankees"},
                "home_team_data": {"runs": 5}, "away_team_data": {"runs": 3},
            }], "meta": {}}

        adapter = BallDontLieAdapter("test-key", "MLB", getter=paged_getter,
                                    today=dt.date(2026, 7, 17))
        with mock.patch("provider_adapters.time.sleep") as sleep_mock:
            games = adapter.season_games()
        self.assertEqual(len(calls), 2)
        sleep_mock.assert_called_once_with(BallDontLieAdapter.SEASON_PAGE_DELAY_SEC)
        self.assertEqual(len(games), 1)
        self.assertEqual(games[0]["score"], {"home": 5, "away": 3, "winner": "h"})

    def test_season_games_recovers_from_a_single_transient_page_failure(self):
        calls = []

        def flaky_once_getter(url, headers):
            cursor = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query)).get("cursor")
            calls.append(cursor)
            if cursor is None:
                return {"data": [{
                    "id": 1, "date": "2026-05-01T22:00:00.000Z", "season": 2026,
                    "status": "STATUS_FINAL", "season_type": "regular",
                    "home_team": {"display_name": "Boston Red Sox"},
                    "away_team": {"display_name": "New York Yankees"},
                    "home_team_data": {"runs": 5}, "away_team_data": {"runs": 3},
                }], "meta": {"next_cursor": "page2"}}
            if calls.count("page2") == 1:  # fail once on page 2, then succeed
                raise ProviderError("429 rate limited")
            return {"data": [{
                "id": 2, "date": "2026-05-02T22:00:00.000Z", "season": 2026,
                "status": "STATUS_FINAL", "season_type": "regular",
                "home_team": {"display_name": "Cubs"}, "away_team": {"display_name": "Cardinals"},
                "home_team_data": {"runs": 2}, "away_team_data": {"runs": 1},
            }], "meta": {}}

        adapter = BallDontLieAdapter("test-key", "MLB", getter=flaky_once_getter,
                                    today=dt.date(2026, 7, 17))
        with mock.patch("provider_adapters.time.sleep"):
            games = adapter.season_games()
        # one retry consumed on page 2, so the getter saw it 3 times total (page1, page2 fail, page2 retry)
        self.assertEqual(len(calls), 3)
        self.assertEqual(len(games), 2)

    def test_season_games_raises_instead_of_caching_a_truncated_season(self):
        calls = []

        def always_fails_page2(url, headers):
            cursor = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query)).get("cursor")
            calls.append(cursor)
            if cursor is None:
                return {"data": [{
                    "id": 1, "date": "2026-05-01T22:00:00.000Z", "season": 2026,
                    "status": "STATUS_FINAL", "season_type": "regular",
                    "home_team": {"display_name": "Boston Red Sox"},
                    "away_team": {"display_name": "New York Yankees"},
                    "home_team_data": {"runs": 5}, "away_team_data": {"runs": 3},
                }], "meta": {"next_cursor": "page2"}}
            raise ProviderError("429 rate limited")

        adapter = BallDontLieAdapter("test-key", "MLB", getter=always_fails_page2,
                                    today=dt.date(2026, 7, 17))
        with mock.patch("provider_adapters.time.sleep"):
            with self.assertRaises(ProviderError):
                adapter.season_games()
        # page 1 (once) + page 2 (initial attempt + one retry, both failing)
        self.assertEqual(len(calls), 3)


class CollegeFootballDataTests(unittest.TestCase):
    def getter(self, url, headers):
        self.assertEqual(headers["Authorization"], "Bearer shared-key")
        if "/games?" in url:
            return [{"id": 7, "season": 2026, "week": 1, "seasonType": "regular",
                     "startDate": "2026-09-01T23:00:00Z", "completed": False,
                     "homeTeam": "Michigan", "homeConference": "Big Ten", "homePoints": None,
                     "awayTeam": "Ohio State", "awayConference": "Big Ten", "awayPoints": None,
                     "venue": "Example Stadium"}]
        if "/records?" in url:
            return [{"team": "Michigan", "conference": "Big Ten", "classification": "fbs",
                     "total": {"games": 1, "wins": 1, "losses": 0, "ties": 0},
                     "conferenceGames": {"games": 1, "wins": 1, "losses": 0}}]
        if "/rankings?" in url:
            return [{"season": 2026, "week": 1, "polls": [{"poll": "AP Top 25",
                     "ranks": [{"rank": 1, "school": "Michigan"}]}]}]
        raise AssertionError(url)

    def test_schedule_standings_and_rankings_contracts(self):
        adapter = CollegeFootballDataAdapter("shared-key", getter=self.getter,
                                             today=dt.date(2026, 7, 17))
        match = adapter.schedule()[0]
        model, tables = adapter.standings()
        ranks, projection = adapter.rankings(tables)
        self.assertEqual(match["data_source"], "CollegeFootballData")
        self.assertEqual(match["stage"], "Week 1")
        self.assertEqual(model["michigan"]["record"], "1-0")
        self.assertEqual(tables[0]["group"], "Big Ten")
        self.assertEqual(ranks[0]["name"], "Michigan")
        self.assertIsNone(projection)
        self.assertFalse(model["michigan"]["season_stale"])

    def test_reshape_player_stats_groups_rows_by_player(self):
        rows = [
            {"playerId": "1", "player": "Player A", "position": "QB", "team": "Michigan",
             "conference": "Big Ten", "category": "passing", "statType": "YDS", "stat": "3000"},
            {"playerId": "1", "player": "Player A", "position": "QB", "team": "Michigan",
             "conference": "Big Ten", "category": "passing", "statType": "TD", "stat": "25"},
        ]
        players = CollegeFootballDataAdapter._reshape_player_stats(rows)
        self.assertEqual(len(players), 1)
        entry = players["1"]
        self.assertEqual(entry["name"], "Player A")
        self.assertEqual(entry["team"], "Michigan")
        self.assertEqual(entry["stats"]["passing"]["YDS"], 3000)
        self.assertEqual(entry["stats"]["passing"]["TD"], 25)

    def test_leaders_reshapes_long_format_and_filters_to_fbs(self):
        # Regression: /stats/player/season has no working classification
        # filter of its own (it returns FCS/D2/D3 rows regardless of the
        # query param, same as /records before its per-row filter), so
        # leaders() must cross-check each player's team against a real FBS
        # team list -- otherwise a small-school stat leader with weak
        # competition (e.g. Tuskegee here) could out-rank actual FBS
        # leaders on the dashboard.
        def getter(url, headers):
            self.assertEqual(headers["Authorization"], "Bearer shared-key")
            if "/records?" in url:
                self.assertIn("year=2026", url)
                return [{"team": "Michigan", "classification": "fbs"},
                        {"team": "Tuskegee", "classification": "ii"}]
            if "/stats/player/season?" in url:
                self.assertIn("year=2026", url)
                return [
                    {"playerId": "1", "player": "Player A", "position": "QB", "team": "Michigan",
                     "conference": "Big Ten", "category": "passing", "statType": "YDS", "stat": "3000"},
                    {"playerId": "1", "player": "Player A", "position": "QB", "team": "Michigan",
                     "conference": "Big Ten", "category": "passing", "statType": "TD", "stat": "25"},
                    {"playerId": "2", "player": "Player B", "position": "RB", "team": "Michigan",
                     "conference": "Big Ten", "category": "rushing", "statType": "YDS", "stat": "1200"},
                    {"playerId": "3", "player": "Player X", "position": "QB", "team": "Tuskegee",
                     "conference": "SIAC", "category": "passing", "statType": "YDS", "stat": "5000"},
                    {"playerId": "4", "player": "Player C", "position": "LB", "team": "Michigan",
                     "conference": "Big Ten", "category": "defensive", "statType": "TOT", "stat": "90"},
                    {"playerId": "4", "player": "Player C", "position": "LB", "team": "Michigan",
                     "conference": "Big Ten", "category": "defensive", "statType": "SACKS", "stat": "8"},
                ]
            raise AssertionError(url)

        adapter = CollegeFootballDataAdapter("shared-key", getter=getter,
                                             today=dt.date(2026, 7, 17))
        leaders = adapter.leaders()
        self.assertEqual(leaders["source"], "CollegeFootballData")
        by_key = {c["key"]: c for c in leaders["categories"]}
        self.assertEqual(by_key["PassingYards"]["leaders"][0]["name"], "Player A")
        self.assertEqual(by_key["PassingYards"]["leaders"][0]["value"], 3000)
        names = [entry["name"] for entry in by_key["PassingYards"]["leaders"]]
        self.assertNotIn("Player X", names)  # non-FBS, excluded despite the higher raw total
        self.assertEqual(by_key["RushingYards"]["leaders"][0]["name"], "Player B")
        self.assertEqual(by_key["PassingTouchdowns"]["leaders"][0]["value"], 25)
        self.assertEqual(by_key["Tackles"]["leaders"][0]["name"], "Player C")
        self.assertEqual(by_key["Sacks"]["leaders"][0]["value"], 8)

    def test_standings_flags_prior_season_fallback_as_stale(self):
        # Regression: before the current season's games exist, CFBD's
        # /records for the new year comes back empty and the adapter falls
        # back to last season's FINAL record. That record used to be fed to
        # the model with no indication it was a year old, which let a P4
        # team's rough previous season dominate a true preseason matchup
        # over its actual (much larger) recruiting-talent edge.
        def getter(url, headers):
            if "/games?" in url:
                return []
            if "/records?" in url and "year=2026" in url:
                return []
            if "/records?" in url and "year=2025" in url:
                return [{"team": "Michigan State", "conference": "Big Ten", "classification": "fbs",
                         "total": {"games": 12, "wins": 4, "losses": 8, "ties": 0},
                         "conferenceGames": {"games": 9, "wins": 3, "losses": 6}}]
            raise AssertionError(url)
        adapter = CollegeFootballDataAdapter("shared-key", getter=getter,
                                             today=dt.date(2026, 7, 17))
        adapter.schedule()
        model, tables = adapter.standings()
        self.assertTrue(model["michigan state"]["season_stale"])
        self.assertTrue(tables[0]["teams"][0]["season_stale"])


class CollegeBasketballDataTests(unittest.TestCase):
    def getter(self, url, headers):
        self.assertEqual(headers["Authorization"], "Bearer shared-key")
        if url.endswith("/teams"):
            return [{"school": "Duke", "conference": "ACC"},
                    {"school": "North Carolina", "conference": "ACC"}]
        self.assertIn("/games?season=2026", url)
        return [{"id": 8, "season": 2026, "seasonType": "regular",
                 "startDate": "2026-01-10T20:00:00Z", "status": "final",
                 "homeTeam": "Duke", "homeConference": "ACC", "homePoints": 82,
                 "awayTeam": "North Carolina", "awayConference": "ACC", "awayPoints": 77,
                 "venue": "Example Arena"}]

    def test_games_derive_real_standings_and_top_25(self):
        adapter = CollegeBasketballDataAdapter("shared-key", getter=self.getter,
                                               today=dt.date(2026, 7, 17))
        match = adapter.schedule()[0]
        model, tables = adapter.standings()
        ranks, _ = adapter.rankings(tables)
        self.assertEqual(match["status"], "FINISHED")
        self.assertEqual(match["score"]["winner"], "h")
        self.assertEqual(match["data_source"], "CollegeBasketballData")
        self.assertEqual(model["duke"]["record"], "1-0")
        self.assertEqual(model["north carolina"]["record"], "0-1")
        self.assertEqual(ranks[0]["name"], "Duke")

    def test_leaders_computes_per_game_averages_for_d1_only(self):
        # CBBD's /stats/player/season is already one row per player (unlike
        # CFBD's long format), but it reports season totals, not per-game
        # rates, and includes non-Division-I programs -- both need handling
        # before the totals are leaderboard-ready.
        def getter(url, headers):
            self.assertEqual(headers["Authorization"], "Bearer shared-key")
            if url.endswith("/teams"):
                return [{"school": "Duke", "conference": "ACC"},
                        {"school": "Some JUCO", "conference": None}]
            self.assertIn("/stats/player/season?season=2026", url)
            return [
                {"name": "Player A", "team": "Duke", "games": 10, "points": 250,
                 "assists": 40, "blocks": 10, "rebounds": {"total": 90},
                 "steals": 25, "turnovers": 15},
                {"name": "Player B", "team": "Some JUCO", "games": 10, "points": 400,
                 "assists": 5, "blocks": 2, "rebounds": {"total": 30},
                 "steals": 50, "turnovers": 60},
            ]

        adapter = CollegeBasketballDataAdapter("shared-key", getter=getter,
                                               today=dt.date(2026, 7, 17))
        leaders = adapter.leaders()
        self.assertEqual(leaders["source"], "CollegeBasketballData")
        by_key = {c["key"]: c for c in leaders["categories"]}
        self.assertEqual(by_key["PointsPerGame"]["leaders"][0]["name"], "Player A")
        self.assertEqual(by_key["PointsPerGame"]["leaders"][0]["value"], 25.0)
        names = [entry["name"] for entry in by_key["PointsPerGame"]["leaders"]]
        self.assertNotIn("Player B", names)  # not a Division I team, excluded despite the higher raw total
        self.assertEqual(by_key["ReboundsPerGame"]["leaders"][0]["value"], 9.0)
        self.assertEqual(by_key["StealsPerGame"]["leaders"][0]["name"], "Player A")
        names_steals = [entry["name"] for entry in by_key["StealsPerGame"]["leaders"]]
        self.assertNotIn("Player B", names_steals)  # non-D1, excluded despite the higher raw total


class SportmonksTests(unittest.TestCase):
    def getter(self, url, headers):
        return {"data": [{
            "id": 99,
            "participants": [
                {"id": 1, "name": "Arsenal", "meta": {"location": "home"}},
                {"id": 2, "name": "Chelsea", "meta": {"location": "away"}},
            ],
            "statistics": [
                {"participant_id": 1, "type": {"code": "shots-total"}, "data": {"value": 12}},
                {"participant_id": 2, "type": {"code": "shots-total"}, "data": {"value": 8}},
            ],
            "lineups": [], "sidelined": [],
        }]}

    def test_enrichment_attaches_box_stats(self):
        matches = [{"kickoff": "2026-07-17T19:00:00Z", "status": "FINISHED",
                    "home": {"name": "Arsenal"}, "away": {"name": "Chelsea"},
                    "injuries": {"home": [], "away": []}}]
        adapter = SportmonksAdapter("test-key", getter=self.getter)
        attached = adapter.enrich(matches, lambda left, right: left.lower() == right.lower())
        self.assertEqual(attached, 1)
        self.assertEqual(matches[0]["stats_extra"]["home"]["shots"], 12)
        self.assertEqual(matches[0]["stats_extra"]["source"], "Sportmonks")


if __name__ == "__main__":
    unittest.main()
