"""The connected CFP drawing must preserve fixed advancement and settled results."""
import pathlib
import shutil
import subprocess
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent

@unittest.skipUnless(shutil.which('node'), 'Node.js is unavailable')
class CFPBracketTests(unittest.TestCase):
    def test_seed_paths_results_and_missing_identity(self):
        script = r"""
const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
const s=fs.readFileSync('app-4-features.js','utf8');
const context={DATA:{},esc:String};vm.createContext(context);
vm.runInContext(s.slice(s.indexOf('function _v11TeamName'),s.indexOf('function _v11TeamCode'))+s.slice(s.indexOf('function _cfpRoundKey'),s.indexOf('function renderBracket(){')),context);
const first=[[5,12],[6,11],[7,10],[8,9]].map(([h,a])=>({home:'School '+h,away:'School '+a,home_slot:String(h),away_slot:String(a),status:'PROJECTED',score:{}}));
const quarter=[1,2,3,4].map(n=>({home:'School '+n,away:'First-round winner',home_slot:String(n),status:'PROJECTED',score:{}}));
const source=[{round:'CFP First Round (model projection)',matches:first},{round:'CFP Quarter-finals (model projection)',matches:quarter}];
context.DATA.bracket=source;
const original=JSON.stringify(source);
const tree=()=>context._cfpBracketTree();
const get=(id)=>tree().find(n=>n.id===id);
assert.equal(tree().length,11);
// Automatic qualifiers can displace a higher AP-ranked team: do not just take ranks 13–16.
context.MATCHDAY_CFB_AP_POLL={rankings:[...Array.from({length:11},(_,i)=>({name:'School '+(i+1),rank:i+1})),...Array.from({length:4},(_,i)=>({name:'School '+(i+13),rank:i+12})),{name:'School 12',rank:25}]};
assert.equal(context._cfpFirstFourOut(tree()).map(t=>t.name).join(','),'School 13,School 14,School 15,School 16');
assert.equal(context._cfpFirstFourOut(tree().filter(n=>n.id!=='qf1')).length,0);
assert.equal(context._cfpOutRow(tree(),true),'');
const pollBefore=JSON.stringify(context.MATCHDAY_CFB_AP_POLL);
context._cfpFirstFourOut(tree());assert.equal(JSON.stringify(context.MATCHDAY_CFB_AP_POLL),pollBefore);

assert.equal(tree().filter(n=>n.next).length,10);
for(const [seed,pair] of [[1,[8,9]],[4,[5,12]],[2,[7,10]],[3,[6,11]]]){
 assert.equal(get('fr'+seed).teams.map(t=>t.seed).join(','),pair.join(','));
 assert.equal(get('fr'+seed).next,'qf'+seed);
 assert.equal(get('qf'+seed).teams[0].seed,seed);
 assert.equal(get('qf'+seed).next,[1,4].includes(seed)?'sf1':'sf2');
}
assert.equal(get('sf1').teams.map(t=>t.name).join(','),'Winner QF 1,Winner QF 2');
assert.equal(get('sf2').teams.map(t=>t.name).join(','),'Winner QF 3,Winner QF 4');
assert.equal(JSON.stringify(source),original,'Rendering cannot mutate the public record');
// Order is not identity. Both provider arrays can arrive in any order.
source.forEach(r=>r.matches.reverse());
assert.equal(get('fr1').teams[0].seed,8);assert.equal(get('qf4').teams[0].seed,4);
// Null scores and projected matches never advance a named winner.
const m=first.find(m=>m.home_slot==='8');m.status='FINISHED';m.score={home:null,away:7};
assert.equal(get('qf1').teams[1].name,'Winner 8 / 9');
m.score={home:14,away:7};
assert.equal(get('qf1').teams[1].name,'School 8');
// A supplied quarterfinal team takes precedence over an inferred winner.
const q=quarter.find(m=>m.home_slot==='1');q.away='Confirmed opponent';
assert.equal(get('qf1').teams[1].name,'Confirmed opponent');
q.away='School 8';q.away_slot='8';q.status='FINISHED';q.score={home:10,away:20};
assert.equal(get('sf1').teams[0].name,'School 8');
// A real semifinal in reversed home/away order still gets the right connector.
source.push({round:'CFP Semifinals',matches:[{home:'School 4',away:'School 8',home_slot:'4',away_slot:'8',status:'UPCOMING',score:{}}]});
assert.equal(get('sf1').teams[1].name,'School 8');assert.equal(get('qf1').nextRow,1);
// A sole right-hand semifinal must not be borrowed by the left side.
source[source.length-1].matches=[{home:'School 2',away:'School 3',home_slot:'2',away_slot:'3',status:'UPCOMING'}];
assert.equal(get('sf1').m,undefined);assert.equal(get('sf2').teams[0].seed,2);
// A bye team on the away row leaves the home row for the advancing winner.
q.home='Winner 8 / 9';q.home_slot='path';q.away='School 1';q.away_slot='1';q.status='PROJECTED';q.score={};
assert.equal(get('qf1').teams[0].seed,8);assert.equal(get('fr1').nextRow,0);
// Both legacy parenthesized seeds and current slot seeds are accepted.
assert.equal(context._cfpTeam({home:'(12) Texas'},'home').seed,12);
assert.equal(context._cfpTeam({home:{name:'Texas',seed:12}},'home').seed,12);
context.DATA.bracket=[];assert.equal(tree().length,0);
context.DATA.bracket=[{round:'CFP First Round',matches:[{home:'Unknown A',away:'Unknown B'}]}];
assert.equal(tree().length,0,'Unknown seed identity must not silently discard a supplied game');
console.log('CFP path, result, order and empty-state checks passed');
"""
        result = subprocess.run(['node', '-e', script], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
