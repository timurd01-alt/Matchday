"""The weekly export must only ever describe games that happen this week.

That is the failure this suite exists for. The handoff carries picks months
ahead -- when this was written, 72 picks of which 13 were for 12 September
through 28 November -- so any ranking that forgets to filter by date will
cheerfully put a Thanksgiving-weekend fixture on a post captioned "this week".
The tests below feed the exporter a fixture list built around a known clock and
assert the out-of-window games are gone.

Everything here is standard library, like the module it tests, so it runs in
deploy.yml's discovery with nothing installed.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import unittest

import social_export

# A Wednesday, matching the day this was first run, so the window under test is
# a partial week with games on both sides of its edges.
NOW = dt.datetime(2026, 9, 2, 21, 45, tzinfo=dt.timezone.utc)

RANKING_ROWS = [
    {"rank": 3, "team_name": "Notre Dame", "tier": "power", "conference": "Ind"},
    {"rank": 7, "team_name": "Ole Miss", "tier": "power", "conference": "SEC"},
    {"rank": 9, "team_name": "Utah", "tier": "power", "conference": "Big 12"},
    {"rank": 23, "team_name": "Louisville", "tier": "power", "conference": "ACC"},
    {"rank": 40, "team_name": "Wisconsin", "tier": "power", "conference": "Big Ten"},
    {"rank": 90, "team_name": "Boise State", "tier": "group_of_five", "conference": "MW"},
]
BY_NAME = {r["team_name"]: r for r in RANKING_ROWS}


def _pick(home, away, kickoff, model=60.0, market=55.0):
    return {"home": home, "away": away, "kickoff": kickoff, "pick_name": home,
            "model_pct": model, "market_pct": market, "edge_points": model - market}


DOCUMENT = {"picks": [
    _pick("Ole Miss", "Louisville", "2026-09-06T23:30:00Z"),        # in window, Sunday
    _pick("Notre Dame", "Wisconsin", "2026-09-06T23:30:00Z"),       # in window
    _pick("Utah", "Idaho", "2026-09-04T01:00:00Z"),                 # in window, Friday
    _pick("Louisville", "Boise State", "2026-09-07T23:00:00Z"),     # in window, Monday night
    _pick("Notre Dame", "Ole Miss", "2026-09-12T19:00:00Z"),        # NEXT week
    _pick("Utah", "Louisville", "2026-11-28T19:00:00Z"),            # Thanksgiving weekend
    _pick("Ole Miss", "Utah", "2026-09-02T18:00:00Z"),              # already kicked off today
    _pick("Wisconsin", "Boise State", "bad-timestamp"),             # unparseable
]}


class WeekWindow(unittest.TestCase):
    def test_window_runs_to_the_end_of_the_coming_monday(self):
        start, end = social_export.week_window(NOW)
        self.assertEqual(start, NOW)
        self.assertEqual(end.date(), dt.date(2026, 9, 7))
        self.assertEqual(end.weekday(), 0, "a college week ends on Monday")
        self.assertEqual((end.hour, end.minute), (23, 59))

    def test_on_a_monday_the_window_is_the_rest_of_that_day(self):
        """Monday's games are this week's, not next week's."""
        monday = dt.datetime(2026, 9, 7, 9, 0, tzinfo=dt.timezone.utc)
        start, end = social_export.week_window(monday)
        self.assertEqual(end.date(), monday.date())
        self.assertGreater(end, start)

    def test_on_a_tuesday_the_window_opens_a_fresh_week(self):
        tuesday = dt.datetime(2026, 9, 8, 9, 0, tzinfo=dt.timezone.utc)
        _start, end = social_export.week_window(tuesday)
        self.assertEqual(end.date(), dt.date(2026, 9, 14))


