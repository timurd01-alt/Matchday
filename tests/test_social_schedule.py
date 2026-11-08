"""The posting schedule: right slot, right clock, nothing time-sensitive lost.

Includes a check that every cron line in social-post.yml lands inside a slot
in both EST and EDT -- the failure that would otherwise appear silently twice
a year when the clocks change.
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import re
import unittest
from pathlib import Path

import social_publish
import social_schedule as ss

UTC = dt.timezone.utc


def at(text):
    return dt.datetime.fromisoformat(text.replace("Z", "+00:00"))


@dataclasses.dataclass
class P:
    kind: str
    expires_at: str
    key: str = "k"


class Eastern(unittest.TestCase):
    def test_dst_boundaries_2026(self):
        # DST ends 2026-11-01 at 06:00 UTC and starts 2026-03-08 at 07:00 UTC.
        self.assertEqual(ss.eastern(at("2026-11-01T05:59:00Z")).utcoffset(), dt.timedelta(hours=-4))
        self.assertEqual(ss.eastern(at("2026-11-01T06:00:00Z")).utcoffset(), dt.timedelta(hours=-5))
        self.assertEqual(ss.eastern(at("2026-03-08T06:59:00Z")).utcoffset(), dt.timedelta(hours=-5))
        self.assertEqual(ss.eastern(at("2026-03-08T07:00:00Z")).utcoffset(), dt.timedelta(hours=-4))

    def test_matches_the_tz_database_when_available(self):
        try:
            from zoneinfo import ZoneInfo
            zone = ZoneInfo("America/New_York")
        except Exception:
            self.skipTest("no tz database here")
        moment = at("2026-01-01T00:00:00Z")
        while moment < at("2028-01-01T00:00:00Z"):
            self.assertEqual(ss.eastern(moment).utcoffset(), moment.astimezone(zone).utcoffset(), moment)
            moment += dt.timedelta(hours=7)


class Slots(unittest.TestCase):
    def test_thursday_midday_is_the_slate(self):
        slot = ss.slot_at(at("2026-11-05T17:00:00Z"))    # Thu 12:00 EST
        self.assertEqual(slot.kinds[0], "slate_preview")

    def test_sunday_evening_is_rankings(self):
        slot = ss.slot_at(at("2026-11-09T00:30:00Z"))    # Sun 19:30 EST
        self.assertEqual(slot.kinds[0], "power_top25")

    def test_overnight_is_no_slot(self):
        self.assertIsNone(ss.slot_at(at("2026-11-05T08:00:00Z")))   # Thu 03:00 EST

    def test_every_kind_has_a_slot(self):
        import content_engine

        covered = {kind for slot in ss.SLOTS for kind in slot.kinds}
        self.assertEqual(set(content_engine.KINDS) - covered, set())


def _cron_lines():
    text = Path(".github/workflows/social-post.yml").read_text(encoding="utf-8")
    return re.findall(r"cron: '(\d+) (\d+) \* \* ([\d,-]+)'", text)


def _days(spec):
    out = set()
    for part in spec.split(","):
        if "-" in part:
            a, b = map(int, part.split("-"))
            out.update(range(a, b + 1))
        else:
            out.add(int(part))
    return out


class CronFitsSlots(unittest.TestCase):
    """Every cron run lands in a slot, in winter and in summer."""

    WEEKS = ("2027-01-10", "2026-10-11")   # a Sunday in EST, a Sunday in EDT

    def runs(self):
        for week in self.WEEKS:
            sunday = dt.date.fromisoformat(week)
            for minute, hour, days in _cron_lines():
                for cron_day in _days(days):                    # cron: 0 = Sunday
                    day = sunday + dt.timedelta(days=cron_day % 7)
                    yield dt.datetime(day.year, day.month, day.day, int(hour), int(minute), tzinfo=UTC)

    def test_crons_exist(self):
        self.assertGreaterEqual(len(_cron_lines()), 4)

    def test_each_run_is_inside_a_slot(self):
        for moment in self.runs():
            self.assertIsNotNone(ss.slot_at(moment), f"{moment} ({ss.eastern(moment)}) is in no slot")

    def test_each_run_survives_a_half_hour_cron_delay(self):
        for moment in self.runs():
            late = moment + dt.timedelta(minutes=30)
            self.assertEqual(ss.slot_at(late), ss.slot_at(moment), f"{moment} + 30 min leaves its slot")

    def test_runs_in_one_slot_respect_the_x_gap(self):
        runs = sorted(self.runs())
        for a, b in zip(runs, runs[1:]):
            if ss.slot_at(a) == ss.slot_at(b) and b - a < dt.timedelta(hours=12):
                self.assertGreaterEqual(b - a, social_publish.MIN_GAP["x"], (a, b))


class Ordering(unittest.TestCase):
    def test_outside_a_slot_nothing_goes(self):
        posts, slot = ss.order([P("upset_watch", "2026-11-06T00:00:00Z")], at("2026-11-05T08:00:00Z"))
        self.assertEqual((posts, slot), ([], None))

    def test_slot_kinds_first_in_slot_order(self):
        thursday = at("2026-11-05T17:00:00Z")
        posts = [P("upset_watch", "2026-11-06T00:00:00Z", "u"),
                 P("slate_preview", "2026-11-07T17:00:00Z", "s")]
        ordered, _ = ss.order(posts, thursday)
        self.assertEqual([p.key for p in ordered], ["s", "u"])

    def test_an_item_that_would_expire_before_its_slot_is_urgent(self):
        """Monday has no upset slot; an upset pick expiring Wednesday must not wait for Thursday."""
        monday = at("2026-11-02T17:00:00Z")
        posts = [P("upset_watch", "2026-11-04T23:00:00Z", "urgent"),
                 P("game_of_the_week", "2026-11-08T00:30:00Z", "can-wait")]
        ordered, slot = ss.order(posts, monday)
        self.assertIn("ballot_top25", slot.kinds)
        self.assertEqual([p.key for p in ordered], ["urgent"])

    def test_next_slot_start(self):
        monday = at("2026-11-02T17:00:00Z")
        start = ss.next_slot_start("slate_preview", monday)
        self.assertEqual(ss.eastern(start).weekday(), 3)    # Thursday
        self.assertEqual(ss.eastern(start).hour, 11)


if __name__ == "__main__":
    unittest.main()
