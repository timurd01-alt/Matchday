"""The content engine must be able to say nothing, and must never say something stale.

Every test builds a synthetic handoff in a temporary directory around a fixed
clock, so the suite never depends on whatever trdlab_picks.json happens to be
committed today. Standard library only, like the module under test.
"""
from __future__ import annotations

import base64
import copy
import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path

import content_engine as ce
import trdlab_handoff

# Wednesday 4 November 2026: the football week runs to Monday 9 November.
NOW = dt.datetime(2026, 11, 4, 15, 0, tzinfo=dt.timezone.utc)
TEAMS = [
    "Notre Dame Fighting Irish", "Miami Hurricanes", "Ohio State Buckeyes", "Indiana Hoosiers",
    "Georgia Bulldogs", "Alabama Crimson Tide", "LSU Tigers", "Ole Miss Rebels", "Utah Utes",
    "Texas Longhorns", "Wake Forest Demon Deacons", "Oregon Ducks", "Texas Tech Red Raiders",
    "Tennessee Volunteers", "Iowa Hawkeyes", "USC Trojans", "Arizona Wildcats",
    "Missouri Tigers", "Houston Cougars", "Louisville Cardinals", "Texas A&M Aggies",
    "Northwestern Wildcats", "BYU Cougars", "Nebraska Cornhuskers", "UCLA Bruins",
]
EXTRA = [("Tulsa Golden Hurricane", "group_of_five"), ("Oklahoma State Cowboys", "power")]


def _ranking(sport="ncaaf", published="2026-11-01"):
    rows = [{"rank": i + 1, "team_name": t, "rating": 40.0 - i, "wins": 7, "losses": 1,
             "movement": 0, "conference": "X", "tier": "power", "division": "fbs"}
            for i, t in enumerate(TEAMS)]
    rows += [{"rank": 60 + i, "team_name": t, "rating": 5.0, "wins": 3, "losses": 5,
              "tier": tier, "division": "fbs", "conference": "Y"}
             for i, (t, tier) in enumerate(EXTRA)]
    return {"available": True, "sport": sport, "season": 2026, "published_on": published,
            "basis": {"label": "Opponent-adjusted scoring margin"}, "rankings": rows}


def _pick(home, away, kickoff, model=60.0, market=58.0, dog=None):
    sides = [{"selection": home, "is_home": True, "model_pct": model, "market_pct": market},
             {"selection": away, "is_home": False, "model_pct": 100 - model,
              "market_pct": 100 - market}]
    return {"event_id": f"{home}-{away}", "sport": "ncaaf", "competition": "NCAAF",
            "home": home, "away": away, "kickoff": kickoff, "pick_name": home, "pick": "h",
            "model_pct": model, "market_pct": market, "edge_points": model - market,
            "basis": trdlab_handoff.LIVE_BASIS, "official_pick": False, "sides": sides}