class WeeklyFiltering(unittest.TestCase):
    def setUp(self):
        self.games = social_export.weekly_games(
            DOCUMENT, BY_NAME, social_export.week_window(NOW))

    def test_only_this_weeks_games_survive(self):
        self.assertEqual(len(self.games), 4)

    def test_a_november_game_never_reaches_a_this_week_post(self):
        """The specific bug this module exists to prevent."""
        for game in self.games:
            self.assertLess(game["kickoff"], "2026-09-08",
                            "%s v %s is outside this week" % (game["home"], game["away"]))

    def test_next_weeks_game_is_excluded_even_though_it_is_the_best_matchup(self):
        """Notre Dame v Ole Miss on 12 September outscores everything in the
        window, so it is exactly what an unfiltered ranking would promote."""
        pairs = {(g["home"], g["away"]) for g in self.games}
        self.assertNotIn(("Notre Dame", "Ole Miss"), pairs)

    def test_a_game_already_kicked_off_is_excluded(self):
        pairs = {(g["home"], g["away"]) for g in self.games}
        self.assertNotIn(("Ole Miss", "Utah"), pairs)

    def test_an_unparseable_kickoff_is_dropped_not_crashed_on(self):
        pairs = {(g["home"], g["away"]) for g in self.games}
        self.assertNotIn(("Wisconsin", "Boise State"), pairs)

    def test_monday_night_game_is_kept(self):
        pairs = {(g["home"], g["away"]) for g in self.games}
        self.assertIn(("Louisville", "Boise State"), pairs)


class FanRanking(unittest.TestCase):
    def test_two_ranked_teams_beat_one_great_team_and_a_tune_up(self):
        """The whole point of weighting the weaker side.

        Ole Miss (#7) v Louisville (#23) must outrank Utah (#9) v an unrated
        opponent, even though Utah's own rank is better than Louisville's.
        """
        games = social_export.weekly_games(
            DOCUMENT, BY_NAME, social_export.week_window(NOW))
        order = [(g["home"], g["away"]) for g in games]
        self.assertLess(order.index(("Ole Miss", "Louisville")),
                        order.index(("Utah", "Idaho")))

    def test_a_plain_sum_would_get_it_wrong(self):
        """Documents why the formula is not the obvious one."""
        ole, _ = social_export.team_points("Ole Miss", BY_NAME)
        lou, _ = social_export.team_points("Louisville", BY_NAME)
        utah, _ = social_export.team_points("Utah", BY_NAME)
        cupcake, _ = social_export.team_points("Idaho", BY_NAME)
        self.assertEqual(cupcake, 0, "an unrated opponent contributes nothing")
        self.assertGreater(utah + cupcake, 0)
        self.assertLess(social_export.fan_score(utah, cupcake),
                        social_export.fan_score(ole, lou))

    def test_an_unranked_power_team_still_counts_for_something(self):
        wisconsin, rank = social_export.team_points("Wisconsin", BY_NAME)
        self.assertIsNone(rank, "rank 40 is outside the top 25")
        self.assertEqual(wisconsin, social_export.TIER_POINTS["power"])

    def test_power_outranks_group_of_five(self):
        wisconsin, _ = social_export.team_points("Wisconsin", BY_NAME)
        boise, _ = social_export.team_points("Boise State", BY_NAME)
        self.assertGreater(wisconsin, boise)


