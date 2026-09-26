"""Prevent removed sports and legacy handles from resurfacing publicly."""
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent


class CollegeLeaderboardTests(unittest.TestCase):
    def test_only_college_competitions_accept_new_picks(self):
        source = (ROOT / "api" / "leaderboard.js").read_text(encoding="utf-8")
        self.assertIn('const ALLOWED_COMPS = new Set(["ncaaf", "ncaam"]);', source)
        self.assertIn("v.comp IN ('ncaaf','ncaam')", source)

    def test_legacy_handles_are_public_aliases_not_erased_rows(self):
        source = (ROOT / "api" / "leaderboard.js").read_text(encoding="utf-8")
        accounts = (ROOT / "api" / "_accounts.js").read_text(encoding="utf-8")
        self.assertIn("handle: collegeHandle(row.handle)", source)
        self.assertIn("export function collegeHandle(handle)", accounts)
