import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

import qb_availability as Q

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 24, 15, tzinfo=timezone.utc)


def payload():
    return {"123": {"ReportType": "Game Day", "conferenceTimeZone": "CT",
        "publishDate": "2026-10-24", "postedTime": "9:30:00",
        "footer": {"date": "2026-10-24", "time": "11:00:00", "networkImage": "PRIVATE-BRANDING"},
        "conferenceImage": "PRIVATE-BRANDING", "games": [
            {"teamName": "Michigan", "rows": [
                {"name": "QB #1 First Quarterback", "status": "Out", "exemptStatus": "NonExempt", "diagnosis": "DO-NOT-STORE"},
                {"name": "QB #2 Second Quarterback", "status": "Available"},
                {"name": "QB #3 Exempt Quarterback", "status": "Exempt", "exemptStatus": "Exempt"},
                {"name": "WR #4 Receiver", "status": "Out"}]},
            {"teamName": "Ohio State", "rows": [
                {"name": "QB #5 Other Quarterback", "status": "Questionable"}]}]}}


class AvailabilityCollectionTests(unittest.TestCase):
    def test_publication_time_unpadded_hour_and_qb_only_facts(self):
        rows = Q.normalize("B10", payload(), NOW.isoformat())
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["published_at"], "2026-10-24T14:30:00+00:00")
        self.assertEqual(row["kickoff"], "2026-10-24T16:00:00+00:00")
        self.assertTrue(row["observed_before_kickoff"])
        self.assertEqual([q["status"] for q in row["teams"][0]["quarterbacks"]], ["Out", "Available"])
        serialized = json.dumps(row)
        for forbidden in ("PRIVATE-BRANDING", "DO-NOT-STORE", "Receiver", "Exempt Quarterback"):
            self.assertNotIn(forbidden, serialized)

    def test_unknown_status_does_not_become_healthy(self):
        data = payload()
        data["123"]["games"][0]["rows"][0]["status"] = "New status wording"
        self.assertEqual(Q.normalize("B10", data, NOW.isoformat())[0]["teams"][0]["quarterbacks"][0]["status"], "Unknown")

    def test_future_missing_and_ambiguous_times_are_rejected(self):
        for change in ({"publishDate": "2026-10-25"}, {"conferenceTimeZone": "??"}, {"postedTime": None}):
            data = payload(); data["123"].update(change)
            self.assertEqual(Q.normalize("B10", data, NOW.isoformat()), [])

    def test_repeated_fetch_preserves_first_seen_and_revisions_append(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); ledger, snap, script = [root / n for n in ("ledger.jsonl", "snapshot.json", "data.js")]
            getter = lambda conf: payload() if conf == "B10" else {}
            first = Q.collect(ledger, snap, script, getter=getter, now=NOW)
            later = datetime(2026, 10, 24, 15, 30, tzinfo=timezone.utc)
            second = Q.collect(ledger, snap, script, getter=getter, now=later)
            self.assertEqual(len(ledger.read_text().splitlines()), 1)
            self.assertEqual(first["reports"][0]["first_observed_at"], second["reports"][0]["first_observed_at"])
            revised = payload(); revised["123"]["games"][0]["rows"][0]["status"] = "Available"
            Q.collect(ledger, snap, script, getter=lambda conf: revised if conf == "B10" else {}, now=later)
            self.assertEqual(len(ledger.read_text().splitlines()), 2)
            def broken(_): raise OSError("private failure detail")
            failed = Q.collect(ledger, snap, script, getter=broken, now=later)
            self.assertEqual(len(failed["reports"]), 1)
            self.assertEqual(failed["sources"]["B10"]["state"], "unavailable")
            self.assertNotIn("private failure detail", script.read_text())
            self.assertEqual(failed["prediction_weight"], 0)

    def test_later_collection_cannot_claim_pregame_observation(self):
        row = Q.normalize("SEC", payload(), "2026-10-25T15:00:00+00:00")[0]
        self.assertFalse(row["observed_before_kickoff"])


@unittest.skipUnless(shutil.which("node"), "Node.js is unavailable")
class AvailabilityDisplayTests(unittest.TestCase):
    def test_match_identity_missing_stale_and_html_escaping(self):
        script = r"""
const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
const ctx={DATA:{comp_key:'NCAAF'},teamKey:s=>String(s).toLowerCase().replace(/[^a-z0-9 ]/g,'').trim(),esc:s=>String(s).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;')};
vm.createContext(ctx);
const base=fs.readFileSync('app-3-panels.js','utf8');
vm.runInContext(base.slice(0,base.indexOf('function _bbShiftDay')),ctx);
vm.runInContext(fs.readFileSync('app-qb-availability.js','utf8'),ctx);
const now=Date.parse('2026-10-24T15:00:00Z'),m={home:{name:'Michigan Wolverines'},away:{name:'Ohio State Buckeyes'},kickoff:'2026-10-24T16:00:00Z'};
const report={conference:'B10',report_id:'one',kickoff:m.kickoff,published_at:'2026-10-24T14:00:00Z',first_observed_at:'2026-10-24T14:30:00Z',source_url:'https://bigten.org/',teams:[{name:'Michigan',quarterbacks:[{name:'<img src=x>',status:'Out'}]},{name:'Ohio State',quarterbacks:[]}]};
ctx.MATCHDAY_QB_AVAILABILITY={sources:{B10:{state:'ok',checked_at:'2026-10-24T14:30:00Z',source_url:'https://bigten.org/'}},reports:[report]};
assert.equal(ctx.qbAvailabilityFor(m,now).state,'reported');
assert.equal(ctx.qbAvailabilityFor({...m,home:{name:'Michigan State Spartans'}},now).state,'unknown');
assert.equal(ctx.qbAvailabilityFor({...m,kickoff:'2026-10-31T16:00:00Z'},now).state,'unknown');
assert.equal(ctx.qbAvailabilityFor(m,now+5*3600e3).state,'stale');
assert.equal(ctx.qbAvailabilityFor({...m,_comp:'NCAAM'},now),null);
assert.equal(ctx.qbReportName('Miami (FL)'),'Miami');
assert.ok(ctx.qbAvailabilityPanel(m).includes('&lt;img'));
assert.ok(ctx.qbAvailabilityPanel(m).includes('No QB status listed'));
assert.ok(ctx.qbAvailabilityPanel(m).includes('These reports do not change the forecast.'));
ctx.MATCHDAY_QB_AVAILABILITY.reports.push({...report,report_id:'two'});
assert.equal(ctx.qbAvailabilityFor(m,now).state,'unknown');
"""
        result = subprocess.run(["node", "-e", script], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
