"""The board's "data N days ago" must describe the data, not the handoff.

`applyCurrentCfbSnapshot` used to stamp the Bet Better snapshot's own date over
the payload's. The snapshot is rebuilt only when a new handoff is taken in,
while data_*.json is refetched hourly, so whenever the handoff was the older of
the two the board advertised itself as stale while its fixtures and scores were
current. Confirmed live on 2026-09-03: the strip read "data 4 days ago" from a
snapshot stamped 2026-08-31T00:41:38Z, while data_ncaaf.json had been refetched
at 14:40:35 the same day.
"""
from __future__ import annotations

import os
import re
import unittest

ROOT = os.path.dirname(os.path.abspath(__file__))
PANELS = os.path.join(ROOT, "app-3-panels.js")


def source() -> str:
    with open(PANELS, encoding="utf-8") as handle:
        return handle.read()


class DataAgeReporting(unittest.TestCase):
    def test_no_snapshot_overwrites_the_payload_timestamp_outright(self):
        """The specific line that caused it, in either snapshot applier."""
        offenders = re.findall(r"payload\.updated\s*=\s*MATCHDAY_\w+_SNAPSHOT\.updated",
                               source())
        self.assertEqual(offenders, [],
                         "a snapshot is stamping its own date over the fetched data: %s"
                         % offenders)

    def test_both_appliers_reconcile_the_two_timestamps(self):
        assignments = re.findall(r"payload\.updated\s*=\s*([^;]+);", source())
        self.assertGreaterEqual(len(assignments), 2,
                                "expected the CFB and NCAAM appliers to both set it")
        for assignment in assignments:
            self.assertIn("_freshestUpdated", assignment,
                          "payload.updated set without reconciling: %s" % assignment)

    def test_the_helper_compares_instants_not_strings(self):
        """The two stamps arrive in different formats -- "...Z" from the snapshot
        and "...+00:00" from the fetch -- so a string compare is not safe."""
        body = re.search(r"function _freshestUpdated\(current,incoming\)\{(.*?)\n\}",
                         source(), re.S)
        self.assertIsNotNone(body, "_freshestUpdated is missing")
        self.assertIn("Date.parse", body.group(1))

    def test_the_helper_survives_a_missing_or_unparseable_stamp(self):
        body = re.search(r"function _freshestUpdated\(current,incoming\)\{(.*?)\n\}",
                         source(), re.S).group(1)
        self.assertIn("Number.isFinite", body,
                      "an unparseable date must not silently become the newest")


if __name__ == "__main__":
    unittest.main()
