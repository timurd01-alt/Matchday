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
    def test_cross_year_season_before_start_month_belongs_to_previous_season(self):
        # February is mid-season for college basketball: it belongs to the season
        # that started the previous autumn, not to a season named for February's year.
        self.assertEqual(game_archive.season_for("NCAAM", "2026-02-08T23:30:00Z"), "2025-26")

    def test_cross_year_season_on_start_month_opens_the_new_season(self):
        self.assertEqual(game_archive.season_for("NCAAM", "2026-08-15T14:00:00Z"), "2026-27")

    def test_unknown_competition_falls_back_to_calendar_year(self):
        self.assertEqual(game_archive.season_for("XYZ", "2026-08-15T14:00:00Z"), "2026")


class GameIdTests(unittest.TestCase):
    def test_provider_id_is_preferred(self):
        self.assertEqual(
            game_archive.make_game_id("NCAAM", "2026-01-19T00:08:00Z", "A", "B", 5059251),
            "ncaam-5059251")

    def test_kickoff_time_drift_does_not_mint_a_second_id(self):
        # Providers nudge kickoff times by minutes; the fallback id keys on the
        # calendar date so that cannot duplicate a game already archived.
        first = game_archive.make_game_id("NCAAM", "2026-04-10T18:00:00Z", "Alpha", "Beta")
        second = game_archive.make_game_id("NCAAM", "2026-04-10T18:25:00Z", "Alpha", "Beta")
        self.assertEqual(first, second)

    def test_different_fixtures_get_different_ids(self):
        first = game_archive.make_game_id("NCAAM", "2026-04-10T18:00:00Z", "Alpha", "Beta")
        second = game_archive.make_game_id("NCAAM", "2026-04-10T18:00:00Z", "Beta", "Alpha")
        self.assertNotEqual(first, second)


class NormalizeTests(unittest.TestCase):
    def test_finished_game_normalizes(self):
        row = game_archive.normalize_match("NCAAM", match())
        self.assertEqual(row["comp"], "NCAAM")
        self.assertEqual((row["home_score"], row["away_score"]), (2, 1))
        self.assertEqual(row["source"], "BALLDONTLIE")

    def test_unfinished_statuses_are_refused(self):
        for status in ("UPCOMING", "LIVE", "POSTPONED", ""):
            with self.subTest(status=status):
                self.assertIsNone(game_archive.normalize_match("NCAAM", match(status=status)))

    def test_missing_score_is_refused(self):
        broken = match()
        broken["score"] = {"home": None, "away": None}
        self.assertIsNone(game_archive.normalize_match("NCAAM", broken))

    def test_missing_team_name_is_refused(self):
        broken = match()
        broken["home"] = {"name": "", "code": ""}
        self.assertIsNone(game_archive.normalize_match("NCAAM", broken))

    def test_a_shutout_is_archived(self):
        # Guards a falsy-vs-None slip: 0 is a real score, not a missing one.
        # (0-0 itself cannot be a college final; see ScorelessPlaceholderTest.)
        row = game_archive.normalize_match("NCAAF", match(home_score=0, away_score=21))
        self.assertIsNotNone(row)
        self.assertEqual((row["home_score"], row["away_score"]), (0, 21))