def _handoff(generated="2026-11-03T02:50:00+00:00"):
    picks = [
        _pick("Notre Dame Fighting Irish", "Miami Hurricanes", "2026-11-08T00:30:00Z"),
        _pick("LSU Tigers", "Alabama Crimson Tide", "2026-11-07T20:30:00Z"),
        _pick("Ole Miss Rebels", "Georgia Bulldogs", "2026-11-08T00:30:00Z"),
        _pick("Ohio State Buckeyes", "Oregon Ducks", "2026-11-07T20:30:00Z"),
        _pick("Missouri Tigers", "Texas Longhorns", "2026-11-07T17:00:00Z"),
        # The underdog: market 18%, model 43% on Tulsa.
        _pick("Oklahoma State Cowboys", "Tulsa Golden Hurricane", "2026-11-06T00:00:00Z",
              model=57.0, market=82.0),
        _pick("Utah Utes", "UCLA Bruins", "2026-11-04T12:00:00Z"),       # already started
        _pick("Indiana Hoosiers", "Iowa Hawkeyes", "2026-11-14T17:00:00Z"),  # next week
    ]
    card = {"available": True, "reportable": True,
            "lock_policy": {"rule": "Frozen 60 minutes before kickoff."},
            "record": {"picks": 520, "wins": 382, "losses": 138, "hit_rate_pct": 73.5,
                       "expected_hit_rate_pct": 73.4, "confidence_interval_pct": [69.5, 77.1]},
            "versus_market": {"beat_market": {"picks": 948, "hit_rate_pct": 44.7, "basis": "Brier"},
                              "disagreed_with_market": {"picks": 42, "wins": 16, "losses": 26,
                                                        "hit_rate_pct": 38.1}}}
    upset_picks = [
        {"sport": "ncaaf", "home": "Utah Utes", "away": "UCLA Bruins",
         "kickoff": "2026-11-01T00:00:00Z", "selection": "UCLA Bruins", "model_pct": 40.0,
         "market_pct": 25.0, "result": "won", "home_score": 20, "away_score": 24},
        {"sport": "ncaaf", "home": "Texas Longhorns", "away": "Iowa Hawkeyes",
         "kickoff": "2026-11-01T19:00:00Z", "selection": "Iowa Hawkeyes", "model_pct": 38.0,
         "market_pct": 22.0, "result": "lost", "home_score": 31, "away_score": 10},
    ]
    return {
        "handoff_version": 11, "source": "trdlab", "generated_at": generated,
        "sports": ["ncaaf", "ncaam"], "picks": picks,
        "rankings": {"ncaaf": _ranking()},
        "ballots": {"ncaaf": {"available": True, "published_on": "2026-11-01", "basis": "ballot",
                              "rankings": [{"rank": i + 1, "team_name": t,
                                            "resume": {"record": "7-1"}}
                                           for i, t in enumerate(reversed(TEAMS))]}},
        "publication": {"reason": "Live shadow forecasts, not frozen."},
        "game_of_the_week": {"available": True, "caveat": "Editorial, not advice.", "game": {
            "event_id": "gotw", "competition": "NCAAF", "kickoff": "2026-11-08T00:30:00Z",
            "home": {"team": "Notre Dame Fighting Irish", "rank": 1, "record": "7-1"},
            "away": {"team": "Miami Hurricanes", "rank": 2, "record": "8-0"},
            "model_pick": "Notre Dame Fighting Irish", "model_pct": 61.8, "market_pct": 65.7}},
        "upset_of_the_week": {"available": True, "recorded": True, "week": "2026-W44",
                              "picks": upset_picks},
        "scorecard": {"caveat": "Never render the hit rate on its own.",
                      "sports": {"ncaaf": card}},
    }


