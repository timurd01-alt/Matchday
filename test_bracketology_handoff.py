"""Independent producer/display boundary checks; no provider requests or browser needed."""
import pathlib
import shutil
import subprocess
import unittest


ROOT = pathlib.Path(__file__).resolve().parent
NODE = shutil.which("node")
HARNESS = r"""
const fs = require('fs'), vm = require('vm'), assert = require('assert/strict');
const fixture = JSON.parse(fs.readFileSync('docs/fixtures/bracketology_ncaam.mock.json', 'utf8'));
const requests = [];
let response = {ok:true,json:async()=>fixture};
const host = {isConnected:true,innerHTML:'',querySelector:()=>({}),querySelectorAll:()=>[]};
const context = {
  window:{}, location:{hostname:'localhost',search:'?bracketology_preview=1'},
  URLSearchParams, AbortController, setTimeout, clearTimeout, Date, Intl,
  requestAnimationFrame:()=>0,
  esc:s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])),
  teamMark:s=>'<span class="test-logo">'+s+'</span>', DATA:{comp_key:'NCAAM'},
  document:{getElementById:()=>null},
  fetch:async(url)=>{requests.push(url);return response;},
};
vm.createContext(context);
vm.runInContext(fs.readFileSync('app-bracketology.js','utf8'),context);
const api=context.window.MatchdayBracketology;
function rejects(change){const d=structuredClone(fixture);change(d);assert.throws(()=>api.validate(d,true));}
"""


@unittest.skipUnless(NODE, "Node is required for frontend contract verification")
class BracketologyHandoffTests(unittest.TestCase):
    def run_js(self, script):
        result = subprocess.run(
            [NODE, "-e", HARNESS + "\n(async()=>{\n" + script +
             "\n})().catch(e=>{console.error(e);process.exitCode=1});"],
            cwd=ROOT, capture_output=True, text=True, timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_complete_preview_fixture_accepted_without_mutation(self):
        self.run_js("const before=JSON.stringify(fixture); assert.equal(api.validate(fixture,true),fixture); assert.equal(JSON.stringify(fixture),before);")

    def test_mock_forbidden_in_live_validation(self):
        self.run_js("assert.throws(()=>api.validate(fixture));")

    def test_required_display_metadata_rejected_when_missing(self):
        self.run_js("""
        for(const key of ['odds_rounds','max_seed','build_id'])rejects(d=>delete d[key]);
        rejects(d=>d.odds_rounds=[]);rejects(d=>d.max_seed=0);
        rejects(d=>delete d.bracket.games[0].label);
        rejects(d=>delete d.rounds[0].label);
        """)

    def test_official_phase_and_bracket_kind_must_agree(self):
        self.run_js("""
        rejects(d=>d.phase='official');rejects(d=>d.bracket.kind='official');
        const d=structuredClone(fixture);d.phase='official';d.bracket.kind='official';
        assert.equal(api.validate(d,true),d);
        """)

    def test_probability_missing_zero_and_tiny_remain_distinct(self):
        self.run_js("""
        for(const x of [null,undefined,NaN,-.1,1.1,'0'])assert.equal(api.formatOdds(x),'Unavailable');
        assert.equal(api.formatOdds(0),'0%'); assert.equal(api.formatOdds(.00001),'<1%');
        assert.equal(api.formatOdds(1),'100%'); assert.equal(api.formatOdds(.42),'42%');
        """)

    def test_duplicate_field_and_unknown_team_rejected(self):
        self.run_js("""
        rejects(d=>d.field[1]=structuredClone(d.field[0]));
        rejects(d=>d.field[0].team_key='unknown-school');
        rejects(d=>d.bracket.games[0].slots[0]={team_key:'unknown-school'});
        """)

    def test_invalid_probability_rejected_without_normalizing(self):
        self.run_js("rejects(d=>Object.values(d.teams)[0].odds.make_field=42);")

    def test_missing_graph_references_rejected(self):
        self.run_js("""
        rejects(d=>d.bracket.games[0].next_game='missing-game');
        rejects(d=>d.bracket.games[0].slots[0]={source_game:'missing-game',label:'Winner'});
        """)

    def test_graph_cycle_rejected(self):
        self.run_js("rejects(d=>{const g=d.bracket.games[0];g.next_game=g.id;g.next_slot=0;});")

    def test_advancement_and_feeder_must_agree(self):
        self.run_js("""
        rejects(d=>{const g=d.bracket.games.find(g=>g.next_game);g.next_slot=1-g.next_slot;});
        """)

    def test_slot_cannot_have_two_identity_sources(self):
        self.run_js("""
        rejects(d=>{const g=d.bracket.games.find(g=>g.slots.some(s=>s.source_game));
          g.slots.find(s=>s.source_game).team_key=d.field[0].team_key;});
        """)

    def test_preview_is_explicit_and_local_only(self):
        self.run_js("""
        await api.render(host);assert.equal(requests[0],'docs/fixtures/bracketology_ncaam.mock.json');
        assert.match(host.innerHTML,/DESIGN PREVIEW/);assert.match(host.innerHTML,/Beta/);
        context.location.hostname='matchday.example';await api.render(host,true);
        assert.equal(requests[1],'bracketology_ncaam.json');
        assert.match(host.innerHTML,/cannot be shown as a live projection/);
        """)

    def test_expired_feed_hides_projection(self):
        self.run_js("""
        fixture.as_of='2020-01-01T00:00:00Z';fixture.valid_until='2020-01-02T00:00:00Z';
        await api.render(host);assert.match(host.innerHTML,/update overdue/);
        assert.doesNotMatch(host.innerHTML,/bkGameTeam/);
        """)

    def test_missing_feed_does_not_fetch_mock_or_calculate_fallback(self):
        self.run_js("""
        context.location.search='';response={ok:false,status:404};
        context.projectNcaamBracket=()=>{throw Error('Legacy projection must not execute');};
        await api.render(host);assert.deepEqual(requests,['bracketology_ncaam.json']);
        assert.match(host.innerHTML,/has not arrived/);assert.doesNotMatch(host.innerHTML,/bkGameTeam/);
        """)

    def test_fetch_error_becomes_readable_unavailable_state(self):
        self.run_js("""
        context.fetch=async()=>{throw Error('Network unavailable');};await api.render(host);
        assert.match(host.innerHTML,/Bracketology unavailable/);assert.match(host.innerHTML,/Network unavailable/);
        """)

    def test_producer_winner_and_scores_preserved_without_inference(self):
        self.run_js("""
        const g=fixture.bracket.games.find(g=>g.region===fixture.regions[0]&&g.slots.every(s=>s.team_key));
        g.status='finished';g.score=[70,70];g.winner_key=g.slots[1].team_key;
        const before=JSON.stringify(g);await api.render(host);
        assert.equal(JSON.stringify(g),before);assert.match(host.innerHTML,/bkWinner/);
        assert.equal(host.innerHTML.split('class="bkScore">70</strong>').length-1,2);
        """)


if __name__ == '__main__':
    unittest.main()