class UpsertTests(ArchiveTestCase):
    def test_games_are_written_and_read_back(self):
        game_archive.record_build("NCAAM", [match()])
        rows = game_archive.load_games("NCAAM")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["home_name"], "Alpha FC")

    def test_repeated_capture_is_idempotent(self):
        matches = [match(provider_id=1), match(provider_id=2, kickoff="2026-04-11T18:00:00Z")]
        first = game_archive.record_build("NCAAM", matches)
        second = game_archive.record_build("NCAAM", matches)
        self.assertEqual(first["added"], 2)
        self.assertEqual(second["added"], 0)
        self.assertEqual(second["unchanged"], 2)
        self.assertEqual(len(game_archive.load_games("NCAAM")), 2)

    def test_first_seen_is_not_refreshed_on_a_later_run(self):
        game_archive.record_build("NCAAM", [match()])
        original = game_archive.load_games("NCAAM")[0]["first_seen"]
        game_archive.record_build("NCAAM", [match()])
        self.assertEqual(game_archive.load_games("NCAAM")[0]["first_seen"], original)

    def test_a_settled_score_is_never_rewritten(self):
        game_archive.record_build("NCAAM", [match(home_score=2, away_score=1)])
        result = game_archive.record_build("NCAAM", [match(home_score=3, away_score=1)])
        self.assertEqual(result["conflicts"], 1)
        row = game_archive.load_games("NCAAM")[0]
        self.assertEqual(row["home_score"], "2", "the original score must stand")

    def test_a_refused_revision_is_recorded_for_review(self):
        game_archive.record_build("NCAAM", [match(home_score=2, away_score=1)])
        game_archive.record_build("NCAAM", [match(home_score=3, away_score=1)])
        entries = [json.loads(line) for line in
                   game_archive.CONFLICTS_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["kind"], "score_revision")
        self.assertEqual(entries[0]["incoming"]["home_score"], 3)

    def test_seasons_are_written_to_separate_partitions(self):
        game_archive.record_build("NCAAM", [
            match(provider_id=1, kickoff="2025-09-10T18:00:00Z"),
            match(provider_id=2, kickoff="2026-09-10T18:00:00Z"),
        ])
        partitions = sorted(p.name for p in (game_archive.GAMES_DIR / "ncaam").glob("*.csv"))
        self.assertEqual(partitions, ["2025-26.csv", "2026-27.csv"])

    def test_rows_are_stored_in_date_order(self):
        # The partition is rewritten in full on every change, so ordering is what
        # keeps a normal day's capture a small git delta instead of a whole-file diff.
        game_archive.record_build("NCAAM", [
            match(provider_id=3, kickoff="2026-04-12T18:00:00Z"),
            match(provider_id=1, kickoff="2026-04-10T18:00:00Z"),
            match(provider_id=2, kickoff="2026-04-11T18:00:00Z"),
        ])
        dates = [row["date_utc"] for row in game_archive.load_games("NCAAM")]
        self.assertEqual(dates, sorted(dates))

    def test_partitions_use_lf_endings_on_every_platform(self):
        game_archive.record_build("NCAAM", [match()])
        raw = (game_archive.GAMES_DIR / "ncaam" / "2025-26.csv").read_bytes()
        self.assertNotIn(b"\r\n", raw)

    def test_record_build_survives_a_malformed_match(self):
        # The hourly build publishes the site; an archive failure must degrade to
        # "nothing archived", never take the deploy down.
        result = game_archive.record_build("NCAAM", [{"status": "FINISHED"}, match()])
        self.assertEqual(result["added"], 1)


class BoxTests(ArchiveTestCase):
    def box_row(self, **extra):
        row = {"game_id": "ncaam-1", "comp": "NCAAM", "season": "2025-26",
               "date_utc": "2026-04-10T18:00:00Z", "team_name": "Alpha", "side": "home",
               "points": 78, "fga": 60, "orb": 10, "turnovers": 12, "fta": 20, "source": "test"}
        row.update(extra)
        return row

    def test_possessions_are_derived_on_write(self):
        game_archive.upsert_box([self.box_row()])
        stored = game_archive.load_box("NCAAM")[0]
        # 60 - 10 + 12 + 0.475*20 = 71.5
        self.assertEqual(float(stored["possessions"]), 71.5)

    def test_possessions_are_blank_rather_than_wrong_when_an_input_is_missing(self):
        row = self.box_row()
        del row["turnovers"]
        game_archive.upsert_box([row])
        self.assertEqual(game_archive.load_box("NCAAM")[0]["possessions"], "")

    def test_estimate_returns_none_on_a_missing_field(self):
        self.assertIsNone(game_archive.estimate_possessions({"fga": 60, "orb": 10, "fta": 20}))

    def test_both_sides_of_a_game_are_kept(self):
        game_archive.upsert_box([self.box_row(side="home"), self.box_row(side="away", team_name="Beta")])
        self.assertEqual(len(game_archive.load_box("NCAAM")), 2)

    def test_box_upsert_is_idempotent(self):
        game_archive.upsert_box([self.box_row()])
        second = game_archive.upsert_box([self.box_row()])
        self.assertEqual(second["added"], 0)