class Workspace(unittest.TestCase):
    """A temp repo root holding whatever handoff a test writes."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def write(self, document):
        (self.root / trdlab_handoff.DEFAULT_HANDOFF_PATH).write_text(
            json.dumps(document), encoding="utf-8")

    def queue(self, document=None, now=NOW):
        if document is not None:
            self.write(document)
        return ce.build_queue(now, self.root)

    def kinds(self, queue):
        return {(i["kind"], i["sport"]) for i in queue["items"]}


class SaysNothing(Workspace):
    def test_no_handoff_and_no_posts_is_an_empty_queue(self):
        queue = self.queue()
        self.assertEqual(queue["items"], [])
        self.assertEqual(queue["withheld"][0]["scope"], "handoff")

    def test_a_stale_handoff_posts_nothing_derived_from_it(self):
        queue = self.queue(_handoff(generated="2026-10-20T00:00:00+00:00"))
        self.assertEqual(queue["items"], [])
        self.assertIn("older than", queue["withheld"][0]["reason"])

    def test_after_every_expiry_the_queue_is_empty(self):
        """A week later every item has expired, even with the same handoff on disk.

        Freshness is checked first, so move the handoff's clock with the test's.
        """
        later = NOW + dt.timedelta(days=7)
        queue = self.queue(_handoff(generated="2026-11-10T00:00:00+00:00"), now=later)
        stale_kinds = {"power_top25", "ballot_top25", "upset_watch",
                       "game_of_the_week", "upset_results"}
        self.assertFalse(stale_kinds & {k for k, _ in self.kinds(queue)})
        # The slate rolls forward rather than expiring: the only game left is
        # the one that genuinely falls in the new week.
        slate = [i for i in queue["items"] if i["kind"] == "slate_preview"]
        self.assertEqual([(g["home"], g["away"]) for g in slate[0]["facts"]["games"]],
                         [("Indiana Hoosiers", "Iowa Hawkeyes")])

    def test_summary_says_do_not_invent_work_when_empty(self):
        self.assertIn("do not invent", ce._summary(self.queue()))


class FreshWeek(Workspace):
    def setUp(self):
        super().setUp()
        self.result = self.queue(_handoff())
        self.by_kind = {(i["kind"], i["sport"]): i for i in self.result["items"]}

    def test_expected_items_are_present(self):
        self.assertEqual(self.kinds(self.result), {
            ("power_top25", "ncaaf"), ("ballot_top25", "ncaaf"), ("scorecard", "ncaaf"),
            ("slate_preview", "ncaaf"), ("upset_watch", "ncaaf"),
            ("game_of_the_week", "ncaaf"), ("upset_results", "ncaaf"),
        })

    def test_every_caption_fits_x_and_ends_with_a_tracked_link(self):
        for item in self.result["items"]:
            self.assertLessEqual(ce.x_length(item["caption"]), ce.MAX_CAPTION, item["key"])
            self.assertTrue(item["caption"].endswith(item["link"]), item["key"])
            self.assertIn("utm_source=x", item["link"])

    def test_every_item_names_its_source_and_hash(self):
        for item in self.result["items"]:
            self.assertEqual(len(item["source"]["sha256"]), 64)
            self.assertTrue(item["source"]["file"])

    def test_slate_excludes_started_and_next_week_games(self):
        games = self.by_kind[("slate_preview", "ncaaf")]["facts"]["games"]
        pairs = {(g["home"], g["away"]) for g in games}
        self.assertNotIn(("Utah Utes", "UCLA Bruins"), pairs)
        self.assertNotIn(("Indiana Hoosiers", "Iowa Hawkeyes"), pairs)
        self.assertEqual(len(games), ce.SLATE_SIZE)

    def test_upset_list_expires_at_its_first_kickoff(self):
        item = self.by_kind[("upset_watch", "ncaaf")]
        self.assertEqual(item["expires_at"], "2026-11-06T00:00:00Z")
        self.assertEqual(item["facts"]["games"][0]["underdog"], "Tulsa Golden Hurricane")

    def test_pick_items_carry_the_live_forecast_caveat(self):
        for kind in ("slate_preview", "upset_watch"):
            self.assertIn("Live shadow", self.by_kind[(kind, "ncaaf")]["caveat"])

    def test_scorecard_never_shows_the_hit_rate_alone(self):
        caption = self.by_kind[("scorecard", "ncaaf")]["caption"]
        self.assertIn("73.4% expected", caption)
        self.assertIn("44.7%", caption)
        self.assertIn("382-138", caption)

    def test_upset_results_report_the_misses(self):
        item = self.by_kind[("upset_results", "ncaaf")]
        self.assertEqual((item["facts"]["won"], item["facts"]["lost"]), (1, 1))
        self.assertIn("1 of 2", item["caption"])

    def test_the_same_input_gives_the_same_keys(self):
        again = ce.build_queue(NOW + dt.timedelta(minutes=5), self.root)
        self.assertEqual([i["key"] for i in self.result["items"]],
                         [i["key"] for i in again["items"]])


class Withholding(Workspace):
    def test_scorecard_without_market_comparison_is_withheld(self):
        doc = _handoff()
        del doc["scorecard"]["sports"]["ncaaf"]["versus_market"]
        self.assertNotIn(("scorecard", "ncaaf"), self.kinds(self.queue(doc)))

    def test_unreportable_scorecard_is_withheld(self):
        doc = _handoff()
        doc["scorecard"]["sports"]["ncaaf"]["reportable"] = False
        self.assertNotIn(("scorecard", "ncaaf"), self.kinds(self.queue(doc)))

    def test_partially_settled_upset_week_is_not_reported(self):
        doc = _handoff()
        doc["upset_of_the_week"]["picks"][1]["result"] = None
        self.assertNotIn(("upset_results", "ncaaf"), self.kinds(self.queue(doc)))

    def test_short_ranking_is_not_a_top_25(self):
        doc = _handoff()
        doc["rankings"]["ncaaf"]["rankings"] = doc["rankings"]["ncaaf"]["rankings"][:20]
        self.assertNotIn(("power_top25", "ncaaf"), self.kinds(self.queue(doc)))

    def test_game_of_the_week_already_kicked_off_is_withheld(self):
        doc = _handoff()
        doc["game_of_the_week"]["game"]["kickoff"] = "2026-11-04T14:00:00Z"
        self.assertNotIn(("game_of_the_week", "ncaaf"), self.kinds(self.queue(doc)))


class Captions(unittest.TestCase):
    def test_x_counts_links_as_23(self):
        url = "https://matchdayterminal.com/" + "a" * 200
        self.assertEqual(ce.x_length("hi " + url), 3 + 23)

    def test_fit_keeps_the_url_whole(self):
        url = "https://matchdayterminal.com/?view=score"
        out = ce.fit("word " * 100 + url)
        self.assertTrue(out.endswith(url))
        self.assertLessEqual(ce.x_length(out), ce.MAX_CAPTION)

    def test_basketball_mascots_are_shortened(self):
        self.assertEqual(ce.short("Iowa State Cyclones"), "Iowa State")
        self.assertEqual(ce.short("New Mexico Lobos"), "New Mexico")
        self.assertEqual(ce.short("Ohio State Buckeyes"), "Ohio State")
        self.assertEqual(ce.short("Duke"), "Duke")

    def test_the_longest_mascot_wins_and_no_half_mascot_is_left(self):
        """Seen in a replayed week: "Marquette Golden" and "Cincinnati Bearcats"."""
        cases = {
            "Marquette Golden Eagles": "Marquette", "Cincinnati Bearcats": "Cincinnati",
            "Army Black Knights": "Army", "North Dakota Fighting Hawks": "North Dakota",
            "UMass Lowell River Hawks": "UMass Lowell", "Bowling Green Falcons": "Bowling Green",
            "Tulsa Golden Hurricane": "Tulsa", "Miami Hurricanes": "Miami",
            "Stanford Cardinal": "Stanford", "Louisville Cardinals": "Louisville",
            "Alabama Crimson Tide": "Alabama", "Akron Zips": "Akron Zips",
        }
        for full, expected in cases.items():
            self.assertEqual(ce.short(full), expected, full)


PNG = base64.b64decode(ce.BLANK_PNG.split(",", 1)[1])


class Studio(Workspace):
    def setUp(self):
        super().setUp()
        self.logos = self.root / "logos"
        self.logos.mkdir()
        for name in ("ohio", "ohioState", "notreDame", "miami"):
            (self.logos / f"{name}.png").write_bytes(PNG)

    def test_longest_prefix_wins(self):
        index = ce._logo_index(self.logos)
        self.assertEqual(ce.logo_for("Ohio State Buckeyes", index).stem, "ohioState")
        self.assertEqual(ce.logo_for("Ohio Bobcats", index).stem, "ohio")
        self.assertIsNone(ce.logo_for("Tulane Green Wave", index))

    def assert_loads_in_studio(self, edition):
        """Mirror of Matchday Studio's loadFile validation for version 2."""
        self.assertEqual(edition["version"], 2)
        self.assertIn(edition["mode"], ("rankings", "ballot", "matchups", "upset"))
        self.assertEqual(len(edition["rankings"]), 25)
        self.assertEqual(len(edition["matchups"]), 5)
        if "ballot" in edition:
            self.assertEqual(len(edition["ballot"]), 25)
        if "upsets" in edition:
            self.assertEqual(len(edition["upsets"]), 3)
            self.assertTrue(all(isinstance(m["detail"], str) for m in edition["upsets"]))
        teams = (edition["rankings"] + edition.get("ballot", [])
                 + [s for m in edition["matchups"] + edition.get("upsets", [])
                    for s in (m["left"], m["right"])])
        for team in teams:
            self.assertIsInstance(team["name"], str)
            self.assertTrue(team["src"].startswith("data:image/"))
        self.assertTrue(all(isinstance(r["detail"], str) for r in edition["rankings"]))
        self.assertTrue(all(isinstance(m["detail"], str) for m in edition["matchups"]))
        self.assertLessEqual(len(edition["edition"]), ce.STUDIO_EDITION_MAX)
        self.assertLessEqual(len(edition["footer"]), ce.STUDIO_FOOTER_MAX)
        json.dumps(edition)

    def test_edition_is_loadable_and_reports_missing_logos(self):
        edition = ce.studio_edition(self.queue(_handoff()), self.logos)
        self.assert_loads_in_studio(edition)
        self.assertEqual(edition["edition"], "NOV 1, 2026")
        self.assertEqual(edition["rankings"][0]["detail"], "40.00")
        self.assertIn("Texas Longhorns", edition["_matchday"]["missing_logos"])
        self.assertNotIn("Ohio State Buckeyes", edition["_matchday"]["missing_logos"])

    def test_no_edition_without_a_full_slate(self):
        doc = _handoff()
        doc["picks"] = doc["picks"][:3]
        self.assertIsNone(ce.studio_edition(self.queue(doc), self.logos))

    def test_upsets_are_omitted_unless_exactly_three(self):
        edition = ce.studio_edition(self.queue(_handoff()), self.logos)
        self.assertNotIn("upsets", edition)

    def test_real_logo_directory_covers_the_fixture_top_25(self):
        index = ce._logo_index(ce.LOGO_DIR)
        missing = [t for t in TEAMS if ce.logo_for(t, index) is None]
        self.assertEqual(missing, [])

    def test_brand_names_reach_the_full_school_logo(self):
        # "UConn" shares no prefix with "connecticut", so only an alias finds it.
        index = ce._logo_index(ce.LOGO_DIR)
        cases = {
            "UConn Huskies": "connecticut",
            "App State Mountaineers": "appalachianState",
            "Louisiana Ragin' Cajuns": "louisianaLafayette",
            "UL Monroe Warhawks": "louisianaMonroe",
            "UTSA Roadrunners": "texasSanAntonio",
            "Sam Houston Bearkats": "samHoustonState",
            "San José State Spartans": "sanJoseState",
            "UAlbany Great Danes": "albany",
            # aliases must not capture the schools they sit next to
            "Washington Huskies": "washington",
            "Louisiana Tech Bulldogs": "LouisianaTech",
        }
        for team, stem in cases.items():
            with self.subTest(team=team):
                self.assertEqual(ce.logo_for(team, index).stem, stem)

    def test_every_alias_points_at_a_real_logo(self):
        stems = {p.stem for p in ce.LOGO_DIR.glob("*.png")}
        self.assertEqual(sorted(set(ce.LOGO_ALIASES.values()) - stems), [])


