import csv
import datetime as dt
import gzip
import io
import unittest
import urllib.parse
from unittest import mock

from provider_adapters import (BallDontLieAdapter, BigBallsSportsAdapter,
                               CollegeBasketballDataAdapter,
                               CollegeFootballDataAdapter, NflverseAdapter,
                               NflversePregameAdapter, ProviderError,
                               SportsDataIOAdapter, SportsGameOddsAdapter, SportmonksAdapter,
                               normalized_score)


class ShortCodeTests(unittest.TestCase):
    def test_michigan_state_is_msu_not_ms(self):
        from provider_adapters import _short_code
        self.assertEqual(_short_code("Michigan State"), "MSU")

    def test_state_schools_dont_collide_on_shared_initials(self):
        # The generic first-letter algorithm reduces both of these to "MS" --
        # a real collision, not just an unfamiliar abbreviation.
        from provider_adapters import _short_code
        self.assertNotEqual(_short_code("Michigan State"), _short_code("Mississippi State"))


class ScoreNormalizationTests(unittest.TestCase):
    def test_only_final_scores_receive_a_winner(self):
        self.assertEqual(normalized_score(27, 20, True),
                         {"home": 27, "away": 20, "winner": "h"})
        self.assertEqual(normalized_score(20, 20, True),
                         {"home": 20, "away": 20, "winner": "d"})
        self.assertEqual(normalized_score(27, 20, False),
                         {"home": 27, "away": 20})


class BigBallsSportsTests(unittest.TestCase):
    def setUp(self):
        self.rows = [{
            "player": {"id": "p1", "name": "Current Star",
                       "team": {"name": "Boston Celtics", "abbreviation": "BOS"}},
            "status": "Out", "injury_type": "Knee",
            "return_date": "2026-12-01", "updated_at": "2026-10-20T12:00:00Z",
        }, {
            "player": {"id": "p2", "name": "Recovered Player",
                       "team": {"name": "Boston Celtics", "abbreviation": "BOS"}},
            "status": "Out", "injury_type": "Ankle",
            "return_date": "2026-10-01", "updated_at": "2026-09-15T12:00:00Z",
        }, {
            "player": {"id": "p3", "name": "Away Doubt",
                       "team": {"name": "New York Knicks", "abbreviation": "NYK"}},
            "status": "Questionable", "injury_type": "Illness",
            "return_date": None, "updated_at": "2026-10-20T12:00:00Z",
        }]

    def getter(self, url, headers):
        self.assertIn("/v1/injuries?sport=basketball", url)
        self.assertEqual(headers["Authorization"], "Bearer test-key")
        return {"data": {"sport": "basketball", "injuries": self.rows}}

    @staticmethod
    def match():
        return {"id": "game-1", "kickoff": "2026-10-25T23:00:00Z",
                "home": {"name": "Boston Celtics", "code": "BOS"},
                "away": {"name": "New York Knicks", "code": "NYK"},
                "injuries": {"home": [], "away": []}}

    def test_active_reports_attach_by_team_and_expired_return_is_excluded(self):
        match = self.match()
        count = BigBallsSportsAdapter("test-key", "NBA", getter=self.getter).attach_availability(
            [match], observed_at="2026-10-20T12:00:00Z")
        self.assertEqual(count, 2)
        self.assertEqual(match["injuries"]["home"], ["Current Star (Out - Knee)"])
        self.assertEqual(match["injuries"]["away"], ["Away Doubt (Questionable - Illness)"])
        self.assertTrue(match["personnel"]["injuries_feed_checked"])
        self.assertTrue(match["personnel"]["injuries_confirmed"])
        self.assertEqual(match["pregame_provenance"][0]["source"], "Big Balls Sports Data")

    def test_successful_empty_report_still_marks_feed_checked(self):
        match = self.match()
        adapter = BigBallsSportsAdapter("test-key", "NHL", getter=lambda *_: {"data": {"injuries": []}})
        self.assertEqual(adapter.attach_availability([match]), 0)
        self.assertTrue(match["personnel"]["injuries_feed_checked"])
        self.assertFalse(any(match["injuries"].values()))

    def test_unsupported_injury_sport_is_rejected_instead_of_faked(self):
        with self.assertRaises(ProviderError):
            BigBallsSportsAdapter("test-key", "MLB", getter=self.getter)