class ValidateTests(ArchiveTestCase):
    def test_a_clean_archive_reports_no_problems(self):
        game_archive.record_build("NCAAM", [match()])
        self.assertEqual(game_archive.validate()["problems"], [])

    def test_a_row_filed_under_the_wrong_season_is_caught(self):
        game_archive.record_build("NCAAM", [match()])
        partition = game_archive.GAMES_DIR / "ncaam" / "2025-26.csv"
        partition.write_text(partition.read_text(encoding="utf-8").replace("2025-26", "1999-00"),
                             encoding="utf-8", newline="")
        self.assertTrue(any("filed in" in problem for problem in game_archive.validate()["problems"]))

    def test_an_unparseable_score_is_caught(self):
        game_archive.record_build("NCAAM", [match()])
        partition = game_archive.GAMES_DIR / "ncaam" / "2025-26.csv"
        partition.write_text(partition.read_text(encoding="utf-8").replace(",2,1,FINISHED", ",n/a,1,FINISHED"),
                             encoding="utf-8", newline="")
        self.assertTrue(any("unparseable" in problem for problem in game_archive.validate()["problems"]))

    def test_summary_counts_games_per_competition(self):
        game_archive.record_build("NCAAM", [match(provider_id=1)])
        game_archive.record_build("NCAAF", [match(provider_id=2, kickoff="2026-09-01T18:00:00Z")])
        summary = game_archive.summary()
        self.assertEqual(summary["total_games"], 2)
        self.assertEqual(summary["competitions"]["NCAAM"]["games"], 1)


class OverlapResolutionTests(unittest.TestCase):
    """The backfill's cross-provider dedupe.

    The regression these cover is specific and was live: keying on the raw
    source label treated one provider's two spellings as rivals and discarded
    most of a season in favour of a hundred rows.
    """

    def row(self, source, game_id, comp="NCAAM", season="2025-26"):
        return {"game_id": game_id, "comp": comp, "season": season,
                "date_utc": "2025-12-10T18:00:00Z", "source": source}

    def test_one_provider_under_two_spellings_is_not_resolved_away(self):
        rows = [self.row("CollegeBasketballData", "ncaam-1"),
                self.row("ncaam", "ncaam-2"),
                self.row("ncaam", "ncaam-3")]
        kept, notes = archive_backfill.resolve_overlaps(rows)
        self.assertEqual(len(kept), 3, "same provider, different labels: keep every game")
        self.assertEqual(notes, [])

    def test_two_real_providers_in_one_season_resolve_to_the_pipeline_one(self):
        rows = [self.row("cbbd", "ncaam-1"), self.row("some-bulk-feed", "bulk-1")]
        kept, notes = archive_backfill.resolve_overlaps(rows)
        self.assertEqual([row["game_id"] for row in kept], ["ncaam-1"])
        self.assertEqual(len(notes), 1)

    def test_a_season_only_the_other_source_covers_is_kept(self):
        rows = [self.row("cbbd", "ncaam-1", season="2025-26"),
                self.row("some-bulk-feed", "bulk-2021", season="2021-22")]
        kept, _ = archive_backfill.resolve_overlaps(rows)
        self.assertEqual(len(kept), 2)

    def test_duplicate_game_ids_within_one_provider_collapse(self):
        rows = [self.row("cbbd", "ncaam-1"), self.row("CollegeBasketballData", "ncaam-1")]
        kept, _ = archive_backfill.resolve_overlaps(rows)
        self.assertEqual(len(kept), 1)

    def test_canonical_source_collapses_known_aliases(self):
        for label in ("ncaaf", "CollegeFootballData", "cfbd"):
            with self.subTest(label=label):
                self.assertEqual(archive_backfill.canonical_source(label), "cfbd")
        for label in ("ncaam", "CollegeBasketballData", "cbbd"):
            with self.subTest(label=label):
                self.assertEqual(archive_backfill.canonical_source(label), "cbbd")


