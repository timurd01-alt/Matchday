function scorecardAuditCount(v,preferred='total'){if(v==null)return 0;if(typeof v==='object')return Number(v[preferred]??v.total??v.graded??v.count)||0;return Number(v)||0}
function scorecardMarketComparisonPick(p){if(['h','d','a'].includes(p?.market_comparison_pick))return p.market_comparison_pick;return p?.outcome_basis==='ultimate_winner'||p?.prediction_snapshot?.is_knockout?p?.regulation_pick:p?.pick}
function scorecardUnderdogTag(p){if(!p?.upset_score||!p?.upset_snapshot?.radar||p?.upset_snapshot?.standings_gap_pct==null)return'';const name=esc(p.upset_name||'Underdog'),score=esc(p.upset_score);if(!p.upset_triggered)return` <i class="scsplit upsetTag">underdog risk · ${name} ${score}/100</i>`;const outcome=p.result?(p.upset_hit?' &#10003;':' &#10007;'):'';return` <i class="scsplit upsetTag">upset pick · ${name} ${score}/100${outcome}</i>`}
// One team-name matcher for everything the handoff feeds.
//
// The fixture feed calls a team "Virginia"; the engine calls it "Virginia
// Cavaliers". externalRating() already tolerated that with prefix matching, but
// the records map and the results settling keyed on an exact match and so
// silently matched nothing -- ratings appeared while every record stayed 0-0
// and no played game ever settled.
const _BB_NAME_KEY_CACHE=new Map();
function bbNameKey(name){
  // CFBD calls the school Massachusetts; Bet Better and its poll use UMass.
  // Normalize that one established school alias before matching fixtures.
  const label=String(name||'');
  const hit=_BB_NAME_KEY_CACHE.get(label);
  if(hit!==undefined)return hit;
  const key=teamKey(label).replace(/^umass(?= |$)/,'massachusetts');
  _BB_NAME_KEY_CACHE.set(label,key);
  return key;
}
// Both are split per word on every comparison; the merge compares the same few
// hundred names against each other, so the split is kept too.
const _BB_WORDS_CACHE=new Map();
function bbNameWords(name){
  const label=String(name||'');
  let words=_BB_WORDS_CACHE.get(label);
  if(words===undefined){words=bbNameKey(label).split(' ').filter(Boolean);_BB_WORDS_CACHE.set(label,words)}
  return words;
}
// A parenthetical is part of the identity, not decoration. "Miami" and
// "Miami (OH)" are two different schools that both play, and whole-string
// prefixing matched them to each other -- the fixture feed's "Miami" against the
// engine's "Miami (OH) RedHawks" -- which is how a result gets settled onto the
// wrong game.
const _BB_QUALIFIER_CACHE=new Map();
function bbNameQualifier(name){
  const label=String(name||'');
  const hit=_BB_QUALIFIER_CACHE.get(label);
  if(hit!==undefined)return hit;
  const m=/\(([^)]*)\)/.exec(label);
  const qualifier=m?teamKey(m[1]):'';
  _BB_QUALIFIER_CACHE.set(label,qualifier);
  return qualifier;
}
// Matched word by word, with the shorter name's last word allowed to be an
// abbreviation of the longer's.
//
// Whole-string prefixing needed a space at the boundary, so the fixture feed's
// "Southern Miss" never reached the engine's "Southern Mississippi Golden
// Eagles" -- "southern mississippi..." does not start with "southern miss ".
// Same for "App State" against "Appalachian State Mountaineers". Comparing per
// word instead lets "miss" match "mississippi" and "app" match "appalachian",
// while still requiring every earlier word to line up.
//
// What it does NOT fix, and neither did the old one: "Ohio" still matches "Ohio
// State", because one school's whole name really is a prefix of the other's and
// nothing in the strings can separate them. Two things keep that from settling a
// score onto the wrong game -- both teams must match, and the kickoff has to be
// within a day -- but a name table is the only real answer if it ever bites.
function bbNameMatches(a,b){
  if(bbNameQualifier(a)!==bbNameQualifier(b))return false;
  const x=bbNameWords(a),y=bbNameWords(b);
  if(!x.length||!y.length)return false;
  const [short,long]=x.length<=y.length?[x,y]:[y,x];
  return short.every((word,i)=>long[i].startsWith(word));
}
/* A poll is not a conference, and its order is not ours to re-derive.

   The provider's poll tables arrive in payload.standings beside the real
   conferences -- fetch_data.py stamps them table_type "official_poll" -- and
   this view rendered every group the same way under one "Conferences"
   heading. The AP Top 25 therefore sat at the top of the conference list, as
   though the twenty-five best teams in the country were a league that plays
   itself. The note under it already read "official national poll", which only
   made the placement look deliberate.

   Worse, the snapshot pass below re-sorted every group by record and rating
   and renumbered it. A poll re-sorted is no longer that poll: the published
   board had USC at 1 and Indiana at 2 under an "AP Top 25" heading, when the
   AP had Indiana first and USC eighteenth. These tables now keep the order
   they were published in, and get a section of their own. */
const POLL_TABLE_TYPES=new Set(['official_poll','matchday_top_25']);
function isPollTable(g){return POLL_TABLE_TYPES.has(String(g?.table_type||''));}
function pollTableNote(g){
  return String(g?.table_type)==='matchday_top_25'
    ?'Matchday model \u00b7 separate from the poll'
    :'official national poll';
}
function pollSectionHTML(polls){
  if(!polls||!polls.length)return '';
  const movement=t=>{
    const move=Number(t.movement);
    if(t.movement!=null&&Number.isFinite(move)){
      if(move>0)return `<span class="pollMove up" title="Up ${move} place${move===1?'':'s'}">▲${move}</span>`;
      if(move<0)return `<span class="pollMove down" title="Down ${Math.abs(move)} place${move===-1?'':'s'}">▼${Math.abs(move)}</span>`;
      return '<span class="pollMove same" title="Unchanged">—</span>';
    }
    return '<span class="pollMove unavailable" title="Previous AP rank unavailable">—</span>';
  };
  const rows=g=>(g.teams||[]).map((t,i)=>`<tr><td class="pollRank">${esc(t.pos??i+1)}</td><td class="pollMoveCell">${movement(t)}</td>`
    +`<td><div class="gteam teamClickable" data-team="${esc(t.name||'')}" onclick="openTeamModal(this.dataset.team)">`
    +`<span class="code">${esc(t.code||'')}</span>${esc(t.name||'')}</div></td>`
    +`<td><b>${esc(t.record||`${t.w??'\u2014'}-${t.l??'\u2014'}`)}</b></td>`
    +`<td${t.external_rank?` title="Matchday power rating #${Number(t.external_rank)}"`:''}>${t.rating!=null?Number(t.rating).toFixed(2):'\u2014'}</td></tr>`).join('');
  return `<div class="vhead">Rankings</div>`+polls.map(g=>
    `<div class="tablewrap officialPoll"><div class="groupHead">${esc(g.group||'Ranking')}<span>${esc(pollTableNote(g))}</span></div>`
    +`<table class="gtable officialPollTable"><thead><tr><th>#</th><th class="pollMoveCell">Move</th><th>Team</th><th>Record</th>`
    +`<th title="Opponent-adjusted scoring margin; Matchday power-rating rank appears on hover" >Power</th></tr></thead>`
    +`<tbody>${rows(g)}</tbody></table></div>`).join('');
}
function _bbShiftDay(day,delta){const t=Date.parse(day+'T12:00:00Z');return Number.isFinite(t)?new Date(t+delta*86400000).toISOString().slice(0,10):day;}
/* Merging the handoff used to compare every fixture against every other one.
   With 632 handoff fixtures folded into a 160-fixture board that is ~700,000
   sameCfbFixture() calls, and it locked the main thread for over two minutes
   before the page could paint.

   sameCfbFixture() can only match kickoffs within 36 hours of each other, or
   two fixtures whose kickoff strings give the same calendar day. So fixtures
   are bucketed by day here and each one is only compared against the two days
   either side -- a superset of everything that could have matched, at a few
   comparisons apiece instead of the whole board. */
