"""Expanded profiles use completed season results, rather than a five-game tail."""
import json
from pathlib import Path
import shutil
import subprocess
import unittest


class TeamOverallFormTests(unittest.TestCase):
    def test_all_results_order_perspective_and_invalid_scores(self):
        node = shutil.which('node')
        if not node:
            self.skipTest('Node is required for UI helper checks')
        source = (Path(__file__).resolve().parents[1] / 'app-3-panels.js').read_text(encoding='utf-8')
        helper = source[source.index('function teamOverallForm('):source.index('function computeTeamProfile(')]
        script = "const assert=require('node:assert/strict'); const bbNameMatches=(a,b)=>a===b;\n" + helper + r'''
const game=(day,home,hs,as,status='FINISHED')=>({kickoff:`2026-09-${String(day).padStart(2,'0')}T12:00:00Z`,home:{name:home?'Team':'Opponent'},away:{name:home?'Opponent':'Team'},score:{home:hs,away:as},status});
const matches=[game(7,true,10,0),game(6,false,7,0),game(5,true,1,0),game(4,false,9,0),game(3,true,4,0),game(2,false,2,0),game(1,true,5,0),game(8,true,null,0),game(9,true,0,null),game(10,true,NaN,0),game(11,true,9,0,'SCHEDULED'),{...game(1,true,0,9),kickoff:'2025-09-01T12:00:00Z'}];
assert.equal(teamOverallForm(matches,'Team',Date.parse('2026-07-01')),'WLWLWLW');
assert.equal(teamOverallForm([...matches,{...game(7,true,10,0),id:'another-provider',kickoff:'2026-09-07T14:00:00Z'}],'Team',Date.parse('2026-07-01')),'WLWLWLW');
assert.equal(matches[0].kickoff,'2026-09-07T12:00:00Z');
assert.equal(teamOverallForm([],'Team',0),'');
'''
        result = subprocess.run([node, '-e', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