class HandoffBackfillTest(ArchiveTestCase):
    """The handoff covers weeks the hourly hook never committed."""

    def _run(self, results, short_names):
        import os
        cwd = os.getcwd()
        work = Path(self._tmp.name) / "cwd"
        work.mkdir()
        (work / "trdlab_picks.json").write_text(json.dumps({"results": results}), encoding="utf-8")
        (work / "data_ncaaf.json").write_text(json.dumps({"matches": [
            {"home": {"name": n}, "away": {"name": "Filler"}} for n in short_names]}), encoding="utf-8")
        os.chdir(work)
        self.addCleanup(os.chdir, cwd)
        return archive_backfill.source_handoff()

    def test_uses_provider_id_and_longest_short_name(self):
        rows = self._run([{"event_id": "401", "competition": "NCAAF",
                           "kickoff": "2026-09-26T19:30Z", "home": "Michigan State Spartans",
                           "away": "Michigan Wolverines", "home_score": 20.0, "away_score": 27.0}],
                         ["Michigan", "Michigan State"])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["game_id"], "ncaaf-401")
        self.assertEqual((rows[0]["home_name"], rows[0]["away_name"]), ("Michigan State", "Michigan"))
        self.assertEqual((rows[0]["home_score"], rows[0]["away_score"]), (20, 27))

    def test_unmatched_name_is_kept_and_missing_handoff_is_silent(self):
        rows = self._run([{"event_id": "402", "competition": "NCAAF", "kickoff": "2026-09-06T17:00Z",
                           "home": "Texas A&M Aggies", "away": "Robert Morris Colonials",
                           "home_score": 56.0, "away_score": 0.0}], ["Texas A&M"])
        self.assertEqual((rows[0]["home_name"], rows[0]["away_name"]), ("Texas A&M", "Robert Morris Colonials"))
        Path("trdlab_picks.json").unlink()
        self.assertEqual(archive_backfill.source_handoff(), [])


class HandoffNameTruncationTest(ArchiveTestCase):
    """Build 1112T: "UTEP 51-10 Texas" was UTEP against Texas Southern.

    The FCS school is absent from the pipeline's names, so the character-prefix
    match fell through to the FBS school sharing its first word.
    """

    SHORTS = ["Texas", "Alabama", "Utah", "Florida", "North Carolina", "Indiana",
              "Miami", "Arkansas", "Michigan", "Michigan State", "Louisiana", "Hawai'i"]

    def mapped(self, *names):
        return archive_backfill.handoff_name_map(names, self.SHORTS)

    def test_an_fcs_school_is_never_cut_to_the_fbs_school_it_starts_with(self):
        names = self.mapped("Texas Southern Tigers", "Alabama State Hornets", "Utah Tech Trailblazers",
                            "Florida A&M Rattlers", "Indiana State Sycamores",
                            "North Carolina Central Eagles", "Arkansas-Pine Bluff Golden Lions",
                            "Miami (OH) RedHawks")
        for full, archived in names.items():
            with self.subTest(full=full):
                self.assertEqual(archived, full)

    def test_the_fbs_school_itself_still_maps_to_its_short_name(self):
        names = self.mapped("Texas Longhorns", "Texas Southern Tigers", "North Carolina Tar Heels",
                            "North Carolina A&T Aggies", "Louisiana Ragin' Cajuns",
                            "Hawai'i Rainbow Warriors", "Michigan State Spartans", "Michigan Wolverines")
        self.assertEqual(names["Texas Longhorns"], "Texas")
        self.assertEqual(names["North Carolina Tar Heels"], "North Carolina")
        self.assertEqual(names["Louisiana Ragin' Cajuns"], "Louisiana")
        self.assertEqual(names["Hawai'i Rainbow Warriors"], "Hawai'i")
        self.assertEqual(names["Michigan State Spartans"], "Michigan State")
        self.assertEqual(names["Michigan Wolverines"], "Michigan")

    def test_two_names_landing_on_one_school_both_keep_their_full_form(self):
        # Neither remainder reads as a qualifier, so only the collision shows
        # that one of them is not Utah. Guessing would record a false game.
        names = self.mapped("Utah Utes", "Utah Valiants")
        self.assertEqual(names, {"Utah Utes": "Utah Utes", "Utah Valiants": "Utah Valiants"})

    def test_a_short_name_must_end_on_a_word(self):
        self.assertEqual(self.mapped("Texans Mascots"), {"Texans Mascots": "Texans Mascots"})


