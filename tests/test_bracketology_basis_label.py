"""The Bracketology tab must be able to say what its numbers are built on.

The page prints a line about team strength and a line about what the odds assume
only for values it recognises. Until Build 1111A the engine sent `odds_basis` as a
sentence the page matched against nothing, so the footer said nothing: a team at
53% to make the field showed 46% to reach the Round of 64 with no note that round
odds are for the bracket as drawn.
"""

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class BracketologyBasisLabelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.page = (ROOT / "app-bracketology.js").read_text(encoding="utf-8")
        cls.handoff = json.loads((ROOT / "bracketology_ncaam.json").read_text(encoding="utf-8"))

    def recognised(self, field):
        return set(re.findall(field + r"(?:\?)?(?:\.basis)?==='([a-z_]+)'", self.page))

    def test_the_page_knows_the_published_odds_basis(self):
        self.assertIn(self.handoff["odds_basis"], self.recognised("odds_basis"))

    def test_the_page_knows_the_published_power_basis(self):
        basis = (self.handoff.get("power_basis") or {}).get("basis")
        self.assertIn(basis, self.recognised("power_basis"))

    def test_the_as_drawn_wording_is_shown_for_the_engine_key(self):
        self.assertIn("season_unconditional_rounds_as_drawn", self.page)
        self.assertIn("for this bracket as drawn", self.page)

    def test_first_four_at_large_teams_are_the_lowest_at_large_seeds(self):
        at_large = [f for f in self.handoff["field"] if f["bid"] == "at_large"]
        play_in = [f["overall_seed"] for f in at_large if f["first_four"]]
        byes = [f["overall_seed"] for f in at_large if not f["first_four"]]
        if play_in and byes and self.handoff["bracket"]["kind"] == "projected":
            self.assertGreater(min(play_in), max(byes))


if __name__ == "__main__":
    unittest.main()
