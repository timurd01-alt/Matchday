"""The ship refuses a handoff built on missing results, wrong records or drifted scores."""
import datetime as dt
import unittest

import check_handoff_integrity as chi

NOW = dt.datetime(2026, 10, 18, 14, 0, tzinfo=dt.timezone.utc)


def doc(fixtures=(), results=(), rankings=(), picks=()):
    return {"fixtures": list(fixtures), "results": list(results), "picks": list(picks),
            "rankings": {"ncaaf": {"rankings": list(rankings)}}}


def fixture(i, kickoff="2026-10-17T19:30Z", status="pre"):
    return {"event_id": str(i), "sport": "ncaaf", "kickoff": kickoff, "status": status,
            "home": f"Home {i}", "away": f"Away {i}"}


def result(i, home, away, hs, as_):
    return {"event_id": str(i), "sport": "ncaaf", "season": 2026, "home": home, "away": away,
            "home_score": hs, "away_score": as_}


class IntegrityTests(unittest.TestCase):
    def test_a_week_of_unscored_games_is_refused(self):
        ok, lines = chi.check(doc(fixtures=[fixture(i) for i in range(29)]), NOW)
        self.assertFalse(ok)
        self.assertIn("poller", lines[0])

    def test_scored_and_future_games_pass(self):
        fx = [fixture(1), fixture(2, kickoff="2026-10-24T19:30Z")]
        ok, _ = chi.check(doc(fixtures=fx, results=[result(1, "Home 1", "Away 1", 21, 14)]), NOW)
        self.assertTrue(ok)

    def test_byu_published_unbeaten_after_a_loss_is_refused(self):
        results = [result(i, "BYU Cougars", f"Opp {i}", 30, 10) for i in range(5)] + \
                  [result(9, "BYU Cougars", "Notre Dame Fighting Irish", 24, 28)]
        rankings = [{"team_name": "BYU Cougars", "rank": r, "wins": 6, "losses": 0} for r in (19, 20, 21)]
        ok, lines = chi.check(doc(results=results, rankings=rankings), NOW)
        self.assertFalse(ok)
        self.assertIn("records", lines[0])

    def test_projected_scores_far_from_the_line_are_refused(self):
        picks = [{"projected_score": {"home": 38, "away": 20}, "model_line": {"home_margin": 6.4}}] * 10
        ok, lines = chi.check(doc(picks=picks), NOW)
        self.assertFalse(ok)
        self.assertIn("model line", lines[0])

    def test_scores_close_to_the_line_pass(self):
        picks = [{"projected_score": {"home": 27, "away": 23}, "model_line": {"home_margin": 4.0}}] * 10
        self.assertTrue(chi.check(doc(picks=picks), NOW)[0])


if __name__ == "__main__":
    unittest.main()