class HandoffBasketballSkippedTest(ArchiveTestCase):
    def test_ncaam_results_are_not_archived_from_the_handoff(self):
        import os
        cwd = os.getcwd()
        work = Path(self._tmp.name) / "cwd"
        work.mkdir()
        (work / "trdlab_picks.json").write_text(json.dumps({"results": [
            {"event_id": "401920982", "competition": "NCAAM", "kickoff": "2026-11-01T14:30Z",
             "home": "Villanova Wildcats", "away": "Notre Dame Fighting Irish",
             "home_score": 72.0, "away_score": 74.0}]}), encoding="utf-8")
        os.chdir(work)
        self.addCleanup(os.chdir, cwd)
        # ESPN numbers the game 401920982, CBBD 377909: no row could dedupe.
        self.assertEqual(archive_backfill.source_handoff(), [])


class OverlapAgainstArchiveTest(unittest.TestCase):
    """A run of one source used to see one provider and resolve nothing."""

    def row(self, source, game_id):
        return {"game_id": game_id, "comp": "NCAAM", "season": "2026-27",
                "date_utc": "2026-11-03T00:00:00Z", "source": source}

    def test_a_season_the_pipeline_already_owns_refuses_a_bulk_provider(self):
        on_disk = [self.row("cbbd", "ncaam-377909")]
        kept, notes = archive_backfill.resolve_overlaps(
            [self.row("espn", "ncaam-401920982")], lambda comp, season: on_disk)
        self.assertEqual(kept, [])
        self.assertEqual(len(notes), 1)

    def test_the_owning_provider_still_adds_games(self):
        on_disk = [self.row("cbbd", "ncaam-377909")]
        kept, notes = archive_backfill.resolve_overlaps(
            [self.row("CollegeBasketballData", "ncaam-377910")], lambda comp, season: on_disk)
        self.assertEqual([row["game_id"] for row in kept], ["ncaam-377910"])
        self.assertEqual(notes, [])


class CrossIdDuplicateTest(ArchiveTestCase):
    def row(self, game_id, source, home, away, hs, as_, when="2026-11-02T16:30:00Z"):
        return {"game_id": game_id, "comp": "NCAAM", "season": "2026-27", "date_utc": when,
                "home_name": home, "away_name": away, "home_score": hs, "away_score": as_,
                "status": "FINISHED", "source": source}

    def test_one_game_under_two_providers_is_reported(self):
        rows = [self.row("ncaam-1", "cbbd", "Hofstra", "Saint Joseph's Long Island", 97, 51),
                self.row("ncaam-401", "ncaam", "Hofstra", "St. Joseph's Long Island Golden Eagles", 97, 51,
                         when="2026-11-02T16:30Z")]
        pairs = game_archive.cross_id_duplicates(rows)
        self.assertEqual([(one["game_id"], two["game_id"]) for one, two in pairs], [("ncaam-1", "ncaam-401")])
        game_archive._write_partition(game_archive.partition_path("games", "NCAAM", "2026-27"),
                                      game_archive.GAME_FIELDS, rows)
        self.assertTrue(any("archived twice" in p for p in game_archive.validate()["problems"]))

    def test_same_score_same_day_different_teams_is_silent(self):
        rows = [self.row("ncaam-1", "cbbd", "Duke", "Army", 84, 50),
                self.row("ncaam-2", "cbbd", "Kansas", "Howard", 84, 50)]
        self.assertEqual(game_archive.cross_id_duplicates(rows), [])

    def test_a_rematch_days_later_is_silent(self):
        rows = [self.row("ncaam-1", "cbbd", "Duke", "Army", 84, 50),
                self.row("ncaam-2", "cbbd", "Duke", "Army", 84, 50, when="2026-11-09T16:30:00Z")]
        self.assertEqual(game_archive.cross_id_duplicates(rows), [])


