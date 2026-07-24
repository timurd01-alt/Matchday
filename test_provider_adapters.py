import datetime as dt
import unittest
import urllib.parse
from unittest import mock

from provider_adapters import (BallDontLieAdapter, CollegeBasketballDataAdapter,
                               CollegeFootballDataAdapter, ProviderError,
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

    def test_season_games_keeps_partial_results_after_a_later_page_fails(self):
        calls = []

        def flaky_getter(url, headers):
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

        adapter = BallDontLieAdapter("test-key", "MLB", getter=flaky_getter,
                                    today=dt.date(2026, 7, 17))
        with mock.patch("provider_adapters.time.sleep"):
            games = adapter.season_games()
        self.assertEqual(len(calls), 2)
        self.assertEqual(len(games), 1)


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
