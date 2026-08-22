import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import forecast_ledger
import mlb_shadow_ledger


NOW = datetime(2026, 8, 18, 18, 0, tzinfo=timezone.utc)


def fixture(status="UPCOMING"):
    return {
        "id": "mlb-1", "status": status, "kickoff": "2026-08-18T20:00:00Z",
        "home": {"name": "Alpha"}, "away": {"name": "Beta"},
        "data_source": "licensed test source", "model_signal_schema": 7,
        "markets": {"1x2": {"home_pct": 54.25, "away_pct": 45.75,
                              "observed_at": "2026-08-18T17:59:00Z", "books": 4}},
        "pregame_context": {
            "phase": "lock_window",
            "inputs": {"market": "confirmed", "starting_pitchers": "missing",
                       "lineups": "missing", "bullpen": "available"},
            "missing_critical": ["starting_pitchers", "lineups"],
        },
        "mlb_challenger_shadow": {
            "mode": "prospective_shadow", "production_weight": 0,
            "model_version": "candidate-v1", "trained_through": "2025-09-28",
            "artifact_sha256": "a" * 64, "feature_schema": ["run_diff"],
            "feature_schema_version": 1, "transformation_version": "transform-v1",
            "home_win_probability": .611234, "league_home_prior_probability": .534641,
            "features": {"run_diff": .25},
            "missing_personnel": ["confirmed_lineup"],
        },
    }


def prediction():
    return {
        "model_version": "official-v1", "model_signal_schema": 7,
        "model": {"h": 57.1234, "a": 42.8766, "d": 0},
        "regulation_probs": {"h": 55.4321, "a": 44.5679, "d": 0},
    }


class MLBShadowLedgerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "mlb_shadow_ledger.jsonl"

    def tearDown(self):
        self.temp.cleanup()

    def test_lock_is_private_complete_and_idempotent(self):
        first = mlb_shadow_ledger.sync(self.path, [fixture()], {"mlb-1": prediction()}, NOW)
        second = mlb_shadow_ledger.sync(self.path, [fixture()], {"mlb-1": prediction()}, NOW)
        self.assertEqual(first["locked"], 1)
        self.assertEqual(second["locked"], 0)
        events = forecast_ledger.read_events(self.path)
        self.assertEqual([row["event_type"] for row in events], [mlb_shadow_ledger.LOCK_EVENT])
        payload = events[0]["payload"]
        self.assertEqual(payload["baseline"]["home_win_probability"], .554321)
        self.assertEqual(payload["independent_official"]["home_win_probability"], .571234)
        self.assertEqual(payload["candidate"]["home_win_probability"], .611234)
        self.assertEqual(payload["market"]["home_win_probability"], .5425)
        self.assertEqual(payload["candidate"]["artifact_sha256"], "a" * 64)
        snapshot = payload["input_snapshot"]
        canonical = json.dumps(snapshot, ensure_ascii=False, sort_keys=True,
                               separators=(",", ":"), default=str)
        self.assertEqual(payload["provenance"]["input_snapshot_hash"],
                         hashlib.sha256(canonical.encode("utf-8")).hexdigest())

    def test_never_locks_after_kickoff_or_outside_two_hour_window(self):
        too_early = datetime(2026, 8, 18, 17, 59, 59, tzinfo=timezone.utc)
        after = datetime(2026, 8, 18, 20, 0, 1, tzinfo=timezone.utc)
        self.assertFalse(mlb_shadow_ledger.lock_match(self.path, fixture(), prediction(), too_early))
        self.assertFalse(mlb_shadow_ledger.lock_match(self.path, fixture(), prediction(), after))
        self.assertFalse(self.path.exists())

    def test_post_lock_market_quote_is_not_frozen_as_comparable(self):
        match = fixture()
        match["markets"]["1x2"]["observed_at"] = "2026-08-18T18:01:00Z"
        self.assertTrue(mlb_shadow_ledger.lock_match(self.path, match, prediction(), NOW))
        market = forecast_ledger.read_events(self.path)[0]["payload"]["market"]
        self.assertIsNone(market["home_win_probability"])
        self.assertEqual(market["missing_reason"], "quote_observed_after_lock")

    def test_replay_refuses_a_tampered_chain(self):
        mlb_shadow_ledger.lock_match(self.path, fixture(), prediction(), NOW)
        event = json.loads(self.path.read_text(encoding="utf-8"))
        event["payload"]["candidate"]["home_win_probability"] = .99
        self.path.write_text(json.dumps(event) + "\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            mlb_shadow_ledger.lock_match(self.path, fixture(), prediction(), NOW)

    def test_grade_appends_without_mutating_lock(self):
        mlb_shadow_ledger.lock_match(self.path, fixture(), prediction(), NOW)
        original_lock = forecast_ledger.read_events(self.path)[0]
        final = fixture("FINISHED")
        final["score"] = {"home": 5, "away": 3,
                          "observed_at": "2026-08-18T22:55:00Z"}
        grade_time = datetime(2026, 8, 18, 23, 0, tzinfo=timezone.utc)
        self.assertEqual(mlb_shadow_ledger.grade_matches(self.path, [final], grade_time), 1)
        self.assertEqual(mlb_shadow_ledger.grade_matches(self.path, [final], grade_time), 0)
        events = forecast_ledger.read_events(self.path)
        self.assertEqual(events[0], original_lock)
        self.assertEqual(events[1]["event_type"], mlb_shadow_ledger.GRADE_EVENT)
        self.assertEqual(events[1]["payload"]["result"], "h")
        self.assertEqual(events[1]["payload"]["lock_event_id"], original_lock["event_id"])
        self.assertEqual(events[1]["payload"]["outcome_source"]["provider"],
                         "licensed test source")
        self.assertEqual(events[1]["payload"]["outcome_source"]["observed_at"],
                         "2026-08-18T22:55:00Z")
        self.assertEqual(forecast_ledger.validate(self.path)["events"], 2)

    def test_grade_rejects_reused_identity_and_premature_final(self):
        mlb_shadow_ledger.lock_match(self.path, fixture(), prediction(), NOW)
        final = fixture("FINISHED")
        final["score"] = {"home": 5, "away": 3}
        with self.assertRaisesRegex(ValueError, "precedes locked kickoff"):
            mlb_shadow_ledger.grade_matches(self.path, [final], NOW)

        final["home"]["name"] = "Different Alpha"
        after = datetime(2026, 8, 18, 23, 0, tzinfo=timezone.utc)
        with self.assertRaisesRegex(ValueError, "fixture identity mismatch"):
            mlb_shadow_ledger.grade_matches(self.path, [final], after)

        final = fixture("FINISHED")
        final["score"] = {"home": 5, "away": 3}
        final["kickoff"] = "2026-08-18T20:30:00Z"
        with self.assertRaisesRegex(ValueError, "fixture identity mismatch"):
            mlb_shadow_ledger.grade_matches(self.path, [final], after)


class LockDecisionReportingTests(unittest.TestCase):
    """A refusal to lock is permanent, so it has to be visible when it happens.

    Four healthy runs on the evening of 2026-08-19 fetched MLB, committed their
    output, and locked nothing across a full slate. Nothing in the CI log, the
    ledger, or the committed tree recorded that -- the only signal was a DIAG
    entry that is suppressed at zero and written to an untracked file. These
    tests pin the tally so the next occurrence is diagnosable from the log.
    """

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "mlb_shadow_ledger.jsonl"

    def tearDown(self):
        self.temp.cleanup()

    def test_every_refusal_is_named_and_counted(self):
        early = fixture()
        early["id"] = "mlb-early"
        early["kickoff"] = "2026-08-18T23:00:00Z"
        started = fixture()
        started["id"] = "mlb-started"
        started["kickoff"] = "2026-08-18T17:00:00Z"
        unweighted = fixture()
        unweighted["id"] = "mlb-weighted"
        unweighted["mlb_challenger_shadow"]["production_weight"] = 0.1
        incomplete = fixture()
        incomplete["id"] = "mlb-incomplete"
        incomplete["mlb_challenger_shadow"]["league_home_prior_probability"] = None
        rows = [fixture(), fixture("FINISHED"), started, unweighted, incomplete, early]
        predictions = {row["id"]: prediction() for row in rows}
        state = mlb_shadow_ledger.sync(self.path, rows, predictions, NOW)
        self.assertEqual(state["locked"], 1)
        self.assertEqual(state["considered"], 6)
        self.assertEqual(state["lock_reasons"], {
            "first_pitch_passed": 1,
            "incomplete_lock_inputs": 1,
            "locked": 1,
            "no_zero_weight_challenger_shadow": 1,
            "not_upcoming": 1,
            "before_lock_window": 1,
        })

    def test_a_quiet_hour_still_reports_why_it_was_quiet(self):
        too_early = datetime(2026, 8, 18, 17, 0, tzinfo=timezone.utc)
        state = mlb_shadow_ledger.sync(self.path, [fixture()], {"mlb-1": prediction()}, too_early)
        self.assertEqual(state["locked"], 0)
        self.assertEqual(state["lock_reasons"], {"before_lock_window": 1})

    def test_lock_match_keeps_its_boolean_contract(self):
        self.assertIs(mlb_shadow_ledger.lock_match(
            self.path, fixture(), prediction(), NOW), True)
        self.assertIs(mlb_shadow_ledger.lock_match(
            self.path, fixture(), prediction(), NOW), False)


if __name__ == "__main__":
    unittest.main()