class ArchiveRepairTest(ArchiveTestCase):
    def write(self, comp, rows):
        game_archive._write_partition(game_archive.partition_path("games", comp, "2026-27"),
                                      game_archive.GAME_FIELDS, rows)

    def read(self, comp):
        return game_archive.read_partition(game_archive.partition_path("games", comp, "2026-27"))

    def log(self):
        path = game_archive.ARCHIVE_ROOT / "corrections.jsonl"
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

    def football(self, game_id, home, away, hs, as_, source="ncaaf"):
        return {"game_id": game_id, "comp": "NCAAF", "season": "2026-27", "date_utc": "2026-09-06T17:00Z",
                "home_name": home, "away_name": away, "home_score": hs, "away_score": as_,
                "status": "FINISHED", "source": source, "first_seen": "2026-10-21T17:21:10+00:00"}

    def test_names_are_corrected_scores_are_not_and_every_change_is_logged(self):
        import archive_repair
        self.write("NCAAF", [self.football("ncaaf-1", "UTEP", "Texas", 51, 10),
                             self.football("ncaaf-2", "Texas", "Rice", 38, 7),
                             self.football("ncaaf-3", "Troy", "Alabama", 34, 17)])
        handoff = {"results": [
            {"event_id": "1", "competition": "NCAAF", "home": "UTEP Miners", "away": "Texas Southern Tigers",
             "home_score": 51.0, "away_score": 10.0},
            {"event_id": "2", "competition": "NCAAF", "home": "Texas Longhorns", "away": "Rice Owls",
             "home_score": 38.0, "away_score": 7.0},
            # A different final than the archive's: the row is left alone.
            {"event_id": "3", "competition": "NCAAF", "home": "Troy Trojans", "away": "Alabama State Hornets",
             "home_score": 35.0, "away_score": 17.0}]}
        shorts = ["UTEP", "Texas", "Rice", "Troy", "Alabama"]
        result = archive_repair.correct_names([handoff], shorts=shorts)
        self.assertEqual(result, {"checked": 3, "corrected": 1, "skipped": 1})
        rows = {row["game_id"]: row for row in self.read("NCAAF")}
        self.assertEqual((rows["ncaaf-1"]["away_name"], rows["ncaaf-1"]["home_score"],
                          rows["ncaaf-1"]["away_score"]), ("Texas Southern Tigers", "51", "10"))
        self.assertEqual(rows["ncaaf-2"]["home_name"], "Texas")
        self.assertEqual(rows["ncaaf-3"]["away_name"], "Alabama")
        kinds = sorted(entry["kind"] for entry in self.log())
        self.assertEqual(kinds, ["name_correction_skipped", "team_name_correction"])
        self.assertEqual(archive_repair.correct_names([handoff], shorts=shorts)["corrected"], 0)

    def test_foreign_id_rows_are_removed_logged_and_the_pipeline_rows_kept(self):
        import archive_repair
        base = {"comp": "NCAAM", "season": "2026-27", "status": "FINISHED", "first_seen": "x"}
        self.write("NCAAM", [
            dict(base, game_id="ncaam-377909", date_utc="2026-11-01T14:30:00Z", home_name="Villanova",
                 away_name="Notre Dame", home_score=72, away_score=74, source="cbbd"),
            dict(base, game_id="ncaam-401920982", date_utc="2026-11-01T14:30Z", home_name="Villanova",
                 away_name="Notre Dame", home_score=72, away_score=74, source="ncaam"),
            dict(base, game_id="ncaam-401999999", date_utc="2026-11-02T23:00Z", home_name="Florida",
                 away_name="Miami", home_score=77, away_score=67, source="ncaam")])
        handoff = {"results": [{"event_id": "401920982", "competition": "NCAAM"},
                               {"event_id": "401999999", "competition": "NCAAM"}]}
        result = archive_repair.remove_foreign_ids([handoff])
        self.assertEqual(result, {"removed": 2, "with_pipeline_twin": 1, "without": 1})
        self.assertEqual([row["game_id"] for row in self.read("NCAAM")], ["ncaam-377909"])
        twins = {entry["game_id"]: entry["pipeline_twin"] for entry in self.log()}
        self.assertEqual(twins, {"ncaam-401920982": "ncaam-377909", "ncaam-401999999": None})
        self.assertEqual(archive_repair.remove_foreign_ids([handoff])["removed"], 0)


class ScorelessPlaceholderTest(unittest.TestCase):
    def test_a_college_zero_zero_final_is_not_archived(self):
        game = {"id": "cbbd-374807", "kickoff": "2026-11-10T00:00:00Z", "status": "FINISHED",
                "score": {"home": 0, "away": 0}, "home": {"name": "Alabama State"},
                "away": {"name": "Georgia College"}}
        self.assertIsNone(game_archive.normalize_match("NCAAM", game, "cbbd"))
        game["score"] = {"home": 81, "away": 60}
        self.assertIsNotNone(game_archive.normalize_match("NCAAM", game, "cbbd"))


if __name__ == "__main__":
    unittest.main()