function _cfbDayOf(fixture){return String(fixture?.kickoff||'').slice(0,10)}
function _cfbDayIsReal(day){return Number.isFinite(Date.parse(day+'T12:00:00Z'))}
function makeCfbFixtureIndex(){
  const byDay=new Map(),undated=[];let seq=0;
  return {
    add(fixture,value){
      const record={fixture,value:value===undefined?fixture:value,seq:seq++};
      const day=_cfbDayOf(fixture);
      if(_cfbDayIsReal(day)){let list=byDay.get(day);if(!list)byDay.set(day,list=[]);list.push(record)}
      else undated.push(record);
      return record;
    },
    // The first stored fixture that sameCfbFixture() accepts, in the order the
    // fixtures were added -- the linear scan this replaces took the first hit.
    match(probe){
      const day=_cfbDayOf(probe);
      let pool;
      if(_cfbDayIsReal(day)){
        pool=undated.slice();
        for(let delta=-2;delta<=2;delta++){const list=byDay.get(_bbShiftDay(day,delta));if(list)pool.push(...list)}
      }else{
        // No usable day to bucket on: compare against everything, as before.
        pool=undated.slice();for(const list of byDay.values())pool.push(...list);
      }
      pool.sort((a,b)=>a.seq-b.seq);
      return pool.find(record=>sameCfbFixture(record.fixture,probe))||null;
    }
  };
}
function bbFindByName(list,name){return (list||[]).find(r=>bbNameMatches(r.name||r.team_name,name))||null;}
// The snapshots are rebuilt only when a new Bet Better handoff is taken in;
// data_*.json is refetched hourly. Stamping the snapshot's date over the
// payload's therefore reported the whole board as stale whenever the handoff
// was older than the last fetch -- on 2026-09-03 the strip read "data 4 days
// ago" while the fixtures and scores under it were two hours old, because the
// snapshot still carried 2026-08-31. The board is both sources, so the age it
// shows is the newer of the two, not whichever was written last. Compared as
// instants, not strings: these stamps arrive in mixed formats ("...Z" from the
// snapshot, "...+00:00" from the fetch) that do not sort lexicographically.
function _freshestUpdated(current,incoming){
  const a=Date.parse(current||''),b=Date.parse(incoming||'');
  if(!Number.isFinite(b))return current;
  if(!Number.isFinite(a))return incoming;
  return b>a?incoming:current;
}
function sameCfbSchool(a,b){
  if(bbNameMatches(a,b))return true;
  const x=primaryTeamLogo(a),y=primaryTeamLogo(b);
  return !!x&&x===y;
}
function sameCfbFixture(a,b){
  const ax=a.home?.name||a.home,bx=b.home?.name||b.home;
  const ay=a.away?.name||a.away,by=b.away?.name||b.away;
  const sameTeams=(sameCfbSchool(ax,bx)&&sameCfbSchool(ay,by))
    ||(sameCfbSchool(ax,by)&&sameCfbSchool(ay,bx));
  if(!sameTeams)return false;
  const ta=Date.parse(a.kickoff||''),tb=Date.parse(b.kickoff||'');
  return Number.isFinite(ta)&&Number.isFinite(tb)?Math.abs(ta-tb)<=36*3600e3
    :String(a.kickoff||'').slice(0,10)===String(b.kickoff||'').slice(0,10);
}
function applyCurrentCfbSnapshot(payload){
  const comp=String(payload?.comp_key||'').toUpperCase();
  if(comp!=='NCAAF'||typeof MATCHDAY_CFB_SNAPSHOT==='undefined')return payload;
  payload.news=[...(MATCHDAY_CFB_SNAPSHOT.news||[]),...(payload.news||[])];
  payload.updated=_freshestUpdated(payload.updated,MATCHDAY_CFB_SNAPSHOT.updated);
  // Add fixtures the schedule feed has not caught up with.
  //
  // Matchday's own fixture provider has a monthly ceiling, and when it is spent
  // data_ncaaf.json simply stops changing -- the board then shows a schedule
  // that ends on whatever day the allowance ran out. The engine already holds
  // the same fixtures from an ingest that was paid for, so they are merged in
  // here: anything already present is left alone, and only genuinely missing
  // games are added.
  const upcoming=(typeof MATCHDAY_BETBETTER_FIXTURES!=='undefined'?MATCHDAY_BETBETTER_FIXTURES:[]);
  if(upcoming.length){
    const have=new Set((payload.matches||[]).map(m=>
      `${teamKey(m.home?.name)}|${teamKey(m.away?.name)}|${String(m.kickoff||'').slice(0,10)}`));
    const added=[];
    const known=makeCfbFixtureIndex();
    (payload.matches||[]).forEach(m=>known.add(m));
    upcoming.forEach(f=>{
      // A game both sources hold keeps the feed's row, but takes the engine's
      // kickoff once one is announced. The frozen feed still carries the
      // midnight-Eastern placeholder it had before times were set, so Saturday
      // games read "Time TBA" while the engine had noon and 3:30.
      const hit=known.match(f),held=hit&&hit.value;
      if(held&&held!==f&&held.home){
        if(held.status==='UPCOMING'&&f.kickoff&&kickoffTimeTbd(held)&&!kickoffTimeTbd(f)){
          held.kickoff=f.kickoff;held._kickoff_from='betbetter_fixtures';
        }
        return;
      }
      const day=String(f.kickoff||'').slice(0,10);
      const key=`${teamKey(f.home)}|${teamKey(f.away)}|${day}`;
      if(have.has(key))return;
      // sameCfbFixture() reads home/away off .name when present; the handoff
      // rows carry plain strings, which it already handles.
      if(known.match(f))return;
      have.add(key);
      known.add({kickoff:f.kickoff,home:{name:f.home},away:{name:f.away}});
      added.push({id:`bb-${f.event_id}`,_comp:'NCAAF',competition:f.competition||'NCAAF',
        kickoff:f.kickoff,status:'UPCOMING',
        home:{name:f.home},away:{name:f.away},score:{},_from:'betbetter_fixtures'});
    });
    if(added.length)payload.matches=(payload.matches||[]).concat(added);
  }

  // Settle finished games from the handoff.
  //
  // The fixture feed cannot do this right now: CFBD is at 0 calls for the month
  // so data_ncaaf.json is frozen at its 23 August snapshot, and every game
  // played since is still stamped UPCOMING with no score. The handoff carries
  // those results with scores, so they are applied here rather than leaving a
  // played game displayed as though it had not kicked off.
  //
  // Matched on both team names and the calendar day, and only ever applied to a
  // fixture that is not already FINISHED -- a settled score is never rewritten.
  const settled=(typeof MATCHDAY_BETBETTER_RESULTS!=='undefined'?MATCHDAY_BETBETTER_RESULTS:[]);
  if(settled.length){
    const byDay=new Map();
    settled.forEach(r=>{const d=String(r.played_on||'').slice(0,10);(byDay.get(d)||byDay.set(d,[]).get(d)).push(r)});
    (payload.matches||[]).forEach(m=>{
      if(m.status==='FINISHED')return;
      const day=String(m.kickoff||'').slice(0,10);
      // A day either side, because a late kickoff and its result can land on
      // opposite sides of midnight UTC.
      const near=[day,_bbShiftDay(day,-1),_bbShiftDay(day,1)].flatMap(d=>byDay.get(d)||[]);
      const hit=near.find(r=>bbNameMatches(r.home,m.home?.name)&&bbNameMatches(r.away,m.away?.name));
      if(!hit)return;
      m.status='FINISHED';
      m.score={...(m.score||{}),home:Number(hit.home_score),away:Number(hit.away_score)};
      m._settled_from='betbetter_results';
      hit._merged=true;
    });
    // Played games the fixture feed never carried at all.
    //
    // Settling above can only repair a game already on the board, and the feed
    // keeps a rolling window -- on 2026-09-15 it began on 12 September, so the
    // Results tab showed 40 of the 185 games played that season and the first
    // three weekends existed nowhere on the site. The handoff holds them, so
    // the missing ones are added as finished fixtures.
    //
    // Only games involving a rated team: the engine's results also carry the
    // FCS and Division II games its opponents' schedules drag in (Willamette at
    // Pacific), and the site covers neither.
    const ratedNames=((typeof MATCHDAY_CFB_RANKINGS!=='undefined'&&MATCHDAY_CFB_RANKINGS.rankings)||[])
      .map(r=>teamKey(r.name)).filter(Boolean);
    const rated=new Set(ratedNames);
    const isRated=name=>{
      const key=teamKey(name);
      if(!key)return false;
      if(rated.has(key))return true;
      return ratedNames.some(r=>r===key||r.startsWith(key+' ')||key.startsWith(r+' '));
    };
    if(rated.size){
      const present=new Set((payload.matches||[]).map(m=>
        `${teamKey(m.home?.name)}|${teamKey(m.away?.name)}|${String(m.kickoff||'').slice(0,10)}`));
      const recovered=[];
      // The board is only read by kickoff day below, so it is bucketed once
      // here rather than scanned in full for each of the handoff's results.
      const matchesByDay=new Map();
      (payload.matches||[]).forEach(m=>{
        const mday=String(m.kickoff||'').slice(0,10);
        let list=matchesByDay.get(mday);if(!list)matchesByDay.set(mday,list=[]);list.push(m);
      });
      settled.forEach(r=>{
        if(r._merged)return;
        if(String(r.sport||'ncaaf')!=='ncaaf')return;
        if(!isRated(r.home)&&!isRated(r.away))return;
        const day=String(r.played_on||'').slice(0,10);
        const key=`${teamKey(r.home)}|${teamKey(r.away)}|${day}`;
        if(present.has(key))return;
        const sameWindow=[day,_bbShiftDay(day,-1),_bbShiftDay(day,1)]
          .flatMap(d=>matchesByDay.get(d)||[]);
        if(sameWindow.some(m=>bbNameMatches(m.home?.name,r.home)&&bbNameMatches(m.away?.name,r.away)))return;
        present.add(key);
        recovered.push({id:`bb-result-${r.event_id||key}`,_comp:'NCAAF',competition:r.competition||'NCAAF',
          kickoff:r.kickoff||`${day}T00:00:00Z`,status:'FINISHED',
          home:{name:r.home},away:{name:r.away},
          score:{home:Number(r.home_score),away:Number(r.away_score)},_from:'betbetter_results'});
      });
      if(recovered.length)payload.matches=(payload.matches||[]).concat(recovered);
    }
  }
  // A provider may call one school FAU and another Florida Atlantic. Collapse
  // those same-kickoff aliases after both fixture and result recovery, while
  // preserving the provider row (and any final score) over a thin handoff row.
  const unique=[];
  const kept=makeCfbFixtureIndex();
  (payload.matches||[]).forEach(m=>{
    const hit=kept.match(m);
    if(!hit){const position=unique.push(m)-1;kept.add(m,position);return}
    if(m.status==='FINISHED'&&unique[hit.value].status!=='FINISHED'){
      unique[hit.value]=m;
      // The scan this replaces compared later fixtures against the row it had
      // just swapped in, so the index has to follow the swap. When the new row
      // sits on a different calendar day it is registered there too, pointing
      // at the same position.
      const previousDay=_cfbDayOf(hit.fixture);
      hit.fixture=m;
      if(_cfbDayOf(m)!==previousDay)kept.add(m,hit.value);
    }
  });
  payload.matches=unique;
  // This season's advanced profile on every fixture, from the engine's own
  // play-by-play. It replaces a previous-season CFBD file that stopped
  // refreshing, which is why the expanded view mostly said "unavailable".
  const profiles=(typeof MATCHDAY_BETBETTER_TEAM_PROFILES!=='undefined'&&MATCHDAY_BETBETTER_TEAM_PROFILES)||{};
  const profileTeams=profiles.teams||{};
  const profileNames=Object.keys(profileTeams);
  if(profileNames.length){
    const byKey=new Map(profileNames.map(n=>[teamKey(n),n]));
    // Only a miss walks the whole profile list, and the board asks about the
    // same few hundred schools twice a fixture, so the answer is kept.
    const profileCache=new Map();
    const profileFor=name=>{
      const label=String(name||'');
      if(profileCache.has(label))return profileCache.get(label);
      const found=(()=>{
        const exact=byKey.get(teamKey(label));if(exact)return profileTeams[exact];
        const words=n=>bbNameWords(n).length;
        const hits=profileNames.filter(n=>bbNameMatches(n,label)).sort((a,b)=>Math.abs(words(a)-words(label))-Math.abs(words(b)-words(label)));
        if(hits.length===1||(hits.length>1&&Math.abs(words(hits[0])-words(label))<Math.abs(words(hits[1])-words(label))))return profileTeams[hits[0]];
        return null;
      })();
      profileCache.set(label,found);
      return found;
    };
    (payload.matches||[]).forEach(m=>{
      const home=profileFor(m.home?.name),away=profileFor(m.away?.name);
      if(!home&&!away)return;
      m.advanced_metrics={...(home?{home}:{}),...(away?{away}:{})};
      // A fixed label rather than the handoff's own `source`, which names the
      // engine. The modelling engine is private and is not named on the site.
      m.advanced_metrics_meta={source:'Play-by-play (expected points added) and opponent-adjusted ratings',
        generated_at:profiles.generated_through||null,shadow_only:true,production_weight:0,
        coverage:{season:profiles.season,season_role:'current',teams:profileNames.length}};
    });
  }

  // Team records on every fixture, from the ranking rows.
  //
  // The fixture feed's standings are CFBD's, and while its quota is spent they
  // stay at their preseason 0-0, so the expanded view showed Ohio State 0-0 after
  // two games. The handoff's ranking rows carry each rated team's current
  // wins, losses, games and form, so they replace the feed's numbers here.
  const rankRows=((typeof MATCHDAY_CFB_RANKINGS!=='undefined'&&MATCHDAY_CFB_RANKINGS.rankings)||[]);
  const rankByKey=new Map(rankRows.map(r=>[teamKey(r.name),r]));
  const rankCache=new Map();
  const rankFor=name=>{
    const label=String(name||'');
    if(rankCache.has(label))return rankCache.get(label);
    const found=(()=>{
      const exact=rankByKey.get(teamKey(label));
      if(exact)return exact;
      const extra=r=>bbNameWords(r.name).length-bbNameWords(label).length;
      const hits=rankRows.filter(r=>bbNameMatches(r.name,label)).sort((a,b)=>Math.abs(extra(a))-Math.abs(extra(b)));
      // "Texas" matches Texas Longhorns and Texas Tech Red Raiders; take the
      // closest name only when it is unambiguous.
      if(hits.length===1||(hits.length>1&&Math.abs(extra(hits[0]))<Math.abs(extra(hits[1]))))return hits[0];
      return null;
    })();
    rankCache.set(label,found);
    return found;
  };
  // The published result ledger can be newer than the derived rating rows.
  // Count every completed game, including non-conference opponents, once.
  const resultRecords=new Map(),seenResults=new Set(),gameLog=[];
  (typeof MATCHDAY_BETBETTER_RESULTS!=='undefined'?MATCHDAY_BETBETTER_RESULTS:[])
    .filter(g=>String(g.sport||'').toLowerCase()==='ncaaf'&&Number(g.season)===Number(MATCHDAY_CFB_RANKINGS?.season))
    .sort((a,b)=>String(a.kickoff||a.played_on||'').localeCompare(String(b.kickoff||b.played_on||'')))
    .forEach(g=>{
      if(!g.home||!g.away||g.home_score==null||g.away_score==null)return;
      const key=String(g.event_id||`${g.played_on}|${g.home}|${g.away}`);
      if(seenResults.has(key))return;
      seenResults.add(key);
      gameLog.push({home:teamKey(g.home),away:teamKey(g.away),hs:Number(g.home_score),as:Number(g.away_score)});
      [['home','away'],['away','home']].forEach(([side,other])=>{
        const team=teamKey(g[side]),pf=Number(g[side+'_score']),pa=Number(g[other+'_score']);
        if(!team||!Number.isFinite(pf)||!Number.isFinite(pa))return;
        const rec=resultRecords.get(team)||{pld:0,w:0,d:0,l:0,gf:0,ga:0,form:''};
        rec.pld++;rec.gf+=pf;rec.ga+=pa;
        if(pf>pa){rec.w++;rec.form+='W'}else if(pf<pa){rec.l++;rec.form+='L'}else{rec.d++;rec.form+='D'}
        resultRecords.set(team,rec);
      });
    });
  /* Exact key first, then the same prefix matcher the ratings use.
     The fixture feed says "Sacramento State" while results are filed under
     "Sacramento State Hornets", so an exact-key lookup misses. For a ranked
     team that went unnoticed, because the ranking row carried a record to fall
     back on. For a team the poll withholds -- one whose rating was earned
     mostly against FCS opposition -- there is no ranking row, so the miss left
     a stale number on the page: North Dakota State read 1-0 at 4-0, and
     Sacramento State 0-1 at 1-3. Every wrong record on the site was a withheld
     team, which is what gave the cause away. */
  const completedRecord=(name,minimum=0)=>{
    let r=resultRecords.get(teamKey(name));
    if(!r){
      for(const [key,value] of resultRecords){
        if(bbNameMatches(key,name)){r=value;break;}
      }
    }
    return r&&r.pld>=minimum?{...r,gd:r.gf-r.ga,pts:r.w*3+r.d,form:r.form.slice(-5),record:`${r.w}-${r.l}`}:null;
  };
  payload.cfb_result_records=Object.fromEntries(
    [...resultRecords].map(([key,rec])=>[key,{pld:rec.pld,w:rec.w,l:rec.l,record:`${rec.w}-${rec.l}`}])
  );
  (payload.matches||[]).forEach(m=>['home','away'].forEach(side=>{
    const team=m[side];if(!team?.name)return;
    const row=rankFor(team.name),latest=completedRecord(row?.name||team.name,Number(row?.season_games)||0);
    if(!row&&!latest)return;
    const w=latest?.w??(Number(row?.wins)||0),l=latest?.l??(Number(row?.losses)||0),played=latest?.pld??(Number(row?.season_games)||(w+l));
    Object.assign(team,{w,l,d:latest?.d||0,pld:played,record:`${w}-${l}`,win_pct:played?w/played:0,
      form:latest?.form||String(row?.recent_form||team.form||'').slice(-5),season_stale:false,
      model_rank:row?.rank<=25?row.rank:(team.model_rank??null),_record_from:'completed_results'});
  }));

  // Records come from the ranking rows first.
  //
  // MATCHDAY_CFB_SNAPSHOT.records is a hand-maintained list of sixteen teams,
  // so every other conference row showed 0-0 however many games had been
  // played. The handoff carries wins, losses, games and form for all 133 rated
  // teams and is regenerated with the ratings, so it is the better source and
  // the hand list is only the fallback for anything it does not rate.
  const records=new Map((MATCHDAY_CFB_SNAPSHOT.records||[]).map(t=>[teamKey(t.name),t]));
  ((typeof MATCHDAY_CFB_RANKINGS!=='undefined'&&MATCHDAY_CFB_RANKINGS.rankings)||[]).forEach(r=>{
    const w=Number(r.wins)||0,l=Number(r.losses)||0,d=Number(r.draws)||0;
    const played=Number(r.season_games)||(w+l+d);
    if(!played)return;
    records.set(teamKey(r.name),completedRecord(r.name,played)||{name:r.name,pld:played,w,d,l,gf:0,ga:0,gd:0,pts:w*3+d,
      form:String(r.recent_form||'').slice(-5),record:`${w}-${l}`});
  });
  resultRecords.forEach((_,key)=>{
    const latest=completedRecord(key,Number(records.get(key)?.pld)||0);
    if(latest)records.set(key,latest);
  });
  const recordFor=name=>records.get(teamKey(name))||records.get(teamKey(rankFor(name)?.name));
  const externalRating=name=>{const key=teamKey(name);return (MATCHDAY_CFB_SNAPSHOT.rankings||[]).find(row=>{const rk=teamKey(row.name);return rk===key||rk.startsWith(key+' ')||key.startsWith(rk+' ')})};
  /* Conference standings, ordered the way conferences order them.
     1. Conference win percentage -- only games between two members of this
        table count; non-conference games never move a team up or down here.
     2. Head-to-head among the tied teams (a mini-table if three or more are
        level); if that separates some of them, each still-level subgroup is
        re-run from step 2.
     3. Overall win percentage.
     4. Model rating, standing in for the computer/CFP rankings most
        conferences use as their late tiebreaker.
     Conference-specific steps (common opponents, rival divisions) are not
     modelled; the first three settle almost every real tie. */
  const conferenceOrder=teams=>{
    const idx=new Map();
    teams.forEach((t,i)=>{[t.name,rankFor(t.name)?.name].forEach(n=>{if(n)idx.set(teamKey(n),i)})});
    const confGames=gameLog.map(g=>({h:idx.get(g.home),a:idx.get(g.away),hs:g.hs,as:g.as}))
      .filter(g=>g.h!=null&&g.a!=null&&g.h!==g.a&&g.hs!==g.as);
    teams.forEach(t=>{t.cw=0;t.cl=0});
    confGames.forEach(g=>{const [w,l]=g.hs>g.as?[g.h,g.a]:[g.a,g.h];teams[w].cw++;teams[l].cl++;});
    teams.forEach(t=>{t.conf_record=`${t.cw}-${t.cl}`});
    const pct=(w,l)=>w+l?w/(w+l):0;
    const overall=t=>pct(Number(t.w)||0,Number(t.l)||0);
    const pos=new Map(teams.map((t,i)=>[t,i]));
    const h2h=group=>{
      const inG=new Set(group.map(t=>pos.get(t))),rec=new Map(group.map(t=>[t,{w:0,l:0}]));
      confGames.forEach(g=>{if(!inG.has(g.h)||!inG.has(g.a))return;
        const [w,l]=g.hs>g.as?[g.h,g.a]:[g.a,g.h];rec.get(teams[w]).w++;rec.get(teams[l]).l++;});
      return t=>{const r=rec.get(t);return r.w+r.l?pct(r.w,r.l):null};
    };
    const bucket=(list,key)=>{const out=[];list.forEach(t=>{const k=key(t),last=out[out.length-1];if(last&&last.k===k)last.items.push(t);else out.push({k,items:[t]})});return out.map(b=>b.items)};
    const fallback=(a,b)=>(overall(b)-overall(a))||((Number(b.rating)||0)-(Number(a.rating)||0))||a.name.localeCompare(b.name);
    const breakTie=group=>{
      if(group.length<2)return group;
      const score=h2h(group),scores=group.map(score);
      // Head-to-head only decides a tie when every tied team has played at
      // least one of the others; otherwise it rewards whoever happened to be
      // scheduled against the group.
      if(scores.some(v=>v==null)||new Set(scores).size===1)return [...group].sort(fallback);
      const ordered=[...group].sort((a,b)=>score(b)-score(a));
      return bucket(ordered,score).flatMap(g=>g.length===group.length?[...g].sort(fallback):breakTie(g));
    };
    // Equal percentage is the tie; more conference wins breaks 2-0 vs 1-0.
    const byConf=[...teams].sort((a,b)=>(pct(b.cw,b.cl)-pct(a.cw,a.cl))||(b.cw-a.cw));
    return bucket(byConf,t=>`${pct(t.cw,t.cl)}|${t.cw}`).flatMap(breakTie);
  };
  payload.standings=(payload.standings||[]).filter(g=>g.group!=='Matchday Top 25').map(g=>{
    // A poll carries its own order. Attaching ratings is fine; re-sorting on
    // them, and renumbering pos, publishes a different table under the poll's
    // name.
    if(isPollTable(g))return {...g,teams:(g.teams||[]).map(team=>{
      const ranked=externalRating(team.name);
      return {...team,rating:ranked?.rating??team.rating??null,
              external_rank:ranked?.rank??team.external_rank??null};
    })};
    const teams=(g.teams||[]).map((team,index)=>{
      const current=recordFor(team.name);
      const ranked=externalRating(team.name);
      // Prefer the ranking row's own record: it is regenerated with the
      // ratings and covers every rated team, where the hand list covers 16.
      return {...team,pos:index+1,rating:ranked?.rating??null,external_rank:ranked?.rank??null,pld:current?.pld||0,w:current?.w||0,d:current?.d||0,l:current?.l||0,
        gf:current?.gf||0,ga:current?.ga||0,gd:current?.gd||0,pts:current?.pts||0,
        form:current?.form||'',record:current?.record||'0-0'};
    });
    const sorted=conferenceOrder(teams);
    teams.length=0;teams.push(...sorted);
    teams.forEach((team,index)=>team.pos=index+1);
    return {...g,teams};
  });
  const ap=(typeof MATCHDAY_CFB_AP_POLL!=='undefined'&&MATCHDAY_CFB_AP_POLL.rankings)||[];
  if(ap.length===25){
    const apTable={group:MATCHDAY_CFB_AP_POLL.poll_name||'AP Top 25',table_type:'official_poll',
      source:MATCHDAY_CFB_AP_POLL.source||'',updated:MATCHDAY_CFB_AP_POLL.fetched_on||'',teams:ap};
    payload.standings=[apTable,...(payload.standings||[]).filter(g=>!isPollTable(g))];
  }
  payload.bracket=(typeof MATCHDAY_CFB_AP_BRACKET!=='undefined'&&MATCHDAY_CFB_AP_BRACKET.length)
    ?MATCHDAY_CFB_AP_BRACKET:(MATCHDAY_CFB_SNAPSHOT.bracket||[]);
  payload.bracketology=null;
  payload.position_views_note='Current-season results only. The playoff projection is recalibrating.';
  return payload;
}
function buildNcaamBracketology(rankings){
  const regions={East:[],West:[],South:[],Midwest:[]},names=Object.keys(regions);
  (rankings||[]).forEach((team,index)=>{
    const seed=Math.floor(index/4)+1,zigzag=seed%2===0?3-index%4:index%4;
    regions[names[zigzag]].push({...team,seed});
  });
  return {version:'Top 25 preview',field_size:(rankings||[]).length,
    methodology:'Current Matchday rankings snapshot; conference auto-bids and the full 68-team field begin when the new season produces results.',
    source_note:'Provisional Matchday bracketology based on the imported college-basketball rankings snapshot.',
    first_four:[],last_four_byes:(rankings||[]).slice(17,21),first_four_out:(rankings||[]).slice(21,25),next_four_out:[],regions};
}
function applyCurrentNcaamSnapshot(payload){
  if(String(payload?.comp_key||'').toUpperCase()!=='NCAAM'||typeof MATCHDAY_NCAAM_SNAPSHOT==='undefined')return payload;
  const externalRating=name=>{const key=teamKey(name);return (MATCHDAY_NCAAM_SNAPSHOT.rankings||[]).find(row=>{const rk=teamKey(row.name);return rk===key||rk.startsWith(key+' ')||key.startsWith(rk+' ')})};
  payload.standings=(payload.standings||[]).filter(g=>g.group!=='Matchday Top 25').map(g=>{if(isPollTable(g))return {...g,teams:(g.teams||[]).map(team=>{const ranked=externalRating(team.name);return {...team,rating:ranked?.model_score??team.rating??null,external_rank:ranked?.rank??team.external_rank??null}})};const teams=(g.teams||[]).map(team=>{const ranked=externalRating(team.name);return {...team,rating:ranked?.model_score??null,external_rank:ranked?.rank??null,pld:0,w:0,d:0,l:0,gf:0,ga:0,gd:0,pts:0,form:'',record:'0-0',win_pct:0,avg_pf:0,avg_pa:0}}).sort((a,b)=>(b.w-a.w)||(a.l-b.l)||(b.gd-a.gd)||((Number(b.rating)||0)-(Number(a.rating)||0))||a.name.localeCompare(b.name));teams.forEach((team,index)=>team.pos=index+1);return {...g,teams};});
  payload.bracketology=buildNcaamBracketology(MATCHDAY_NCAAM_SNAPSHOT.rankings);
  payload.bracket=[];
  payload.updated=_freshestUpdated(payload.updated,MATCHDAY_NCAAM_SNAPSHOT.updated);
  return payload;
}
/* The scorecard is the engine's, and it is generated.

   What was here before was eight games typed into matchday-cfb-snapshot.js on
   the day the site went college-only. That block sits outside the file's
   BEGIN/END GENERATED markers, so build_cfb_snapshot.py never touched it and
   nothing else ever wrote it: weeks later the page still showed the 29 August
   slate and called six of eight "model hits" for a model this site no longer
   publishes.

   The handoff carries the real one -- cards frozen an hour before kickoff and
   never rewritten -- so the page reads that instead.

   One rule travels with the data and is obeyed here rather than paraphrased:
   the hit rate is never rendered on its own. These cards are mostly heavy
   favourites, so a high hit rate is what the model already expected; the
   number that says whether it is any good is the distance between what it hit
   and what it expected to hit, and whether it beat the price. Expected sits
   beside actual in the same tile, and the engine's own caveat is printed
   underneath. */
function betbetterScorecard(){
  const all=(typeof MATCHDAY_BETBETTER_SCORECARD!=='undefined')?MATCHDAY_BETBETTER_SCORECARD:null;
  if(!all)return null;
  const key=(typeof currentSportKey==='function'?currentSportKey():'')||'';
  const sport=key?(all.sports||{})[key]:null;
  // `caveat` and `scope` sit on the document, not on the sport, because they
  // are the same sentences whichever board is loaded. Carried onto the sport
  // object so the renderer reads one shape.
  return sport?{...sport,caveat:all.caveat,scope:all.scope}:null;
}
// The engine's caveat is addressed partly to whoever renders it -- it names its
// own JSON fields. The warning is printed as written except for those
// identifiers, which are swapped for the words the page uses for the same
// numbers. Nothing is softened, dropped or reordered: a reader gets the same
// sentence, and the structural half of the instruction ("never render the hit
// rate on its own") is obeyed by the layout above rather than by editing it out.
const SCORECARD_FIELD_WORDS={
  hit_rate_pct:'the hit rate',
  expected_hit_rate_pct:'what it expected to hit',
  beat_market_pct:'how often it beat the price',
  calibration_gap_points:'the calibration gap',
};
function scorecardCaveat(text){
  let out=String(text||'');
  // Longest field name first: hit_rate_pct is a substring of
  // expected_hit_rate_pct, and replacing the short one first turns the long one
  // into "expected_the hit rate".
  Object.keys(SCORECARD_FIELD_WORDS).sort((a,b)=>b.length-a.length)
    .forEach(k=>{out=out.split(k).join(SCORECARD_FIELD_WORDS[k])});
  // The closing sentence is an instruction to whoever builds this page, not a
  // fact about the record, and the layout above already obeys it. It is dropped
  // from the reader's copy; nothing that describes the numbers is.
  return out.replace(/\s*Never render[^.]*\.\s*$/,'').trim();
}
// Scorecard. One anchor (the record), then three short sections. Explanation
// lives behind "Methodology" rather than as prose between the numbers.
function _scNum(v,d=1){const n=Number(v);return Number.isFinite(n)?n.toFixed(d):null;}
function _scPct(v){const n=Number(v);return Number.isFinite(n)?n.toFixed(1)+'%':'—';}
function _scGap(v,unit=' pts'){
  const n=Number(v);
  if(!Number.isFinite(n))return '<span class="scGap flat">—</span>';
  // Above expectation is not "good" and below is not "bad" -- a model that hits
  // exactly what it forecast is the calibrated one. Neutral colour, signed number.
  return `<span class="scGap">${n>0?'+':n<0?'−':''}${Math.abs(n).toFixed(1)}${unit}</span>`;
}
function _scHead(label,hint,aside){
  // The hint is a tooltip on a ?, not a sentence under the heading.
  const help=hint?`<button type="button" class="metricHelp boardHelp scHelp" aria-label="${esc(hint)}" data-tip="${esc(hint)}">?</button>`:'';
  return `<div class="scHead"><div class="seclbl">${label}${help}</div>${aside?`<span class="scAside">${aside}</span>`:''}</div>`;
}
function _scStat(value,label,sub){
  return `<div class="scStat"><b>${value}</b><span>${label}</span>${sub?`<small>${sub}</small>`:''}</div>`;
}
/* Scorecard layout, on the same grid and panels as Research: numbered parts,
   titled panels sized by what they hold, and long lists behind View all.
   Every panel here is graded, so each carries the Graded label. */
