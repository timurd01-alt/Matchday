"""What the Bet Better handoff is allowed to put on a match card.

The engine's picks are live forecasts, not frozen cards. These tests pin the
boundary that keeps them from drifting into the published, graded record:
they attach to their own key, they never claim an official receipt, and they
never reach a fixture whose result is already known.
"""

import json
import os
import tempfile
import unittest

import betbetter_handoff
import forecast_pause
import pick_integrity


def pick(**overrides):
    record = {
        "event_id": "abc123",
        "sport": "ncaaf",
        "competition": "NCAAF",
        "home": "Rutgers Scarlet Knights",
        "away": "UMass Minutemen",
        "kickoff": "2026-09-03T22:00:00Z",
        "pick_name": "Rutgers Scarlet Knights",
        "pick": "h",
        "model_pct": 98.8,
        "market_pct": 94.5,
        "edge_points": 4.4,
        "best_price": 1.01,
        "best_american": -10000,
        "book_count": 7,
        "model_name": "NCAAF statistical baseline",
        "model_version": "spplus-normal-v1",
        "generated_at": "2026-08-30T20:22:56Z",
        "official_pick": False,
        "basis": "live_shadow_forecast",
        "moves_until_kickoff": True,
        "integrity_note": "Live model read, not a frozen card.",
        "sides": [],
    }
    record.update(overrides)
    return record


def document(**overrides):
    doc = {
        "handoff_version": 1,
        "source": "betbetter",
        "generated_at": "2026-08-30T23:35:50Z",
        "sports": ["ncaaf", "ncaam"],
        "picks": [pick()],
        "edge_warning": "Do not stake on edge_points.",
    }
    doc.update(overrides)
    return doc


def match(**overrides):
    record = {
        "home": "Rutgers Scarlet Knights",
        "away": "UMass Minutemen",
        "kickoff": "2026-09-03T22:00:00Z",
        "status": "UPCOMING",
    }
    record.update(overrides)
    return record


class LoadTests(unittest.TestCase):
    def write(self, payload):
        handle, path = tempfile.mkstemp(suffix=".json")
        with os.fdopen(handle, "w", encoding="utf-8") as file:
            json.dump(payload, file)
        self.addCleanup(os.unlink, path)
        return path

    def test_a_missing_file_is_not_an_error(self):
        # Bet Better may simply not have run. That is different from broken.
        self.assertIsNone(betbetter_handoff.load("no_such_handoff.json"))

    def test_a_known_version_loads(self):
        loaded = betbetter_handoff.load(self.write(document()))
        self.assertEqual(len(loaded["picks"]), 1)

    def test_an_unknown_version_is_refused_whole(self):
        with self.assertRaises(betbetter_handoff.HandoffError):
            betbetter_handoff.load(self.write(document(handoff_version=99)))

    def test_a_document_from_somewhere_else_is_refused(self):
        with self.assertRaises(betbetter_handoff.HandoffError):
            betbetter_handoff.load(self.write(document(source="somebody_else")))

    def test_a_pick_claiming_an_official_receipt_is_refused(self):
        # Not trimmed — refused. A handoff that tries to mint an official pick
        # means something upstream is wrong about what it may say.
        with self.assertRaises(betbetter_handoff.HandoffError) as raised:
            betbetter_handoff.load(
                self.write(document(picks=[pick(official_pick=True)])))
        self.assertIn("official_pick", str(raised.exception))

    def test_an_unexpected_basis_is_refused(self):
        with self.assertRaises(betbetter_handoff.HandoffError):
            betbetter_handoff.load(
                self.write(document(picks=[pick(basis="locked_card")])))

    def test_malformed_json_is_reported_rather_than_treated_as_empty(self):
        handle, path = tempfile.mkstemp(suffix=".json")
        with os.fdopen(handle, "w", encoding="utf-8") as file:
            file.write("{not json")
        self.addCleanup(os.unlink, path)
        with self.assertRaises(betbetter_handoff.HandoffError):
            betbetter_handoff.load(path)


