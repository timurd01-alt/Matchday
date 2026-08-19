import json
import tempfile
import unittest
from pathlib import Path

import ncaam_advanced_metrics as ncaam
from ncaam_advanced_metrics import (MappingUnverified, REQUIRED, build_profiles,
                                    normalize, refresh, verify_mapping)


def box(game_id="g1", team="Duke", opponent="Kansas", points=75, fgm=28, fga=60,
        tpm=8, tpa=22, fta=15, orb=10, drb=25, tov=11, date="2026-11-10T23:00:00Z"):
    return {"gameId": game_id, "team": team, "opponent": opponent,
            "startDate": date, "points": points,
            "fieldGoalsMade": fgm, "fieldGoalsAttempted": fga,
            "threePointFieldGoalsMade": tpm, "threePointFieldGoalsAttempted": tpa,
            "freeThrowsAttempted": fta, "offensiveRebounds": orb,
            "defensiveRebounds": drb, "turnovers": tov}


def paired_season(games=10, teams=("Duke", "Kansas", "Iowa", "Baylor")):
    rows = []
    for index in range(games):
        home, away = teams[index % len(teams)], teams[(index + 1) % len(teams)]
        gid = f"g{index}"
        day = 10 + (index % 18)
        rows.append(box(gid, home, away, points=78, date=f"2026-11-{day:02d}T23:00:00Z"))
        rows.append(box(gid, away, home, points=70, date=f"2026-11-{day:02d}T23:00:00Z"))
    return rows


class NormalizeTest(unittest.TestCase):
    def test_camel_case_fields_are_mapped(self):
        row = normalize([box()])[0]
        self.assertEqual(row["game_id"], "g1")
        self.assertEqual(row["fgm"], 28)
        self.assertEqual(row["three_pm"], 8)
        self.assertEqual(row["tov"], 11)

    def test_alternate_flattened_names_are_accepted(self):
        raw = {"id": "g9", "school": "Duke", "points": 60, "fgm": 20, "fga": 50,
               "tpm": 5, "tpa": 15, "fta": 10, "oreb": 8, "dreb": 20, "tov": 9}
        row = normalize([raw])[0]
        self.assertEqual(row["game_id"], "g9")
        self.assertEqual(row["team"], "Duke")
        self.assertEqual(row["orb"], 8)

    def test_game_date_is_truncated_to_a_day(self):
        self.assertEqual(normalize([box()])[0]["game_date"], "2026-11-10")

    def test_rows_without_identity_are_dropped(self):
        self.assertEqual(normalize([{"points": 70}]), [])

    def test_non_dict_rows_are_ignored(self):
        self.assertEqual(normalize(["nope", None, 3]), [])


class VerifyMappingTest(unittest.TestCase):
    def test_clean_response_is_ready_to_verify(self):
        report = verify_mapping(paired_season())
        self.assertTrue(report["ready_to_verify"])
        self.assertEqual(report["missing_required_fields"], [])
        self.assertEqual(report["fields"]["fgm"]["resolved_key"], "fieldGoalsMade")

    def test_renamed_provider_field_is_reported_not_silently_dropped(self):
        """The failure mode this module exists to catch."""
        rows = paired_season()
        for row in rows:
            row["fg_made"] = row.pop("fieldGoalsMade")
        report = verify_mapping(rows)
        self.assertFalse(report["ready_to_verify"])
        self.assertIn("fgm", report["missing_required_fields"])
        self.assertIn("fg_made", report["unmapped_keys"])

    def test_unmapped_extra_keys_are_surfaced(self):
        rows = paired_season()
        for row in rows:
            row["assists"] = 12
        self.assertIn("assists", verify_mapping(rows)["unmapped_keys"])

    def test_partial_coverage_blocks_verification(self):
        rows = paired_season()
        for row in rows[:len(rows) // 2]:
            del row["turnovers"]
        report = verify_mapping(rows)
        self.assertFalse(report["ready_to_verify"])
        self.assertLess(report["fields"]["tov"]["coverage_pct"], 95.0)

    def test_empty_response_is_not_ready(self):
        self.assertFalse(verify_mapping([])["ready_to_verify"])


class BuildTest(unittest.TestCase):
    def test_profiles_are_derived_from_paired_boxes(self):
        payload = build_profiles(paired_season(games=24), min_games=3)
        self.assertGreater(len(payload["profiles"]), 0)
        profile = next(iter(payload["profiles"].values()))
        for field in ("adjusted_off_rating", "adjusted_def_rating", "efg",
                      "tov_rate", "orb_rate", "tempo", "schedule_strength"):
            self.assertIn(field, profile)

    def test_artifact_is_marked_research_only_at_zero_weight(self):
        payload = build_profiles(paired_season(games=24), min_games=3)
        self.assertEqual(payload["production_weight"], 0)
        self.assertTrue(payload["research_only"])

    def test_artifact_records_whether_the_mapping_was_verified(self):
        payload = build_profiles(paired_season(games=24), min_games=3)
        self.assertEqual(payload["mapping_verified"], ncaam.MAPPING_VERIFIED)

    def test_a_renamed_field_yields_no_profiles_rather_than_wrong_ones(self):
        rows = paired_season(games=24)
        for row in rows:
            row["fg_made"] = row.pop("fieldGoalsMade")
        self.assertEqual(build_profiles(rows, min_games=3)["profiles"], {})


class RefreshGateTest(unittest.TestCase):
    def test_refresh_refuses_while_the_mapping_is_unverified(self):
        with self.assertRaises(MappingUnverified):
            refresh(lambda: paired_season(), output="unused.json")

    def test_explicit_override_allows_a_local_build(self):
        with tempfile.TemporaryDirectory() as root:
            out = Path(root) / "ncaam.json"
            payload = refresh(lambda: paired_season(games=40), output=str(out),
                              min_games=3, min_teams=1, allow_unverified=True)
            self.assertIsNotNone(payload)
            self.assertTrue(out.is_file())
            self.assertFalse(json.loads(out.read_text())["mapping_verified"])

    def test_thin_coverage_leaves_the_last_good_artifact_untouched(self):
        with tempfile.TemporaryDirectory() as root:
            out = Path(root) / "ncaam.json"
            out.write_text('{"profiles": {"previous": {}}}', encoding="utf-8")
            result = refresh(lambda: paired_season(games=4), output=str(out),
                             min_games=3, min_teams=999, allow_unverified=True)
            self.assertIsNone(result)
            self.assertIn("previous", json.loads(out.read_text())["profiles"])

    def test_required_fields_match_what_the_metric_layer_demands(self):
        from advanced_metrics import basketball_game_records
        rows = normalize(paired_season(games=4))
        for field in REQUIRED:
            broken = [dict(row) for row in rows]
            for row in broken:
                row.pop(field, None)
            self.assertEqual(basketball_game_records(broken), [],
                             f"{field} is listed REQUIRED but records built without it")


if __name__ == "__main__":
    unittest.main()
