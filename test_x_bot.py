import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import x_bot
from pick_integrity import MODEL_CODE_MARKER, is_official_pick_record


UTC = dt.timezone.utc
NOW = dt.datetime(2026, 8, 3, 12, 0, tzinfo=UTC)


class CandidateTests(unittest.TestCase):
    def official_record(self, **overrides):
        record = {
            "schema_ver": 2, "model_code_marker": MODEL_CODE_MARKER,
            "fixture_id": "fixture-1", "competition": "NFL",
            "home": "Alpha", "away": "Beta", "pick": "h", "pick_name": "Alpha",
            "confidence": 61, "kickoff": "2026-08-04T12:00:00Z",
            "locked_at": "2026-08-04T10:00:00Z", "lead_time_seconds": 7200,
            "lock_window_hours": 2, "status_at_lock": "UPCOMING",
            "integrity_eligible": True, "integrity_status": "verified",
            "prediction_snapshot": {}, "input_snapshot": {}, "result": None,
            "outcome_basis": "regulation",
        }
        record.update(overrides)
        return record

    def test_only_official_upcoming_picks_become_prediction_posts(self):
        quarantined = self.official_record(integrity_status="quarantined")
        self.assertEqual(x_bot.locked_pick_candidates([quarantined], NOW), [])
        candidates = x_bot.locked_pick_candidates([self.official_record()], NOW)
        self.assertEqual(len(candidates), 1)
        self.assertIn("locked model pick: Alpha", candidates[0].text)
        self.assertIn("61%", candidates[0].text)
        self.assertLessEqual(len(candidates[0].text), 280)

    def test_finished_distant_and_malformed_fixtures_are_not_promoted(self):
        cases = [
            self.official_record(result="h"),
            self.official_record(kickoff="2026-08-10T12:00:00Z", lead_time_seconds=691200),
            self.official_record(fixture_id=""),
        ]
        for record in cases:
            self.assertEqual(x_bot.locked_pick_candidates([record], NOW), [])

    def test_draw_and_advancement_wording_match_outcome_basis(self):
        draw = self.official_record(pick="d", pick_name="Draw")
        advance = self.official_record(fixture_id="cup-1", pick="a", pick_name="Beta",
                                       outcome_basis="ultimate_winner")
        texts = [candidate.text for candidate in x_bot.locked_pick_candidates([draw, advance], NOW)]
        self.assertTrue(any("regulation pick: draw" in text for text in texts))
        self.assertTrue(any("pick to advance: Beta" in text for text in texts))

    def test_article_copy_is_bounded_and_links_to_the_article(self):
        very_long = "A detailed model recap " * 30
        candidate = x_bot.article_candidates(
            [{"slug": "nfl-2026-08-03", "title": very_long, "date": "2026-08-03"}], "recap"
        )[0]
        self.assertLessEqual(len(candidate.text), 280)
        self.assertTrue(candidate.text.endswith("/posts/nfl-2026-08-03.html"))

    def test_sent_campaign_is_not_selected_twice(self):
        first = x_bot.Candidate("one", "first", "evergreen")
        second = x_bot.Candidate("two", "second", "evergreen")
        state = {"events": [{"key": "one", "status": "success", "at": "2026-08-02T12:00:00Z"}]}
        self.assertEqual(x_bot.choose_candidate([first, second], state, NOW), second)

    def test_ambiguous_attempt_blocks_all_posts_but_definitive_failure_can_retry(self):
        candidate = x_bot.Candidate("one", "first", "evergreen")
        ambiguous = {"events": [{"key": "other", "status": "ambiguous", "at": "2026-08-02T12:00:00Z"}]}
        self.assertIsNone(x_bot.choose_candidate([candidate], ambiguous, NOW))
        failed = {"events": [
            {"key": "one", "status": "attempting", "at": "2026-08-02T12:00:00Z"},
            {"key": "one", "status": "failed", "at": "2026-08-02T12:00:01Z"},
        ]}
        self.assertEqual(x_bot.choose_candidate([candidate], failed, NOW), candidate)

    def test_record_is_auditable_without_storing_post_text(self):
        candidate = x_bot.Candidate("one", "public copy", "evergreen")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            x_bot.append_event(path, {"events": []}, candidate, "success", NOW, post_id="123")
            state = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(state["events"][0]["post_id"], "123")
        self.assertNotIn("text", state["events"][0])
        self.assertEqual(len(state["events"][0]["text_sha256"]), 64)

    def test_ambiguous_receipt_can_only_be_resolved_with_verified_post_id(self):
        candidate = x_bot.Candidate("one", "public copy", "evergreen")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            state = {"events": []}
            x_bot.append_event(path, state, candidate, "ambiguous", NOW)
            with self.assertRaisesRegex(ValueError, "post id"):
                x_bot.resolve_ambiguous(path, state, "one", "success", NOW)
            x_bot.resolve_ambiguous(path, state, "one", "success", NOW, post_id="123")
            saved = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(saved["events"][-1]["status"], "success")
        self.assertEqual(saved["events"][-1]["post_id"], "123")

    def test_shared_integrity_validator_rejects_tampered_lead_time(self):
        self.assertTrue(is_official_pick_record(self.official_record()))
        self.assertFalse(is_official_pick_record(self.official_record(lead_time_seconds=1)))


class OAuthTests(unittest.TestCase):
    def test_oauth_header_is_deterministic_and_contains_no_secrets(self):
        header = x_bot.oauth1_header(
            "POST", x_bot.X_POST_URL, "key", "api-secret", "token", "token-secret",
            nonce="fixed", timestamp=1234567890,
        )
        self.assertTrue(header.startswith("OAuth "))
        self.assertIn('oauth_consumer_key="key"', header)
        self.assertIn('oauth_nonce="fixed"', header)
        self.assertIn("oauth_signature=", header)
        self.assertNotIn("api-secret", header)
        self.assertNotIn("token-secret", header)

    def test_dry_run_never_calls_publisher_or_writes_state(self):
        candidate = x_bot.Candidate("preview", "Preview copy", "evergreen")
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "state.json"
            with mock.patch("x_bot.build_candidates", return_value=[candidate]), \
                    mock.patch("x_bot.publish_post") as publish:
                self.assertEqual(x_bot.main(["--dry-run", "--state", str(state)]), 0)
            publish.assert_not_called()
            self.assertFalse(state.exists())


if __name__ == "__main__":
    unittest.main()