class Determinism(unittest.TestCase):
    def test_digest_ignores_key_order_but_not_values(self):
        a = {"x": 1, "y": [1, 2]}
        self.assertEqual(ce.digest(a), ce.digest({"y": [1, 2], "x": 1}))
        changed = copy.deepcopy(a)
        changed["x"] = 2
        self.assertNotEqual(ce.digest(a), ce.digest(changed))


def _bracket(**over):
    field = [{"team_name": n, "seed": 1, "region": r, "overall_seed": i + 1}
             for i, (n, r) in enumerate([("Duke Blue Devils", "East"), ("Florida Gators", "West"),
                                         ("Houston Cougars", "South"), ("Purdue Boilermakers", "Midwest")])]
    field.append({"team_name": "Iowa State Cyclones", "seed": 2, "region": "East", "overall_seed": 5})
    doc = {"phase": "in_season", "calibrated": False, "build_id": "b1", "simulations": 10000,
           "as_of": "2027-02-01T00:00:00Z", "valid_until": "2027-02-08T00:00:00Z", "field": field}
    doc.update(over)
    return doc


class Bracketology(unittest.TestCase):
    NOW = dt.datetime(2027, 2, 3, tzinfo=dt.timezone.utc)

    def test_in_season_projection_names_the_one_seeds(self):
        [item] = ce.bracketology(_bracket(), self.NOW, "bracketology_ncaam.json")
        self.assertEqual(item.key, "bracketology:ncaam:b1")
        self.assertIn("Projected No. 1 seeds: Duke (East), Florida (West), Houston (South), Purdue (Midwest)",
                      item.caption)
        self.assertIn("Beta projection", item.caption)
        self.assertIn("not the NCAA selection committee", item.caveat)
        self.assertEqual(item.expires_at, "2027-02-08T00:00:00Z")

    def test_early_phase_mock_and_expired_say_nothing(self):
        self.assertEqual(ce.bracketology(_bracket(phase="early"), self.NOW, "b"), [])
        self.assertEqual(ce.bracketology(_bracket(mock=True), self.NOW, "b"), [])
        self.assertEqual(ce.bracketology(_bracket(valid_until="2027-02-02T00:00:00Z"), self.NOW, "b"), [])
        self.assertEqual(ce.bracketology(None, self.NOW, "b"), [])

    def test_official_bracket_drops_the_beta_and_the_caveat(self):
        [item] = ce.bracketology(_bracket(phase="official"), self.NOW, "b")
        self.assertIn("Official No. 1 seeds", item.caption)
        self.assertNotIn("Beta", item.caption)
        self.assertIsNone(item.caveat)


if __name__ == "__main__":
    unittest.main()