class SportsGameOddsTests(unittest.TestCase):
    @staticmethod
    def _odd(side, prices, draw=False):
        return {
            "statID": "points", "statEntityID": "all" if side == "draw" else side,
            "periodID": "reg" if draw else "game",
            "betTypeID": "ml3way" if draw else "ml", "sideID": side,
            "byBookmaker": {book: {"odds": price, "available": True}
                            for book, price in prices.items()},
        }

    def event(self):
        return {
            "eventID": "sgo-1",
            "teams": {
                "home": {"teamID": "BOSTON_CELTICS_NBA",
                         "names": {"long": "Boston Celtics", "short": "BOS"}},
                "away": {"teamID": "NEW_YORK_KNICKS_NBA",
                         "names": {"long": "New York Knicks", "short": "NYK"}},
            },
            "info": {"venue": "Example Garden"},
            # Players tied to props are intentionally ignored by the adapter.
            "players": {"p1": {"name": "A Player", "teamID": "BOSTON_CELTICS_NBA"}},
            "odds": {
                "home": self._odd("home", {"fanduel": "+110", "betmgm": "+105",
                                             "espnbet": "-500"}),
                "away": self._odd("away", {"fanduel": "-120", "betmgm": "-115",
                                             "espnbet": "+350"}),
            },
        }

    def test_consensus_excludes_espn_and_removes_each_books_overround(self):
        market = SportsGameOddsAdapter.market(
            self.event(), observed_at="2026-08-08T12:00:00Z")
        self.assertEqual(market["books"], 2)
        self.assertTrue(market["espn_excluded"])
        self.assertEqual(market["home_pct"] + market["away_pct"], 100)
        self.assertEqual(market["source"], "SportsGameOdds consensus")

    def test_prop_players_are_not_mislabeled_as_lineups_or_injuries(self):
        match = {
            "id": "m1", "home": {"name": "Boston Celtics", "code": "BOS"},
            "away": {"name": "New York Knicks", "code": "NYK"},
            "markets": {}, "injuries": {"home": [], "away": []}, "lineups": None,
        }
        adapter = SportsGameOddsAdapter("test-key", "NBA", getter=lambda *_: {})
        result = adapter.attach_pregame(
            [match], [self.event()], observed_at="2026-08-08T12:00:00Z")
        self.assertEqual(result, {"markets": 1, "venues": 1})
        self.assertEqual(match["venue"], "Example Garden")
        self.assertIsNone(match["lineups"])
        self.assertFalse(any(match["injuries"].values()))
        self.assertNotIn("players", match)

    def test_mlb_player_markets_attach_only_unconfirmed_inferences(self):
        home_ids = [f"HOME_{i}_MLB" for i in range(1, 8)]
        away_ids = [f"AWAY_{i}_MLB" for i in range(1, 8)]
        players = {
            **{player_id: {"name": f"Home Hitter {i}", "teamID": "BOSTON_RED_SOX_MLB"}
               for i, player_id in enumerate(home_ids, 1)},
            **{player_id: {"name": f"Away Hitter {i}", "teamID": "NEW_YORK_YANKEES_MLB"}
               for i, player_id in enumerate(away_ids, 1)},
            "HOME_P_MLB": {"name": "Home Pitcher", "teamID": "BOSTON_RED_SOX_MLB"},
            "AWAY_P_MLB": {"name": "Away Pitcher", "teamID": "NEW_YORK_YANKEES_MLB"},
        }
        odds = {
            "home": self._odd("home", {"fanduel": "+110", "espnbet": "-500"}),
            "away": self._odd("away", {"fanduel": "-120", "espnbet": "+350"}),
        }
        for player_id in home_ids + away_ids:
            odds["hit-" + player_id] = {
                "statID": "batting_hits", "playerID": player_id,
                "byBookmaker": {"fanduel": {"odds": "-110", "available": True}},
            }
        for player_id in ("HOME_P_MLB", "AWAY_P_MLB"):
            odds["pitch-" + player_id] = {
                "statID": "pitching_strikeouts", "playerID": player_id,
                "byBookmaker": {"draftkings": {"odds": "+100", "available": True}},
            }
        event = {
            "eventID": "mlb-1",
            "teams": {
                "home": {"teamID": "BOSTON_RED_SOX_MLB", "names": {"long": "Boston Red Sox"}},
                "away": {"teamID": "NEW_YORK_YANKEES_MLB", "names": {"long": "New York Yankees"}},
            },
            "players": players, "odds": odds,
        }
        match = {"id": "m1", "home": {"name": "Boston Red Sox", "code": "BOS"},
                 "away": {"name": "New York Yankees", "code": "NYY"},
                 "markets": {}, "lineups": None, "injuries": {"home": [], "away": []}}
        result = SportsGameOddsAdapter("test-key", "MLB", getter=lambda *_: {}).attach_pregame(
            [match], [event], observed_at="2026-08-12T12:00:00Z")
        self.assertEqual(result["starting_pitchers"], 2)
        self.assertEqual(result["lineups"], 1)
        self.assertEqual(match["personnel"]["starting_pitchers"]["home"]["name"],
                         "Home Pitcher")
        self.assertFalse(match["personnel"]["starting_pitchers_confirmed"])
        self.assertEqual(len(match["lineups"]["away"]["xi"]), 7)
        self.assertFalse(match["lineups"]["confirmed"])
        self.assertIn("not a batting order", match["lineups"]["basis"])
        self.assertFalse(any(match["injuries"].values()))

    def test_mlb_inference_rejects_espn_only_player_markets(self):
        event = {
            "teams": {"home": {"teamID": "HOME_MLB"}, "away": {"teamID": "AWAY_MLB"}},
            "players": {"P_MLB": {"name": "Pitcher", "teamID": "HOME_MLB"}},
            "odds": {"pitch": {"statID": "pitching_strikeouts", "playerID": "P_MLB",
                                "byBookmaker": {"espnbet": {"odds": "-110", "available": True}}}},
        }
        inferred = SportsGameOddsAdapter.mlb_personnel(event)
        self.assertEqual(inferred["starting_pitchers"], {})
        self.assertIsNone(inferred["lineups"])

    def test_usage_gate_refuses_event_call_before_monthly_reserve(self):
        calls = []
        def getter(url, headers):
            calls.append(url)
            return {"data": {"rateLimits": {"per-month": {
                "max-entities": 2500, "current-entities": 2395,
            }}}}
        adapter = SportsGameOddsAdapter("test-key", "MLB", getter=getter)
        with self.assertRaisesRegex(ProviderError, "reserve reached"):
            adapter.upcoming_events("2026-08-08T00:00:00Z", "2026-08-09T12:00:00Z")
        self.assertEqual(len(calls), 1)
        self.assertIn("/account/usage", calls[0])

    def test_ucl_market_requires_same_three_non_espn_books(self):
        event = self.event()
        event["odds"] = {
            "home": self._odd("home", {"fanduel": "+150", "betmgm": "+160"}, draw=True),
            "draw": self._odd("draw", {"fanduel": "+220", "betmgm": "+230"}, draw=True),
            "away": self._odd("away", {"fanduel": "+180", "betmgm": "+175"}, draw=True),
        }
        market = SportsGameOddsAdapter.market(event, has_draws=True)
        self.assertEqual(market["books"], 2)
        self.assertEqual(market["home_pct"] + market["draw_pct"] + market["away_pct"], 100)


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
            "/projections/json/InjuredPlayers": [
                {"Team": "BOS", "Name": "Example Player", "InjuryStatus": "Questionable"},
            ],
            "/stats/json/PlayerSeasonStats/": [
                {"Name": "Player One", "Games": 10, "Points": 300, "Rebounds": 90,
                 "Assists": 80, "BlockedShots": 20},
                {"Name": "Player Two", "Games": 10, "Points": 250, "Rebounds": 110,
                 "Assists": 60, "BlockedShots": 30},
            ],
            "/projections/json/StartingLineupsByDate/": [{
                "GameID": 42, "HomeTeam": "BOS", "AwayTeam": "NYK",
                "HomeLineup": [{"PlayerID": 1, "Name": "Home Starter", "Position": "PG",
                                "Starting": True, "Confirmed": True},
                               {"PlayerID": 3, "Name": "Home Bench", "Position": "SG",
                                "Starting": False, "Confirmed": True}],
                "AwayLineup": [{"PlayerID": 2, "Name": "Away Starter", "Position": "PG",
                                "Starting": True, "Confirmed": True}],
            }],
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
        self.assertIn("Questionable", matches[0]["injuries_shadow"]["home"][0])
        self.assertFalse(any(matches[0]["injuries"].values()))
        leaders = adapter.leaders()
        self.assertEqual(leaders["source"], "SportsDataIO")
        self.assertEqual(leaders["categories"][0]["leaders"][0]["value"], 30.0)

    def test_availability_maps_cross_provider_team_name_not_only_short_code(self):
        adapter = SportsDataIOAdapter("test-key", "NBA", getter=self.getter)
        matches = [{"home": {"name": "Boston Celtics", "code": "B"},
                    "away": {"name": "New York Knicks", "code": "N"},
                    "personnel": {}}]
        self.assertEqual(adapter.attach_availability(matches), 1)
        self.assertEqual(matches[0]["personnel"]["injury_details"]["home"][0]["name"],
                         "Example Player")

    def test_starting_lineups_are_normalized_with_confirmation(self):
        adapter = SportsDataIOAdapter("test-key", "NBA", getter=self.getter)
        rows = adapter.starting_lineups("2026-11-01")
        self.assertEqual(rows[0]["home"]["xi"][0]["name"], "Home Starter")
        self.assertEqual(len(rows[0]["home"]["xi"]), 1)
        self.assertTrue(rows[0]["confirmed"])

    def test_mlb_batting_lineups_and_pitchers_follow_official_schema(self):
        def getter(url, headers):
            if "/projections/json/StartingLineupsByDate/" in url:
                return [{"GameID": 7, "HomeTeam": "BOS", "AwayTeam": "NYY",
                         "HomeBattingLineup": [{"PlayerID": 1, "Name": "Home Batter",
                                                 "Starting": True, "Confirmed": True}],
                         "AwayBattingLineup": [{"PlayerID": 2, "Name": "Away Batter",
                                                 "Starting": True, "Confirmed": True}],
                         "HomeStartingPitcher": {"PlayerID": 3, "Name": "Home Pitcher",
                                                   "Confirmed": True},
                         "AwayStartingPitcher": {"PlayerID": 4, "Name": "Away Pitcher",
                                                   "Confirmed": False}}]
            raise AssertionError(url)
        row = SportsDataIOAdapter("test-key", "MLB", getter=getter).starting_lineups("2026-08-03")[0]
        self.assertEqual(row["home"]["xi"][0]["name"], "Home Batter")
        self.assertTrue(row["home_starting_pitcher"]["confirmed"])
        self.assertFalse(row["away_starting_pitcher"]["confirmed"])

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

    def test_nhl_starting_goalies_are_normalized(self):
        def getter(url, headers):
            if "/projections/json/StartingGoaltendersByDate/" in url:
                return [{"GameID": 9, "HomeTeam": "BOS", "AwayTeam": "NYR",
                         "HomeGoaltender": {"PlayerID": 1, "FirstName": "Home", "LastName": "Goalie",
                                             "Confirmed": True},
                         "AwayGoaltender": {"PlayerID": 2, "FirstName": "Away", "LastName": "Goalie",
                                             "Confirmed": False}}]
            raise AssertionError(url)
        rows = SportsDataIOAdapter("test-key", "NHL", getter=getter).starting_goalies("2026-OCT-10")
        self.assertEqual(rows[0]["home"]["name"], "Home Goalie")
        self.assertTrue(rows[0]["home"]["confirmed"])
        self.assertFalse(rows[0]["away"]["confirmed"])


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

    def test_pregame_snapshot_uses_newest_depth_chart_and_roster_status(self):
        depth_rows = [
            {"dt": "2026-08-09T07:00:00Z", "team": "SEA", "player_name": "Old QB",
             "gsis_id": "old", "pos_grp": "Offense", "pos_name": "Quarterback",
             "pos_abb": "QB", "pos_slot": "1", "pos_rank": "1"},
            {"dt": "2026-08-10T07:00:00Z", "team": "SEA", "player_name": "Current QB",
             "gsis_id": "new", "pos_grp": "Offense", "pos_name": "Quarterback",
             "pos_abb": "QB", "pos_slot": "1", "pos_rank": "1"},
            {"dt": "2026-08-10T07:00:00Z", "team": "SEA", "player_name": "Backup QB",
             "gsis_id": "backup", "pos_grp": "Offense", "pos_name": "Quarterback",
             "pos_abb": "QB", "pos_slot": "1", "pos_rank": "2"},
        ]
        roster_rows = [
            {"season": "2026", "team": "SEA", "position": "QB", "status": "ACT",
             "full_name": "Current QB", "gsis_id": "new", "week": "1",
             "status_description_abbr": "A01"},
            {"season": "2026", "team": "SEA", "position": "QB", "status": "RES",
             "full_name": "Current QB", "gsis_id": "new", "week": "2",
             "status_description_abbr": "R09"},
        ]

        def zipped(rows):
            buffer = io.StringIO(newline="")
            writer = csv.DictWriter(buffer, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
            return gzip.compress(buffer.getvalue().encode("utf-8"))

        def getter(url, headers):
            return zipped(roster_rows if "weekly_rosters" in url else depth_rows)

        snapshot = NflversePregameAdapter(
            getter=getter, today=dt.date(2026, 8, 11)).snapshot()
        self.assertEqual(snapshot["season"], 2026)
        self.assertEqual(snapshot["week"], 2)
        self.assertEqual(snapshot["observed_at"], "2026-08-10T07:00:00Z")
        self.assertEqual([p["name"] for p in snapshot["teams"]["SEA"]["starters"]],
                         ["Current QB"])
        self.assertEqual(snapshot["teams"]["SEA"]["starters"][0]["roster_status"], "RES")


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

    def test_postponed_game_resolves_to_finished_with_no_fabricated_score(self):
        def postponed_getter(url, headers):
            return {"data": [{
                "id": 502, "date": "2026-07-19T00:08:00.000Z", "season": 2026,
                "status": "STATUS_POSTPONED", "period": None, "display_clock": None,
                "venue": "Yankee Stadium", "season_type": "regular",
                "home_team": {"display_name": "New York Yankees", "abbreviation": "NYY"},
                "away_team": {"display_name": "Los Angeles Dodgers", "abbreviation": "LAD"},
                # BALLDONTLIE's schema still reports a numeric 0 for an unplayed
                # game rather than omitting the field -- naively trusting that
                # as a real score would grade a postponed game as a false 0-0.
                "home_team_data": {"runs": 0}, "away_team_data": {"runs": 0},
            }], "meta": {"per_page": 100}}

        adapter = BallDontLieAdapter("test-key", "MLB", getter=postponed_getter,
                                    today=dt.date(2026, 7, 26))
        match = adapter.schedule()[0]
        # Terminal (not UPCOMING forever), but with no real score to grade against.
        self.assertEqual(match["status"], "FINISHED")
        self.assertEqual(match["score"], {"home": None, "away": None})

    def test_placeholder_team_name_drops_the_game_instead_of_inventing_a_team(self):
        def placeholder_getter(url, headers):
            return {"data": [
                {
                    "id": 8712499, "date": "2026-07-15T00:00:00.000Z", "season": 2026,
                    "status": "STATUS_FINAL", "period": 9, "venue": "Citizens Bank Park",
                    "season_type": "regular",
                    "home_team": {"display_name": "Unknown", "abbreviation": "UNK"},
                    "away_team": {"display_name": "Unknown", "abbreviation": "UNK"},
                    "home_team_data": {"runs": 0}, "away_team_data": {"runs": 4},
                },
                {
                    "id": 503, "date": "2026-07-15T00:00:00.000Z", "season": 2026,
                    "status": "STATUS_FINAL", "period": 9, "venue": "Fenway Park",
                    "season_type": "regular",
                    "home_team": {"display_name": "Boston Red Sox", "abbreviation": "BOS"},
                    "away_team": {"display_name": "TBD", "abbreviation": ""},
                    "home_team_data": {"runs": 3}, "away_team_data": {"runs": 1},
                },
            ], "meta": {"per_page": 100}}

        adapter = BallDontLieAdapter("test-key", "MLB", getter=placeholder_getter,
                                    today=dt.date(2026, 7, 15))
        # A placeholder is not a resolvable club: crediting it created a 31st
        # MLB "team" in the standings table and a real Elo entry trained on
        # real results, so both rows are dropped at the provider boundary.
        self.assertEqual(adapter.schedule(), [])

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

    def test_historical_season_uses_seasons_filter_and_pages_to_completion(self):
        # backfill_history.py's one-time historical pull, distinct from
        # season_games()'s date-window approach used by the hourly build().
        # Live-verified 2026-07-26 that BALLDONTLIE's `seasons[]` filter
        # returns a real season in full via cursor pagination (2010 NFL:
        # exactly 267 games over 3 pages) -- this test pins that contract.
        calls = []

        def paged_getter(url, headers):
            qs = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))
            self.assertEqual(qs.get("seasons[]"), "2010")
            cursor = qs.get("cursor")
            calls.append(cursor)
            if cursor is None:
                return {"data": [{
                    "id": 1, "date": "2010-09-10T00:30:00.000Z", "season": 2010,
                    "status": "STATUS_FINAL", "season_type": "regular",
                    "home_team": {"display_name": "New Orleans Saints"},
                    "visitor_team": {"display_name": "Minnesota Vikings"},
                    "home_team_score": 14, "visitor_team_score": 9,
                }], "meta": {"next_cursor": "page2"}}
            return {"data": [{
                "id": 2, "date": "2011-02-06T23:29:00.000Z", "season": 2010,
                "status": "STATUS_FINAL", "season_type": "postseason",
                "home_team": {"display_name": "Green Bay Packers"},
                "visitor_team": {"display_name": "Pittsburgh Steelers"},
                "home_team_score": 31, "visitor_team_score": 25,
            }], "meta": {}}

        adapter = BallDontLieAdapter("test-key", "NFL", getter=paged_getter)
        with mock.patch("provider_adapters.time.sleep") as sleep_mock:
            games = adapter.historical_season(2010)
        self.assertEqual(len(calls), 2)
        sleep_mock.assert_called_once_with(BallDontLieAdapter.SEASON_PAGE_DELAY_SEC)
        self.assertEqual(len(games), 2)
        self.assertEqual(games[0]["home"]["name"], "New Orleans Saints")
        self.assertEqual(games[0]["score"], {"home": 14, "away": 9, "winner": "h"})
        self.assertEqual(games[1]["score"], {"home": 31, "away": 25, "winner": "h"})

    def test_historical_season_drops_preseason_like_season_games(self):
        def getter(url, headers):
            return {"data": [{
                "id": 1, "date": "2019-08-01T00:00:00.000Z", "season": 2019,
                "status": "STATUS_FINAL", "season_type": "preseason",
                "home_team": {"display_name": "Boston Red Sox"},
                "away_team": {"display_name": "New York Yankees"},
                "home_team_score": 1, "visitor_team_score": 0,
            }], "meta": {}}
        adapter = BallDontLieAdapter("test-key", "MLB", getter=getter)
        with mock.patch("provider_adapters.time.sleep"):
            games = adapter.historical_season(2019)
        self.assertEqual(games, [])

    def test_historical_season_recovers_from_a_single_transient_page_failure(self):
        calls = []

        def flaky_once_getter(url, headers):
            cursor = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query)).get("cursor")
            calls.append(cursor)
            if cursor is None:
                return {"data": [{
                    "id": 1, "date": "2015-09-01T00:00:00.000Z", "season": 2015,
                    "status": "STATUS_FINAL", "season_type": "regular",
                    "home_team": {"display_name": "Boston Celtics"},
                    "visitor_team": {"display_name": "New York Knicks"},
                    "home_team_score": 100, "visitor_team_score": 90,
                }], "meta": {"next_cursor": "page2"}}
            if calls.count("page2") == 1:
                raise ProviderError("429 rate limited")
            return {"data": [{
                "id": 2, "date": "2015-09-02T00:00:00.000Z", "season": 2015,
                "status": "STATUS_FINAL", "season_type": "regular",
                "home_team": {"display_name": "Chicago Bulls"},
                "visitor_team": {"display_name": "Miami Heat"},
                "home_team_score": 95, "visitor_team_score": 90,
            }], "meta": {}}

        adapter = BallDontLieAdapter("test-key", "NBA", getter=flaky_once_getter)
        with mock.patch("provider_adapters.time.sleep"):
            games = adapter.historical_season(2015)
        self.assertEqual(len(calls), 3)
        self.assertEqual(len(games), 2)

    def test_historical_season_raises_instead_of_caching_a_truncated_season(self):
        def always_fails_page2(url, headers):
            cursor = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query)).get("cursor")
            if cursor is None:
                return {"data": [{
                    "id": 1, "date": "2015-09-01T00:00:00.000Z", "season": 2015,
                    "status": "STATUS_FINAL", "season_type": "regular",
                    "home_team": {"display_name": "Boston Celtics"},
                    "visitor_team": {"display_name": "New York Knicks"},
                    "home_team_score": 100, "visitor_team_score": 90,
                }], "meta": {"next_cursor": "page2"}}
            raise ProviderError("429 rate limited")

        adapter = BallDontLieAdapter("test-key", "NBA", getter=always_fails_page2)
        with mock.patch("provider_adapters.time.sleep"):
            with self.assertRaises(ProviderError):
                adapter.historical_season(2015)


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

    def test_standings_model_dict_gets_the_same_position_as_the_sorted_table(self):
        # Regression: `model[name]` used to be snapshotted via {**item, ...}
        # BEFORE the per-group sort assigned real positions, so every team's
        # `pos` in the model dict stayed frozen at the pre-sort None forever --
        # only the `tables` return value (a shared reference, mutated in
        # place) ever saw the real position. Confirmed live 2026-07-27:
        # fetch_data.py's standings builder reads position from `model`
        # (`st` there), so conference tables sorted by "pos or 99" put every
        # team at 99 and fell back to API response order -- observed as
        # standings that looked completely unordered.
        def getter(url, headers):
            if "/games?" in url:
                return []
            if "/records?" in url:
                return [
                    {"team": "Losing Tigers", "conference": "Big Ten", "classification": "fbs",
                     "total": {"games": 10, "wins": 2, "losses": 8, "ties": 0},
                     "conferenceGames": {"games": 8, "wins": 1, "losses": 7}},
                    {"team": "Winning Wolverines", "conference": "Big Ten", "classification": "fbs",
                     "total": {"games": 10, "wins": 9, "losses": 1, "ties": 0},
                     "conferenceGames": {"games": 8, "wins": 8, "losses": 0}},
                ]
            raise AssertionError(url)
        adapter = CollegeFootballDataAdapter("shared-key", getter=getter, today=dt.date(2026, 7, 17))
        model, tables = adapter.standings()
        teams = tables[0]["teams"]
        self.assertEqual(teams[0]["name"], "Winning Wolverines")
        self.assertEqual(teams[0]["pos"], 1)
        self.assertEqual(teams[1]["pos"], 2)
        # the fix under test: the model dict (built before sorting, in API
        # response order) must reflect the SAME final positions as the table
        self.assertEqual(model["winning wolverines"]["pos"], 1)
        self.assertEqual(model["losing tigers"]["pos"], 2)

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

    def test_offseason_with_no_poll_blends_prior_results_and_talent(self):
        # Regression, live user report 2026-07-26: falling back to last
        # season's postseason poll always succeeds once that poll happened
        # (it's historical), so this used to show an already-finished
        # season's final Top 25 for the ENTIRE off-season -- "the old season
        # no one cares about" -- instead of ever preferring a signal about
        # the season that's actually coming up. Zero completed games this
        # season is the real off-season signal; when no real poll exists
        # either (current or preseason), blend last year's performance with
        # recruiting talent in a new projection, clearly marked as one.
        def getter(url, headers):
            if "/games?" in url:
                return [{"id": 7, "season": 2027, "week": 1, "seasonType": "regular",
                         "startDate": "2026-09-01T23:00:00Z", "completed": False,
                         "homeTeam": "Michigan", "homeConference": "Big Ten", "homePoints": None,
                         "awayTeam": "Ohio State", "awayConference": "Big Ten", "awayPoints": None,
                         "venue": "Example Stadium"}]
            if "/rankings?" in url and "year=2026" in url:
                return []  # no real poll yet, current or preseason
            if "/rankings?" in url and "year=2025" in url:
                return [{"season": 2025, "week": 16, "polls": [{"poll": "AP Top 25", "ranks": [
                    {"rank": 1, "school": "Indiana"}, {"rank": 25, "school": "Boise State"},
                ]}]}]
            if "/talent?" in url:
                return [{"team": "Ohio State", "talent": 950.0}, {"team": "Michigan", "talent": 800.0}]
            raise AssertionError(url)
        adapter = CollegeFootballDataAdapter("shared-key", getter=getter,
                                             today=dt.date(2026, 7, 17))
        adapter.schedule()
        ranks, projection = adapter.rankings([])
        self.assertTrue(ranks[0]["projected"])
        names = [row["name"] for row in ranks]
        self.assertIn("Indiana", names)  # recent elite performance survives weak/absent talent rank
        self.assertLess(names.index("Indiana"), names.index("Michigan"))
        self.assertLess(names.index("Ohio State"), names.index("Boise State"))
        self.assertIsNone(projection)  # a projection never doubles as a real CFP seed

    def test_offseason_projection_falls_back_to_talent_when_final_poll_is_missing(self):
        def getter(url, headers):
            if "/rankings?" in url:
                return []
            if "/talent?" in url:
                return [{"team": "Ohio State", "talent": 950.0}, {"team": "Michigan", "talent": 800.0}]
            raise AssertionError(url)
        adapter = CollegeFootballDataAdapter("shared-key", getter=getter,
                                             today=dt.date(2026, 7, 17))
        ranks = adapter._projected_ranking()
        self.assertEqual([row["name"] for row in ranks], ["Ohio State", "Michigan"])

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
        if "/rankings" in url:
            self.assertIn("season=2026", url)
            return [
                {"season": 2026, "week": 1, "pollType": "AP Top 25", "ranking": 1, "team": "North Carolina"},
                {"season": 2026, "week": 1, "pollType": "AP Top 25", "ranking": None, "team": "Others receiving votes"},
                {"season": 2026, "week": 2, "pollType": "AP Top 25", "ranking": 1, "team": "Duke"},
                {"season": 2026, "week": 2, "pollType": "AP Top 25", "ranking": 2, "team": "North Carolina"},
                {"season": 2026, "week": 2, "pollType": "Coaches Poll", "ranking": 1, "team": "North Carolina"},
            ]
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
        # real AP Top 25 poll, latest week -- not a raw win-percentage sort
        # (which would have ranked both teams 1-0/0-1 arbitrarily by name/gd)
        self.assertEqual(ranks[0]["name"], "Duke")
        self.assertEqual(ranks[1]["name"], "North Carolina")

    def test_rankings_season_rolls_over_in_august(self):
        # CBBD numbers a season by its ENDING year -- a July date should
        # request the season that just concluded, but from August onward it
        # must request the following year's season, since the new season's
        # (not-yet-played) schedule/polls start appearing under that number.
        adapter_before = CollegeBasketballDataAdapter("shared-key", getter=self.getter,
                                                      today=dt.date(2026, 7, 31))
        self.assertEqual(adapter_before.season, 2026)

        def getter_2027(url, headers):
            if url.endswith("/teams"):
                return []
            self.assertIn("season=2027", url)
            return []
        adapter_after = CollegeBasketballDataAdapter("shared-key", getter=getter_2027,
                                                     today=dt.date(2026, 8, 1))
        self.assertEqual(adapter_after.season, 2027)
        adapter_after.schedule()

    def test_offseason_with_no_poll_blends_prior_results_and_recruiting(self):
        # Same off-season fix as CFBD: zero "final" games this season means
        # it hasn't started, so an empty current /rankings response should
        # blend last year's results with recruiting instead of displaying the
        # old final poll as though it were current.
        def getter(url, headers):
            if url.endswith("/teams"):
                return [{"school": "Duke", "conference": "ACC"}]
            if "/rankings" in url and "season=2026" in url:
                return []
            if "/rankings" in url and "season=2025" in url:
                return [
                    {"season": 2025, "week": 20, "pollType": "AP Top 25", "ranking": 1, "team": "Florida"},
                    {"season": 2025, "week": 20, "pollType": "AP Top 25", "ranking": 25, "team": "Memphis"},
                ]
            if "/recruiting/teams" in url:
                return [{"team": "Duke", "rating": 95.0}, {"team": "Gonzaga", "rating": 80.0}]
            self.assertIn("/games?season=2026", url)
            return [{"id": 8, "season": 2026, "seasonType": "regular",
                     "startDate": "2026-11-10T20:00:00Z", "status": "scheduled",
                     "homeTeam": "Duke", "homeConference": "ACC", "homePoints": None,
                     "awayTeam": "Gonzaga", "awayConference": "WCC", "awayPoints": None,
                     "venue": "Example Arena"}]
        adapter = CollegeBasketballDataAdapter("shared-key", getter=getter,
                                               today=dt.date(2026, 7, 17))
        adapter.schedule()
        ranks, projection = adapter.rankings([])
        self.assertTrue(ranks[0]["projected"])
        names = [row["name"] for row in ranks]
        self.assertIn("Florida", names)
        self.assertLess(names.index("Florida"), names.index("Gonzaga"))
        self.assertLess(names.index("Duke"), names.index("Memphis"))
        self.assertIsNone(projection)

    def test_basketball_projection_falls_back_to_recruiting_without_final_poll(self):
        def getter(url, headers):
            if "/rankings" in url:
                return []
            if "/recruiting/teams" in url:
                return [{"team": "Duke", "rating": 95.0}, {"team": "Gonzaga", "rating": 80.0}]
            raise AssertionError(url)
        adapter = CollegeBasketballDataAdapter("shared-key", getter=getter,
                                               today=dt.date(2026, 7, 17))
        ranks = adapter._projected_ranking()
        self.assertEqual([row["name"] for row in ranks], ["Duke", "Gonzaga"])

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