function _scCompare(items){
  return `<div class="rsCompare">${items.map(([k,v,sub])=>`<div><span class="rsKicker">${k}</span><b>${v}</b>${sub?`<span>${sub}</span>`:''}</div>`).join('')}</div>`;
}
function _scBands(bands){
  if(!bands||!bands.length)return '';
  const n=bands.reduce((a,b)=>a+(Number(b.picks)||0),0);
  // Track runs 50-100%: every pick is a favourite, so below 50 is empty space.
  const pos=v=>Math.max(0,Math.min(100,(Number(v)-50)*2));
  const rows=bands.map(b=>{
    const hit=Number(b.hit_rate_pct),exp=Number(b.expected_hit_rate_pct);
    const ok=Number.isFinite(hit)&&Number.isFinite(exp);
    return `<div class="scCalRow"><span class="scCalBand">${esc(b.band||'')}</span>`
      +`<span class="scCalTrack" aria-hidden="true">${ok?`<i class="scCalFill" style="width:${pos(hit)}%"></i><i class="scCalExp" style="left:${pos(exp)}%"></i>`:''}</span>`
      +`<span class="scCalNums"><b>${ok?Math.round(hit)+'%':'—'}</b> / ${ok?Math.round(exp)+'%':'—'}</span>`
      +`<span class="scCalGap">${_scGap(b.calibration_gap_points,'')}</span></div>`;
  }).join('');
  return `<section class="rsBlock rsSpan5">${rsTop('Calibration','graded',`${n} picks`)}`
    +`<div class="scCalKey"><span><i class="scCalFill"></i>Hit rate</span><span><i class="scCalExp"></i>Expected</span></div>`
    +`<div class="scCal">${rows}</div>`
    +`<p class="rsFine">Does a 70% pick win about 70% of the time? A gap either way is miscalibration.</p></section>`;
}
/* Picks that agreed with the market and picks that disagreed. The lift stat
   never renders without the record it earned taking that side: showing it
   alone would claim an edge the results do not support. */
function _scMarket(vm,c){
  const d=c&&c.available!==false?c.outright_disagreements:null;
  const lift=c?.underdog_lift_points;
  const stats=(d&&d.picks&&lift!=null)
    ? _scCompare([['Underdog lean',`${lift>0?'+':''}${esc(lift)} pts`,`${esc(c.contested_underdogs??'—')} selections`],
        ['Avg. price gap',`${esc(c.mean_divergence_points??'—')} pts`,'every graded card'],
        ['Model underdogs',`${esc(d.wins)}–${esc(d.losses)}`,'record vs market']])
    : '';
  const pairs=[['Agreed',vm?.agreed_with_market],['Disagreed',vm?.disagreed_with_market]]
    .filter(([,b])=>b&&Number.isFinite(Number(b.hit_rate_pct)));
  if(!stats&&!pairs.length)return '';
  const rows=pairs.map(([label,b])=>{
    const ci=Array.isArray(b.confidence_interval_pct)?b.confidence_interval_pct:null;
    return `<tr><td>${label}</td><td>${esc(b.picks??'—')}</td>`
      +`<td>${esc(b.wins??'—')}–${esc(b.losses??'—')}</td>`
      +`<td${ci?` title="95% CI ${_scNum(ci[0])}–${_scNum(ci[1])}%"`:''}>${_scPct(b.hit_rate_pct)}</td>`
      +`<td>${_scPct(b.expected_hit_rate_pct)}</td><td>${_scGap(b.calibration_gap_points,'')}</td></tr>`;
  }).join('');
  const share=Number(vm?.disagreement_share_pct);
  return `<section class="rsBlock rsSpan12">${rsTop('Against the market','graded')}`
    +`<div class="rsSplit"><div class="rsSplitMain">${stats}`
    +`<p class="rsFeatRead">${Number.isFinite(share)?`Matchday took a different side from the market on ${share.toFixed(1)}% of priced picks. `:''}`
    +`${stats?'Seeing an underrated team and beating the price are not the same thing — so far only the first holds.':''}</p></div>`
    +(rows?`<div class="rsSplitSide"><div class="scTableWrap"><table class="scTable"><thead><tr><th>vs market</th><th>Picks</th><th>Record</th><th>Hit</th><th>Expected</th><th>Gap</th></tr></thead><tbody>${rows}</tbody></table></div>`
      +`<p class="rsFine">Hover a hit rate for its 95% interval.</p></div>`:'')
    +`</div></section>`;
}
function _scTeamLine(name,score,won,prefix){
  const short=typeof rsShortName==='function'?rsShortName(name):name;
  return `<div class="scTeam${won?' won':''}" title="${esc(name)}">${typeof teamMark==='function'?teamMark(name):''}`
    +`<span>${prefix?`<em>${prefix}</em> `:''}${esc(short)}</span><b>${esc(score??'')}</b></div>`;
}
function _scRecent(rows){
  const graded=(rows||[]).filter(r=>['win','loss'].includes(String(r.result||'').toLowerCase()));
  if(!graded.length)return '';
  const list=graded.slice(0,10);
  return `<section class="rsBlock rsSpan7 rsExpandable">${rsTop('Recent results','graded','Newest first')}<ul class="scGames">`
    +list.map((r,i)=>{
      const won=String(r.result||'').toLowerCase()==='win';
      const p=Number(r.probability_pct);
      const [away,home]=String(r.event_name||'').split(' at ');
      // Scores are published home–away.
      const [hs,as]=String(r.score||'').split(/[–-]/).map(s=>s.trim());
      const hn=Number(hs),an=Number(as);
      const teams=home
        ? _scTeamLine(away,as,an>hn)+_scTeamLine(home,hs,hn>an,'at')
        : `<div class="scTeam"><span>${esc(r.event_name||'')}</span><b>${esc(r.score||'')}</b></div>`;
      return `<li class="scGame ${won?'hit':'miss'}${i>=4?' rsExtra':''}">${teams}`
        +`<div class="scGamePick"><span>Pick · ${esc(typeof rsShortName==='function'?rsShortName(r.selection):(r.selection||''))}${Number.isFinite(p)?` ${modelPctLabel(p)}`:''}</span>`
        +`<b>${won?'✓ Won':'✗ Lost'}</b></div></li>`;
    }).join('')+`</ul>`
    +(list.length>4?rsMoreBtn(list.length,'View all','Recent results'):'')+`</section>`;
}
function renderScore(){
  const host=$('#view-score'),sc=betbetterScorecard();
  if(!sc||sc.available===false){
    // The engine states its own reason ("no locked cards stored for ncaam"),
    // which is the honest one -- but it is a field value, not a sentence.
    const why=String(sc?.reason||'no graded record for this sport yet');
    host.innerHTML=`<div class="vhead">Scorecard</div><div class="empty">`
      +`<b>${esc(why.charAt(0).toUpperCase()+why.slice(1).replace(/\.$/,''))}.</b> `
      +`Cards freeze an hour before kickoff and are graded once the game is final.</div>`;
    return;
  }
  const rec=sc.record||{},totals=sc.totals||{},vm=sc.versus_market||{},scope=sc.scope||{};
  const ci=Array.isArray(rec.confidence_interval_pct)?rec.confidence_interval_pct:null;
  const priced=Number(vm.graded_priced_selections);
  // Beating the price is a pairwise comparison, so its baseline is a coin flip
  // at 50%. The interval settles it: straddling 50 means "not yet separable".
  const bm=vm.beat_market||null;
  const bmCi=bm&&Array.isArray(bm.confidence_interval_pct)?bm.confidence_interval_pct:null;
  const straddles=bmCi&&Number(bmCi[0])<50&&Number(bmCi[1])>50;
  const pending=Number(totals.awaiting_result)||0;
  const method=`<details class="scMethod"><summary>Methodology <span aria-hidden="true">ⓘ</span></summary><div>`
    +`<p><b>Locking.</b> The latest forecast at or before 60 minutes to kickoff, and the market price then, are recorded and never changed. Only verified final results are graded.</p>`
    +`<p><b>Model record</b> is wins over graded picks. <b>Expected</b> is the average probability the model gave its picks; the gap between the two is calibration.</p>`
    +`<p><b>Against the price</b> is how often the model's probability beat the locked market price${Number.isFinite(priced)?` across ${priced} priced selections`:''}${bm&&bm.wins!=null?` (${bm.wins}–${bm.losses}${bm.ties?`, ${bm.ties} tied`:''})`:''}. Two forecasters on the same games are a coin flip at 50%.${vm.basis?` Price: ${esc(vm.basis)}.`:''}</p>`
    +`<p><b>Intervals</b> are 95% confidence intervals; small samples move the point estimate a long way.</p>`
    +`<p>${esc(totals.graded_selections??'—')} graded selections across ${esc(totals.locked_events??'—')} locked cards; a card can carry more than one selection.${pending?` ${pending} await a final score.`:''}</p>`
    +(sc.caveat?`<p>${esc(scorecardCaveat(sc.caveat))}</p>`:'')
    +(scope.winner_note?`<p><b>It predicts ${esc(scope.predicts||'who wins')}.</b> ${esc(scope.winner_note)}</p>`:'')
    +(scope.spread_note?`<p><b>It does not predict ${esc(scope.does_not_predict||'the spread')}.</b> ${esc(scope.spread_note)}</p>`:'')
    +(scope.conviction_note?`<p>${esc(scope.conviction_note)}</p>`:'')
    +`</div></details>`;
  const reportable=sc.reportable===false
    ? `<div class="banner" style="margin-bottom:14px"><b>Not yet a reportable record.</b> `
      +`Fewer than ${esc(sc.minimum_picks_to_read??'the minimum')} graded picks, so the rate below is not a measurement yet.</div>`
    : '';
  const record=`<section class="rsBlock rsSpan7">${rsTop('Model record','graded',`${esc(rec.picks??'—')} graded picks`)}`
    +`<div class="scLead"><div><strong class="scBig">${esc(rec.wins??'—')}–${esc(rec.losses??'—')}</strong><span class="rsKicker">Wins–losses</span></div>`
    +`<div><strong class="scBig">${_scPct(rec.hit_rate_pct)}</strong><span class="rsKicker">Hit rate</span></div></div>`
    +`<dl class="rsSummary scLeadCtx"><div><dt>Expected</dt><dd>${_scPct(rec.expected_hit_rate_pct)}</dd></div>`
    +`<div><dt>vs expected</dt><dd>${_scGap(rec.calibration_gap_points)}</dd></div>`
    +(ci?`<div><dt>95% CI</dt><dd>${_scNum(ci[0])}–${_scNum(ci[1])}%</dd></div>`:'')+`</dl></section>`;
  const price=`<section class="rsBlock rsSpan5">${rsTop('Against the price','graded')}`
    +_scCompare([['Actual',_scPct(vm.beat_market_pct)],['Expected',bm?_scPct(bm.expected_hit_rate_pct):'50.0%'],['Difference',bm?_scGap(bm.calibration_gap_points):'—']])
    +`<p class="rsFeatRead">${straddles?'Matchday and the market are not yet separable on this sample.':'Above 50% the model is the better forecaster of the two; below it, the market is.'}</p>`
    +(bmCi?`<p class="rsFine">95% CI ${_scNum(bmCi[0])}–${_scNum(bmCi[1])}%. A coin flip is 50%.</p>`:'')+`</section>`;
  const grid=(...cells)=>{const c=cells.filter(Boolean);return c.length?`<div class="rsRow">${c.join('')}</div>`:''};
  const part=typeof rsPart==='function'?rsPart:(n,l,b)=>b;
  host.innerHTML=`<div class="vhead">Scorecard</div>`
    +`<div class="scIntro">${method}</div>`+reportable
    +`<section class="collegeResearch scorecardPage">`
    +part('01','The record',grid(record,price))
    +part('02','Against the market',grid(_scMarket(vm,sc.conviction)))
    +part('03','Calibration and results',grid(_scBands(sc.by_confidence),_scRecent(sc.recent)))
    +`</section>`;
}
function highlightFavoriteRows(){if(!favoriteTeam())return;document.querySelectorAll('.gtable .gteam').forEach(cell=>{if(teamKey(cell.dataset.team||cell.textContent).includes(teamKey(favoriteTeam())))cell.closest('tr')?.classList.add('favoriteTeamRow')})}
/* Every page title carries a short, muted descriptor on its right instead of
   an explanatory sentence beneath it. One place, so the tabs stay consistent. */
const PAGE_TAGS={
  news:()=>'Model · Team · Conference',
  score:()=>'Public model record',
  groups:()=>{const s=(typeof MATCHDAY_CFB_RANKINGS!=='undefined'&&MATCHDAY_CFB_RANKINGS?.season)||'';return `${s?s+' ':''}team ratings`},
  results:()=>'Final scores',
  bracket:()=>'Playoff projection',
  community:()=>'Picks & polls',
  insights:()=>'Model recaps',
  customize:()=>'Saved in this browser',
};
function tagPageHead(){
  const view=document.getElementById('view-'+VIEW),head=view?.querySelector('.vhead');
  const tag=PAGE_TAGS[VIEW]?.();
  if(!head||!tag||head.querySelector('.pageTag'))return;
  head.classList.add('pageHead');
  head.insertAdjacentHTML('beforeend',`<small class="pageTag">${esc(tag)}</small>`);
}
function renderCurrent(){captureSignalsIfFresh();({home:renderHome,matches:renderMatches,results:renderResults,groups:renderStandings,bracket:renderBracket,score:renderScore,news:renderNews,community:renderCommunity}[VIEW]||renderHome)();renderWelcome();highlightFavoriteRows();applyStaticI18n();tagPageHead()}
function renderStrip(){const M=DATA.matches||[],next=M.filter(isVisibleUpcoming).sort((a,b)=>(a.kickoff||'').localeCompare(b.kickoff||''))[0];const parts=[];
const isSample=(DATA.source_note||'').toLowerCase().includes('sample');
const freshness=DATA.source_freshness||{},fallback=freshness.state==='fallback';
const syncedAt=typeof MATCHDAY_BETBETTER_GENERATED_AT!=='undefined'?MATCHDAY_BETBETTER_GENERATED_AT:'';
parts.push(isSample?`<span class="ls-badge sample">${t("sample data")}</span>`:`<span class="ls-badge ok">${t("data feed")}</span>`);
const streakStats=btmStats(btmGrade());
if(streakStats.streak>=2)parts.push(`<span class="ls-streak" title="Beat the Model: ${streakStats.streak} correct in a row" onclick="setView('community')">\u{1F525} ${streakStats.streak}</span>`);
if(next)parts.push(`<span class="ls-next ls-clickable" data-mid="${esc(next.id)}" onclick="openMatchModal(this.dataset.mid)" role="button" tabindex="0" title="Open expanded view">Next · <b>${esc(next.home.code)} v ${esc(next.away.code)}</b> ${kickIn(next.kickoff)}</span>`);else parts.push(`<span class="ls-next">No upcoming fixtures</span>`);parts.push(`<span class="ls-upd">${fallback&&syncedAt?`Predictions synced ${ago(syncedAt)} · `:fallback?`<b class="stale">data source ${ago(freshness.last_successful_at||DATA.updated)}</b> · `:(()=>{try{const a=(Date.now()-new Date(DATA.updated))/60000;if(a>360)return `<b class="stale">data ${ago(DATA.updated)}</b> · `;}catch(e){}return 'Updated '+ago(DATA.updated)+' · ';})()}${t("independent · built for fans")} · <b style="color:var(--signal)">build ${currentBuild()}</b></span>`);$('#strip').innerHTML=parts.join('')}
/* removed duplicate (diverseNews) */
/* removed duplicate (renderInsight) */
const VIEW_PUBLIC_NAMES={home:'home',matches:'games',groups:'rankings',news:'research'};
function syncViewLocation(v,mode='push'){
  if(!window.history?.pushState)return;
  const url=new URL(window.location.href),publicName=VIEW_PUBLIC_NAMES[safeView(v)]||safeView(v),sport=currentSportKey();
  if(url.searchParams.get('view')===publicName&&url.searchParams.get('sport')===sport)return;
  url.searchParams.set('view',publicName);if(sport)url.searchParams.set('sport',sport);url.searchParams.delete('match');
  window.history[mode==='replace'?'replaceState':'pushState']({view:publicName,sport},'',url);
}
function setView(v,options={}){VIEW=safeView(v);v=VIEW;if(typeof closeNavSheet==='function')closeNavSheet();
  $('#app')?.classList.toggle('gamesWide',v==='matches'||v==='home');document.querySelectorAll('.navbtn[data-v]').forEach(b=>{const on=b.dataset.v===v;b.setAttribute('aria-pressed',on);if(on)b.setAttribute('aria-current','page');else b.removeAttribute('aria-current')});document.querySelectorAll('.view').forEach(el=>el.style.display=el.id==='view-'+v?((v==='matches'||v==='results')?'grid':'block'):'none');if(options.history!==false)syncViewLocation(v,options.replace?'replace':'push');renderCurrent();const active=$('#view-'+v);if(active){active.classList.remove('viewEntering');void active.offsetWidth;active.classList.add('viewEntering')}}