class UpsetSelection(unittest.TestCase):
    """An upset is a property of a game, not of the model's pick.

    Each game prices two sides and only one can be below even money, so there is
    exactly one upset candidate per game. Scoring the model's *chosen* side
    instead is the bug these tests pin: it hides the clearest upset on the
    board whenever the model picks the favourite while still rating the
    underdog far above the market.
    """

    TULSA = {
        "kickoff": "2026-09-05T19:45:00Z", "day": "Sat",
        "home": "Tulsa", "away": "Oklahoma State", "pick": "Oklahoma State",
        "model_pct": 56.9, "market_pct": 82.1,
        "sides": [
            {"selection": "Tulsa", "model_pct": 43.1, "market_pct": 17.9, "best_price": 5.6},
            {"selection": "Oklahoma State", "model_pct": 56.9, "market_pct": 82.1,
             "best_price": 1.18},
        ],
    }

    def test_the_underdog_is_found_even_when_the_model_picks_the_favourite(self):
        dog = social_export.underdog_side(self.TULSA)
        self.assertIsNotNone(dog)
        self.assertEqual(dog["selection"], "Tulsa")

    def test_a_game_the_old_pick_side_filter_dropped_is_now_the_top_upset(self):
        """The regression this rewrite exists for.

        The model picks Oklahoma State at 56.9%, whose market_pct is 82.1 -- so
        filtering on the picked side excluded the game entirely, losing a 25.2
        point disagreement about Tulsa.
        """
        upsets = social_export.weekly_upsets([self.TULSA], 3)
        self.assertEqual(len(upsets), 1)
        self.assertEqual(upsets[0]["underdog"], "Tulsa")
        self.assertAlmostEqual(upsets[0]["disagreement_points"], 25.2, places=1)
        self.assertGreaterEqual(self.TULSA["market_pct"], 50,
                                "the picked side is the market favourite, which is the point")

    def test_exactly_one_candidate_per_game(self):
        upsets = social_export.weekly_upsets([self.TULSA, self.TULSA], 10)
        self.assertEqual(len(upsets), 2, "one per game, never one per side")

    def test_the_model_must_like_the_underdog_more_than_the_market_does(self):
        agreeing = dict(self.TULSA, sides=[
            {"selection": "Tulsa", "model_pct": 12.0, "market_pct": 17.9},
            {"selection": "Oklahoma State", "model_pct": 88.0, "market_pct": 82.1},
        ])
        self.assertEqual(social_export.weekly_upsets([agreeing], 3), [])

    def test_a_pick_em_game_has_no_underdog(self):
        even = dict(self.TULSA, sides=[
            {"selection": "A", "model_pct": 60.0, "market_pct": 50.0},
            {"selection": "B", "model_pct": 40.0, "market_pct": 50.0},
        ])
        self.assertIsNone(social_export.underdog_side(even))

    def test_missing_or_partial_side_prices_are_skipped(self):
        self.assertIsNone(social_export.underdog_side({"sides": []}))
        self.assertIsNone(social_export.underdog_side(
            {"sides": [{"selection": "A", "model_pct": 40.0, "market_pct": 20.0}]}))
        self.assertIsNone(social_export.underdog_side({"sides": [
            {"selection": "A", "model_pct": None, "market_pct": 20.0},
            {"selection": "B", "model_pct": 60.0, "market_pct": 80.0}]}))

    def test_upsets_are_ranked_by_the_size_of_the_disagreement(self):
        small = dict(self.TULSA, kickoff="2026-09-05T00:00:00Z", sides=[
            {"selection": "Dog", "model_pct": 30.0, "market_pct": 25.0},
            {"selection": "Fav", "model_pct": 70.0, "market_pct": 75.0}])
        ranked = social_export.weekly_upsets([small, self.TULSA], 5)
        self.assertEqual([u["underdog"] for u in ranked], ["Tulsa", "Dog"])

    def test_upsets_inherit_the_weekly_date_filter(self):
        """Derived from the already-filtered list, so a November game cannot
        appear here even though the handoff's own upset block looks ahead on
        its own clock."""
        games = social_export.weekly_games(
            DOCUMENT, BY_NAME, social_export.week_window(NOW))
        for upset in social_export.weekly_upsets(games, 5):
            self.assertLess(upset["kickoff"], "2026-09-08")


