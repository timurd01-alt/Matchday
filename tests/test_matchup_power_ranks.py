"""Matchup labels must use the published power rank, never a feed position."""
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]

class MatchupPowerRankTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Node is required")
    def test_both_sports_aliases_missing_ranks_and_records(self):
        core = (ROOT / "app-1-core.js").read_text(encoding="utf-8")
        panels = (ROOT / "app-3-panels.js").read_text(encoding="utf-8")
        source = "const assert=require('node:assert/strict'); const _TEAM_KEY_CACHE=new Map();\n"
        source += core[core.index("function teamKey("):core.index("function teamInitials(")]
        source += panels[:panels.index("/* A poll is not a conference")]
        source += core[core.index("const SCORE_DIFF_TERM="):core.index("function scoreText(")]
        source += r'''
const DATA={comp_key:'NCAAM'},currentSportKey=()=> 'ncaam';
const MATCHDAY_NCAAM_RANKINGS={rankings:[
  {name:'Michigan State Spartans',rank:3},
  {name:'Michigan Wolverines',rank:7},
  {name:'UConn Huskies',rank:5},
  {name:'Unranked',rank:null}
]};
const MATCHDAY_CFB_RANKINGS={rankings:[
  {name:'Michigan State Spartans',rank:65},
  {name:'Michigan Wolverines',rank:18},
  {name:'Texas Tech Red Raiders',rank:4},
  {name:'Texas Longhorns',rank:9}
]};
assert.deepEqual(teamStandingsMeta({name:'Michigan',pos:12,record:'1-0'},'NCAAM'),['#7','1-0']);
assert.deepEqual(teamStandingsMeta({name:'UConn',pos:4,record:'1-0'},'ncaam'),['#5','1-0']);
assert.equal(teamPowerRank('Michigan','NCAAF'),18);
assert.equal(teamPowerRank('Michigan State','ncaaf'),65);
assert.equal(teamPowerRank('Texas','ncaaf'),9);
assert.equal(teamPowerRank('Michigan'),7);
assert.deepEqual(teamStandingsMeta({name:'Unknown',pos:1,record:'2-0'},'NCAAM'),['2-0']);
assert.equal(teamPowerRank('Unranked','ncaam'),null);
MATCHDAY_NCAAM_RANKINGS.rankings.push({name:'Michigan Wolverines',rank:9});
assert.equal(teamPowerRank('Michigan','ncaam'),null);
MATCHDAY_NCAAM_RANKINGS.rankings=[];
assert.equal(teamPowerRank('Michigan','ncaam'),null);
'''
        result = subprocess.run(["node", "-e", source], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