class AttachTests(unittest.TestCase):
    def test_a_pick_lands_on_its_own_key_not_on_prediction(self):
        matches = [match(prediction={"publication_state": "paused"})]
        self.assertEqual(betbetter_handoff.attach(matches, document()), 1)
        self.assertIn("betbetter_pick", matches[0])
        # The production forecast is untouched, so the pause still owns it.
        self.assertEqual(matches[0]["prediction"], {"publication_state": "paused"})

    def test_a_team_is_an_object_on_the_matchday_side(self):
        # Matchday carries {"name": ..., "code": ...}; reading str() of that
        # matched nothing at all, which is how this was found.
        matches = [match(home={"name": "Rutgers", "code": "RUT"},
                         away={"name": "UMass", "code": "MASS"})]
        self.assertEqual(betbetter_handoff.attach(matches, document()), 1)

    def test_short_names_match_the_engine_full_names(self):
        # Matchday says "TCU"; Bet Better says "TCU Horned Frogs".
        matches = [match(home={"name": "TCU"}, away={"name": "North Carolina"})]
        doc = document(picks=[pick(home="TCU Horned Frogs",
                                   away="North Carolina Tar Heels")])
        self.assertEqual(betbetter_handoff.attach(matches, doc), 1)

    def test_accents_and_punctuation_are_not_a_difference(self):
        matches = [match(home={"name": "San José State"}, away={"name": "U-Mass"})]
        doc = document(picks=[pick(home="San Jose State Spartans",
                                   away="UMass Minutemen")])
        self.assertEqual(betbetter_handoff.attach(matches, doc), 1)

    def test_a_prefix_shared_by_two_schools_yields_no_pick(self):
        # "Miami" prefixes both. Showing the wrong team's number is worse than
        # showing none, so an ambiguous day resolves to nothing.
        matches = [match(home={"name": "Miami"}, away={"name": "Florida State"})]
        doc = document(picks=[
            pick(home="Miami Hurricanes", away="Florida State Seminoles"),
            pick(home="Miami OH RedHawks", away="Florida State Seminoles"),
        ])
        self.assertEqual(betbetter_handoff.attach(matches, doc), 0)
        self.assertNotIn("betbetter_pick", matches[0])

    def test_a_two_letter_stub_does_not_match_everything(self):
        matches = [match(home={"name": "NC"}, away={"name": "UMass Minutemen"})]
        doc = document(picks=[pick(home="NC State Wolfpack",
                                   away="UMass Minutemen")])
        self.assertEqual(betbetter_handoff.attach(matches, doc), 0)

    def test_home_and_away_are_not_interchangeable(self):
        # A pick for the reverse fixture is a different game.
        matches = [match(home={"name": "UMass Minutemen"},
                         away={"name": "Rutgers Scarlet Knights"})]
        self.assertEqual(betbetter_handoff.attach(matches, document()), 0)

    def test_kickoff_minutes_may_differ_between_feeds(self):
        matches = [match(kickoff="2026-09-03T21:30:00Z")]
        self.assertEqual(betbetter_handoff.attach(matches, document()), 1)

    def test_a_played_game_never_receives_a_live_pick(self):
        # Attaching a live number to a finished game would read as a call made
        # in advance. Every non-UPCOMING status is refused.
        for status in ("FINISHED", "IN_PLAY", "PAUSED", ""):
            matches = [match(status=status)]
            self.assertEqual(betbetter_handoff.attach(matches, document()), 0,
                             f"status {status!r} should not receive a pick")
            self.assertNotIn("betbetter_pick", matches[0])

    def test_an_unrelated_fixture_is_left_alone(self):
        matches = [match(home="Ohio State Buckeyes", away="Michigan Wolverines")]
        self.assertEqual(betbetter_handoff.attach(matches, document()), 0)

    def test_the_attached_block_refuses_publication_on_its_face(self):
        matches = [match()]
        betbetter_handoff.attach(matches, document())
        block = matches[0]["betbetter_pick"]
        self.assertIs(block["official_pick"], False)
        self.assertIs(block["official_publication_eligible"], False)
        self.assertEqual(block["basis"], "live_shadow_forecast")
        self.assertEqual(block["engine"], "betbetter")
        # The warning travels with the card, not only in the envelope.
        self.assertIn("edge", block["edge_warning"].lower())

    def test_an_attached_block_is_not_an_official_pick_record(self):
        # The guard that matters most: whatever this module attaches must fail
        # Matchday's own receipt test, so it can never be graded as a call.
        matches = [match()]
        betbetter_handoff.attach(matches, document())
        self.assertFalse(
            pick_integrity.is_official_pick_record(matches[0]["betbetter_pick"]))


class FileLevelTests(unittest.TestCase):
    def test_a_broken_handoff_does_not_stop_a_fetch(self):
        handle, path = tempfile.mkstemp(suffix=".json")
        with os.fdopen(handle, "w", encoding="utf-8") as file:
            file.write("{not json")
        self.addCleanup(os.unlink, path)
        report = betbetter_handoff.attach_from_file([match()], path)
        self.assertEqual(report["attached"], 0)
        self.assertFalse(report["available"])
        self.assertTrue(report["reason"])

    def test_a_missing_handoff_reports_rather_than_raises(self):
        report = betbetter_handoff.attach_from_file([match()], "nope.json")
        self.assertEqual(report["attached"], 0)
        self.assertFalse(report["available"])


class PauseTests(unittest.TestCase):
    def test_display_is_refused_regardless_of_how_the_pause_is_set(self):
        # These picks are never publishable, so the answer does not depend on
        # the pause. This is what lets the pipe be wired while it stays on.
        matches = [match()]
        betbetter_handoff.attach(matches, document())
        self.assertIs(
            matches[0]["betbetter_pick"]["official_publication_eligible"], False)
        self.assertFalse(forecast_pause.PAUSE_ACTIVE)


if __name__ == "__main__":
    unittest.main()
