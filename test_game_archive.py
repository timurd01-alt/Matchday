"""Tests for the durable game archive and its free-source backfill.

Every test here isolates the archive to a temporary directory. The module
resolves its paths from `ARCHIVE_ROOT` at call time via the `GAMES_DIR` /
`BOX_DIR` / `CONFLICTS_PATH` module constants, so redirecting those is enough --
and it must be done, or running the suite would append test fixtures to the real
35,000-game archive.
"""

import json
import tempfile
import unittest
from pathlib import Path

import archive_backfill
import game_archive


def match(status="FINISHED", home_score=2, away_score=1, kickoff="2026-04-10T18:00:00Z",
          home="Alpha FC", away="Beta FC", provider_id=101, **extra):
    payload = {
        "id": f"bdl-{provider_id}",
        "provider_id": provider_id,
        "stage": "Regular",
        "venue": "Test Park",
        "kickoff": kickoff,
        "status": status,
        "score": {"home": home_score, "away": away_score},
        "home": {"name": home, "code": home[:3].upper()},
        "away": {"name": away, "code": away[:3].upper()},
        "data_source": "BALLDONTLIE",
    }
    payload.update(extra)
    return payload


class ArchiveTestCase(unittest.TestCase):
    """Redirects the archive at a temp dir for the lifetime of each test."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self._saved = (game_archive.ARCHIVE_ROOT, game_archive.GAMES_DIR,
                       game_archive.BOX_DIR, game_archive.CONFLICTS_PATH)
        game_archive.ARCHIVE_ROOT = root
        game_archive.GAMES_DIR = root / "games"
        game_archive.BOX_DIR = root / "box"
        game_archive.CONFLICTS_PATH = root / "conflicts.jsonl"
        self.addCleanup(self._restore)

    def _restore(self):
        (game_archive.ARCHIVE_ROOT, game_archive.GAMES_DIR,
         game_archive.BOX_DIR, game_archive.CONFLICTS_PATH) = self._saved
        self._tmp.cleanup()


class SeasonTests(unittest.TestCase):
    def test_single_calendar_year_sport_uses_the_year(self):
        self.assertEqual(game_archive.season_for("MLB", "2026-07-19T00:08:00Z"), "2026")

    def test_cross_year_season_before_start_month_belongs_to_previous_season(self):
        # February is mid-season for the NFL: it belongs to the season that
        # started the previous autumn, not to a season named for February's year.
        self.assertEqual(game_archive.season_for("NFL", "2026-02-08T23:30:00Z"), "2025-26")

    def test_cross_year_season_on_start_month_opens_the_new_season(self):
        self.assertEqual(game_archive.season_for("EPL", "2026-08-15T14:00:00Z"), "2026-27")

    def test_unknown_competition_falls_back_to_calendar_year(self):
        self.assertEqual(game_archive.season_for("XYZ", "2026-08-15T14:00:00Z"), "2026")


class GameIdTests(unittest.TestCase):
    def test_provider_id_is_preferred(self):
        self.assertEqual(
            game_archive.make_game_id("MLB", "2026-07-19T00:08:00Z", "A", "B", 5059251),
            "mlb-5059251")

    def test_kickoff_time_drift_does_not_mint_a_second_id(self):
        # Providers nudge kickoff times by minutes; the fallback id keys on the
        # calendar date so that cannot duplicate a game already archived.
        first = game_archive.make_game_id("EPL", "2026-04-10T18:00:00Z", "Alpha", "Beta")
        second = game_archive.make_game_id("EPL", "2026-04-10T18:25:00Z", "Alpha", "Beta")
        self.assertEqual(first, second)

    def test_different_fixtures_get_different_ids(self):
        first = game_archive.make_game_id("EPL", "2026-04-10T18:00:00Z", "Alpha", "Beta")
        second = game_archive.make_game_id("EPL", "2026-04-10T18:00:00Z", "Beta", "Alpha")
        self.assertNotEqual(first, second)


class NormalizeTests(unittest.TestCase):
    def test_finished_game_normalizes(self):
        row = game_archive.normalize_match("EPL", match())
        self.assertEqual(row["comp"], "EPL")
        self.assertEqual((row["home_score"], row["away_score"]), (2, 1))
        self.assertEqual(row["source"], "BALLDONTLIE")

    def test_unfinished_statuses_are_refused(self):
        for status in ("UPCOMING", "LIVE", "POSTPONED", ""):
            with self.subTest(status=status):
                self.assertIsNone(game_archive.normalize_match("EPL", match(status=status)))

    def test_missing_score_is_refused(self):
        broken = match()
        broken["score"] = {"home": None, "away": None}
        self.assertIsNone(game_archive.normalize_match("EPL", broken))

    def test_missing_team_name_is_refused(self):
        broken = match()
        broken["home"] = {"name": "", "code": ""}
        self.assertIsNone(game_archive.normalize_match("EPL", broken))

    def test_a_zero_zero_draw_is_archived(self):
        # Guards a falsy-vs-None slip: 0 is a real score, not a missing one.
        row = game_archive.normalize_match("EPL", match(home_score=0, away_score=0))
        self.assertIsNotNone(row)
        self.assertEqual((row["home_score"], row["away_score"]), (0, 0))


class UpsertTests(ArchiveTestCase):
    def test_games_are_written_and_read_back(self):
        game_archive.record_build("EPL", [match()])
        rows = game_archive.load_games("EPL")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["home_name"], "Alpha FC")

    def test_repeated_capture_is_idempotent(self):
        matches = [match(provider_id=1), match(provider_id=2, kickoff="2026-04-11T18:00:00Z")]
        first = game_archive.record_build("EPL", matches)
        second = game_archive.record_build("EPL", matches)
        self.assertEqual(first["added"], 2)
        self.assertEqual(second["added"], 0)
        self.assertEqual(second["unchanged"], 2)
        self.assertEqual(len(game_archive.load_games("EPL")), 2)

    def test_first_seen_is_not_refreshed_on_a_later_run(self):
        game_archive.record_build("EPL", [match()])
        original = game_archive.load_games("EPL")[0]["first_seen"]
        game_archive.record_build("EPL", [match()])
        self.assertEqual(game_archive.load_games("EPL")[0]["first_seen"], original)

    def test_a_settled_score_is_never_rewritten(self):
        game_archive.record_build("EPL", [match(home_score=2, away_score=1)])
        result = game_archive.record_build("EPL", [match(home_score=3, away_score=1)])
        self.assertEqual(result["conflicts"], 1)
        row = game_archive.load_games("EPL")[0]
        self.assertEqual(row["home_score"], "2", "the original score must stand")

    def test_a_refused_revision_is_recorded_for_review(self):
        game_archive.record_build("EPL", [match(home_score=2, away_score=1)])
        game_archive.record_build("EPL", [match(home_score=3, away_score=1)])
        entries = [json.loads(line) for line in
                   game_archive.CONFLICTS_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["kind"], "score_revision")
        self.assertEqual(entries[0]["incoming"]["home_score"], 3)

    def test_seasons_are_written_to_separate_partitions(self):
        game_archive.record_build("EPL", [
            match(provider_id=1, kickoff="2025-09-10T18:00:00Z"),
            match(provider_id=2, kickoff="2026-09-10T18:00:00Z"),
        ])
        partitions = sorted(p.name for p in (game_archive.GAMES_DIR / "epl").glob("*.csv"))
        self.assertEqual(partitions, ["2025-26.csv", "2026-27.csv"])

    def test_rows_are_stored_in_date_order(self):
        # The partition is rewritten in full on every change, so ordering is what
        # keeps a normal day's capture a small git delta instead of a whole-file diff.
        game_archive.record_build("MLB", [
            match(provider_id=3, kickoff="2026-04-12T18:00:00Z"),
            match(provider_id=1, kickoff="2026-04-10T18:00:00Z"),
            match(provider_id=2, kickoff="2026-04-11T18:00:00Z"),
        ])
        dates = [row["date_utc"] for row in game_archive.load_games("MLB")]
        self.assertEqual(dates, sorted(dates))

    def test_partitions_use_lf_endings_on_every_platform(self):
        game_archive.record_build("EPL", [match()])
        raw = (game_archive.GAMES_DIR / "epl" / "2025-26.csv").read_bytes()
        self.assertNotIn(b"\r\n", raw)

    def test_record_build_survives_a_malformed_match(self):
        # The hourly build publishes the site; an archive failure must degrade to
        # "nothing archived", never take the deploy down.
        result = game_archive.record_build("EPL", [{"status": "FINISHED"}, match()])
        self.assertEqual(result["added"], 1)


class BoxTests(ArchiveTestCase):
    def box_row(self, **extra):
        row = {"game_id": "epl-1", "comp": "EPL", "season": "2025-26",
               "date_utc": "2026-04-10T18:00:00Z", "team_name": "Alpha", "side": "home",
               "points": 78, "fga": 60, "orb": 10, "turnovers": 12, "fta": 20, "source": "test"}
        row.update(extra)
        return row

    def test_possessions_are_derived_on_write(self):
        game_archive.upsert_box([self.box_row()])
        stored = game_archive.load_box("EPL")[0]
        # 60 - 10 + 12 + 0.475*20 = 71.5
        self.assertEqual(float(stored["possessions"]), 71.5)

    def test_possessions_are_blank_rather_than_wrong_when_an_input_is_missing(self):
        row = self.box_row()
        del row["turnovers"]
        game_archive.upsert_box([row])
        self.assertEqual(game_archive.load_box("EPL")[0]["possessions"], "")

    def test_estimate_returns_none_on_a_missing_field(self):
        self.assertIsNone(game_archive.estimate_possessions({"fga": 60, "orb": 10, "fta": 20}))

    def test_both_sides_of_a_game_are_kept(self):
        game_archive.upsert_box([self.box_row(side="home"), self.box_row(side="away", team_name="Beta")])
        self.assertEqual(len(game_archive.load_box("EPL")), 2)

    def test_box_upsert_is_idempotent(self):
        game_archive.upsert_box([self.box_row()])
        second = game_archive.upsert_box([self.box_row()])
        self.assertEqual(second["added"], 0)


class ValidateTests(ArchiveTestCase):
    def test_a_clean_archive_reports_no_problems(self):
        game_archive.record_build("EPL", [match()])
        self.assertEqual(game_archive.validate()["problems"], [])

    def test_a_row_filed_under_the_wrong_season_is_caught(self):
        game_archive.record_build("EPL", [match()])
        partition = game_archive.GAMES_DIR / "epl" / "2025-26.csv"
        partition.write_text(partition.read_text(encoding="utf-8").replace("2025-26", "1999-00"),
                             encoding="utf-8", newline="")
        self.assertTrue(any("filed in" in problem for problem in game_archive.validate()["problems"]))

    def test_an_unparseable_score_is_caught(self):
        game_archive.record_build("EPL", [match()])
        partition = game_archive.GAMES_DIR / "epl" / "2025-26.csv"
        partition.write_text(partition.read_text(encoding="utf-8").replace(",2,1,FINISHED", ",n/a,1,FINISHED"),
                             encoding="utf-8", newline="")
        self.assertTrue(any("unparseable" in problem for problem in game_archive.validate()["problems"]))

    def test_summary_counts_games_per_competition(self):
        game_archive.record_build("EPL", [match(provider_id=1)])
        game_archive.record_build("MLB", [match(provider_id=2, kickoff="2026-07-01T18:00:00Z")])
        summary = game_archive.summary()
        self.assertEqual(summary["total_games"], 2)
        self.assertEqual(summary["competitions"]["EPL"]["games"], 1)


class OverlapResolutionTests(unittest.TestCase):
    """The backfill's cross-provider dedupe.

    The regression these cover is specific and was live: keying on the raw
    source label treated one provider's two spellings as rivals and discarded
    1,698 of 1,698 MLB games in favour of 113.
    """

    def row(self, source, game_id, comp="NFL", season="2025-26"):
        return {"game_id": game_id, "comp": comp, "season": season,
                "date_utc": "2025-09-10T18:00:00Z", "source": source}

    def test_one_provider_under_two_spellings_is_not_resolved_away(self):
        rows = [self.row("BALLDONTLIE", "mlb-1", "MLB", "2026"),
                self.row("balldontlie", "mlb-2", "MLB", "2026"),
                self.row("balldontlie", "mlb-3", "MLB", "2026")]
        kept, notes = archive_backfill.resolve_overlaps(rows)
        self.assertEqual(len(kept), 3, "same provider, different labels: keep every game")
        self.assertEqual(notes, [])

    def test_two_real_providers_in_one_season_resolve_to_the_pipeline_one(self):
        rows = [self.row("balldontlie", "nfl-1"), self.row("nflverse", "nfl-2021-01-ari-ten")]
        kept, notes = archive_backfill.resolve_overlaps(rows)
        self.assertEqual([row["game_id"] for row in kept], ["nfl-1"])
        self.assertEqual(len(notes), 1)

    def test_a_season_only_the_bulk_source_covers_is_kept(self):
        # Season-scoped, so nflverse still supplies the four seasons BallDontLie
        # has no cache for.
        rows = [self.row("balldontlie", "nfl-1", season="2025-26"),
                self.row("nflverse", "nfl-2021", season="2021-22")]
        kept, _ = archive_backfill.resolve_overlaps(rows)
        self.assertEqual(len(kept), 2)

    def test_duplicate_game_ids_within_one_provider_collapse(self):
        rows = [self.row("balldontlie", "nfl-1"), self.row("BALLDONTLIE", "nfl-1")]
        kept, _ = archive_backfill.resolve_overlaps(rows)
        self.assertEqual(len(kept), 1)

    def test_canonical_source_collapses_known_aliases(self):
        for label in ("BALLDONTLIE", "balldontlie", "bdl"):
            with self.subTest(label=label):
                self.assertEqual(archive_backfill.canonical_source(label), "balldontlie")
        for label in ("ncaam", "CollegeBasketballData", "cbbd"):
            with self.subTest(label=label):
                self.assertEqual(archive_backfill.canonical_source(label), "cbbd")


if __name__ == "__main__":
    unittest.main()
