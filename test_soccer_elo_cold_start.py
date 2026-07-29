import unittest

from soccer_elo_challenger import DEFAULT_PARAMS, metrics, normalize_team, replay


def match(identifier, kickoff, home, away, winner, season=2025):
    scores = {"h": (2, 0), "d": (1, 1), "a": (0, 2)}[winner]
    return {"id": identifier, "kickoff": kickoff, "competition": "EPL", "season": season,
            "home": {"name": home}, "away": {"name": away},
            "score": {"home": scores[0], "away": scores[1], "winner": winner}}


class SoccerEloColdStartTests(unittest.TestCase):
    def test_predicts_before_each_result_update(self):
        rows, state = replay([
            match("g1", "2025-08-01T12:00:00Z", "Álpha FC", "Beta FC", "h"),
            match("g2", "2025-08-08T12:00:00Z", "Alpha FC", "Beta FC", "h"),
        ], DEFAULT_PARAMS, 2025)
        self.assertEqual(rows[0]["home_games_before"], 0)
        self.assertEqual(rows[1]["home_games_before"], 1)
        self.assertGreater(rows[1]["probabilities"]["h"], rows[0]["probabilities"]["h"])
        self.assertEqual(state["games"][normalize_team("Álpha FC")], 2)

    def test_three_way_probabilities_are_valid_and_scoreable(self):
        rows, _ = replay([match("g1", "2025-08-01T12:00:00Z", "A", "B", "d")],
                         DEFAULT_PARAMS, 2025)
        self.assertAlmostEqual(sum(rows[0]["probabilities"].values()), 1.0)
        self.assertEqual(metrics(rows)["n"], 1)


if __name__ == "__main__":
    unittest.main()
