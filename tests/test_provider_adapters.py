import datetime as dt
import unittest

from provider_adapters import (CollegeBasketballDataAdapter,
                               CollegeFootballDataAdapter, ProviderError,
                               SportsDataIOAdapter, SportsGameOddsAdapter,
                               _iso_utc, normalized_score)


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

    def test_unqualified_et_uses_daylight_saving_time(self):
        self.assertEqual(_iso_utc("2026-07-04T13:00:00"), "2026-07-04T17:00:00Z")
        self.assertEqual(_iso_utc("2026-12-04T13:00:00"), "2026-12-04T18:00:00Z")


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
        adapter = SportsGameOddsAdapter("test-key", "NCAAM", getter=lambda *_: {})
        result = adapter.attach_pregame(
            [match], [self.event()], observed_at="2026-08-08T12:00:00Z")
        self.assertEqual(result, {"markets": 1, "venues": 1})
        self.assertEqual(match["venue"], "Example Garden")
        self.assertIsNone(match["lineups"])
        self.assertFalse(any(match["injuries"].values()))
        self.assertNotIn("players", match)

    def test_same_team_doubleheader_requires_exact_event_time(self):
        first = self.event()
        first.update({"eventID": "dh-1", "startsAt": "2026-08-12T17:00:00Z"})
        second = self.event()
        second.update({"eventID": "dh-2", "startsAt": "2026-08-12T23:00:00Z"})
        match = {"id": "local-2", "kickoff": "2026-08-12T23:00:00Z",
                 "home": {"name": "Boston Celtics", "code": "BOS"},
                 "away": {"name": "New York Knicks", "code": "NYK"},
                 "markets": {}, "lineups": None}
        adapter = SportsGameOddsAdapter("test-key", "NCAAM", getter=lambda *_: {})
        adapter.attach_pregame([match], [first, second], observed_at="2026-08-12T12:00:00Z")
        receipt = match["pregame_provenance"][0]["join"]
        self.assertEqual(receipt["strategy"], "teams_and_start_time")
        self.assertEqual(receipt["provider_event_id"], "dh-2")

        ambiguous = {**match, "id": "local-x", "kickoff": "2026-08-12T20:00:00Z",
                     "markets": {}, "pregame_provenance": []}
        adapter.attach_pregame([ambiguous], [first, second], observed_at="2026-08-12T12:00:00Z")
        self.assertFalse(ambiguous["markets"])
        self.assertEqual(ambiguous["pregame_provenance"][0]["join"]["reason"],
                         "ambiguous_same_team_fixture")

    def test_start_time_is_read_from_the_live_payload_shape(self):
        # The provider carries kickoff on `status`, not at the top level and
        # not on `info` (which holds only venue metadata). Reading the wrong
        # field returned None for every real event and silently disabled the
        # teams_and_start_time join.
        event = self.event()
        event.pop("startsAt", None)
        event["info"] = {"venue": {"name": "American Family Field"}}
        event["status"] = {"startsAt": "2026-08-20T18:10:00.000Z", "started": False}
        self.assertEqual(SportsGameOddsAdapter._event_time(event),
                         "2026-08-20T18:10:00Z")

    def test_doubleheader_is_separated_using_the_live_payload_shape(self):
        first = self.event()
        first.pop("startsAt", None)
        first.update({"eventID": "dh-1",
                      "status": {"startsAt": "2026-08-12T17:00:00.000Z"}})
        second = self.event()
        second.pop("startsAt", None)
        second.update({"eventID": "dh-2",
                       "status": {"startsAt": "2026-08-12T23:00:00.000Z"}})
        match = {"id": "local-3", "kickoff": "2026-08-12T23:00:00Z",
                 "home": {"name": "Boston Celtics", "code": "BOS"},
                 "away": {"name": "New York Knicks", "code": "NYK"},
                 "markets": {}, "lineups": None}
        adapter = SportsGameOddsAdapter("test-key", "NCAAM", getter=lambda *_: {})
        adapter.attach_pregame([match], [first, second], observed_at="2026-08-12T12:00:00Z")
        receipt = match["pregame_provenance"][0]["join"]
        self.assertEqual(receipt["strategy"], "teams_and_start_time")
        self.assertEqual(receipt["provider_event_id"], "dh-2")

    def test_usage_gate_refuses_event_call_before_monthly_reserve(self):
        calls = []
        def getter(url, headers):
            calls.append(url)
            return {"data": {"rateLimits": {"per-month": {
                "max-entities": 2500, "current-entities": 2395,
            }}}}
        adapter = SportsGameOddsAdapter("test-key", "NCAAM", getter=getter)
        with self.assertRaisesRegex(ProviderError, "reserve reached"):
            adapter.upcoming_events("2026-08-08T00:00:00Z", "2026-08-09T12:00:00Z")
        self.assertEqual(len(calls), 1)
        self.assertIn("/account/usage", calls[0])

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

    def test_availability_maps_cross_provider_team_name_not_only_short_code(self):
        adapter = SportsDataIOAdapter("test-key", "NCAAM", getter=self.getter)
        matches = [{"home": {"name": "Boston Celtics", "code": "B"},
                    "away": {"name": "New York Knicks", "code": "N"},
                    "personnel": {}}]
        self.assertEqual(adapter.attach_availability(matches), 1)
        self.assertEqual(matches[0]["personnel"]["injury_details"]["home"][0]["name"],
                         "Example Player")

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
        self.assertEqual(ranks[0]["poll_name"], "AP Top 25")
        self.assertIsNone(projection)
        self.assertFalse(model["michigan"]["season_stale"])

    def test_full_poll_builds_projection_without_sportsdataio(self):
        # Short test polls never exercised the helper used by a real Top 25.
        for count in (11, 12, 25):
            with self.subTest(count=count):
                calls = []
                def getter(url, headers):
                    calls.append(url)
                    self.assertIn("api.collegefootballdata.com/rankings?", url)
                    return [{"season": 2026, "week": 3, "polls": [{
                        "poll": "AP Top 25",
                        "ranks": [{"rank": i, "school": f"College {i}"}
                                  for i in range(1, count + 1)],
                    }]}]
                adapter = CollegeFootballDataAdapter(
                    "shared-key", getter=getter, today=dt.date(2026, 9, 18))
                ranks, projection = adapter.rankings([])
                self.assertEqual(len(ranks), count)
                if count < 12:
                    self.assertIsNone(projection)
                else:
                    first_round, quarterfinals = projection
                    self.assertIn("model projection", first_round["round"])
                    self.assertEqual(
                        [(m["home"], m["away"]) for m in first_round["matches"]],
                        [(f"({a}) College {a}", f"({b}) College {b}")
                         for a, b in ((5, 12), (6, 11), (7, 10), (8, 9))])
                    self.assertEqual([m["home"] for m in quarterfinals["matches"]],
                                     [f"({i}) College {i}" for i in range(1, 5)])
                self.assertEqual(adapter.rankings([]), (ranks, projection))
                self.assertEqual(len(calls), 1)

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
        self.assertTrue(all(row["poll_name"] == "AP Top 25" for row in ranks))

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


if __name__ == "__main__":
    unittest.main()
