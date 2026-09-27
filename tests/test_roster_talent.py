"""Roster talent tiers: name matching, tier shares, and the no-request path."""
import unittest

import roster_talent as rt

NAMES = ["Florida Gators", "Florida State Seminoles", "Florida Atlantic Owls",
         "Alabama Crimson Tide", "Miami Hurricanes", "Miami (OH) RedHawks",
         "Louisiana Ragin' Cajuns", "Louisiana Tech Bulldogs"]


class RosterTalentTests(unittest.TestCase):
    def test_short_name_takes_the_closest_school(self):
        self.assertEqual(rt.match("Florida", NAMES), "Florida Gators")
        self.assertEqual(rt.match("Florida State", NAMES), "Florida State Seminoles")
        self.assertEqual(rt.match("Alabama", NAMES), "Alabama Crimson Tide")
        self.assertEqual(rt.match("Miami", NAMES), "Miami Hurricanes")

    def test_tiers_cover_every_matched_team_in_rank_order(self):
        scores = {f"Team {i}": 1000 - i for i in range(100)}
        names = [f"Team {i} Mascots" for i in range(100)]
        tiers = rt.tiers_from(scores, names)
        self.assertEqual(len(tiers), 100)
        self.assertEqual(tiers["Team 0 Mascots"], "Elite")
        self.assertEqual(tiers["Team 99 Mascots"], "Weak")
        self.assertEqual(sum(1 for t in tiers.values() if t == "Average"), 40)

    def test_only_labels_are_published_never_raw_scores(self):
        tiers = rt.tiers_from({"Florida": 987.6}, NAMES)
        self.assertEqual(set(tiers.values()) <= {label for _, label in rt.TIERS}, True)
        self.assertNotIn(987.6, tiers.values())

    def test_a_stored_season_makes_no_request(self):
        class Boom:
            def talent(self, **_):
                raise AssertionError("no request expected")
        stored = rt.load()
        if stored.get("season") and len(stored.get("tiers") or {}) >= rt.MIN_TEAMS:
            self.assertEqual(rt.refresh(season=stored["season"], adapter=Boom()), stored)


if __name__ == "__main__":
    unittest.main()