class BriefRendering(unittest.TestCase):
    def test_brief_states_what_was_excluded(self):
        payload = {
            "week": {"from": "2026-09-02T21:45Z", "to": "2026-09-07T23:59Z",
                     "games_in_window": 59, "picks_in_handoff": 72},
            "ranking_published_on": "2026-08-31", "basis": "Opponent-adjusted scoring margin",
            "top25": [{"rank": 1, "team": "Indiana", "rating": 23.1,
                       "conference": "Big Ten", "sos": 6.0, "record": "0-0"}],
            "slate": [], "upsets": [],
        }
        text = social_export.brief(payload)
        self.assertIn("59 of 72", text, "the brief must say how many games were excluded")
        self.assertIn("2026-09-07", text)

    def test_no_upsets_says_so_rather_than_showing_an_empty_heading(self):
        payload = {
            "week": {"from": "a", "to": "b", "games_in_window": 0, "picks_in_handoff": 0},
            "ranking_published_on": "x", "basis": "y",
            "top25": [], "slate": [], "upsets": [],
        }
        self.assertIn("No game this week", social_export.brief(payload))




class GeneratedGraphicsData(unittest.TestCase):
    """social/weekly-data.js must be generated, and must agree with the export.

    It was hand-written, and it had rotted exactly the way hand-written data
    does: a slate of five games of which two were not in the schedule at all and
    two were one and two weeks away, plus an upset left over from a superseded
    definition. These tests assert the file is machine-written and that its
    numbers match what the exporter says today.
    """

    JS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "social", "weekly-data.js")

    def _payload(self):
        with open(self.JS, encoding="utf-8") as handle:
            text = handle.read()
        match = re.search(r"window\.MATCHDAY_SOCIAL = (.*);\s*$", text, re.S)
        self.assertIsNotNone(match, "weekly-data.js is not in the expected shape")
        return json.loads(match.group(1)), text

    @unittest.skipUnless(os.path.exists(JS), "social/weekly-data.js is absent")
    def test_it_is_marked_generated_so_nobody_hand_edits_it_again(self):
        _data, text = self._payload()
        self.assertIn("GENERATED by social_export.py", text)

    @unittest.skipUnless(os.path.exists(JS), "social/weekly-data.js is absent")
    def test_it_carries_a_full_top25_and_a_slate(self):
        data, _text = self._payload()
        self.assertEqual(len(data["top25"]), 25)
        self.assertTrue(data["slate"])
        for row in data["top25"]:
            self.assertEqual(len(row), 2, "graphics.js reads [name, rating] pairs")
            self.assertIsInstance(row[1], (int, float), "rating must be numeric for toFixed")

    @unittest.skipUnless(os.path.exists(JS), "social/weekly-data.js is absent")
    def test_every_field_graphics_js_reads_is_present(self):
        """A missing field is not a blank on the canvas, it is a thrown
        exception -- graphics.js calls .toUpperCase() and .toFixed() directly."""
        data, _text = self._payload()
        for key in ("week", "published", "logos", "top25", "upset", "slate"):
            self.assertIn(key, data)
        for key in ("underdog", "favorite", "modelPct", "marketPct", "kickoff", "note"):
            self.assertIn(key, data["upset"])
        for game in data["slate"]:
            for key in ("rank", "away", "home", "time", "hook"):
                self.assertIn(key, game)
            self.assertTrue(game["hook"], "hook is drawn with .toUpperCase()")


class ShortNames(unittest.TestCase):
    def test_mascots_are_stripped(self):
        self.assertEqual(social_export.short_name("Notre Dame Fighting Irish"), "Notre Dame")
        self.assertEqual(social_export.short_name("Tulsa Golden Hurricane"), "Tulsa")
        self.assertEqual(social_export.short_name("Ohio State Buckeyes"), "Ohio State")

    def test_a_name_with_no_known_mascot_is_left_alone(self):
        self.assertEqual(social_export.short_name("Stanford Cardinal"), "Stanford")
        self.assertEqual(social_export.short_name("Idaho"), "Idaho")


class WeekLabel(unittest.TestCase):
    def test_it_falls_back_to_a_date_rather_than_guessing_a_number(self):
        """A wrong week number on a graphic is worse than no week number."""
        import unittest.mock as mock
        with mock.patch("builtins.open", side_effect=OSError):
            label = social_export.week_label(social_export.week_window(NOW))
        self.assertTrue(label.startswith("WEEK OF "), label)

if __name__ == "__main__":
    unittest.main()