$('#nav').addEventListener('click',e=>{const b=e.target.closest('.navbtn[data-v]');if(b?.dataset.v)setView(b.dataset.v)});
// aggregateScorecards() lived here: it merged every sport's scorecard into the
// one the merged "All college" board showed. Each board now reads its own
// sport's scorecard straight from that sport's data file.
// A unique ?_=<timestamp> on every poll made each request a distinct URL, so
// no browser or CDN cache could ever serve or revalidate it: each refresh
// re-downloaded the full payload -- 9.8MB across the all-sports view -- to
// receive bytes that only change when the hourly build publishes. cache
// 'no-cache' revalidates instead of guessing: the browser sends the ETag it
// holds and a server with nothing new answers 304 with no body at all. Data
// arrives exactly as promptly, having cost a few hundred bytes instead of
// megabytes. Not 'no-store', which would forbid keeping a copy to revalidate
// against and put us straight back to full downloads.
const REVALIDATE={cache:'no-cache'};
let LOAD_SEQUENCE=0;
const SPORT_DATA_CACHE=Object.create(null);
const SPORT_PREFETCH=Object.create(null);
function showSportData(payload,cached=false){
  DATA=cached?payload:stripPastSeasonCompetitionViews(payload);
  const loadAlert=$('#alertBar');if(loadAlert?.textContent==='The data connection failed. Use Retry loading below.'){loadAlert.style.display='none';loadAlert.textContent=''}
  if(!cached){applyForecastPublicationPauses(DATA);applyCurrentCfbSnapshot(DATA);applyCurrentNcaamSnapshot(DATA);decodeNewsEntities(DATA);DATA.news=(DATA.news||[]).filter(isFreshNews).sort((a,b)=>newsTime(b)-newsTime(a))}
  SPORT_DATA_CACHE[DATA_FILE]=DATA;
  BYID={};(DATA.matches||[]).forEach(m=>BYID[m.id]=m);
  LAST_OK=true;LAST_ERROR='';
  const tb=document.querySelector('.navbtn[data-v="third"]');if(tb)tb.style.display=(DATA.third_race&&DATA.third_race.length)?'':'none';
  const gb2=document.querySelector('.navbtn[data-v="groups"]');if(gb2)gb2.style.display=(DATA.standings&&DATA.standings.length)?'':'none';
  applySportNav();renderStrip();renderInsight();renderCurrent();applyStaticI18n();renderAlerts();
}
function prefetchOtherSport(){
  const other=DATA_FILE==='data_ncaaf.json'?'data_ncaam.json':'data_ncaaf.json';
  if(SPORT_DATA_CACHE[other]||SPORT_PREFETCH[other])return;
  // The basketball payload is several megabytes. Pulling it immediately after
  // football made first visits compete with an invisible download on phones.
  // A switch still loads normally; only speculative background work is gated.
  const connection=navigator.connection||navigator.mozConnection||navigator.webkitConnection;
  if(connection?.saveData||/^(?:slow-)?2g|3g$/i.test(connection?.effectiveType||'')||matchMedia('(max-width:760px)').matches)return;
  const start=()=>{if(SPORT_DATA_CACHE[other]||SPORT_PREFETCH[other])return;SPORT_PREFETCH[other]=fetch(other,REVALIDATE).then(r=>{if(!r.ok)throw new Error('HTTP '+r.status);return r.json()}).catch(()=>null)};
  if('requestIdleCallback' in window)requestIdleCallback(start,{timeout:5000});else setTimeout(start,2500);
}
async function load(manual=false){const loadSequence=++LOAD_SEQUENCE,requestedFile=DATA_FILE;if(LOAD_TIMER){clearTimeout(LOAD_TIMER);LOAD_TIMER=null}try{
  // One board, one file. The merged "All college" view used to assemble itself
  // here out of board_summary.json (or, failing that, every per-sport file at
  // once) and then escalate to the full files when a visitor left the board;
  // none of that machinery is needed to load a single sport.
  const pending=SPORT_PREFETCH[requestedFile];const payload=pending?await pending:null;
  const fresh=payload||await (async()=>{
    const controller=new AbortController(),timeout=setTimeout(()=>controller.abort(),15000);
    try{const r=await fetch(requestedFile,{...REVALIDATE,signal:controller.signal});if(!r.ok)throw new Error('HTTP '+r.status);return await r.json()}
    finally{clearTimeout(timeout)}
  })();
  SPORT_PREFETCH[requestedFile]=null;
  if(loadSequence!==LOAD_SEQUENCE||requestedFile!==DATA_FILE)return;
  // .some() passes (element,index): the index landed on isForecastPaused's
  // `payload` parameter, so the competition check read match._comp, which only
  // the merged build set -- the banner fired on every board except MLB's own.
  showSportData(fresh);prefetchOtherSport()}catch(e){if(loadSequence!==LOAD_SEQUENCE||requestedFile!==DATA_FILE)return;console.error(e);if(SPORT_DATA_CACHE[requestedFile]&&LAST_OK){LAST_ERROR=String(e.message||e);return}applySportNav();
  const sel=currentSportKey();
  if(sel&&(!DATA||((DATA.comp_key||'').toLowerCase()!==sel))){
    DATA={matches:[],news:[],standings:[],third_race:[],bracket:null,scorecard:null,title_odds:[],scorers:[],team_of_tournament:null,
          comp_key:sel.toUpperCase(),competition:(SPORT_LABELS[sel]||sel),updated:'',_missing:true};
    BYID={};
  }
  applySportNav();LAST_OK=false;LAST_ERROR=String(e.message||e);$('#strip').textContent='data unavailable';
  const notice='<div class="empty scLoadError"><b>Matchday data did not load.</b><br>Check your connection, then try again.<br><button class="actionbtn" type="button" onclick="load(true)">Retry loading</button></div>';
  document.querySelectorAll('.view').forEach(view=>{view.innerHTML=notice;view.style.display=view.id==='view-'+VIEW?'block':'none'});
  const alert=$('#alertBar');if(alert){alert.style.display='block';alert.textContent='The data connection failed. Use Retry loading below.'}
}finally{if(loadSequence===LOAD_SEQUENCE){const ss=$('#sportSel');if(ss)ss.value=(DATA_FILE.match(/data_(\w+)\.json/)||['','ncaaf'])[1];scheduleNextLoad()}}}
function scheduleNextLoad(){if(LOAD_TIMER)clearTimeout(LOAD_TIMER);LOAD_TIMER=setTimeout(()=>load(),Math.max(30,Number(SETTINGS.refresh)||60)*1000)}


/* ===== UI PATCH: keep data untouched; improve news source logic and match opening ===== */
/* removed duplicate (_srcClean) */
/* removed duplicate (_srcFromTitle) */
/* removed duplicate (_srcFromLink) */
/* removed duplicate (sourceName) */
/* removed duplicate (feedName) */
/* removed duplicate (newsBuckets) */
/* removed duplicate (newsSources) */
/* removed duplicate (diverseNews) */
/* removed duplicate (renderNews) */
// Polls and Matchday rankings are separate tables; keep their provenance
// visible even though the college table renderer is shared with conferences.
const _renderGroupsWithRankingSources=renderGroups;
renderGroups=function(){
  _renderGroupsWithRankingSources();
  if(!['NCAAF','NCAAM'].includes(String(DATA.comp_key||'').toUpperCase()))return;
  document.querySelectorAll('#view-groups .groupHead').forEach(head=>{
    const label=String(head.childNodes[0]?.textContent||'').trim();
    const note=head.querySelector('span');
    if(!note)return;
    if(label==='Matchday Top 25')note.textContent='Matchday model · separate from the poll';
    else if(/(?:AP Top 25|playoff|coaches|national poll)/i.test(label))note.textContent='official national poll';
  });
};
/* dedup */
function ensureMatchModal(){let modal=document.getElementById('matchModal');if(modal)return modal;modal=document.createElement('div');modal.id='matchModal';modal.className='matchModal';modal.addEventListener('click',e=>{if(e.target===modal)closeMatchModal()});document.body.appendChild(modal);return modal}

/* ===== Team Stats — compiled per-team profile, one page per team =========
   Every number here is data the app already collects (standings, form,
   class/Elo rating, split form, schedule) -- no new data source. No
   individual player stats: only soccer's top-20 scorers are ever
   available, and NFL/NBA have no free player-stat access at all, so a
   "per player" page would be mostly empty for most players. */
