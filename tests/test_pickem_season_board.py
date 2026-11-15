"""Pick 'Em season board: picks must grade, and players under the minimum must show.

2026-11-15: a player with ten picks saw "No one has 10 graded picks yet". The
server graded a pick only against data_<comp>.json, which holds the current
slate alone, so a pick whose game rolled off it before its owner synced could
never be graded; guests synced only when their own browser graded something;
and the Season board dropped everyone under ten graded picks.
"""
import csv
import datetime as dt
import json
import pathlib
import tempfile
import unittest

import build_team_form

ROOT = pathlib.Path(__file__).resolve().parent.parent


class SeasonFinalsFeedTests(unittest.TestCase):
    def test_finals_are_published_as_json_for_the_grader(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            source = root / "archive/games/ncaaf/2026-27.csv"
            source.parent.mkdir(parents=True)
            fields = ["game_id", "comp", "season", "date_utc", "stage", "venue", "home_name", "home_code",
                      "away_name", "away_code", "home_score", "away_score", "status", "source", "first_seen"]
            with source.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                writer.writerow(dict.fromkeys(fields, "") | {
                    "game_id": "ncaaf-401858521", "date_utc": "2026-11-14T22:30:00Z", "home_name": "Michigan State",
                    "away_name": "Washington", "home_score": "14", "away_score": "21", "status": "FINISHED"})
                writer.writerow(dict.fromkeys(fields, "") | {
                    "game_id": "ncaaf-401858529", "home_name": "Michigan State", "away_name": "Oregon",
                    "status": "UPCOMING"})
            out = root / "_site"
            build_team_form.build(out, root, today=dt.date(2026, 11, 15))
            published = json.loads((out / "team-form-history.json").read_text(encoding="utf-8"))
            self.assertEqual([g["id"] for g in published["ncaaf"]], ["ncaaf-401858521"])
            self.assertEqual(published["ncaaf"][0]["score"], {"home": 14, "away": 21})
            self.assertTrue((out / "team-form-history.js").exists())


class ServerGradingTests(unittest.TestCase):
    def setUp(self):
        self.source = (ROOT / "api" / "leaderboard.js").read_text(encoding="utf-8")

    def test_pick_off_the_slate_grades_from_season_finals(self):
        grade = self.source[self.source.index("async function gradeAndCount("):self.source.index("async function syncOwner(")]
        self.assertIn("if (!match) {", grade)
        self.assertIn("await loadSeasonFinals()", grade)
        self.assertIn("numericId(row.match_id)", grade)
        loader = self.source[self.source.index("async function loadSeasonFinals("):self.source.index("async function lockPick(")]
        self.assertIn("${PUBLIC_DATA_ORIGIN}/team-form-history.json", loader)
        self.assertIn('redirect: "error"', loader)

    def test_a_tied_final_never_grades(self):
        winner = self.source[self.source.index("function finalWinner("):self.source.index("async function lockPick(")]
        self.assertIn("home === away) return \"\"", winner)

    def test_season_board_lists_players_under_the_minimum_unranked(self):
        board = self.source[self.source.index("async function leaderboard("):self.source.index("async function consensus(")]
        self.assertNotIn("HAVING", board)
        self.assertIn("ORDER BY (COUNT(*) >= $2) DESC", board)
        self.assertIn("qualified: row.graded >= minimum", board)


class ClientBoardTests(unittest.TestCase):
    def setUp(self):
        self.views = (ROOT / "app-2-views.js").read_text(encoding="utf-8")

    def test_opening_pick_em_syncs_before_reading_the_board(self):
        load = self.views[self.views.index("function commLoad("):self.views.index("let COMM_BOARD=null")]
        self.assertIn("pushScore()", load)
        self.assertLess(load.index("pushScore()"), load.index("fetchLeaderboard("))

    def test_unqualified_players_render_unranked_with_their_own_row_kept(self):
        render = self.views[self.views.index("function renderCommunity("):self.views.index("// Recent activity.")]
        self.assertNotIn("No one has 10 graded picks yet.", render)
        self.assertIn("r.qualified===false", render)
        self.assertIn("waiting.find(r=>r.handle===me)", render)
        self.assertIn("rank<0?'–':rank+1", render)


if __name__ == "__main__":
    unittest.main()
