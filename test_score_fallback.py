"""Final scores from the scoreboard: settle what is certain, leave the rest."""

import datetime as dt
import unittest

import score_fallback

NOW = dt.datetime(2026, 9, 12, 19, 0, tzinfo=dt.timezone.utc)


def fixture(home, away, kickoff="2026-09-11T23:30:00.000Z", status="UPCOMING"):
    return {"id": f"{home}-{away}", "kickoff": kickoff, "status": status,
            "score": {"home": None, "away": None},
            "home": {"name": home}, "away": {"name": away}}


def team(location, display, short=None):
    return {"location": location, "displayName": display, "shortDisplayName": short or location}


def event(home, away, home_score, away_score, date="2026-09-11T23:30Z", completed=True):
    return {"date": date, "competitions": [{
        "date": date,
        "status": {"type": {"completed": completed}},
        "competitors": [
            {"homeAway": "home", "score": str(home_score), "team": home},
            {"homeAway": "away", "score": str(away_score), "team": away},
        ]}]}


class ScoreFallbackTests(unittest.TestCase):
    def run_with(self, matches, events):
        asked = []

        def fetch(url):
            asked.append(url)
            return {"events": events}
        return score_fallback.settle(matches, "NCAAF", now=NOW, fetch=fetch), asked

    def test_a_played_fixture_takes_the_final_score_and_nothing_else(self):
        match = fixture("Boston College", "Rutgers")
        report, asked = self.run_with([match], [event(
            team("Boston College", "Boston College Eagles"),
            team("Rutgers", "Rutgers Scarlet Knights"), 28, 21)])
        self.assertEqual(report["settled"], 1)
        self.assertEqual(match["status"], "FINISHED")
        self.assertEqual((match["score"]["home"], match["score"]["away"]), (28, 21))
        self.assertEqual(match["score"]["winner"], "h")
        self.assertIn("ESPN", match["score_source"])
        # Friday 23:30Z is Friday evening in the East, which is the day ESPN
        # files it under.
        self.assertIn("dates=20260911", asked[0])

    def test_names_are_matched_across_accents_and_ampersands(self):
        match = fixture("Miami", "Florida A&M", kickoff="2026-09-11T00:00:00.000Z")
        report, asked = self.run_with([match], [event(
            team("Miami", "Miami Hurricanes"), team("Florida A&M", "Florida A&M Rattlers"),
            52, 3, date="2026-09-11T00:00Z")])
        self.assertEqual(report["settled"], 1)
        self.assertIn("dates=20260910", asked[0])

    def test_a_neutral_site_game_listed_the_other_way_round_keeps_our_sides(self):
        match = fixture("Home U", "Away U")
        self.run_with([match], [event(team("Away U", "Away U Owls"),
                                      team("Home U", "Home U Hawks"), 30, 10)])
        self.assertEqual((match["score"]["home"], match["score"]["away"]), (10, 30))

    def test_a_game_not_yet_final_is_left_alone(self):
        match = fixture("Boston College", "Rutgers")
        report, _ = self.run_with([match], [event(
            team("Boston College", "Boston College Eagles"),
            team("Rutgers", "Rutgers Scarlet Knights"), 14, 7, completed=False)])
        self.assertEqual(report["settled"], 0)
        self.assertEqual(match["status"], "UPCOMING")

    def test_one_matching_team_is_not_a_match(self):
        match = fixture("Miami", "Florida A&M")
        report, _ = self.run_with([match], [event(
            team("Miami (OH)", "Miami (OH) RedHawks"), team("Florida A&M", "Florida A&M Rattlers"),
            20, 17)])
        self.assertEqual(report["settled"], 0)

    def test_a_scoreboard_game_on_another_kickoff_is_not_this_one(self):
        match = fixture("Boston College", "Rutgers", kickoff="2026-09-11T12:00:00.000Z")
        report, _ = self.run_with([match], [event(
            team("Boston College", "Boston College Eagles"),
            team("Rutgers", "Rutgers Scarlet Knights"), 28, 21, date="2026-09-11T23:30Z")])
        self.assertEqual(report["settled"], 0)

    def test_nothing_is_requested_for_games_still_being_played_or_already_final(self):
        playing = fixture("A", "B", kickoff="2026-09-12T17:00:00.000Z")
        finished = fixture("C", "D", status="FINISHED")
        report, asked = self.run_with([playing, finished], [])
        self.assertEqual((report["candidates"], asked), (0, []))

    def test_a_failed_request_leaves_fixtures_unsettled_and_says_so(self):
        match = fixture("Boston College", "Rutgers")

        def broken(url):
            raise OSError("timed out")
        report = score_fallback.settle([match], "NCAAF", now=NOW, fetch=broken)
        self.assertEqual(report["settled"], 0)
        self.assertEqual(len(report["errors"]), 1)
        self.assertEqual(match["status"], "UPCOMING")

    def test_competitions_without_a_scoreboard_are_untouched(self):
        match = fixture("A", "B")
        report = score_fallback.settle([match], "NCAAM", now=NOW, fetch=lambda url: 1 / 0)
        self.assertEqual(report["candidates"], 0)


if __name__ == "__main__":
    unittest.main()