function ensureTeamModal(){let modal=document.getElementById('teamModal');if(modal)return modal;modal=document.createElement('div');modal.id='teamModal';modal.className='matchModal teamModal';modal.addEventListener('click',e=>{if(e.target===modal)closeTeamModal()});document.body.appendChild(modal);return modal}
function closeTeamModal(){const modal=document.getElementById('teamModal');if(modal)modal.classList.remove('show');document.body.classList.remove('modalOpen')}
function computeTeamProfile(name){
  const key=teamKey(name);
  const rankings=String(DATA.comp_key||'').toUpperCase()==='NCAAM'
    ?(typeof MATCHDAY_NCAAM_RANKINGS!=='undefined'?MATCHDAY_NCAAM_RANKINGS:null)
    :(typeof MATCHDAY_CFB_RANKINGS!=='undefined'?MATCHDAY_CFB_RANKINGS:null);
  const ranked=(rankings?.rankings||[]).find(r=>teamKey(r.name)===key)
    ||(rankings?.rankings||[]).find(r=>bbNameMatches(r.name,name))||null;
  let standRec=null;
  (DATA.standings||[]).filter(g=>g.table_type!=='power_ratings').forEach(g=>(g.teams||[]).forEach(t=>{if(bbNameMatches(t.name,name))standRec=t;}));
  const matches=(DATA.matches||[]).filter(m=>bbNameMatches(m.home?.name,name)||bbNameMatches(m.away?.name,name));
  let side=null;
  for(const m of matches){side=bbNameMatches(m.home?.name,name)?m.home:(bbNameMatches(m.away?.name,name)?m.away:null);if(side)break;}
  const rec=standRec||side||{name};
  const record=ranked?.record||rec.record||'';
  const recordParts=/^(\d+)\s*[-–]\s*(\d+)/.exec(record);
  const finished=matches.filter(m=>m.status==='FINISHED').sort((a,b)=>(b.kickoff||'').localeCompare(a.kickoff||''));
  const next=matches.filter(isVisibleUpcoming).sort((a,b)=>(a.kickoff||'').localeCompare(b.kickoff||''))[0];
  return {
    name: ranked?.name||rec.name||name, code: rec.code||side?.code||'',
    pos: ranked?.rank??rec.pos??null, pld: recordParts?Number(recordParts[1])+Number(recordParts[2]):(rec.pld??side?.pld??null),
    w: recordParts?Number(recordParts[1]):rec.w??null, d: rec.d??null, l: recordParts?Number(recordParts[2]):rec.l??null,
    gf: rec.gf??side?.gf??null, ga: rec.ga??side?.ga??null, gd: rec.gd??side?.gd??null,
    pts: rec.pts??side?.pts??null, form: rec.form||side?.form||'',
    formHome: side?.form_home||'', formAway: side?.form_away||'',
    rating: ranked?.rating??side?.rating??rec.rating??null,
    sos: ranked?.sos??null, offense: ranked?.adj_o??null, defense: ranked?.adj_d??null,
    conference: ranked?.conference||'', published: rankings?.published_on||'',
    next, recent: finished.slice(0,5)
  };
}
function teamProfileHTML(p){
  const twoWay=SANDBOX_TWO_WAY.has(String(DATA.comp_key||'').toLowerCase());
  const winPct=p.pld?((Number(p.w)||0)/p.pld*100).toFixed(1)+'%':'—';
  const formRow=(label,str)=>str?`<div class="tpFormRow"><span class="tpFormLbl">${esc(label)}</span><span class="tpFormDots">${str.trim().split(' ').map(r=>`<i class="tpDot ${r}">${esc(r)}</i>`).join('')}</span></div>`:'';
  const recentRows=(p.recent||[]).map(m=>{
    const home=bbNameMatches(m.home.name,p.name);
    const opp=home?m.away:m.home;
    const gf=home?m.score?.home:m.score?.away, ga=home?m.score?.away:m.score?.home;
    const res=gf>ga?'W':gf<ga?'L':'D';
    return `<div class="tpRecentRow"><i class="tpDot ${res}">${res}</i><span>${home?'vs':'@'} ${esc(opp.name||opp.code)}</span><b>${gf}-${ga}</b><span class="tpFaint">${esc(dt(m.kickoff)||'')}</span></div>`;
  }).join('');
  const nextLine=p.next?`<div class="tpNext"><span class="tpFaint">Next</span> ${bbNameMatches(p.next.home.name,p.name)?'vs':'@'} <b>${esc(bbNameMatches(p.next.home.name,p.name)?p.next.away.name:p.next.home.name)}</b> · ${kickIn(p.next.kickoff)}</div>`:'';
  const record=(p.w!=null)?`${p.w}-${p.l}${!twoWay&&p.d!=null?`-${p.d}`:''}`:'—';
  return `<div class="tpHead"><button class="modalClose" onclick="closeTeamModal()" aria-label="Close">×</button>
    <div class="tpCode">${esc(p.code)}</div><div class="tpName">${teamMark(p.name)}${esc(p.name)}</div>
    <div class="tpMeta">${p.pos?`Power #${p.pos} · `:''}${p.conference?`${esc(p.conference)} · `:''}${record!=='—'?`record ${record}`:'record pending'}${p.published?` · rating ${esc(p.published)}`:''}</div></div>
    <div class="tpBody">
      <div class="tpStatGrid">
        ${p.w!=null&&p.pld?`<div class="tpStat"><span class="tpStatLbl">Win rate</span><b>${winPct}</b></div>`:''}
        ${p.rating!=null?`<div class="tpStat"><span class="tpStatLbl">Power rating</span><b>${Number(p.rating).toFixed(1)}</b></div>`:''}
        ${p.sos!=null?`<div class="tpStat"><span class="tpStatLbl">Schedule</span><b>${Number(p.sos).toFixed(1)}</b></div>`:''}
        ${p.offense!=null?`<div class="tpStat"><span class="tpStatLbl">Adjusted offense</span><b>${Number(p.offense).toFixed(1)}</b></div>`:''}
        ${p.defense!=null?`<div class="tpStat"><span class="tpStatLbl">Adjusted defense</span><b>${Number(p.defense).toFixed(1)}</b></div>`:''}
      </div>
      ${formRow('Overall form',p.form)}
      ${formRow('Home form',p.formHome)}
      ${formRow('Away form',p.formAway)}
      ${nextLine}
      ${recentRows?`<div class="tpSeclbl">Recent results</div>${recentRows}`:''}
    </div>`;
}
function openTeamModal(name){
  const p=computeTeamProfile(name);
  const modal=ensureTeamModal();
  modal.innerHTML=`<section class="matchSheet teamSheet" role="dialog" aria-modal="true">${teamProfileHTML(p)}</section>`;
  modal.classList.add('show');document.body.classList.add('modalOpen');
}
/* modalModel removed */
/* removed duplicate (openMatchModal) */
function closeMatchModal(){const modal=document.getElementById('matchModal');if(modal)modal.classList.remove('show');document.body.classList.remove('modalOpen')}
document.addEventListener('keydown',e=>{if(e.key==='Escape')closeMatchModal()});
/* removed duplicate (cardHTML) */



/* ===== PATCH: better source diversity + compact two-sided bracket ===== */
const _ISO3={AFG:'AF',ALB:'AL',ALG:'DZ',AND:'AD',ANG:'AO',ARG:'AR',ARM:'AM',AUS:'AU',AUT:'AT',AZE:'AZ',BAH:'BS',BHR:'BH',BAN:'BD',BEL:'BE',BIH:'BA',BOL:'BO',BRA:'BR',BUL:'BG',CAM:'CM',CAN:'CA',CHI:'CL',CHN:'CN',COL:'CO',CRC:'CR',CRO:'HR',CUB:'CU',CZE:'CZ',DEN:'DK',DOM:'DO',ECU:'EC',EGY:'EG',ENG:'GB',ESP:'ES',FIN:'FI',FRA:'FR',GER:'DE',GHA:'GH',GRE:'GR',GUA:'GT',HAI:'HT',HON:'HN',HUN:'HU',IND:'IN',IDN:'ID',IRN:'IR',IRQ:'IQ',IRL:'IE',ISR:'IL',ITA:'IT',JAM:'JM',JPN:'JP',KOR:'KR',KUW:'KW',MAR:'MA',MEX:'MX',NED:'NL',NOR:'NO',NZL:'NZ',PAN:'PA',PAR:'PY',PER:'PE',POL:'PL',POR:'PT',QAT:'QA',ROU:'RO',RSA:'ZA',RUS:'RU',KSA:'SA',SCO:'GB',SEN:'SN',SRB:'RS',SUI:'CH',SVK:'SK',SVN:'SI',SWE:'SE',TUN:'TN',TUR:'TR',UKR:'UA',URU:'UY',USA:'US',VEN:'VE',WAL:'GB',CPV:'CV',CIV:'CI',CUW:'CW'};
function flagEmoji(code){code=String(code||'').toUpperCase().trim();let c=_ISO3[code]||(/^[A-Z]{2}$/.test(code)?code:'');if(!c)return'';return c.replace(/./g,ch=>String.fromCodePoint(127397+ch.charCodeAt(0)))}
function codeForTeam(name,explicit){if(explicit)return explicit;const n=String(name||'').toLowerCase();for(const g of DATA.standings||[])for(const t of g.teams||[])if(String(t.name||'').toLowerCase()===n)return t.code||'';for(const m of DATA.matches||[]){if(String(m.home?.name||'').toLowerCase()===n)return m.home.code||'';if(String(m.away?.name||'').toLowerCase()===n)return m.away.code||''}return''}
function bracketTeam(name,code,slot,score,win,live){const nm=name||'TBD',cd=codeForTeam(nm,code),fl=uiFlag(cd);return `<div class="bmTeam ${win?'win':''} ${live?'live':''}"><div class="bmName">${slot?`<span class="bmSlot">${esc(slot)}</span>`:''}${fl?`<span class="flag">${fl}</span>`:''}<span class="bmCode">${esc(cd||'')}</span><span>${nm==='TBD'?'<span class="bmTbd">TBD</span>':esc(nm)}</span></div><div class="bmScore">${score!=null?esc(score):''}</div></div>`}
function compactBracketMatch(km,last=false,side='left',isFinal=false){const pending=km.status==='LIVE',done=km.status==='FINISHED';const hs=km.score?.home,as=km.score?.away;const hw=done&&Number(hs)>Number(as),aw=done&&Number(as)>Number(hs);const cls=`brMini ${done?'done':''} ${isFinal?'finalCard':''} ${last?'':side==='right'?'connectL':'connectR'} ${(!km.home&&!km.away)?'tbd':''}`;return `<div class="${cls}">${isFinal?'<div class="finalBadge">Final</div>':''}<div class="bmMeta"><span>${esc(km.stage||km.round||'Match')}</span><span>${pending?'AWAITING FINAL':done?'FT':km.kickoff?dt(km.kickoff):'TBD'}</span></div>${bracketTeam(km.home,km.home_code||km.homeCode||'',km.home_slot||'',done?hs:null,hw,false)}${bracketTeam(km.away,km.away_code||km.awayCode||'',km.away_slot||'',done?as:null,aw,false)}</div>`}
/* removed duplicate (compactProjectedMatch) */
/* removed duplicate (roundMatches) */
function shortRoundName(name){return name.replace('Round of ','R').replace('Quarter-finals','QF').replace('Semi-finals','SF').replace('Third-place playoff','3rd')}
/* removed duplicate (bracketColumn) */
/* removed duplicate (renderBracket) */

function _srcClean(x){x=String(x||'').replace(/\s+/g,' ').trim();if(!x)return'';x=x.replace(/^www\./i,'').replace(/\.com$/i,'');const map=[[/espn|espn fc/i,'ESPN'],[/bbc/i,'BBC Sport'],[/guardian/i,'The Guardian'],[/sky\s*sports|skysports/i,'Sky Sports'],[/cbs/i,'CBS Sports'],[/fox\s*sports|foxsports/i,'FOX Sports'],[/reuters/i,'Reuters'],[/associated\s*press|^ap$/i,'Associated Press'],[/fifa/i,'FIFA'],[/le\s*monde|lemonde/i,'Le Monde'],[/marca/i,'Marca'],[/goal/i,'Goal'],[/yahoo/i,'Yahoo Sports'],[/nbc/i,'NBC Sports'],[/google\s*news/i,'Google News']];for(const [re,n] of map)if(re.test(x))return n;return x.split('|')[0].trim()}
function newsTime(a){const ts=Date.parse(a?.published||'');return Number.isFinite(ts)?ts:0}
function isFreshNews(a){const ts=newsTime(a),age=Date.now()-ts;return !!ts&&age>=-24*3600000&&age<=7*86400000}
function _srcFromTitle(a){const h=String(a.headline||a.title||'');const parts=h.split(/\s[-–—]\s/g).map(x=>x.trim()).filter(Boolean);if(parts.length>1){const tail=parts[parts.length-1];if(tail.length<=42&&!/world cup|football|soccer|latest|news|live/i.test(tail))return _srcClean(tail)}return''}
function _srcFromLink(a){try{const u=new URL(a.link||a.url||'',location.href);let h=u.hostname.replace(/^www\./,'');if(h.includes('news.google.'))return'';if(h.includes('espn'))return'ESPN';if(h.includes('bbc'))return'BBC Sport';if(h.includes('theguardian'))return'The Guardian';if(h.includes('skysports'))return'Sky Sports';if(h.includes('cbssports'))return'CBS Sports';if(h.includes('foxsports'))return'FOX Sports';if(h.includes('reuters'))return'Reuters';if(h.includes('apnews'))return'Associated Press';if(h.includes('fifa'))return'FIFA';if(h.includes('marca'))return'Marca';if(h.includes('goal'))return'Goal';return _srcClean(h.split('.')[0])}catch(e){return''}}
function sourceName(a){const raw=_srcClean(a.source_name||a.publisher||a.provider||a.source||a.feed_source||'');const feed=_srcClean(a.feed||'');const titleSrc=_srcFromTitle(a),linkSrc=_srcFromLink(a);const generic=s=>!s||/^(news|headlines|football|soccer|rss|google news|world cup)$/i.test(s);if(raw&&!generic(raw))return raw;if(titleSrc&&!generic(titleSrc))return titleSrc;if(linkSrc&&!generic(linkSrc))return linkSrc;if(feed&&!generic(feed))return feed;return raw||feed||'News'}
function feedName(a){const f=_srcClean(a.feed||'');return f&&f!==sourceName(a)?f:''}
function newsBuckets(){const buckets={};(DATA.news||[]).filter(isFreshNews).forEach((a,i)=>{const src=sourceName(a);(buckets[src] ||= []).push({...a,_idx:i})});Object.values(buckets).forEach(items=>items.sort((a,b)=>newsTime(b)-newsTime(a)));return buckets}
function newsSources(){const buckets=newsBuckets();return ['all',...Object.keys(buckets).sort((a,b)=>a.localeCompare(b))]}
function diverseNews(limit=12){
  const all=(DATA.news||[]).filter(isFreshNews);
  const buckets={};
  all.forEach((a,i)=>{const key=sourceName(a);(buckets[key]||=[]).push({...a,_idx:i})});
  Object.values(buckets).forEach(items=>items.sort((a,b)=>newsTime(b)-newsTime(a)));
  const keys=Object.keys(buckets).sort((a,b)=>newsTime(buckets[b][0])-newsTime(buckets[a][0])),out=[];let row=0;
  while(out.length<limit&&keys.length){let moved=false;for(const key of keys){const item=buckets[key][row];if(item){out.push(item);moved=true;if(out.length>=limit)break}}if(!moved)break;row++}
  const result=out.length?out:all.slice(0,limit),fav=favoriteNewsTerm();
  return fav?result.sort((a,b)=>Number(teamKey(`${b.headline||b.title||''} ${b.desc||''}`).includes(fav))-Number(teamKey(`${a.headline||a.title||''} ${a.desc||''}`).includes(fav))):result;
}
// A story's kind, from its own headline and summary: the card's colour and
// tag, and the order the grid is grouped in. First rule that matches wins, so
// "ruled out vs. South Carolina" is an injury, not a preview.
const NEWS_KINDS=[
  {key:'injury',label:'Injuries',re:/\b(injur\w*|ruled out|out for|miss(es|ing)? (the )?(game|week|season|extended)|availability report|questionable|doubtful|sidelined|surgery|concussion|torn|season-ending)\b/i},
  {key:'recruiting',label:'Recruiting',re:/\b(recruit\w*|commit\w*|decommit\w*|visit|offer(ed)?|signee|signing|transfer( portal)?|portal|\d-star|class of 20\d\d|20\d\d class)\b/i},
  {key:'offfield',label:'Off the field',re:/\b(lawsuit|court|injunction|ruling|ncaa (rule|eligib)|eligib\w*|nil\b|president|congress|senate|legislat\w*|act\b|fired|hired|hires|coaching (search|change)|suspend\w*|arrest\w*|investigation|conference realignment)\b/i},
  {key:'preview',label:'Game preview',re:/\b(vs\.?|versus|preview|predictions?|picks?|odds|spread|matchup|what to know|things to know|keys to|tale of the tape|how to watch|kickoff|game day|gameday|showdown|week \d+)\b/i},
];
function newsKind(a){const text=`${a.headline||a.title||''} ${a.desc||a.description||''}`;return NEWS_KINDS.find(k=>k.re.test(text))||{key:'general',label:'News'}}
const NEWS_KIND_ORDER=['injury','preview','recruiting','offfield','general'];
/* The news feed. One filter bar that switches between publications and story
   types, and cards with a single colour signal (the left edge), the category
   and original publication on top, and the aggregator demoted to the footer
   so it never reads as the author. */
let NEWS_MODE='sources',NEWS_KIND_FILTER='all';
function newsCard(a,k,lead){
  const feed=feedName(a),when=a.published?ago(a.published):'';
  const foot=[when,feed?`via ${esc(feed)}`:''].filter(Boolean).join(' · ');
  return `<a class="ncard nk-${k.key}${lead?' ncardLead':''}" href="${esc(a.link||a.url||'#')}" target="_blank" rel="noopener">`
    +`<div class="srcTop"><span class="newsKind">${esc(k.label)}</span><span class="srcName">${esc(sourceName(a))}</span></div>`
    +`<div class="nhead">${esc(a.headline||a.title||'Untitled')}</div>`
    +(a.desc||a.description?`<div class="ndesc">${esc(a.desc||a.description)}</div>`:'')
    +`<div class="nmeta"><span>${foot}</span><span class="narrow" aria-hidden="true">→</span></div></a>`;
}
function renderNews(){
  const n=DATA.news||[],host=$('#view-news');
  const buckets=newsBuckets(),srcs=newsSources();
  if(NEWS_FILTER!=='all'&&!buckets[NEWS_FILTER])NEWS_FILTER='all';
  const all=diverseNews(Math.max(n.length,18)).map((a,i)=>({a,i,k:newsKind(a)}));
  const kinds=NEWS_KIND_ORDER.map(key=>({key,label:key==='general'?'News':(NEWS_KINDS.find(k=>k.key===key)||{}).label,count:all.filter(x=>x.k.key===key).length})).filter(k=>k.count);
  if(NEWS_KIND_FILTER!=='all'&&!kinds.some(k=>k.key===NEWS_KIND_FILTER))NEWS_KIND_FILTER='all';
  let list;
  if(NEWS_MODE==='categories'){
    list=all.filter(x=>NEWS_KIND_FILTER==='all'||x.k.key===NEWS_KIND_FILTER);
  }else{
    list=NEWS_FILTER==='all'?all:(buckets[NEWS_FILTER]||[]).map((a,i)=>({a,i,k:newsKind(a)}));
  }
  list=list.slice().sort((x,y)=>NEWS_KIND_ORDER.indexOf(x.k.key)-NEWS_KIND_ORDER.indexOf(y.k.key)||x.i-y.i);
  const chip=(on,label,count,click)=>`<button class="chip ${on?'on':''}" onclick="${click}">${esc(label)}<span class="count">${count}</span></button>`;
  const chips=NEWS_MODE==='categories'
    ?chip(NEWS_KIND_FILTER==='all','All stories',all.length,"NEWS_KIND_FILTER='all';renderNews()")
      +kinds.map(k=>chip(NEWS_KIND_FILTER===k.key,k.label,k.count,`NEWS_KIND_FILTER='${k.key}';renderNews()`)).join('')
    :srcs.map(s=>`<button class="chip ${NEWS_FILTER===s?'on':''}" data-src="${esc(s)}" onclick="NEWS_FILTER=this.dataset.src;renderNews()">${esc(s==='all'?'All sources':s)}<span class="count">${s==='all'?n.length:(buckets[s]||[]).length}</span></button>`).join('');
  const mode=`<div class="newsMode" role="group" aria-label="Filter by">`
    +[['sources','Sources'],['categories','Categories']].map(([k,l])=>`<button type="button" aria-pressed="${NEWS_MODE===k}" onclick="NEWS_MODE='${k}';renderNews()">${l}</button>`).join('')+`</div>`;
  host.innerHTML=`<div class="vhead">News cycle</div>`
    +`<div class="newsTools">${mode}${chips}</div>`
    +(list.length?`<div class="newsGrid">${list.map((x,i)=>newsCard(x.a,x.k,i<2&&list.length>4)).join('')}</div>`:`<div class="empty">No headlines yet.</div>`);
}

const _renderNewsAsResearch=renderNews;
renderNews=function(){
  _renderNewsAsResearch();
  const host=$('#view-news');
  if(!host)return;
  const oldTitle=host.querySelector('.vhead');
  if(oldTitle)oldTitle.remove();
  // Research is useful even when the external headline feed is empty. Do not
  // leave a large empty news panel or expose fetch diagnostics to readers.
  host.querySelector('.diagList')?.remove();
  if(!diverseNews(Math.max((DATA.news||[]).length,18)).length){
    host.querySelector('.srcCount')?.remove();
    host.querySelector('.newsTools')?.remove();
    host.querySelector('.empty')?.remove();
  }
  const collegeAnalysis=typeof collegeResearchModules==='function'?collegeResearchModules():'';
  // College Research is model research only; the news feed is not shown.
  if(collegeAnalysis)host.replaceChildren();
  host.insertAdjacentHTML('afterbegin',`<div class="vhead">Research</div>
    ${collegeAnalysis}`);
}



/* ===== UI PATCH: model dashboard polish only; data untouched ===== */
function _modelHasVerifiedLock(m){return m?.prediction?.publication_state==='locked'}
function _modelIsPast(m){return m.status==='FINISHED'||isStaleUpcoming(m)}
function _modelIsArchived(m){return _modelIsPast(m)&&_modelHasVerifiedLock(m)}
function _highConfidenceAllowed(m){return m?.prediction?.lock_readiness?.confidence_guard?.high_confidence_label_allowed!==false}
function _modelEdgeKind(pr){if(!pr||pr.edge==null)return'level';return pr.edge>=6?'value':pr.edge<=-6?'fade':'level'}
function _modelSortScore(m){const pr=m.prediction||{};const archived=_modelIsArchived(m)?-10000:0;const upcoming=isVisibleUpcoming(m)?500:0;const edge=pr.edge==null?0:Math.max(0,pr.edge)*10;const conf=Number(pr.confidence)||0;return archived+upcoming+edge+conf}
function _modelMarketText(m,side){if(_modelIsArchived(m))return 'archived pick';const mk=(m.markets||{})['1x2']||{};const v={h:mk.home_pct,d:mk.draw_pct,a:mk.away_pct}[side];return v==null?'market n/a':`${v}% market`}
function _modelWhen(m){if(m.status==='LIVE')return 'Awaiting final';if(m.status==='FINISHED')return 'Finished';if(isStaleUpcoming(m))return 'Past kickoff';return kickIn(m.kickoff)}
function _modelTag(m){const pr=m.prediction||{},kind=_modelEdgeKind(pr);if(_modelIsArchived(m))return {txt:'ARCHIVE',kind:'level'};if(m.status==='LIVE')return {txt:'LOCKED',kind:'level'};if(kind==='value')return {txt:'VALUE',kind:'value'};if(kind==='fade')return {txt:'CAUTION',kind:'fade'};if((Number(pr.confidence)||0)>=65&&_highConfidenceAllowed(m))return {txt:'HIGH CONF',kind:'level'};return {txt:'MODEL',kind:'level'}}
function _modelBars(m){const md=officialPredictionProbabilities(m);const rows=_isTwoWay(m)?[['H','home',md.h],['A','away',md.a]]:[['H','home',md.h],['D','draw',md.d],['A','away',md.a]];return `<div class="modelBars">${rows.map(([lab,cls,val])=>{val=Math.max(0,Math.min(100,Number(val)||0));return `<div class="modelBarLine"><span>${lab}</span><div class="modelBarTrack"><span class="modelBarFill ${cls}" style="width:${Math.max(2,val)}%"></span></div><span>${modelPctLabel(val)}</span></div>`}).join('')}</div>`}
function _modelFinalText(m){const s=m.score||{};if(m.status==='FINISHED'&&s.home!=null&&s.away!=null)return `${s.home}–${s.away}`;return _modelWhen(m)}
/* dedup */
/* dedup */
function _modelApplyFilter(all){const f=window.MODEL_FILTER||'action';return all.filter(m=>{const archived=_modelIsArchived(m),pr=m.prediction||{},edge=Number(pr.edge)||0,conf=Number(pr.confidence)||0,hasOdds=!!((m.markets||{})['1x2']);if(f==='archive')return archived;if(archived)return false;if(f==='all')return true;if(f==='action'||f==='upcoming')return isVisibleUpcoming(m);if(f==='value')return isVisibleUpcoming(m)&&edge>=6;if(f==='caution')return isVisibleUpcoming(m)&&edge<=-6;if(f==='high')return isVisibleUpcoming(m)&&conf>=65&&_highConfidenceAllowed(m);if(f==='odds')return isVisibleUpcoming(m)&&hasOdds;return true})}
function _modelFilterBtn(key,label,count){const on=(window.MODEL_FILTER||'action')===key;return `<button class="chip ${on?'on':''}" onclick="window.MODEL_FILTER='${key}';MODEL_VISIBLE=MODEL_PAGE_SIZE;renderEdge()">${label}<span class="count">${count}</span></button>`}
function _archiveRow(m){const op=officialPrediction(m);return `<div class="archiveRow" onclick="openMatchModal('${esc(String(m.id||''))}')"><div><div class="archiveTeams">${esc(m.home?.code||m.home?.name||'H')} v ${esc(m.away?.code||m.away?.name||'A')}</div><div class="archiveMeta">${esc(m.stage||'Fixture')} · ${_modelWhen(m)}</div></div><div class="archiveResult">${esc(_modelFinalText(m))}</div><div class="archivePick">Pick <b>${esc(op.name||'—')}</b> · ${op.confidence??'—'}%</div><div class="archiveBadge">Review</div></div>`}
function renderEdge(){const host=$('#view-edge');const all=(DATA.matches||[]).filter(m=>m.prediction&&(!_modelIsPast(m)||_modelHasVerifiedLock(m))).sort((a,b)=>_modelSortScore(b)-_modelSortScore(a));if(!all.length){host.innerHTML=`<div class="vhead">Model</div>${(()=>{const sc=DATA.scorecard;if(!sc||!sc.graded)return '';const rec=`${sc.model_hits}-${sc.graded-sc.model_hits}`;const br=sc.brier3??sc.brier_advancement??sc.brier??'—';const brLabel=sc.brier3!=null?'Outcome Brier':sc.brier_advancement!=null?'Advancement Brier':'Pick-event Brier';const cl=sc.clv_avg!=null?(sc.clv_avg>0?'+':'')+sc.clv_avg+' pp':'—';const vs=sc.value&&sc.value.all?`${sc.value.all.hits}/${sc.value.all.n}`:'—';return `<div class="credstrip"><span class="credtag">Model record</span><span class="creditem"><b>${rec}</b> last ${sc.graded}</span><span class="creditem">${brLabel} <b>${br}</b></span><span class="creditem">Line movement <b>${cl}</b></span><span class="creditem">Value <b>${vs}</b></span>${sc.graded<20?'<span class="crednote">small sample</span>':''}</div>`;})()}${FORECAST_PAUSE_ACTIVE?`<div class="empty forecastPaused" role="status"><b>Pick board is paused</b><span>${esc(FORECAST_PAUSE_MESSAGE)}</span><em>Graded picks return here once publication resumes. <a href="qa.html#pause">Why, and what comes next</a></em></div>`:'<div class="empty">No model picks yet.</div>'}`;return}if(!window.MODEL_FILTER||window.MODEL_FILTER==='finished'||window.MODEL_FILTER==='live')window.MODEL_FILTER='action';
  // Paused: the pregame tab is empty by construction, so open on the graded
  // record rather than dropping the reader onto a blank board.
  if(FORECAST_PAUSE_ACTIVE&&window.MODEL_FILTER==='action'&&!all.some(isVisibleUpcoming))window.MODEL_FILTER='archive';const archived=all.filter(_modelIsArchived).sort((a,b)=>new Date(b.kickoff||0)-new Date(a.kickoff||0));const active=all.filter(m=>!_modelIsArchived(m));const counts={all:active.length,action:active.filter(isVisibleUpcoming).length,upcoming:active.filter(isVisibleUpcoming).length,value:active.filter(m=>isVisibleUpcoming(m)&&(m.prediction?.edge||0)>=6).length,caution:active.filter(m=>isVisibleUpcoming(m)&&(m.prediction?.edge||0)<=-6).length,high:active.filter(m=>isVisibleUpcoming(m)&&(Number(m.prediction?.confidence)||0)>=65&&_highConfidenceAllowed(m)).length,odds:active.filter(m=>isVisibleUpcoming(m)&&!!((m.markets||{})['1x2'])).length,archive:archived.length};const list=_modelApplyFilter(all).sort((a,b)=>_modelSortScore(b)-_modelSortScore(a));const actionable=active.filter(isVisibleUpcoming);const value=active.filter(m=>isVisibleUpcoming(m)&&(m.prediction?.edge||0)>=6);const caution=active.filter(m=>isVisibleUpcoming(m)&&(m.prediction?.edge||0)<=-6);const high=active.filter(m=>isVisibleUpcoming(m)&&(Number(m.prediction?.confidence)||0)>=65&&_highConfidenceAllowed(m));const archiveMode=window.MODEL_FILTER==='archive';const shownRows=list.slice(0,MODEL_VISIBLE),moreRows=Math.max(0,list.length-shownRows.length);let html=`<div class="modelShell"><div class="modelHero"><div><div class="modelHeroTitle">Pregame model</div><div class="modelHeroSub">Verified locked pregame picks, market context, and postgame grading.</div></div><div class="modelKpis"><div class="modelKpi"><span>Pregame</span><b>${actionable.length}</b></div><div class="modelKpi good"><span>Model leans</span><b>${value.length}</b></div><div class="modelKpi warn"><span>High confidence</span><b>${high.length}</b></div><div class="modelKpi bad"><span>Graded</span><b>${archived.length}</b></div></div></div><div class="modelToolbar">${_modelFilterBtn('action','Pregame',counts.action)}${_modelFilterBtn('value','Model lean',counts.value)}${_modelFilterBtn('archive','Results',counts.archive)}</div>${_modelSpotlight(active)}<div class="modelGrid"><section class="modelPanel"><div class="modelPanelHead"><h3>${archiveMode?'Postgame results':'Pregame pick board'}</h3><span>${shownRows.length} of ${list.length}</span></div><div class="modelList">${shownRows.length?shownRows.map(_modelRow).join(''):`<div class="modelEmptySmall">No matches in this filter.</div>`}</div>${moreRows?`<div class="fixturePager"><span>Showing ${shownRows.length} of ${list.length} picks</span><button class="actionbtn" onclick="MODEL_VISIBLE+=MODEL_PAGE_SIZE;renderEdge()">Load ${Math.min(MODEL_PAGE_SIZE,moreRows)} more</button></div>`:''}</section><section class="modelPanel modelDigestPanel"><div class="modelPanelHead"><h3>${archiveMode?'Postgame reads':'Quick reads'}</h3><span>digest</span></div><div class="modelReadList">`;const reads=(list.length?list:(archiveMode?archived:active)).slice(0,5);html+=reads.map((m,i)=>{const pr=m.prediction||{},tag=_modelTag(m),txt=_modelIsArchived(m)?`${pr.pick_name||'Model'} was ${pr.confidence||'—'}%. Result: ${_modelFinalText(m)}.`:(edgeBreakdown(m)||`${pr.pick_name||'Model'} at ${pr.confidence||'—'}%.`);return `<div class="modelRead" onclick="openMatchModal('${esc(String(m.id||''))}')"><div class="rtitle"><span>${tag.txt}</span>${esc(m.home?.code||'H')} v ${esc(m.away?.code||'A')}</div><p>${esc(txt)}</p></div>`}).join('');html+=`</div></section>`;if(!archiveMode&&archived.length){html+=`<section class="modelPanel modelArchivePanel"><div class="modelPanelHead"><h3>Postgame results <span class="archiveBadge">${archived.length}</span></h3><span><button class="chip" onclick="window.MODEL_FILTER='archive';MODEL_VISIBLE=MODEL_PAGE_SIZE;renderEdge()">View results</button></span></div><div class="modelList">${archived.slice(0,8).map(_archiveRow).join('')}</div></section>`}html+=`</div></div>`;host.innerHTML=html}



/* ===== UI PATCH: complete bracket render; UI only, data untouched ===== */
function _canonRoundName(name){
  const x=String(name||'').toLowerCase().replace(/[_-]/g,' ');
  if(/knockout.*play.?off|play off round/.test(x))return 'Knockout phase play-offs';
  if(/round of 32|last 32|r32/.test(x))return 'Round of 32';
  if(/round of 16|last 16|r16/.test(x))return 'Round of 16';
  if(/quarter/.test(x)||/qf/.test(x))return 'Quarter-finals';
  if(/semi/.test(x)||/sf/.test(x))return 'Semi-finals';
  if(/third|3rd/.test(x))return 'Third-place playoff';
  if(/final/.test(x))return 'Final';
  return String(name||'');
}
function _bracketSourceMap(rounds){
  const map={};
  (Array.isArray(rounds)?rounds:[]).forEach(r=>{
    const key=_canonRoundName(r.round||r.stage||r.name);
    if(!key)return;
    (map[key] ||= []).push(...(r.matches||[]));
  });
  return map;
}
function _slotTBD(label){return {slot:label,team:'TBD',code:'',pts:0,gd:0,live:false}}
function _projectedSlots32(){
  const src=getProjectedSlots();
  const out=[];
  for(let i=0;i<32;i++)out.push(src[i]||_slotTBD(`Seed ${i+1}`));
  return out;
}
function _pairFromSlots(slots,i,label){
  const a=slots[i]||_slotTBD(`Seed ${i+1}`),b=slots[i+1]||_slotTBD(`Seed ${i+2}`);
  return {stage:label,home:a.team,home_code:a.code,home_slot:a.slot,away:b.team,away_code:b.code,away_slot:b.slot,status:'PROJECTED',score:{}};
}
function _winnerPair(prev,idx,label){
  return {stage:label,home:`Winner ${prev} ${idx*2+1}`,home_slot:'path',away:`Winner ${prev} ${idx*2+2}`,away_slot:'path',status:'TBD',score:{}};
}
function _completeProjectedRounds(){
  const slots=_projectedSlots32();
  return [
    {round:'Round of 32',matches:Array.from({length:16},(_,i)=>_pairFromSlots(slots,i*2,`R32 ${i+1}`))},
    {round:'Round of 16',matches:Array.from({length:8},(_,i)=>_winnerPair('R32',i,`R16 ${i+1}`))},
    {round:'Quarter-finals',matches:Array.from({length:4},(_,i)=>_winnerPair('R16',i,`QF ${i+1}`))},
    {round:'Semi-finals',matches:Array.from({length:2},(_,i)=>_winnerPair('QF',i,`SF ${i+1}`))},
    {round:'Final',matches:[{stage:'Final',home:'Winner SF 1',home_slot:'path',away:'Winner SF 2',away_slot:'path',status:'TBD',score:{}}]},
    {round:'Third-place playoff',matches:[{stage:'Third place',home:'Loser SF 1',home_slot:'path',away:'Loser SF 2',away_slot:'path',status:'TBD',score:{}}]}
  ];
}
function _completeRounds(){
  const source=_bracketSourceMap(DATA.bracket||[]),projected=_completeProjectedRounds(),wanted=['Round of 32','Round of 16','Quarter-finals','Semi-finals','Final','Third-place playoff'];
  return wanted.map(name=>{
    const fallback=projected.find(r=>r.round===name)?.matches||[];
    const official=source[name]||[];
    if(!official.length)return {round:name,matches:fallback};
    const need=fallback.length||official.length;
    const merged=[];
    for(let i=0;i<need;i++)merged.push(official[i]||fallback[i]);
    return {round:name,matches:merged};
  });
}
function projectedRounds(){return _completeProjectedRounds()}
function roundMatches(rounds,name){const key=_canonRoundName(name);const r=(rounds||[]).find(x=>_canonRoundName(x.round||x.stage||x.name)===key);return r?.matches||[]}
function compactProjectedMatch(km,last=false,side='left',isFinal=false){
  const cls=`brMini ${isFinal?'finalCard':''} ${last?'':side==='right'?'connectL':'connectR'} ${((km.home||'').includes('Winner')||(km.home||'')==='TBD')?'tbd':''}`;
  return `<div class="${cls}">${isFinal?'<div class="finalBadge">Final</div>':''}<div class="bmMeta"><span>${esc(km.stage||'Projected')}</span><span>${km.status==='PROJECTED'?'projected':'path'}</span></div>${bracketTeam(km.home,km.home_code||'',km.home_slot||'',null,false,false)}${bracketTeam(km.away,km.away_code||'',km.away_slot||'',null,false,false)}</div>`;
}
function bracketColumn(title,matches,side,official,connect=true){
  return `<section class="brCol"><div class="roundTitle">${esc(shortRoundName(title))}</div>${(matches||[]).map(m=>{
    const real=m&&m.status&&m.status!=='TBD'&&m.status!=='PROJECTED';
    return (official&&real)?compactBracketMatch(m,!connect,side,false):compactProjectedMatch(m,!connect,side,false);
  }).join('')}</section>`;
}
/* dedup */



/* ===== UI PATCH: pitch lineups, flags, and richer odds board; UI only ===== */
function uiFlag(code){return''}
function uiTeamFlag(team){return uiFlag(team?.code||codeForTeam(team?.name||'',team?.code||''))}
function teamFlagHTML(team,away=false){const fl=uiTeamFlag(team);return fl?`<span class="flagIcon ${away?'away':''}">${fl}</span>`:''}
function shortPlayerName(name){const s=String(name||'').trim();if(!s)return'';const parts=s.split(/\s+/).filter(Boolean);return parts.length>1?parts[parts.length-1]:s}
function formationParts(f){const nums=String(f||'').match(/\d+/g);return nums?nums.map(Number).filter(n=>n>0):[]}
function normalizePlayer(p){return {n:String(p?.n??p?.number??'').trim(),name:String(p?.name??p?.shortName??p?.athlete?.displayName??'').trim(),out:!!p?.out}}
function lineupRows(xi,formation){const players=(xi||[]).map(normalizePlayer).filter(p=>p.n||p.name);if(!players.length)return[];const parts=formationParts(formation);if(!parts.length){const rows=[];for(let i=0;i<players.length;i+=3)rows.push(players.slice(i,i+3));return rows}const rows=[];let idx=0;rows.push(players.slice(idx,idx+1));idx+=1;parts.forEach(c=>{rows.push(players.slice(idx,idx+c));idx+=c});if(idx<players.length)rows.push(players.slice(idx));return rows.filter(r=>r.length)}
function pitchPlayer(p){const nm=shortPlayerName(p.name)||`#${p.n||'?'}`;return `<div class="pitchPlayer ${p.out?'out':''}" title="${esc((p.n?('#'+p.n+' '):'')+(p.name||''))}"><div class="num">${esc(p.n||'—')}</div><div class="pname">${esc(nm)}</div>${p.out?'<span class="subMark">sub</span>':''}</div>`}
function pitchTeamCard(team,line,side){const rows=lineupRows(line?.xi||[],line?.formation||'');const fl=teamFlagHTML(team);const form=line?.formation||'XI';return `<div class="pitchCard ${side}"><div class="pitchHeader"><div class="pitchTeamName">${fl}<span>${esc(team?.name||side)}</span></div><div class="formationBadge">${esc(form)}</div></div>${rows.length?`<div class="pitch">${rows.map(r=>`<div class="pitchRow">${r.map(pitchPlayer).join('')}</div>`).join('')}</div>`:`<div class="emptyStats">Lineup not available.</div>`}<div class="lineupFoot"><span>${esc(team?.code||'')}</span><span>${rows.reduce((a,r)=>a+r.length,0)} players shown</span></div></div>`}
function rosterPlayer(p){
  const pos=String(p?.position||'').trim(),num=String(p?.n??p?.number??'').trim();
  const status=String(p?.roster_status||'').trim();
  return `<div class="rosterPlayer"><span class="rosterPos">${esc(pos||num||'—')}</span><b>${esc(p?.name||p?.shortName||p?.athlete?.displayName||'Player')}</b>${status&&status!=='ACT'?`<em>${esc(status)}</em>`:''}</div>`;
}
function rosterTeamCard(team,players,summary){
  return `<section class="rosterTeam"><div class="rosterTeamHead"><div><span>${esc(team?.code||'TEAM')}</span><b>${esc(team?.name||'Team')}</b></div><em>${players.length?`${players.length} listed`:'Roster profile'}</em></div>${players.length?`<div class="rosterPlayers">${players.map(rosterPlayer).join('')}</div>`:`<div class="rosterSummary"><b>${esc(summary.title)}</b><span>${esc(summary.note)}</span></div>`}</section>`;
}
function rosterPanel(m){
  const depth=m.personnel?.depth_chart||{},lineups=m.lineups||{};
  const rosterPlayers=raw=>(raw||[]).map(p=>({...normalizePlayer(p),position:p?.position||'',roster_status:p?.roster_status||''})).filter(p=>p.name);
  const homePlayers=rosterPlayers(depth.home?.players||lineups.home?.xi||[]);
  const awayPlayers=rosterPlayers(depth.away?.players||lineups.away?.xi||[]);
  const pr=m.prediction||officialPrediction(m)||{},meta=sportClassMeta(pr,m),edge=Number(pr?.why?.class||0);
  const label=meta.label||'Roster profile',source=meta.source?`Source: ${meta.source}`:(meta.note||'Built from the roster information available to Matchday.');
  const homeTitle=edge>0.05?'Stronger roster':edge<-.05?'Lighter roster':'Even roster grade';
  const awayTitle=edge<-.05?'Stronger roster':edge>.05?'Lighter roster':'Even roster grade';
  const available=homePlayers.length||awayPlayers.length||meta.coverage!=='unavailable';
  if(!available)return `<div class="lineupBoard rosterBoard"><div class="seclbl">Overall roster</div><div class="emptyStats"><b>Roster profile unavailable</b><span>Matchday does not have a verified roster source for this competition yet.</span></div></div>`;
  return `<div class="lineupBoard rosterBoard"><div class="rosterBoardTitle"><div><span class="seclbl">Overall roster</span><b>${esc(label)}</b></div><small>${esc(source)}</small></div><div class="rosterGrid">${rosterTeamCard(m.home,homePlayers,{title:homeTitle,note:homePlayers.length?'Current roster listing':source})}${rosterTeamCard(m.away,awayPlayers,{title:awayTitle,note:awayPlayers.length?'Current roster listing':source})}</div></div>`;
}
function teamSnap(team,side,comp){return `<div class="teamSnap ${side==='away'?'away':''}"><div class="snapCode">${teamFlagHTML(team,side==='away')}${esc(team?.code||side)}</div><div class="snapName">${esc(team?.name||'TBD')}</div><div class="snapMeta">${esc(teamStandingsMeta(team,comp,{diff:true,form:true,hideStaleRecord:String(comp||'').toUpperCase()==='NCAAF'}).join(' · '))}</div></div>`}
/* dedup */
function _v15RenderLeagueTable(st,host){const seen=new Set(),teams=[];(st||[]).forEach(g=>(g.teams||[]).forEach(t=>{const key=String(t.name||t.code||'').toLowerCase();if(key&&!seen.has(key)){seen.add(key);teams.push(t)}}));teams.sort((a,b)=>(Number(a.pos)||999)-(Number(b.pos)||999)||(Number(b.pts)||0)-(Number(a.pts)||0)||(Number(b.gd)||0)-(Number(a.gd)||0));host.innerHTML=`<div class="vhead">Table</div><div class="tablewrap leagueTableWrap"><div class="groupHead">${esc(DATA.competition||'League table')}<span>${teams.length} clubs · full table</span></div><table class="gtable"><thead><tr><th>Team</th><th>P</th><th>W</th><th>D</th><th>L</th><th>GF</th><th>GA</th><th>GD</th><th>Pts</th><th>Form</th></tr></thead><tbody>${teams.map((t,i)=>{const q=t.qual?`<span class="qbadge ${esc(t.qual.status||'')}" title="${esc(t.qual.note||'')}">${esc(t.qual.status||t.qual.note||'')}</span>`:'';return `<tr><td><div class="gteam teamClickable" data-team="${esc(t.name||'')}" onclick="openTeamModal(this.dataset.team)"><span class="pos">${t.pos||i+1}</span><span class="code">${esc(t.code||'')}</span>${esc(t.name||'')} ${q}</div></td><td>${t.pld??'—'}</td><td>${t.w??'—'}</td><td>${t.d??'—'}</td><td>${t.l??'—'}</td><td>${t.gf??'—'}</td><td>${t.ga??'—'}</td><td>${t.gd??'—'}</td><td><b>${t.pts??'—'}</b></td><td class="form">${esc(t.form||'')}</td></tr>`}).join('')}</tbody></table></div>`}
function renderStandings(){renderGroups()}
function renderGroups(){const _tables=deriveStandings(),polls=_tables.filter(isPollTable),st=_tables.filter(g=>!isPollTable(g)),host=$('#view-groups'),sc=DATA.scorers||[];if(!st.length&&!polls.length){host.innerHTML=`<div class="vhead">${['NCAAF','NCAAM'].includes(DATA.comp_key)?'Conferences':'Groups'}</div><div class="empty">No group data found yet.</div>`;return}if(navProfile()==='soccer_league'){_v15RenderLeagueTable(st,host);return}if(DATA.comp_key==='NCAAM'){host.innerHTML=pollSectionHTML(polls)+`<div class="vhead">Conferences</div>`+st.map(g=>`<div class="tablewrap"><div class="groupHead">${esc(g.group)}<span>Power breaks 0-0 ties</span></div><table class="gtable ncaamTable"><thead><tr><th>Team</th><th title="0–10 blend of talent, Elo and season results">Power</th><th>Record</th><th>Win%</th><th>PF/G</th><th>PA/G</th><th>Diff</th><th>Streak</th></tr></thead><tbody>${(g.teams||[]).map(t=>`<tr><td><div class="gteam teamClickable" data-team="${esc(t.name||'')}" onclick="openTeamModal(this.dataset.team)"><span class="pos">${t.pos||''}</span><span class="code">${esc(t.code||'')}</span>${esc(t.name||'')}</div></td><td>${t.rating!=null?Number(t.rating).toFixed(2):'—'}</td><td><b>${esc(t.record||`${t.w??'—'}-${t.l??'—'}`)}</b></td><td>${t.win_pct!=null?(Number(t.win_pct)*100).toFixed(1)+'%':'—'}</td><td>${t.avg_pf!=null&&Number(t.avg_pf)?Number(t.avg_pf).toFixed(1):'—'}</td><td>${t.avg_pa!=null&&Number(t.avg_pa)?Number(t.avg_pa).toFixed(1):'—'}</td><td>${t.gd!=null?esc(t.gd):'—'}</td><td class="form">${esc(t.form||'—')}</td></tr>`).join('')}</tbody></table></div>`).join('');return}const groupsTwoWay=SANDBOX_TWO_WAY.has(String(DATA.comp_key||'').toLowerCase());const americanSport=navProfile()==='us_sport'||navProfile()==='college';const ratingSorted=false;const US_SCORE_UNIT={ncaaf:['PF','PA'],ncaam:['PF','PA']};const[fLabel,aLabel]=US_SCORE_UNIT[String(DATA.comp_key||'').toLowerCase()]||['GF','GA'];const winPct=t=>t.pld?((Number(t.w)||0)/t.pld*100).toFixed(1)+'%':'—';host.innerHTML=pollSectionHTML(polls)+`<div class="vhead">${DATA.comp_key==='NCAAF'?'Conferences':americanSport?'Standings':'Groups'}</div>`+st.map(g=>`<div class="tablewrap"><div class="groupHead">${americanSport?esc(g.group||'Full table'):esc(g.group)}<span>${DATA.comp_key==='NCAAF'?'Conference record, then head-to-head':americanSport?(ratingSorted?'ranked by model rating':'ranked by win rate'):'Top 2 · 3rd'}</span></div><table class="gtable"><thead><tr><th>Team</th>${americanSport?'<th title="0–10 blend of talent, Elo and season results">Power</th>':''}${DATA.comp_key==='NCAAF'?'<th title="Conference record: games against teams in this table only">Conf</th>':''}<th>P</th><th>W</th>${groupsTwoWay?'':'<th>D</th>'}<th>L</th><th>${fLabel}</th><th>${aLabel}</th><th>${americanSport?'Diff':'GD'}</th><th>${americanSport?'Win%':'Pts'}</th><th>Form</th></tr></thead><tbody>${(g.teams||[]).map(t=>{const fl=uiFlag(t.code);const q=t.qual?`<span class="qbadge ${esc(t.qual.status)}" title="${esc(t.qual.note)}">${esc(t.qual.note)}</span>`:'';return `<tr class="${americanSport?'':(t.pos<=2?'qual':t.pos===3?'third':'')}"><td><div class="gteam teamClickable" data-team="${esc(t.name||'')}" onclick="openTeamModal(this.dataset.team)"><span class="pos">${t.pos||''}</span>${fl?`<span class="flagIcon">${fl}</span>`:''}<span class="code">${esc(t.code||'')}</span>${esc(t.name)} ${t.live?'<span class="liveMark">*</span>':''}${q}</div></td>${americanSport?`<td>${t.rating!=null?Number(t.rating).toFixed(2):'—'}</td>`:''}${DATA.comp_key==='NCAAF'?`<td><b>${esc(t.conf_record||'0-0')}</b></td>`:''}<td>${t.pld??'—'}</td><td>${t.w??'—'}</td>${groupsTwoWay?'':`<td>${t.d??'—'}</td>`}<td>${t.l??'—'}</td><td>${t.gf??'—'}</td><td>${t.ga??'—'}</td><td>${t.gd??'—'}</td><td><b>${americanSport?winPct(t):(t.pts??'—')}</b></td><td class="form">${esc(t.form||'')}</td></tr>`}).join('')}</tbody></table></div>`).join('')}

/* The published power rating, on the Conferences tab.
   The tab previously held conference tables only, so the ranking that the whole
   site is built on existed nowhere outside the home board. This renders the
   full rated table -- not just the 25 -- because the handoff carries every
   rated team and "who is 61st" is a real question a conference table cannot
   answer.

   Strength of schedule sits beside every rating, and the move column shows the
   change against last week's edition once there is one to compare with. */
function collegeRankingTableHTML(){
  const table=String(DATA.comp_key||'').toUpperCase()==='NCAAM'
    ?(typeof MATCHDAY_NCAAM_RANKINGS!=='undefined'?MATCHDAY_NCAAM_RANKINGS:null)
    :(typeof MATCHDAY_CFB_RANKINGS!=='undefined'?MATCHDAY_CFB_RANKINGS:null);
  const rows=table?.rankings||[];
  if(!rows.length)return '';
  const preseason=table?.coverage?.is_preseason_edition||table?.coverage?.first_poll;
  const num=(v,d=2)=>Number.isFinite(Number(v))?Number(v).toFixed(d):'—';
  const moved=rows.some(r=>r.movement!=null&&Number.isFinite(Number(r.movement)));
  const currentRecords=(DATA.standings||[]).filter(g=>!isPollTable(g)).flatMap(g=>g.teams||[]);
  const recordForRow=row=>{
    const completed=DATA.cfb_result_records?.[teamKey(row.name)];
    if(completed&&completed.pld>=(Number(row.season_games)||0))return completed.record;
    return currentRecords.find(t=>teamKey(t.name)===teamKey(row.name))?.record
      ||currentRecords.find(t=>bbNameMatches(t.name,row.name))?.record;
  };
  const body=rows.map(r=>`<tr${r.rank<=25?' class="pollRanked"':''}>`
    +`<td class="pollRank">${r.rank}</td>`
    +(moved?`<td class="pollMove">${movementTag(r)}</td>`:'')
    +`<td class="pollTeam"><span class="pollTeamInner">${esc(r.name)}${r.tier&&r.tier!=='power'?' <i class="pollTier">G5</i>':''}</span></td>`
    +`<td>${esc(r.conference||'—')}</td>`
    +`<td class="pollNum">${num(r.rating)}</td>`
    +`<td class="pollNum">${num(r.sos)}</td>`
    +`<td class="pollNum">${num(r.adj_o,1)}</td>`
    +`<td class="pollNum">${num(r.adj_d,1)}</td>`
    +`<td>${esc(recordForRow(r)||r.record||'')}</td></tr>`).join('');
  const withheld=(table?.withheld||[]).filter(w=>w?.team_name);
  const provisional=withheld.map(w=>`<tr><td>${esc(w.team_name)}</td><td>${num(w.rating)}</td><td>${Number.isFinite(Number(w.fcs_share))?(Number(w.fcs_share)*100).toFixed(1)+'%':'—'}</td></tr>`).join('');
  return `<section class="pollSection"><div class="pollHead">
      <div><div class="vhead" style="margin:0">${String(DATA.comp_key||'').toUpperCase()==='NCAAM'?'Basketball power rating':'Football power rating'}</div>
      <p class="pollMeta">${esc(table.basis?.label||'Model rating')} · ${rows.length} rated teams${table.published_on?` · published ${esc(table.published_on)}`:''}</p></div>
      
    </div>
    ${table.season_in_progress===false?'<div class="modWarn">Projection — the season has not started. This rates the completed season.</div>':''}
    <div class="pollScroll"><table class="pollTable powerTable${moved?' hasMove':''}"><thead><tr>
      <th>#</th>${moved?'<th title="Change since last week">Move</th>':''}<th>Team</th><th>Conference</th><th>Rating</th><th>SoS</th><th>Off</th><th>Def</th><th>Rec</th>
    </tr></thead><tbody>${body}</tbody></table></div>
    <details class="pollHelp"><summary aria-label="About the power ratings">?</summary><p>${esc(String(table.note||'').replace(/\.\./g,'.'))}</p><p>Provisional teams are shown below but have no FBS rank because most of their rating evidence comes from FCS games. They enter the ranked table when the source model has enough comparable FBS-opponent evidence.</p></details>
    ${provisional?`<details class="pollProvisional"><summary>Provisional teams · ${withheld.length} unranked</summary><div class="pollScroll"><table class="pollTable"><thead><tr><th>Team</th><th>Model rating</th><th>FCS schedule</th></tr></thead><tbody>${provisional}</tbody></table></div></details>`:''}
  </section>`;
}
/* The full ballot on the Conferences tab, above the power rating: every team's
   résumé on the four criteria it was ranked by, and the best résumés left off,
   so leaving a team out reads as a decision rather than an oversight. */
function collegeBallotTableHTML(){
  const b=typeof collegeBallot==='function'?collegeBallot():null;
  if(!b)return '';
  if(b.source==='x'){
    const rows=b.rankings.map(r=>`<tr${r.rank<=4?' class="pollRanked"':''}><td class="pollRank">${Number(r.rank)}</td><td class="pollTeam teamClickable" data-team="${esc(r.team_name)}" onclick="openTeamModal(this.dataset.team)"><span class="pollTeamInner">${teamMark(r.team_name)}<span>${esc(r.team_name)}</span></span></td></tr>`).join('');
    return `<section class="pollSection ballotSection personalBallot"><div class="pollHead"><div><div class="vhead" style="margin:0">TimurKnowsBall Ballot</div>
      <p class="pollMeta">Personal ballot · published ${esc(b.published_on||'')} · separate from the model</p></div></div>
      <div class="pollScroll"><table class="pollTable officialPollTable"><thead><tr><th>#</th><th>Team</th></tr></thead><tbody>${rows}</tbody></table></div>
      <p class="modNote">${esc(b.note||'')}${b.source_url?` <a href="${esc(b.source_url)}" target="_blank" rel="noopener">View the original post on X</a>.`:''}</p>
    </section>`;
  }
  const body=b.rankings.map(r=>{
    const s=r.resume||{};
    const sor=Number.isFinite(Number(s.sor))?` title="${(Number(s.sor)*100).toFixed(1)}% of top-25-level teams would match this record against this schedule"`:'';
    return `<tr${r.rank<=4?' class="pollRanked"':''}><td class="pollRank">${Number(r.rank)}</td>`
      +`<td class="pollMove">${ballotMove(r)}</td>`
      +`<td class="pollTeam">${esc(r.team_name)}${s.conference_champion?' <i class="pollTier">champ</i>':''}${r.note?`<div class="ballotNote">${esc(r.note)}</div>`:''}</td>`
      +`<td>${esc(s.record||'')}</td>`
      +`<td class="pollNum"${sor}>${s.sor_rank?'#'+Number(s.sor_rank):'—'}</td>`
      +`<td class="pollNum">${Number(s.top25_wins)||0}</td>`
      +`<td>${ballotWin(s.best_win)||'—'}</td>`
      +`<td class="pollNum">${Number(s.bad_losses)||0}</td>`
      +`<td class="pollNum">${s.power_rank?'#'+Number(s.power_rank):'—'}</td></tr>`;
  }).join('');
  const leftOff=(b.left_off||[]).map(t=>`${esc(t.team_name)} (${esc(t.record)}, SOR #${Number(t.sor_rank)})`).join(', ');
  return `<section class="pollSection ballotSection"><div class="pollHead"><div><div class="vhead" style="margin:0">TimurKnowsBall Ballot</div>
      <p class="pollMeta">My ballot · ${esc(b.published_on||'')} · ranked on résumé, not on the power rating</p></div></div>
    <div class="pollScroll"><table class="pollTable"><thead><tr>
      <th>#</th><th title="Change since my last ballot">Move</th><th>Team</th><th>Rec</th><th title="Strength of record rank: how hard this record would be for a top-25-level team to match">SOR</th><th title="Wins over the power rating's top 25">T25 W</th><th>Best win</th><th title="Losses to teams outside the power rating's top 75">Bad L</th><th title="Power rating rank, the eye test">PR</th>
    </tr></thead><tbody>${body}</tbody></table></div>
    ${leftOff?`<p class="modNote">Best résumés left off: ${leftOff}.</p>`:''}
  </section>`;
}
function decorateRankingTeamMarks(host){
  host.querySelectorAll('.gteam[data-team]').forEach(cell=>{
    if(cell.querySelector('.teamMark'))return;
    const anchor=cell.querySelector('.code,.flagIcon,.pos');
    if(anchor)anchor.insertAdjacentHTML('afterend',teamMark(cell.dataset.team));
  });
  const power=String(DATA.comp_key||'').toUpperCase()==='NCAAM'
    ?(typeof MATCHDAY_NCAAM_RANKINGS!=='undefined'?MATCHDAY_NCAAM_RANKINGS:null)
    :(typeof MATCHDAY_CFB_RANKINGS!=='undefined'?MATCHDAY_CFB_RANKINGS:null);
  const ballot=typeof collegeBallot==='function'?collegeBallot():null;
  [[host.querySelectorAll('.pollSection:not(.ballotSection):not(.officialPoll) .pollTeam'),power?.rankings||[],'name'],
   [host.querySelectorAll('.ballotSection .pollTeam'),ballot?.rankings||[],'team_name']].forEach(([cells,rows,key])=>{
    cells.forEach((cell,i)=>{
      if(cell.querySelector('.teamMark')||!rows[i]?.[key])return;
      (cell.querySelector('.pollTeamInner')||cell).insertAdjacentHTML('afterbegin',teamMark(rows[i][key]));
    });
  });
}
const _renderCollegeGroups=renderGroups;
renderGroups=function(){
  _renderCollegeGroups();
  if(!['NCAAF','NCAAM'].includes(String(DATA.comp_key||'').toUpperCase()))return;
  // The poll goes above the conference tables: it is the headline answer this
  // tab was missing, and the conferences are the breakdown beneath it.
  const host=$('#view-groups'),poll=collegeRankingTableHTML();
  if(poll&&!host.querySelector('.pollSection'))host.insertAdjacentHTML('afterbegin',poll);
  const ballotTable=collegeBallotTableHTML();
  if(ballotTable&&!host.querySelector('.ballotSection'))host.insertAdjacentHTML('afterbegin',ballotTable);
  if(!host.querySelector('.rankingsIntro'))host.insertAdjacentHTML('afterbegin',`<section class="rankingsIntro">
    <div class="vhead">Rankings</div>
  </section>`);
  const ballot=host.querySelector('.ballotSection');
  if(ballot&&!host.querySelector('[data-ranking-section="top25"]'))ballot.insertAdjacentHTML('beforebegin',`<div class="seclbl" data-ranking-section="top25">Top 25</div><div class="hint" style="margin-bottom:8px">A résumé ballot, kept separate from the predictive power rating.</div>`);
  const power=host.querySelector('.pollSection:not(.ballotSection):not(.officialPoll)');
  if(power&&!host.querySelector('[data-ranking-section="power"]'))power.insertAdjacentHTML('beforebegin',`<div class="seclbl" data-ranking-section="power">Power Ratings</div><div class="hint" style="margin-bottom:8px">Opponent-adjusted team strength with schedule, offense, and defense context.</div>`);
  const conference=host.querySelector('.tablewrap:not(.officialPoll)');
  if(conference&&!host.querySelector('[data-ranking-section="conferences"]'))conference.insertAdjacentHTML('beforebegin',`<div class="seclbl" data-ranking-section="conferences">Conferences</div><div class="hint" style="margin-bottom:8px">Ordered by conference record (games against conference opponents only), then head-to-head, overall record and model rating.</div>`);
  // The old caption said this rating was "context only" and a preseason
  // tiebreaker. That was wrong and misleading: it is the model's own
  // opponent-adjusted rating and the model does use it. Say what it is.
  document.querySelectorAll('#view-groups .tablewrap:not(.officialPoll) .groupHead span').forEach(el=>el.textContent='Opponent-adjusted rating and strength of schedule');
  document.querySelectorAll('#view-groups .gtable:not(.officialPollTable)').forEach(table=>table.classList.add('collegeConferenceTable'));
  document.querySelectorAll('#view-groups .gtable:not(.officialPollTable) th:nth-child(2)').forEach(th=>{
    th.textContent='Rating · SoS';
    th.title='Opponent-adjusted scoring margin, with the strength of schedule it was earned against.';
  });
  // A rating without its schedule is misleading, so the two never appear apart.
  const table=String(DATA.comp_key||'').toUpperCase()==='NCAAM'
    ?(typeof MATCHDAY_NCAAM_RANKINGS!=='undefined'?MATCHDAY_NCAAM_RANKINGS:null)
    :(typeof MATCHDAY_CFB_RANKINGS!=='undefined'?MATCHDAY_CFB_RANKINGS:null);
  const bySos={};(table?.rankings||[]).forEach(r=>{if(Number.isFinite(Number(r.sos)))bySos[teamKey(r.name)]=Number(r.sos)});
  document.querySelectorAll('#view-groups .gtable:not(.officialPollTable) tbody tr').forEach(tr=>{
    const name=tr.querySelector('.gteam')?.dataset.team||'';
    const cell=tr.children[1];
    const sos=bySos[teamKey(name)];
    if(cell&&Number.isFinite(sos)&&!cell.querySelector('.sosTag')){
      const tag=document.createElement('i');
      tag.className='sosTag';tag.textContent='SoS '+sos.toFixed(2);
      cell.appendChild(tag);
    }
  });
  // Order is fixed: the model's power rating first, the official AP poll
  // second, my ballot last. Sections are inserted by separate renderers, so
  // they are moved into place here rather than relying on insertion order.
  const apTable=host.querySelector('.tablewrap.officialPoll');
  if(apTable){
    const stray=apTable.previousElementSibling;
    if(stray?.classList.contains('vhead')&&stray.textContent.trim()==='Rankings')stray.remove();
    if(!host.querySelector('[data-ranking-section="ap"]'))apTable.insertAdjacentHTML('beforebegin',`<div class="seclbl" data-ranking-section="ap">AP Top 25</div><div class="hint" style="margin-bottom:8px">The official national media poll.</div>`);
  }
  const group=key=>{const lbl=host.querySelector(`[data-ranking-section="${key}"]`);if(!lbl)return[];const out=[lbl];let n=lbl.nextElementSibling;while(n&&!n.dataset.rankingSection&&!n.classList.contains('vhead')){out.push(n);n=n.nextElementSibling;if(out.length>2)break;}return out;};
  const intro=host.querySelector('.rankingsIntro');
  if(intro){let at=intro;['power','ap','top25'].forEach(k=>group(k).forEach(el=>{at.after(el);at=el;}));}
  decorateRankingTeamMarks(host);
};
/* dedup */
// The board loads its sport's full data file, so every match on screen already
// carries the research detail the expanded view reads. The summary payload and
// the per-match hydration it needed went with the merged board.
function openMatchModal(id){const m=BYID[id]||(DATA.matches||[]).find(x=>String(x.id)===String(id));if(!m)return;const modal=ensureMatchModal();const hmeta=t=>esc(teamStandingsMeta(t,m._comp,{form:true}).join(' · '));modal.innerHTML=`<section class="matchSheet" role="dialog" aria-modal="true"><div class="modalHero"><button class="modalClose" onclick="closeMatchModal()" aria-label="Close">×</button><div class="modalStage">${esc(m.stage||'Fixture')} · ${esc(m.status==='LIVE'?'AWAITING FINAL':m.status||'')}</div><div class="modalFixture"><div class="modalTeam"><div class="modalCode">${teamFlagHTML(m.home)}${esc(m.home?.code||'HOME')}</div><div class="modalName">${esc(m.home?.name||'Home')}</div><div class="modalMeta">${hmeta(m.home)}</div></div><div class="modalScore"><div class="bigScore">${esc(scorePlainText(m))}</div><div class="modalStatus">${m.status==='LIVE'?'Score shown after final':kickIn(m.kickoff)}</div></div><div class="modalTeam away"><div class="modalCode">${esc(m.away?.code||'AWAY')}${teamFlagHTML(m.away,true)}</div><div class="modalName">${esc(m.away?.name||'Away')}</div><div class="modalMeta">${hmeta(m.away)}</div></div></div></div><div class="modalBody">${details(m)}</div></section>`;modal.classList.add('show');document.body.classList.add('modalOpen')}




/* ===== MODEL PICK REDESIGN — v3 =====
   This override intentionally avoids the old .pick/.fchip markup inside the modal.
   It prevents vertical letters, cramped chips, and overlap. */
/* dedup */
/* dedup */



/* ===== MATCH MODAL + FORECAST BOARD REDESIGN — v4 ===== */
function _v4PickSideLabel(m,side){
  if(side==='h')return m.home?.name||'Home';
  if(side==='a')return m.away?.name||'Away';
  if(side==='d')return 'Draw';
  return 'No pick';
}
function _v4ModelProbs(m){
  return officialPredictionProbabilities(m);
}
function sportClassMeta(pr,m){
  if(pr?.class_meta)return pr.class_meta;
  // Locked predictions created before class provenance was added keep their
  // immutable snapshot. Derive only the honest display label here; pro-sport
  // legacy "class" values were market proxies, so never present them as a
  // roster/personnel edge.
  const comp=String(m?._comp||DATA.comp_key||'').toUpperCase();
  const labels={NCAAF:'Roster talent edge',NCAAM:'Recruiting edge'};
  return {label:labels[comp]||'Squad edge',coverage:'partial'};
}
function _v4FactorRows(pr,m){
  const classMeta=sportClassMeta(pr,m),legacyMarketClass=!pr?.class_meta&&classMeta.coverage==='unavailable';
  const classLabel=legacyMarketClass?'legacy championship market power':classMeta.label.toLowerCase();
  const labels={class:classLabel,market_power:'championship market power',pts:'points',gd:scoreDiffLabel(m),record:'season record',margin:'scoring margin',rank:'poll rank',srs:'opponent-adjusted rating',form:'form',adv:'home field',rest:'rest',elo:'elo rating',h2h:'head-to-head',injuries:'injuries'};
  const rows=[];
  const classVal=pr?.why?.class!=null?(Number(pr.why.class)||0):null;
  const classListed=classVal!=null&&Math.abs(classVal)>=0.3;
  if(pr&&pr.why){
    Object.entries(pr.why).filter(([k,v])=>labels[k]&&Math.abs(Number(v)||0)>=0.3)
      .sort((a,b)=>Math.abs(Number(b[1])||0)-Math.abs(Number(a[1])||0))
      .forEach(([k,v])=>{v=Number(v)||0;rows.push(`<div class="factorRow ${v>0?'pos':v<0?'neg':'neu'}"><span class="fName">${esc(labels[k])}</span><span class="fVal">${v>0?'+':''}${v.toFixed(1)}</span></div>`)});
  }
  // Two very different things used to look identical here: a roster/talent
  // signal that grades the two teams level, and one the provider never
  // covered. Both fell under the 0.3 threshold above and were dropped
  // silently, so the talent edge simply vanished for 41 of 160 live NCAAF
  // fixtures with nothing on screen saying why. State it either way.
  if(!classListed){
    if(classMeta.edge_available===false){
      rows.push(`<div class="factorRow neu" title="${esc(classMeta.note||`No validated player-quality grades are available, so ${classLabel} is not scored.`)}"><span class="fName">${esc(classLabel)}</span><span class="fVal">not scored</span></div>`);
    }else{
      const covered=classMeta.coverage!=='unavailable'&&classVal!=null;
      rows.push(`<div class="factorRow neu" title="${esc(covered?`${classLabel} is in the model for this matchup and grades the two teams level.`:`No verified ${classLabel} data for this matchup, so the model assigned no edge rather than a fabricated one.`)}"><span class="fName">${esc(classLabel)}</span><span class="fVal">${covered?'level':'no data'}</span></div>`);
    }
  }
  if(classMeta.coverage_label&&classMeta.coverage!=='unavailable')rows.push(`<div class="factorRow neu" title="Expected depth-chart coverage only; this does not assert confirmed gameday actives or player quality."><span class="fName">${esc(classMeta.coverage_label)}</span><span class="fVal">${classMeta.coverage==='complete'?'both teams':'partial'}</span></div>`);
  if(pr&&Number(pr.damp_pct))rows.push(`<div class="factorRow neu"><span class="fName">variance control</span><span class="fVal">−${esc(pr.damp_pct)}%</span></div>`);
  if(pr&&Number(pr.mkt_pull))rows.push(`<div class="factorRow neu"><span class="fName">consensus pull</span><span class="fVal">${Number(pr.mkt_pull)>0?'+':''}${esc(pr.mkt_pull)}</span></div>`);
  // Surfaces the locked pick's own data-availability snapshot as an explicit
  // uncertainty signal, rather than letting a missing input pass silently.
  if(pr&&pr.data_availability){
    const availLabels={market:'market odds',box_score:'box score',lineups:'lineups',injuries:'injury reports',weather:'weather',personnel:'sport-specific personnel',venue_context:'venue context'};
    Object.entries(pr.data_availability).filter(([k,v])=>v==='unavailable'&&availLabels[k])
      .forEach(([k])=>rows.push(`<div class="factorRow neu" title="No ${esc(availLabels[k])} were available when this pick locked, so the model could not use them."><span class="fName">${esc(availLabels[k])}</span><span class="fVal">no data</span></div>`));
  }
  return rows.length?rows.join(''):'<div class="factorRow neu"><span class="fName">No factor detail</span><span class="fVal">—</span></div>';
}
function pregameContextPanel(m){
  const ctx=m.pregame_context||m.prediction?.lock_readiness;
  if(!ctx)return `<div class="readCard pregameContextCard"><div class="seclbl">Pregame context</div><div class="emptyStats"><b>No readiness receipt for this fixture</b><span>This forecast was published before Matchday started recording which pregame inputs it had. The pick still stands as locked; only the receipt is missing.</span></div></div>`;
  const labels={market:'market',injuries:'injuries',lineups:'lineups',weather:'weather',venue:'venue',starting_pitchers:'starting pitchers',bullpen:'bullpen availability',rotation:'rotation',key_players:'QB / key players',starting_goalies:'starting goalies'};
  const state=m.prediction?.publication_state||ctx.phase||'preliminary';
  const stateLabel=state==='locked'?'Locked forecast':state==='lock_candidate'?'Inside lock window':'Preliminary forecast';
  const inWindow=state==='locked'||state==='lock_candidate';
  // Outside the lock window an unconfirmed input is the schedule working, not
  // a fault -- lineups for a fixture two days out have not been named yet. The
  // panel used to render one grey "missing" row per input plus a red "Needed
  // before lock" alert on every such fixture, which is every soccer and
  // college fixture on the board, so a normal pregame card read as a broken
  // one. The full receipt is kept for inside the window, where a missing input
  // genuinely blocks the lock.
  const inputPairs=Object.entries(ctx.inputs||{});
  const confirmedPairs=inputPairs.filter(([,value])=>String(value)==='confirmed');
  const pendingPairs=inputPairs.filter(([,value])=>String(value)!=='confirmed');
  const rows=(inWindow?inputPairs:confirmedPairs).map(([key,value])=>`<div class="factorRow ${value==='confirmed'?'pos':'neu'}"><span class="fName">${esc(labels[key]||key)}</span><span class="fVal">${esc(value)}</span></div>`).join('');
  const lead=Number(ctx.lead_time_hours);
  const pendingLine=(!inWindow&&pendingPairs.length)?`<div class="contextPending"><b>Still to arrive</b><span>${pendingPairs.map(([key])=>esc(labels[key]||key)).join(' · ')}</span><small>${lead>0?`Kickoff is ${lead>=48?Math.round(lead/24)+' days':Math.round(lead)+'h'} away — these confirm closer to it.`:'These confirm closer to kickoff.'}</small></div>`:'';
  // Only a licensed feed writes starting_pitchers; SportsGameOdds writes its
  // market-listed inference under starter_candidates so the two can never be
  // confused. Reading only the first meant this card showed nothing at all on
  // every fixture, and the "not confirmed" wording below was unreachable.
  const injuries=m.injuries||{};
  const injuryDetails=m.personnel?.injury_details||{};
  const injuryCount=(injuries.home||[]).length+(injuries.away||[]).length+
    (injuryDetails.home||[]).length+(injuryDetails.away||[]).length;
  const depth=m.personnel?.depth_chart||{};
  const depthPositions=new Set(['QB','RB','LWR','RWR','SLWR','TE','LDE','RDE','MLB','LCB','RCB','FS','SS']);
  const depthLine=side=>{
    const chart=depth[side]||{},players=(chart.players||[]).filter(p=>depthPositions.has(String(p.position||'').toUpperCase())).slice(0,8);
    if(!players.length)return'';
    const team=side==='home'?m.home:m.away;
    return `${esc(team?.code||team?.name||side)} expected: ${players.map(p=>`${esc(p.position||'')} ${esc(p.name||'')}${p.roster_status&&p.roster_status!=='ACT'?` <b>(${esc(p.roster_status)})</b>`:''}`).join(' · ')}`;
  };
  const detailNotes=[];
  if(injuryCount)detailNotes.push(`<div class="contextNote"><b>Availability report</b><span>${injuryCount} unavailable or questionable player${injuryCount===1?'':'s'}</span></div>`);
  ['home','away'].map(depthLine).filter(Boolean).forEach(line=>detailNotes.push(`<div class="contextNote contextNoteWide"><b>Expected depth</b><span>${line}</span></div>`));
  const depthObserved=depth.home?.observed_at||depth.away?.observed_at;
  if(depthObserved)detailNotes.push(`<div class="contextNote contextNoteWide"><b>Depth-chart timestamp</b><span>${esc(new Date(depthObserved).toLocaleString())}</span><small>Expected hierarchy, not confirmed gameday actives</small></div>`);
  const missing=(ctx.missing_critical||[]).map(k=>labels[k]||k);
  const missingBlock=(inWindow&&missing.length)?`<div class="contextAlert"><span aria-hidden="true">!</span><div><b>Needed before lock</b><p>${missing.map(x=>esc(x)).join(' · ')}</p></div></div>`:'';
  return `<div class="readCard pregameContextCard"><div class="seclbl">Pregame context</div><div class="pick insightPick ${state==='locked'?'':'gate'}"><span class="pl">State</span><span class="pn">${esc(stateLabel)}</span><span class="pc">${esc(ctx.coverage_pct??0)}%</span><span class="pnote">${inWindow?`input coverage · locks on the first successful refresh inside the ${esc(ctx.lock_window_hours??2)}h pregame window`:`input coverage so far · the pick locks inside the ${esc(ctx.lock_window_hours??2)}h window before kickoff`}</span></div>${rows?`<div class="factorRows contextFactorRows">${rows}</div>`:''}${pendingLine}<div class="contextDetails">${detailNotes.length?`<div class="contextNoteGrid">${detailNotes.join('')}</div>`:''}${missingBlock}</div><div class="contextResearch"><span>Research-only</span><p>New personnel and venue inputs are tracked, but do not change the model yet.</p></div></div>`;
}

/* Bet Better's own read on one fixture.
   The expanded view previously showed provider stats and a market price and
   nothing from the model that the rest of this site is built on. These are the
   same rated rows the Top 25 and the scatter draw, looked up per team, so the
   number in a matchup and the number in the ranking cannot disagree.

   Strength of schedule sits next to every rating here for the same reason it
   does everywhere else: a rating without the schedule behind it flatters
   whoever played nobody. */
function betbetterTeamRow(name){
  const key=String(DATA.comp_key||'').toUpperCase()==='NCAAM'
    ?(typeof MATCHDAY_NCAAM_RANKINGS!=='undefined'?MATCHDAY_NCAAM_RANKINGS:null)
    :(typeof MATCHDAY_CFB_RANKINGS!=='undefined'?MATCHDAY_CFB_RANKINGS:null);
  const want=teamKey(name);
  return (key?.rankings||[]).find(r=>{
    const rk=teamKey(r.name);
    return rk===want||rk.startsWith(want+' ')||want.startsWith(rk+' ');
  })||null;
}
function betbetterMatchupPanel(m){
  const h=betbetterTeamRow(m?.home?.name||m?.home),a=betbetterTeamRow(m?.away?.name||m?.away);
  if(!h&&!a)return '';
  const num=(v,d=2)=>Number.isFinite(Number(v))?Number(v).toFixed(d):'—';
  const rows=[
    ['Rank',h?('#'+h.rank):'—',a?('#'+a.rank):'—'],
    ['Rating',num(h?.rating),num(a?.rating)],
    ['Offence',num(h?.adj_o,1),num(a?.adj_o,1)],
    ['Defence',num(h?.adj_d,1),num(a?.adj_d,1)],
    ['Strength of schedule',num(h?.sos),num(a?.sos)],
    ['Conference',h?.conference||'—',a?.conference||'—'],
  ];
  const gap=(Number.isFinite(Number(h?.rating))&&Number.isFinite(Number(a?.rating)))
    ?Number(h.rating)-Number(a.rating):null;
  const lead=gap==null?'':`<div class="bbGap">${esc(gap>=0?(m?.home?.name||'Home'):(m?.away?.name||'Away'))} by <b>${Math.abs(gap).toFixed(2)}</b> on rating</div>`;
  return `<div class="readCard bbMatchupCard"><div class="readHead"><span>Model</span><b>Opponent-adjusted matchup</b></div>
${lead}
<table class="bbTable"><thead><tr><th></th><th>${esc(m?.home?.name||'Home')}</th><th>${esc(m?.away?.name||'Away')}</th></tr></thead>
<tbody>${rows.map(([k,x,y])=>`<tr><td class="bbKey">${esc(k)}</td><td>${esc(x)}</td><td>${esc(y)}</td></tr>`).join('')}</tbody></table>
<p class="bbNote">Opponent-adjusted scoring margin and the schedule it was earned against, from the same table the ranking is drawn from. A rating difference is not a prediction.</p>
${typeof matchdayLivePickHTML==='function'?matchdayLivePickHTML(m):''}</div>`;
}
/* The model read, from the engine the rest of this board already quotes.

   The expanded view rendered `m.prediction` under the heading "Model read".
   That is Matchday's own forecast, not the engine behind the card, the Top 25,
   the rating scatter and the top-pick module -- so a card reading "Florida
   State 54.5%" opened onto a panel reading "TCU 55%": two different models
   under one name, and no way for a reader to tell which one the site stands
   behind. The heading now resolves to the Bet Better read, and `m.prediction`
   is not shown beside it as a second opinion, for the same reason the card
   stopped stacking two pick rows.

   Matchday publishes college football and college basketball only, and the
   engine covers both, so there is no sport left for a second forecast to serve.
   A fixture it has not modeled gets an empty state rather than another model's
   number under the engine's heading. */
function betbetterReadFor(m){
  // Only UPCOMING, matching what the handoff itself will attach: a live
  // forecast on a played game reads as a call that was made in advance.
  if(!m||String(m.status||'').toUpperCase()!=='UPCOMING')return null;
  // Two sources on purpose, as in modTopPick(): a scheduled build attaches the
  // pick to the fixture, a push build does not run the fetch that does, and the
  // handoff is committed either way.
  const list=(typeof MATCHDAY_BETBETTER_PICKS!=='undefined')?MATCHDAY_BETBETTER_PICKS:null;
  const day=String(m.kickoff||'').slice(0,10);
  if(!list||!list.length||!day)return m.betbetter_pick||null;
  const sport=String(m._comp||DATA.comp_key||'').toLowerCase();
  // A day either side, for the same reason the results settling allows it: a
  // late kickoff and its listed date land on opposite sides of midnight UTC.
  const days=[day,_bbShiftDay(day,-1),_bbShiftDay(day,1)];
  const candidates=list.filter(p=>(!p.sport||!sport||String(p.sport).toLowerCase()===sport)
    &&days.includes(String(p.kickoff||'').slice(0,10))
    &&((bbNameMatches(p.home,m.home?.name||m.home)&&bbNameMatches(p.away,m.away?.name||m.away))
      ||(bbNameMatches(p.home,m.away?.name||m.away)&&bbNameMatches(p.away,m.home?.name||m.home))));
  if(m.betbetter_pick)candidates.push(m.betbetter_pick);
  return candidates.sort((a,b)=>(Date.parse(b.generated_at||'')||0)-(Date.parse(a.generated_at||'')||0))[0]||null;
}
function betbetterNoReadPanel(){
  return `<section class="analystPanel"><div class="analystTop"><div class="analystTitle">Model read</div>`
    +`<div class="analystBadge">not modeled</div></div>`
    +`<div class="emptyForecast">No model prediction is available for this fixture yet; `
    +`the opponent-adjusted ratings for both teams are in the matchup table below.</div></section>`;
}
function _bbNum(v){const n=Number(v);return Number.isFinite(n)?n:null;}
function _bbPct(v,d=1){const n=_bbNum(v);return n==null?'\u2014':Math.min(99.9,n).toFixed(d)+'%';}
function _bbStamp(v){const t=Date.parse(v||'');return Number.isFinite(t)?new Date(t).toLocaleString():'';}
function betbetterModelRead(m,p){
  const model=_bbNum(p.model_pct);
  const engine=p.model_name||'Matchday model';
  const when=_bbStamp(p.generated_at);
  // Both sides, not the pick alone. A 54.5% pick is a near coin-flip, and the
  // other side's number is the only thing on the panel that says so.
  const rows=(p.sides||[]).map(s=>`<div class="readSide"><span>${esc(s.selection||'')}</span>`
    +`<strong>${_bbPct(s.model_pct)}</strong></div>`).join('');
  const sideBox=rows
    ?`<div class="readSides" aria-label="Both teams' win chances">${rows}</div>`
    :'';
  return `<section class="analystPanel"><div class="analystTop"><div class="analystTitle">Live model read</div>`
    +`<details class="readHelp"><summary aria-label="About this forecast">?</summary><p>${esc(engine)}${when?` · ${esc(when)}`:''}${p.model_version?` · ${esc(p.model_version)}`:''}. ${esc(p.integrity_note||'This read may change before kickoff and is not a locked, graded pick.')}</p></details></div>`
    +`<div class="analystHero"><div class="analystMain"><div class="analystLabel">Favored team</div>`
    +`<div class="analystPick">${esc(p.pick_name||'No pick')}</div>`
    +`<p class="analystNote">Live forecast · not locked yet</p></div>`
    +`<div class="analystConfidence"><b>${_bbPct(model)}</b><span>chance to win</span></div></div>`
    +`<details class="readBreakdown"><summary>See both teams' chances</summary>${sideBox}</details></section>`;
}
function matchupEvidence(label,note,html,open=false){
  if(!html)return '';
  return `<details class="matchEvidence"${open?' open':''}><summary><span><b>${esc(label)}</b><small>${esc(note)}</small></span><i aria-hidden="true">+</i></summary><div class="matchEvidenceBody">${html}</div></details>`;
}
function details(m){
  if(isForecastPaused(m))return `<div class="detailGrid v4Detail">${forecastPauseHTML(m)}<div class="detailTop">${betbetterMatchupPanel(m)}<div class="readCard forecastMarketCard">${marketPanel(m)}</div></div><div class="detailLow">${rosterPanel(m)}</div></div>`;
  const bb=betbetterReadFor(m);
  const read=bb?betbetterModelRead(m,bb):betbetterNoReadPanel();
  const comparison=betbetterMatchupPanel(m)||matchProfilePanel(m);
  return `<div class="detailGrid v4Detail modernExpandedView"><div class="expandedSectionHead"><div><span>Matchday analysis</span><b>Pick &amp; matchup</b></div></div><div class="expandedDecision"><div class="readCard modelReadCard">${read}</div></div><div class="matchEvidenceList">${matchupEvidence('Team comparison','rating, offence, defence and schedule',comparison,true)}${matchupEvidence('Market','price and model gap',`<div class="readCard forecastMarketCard">${marketPanel(m)}</div>`)}${matchupEvidence('More detail','season profile and roster',`<div class="detailLow">${matchProfilePanel(m)}${rosterPanel(m)}<!-- matchday-advanced-profile --></div>`)}</div></div>`;
}
/* dedup */
function _v4TitleRows(t){
  if(!t.length)return '<div class="emptyForecast">No title-race snapshot yet.</div>';
  const max=Number(t[0].pct)||1;
  return t.slice(0,12).map((x,i)=>`<div class="raceRow"><span class="raceRank">${i+1}</span><div><div class="raceTeam">${uiFlag(x.code)?`<span class="flagIcon">${uiFlag(x.code)}</span>`:''}${esc(x.team)}</div><div class="raceMeta">title probability snapshot</div></div><span class="raceBar"><i style="width:${Math.max(4,Math.round((Number(x.pct)||0)/max*100))}%"></i></span><span class="racePct">${esc(x.pct??'—')}%</span></div>`).join('');
}
function _v4ScorerRows(sc){
  if(!sc.length)return '<div class="emptyForecast">No scorer data yet.</div>';
  return sc.slice(0,10).map((p,i)=>`<div class="scorerRow"><span class="scorerRank">${i+1}</span><div><div class="scorerName">${esc(p.name||'')}</div><div class="scorerMeta">${esc(p.code||p.team||'')}</div></div><span class="scorerGoals">${esc(p.goals??0)} G${p.assists?` · ${esc(p.assists)} A`:''}</span></div>`).join('');
}
function _v13LeaderPanel(sc){
  const board=DATA.leaders||{},cats=board.categories||[];
  if(cats.length){
    const meta=[board.season,board.source].filter(Boolean).join(' · ');
    const cards=cats.map(c=>`<div class="leaderCategory"><div class="leaderCategoryHead"><span>${esc(c.label||c.key||'Leader')}</span><b>${esc(c.abbr||'')}</b></div><div class="leaderRows">${(c.leaders||[]).slice(0,3).map((p,i)=>`<div class="leaderRow"><span>${i+1}</span><strong>${esc(p.name||'')}</strong><b>${esc(p.value??'—')}</b></div>`).join('')}</div></div>`).join('');
    return `<section class="forecastPanel leaderPanel"><div class="forecastPanelHead"><h3>Season leaders</h3><span>${esc(meta||'verified stats')}</span></div><div class="leaderCategoryGrid">${cards}</div></section>`;
  }
  if(sc.length)return `<section class="forecastPanel"><div class="forecastPanelHead"><h3>Scoring leaders</h3><span>goals & assists</span></div><div class="scorerList">${_v4ScorerRows(sc)}</div></section>`;
  return '';
}
function _v4MatchSnapshots(){
  const M=(DATA.matches||[]).filter(m=>m.status!=='FINISHED'&&!isStaleUpcoming(m)&&(m.markets?.['1x2']||m.prediction)).sort((a,b)=>(a.kickoff||'').localeCompare(b.kickoff||'')).slice(0,8);
  if(!M.length)return '<div class="emptyForecast">No upcoming match snapshots yet.</div>';
  return M.map(m=>{const x=(m.markets||{})['1x2']||{},probs=_v4ModelProbs(m),twoWay=_isTwoWay(m);
    const hp=Number(probs.h??x.home_pct??0),dp=Number(probs.d??x.draw_pct??0),ap=Number(probs.a??x.away_pct??0);
    const line=(name,side,pct)=>`<div class="probLine"><span class="sideName">${esc(name)}</span><span class="probTrack"><i class="probFill ${side}" style="width:${Math.max(3,Math.min(100,pct))}%"></i></span><span class="pct">${modelPctLabel(pct)}</span></div>`;
    return `<div class="matchSnapRow" onclick="openMatchModal('${esc(String(m.id||''))}')"><div><div class="matchSnapTeams">${esc(m.home?.code||m.home?.name||'H')} v ${esc(m.away?.code||m.away?.name||'A')}</div><div class="matchSnapMeta">${isForecastPaused(m)?'Market odds · ':''}${esc(m.stage||'')} \u2013 ${kickIn(m.kickoff)}</div></div><div class="probLines">${line(m.home?.code||'H','h',hp)}${twoWay?'':line('Draw','d',dp)}${line(m.away?.code||'A','a',ap)}</div></div>`;
  }).join('');
}
function _v4AdvancementTable(adv){
  if(!adv.length)return '';
  const stages=Object.keys(adv[0].stages||{});
  const advCols=`grid-template-columns:minmax(150px,1.6fr) repeat(${stages.length},minmax(56px,1fr))`;
  return `<section class="forecastPanel"><div class="forecastPanelHead"><h3>Advancement path</h3><span>model projection</span></div><div class="advtable v4"><div class="advrow advhead" style="${advCols}"><span>Team</span>${stages.map(sg=>`<span>${esc(sg==='Champion'?'Win':sg.replace('-finals','F').replace('Round of ','R'))}</span>`).join('')}</div>${adv.slice(0,18).map(r=>`<div class="advrow" style="${advCols}"><span class="advteam">${uiFlag(r.code)?`<span class="flagIcon">${uiFlag(r.code)}</span> `:''}${esc(r.team)}</span>${stages.map(sg=>{const v=r.stages[sg];return `<span class="advpct ${v>=50?'hi':v<10?'lo':''}">${v!=null?v+'%':'&mdash;'}</span>`}).join('')}</div>`).join('')}</div><div class="forecastDisclaimer">Projection only. Later rounds depend on the field that actually survives.</div></section>`;
}
function renderTitle(){
  const t=DATA.title_odds||[],adv=DATA.advancement||[],sc=DATA.scorers||[],upsets=_v4UpsetRows();
  const upcoming=(DATA.matches||[]).filter(m=>m.status!=='FINISHED'&&!isStaleUpcoming(m)).length;
  let html=`<div class="forecastShell"><div class="forecastHero"><div><h2>Forecast board</h2><p>Tournament probabilities, upset risk, advancement paths, and scorer races, in one place.</p></div><div class="forecastKpis"><div class="forecastKpi"><span>Upcoming</span><b>${upcoming}</b></div><div class="forecastKpi"><span>Upset watch</span><b>${upsets.length}</b></div><div class="forecastKpi"><span>Title teams</span><b>${t.length||'—'}</b></div></div></div>`;
  const leaderPanel=_v13LeaderPanel(sc);
  html+=`<div class="forecastGrid ${leaderPanel?'':'single'}"><section class="forecastPanel"><div class="forecastPanelHead"><h3>Upset radar</h3><span>${upsets.length} matches</span></div><div class="upsetList">${upsets.length?upsets.map(x=>`<div class="upsetRow" onclick="openMatchModal('${esc(String(x.m.id||''))}')"><div><div class="upsetMatch">${esc(x.m.home?.code||x.m.home?.name||'H')} v ${esc(x.m.away?.code||x.m.away?.name||'A')}</div><div class="upsetWhy">${esc(x.reason)}</div></div><div class="upsetWhy">${esc(x.m.stage||'')} · ${kickIn(x.m.kickoff)}</div><span class="riskPill ${x.cls}">${x.triggered?'active upset pick':x.risk>=70?'high variance':x.risk>=50?'medium variance':'low variance'}</span></div>`).join(''):'<div class="emptyForecast">No upcoming matches to analyze.</div>'}</div></section>${leaderPanel}</div>`;
  html+=`<div class="forecastGrid"><section class="forecastPanel"><div class="forecastPanelHead"><h3>Title race</h3><span>probability snapshot</span></div><div class="raceList">${_v4TitleRows(t)}</div></section><section class="forecastPanel"><div class="forecastPanelHead"><h3>Match snapshots</h3><span>next fixtures</span></div><div class="matchSnapList">${_v4MatchSnapshots()}</div></section></div>`;
  html+=_v4AdvancementTable(adv);
  html+=`<div class="forecastNote">Read these as probabilities, not calls: a 38% pick is supposed to lose most of the time.</div></div>`;
  const host=$('#view-title');host.innerHTML=html;
}



/* ===== IN-FOCUS PANEL RESTORE — v5 =====
   Keep the expanded match window using the new v4 analyst card,
   but restore the right-side In Focus panel to the original compact read.
   This prevents the large expanded-window model layout from breaking the sidebar. */
/* dedup */
