function btmGrade(){ // fold finished results into the record
  const db=btmLoad();db.picks=db.picks||{};let changed=false;
  (DATA.matches||[]).forEach(m=>{const p=db.picks[m.id];
    if(p&&!p.result&&m.status==='FINISHED'&&m.score){
      const side=x=>x?.home>x?.away?'h':x?.home<x?.away?'a':'d';
      // Community and model picks follow the team that ultimately advanced;
      // the market benchmark continues to use its regulation settlement.
      const res=['h','a','d'].includes(m.score.winner)?m.score.winner:side(m.score);
      const marketRes=side((m.score.reg&&m.score.reg.home!=null)?m.score.reg:m.score);
      p.result=res;p.you_hit=(p.pick===res);
      p.model_hit=(p.modelPick===res);p.market_hit=(p.marketPick===marketRes);changed=true;}});
  if(changed){btmSave(db);pushScore();}return db;
}
function btmStats(db){
  const g=Object.values(db.picks||{}).filter(p=>p.result);
  const paired=g.filter(p=>p.modelPick);
  const you=g.filter(p=>p.you_hit).length, model=paired.filter(p=>p.model_hit).length;
  const beat=paired.filter(p=>p.you_hit&&!p.model_hit).length; // you right, model wrong
  // current streak (most recent graded backwards)
  const chron=g.slice().sort((a,b)=>b.ts-a.ts);let streak=0;
  for(const p of chron){if(p.you_hit)streak++;else break;}
  return {n:g.length,you,model,modelN:paired.length,beat,streak,
    pending:Object.values(db.picks||{}).filter(p=>!p.result).length};
}
function btmBadges(s,db){const out=[];
  const g=db?Object.values(db.picks||{}).filter(p=>p.result):[];
  if(s.n>=1)out.push(['First call','Locked your first pick']);
  if(s.n>=10)out.push(['Regular','10 graded picks']);
  if(s.n>=50)out.push(['Veteran','50 graded picks']);
  if(s.streak>=3)out.push(['On fire',`${s.streak} in a row`]);
  if(s.streak>=6)out.push(['Unstoppable','6+ in a row']);
  if(s.beat>=1)out.push(['Model beater','Out-picked the model']);
  if(s.beat>=5)out.push(['Sharper than the machine','Beat the model 5+ times']);
  if(s.beat>=15)out.push(['Oracle','Beat the model 15+ times']);
  // called an upset the model missed: you picked the market underdog, it won, model didn't have it
  if(g.some(p=>p.you_hit&&p.marketPick&&p.pick!==p.marketPick&&!p.model_hit))
    out.push(['Upset caller','Called an underdog the model missed']);
  // multi-sport: hits across 3+ competitions
  const wonComps=new Set(g.filter(p=>p.you_hit).map(p=>p.comp).filter(Boolean));
  if(wonComps.size>=3)out.push(['All-rounder',`Won picks in ${wonComps.size} competitions`]);
  // perfect week: 5+ graded in a 7-day window, all hit
  const byday=g.slice().sort((a,b)=>a.ts-b.ts);
  for(let i=0;i<byday.length;i++){const wk=byday.filter(p=>p.ts>=byday[i].ts&&p.ts<byday[i].ts+6048e5);
    if(wk.length>=5&&wk.every(p=>p.you_hit)){out.push(['Perfect week','5+ correct in one week']);break;}}
  return out;}
function communityModelPctLabel(v){const n=Number(v);return v==null||!Number.isFinite(n)?'—':Math.max(0,Math.min(99.9,n)).toFixed(1)+'%'}
function communityPickProbs(m){
  const read=typeof betbetterReadFor==='function'?betbetterReadFor(m):m.betbetter_pick;
  const sides=read?.sides||[];
  // Match by team identity first: the fixture can be shown in the reverse
  // orientation from the model handoff, making is_home misleading here.
  const home=sides.find(s=>bbNameMatches(s.selection,m.home?.name))||sides.find(s=>s.is_home===true);
  const away=sides.find(s=>bbNameMatches(s.selection,m.away?.name))||sides.find(s=>s.is_home===false);
  if(home?.model_pct!=null&&away?.model_pct!=null)return {h:+home.model_pct,d:0,a:+away.model_pct,source:'betbetter',read};
  return {h:null,d:null,a:null,source:'none',read:null};
}
function btmAnalytics(db){
  const g=Object.values(db.picks||{}).filter(p=>p.result);
  if(g.length<3)return null;
  const rate=a=>a.length?Math.round(a.filter(p=>p.you_hit).length/a.length*100):null;
  // favorites vs underdogs (was your pick the market underdog?)
  const dog=g.filter(p=>p.marketPick&&p.pick!==p.marketPick);
  const fav=g.filter(p=>p.marketPick&&p.pick===p.marketPick);
  // when you disagreed with the model
  const split=g.filter(p=>p.modelPick&&p.pick!==p.modelPick);
  const withm=g.filter(p=>p.modelPick&&p.pick===p.modelPick);
  // by competition
  const byComp={};g.forEach(p=>{const c=p.comp||'—';(byComp[c]=byComp[c]||[]).push(p);});
  const comps=Object.entries(byComp).filter(([c,a])=>a.length>=3)
    .map(([c,a])=>({comp:c,n:a.length,pct:rate(a)})).sort((x,y)=>y.pct-x.pct);
  return {favPct:rate(fav),favN:fav.length,dogPct:rate(dog),dogN:dog.length,
    splitPct:rate(split),splitN:split.length,withPct:rate(withm),withN:withm.length,comps};
}
function btmSeason(db){
  // 4-week rolling seasons since first pick; returns {label, record} for current season + archive
  const g=Object.values(db.picks||{}).filter(p=>p.result).sort((a,b)=>a.ts-b.ts);
  if(!g.length)return null;
  const WEEK=6048e5, LEN=4*WEEK, start=g[0].ts;
  const seasons={};
  g.forEach(p=>{const idx=Math.floor((p.ts-start)/LEN);(seasons[idx]=seasons[idx]||[]).push(p);});
  const now=Math.floor((Date.now()-start)/LEN);
  const rows=Object.entries(seasons).map(([i,a])=>({n:+i,you:a.filter(p=>p.you_hit).length,
    model:a.filter(p=>p.model_hit).length,total:a.length,current:+i===now}));
  return rows.sort((a,b)=>b.n-a.n);
}
function renderWeeklyAwards(){
  const wa=DATA.weekly_awards;
  if(!wa)return '';
  const cards=[];
  if(wa.biggest_upset){const u=wa.biggest_upset;
    cards.push({label:'Biggest upset',title:`${esc(u.winner)} won`,sub:`${esc(u.home)} ${esc(u.score_line)} ${esc(u.away)}${u.market_pct!=null?` · market gave them ${u.market_pct}%`:''}`});}
  if(wa.best_call){const b=wa.best_call;
    cards.push({label:"Model's best call",title:esc(b.pick),sub:`${esc(b.home)} v ${esc(b.away)} · ${b.confidence}% confidence${b.edge?` · +${b.edge} vs market`:''}`});}
  if(wa.biggest_miss){const b=wa.biggest_miss;
    cards.push({label:"Model's biggest miss",title:`Picked ${esc(b.pick)}`,sub:`${esc(b.home)} v ${esc(b.away)} · ${b.confidence}% confidence · ${esc(b.actual)} won instead`});}
  if(wa.closest_match){const c=wa.closest_match;
    cards.push({label:'Nail-biter of the week',title:`${esc(c.home)} ${esc(c.score_line)} ${esc(c.away)}`,sub:c.margin===0?'as close as it gets':`won by ${c.margin}`});}
  if(!cards.length)return '';
  return `<div class="seclbl" style="margin-top:4px">Weekly awards</div><div class="status-grid weeklyAwards">${cards.map(c=>`<div class="statuscard info"><span class="slbl">${c.label}</span><div class="sval" style="font-size:var(--fs-lg)">${c.title}</div><div class="hint">${c.sub}</div></div>`).join('')}</div>`;
}
// Signed out, a handle belongs to one browser and dies with its storage.
// Signed in, it belongs to an account, so the record follows the person to a
// new browser or a second device.
function renderAccountRow(){
  const providerLabel={google:'Google',github:'GitHub'};
  if(ACCOUNT.signedIn){
    const moved=SIGNIN_CLAIMED?` <b>${SIGNIN_CLAIMED} earlier pick${SIGNIN_CLAIMED===1?'':'s'} moved across.</b>`:'';
    const err=ACCOUNT_ERROR?`<span class="acctErr">${esc(ACCOUNT_ERROR)}</span>`:'';
    // Sign out and delete sit side by side, so delete is styled as the
    // destructive one rather than looking like a second way to leave.
    return `<div class="acctRow signedIn"><span class="acctState">&#10003; Signed in — this handle and record are saved to your account.${moved}</span>
      <span class="acctBtns"><button class="btmbtn" onclick="signOut()">Sign out</button>
      <button class="btmbtn danger" onclick="deleteAccount()">Delete account</button></span>${err}</div>`;
  }
  const buttons=(AUTH_PROVIDERS.length?AUTH_PROVIDERS:[]).map(p=>
    `<button class="btmbtn" onclick="signIn('${esc(p)}')">Continue with ${esc(providerLabel[p]||p)}</button>`).join('');
  const note=SIGNIN_ERROR?`<span class="acctErr">${esc(SIGNIN_ERROR)}</span>`:'';
  if(ACCOUNT_DELETED){
    return `<div class="acctRow"><span class="acctState">&#10003; Your account and its picks were deleted. You are playing as a guest again.</span>
      ${buttons?`<span class="acctBtns">${buttons}</span>`:''}</div>`;
  }
  if(!buttons)return note?`<div class="acctRow">${note}</div>`:'';
  return `<div class="acctRow"><span class="acctState">Playing as a guest — clearing this browser loses your record. To recover scores on another device or after clearing your browser, sign in with Google or GitHub, then use that same account to return.</span>
    <span class="acctBtns">${buttons}</span>${note}</div>`;
}
// Community answers one question: what are other Matchday users picking?
// Model performance lives on Scorecard, rankings on Rankings, analysis on
// Games -- so this page is three light sections and no dashboards:
//   1. Community picks  -- the week's games, the community split beside the
//      model, and your own pick. Picks are a draft until "Submit picks".
//   2. Leaderboard      -- This week | Season, W-L only.
//   3. Recent activity  -- who picked what, and yesterday's records.
let COMM_ALL=false,COMM_FLASH='',COMM_OPEN='',COMM_CONSENSUS={},COMM_ACTIVITY=null,COMM_FETCHED='';
function btmDraft(){try{return JSON.parse(localStorage.getItem('matchday.btmDraft')||'{}')||{}}catch(e){return {}}}
function btmDraftSave(d){try{localStorage.setItem('matchday.btmDraft',JSON.stringify(d))}catch(e){}}
function draftPick(id,side){const d=btmDraft();if(d[id]===side)delete d[id];else d[id]=side;btmDraftSave(d);renderCommunity()}
function pickBtm(id,side){draftPick(id,side)}
function clearDraft(){btmDraftSave({});renderCommunity()}
function toggleCommGame(id){COMM_OPEN=COMM_OPEN===id?'':id;renderCommunity()}
function submitDraft(){
  const d=btmDraft(),ids=Object.keys(d);if(!ids.length)return;
  if(!confirm(`Submit ${ids.length} pick${ids.length===1?'':'s'}? You can change a pick until kickoff; after that it is locked and graded.`))return;
  let done=0;const left={};
  ids.forEach(id=>{if(submitPick(id,d[id],false))done++;else{const m=(DATA.matches||[]).find(x=>String(x.id)===String(id));if(m&&isCommunityPickOpen(m)&&btmLoad().picks?.[id]?.pick!==d[id])left[id]=d[id]}});
  btmDraftSave(left);
  COMM_FLASH=done?`${done} pick${done===1?'':'s'} submitted.`:'Nothing was submitted: those games have started or were already picked.';
  COMM_FETCHED='';renderCommunity();
}
async function commFetch(action,comp){
  if(!LEADERBOARD_URL)return null;
  try{const r=await fetch(`${LEADERBOARD_URL}?action=${action}&comp=${encodeURIComponent(comp)}`);const d=await r.json();return d.ok?d:null}catch(e){return null}
}
function commLoad(comp){
  const stamp=comp+':'+Math.floor(Date.now()/60000);if(COMM_FETCHED===stamp)return;COMM_FETCHED=stamp;
  Promise.all([commFetch('consensus',comp),commFetch('activity',comp),fetchLeaderboard(lbPeriod())]).then(([c,a,board])=>{
    COMM_CONSENSUS=c?.games||{};COMM_ACTIVITY=a?.items||[];COMM_BOARD=board;if(VIEW==='community')renderCommunity(true);
  });
}
let COMM_BOARD=null;
function commSplit(m,picks){
  const c={...(COMM_CONSENSUS[m.id]||{h:0,d:0,a:0})},mine=picks[m.id];
  const n=(c.h||0)+(c.d||0)+(c.a||0);return {h:c.h||0,d:c.d||0,a:c.a||0,n,mine};
}
// Never 100%: a pick is a forecast, and a unanimous split is still not certain.
function commPct(v){const n=Number(v)||0;return (n>=99.95?99.9:n<=0.05&&n>0?0.1:n).toFixed(1).replace(/\.0$/,'')+'%'}
function commShort(m,side){return side==='h'?(m.home.code||m.home.name):side==='a'?(m.away.code||m.away.name):t('Draw')}
function commAgo(ms){const s=Math.max(0,(Date.now()-ms)/1000);return s<3600?`${Math.max(1,Math.round(s/60))}m ago`:s<86400?`${Math.round(s/3600)}h ago`:`${Math.round(s/86400)}d ago`}
function renderCommunity(fromFetch){ensureHandle();const host=$('#view-community');const db=btmScoped(btmGrade());const s=btmStats(db);
  const comp=String(DATA.comp_key||(/ncaam/.test(String(DATA_FILE||''))?'ncaam':'ncaaf')).toLowerCase();
  if(!fromFetch)commLoad(comp);
  const eligible=(DATA.matches||[]).filter(m=>isCommunityPickOpen(m)).sort((a,b)=>(a.kickoff||'').localeCompare(b.kickoff||''));
  const firstKick=eligible.length?kickMs(eligible[0]):0;
  // A missing market can expose an entire season at once; show the next slate.
  const open=eligible.filter(m=>communityPickProbs(m).source==='betbetter'||kickMs(m)<=firstKick+4*864e5).slice(0,40);
  const picks=db.picks||{};
  const draft=btmDraft();Object.keys(draft).forEach(id=>{if(picks[id]?.pick===draft[id]||!open.some(m=>String(m.id)===String(id)))delete draft[id]});
  const nDraft=Object.keys(draft).length;
  let h=`<div class="vhead">Community</div><p class="commLede">What other Matchday users are picking this week.</p>`;
  if(COMM_FLASH){h+=`<div class="commFlash" role="status">${esc(COMM_FLASH)}</div>`;COMM_FLASH='';}
  h+=`<div class="commLayout"><section class="commMain" aria-labelledby="commPicksTitle"><div class="commHead"><h2 id="commPicksTitle">Community picks</h2><span>This week</span></div>`;
  if(!open.length)h+=`<div class="empty">No games are open for picks yet.<br><span class="faintline">Games open seven days before kickoff.</span></div>`;
  else{
    h+=`<div class="commTable" role="table"><div class="commRow commCols" role="row"><span role="columnheader">Game</span><span role="columnheader">Community</span><span role="columnheader" title="Live model: can change before kickoff">Live model</span><span role="columnheader">Your pick</span></div>`;
    // Twelve rows answer 'what is the community picking'; the rest of the
    // week is one tap away instead of a long scroll.
    const shown=COMM_ALL?open:open.slice(0,12);
    shown.forEach(m=>{
      const x=communityPickProbs(m),read=x.read,sp=commSplit(m,picks),p=picks[m.id],dr=draft[m.id];
      const lead=sp.n?(['h','a','d'].reduce((a,b)=>sp[b]>sp[a]?b:a,'h')):null;
      const community=sp.n?`${commPct(sp[lead]/sp.n*100)} ${esc(commShort(m,lead))}`:'<i>no picks yet</i>';
      const model=read?`${communityModelPctLabel(read.model_pct)} ${esc(bbNameMatches(read.pick_name,m.home.name)?commShort(m,'h'):commShort(m,'a'))}`:'<i title="Model probabilities pending">—</i>';
      const mine=dr?`<b class="commMine">${esc(commShort(m,dr))}${p?' (change)':''}</b>`:p?`<b class="commMine locked">${esc(commShort(m,p.pick))} ✓</b>`:'<span class="commMine none">Pick</span>';
      const isOpen=COMM_OPEN===String(m.id);
      h+=`<button type="button" class="commRow commGame${isOpen?' open':''}" role="row" aria-expanded="${isOpen}" onclick="toggleCommGame('${esc(String(m.id))}')"><span role="cell" class="commGameName"><span class="commTeams"><span class="commTeam"><i class="commAt"></i>${teamMark(m.away.name)}<b>${esc(m.away.name)}</b></span><span class="commTeam"><i class="commAt">@</i>${teamMark(m.home.name)}<b>${esc(m.home.name)}</b></span></span><small>${esc(kickIn(m.kickoff))}</small></span><span role="cell">${community}</span><span role="cell">${model}</span><span role="cell">${mine}</span></button>`;
      if(isOpen){
        const bar=(side,label)=>{const pct=sp.n?sp[side]/sp.n*100:0;return `<div class="commBar"><span>${esc(label)}</span><i><em style="width:${pct}%"></em></i><b>${commPct(pct)}</b></div>`};
        const btn=(side,label)=>{const chosen=dr?dr===side:p?.pick===side;const saved=!dr&&p?.pick===side;return `<button type="button" class="btmbtn${saved?' locked':''}${dr===side?' drafted':''}" aria-pressed="${chosen}" onclick="pickBtm('${esc(String(m.id))}','${side}')">${esc(label)}</button>`};
        h+=`<div class="commDetail" role="row"><div role="cell"><div class="commBars">${bar('a',m.away.name)}${bar('h',m.home.name)}<small>${sp.n} pick${sp.n===1?'':'s'} from the community</small></div>
          <div class="btmrow">${btn('a',m.away.name)}${btn('h',m.home.name)}</div>
          <small class="commNote">${p?'Submitted. You can change it until kickoff.':'Tap a team, then Submit picks.'} <button type="button" class="gamesTextLink" onclick="openMatchModal('${esc(String(m.id))}')">Game analysis →</button></small></div></div>`;
      }
    });
    h+=`</div>`;
    if(open.length>12)h+=`<button type="button" class="gamesTextLink commMore" onclick="COMM_ALL=!COMM_ALL;renderCommunity(true)">${COMM_ALL?'Show fewer games':`Show all ${open.length} games`}</button>`;
    h+=`<div class="commSubmitBar${nDraft?' ready':''}"><span>${nDraft?`<b>${nDraft}</b> pick${nDraft===1?'':'s'} ready to submit`:'Open a game to make a pick'}</span>${nDraft?`<button type="button" class="commClear" onclick="clearDraft()">Clear</button>`:''}<button type="button" class="commSubmit" ${nDraft?'':'disabled'} onclick="submitDraft()">Submit picks</button></div>`;
  }
  h+=`</section><aside class="commSide">`;
  // Leaderboard: This week | Season, W-L only.
  const period=lbPeriod()==='week'?'week':'all';
  h+=`<section class="commBox" aria-labelledby="commBoardTitle"><div class="commHead"><h2 id="commBoardTitle">Leaderboard</h2><div class="lbTabs"><button class="lbTab ${period==='week'?'on':''}" onclick="setLbPeriod('week')">This week</button><button class="lbTab ${period==='all'?'on':''}" onclick="setLbPeriod('all')">Season</button></div></div>`;
  if(!LEADERBOARD_URL)h+=`<div class="empty">Coming soon.</div>`;
  else if(COMM_BOARD===null)h+=`<div class="empty">Loading…</div>`;
  else if(!COMM_BOARD.length)h+=`<div class="empty">${period==='week'?'No one has 3 graded picks this week yet.':'No one has 10 graded picks yet.'}</div>`;
  else h+=`<ol class="commBoard">${COMM_BOARD.slice(0,10).map((r,i)=>`<li${r.handle===myHandle()?' class="me"':''}><span>${i+1}</span><b>${esc(r.handle)}</b><em>${r.hits}–${Math.max(0,r.graded-r.hits)}</em></li>`).join('')}</ol>`;
  h+=`<p class="commYou">You are <b>${esc(myHandle()||'')}</b> · ${s.you}–${Math.max(0,(s.n||0)-s.you)}${canReshuffleHandle()?` · <button type="button" class="gamesTextLink" onclick="reshuffleHandle()">new name</button>`:''}</p>${renderAccountRow()}</section>`;
  // Recent activity.
  const byId=new Map((DATA.matches||[]).map(m=>[String(m.id),m]));
  const items=(COMM_ACTIVITY||[]).map(it=>{
    if(it.kind==='day')return `<li><b>${esc(it.handle)}</b> went ${it.wins}–${it.losses} yesterday<small>${commAgo(it.at)}</small></li>`;
    const m=byId.get(String(it.matchId));if(!m)return '';
    const team=it.pick==='h'?m.home.name:it.pick==='a'?m.away.name:'a draw',other=it.pick==='h'?m.away.name:m.home.name;
    return `<li><b>${esc(it.handle)}</b> picked ${esc(team)} over ${esc(other)}<small>${commAgo(it.at)}</small></li>`;
  }).filter(Boolean);
  h+=`<section class="commBox" aria-labelledby="commActTitle"><div class="commHead"><h2 id="commActTitle">Recent activity</h2></div>${COMM_ACTIVITY===null?'<div class="empty">Loading…</div>':items.length?`<ul class="commFeed">${items.slice(0,12).join('')}</ul>`:'<div class="empty">No picks yet this week. Be the first.</div>'}</section>`;
  h+=`</aside></div>`;
  host.innerHTML=h;
}

/* ===== Matchup Sandbox — hypothetical same-competition matchups ===========
   Client-side port of predict()/predict_totals()'s standings-based strength
   calc (points/goal-diff/form/preseason class rating/home-advantage --
   no injuries or market data, since there's no real scheduled game to
   attach any of that to). Runs entirely in the browser against
   DATA.standings, or DATA.matches when standings are empty (preseason). */
const SANDBOX_TWO_WAY=new Set(['ncaaf','ncaam']);
// Same full-season game counts predict() uses server-side, so a team's
// record/form don't get full-confidence weight off a handful of games --
// and season_stale (provider had no current-season sample yet and fell
// back to last season's final record) dents it further, matching the
// backend fix for the same P4-loses-class-edge-to-a-stale-record bug.
const SANDBOX_FULL_GAMES={ncaaf:10,ncaam:18};
function sandboxTeams(){
  const fromStandings=(DATA.standings||[]).filter(g=>g.table_type!=='power_ratings').flatMap(g=>g.teams||[]);
  if(fromStandings.length)return fromStandings;
  // Preseason / before any games are played, standings are legitimately
  // empty -- fall back to the team list from scheduled fixtures so the
  // picker still works. sandboxStrength() already handles missing
  // pts/gd/form gracefully (falls back to a neutral base), so this just
  // produces a toss-up until real results start coming in.
  const seen=new Map();
  (DATA.matches||[]).forEach(m=>{[m.home,m.away].forEach(t=>{if(t&&t.name&&!seen.has(t.name))seen.set(t.name,t)})});
  return [...seen.values()];
}
function sandboxStrength(team,adv){
  const compKey=String(DATA.comp_key||'').toLowerCase();
  const american=SANDBOX_TWO_WAY.has(compKey);
  const fp=String(team.form||'').split(' ').filter(Boolean).reduce((s,r)=>s+({W:3,D:1,L:0}[r]||0),0);
  let reliability=1;
  if(american){
    const full=SANDBOX_FULL_GAMES[compKey]||15;
    reliability=Math.min(1,(team.pld||0)/full);
    if(team.season_stale)reliability*=0.25;
  }
  return Math.max(0.1,1.0+(team.pts||0)*0.6*reliability+(team.gd||0)*0.25*reliability+fp*0.5*reliability+(team.rating||0)+adv);
}
function sandboxExpectedTotal(home,away){
  const rate=(side,key)=>{const pld=side.pld||0,val=side[key];return(!pld||val==null||val===0)?null:val/pld;};
  const hgf=rate(home,'gf'),hga=rate(home,'ga'),agf=rate(away,'gf'),aga=rate(away,'ga');
  if([hgf,hga,agf,aga].some(v=>v==null))return null;
  return Math.round((((hgf+aga)/2)+((agf+hga)/2))*100)/100;
}
function sandboxRun(homeName,awayName){
  const teams=sandboxTeams();
  const home=teams.find(t=>t.name===homeName),away=teams.find(t=>t.name===awayName);
  if(!home||!away)return null;
  const twoWay=SANDBOX_TWO_WAY.has(String(DATA.comp_key||'').toLowerCase());
  const sh=sandboxStrength(home,1.2),sa=sandboxStrength(away,0.0);
  const draw=twoWay?0:0.26,tot=sh+sa;
  const probs={h:Math.round(sh/tot*(1-draw)*100),a:Math.round(sa/tot*(1-draw)*100),d:Math.round(draw*100)};
  const outcomes=twoWay?['h','a']:['h','d','a'];
  const pick=outcomes.reduce((best,k)=>probs[k]>probs[best]?k:best,outcomes[0]);
  return {home,away,probs,pick,twoWay,expected:sandboxExpectedTotal(home,away)};
}
function sandboxPick(side,name){window.__sandboxSel=window.__sandboxSel||{};window.__sandboxSel[side]=name;renderSandbox();}
function renderSandbox(){
  const host=$('#view-sandbox');
  const teams=sandboxTeams();
  if(teams.length<2){
    const msg='No teams to build a matchup with yet — check back once fixtures are scheduled for this sport.';
    host.innerHTML=`<div class="vhead">Matchup Sandbox</div><div class="empty">${msg}</div>`;return;
  }
  const sorted=teams.slice().sort((a,b)=>a.name.localeCompare(b.name));
  const sel=window.__sandboxSel=window.__sandboxSel||{home:sorted[0]?.name,away:sorted[1]?.name};
  const buildOpts=selected=>sorted.map(t=>`<option value="${esc(t.name)}"${t.name===selected?' selected':''}>${esc(t.name)}</option>`).join('');
  let resultHtml='';
  if(sel.home&&sel.away&&sel.home!==sel.away){
    const r=sandboxRun(sel.home,sel.away);
    if(r){
      const tiles=[['h',r.home.code||r.home.name,r.probs.h]];
      if(!r.twoWay)tiles.push(['d','Draw',r.probs.d]);
      tiles.push(['a',r.away.code||r.away.name,r.probs.a]);
      const pickName=r.pick==='d'?'Draw':(r.pick==='h'?r.home.name:r.away.name);
      resultHtml=`<div class="analystBox probMatrixCard" style="margin-top:16px"><div class="analystBoxTitle">Model read</div>
        <div class="probMatrix"><div class="probTiles">${tiles.map(([side,label,pct])=>_v12ProbTile(label,pct,side,side===r.pick)).join('')}</div></div>
        <p class="probContextLine">${esc(pickName)} favored at ${r.probs[r.pick]}%${r.expected!=null?` · model expects ${r.expected} combined ${_totalsUnit()}`:''}.</p>
        <p class="small" style="color:var(--faint);margin-top:8px">Hypothetical matchup — uses each team's current points, goal/point difference, recent form, and preseason class/power rating. No fixture-specific injuries or market data, since there's no real game to price.</p>
        </div>`;
    }
  } else if(sel.home===sel.away){
    resultHtml=`<div class="empty" style="margin-top:16px">Pick two different teams.</div>`;
  }
  host.innerHTML=`<div class="vhead">Matchup Sandbox</div>
    <div class="sandboxPickers">
      <select id="sandboxHome" onchange="sandboxPick('home',this.value)">${buildOpts(sel.home)}</select>
      <span class="sandboxVs">vs</span>
      <select id="sandboxAway" onchange="sandboxPick('away',this.value)">${buildOpts(sel.away)}</select>
    </div>
    ${resultHtml}`;
}
function tournamentPlayerKey(name){return String(name||'').normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLowerCase().replace(/[^a-z0-9]+/g,' ').trim()}
function officialTournamentSelection(){
  const selections=globalThis.MATCHDAY_OFFICIAL_SELECTIONS||{};
  return Object.values(selections).find(selection=>{
    if(selection.competition!==currentSportKey())return false;
    return (selection.signature||[]).every(expected=>(DATA.scorers||[]).some(s=>tournamentPlayerKey(s.name)===tournamentPlayerKey(expected.name)&&Number(s.goals)===Number(expected.goals)));
  })||null;
}
function tournamentViewData(){
  const official=officialTournamentSelection();if(!official)return DATA.team_of_tournament;
  const scorers=new Map((DATA.scorers||[]).map(p=>[tournamentPlayerKey(p.name),p]));
  return {...official,kind:'official',v:3,xi:official.xi.map(player=>{
    const stats=scorers.get(tournamentPlayerKey(player.name));
    return {...player,goals:Number(stats?.goals)||0,assists:Number(stats?.assists)||0,played:Number(stats?.played)||0,statsAvailable:!!stats};
  })};
}
function renderTOTT(){const host=$('#view-tott');const t=tournamentViewData();
  if(!t||!t.xi||!t.xi.length){host.innerHTML=`<div class="vhead">${esc(tottTitle())}</div><div class="empty">Builds once qualifying player stats are logged. Check back after more matches.</div>`;return;}
  if(t.v!==2&&t.v!==3){host.innerHTML=`<div class="vhead">${esc(tottTitle())}</div><div class="banner"><b>Positions need a rebuild.</b> This XI was generated before the real-position fix — run one fetch and players will group by their actual positions (no more strikers in goal).</div>`;return;}
  const byRole=r=>t.xi.filter(p=>p.role===r),official=t.kind==='official';
  const complete=t.xi.length===11&&byRole('FWD').length>0&&byRole('MID').length>0&&byRole('DEF').length>0&&byRole('GK').length===1;
  const stat=p=>official&&!p.statsAvailable?'Official XI':`${Number(p.goals)||0}G ${Number(p.assists)||0}A`;
  const line=(label,arr)=>arr.length?`<div class="tottLine"><div class="tottLbl">${label}</div><div class="tottRow">${arr.map(p=>`<div class="tottCard ${official?'official':''}"><div class="tottName">${esc(p.name||'')}</div><div class="tottTeam">${esc(p.code||p.team||'')}</div><div class="tottStat">${esc(stat(p))}</div></div>`).join('')}</div></div>`:'';
  const source=official?`<a class="tottSource" href="${esc(t.sourceUrl)}" target="_blank" rel="noopener noreferrer">View UEFA source <span aria-hidden="true">↗</span></a>`:'';
  const intro=official
    ?`<div class="banner tottBanner"><span><b>Official ${esc(t.season)} selection.</b> Chosen by the ${esc(t.sourceName)}. Scoring figures are shown only where they exist in Matchday's licensed scorer feed.</span>${source}</div>`
    :complete
      ?`<div class="banner"><b>Model-built XI.</b> ${esc(t.note||'')}</div>`
      :`<div class="banner warn"><b>Model attacking leaders — not a complete XI.</b> ${esc(t.note||'')} Empty positions are hidden until real lineup data supports them.</div>`;
  host.innerHTML=`<div class="vhead">${esc(tottTitle())}</div>${intro}
    <div class="tottPitch ${official?'official':''}">${line('Forwards',byRole('FWD'))}${line('Midfield',byRole('MID'))}${line('Defence',byRole('DEF'))}${line('Goalkeeper',byRole('GK'))}</div>`;}
let POSTS_CACHE=null;
function loadPosts(){
  if(POSTS_CACHE)return Promise.resolve(POSTS_CACHE);
  return fetch('posts.json').then(r=>r.json()).catch(()=>[]).then(list=>{POSTS_CACHE=Array.isArray(list)?list:[];return POSTS_CACHE});
}
let RESEARCH_POSTS_CACHE=null;
function loadResearchPosts(){
  if(RESEARCH_POSTS_CACHE)return Promise.resolve(RESEARCH_POSTS_CACHE);
  return fetch('research_posts.json').then(r=>r.json()).catch(()=>[]).then(list=>{RESEARCH_POSTS_CACHE=Array.isArray(list)?list:[];return RESEARCH_POSTS_CACHE});
}
const INSIGHT_FEATURE_TYPES=new Set(['availability','ranking','simulation','market-audit','methodology']);
function isWeeklyRecapPost(post){return !INSIGHT_FEATURE_TYPES.has(post?.type)}
function insightFeatureLabel(post){return post?.type==='availability'?'Availability':post?.type==='ranking'?'Rankings':post?.type==='simulation'?'Simulation':post?.type==='market-audit'?'Market audit':post?.type==='methodology'?'Methodology':'Feature'}
function newestPostFirst(a,b){return String(b?.date||'').localeCompare(String(a?.date||''))}
function renderInsights(){
  const host=$('#view-insights');
  host.innerHTML=`<div class="vhead">Insights</div><div class="seclbl" style="margin-top:16px">Research</div><div class="hint" style="margin-bottom:8px">How the model itself performs: methodology notes and measured results.</div><div id="researchList" class="insightsList"><div class="empty">Loading…</div></div><div class="seclbl" style="margin-top:20px">Weekly recaps</div><div class="hint" style="margin-bottom:8px">Completed scorecards built from verified, locked picks.</div><div id="insightsList" class="insightsList"><div class="empty">Loading…</div></div><div class="seclbl" style="margin-top:20px">Analysis &amp; features</div><div class="hint" style="margin-bottom:8px">Opening boards, availability desks, simulations, and methodology notes.</div><div id="featuresList" class="insightsList"><div class="empty">Loading…</div></div>`;
  loadResearchPosts().then(posts=>{
    const list=$('#researchList');if(!list)return;
    if(!posts.length){list.innerHTML='<div class="empty">No research posts published yet.</div>';return;}
    list.innerHTML=posts.map(p=>`<a class="insightCard" href="posts/${esc(p.slug)}.html" target="_blank" rel="noopener"><b>${esc(p.title)}</b><span>${esc(p.summary||'')}</span><small>${esc(p.date||'')} · Research</small></a>`).join('');
  });
  loadPosts().then(posts=>{
    const recapList=$('#insightsList'),featuresList=$('#featuresList');if(!recapList||!featuresList)return;
    const recaps=posts.filter(isWeeklyRecapPost).sort(newestPostFirst),features=posts.filter(p=>!isWeeklyRecapPost(p)).sort(newestPostFirst);
    recapList.innerHTML=recaps.length?recaps.slice(0,40).map(p=>`<a class="insightCard" href="posts/${esc(p.slug)}.html" target="_blank" rel="noopener"><b>${esc(p.title)}</b><span>${esc(p.summary||'')}</span><small>${esc(p.date||'')} · ${esc(p.comp_label||'')}</small></a>`).join(''):'<div class="empty">No recaps published yet — check back once this week\'s games are graded.</div>';
    featuresList.innerHTML=features.length?features.slice(0,40).map(p=>`<a class="insightCard" href="posts/${esc(p.slug)}.html" target="_blank" rel="noopener"><b>${esc(p.title)}</b><span>${esc(p.summary||'')}</span><small>${esc(p.date||'')} · ${esc(insightFeatureLabel(p))}</small></a>`).join(''):'<div class="empty">No analysis features published yet.</div>';
  });
}
function renderCustomize(){const host=$('#view-customize');host.innerHTML=`<div class="vhead">Customize</div><div class="settings-grid"><div class="setcard"><label>Accent color</label><select onchange="updateSetting('accent',this.value)">${opt('orange','Matchday orange',SETTINGS.accent)}${opt('blue','Electric blue',SETTINGS.accent)}${opt('green','Pitch green',SETTINGS.accent)}${opt('red','Signal red',SETTINGS.accent)}${opt('purple','Night purple',SETTINGS.accent)}</select><div class="hint">Changes highlights, buttons and the brand dot.</div></div><div class="setcard"><label>Language</label><select onchange="setLang(this.value)">${lopt('','English',LANG)}${lopt('es','Español',LANG)}${lopt('fr','Français',LANG)}${lopt('de','Deutsch',LANG)}${lopt('pt','Português',LANG)}${lopt('ru','Русский',LANG)}</select><div class="hint">Translates the interface. Match data stays as provided by sources.</div></div><div class="setcard"><label>Card density</label><select onchange="updateSetting('density',this.value)">${opt('compact','Compact',SETTINGS.density)}${opt('normal','Normal',SETTINGS.density)}${opt('spacious','Spacious',SETTINGS.density)}</select><div class="hint">Compact fits more matches on screen; spacious gives each card more room.</div></div><div class="setcard"><label>Panel style</label><select onchange="updateSetting('panel',this.value)">${opt('glass','Soft glass',SETTINGS.panel)}${opt('flat','Flat dark',SETTINGS.panel)}</select><div class="hint">Flat mode is lighter on older laptops.</div></div><div class="setcard"><label>Default tab</label><select onchange="updateSetting('defaultView',this.value)">${['matches','groups','title','edge','bracket','third','news','status','updates'].map(v=>opt(v,v[0].toUpperCase()+v.slice(1),SETTINGS.defaultView)).join('')}</select><div class="hint">Selected when the page starts.</div></div><div class="setcard"><label>Refresh rate</label><select onchange="updateSetting('refresh',this.value)">${opt(900,'Every 15 minutes',SETTINGS.refresh)}${opt(1800,'Every 30 minutes',SETTINGS.refresh)}${opt(3600,'Every 60 minutes',SETTINGS.refresh)}</select><div class="hint">Reloads published analysis; provider refreshes run hourly.</div></div><div class="setcard"><label>Display</label><div class="switchrow"><span>Right insight panel</span><input type="checkbox" ${checked(SETTINGS.showInsight)} onchange="updateSetting('showInsight',this.checked)"></div><div class="switchrow" style="margin-top:10px"><span>Match detail panels</span><input type="checkbox" ${checked(SETTINGS.showDetails)} onchange="updateSetting('showDetails',this.checked)"></div></div></div><div class="btnline"><button class="actionbtn" onclick="resetSettings()">Reset settings</button><button class="actionbtn" onclick="setView('status')">Check app status</button><button class="actionbtn" onclick="startTour()">Replay tour</button></div>`}
function scDeepTab(t){window._scTab=t;renderScore();}
function renderDeepDive(sc){const tab=window._scTab||'overview';
  // "You have 0" alone is confusing when the audit cards directly above show
  // graded legacy picks -- those deliberately never feed calibration/signals,
  // since a pick with no provable lock time can't evidence forecast accuracy.
  const need=(min,label)=>{
    if(sc.graded>=min)return '';
    const legacy=Number(sc.legacy?.graded ?? sc.quarantined?.graded)||0;
    const note=legacy?` ${legacy} legacy pick${legacy===1?'':'s'} ${legacy===1?'is':'are'} excluded here: without a provable pregame lock time they can't evidence forecast accuracy.`:'';
    return `<div class="empty">${label} unlocks after ${min} verified graded picks. You have ${sc.graded}.${note}</div>`;
  };
  const tabs=['overview','calibration','signals','upsets','errors'];
  let h=`<div class="ddtabs">${tabs.map(x=>`<button class="ddtab ${x===tab?'on':''}" onclick="scDeepTab('${x}')">${x[0].toUpperCase()+x.slice(1)}</button>`).join('')}</div>`;
  if(tab==='overview'){
    // Deliberately renders nothing extra: renderScore() draws the full
    // headline grid (model record, market benchmark, disagreements, pending)
    // immediately below this, so repeating those four cards here stacked two
    // near-identical grids on top of each other -- eight cards, three of them
    // the same metric twice, which read as a broken/duplicated panel rather
    // than an overview. Overview is simply the default un-filtered view.
    h+='';
  } else if(tab==='calibration'){
    h+=need(20,'Calibration')||`<div class="seclbl">When the model says X%, how often does it happen?</div>`+(sc.calibration||[]).filter(c=>Number(c.n)>0).map(c=>{const pct=Math.round(c.hits/c.n*100);return `<div class="ddrow"><span>${c.band}%</span><div class="ddbarwrap"><div class="ddbar" style="width:${pct}%"></div></div><span>${pct}% <i class="ssnote">(${c.n})</i></span></div>`}).join('');
  } else if(tab==='signals'){
    h+=need(20,'Signal quality')||`<div class="seclbl">When a factor favoured the pick, did the pick hit?</div>`+Object.entries(sc.signal_quality||{}).filter(([k,v])=>v.n).map(([k,v])=>{const L={class:'Talent / squad quality',market_power:'Championship market power',form:'Recent form',gd:'Score difference',rest:'Rest',pts:'Points',record:'Season record',margin:'Scoring margin',rank:'Poll rank',srs:'Opponent-adjusted rating',elo:'Elo rating'}[k]||k;const pct=Math.round(v.hits/v.n*100);return `<div class="ddrow"><span>${L}</span><div class="ddbarwrap"><div class="ddbar ${pct>=55?'good':pct<45?'bad':''}" style="width:${pct}%"></div></div><span>${v.hits}/${v.n} <i class="ssnote">${pct}%</i></span></div>`;}).join('');
  } else if(tab==='upsets'){
    const u=sc.upset||{};h+=`<div class="status-grid">
      <div class="statuscard info"><span class="slbl">Underdogs tracked</span><div class="sval">${u.watched||0}</div><div class="hint">genuine market underdogs</div></div>
      <div class="statuscard ${u.hits?'ok':'info'}"><span class="slbl">Underdog wins</span><div class="sval">${u.hits||0}/${u.watched||0}</div><div class="hint">tracked underdog won</div></div>
      <div class="statuscard info"><span class="slbl">Triggered picks</span><div class="sval">${u.triggered_hits||0}/${u.triggered||0}</div><div class="hint">upset became the pick</div></div>
      <div class="statuscard info"><span class="slbl">Avg score</span><div class="sval">${u.avg_score??'—'}</div><div class="hint">of tracked underdogs</div></div></div>`;
  } else if(tab==='errors'){
    h+=(sc.misses&&sc.misses.length)?`<div class="seclbl">Recent misses — with the evidence at lock time</div>`+sc.misses.map(m=>`<div class="ddmiss"><b>${esc(m.home)} v ${esc(m.away)}</b><span>picked ${m.pick==='h'?esc(m.home):m.pick==='a'?esc(m.away):'Draw'}${m.upset?` · upset flag: ${esc(m.upset)}`:''}${m.gap!=null?` · market gap ${m.gap}`:''}</span></div>`).join(''):`<div class="empty">No graded misses yet — or none captured with evidence. New picks capture full evidence.</div>`;
  }
  return h;}

// Favorite-team personalization is injected after the base settings renderer so
// it stays independent from the rest of the settings layout.
const _renderCustomizeBase=renderCustomize;
renderCustomize=function(){
  _renderCustomizeBase();
  const grid=document.querySelector('#view-customize .settings-grid');
  if(!grid)return;
  const refreshCard=[...grid.querySelectorAll('.setcard')].find(item=>item.querySelector('label')?.textContent.trim()==='Refresh rate');
  refreshCard?.remove();
  const language=[...grid.querySelectorAll('.setcard')].find(item=>item.querySelector('label')?.textContent.trim()==='Language');
  // Rebuilt on every render, not just created once: following or unfollowing a
  // team has to show up in the chips immediately, and the card is cheap.
  const favMarkup=`<label>${t('My teams')}</label>${favoriteTeamsControl()}<div class="hint">${t('Your teams move to the front of matches, news, tables and the insight panel.')}</div>`;
  const existingFav=grid.querySelector('.favoriteTeamSetting');
  if(existingFav){existingFav.innerHTML=favMarkup}
  else{
    const card=document.createElement('div');
    card.className='setcard favoriteTeamSetting';
    card.innerHTML=favMarkup;
    if(language)language.insertAdjacentElement('afterend',card);else grid.prepend(card);
  }
  if(!grid.querySelector('.alertSettings')){
    const alerts=document.createElement('div');
    alerts.className='setcard alertSettings';
    alerts.innerHTML=`<label>Alert preferences</label><div class="alertSettingList"><label><span>Kickoff reminders<small>Watched and favorite teams</small></span><input type="checkbox" ${checked(SETTINGS.alertsKickoff)} onchange="updateSetting('alertsKickoff',this.checked)"></label><label><span>Model movement<small>Pregame probability and market gaps</small></span><input type="checkbox" ${checked(SETTINGS.alertsModel)} onchange="updateSetting('alertsModel',this.checked)"></label><label><span>Data health<small>Delayed or stale published analysis</small></span><input type="checkbox" ${checked(SETTINGS.alertsData)} onchange="updateSetting('alertsData',this.checked)"></label></div><div class="hint">Alerts stay inside Matchday for now. Live score and in-game upset alerts are intentionally not offered.</div>`;
    grid.append(alerts);
  }
};

/* ---- College board modules -------------------------------------------------
   Four cards above the fixture board. Everything numeric here is read from the
   Bet Better handoff baked into matchday-cfb-snapshot.js by
   build_cfb_snapshot.py; nothing on this page recomputes a rating.

   Two rules shape what these may say:
   * edge_points is reported, never ranked on. On graded college samples a wider
     model-market gap predicted WORSE results. The featured pick favors a
     competitive matchup between poll teams, not the largest percentage or gap.
   * A poll for a season that has not started is not a poll about this season.
     season_in_progress drives the caveat, and the engine's own `note` is
     rendered rather than paraphrased.
---------------------------------------------------------------------------- */
function collegeRankingTable(){
  const key=(typeof currentSportKey==='function'?currentSportKey():'')||'';
  if(key==='ncaam')return typeof MATCHDAY_NCAAM_RANKINGS!=='undefined'?MATCHDAY_NCAAM_RANKINGS:null;
  return typeof MATCHDAY_CFB_RANKINGS!=='undefined'?MATCHDAY_CFB_RANKINGS:null;
}

// One board, two sports, one handoff.
//
// The ranking cards already switch on collegeRankingTable(), but the four cards
// fed straight from the handoff globals did not, and those globals hold every
// sport at once. The basketball board therefore led with a football upset of the
// week, a football top pick, football finals under "Top scores" and a football
// betting record -- Oklahoma State at Tulsa, sitting above a Top 25 of
// basketball teams.
//
// Every section of the handoff stamps `sport` on each row, so this filters on it
// rather than guessing. A row that carries no sport is dropped on a sport's own
// board: if the engine ever stops stamping it, a card goes missing, which is the
// safer of the two failures.
function bbSportRows(rows){
  const key=(typeof currentSportKey==='function'?currentSportKey():'')||'';
  // The mixed board makes no claim about which sport it is showing, so there is
  // nothing there for a row to be wrong about.
  if(!key)return rows||[];
  return (rows||[]).filter(r=>String(r?.sport||'').toLowerCase()===key);
}
function formPips(form){
  const chars=String(form||'').slice(-6).split('');
  if(!chars.length)return '';
  return `<span class="pips">`+chars.map(c=>{
    const cls=c==='W'?'pw':c==='L'?'pl':'pd';
    return `<i class="${cls}" title="${c}"></i>`;
  }).join('')+`</span>`;
}
// Two fields, two questions, never merged:
//   movement                 = churn since last week's edition
//   movement_since_preseason = distance from where the ratings opened a team
// A team can be flat week to week and still sit twenty places off its preseason
// mark, so falling back from one to the other would answer a question nobody
// asked and label it as this week's move.
//
// Season 2026's NCAAF poll has been published once. Every row therefore has
// movement=null and previous_rank=null, and there is no week-over-week movement
// to draw. An unranked-before row is marked "new"; everything else shows
// nothing at all rather than an arrow it has not earned.
function movementTag(row){
  const m=Number(row?.movement);
  if(Number.isFinite(m)){
    if(m===0)return '<i class="mvFlat" title="unchanged since last edition">—</i>';
    return m>0
      ?`<i class="mvUp" title="up ${m} since last edition">▲${m}</i>`
      :`<i class="mvDown" title="down ${Math.abs(m)} since last edition">▼${Math.abs(m)}</i>`;
  }
  if(row?.previous_rank==null)return '<i class="mvNew" title="first edition of this power rating">new</i>';
  return '';
}
function modTop25(){
  const table=collegeRankingTable();
  const rows=(table?.top25||[]).slice(0,25);
  if(!rows.length)return '';
  const stale=table.season_in_progress===false;
  const caption=stale
    ?`<div class="modWarn">Projection — the season has not started. This rates the completed season.</div>`
    :'';
  // Only when a previous edition exists. In a first poll this is false and
  // the column is absent, rather than a row of dashes standing in for it.
  const anyMovement=rows.some(r=>Number.isFinite(Number(r.movement)));
  const ratings=rows.map(r=>Number(r.rating)).filter(Number.isFinite);
  const hi=Math.max(...ratings,0),lo=Math.min(...ratings,0);
  const span=(hi-lo)||1;
  const body=rows.map(r=>{
    const v=Number(r.rating);
    const pct=Number.isFinite(v)?Math.max(4,Math.round(((v-lo)/span)*100)):0;
    return `<li class="${r.rank<=4?'seedTop':''}"><b>${r.rank}</b>`
      +`<span class="modTeam">${esc(r.name)}${formPips(r.recent_form)}</span>`
      +`<span class="ratingCell"><i class="ratingBar" style="width:${pct}%"></i>`
      +`<span class="modNum">${Number.isFinite(v)?v.toFixed(2):'—'}</span></span>`
      +`<span class="modSos">${Number.isFinite(Number(r.sos))?'SoS '+Number(r.sos).toFixed(2):''}</span>`
      +(anyMovement?movementTag(r):'')+`</li>`;
  }).join('');
  return `<section class="boardMod modTop25"><header><h3>Power rating</h3>`
    +`<span>${esc(table.basis?.label||'Model rating')}</span></header>${caption}`
    +`<ol class="modList">${body}</ol>`
    +`<p class="modNote">${esc(String(table.note||'').replace(/\.\./g,'.'))}</p>`+`<p class="modNote">Full power rating of every rated team on the Conferences tab.</p></section>`;
}
/* My Top 25: the owner's ballot, beside the power rating rather than instead of
   it. The order is a person's call; what travels with each team is the résumé
   it was judged on (record, strength of record, best win, power rating rank),
   so a reader can see why and argue with it. The owner's published X ballot
   remains the fallback until the richer data-backed ballot exists. */
const MATCHDAY_PERSONAL_CFB_BALLOT={
  available:true,source:'x',published_on:'2026-09-20',
  source_url:'https://x.com/timurknowsball/status/2101747002237210721',
  note:'My first personal ranking after watching three weeks of college football.',
  rankings:['Texas Longhorns','Georgia Bulldogs','Miami Hurricanes','Ole Miss Rebels','Ohio State Buckeyes','Notre Dame Fighting Irish','Indiana Hoosiers','Alabama Crimson Tide','BYU Cougars','USC Trojans','Texas Tech Red Raiders','LSU Tigers','Utah Utes','Louisville Cardinals','Iowa Hawkeyes','Penn State Nittany Lions','Tennessee Volunteers','Florida Gators','Missouri Tigers','Mississippi State Bulldogs','Kentucky Wildcats','Houston Cougars','SMU Mustangs','Michigan Wolverines','Duke Blue Devils'].map((team_name,index)=>({rank:index+1,team_name,first_ballot:true,resume:{}}))
};
function collegeBallot(){
  const b=typeof MATCHDAY_BETBETTER_BALLOT!=='undefined'?MATCHDAY_BETBETTER_BALLOT:null;
  if(String(DATA.comp_key||'').toUpperCase()!=='NCAAF')return null;
  if(b?.available&&(b.rankings||[]).length)return b;
  return MATCHDAY_PERSONAL_CFB_BALLOT;
}
function ballotWin(g){
  if(!g)return '';
  const where=g.site==='away'?'at':g.site==='neutral'?'n':'vs';
  return `${where} ${g.opponent_rank?'#'+Number(g.opponent_rank)+' ':''}${esc(g.opponent)}`;
}
function ballotMove(r){
  if(r.first_ballot)return '';
  const m=Number(r.movement);
  if(r.movement==null)return '<i class="mvNew" title="not on last week\'s ballot">new</i>';
  if(!m)return '<i class="mvSame" title="unchanged">–</i>';
  return m>0?`<i class="mvUp" title="up ${m}">▲${m}</i>`:`<i class="mvDown" title="down ${-m}">▼${-m}</i>`;
}
function modBallot(){
  const b=collegeBallot();
  if(!b)return '';
  const body=b.rankings.map(r=>{
    const s=r.resume||{};
    return `<li class="${r.rank<=4?'seedTop':''}"><b>${Number(r.rank)}</b>`
      +`<span class="modTeam" title="${esc(r.note||'')}">${esc(r.team_name)}<small class="ballotSub">${esc(s.record||'')}${s.best_win?' · best win '+ballotWin(s.best_win):''}</small></span>`
      +`<span class="modSos">${s.power_rank?'PR #'+Number(s.power_rank):''}</span>`
      +ballotMove(r)+`</li>`;
  }).join('');
  return `<section class="boardMod modBallot"><header><h3>TimurKnowsBall Ballot</h3><span>ballot · ${esc(b.published_on||'')}</span></header>`
    +`<ol class="modList">${body}</ol>`
    +`<p class="modNote">${esc(b.note||'My own ranking of who has earned it: record and strength of record, quality wins and bad losses, head-to-head and conference titles, with the power rating as the eye test.')}${b.source_url?` <a href="${esc(b.source_url)}" target="_blank" rel="noopener">Original post on X</a>.`:' Full résumés on the Rankings tab.'}</p></section>`;
}
/* Upsets: the season's results the price said should not have happened.
   Recent finals on their own say nothing about which results mattered, so the
   card ranks wins by the winner's pregame chance (closing no-vig moneyline, or
   the closing spread when no moneyline was captured). Ranks are the ones
   published before kickoff. Falls back to recent finals only when the handoff
   carries no upset board. */
function modUpsets(){
  const board=(typeof MATCHDAY_BETBETTER_UPSETS!=='undefined'&&MATCHDAY_BETBETTER_UPSETS)||{};
  const rows=(board.upsets||[]).slice(0,8);
  if(String(DATA.comp_key||'').toUpperCase()!=='NCAAF'||!rows.length)return modTopScores();
  const ranked=(rank,name)=>`${rank?`<i class="upRank">${Number(rank)}</i>`:''}<span class="upName" title="${esc(name)}">${esc(name)}</span>`;
  const body=rows.map(u=>{
    const pct=Number(u.winner_pregame_pct),line=Number(u.winner_spread);
    const odds=Number.isFinite(line)&&line>0?`+${line%1?line.toFixed(1):line.toFixed(0)}`:'';
    const when=String(u.played_on||'').slice(5).replace('-','/');
    return `<li class="upRow" title="${esc(`${u.winner} had a ${pct.toFixed(1)}% pregame chance${odds?` (${odds} underdog)`:''} · ${when}`)}">`
      +`<span class="modTeam won">${ranked(u.winner_rank,u.winner)}</span><b class="upScore">${Number(u.winner_score)}</b>`
      +`<i class="upOdds">${Number.isFinite(pct)?Math.round(pct)+'%':''}<small>${esc(odds||'chance')}</small></i>`
      +`<span class="modTeam upLoser">${ranked(u.loser_rank,u.loser)}</span><b class="upScore upLoserScore">${Number(u.loser_score)}</b></li>`;
  }).join('');
  return `<section class="boardMod modScores modUpsets"><header><h3>Upsets</h3><span>biggest underdogs to win · pregame chance</span></header><ul class="modList">${body}</ul>`
    +`<p class="modNote">Ranked by how little chance the closing line gave the winner. Numbers are power rating positions at kickoff.</p></section>`;
}
function modTopScores(){
  let done=(DATA.matches||[]).filter(m=>m.status==='FINISHED'
    &&Number.isFinite(Number(m.score?.home))&&Number.isFinite(Number(m.score?.away)));
  // If the fixture feed carries no finals -- which it does not while the
  // provider quota is spent -- read the handoff's own results instead.
  if(!done.length&&typeof MATCHDAY_BETBETTER_RESULTS!=='undefined'){
    done=bbSportRows(MATCHDAY_BETBETTER_RESULTS).slice()
      .sort((a,b)=>String(b.played_on||'').localeCompare(String(a.played_on||'')))
      .map(r=>({home:{name:r.home},away:{name:r.away},kickoff:r.kickoff||r.played_on,
                status:'FINISHED',score:{home:Number(r.home_score),away:Number(r.away_score)}}));
  }
  if(!done.length)return '';
  // Most recent first; the margin is shown because a 3-point game and a
  // 40-point game are not the same result and the score alone buries that.
  const rows=done.sort((a,b)=>(b.kickoff||'').localeCompare(a.kickoff||'')).slice(0,6).map(m=>{
    const h=Number(m.score.home),a=Number(m.score.away);
    const homeWon=h>a;
    return `<li><span class="modTeam ${homeWon?'won':''}">${esc(m.home?.name||m.home||'')}</span>`
      +`<span class="modScore">${h}–${a}</span>`
      +`<span class="modTeam ${homeWon?'':'won'}">${esc(m.away?.name||m.away||'')}</span>`
      +`<i class="modMargin">${Math.abs(h-a)}</i></li>`;
  }).join('');
  return `<section class="boardMod modScores"><header><h3>Top scores</h3><span>most recent finals</span></header><ul class="modList">${rows}</ul></section>`;
}
/* The week's featured live read: the most competitive game between ranked
   teams, never ranked on the uncalibrated edge. Shared by the Home card and
   the Research lead. */
function featuredPick(){
  // Two sources on purpose. A scheduled build attaches the pick to the fixture;
  // a push build does not run the fetch that does so. The handoff is committed,
  // so fall back to it rather than let the card blink out of existence
  // depending on which kind of deploy shipped last.
  const now=new Date(),weekStart=new Date(now.getFullYear(),now.getMonth(),now.getDate()-((now.getDay()+6)%7));
  const weekEnd=new Date(weekStart);weekEnd.setDate(weekEnd.getDate()+7);
  const thisWeek=kickoff=>{const date=new Date(kickoff);return date>now&&date<weekEnd};
  const attached=(DATA.matches||[]).filter(m=>m.status==='UPCOMING'&&m.betbetter_pick&&thisWeek(m.kickoff))
    .map(m=>({m,p:m.betbetter_pick}));
  const baked=attached.length?[]:bbSportRows(typeof MATCHDAY_BETBETTER_PICKS!=='undefined'?MATCHDAY_BETBETTER_PICKS:[])
    .filter(p=>thisWeek(p.kickoff))
    .map(p=>({m:{home:{name:p.home},away:{name:p.away}},p}));
  const poll=currentSportKey()==='ncaaf'
    ?(typeof MATCHDAY_CFB_AP_POLL!=='undefined'?MATCHDAY_CFB_AP_POLL.rankings:[])
    :(collegeRankingTable()?.top25||collegeRankingTable()?.rankings||[]);
  const pollRank=name=>poll.find(r=>bbNameMatches(r.name||r.team_name,name))?.rank||99;
  const available=attached.concat(baked).filter(x=>Number.isFinite(Number(x.p.model_pct)));
  const competitive=available.filter(x=>Number(x.p.model_pct)<90);
  const picks=(competitive.length?competitive:available)
    .map(x=>({...x,homeRank:pollRank(x.m.home?.name||x.m.home),awayRank:pollRank(x.m.away?.name||x.m.away)}))
    .filter(x=>Number(x.p.model_pct)<90)
    // A real contest with two strong teams is more useful to feature than a
    // near-certain FBS/FCS mismatch. Never rank on the uncalibrated edge.
    .sort((a,b)=>((b.homeRank<=25)+(b.awayRank<=25))-((a.homeRank<=25)+(a.awayRank<=25))
      ||Math.max(a.homeRank,a.awayRank)-Math.max(b.homeRank,b.awayRank)
      ||Math.abs(Number(a.p.model_pct)-60)-Math.abs(Number(b.p.model_pct)-60));
  return picks[0]||null;
}
function modTopPick(){
  const fp=featuredPick();
  if(!fp)return '';
  const {m,p}=fp;
  const gap=Number(p.edge_points);
  return `<section class="boardMod modPick"><header><h3>Featured pick this week</h3><span>live model read</span></header>`
    +`<div class="modPickTeam">${esc(p.pick_name||'')}</div>`
    +`<div class="modPickGame">${esc(m.home?.name||m.home||'')} v ${esc(m.away?.name||m.away||'')}</div>`
    +`<div class="modPickBar"><i style="width:${Math.max(0,Math.min(100,Number(p.model_pct)))}%"></i></div>`
    +`<div class="modPickNums"><b>${communityModelPctLabel(p.model_pct)}</b> model`
    +(Number.isFinite(Number(p.market_pct))?` · <b>${Number(p.market_pct).toFixed(1)}%</b> market`:'')
    +(Number.isFinite(gap)?` · gap ${gap>0?'+':''}${gap.toFixed(1)}`:'')+`</div>`
    +`<p class="modNote">Not an official pick — a live model read that keeps moving until kickoff, and it is not graded. A wider model-market gap has predicted worse results on this engine's graded college samples, so the gap is context, not a signal.</p></section>`;
}
function modStatOfWeek(){
  const table=collegeRankingTable();
  const rows=(table?.rankings||[]).filter(r=>Number.isFinite(Number(r.movement_since_preseason)));
  if(!rows.length)return '';
  const riser=rows.slice().sort((a,b)=>Number(b.movement_since_preseason)-Number(a.movement_since_preseason))[0];
  const faller=rows.slice().sort((a,b)=>Number(a.movement_since_preseason)-Number(b.movement_since_preseason))[0];
  // Before anything has moved, movement is not a statistic. The toughest
  // schedule is, and it is the number the ingest fix exists to make readable.
  if(!riser||Number(riser.movement_since_preseason)<=0){
    const sos=(table?.rankings||[]).filter(r=>Number.isFinite(Number(r.sos)));
    if(!sos.length)return '';
    const ranked=sos.filter(r=>(r.rank||999)<=25);
    const hardest=(ranked.length?ranked:sos).slice().sort((a,b)=>Number(b.sos)-Number(a.sos))[0];
    return `<section class="boardMod modStat"><header><h3>Statistic of the week</h3><span>where teams start</span></header>`
      +`<div class="modStatBig">${esc(hardest.name)}</div>`
      +`<div class="modStatSub">strength of schedule <b>${Number(hardest.sos).toFixed(2)}</b>, rated ${Number(hardest.rating).toFixed(2)} at #${hardest.rank}</div>`
      +`<div class="modStatFoot">This is the preseason edition: the poll has been published once, so there is no week-over-week movement to report yet.</div></section>`;
  }
  return `<section class="boardMod modStat"><header><h3>Statistic of the week</h3><span>since the preseason edition</span></header>`
    +`<div class="modStatBig">${esc(riser.name)}</div>`
    +`<div class="modStatSub">up <b>${Number(riser.movement_since_preseason)}</b> places to #${riser.rank}, rating ${Number(riser.rating).toFixed(2)}</div>`
    +(faller&&Number(faller.movement_since_preseason)<0
      ?`<div class="modStatFoot">Biggest fall: ${esc(faller.name)}, down ${Math.abs(Number(faller.movement_since_preseason))} to #${faller.rank}</div>`:'')
    +`</section>`;
}

/* Rating against strength of schedule.
   A rating without its schedule is misleading, and this is the chart that says
   so at a glance: high and to the right is earned, high and to the left is
   padded. Drawn as inline SVG because the page ships no chart library and one
   scatter does not justify adding one.

   Tier colour is not decoration. A measured offset put the Power Four and the
   Group of Five on one scale, and the shape of the two groups is the evidence
   for that correction being real rather than asserted. */
function modRatingScatter(){
  const table=collegeRankingTable();
  const rows=(table?.rankings||[]).filter(r=>Number.isFinite(Number(r.rating))&&Number.isFinite(Number(r.sos)));
  if(rows.length<12)return '';
  const W=320,H=210,PL=34,PR=10,PT=12,PB=26;
  const xs=rows.map(r=>Number(r.sos)),ys=rows.map(r=>Number(r.rating));
  const x0=Math.min(...xs),x1=Math.max(...xs),y0=Math.min(...ys),y1=Math.max(...ys);
  const sx=v=>PL+((v-x0)/((x1-x0)||1))*(W-PL-PR);
  const sy=v=>H-PB-((v-y0)/((y1-y0)||1))*(H-PT-PB);
  const med=a=>{const b=a.slice().sort((m,n)=>m-n);return b[Math.floor(b.length/2)]};
  const mx=sx(med(xs)),my=sy(med(ys));
  const dots=rows.map(r=>{
    const power=String(r.tier||'')==='power';
    return `<circle cx="${sx(Number(r.sos)).toFixed(1)}" cy="${sy(Number(r.rating)).toFixed(1)}" r="${r.rank<=25?3.1:2.2}" class="${power?'dotP':'dotG'}"><title>${esc(r.name)} — rating ${Number(r.rating).toFixed(2)}, SoS ${Number(r.sos).toFixed(2)}${r.conference?' · '+esc(r.conference):''}</title></circle>`;
  }).join('');
  const labels=rows.slice(0,4).map(r=>
    `<text class="scLbl" x="${(sx(Number(r.sos))+5).toFixed(1)}" y="${(sy(Number(r.rating))+3).toFixed(1)}">${esc(String(r.name).split(' ')[0])}</text>`).join('');
  const anyG5=rows.some(r=>String(r.tier||'')&&String(r.tier)!=='power');
  return `<section class="boardMod modScatter"><header><h3>Rating vs schedule</h3><span>every rated team</span></header>
<svg viewBox="0 0 ${W} ${H}" class="scatter" role="img" aria-label="Scatter plot of team rating against strength of schedule">
  <line class="scAx" x1="${PL}" y1="${H-PB}" x2="${W-PR}" y2="${H-PB}"/>
  <line class="scAx" x1="${PL}" y1="${PT}" x2="${PL}" y2="${H-PB}"/>
  <line class="scMed" x1="${mx.toFixed(1)}" y1="${PT}" x2="${mx.toFixed(1)}" y2="${H-PB}"/>
  <line class="scMed" x1="${PL}" y1="${my.toFixed(1)}" x2="${W-PR}" y2="${my.toFixed(1)}"/>
  ${dots}${labels}
  <text class="scAxLbl" x="${(W/2).toFixed(0)}" y="${H-6}">strength of schedule →</text>
  <text class="scAxLbl" transform="rotate(-90 10 ${(H/2).toFixed(0)})" x="10" y="${(H/2).toFixed(0)}">rating →</text>
</svg>
<div class="scLegend"><span><i class="dotKeyP"></i>Power</span>${anyG5?'<span><i class="dotKeyG"></i>Group of Five</span>':''}<span class="scHint">lines are medians</span></div>
<p class="modNote">Up and to the right is a strong rating earned against a hard schedule. Up and to the left is a rating built on a soft one — which is exactly what a rating alone would hide.</p></section>`;
}

function modConferenceStrength(){
  const table=collegeRankingTable();
  const rows=(table?.rankings||[]).filter(r=>r.conference&&Number.isFinite(Number(r.rating)));
  if(rows.length<20)return '';
  const byConf={};
  rows.forEach(r=>{(byConf[r.conference]||=[]).push(Number(r.rating))});
  // Mean, not best team: one outlier should not make a conference look deep.
  const confs=Object.entries(byConf)
    .filter(([,v])=>v.length>=4)
    .map(([name,v])=>({name,mean:v.reduce((a,b)=>a+b,0)/v.length,n:v.length}))
    .sort((a,b)=>b.mean-a.mean).slice(0,5);
  if(confs.length<3)return '';
  const hi=Math.max(...confs.map(c=>c.mean)),lo=Math.min(...confs.map(c=>c.mean));
  const span=(hi-lo)||1;
  const bars=confs.map(c=>{
    const pct=Math.max(4,Math.round(((c.mean-lo)/span)*100));
    return `<li><span class="modTeam">${esc(c.name)}</span>`
      +`<span class="confBarWrap"><i class="confBar" style="width:${pct}%"></i></span>`
      +`<span class="modNum">${c.mean.toFixed(1)}</span><span class="modSos">${c.n}</span></li>`;
  }).join('');
  return `<section class="boardMod modConf"><header><h3>Conference strength</h3><span>mean rating</span></header>`
    +`<ul class="modList">${bars}</ul>`
    +`<p class="modNote">Average opponent-adjusted rating across each conference's rated teams, with the number of teams counted. A mean rather than a best team, so one outlier cannot make a conference look deep.</p></section>`;
}
function modNotable(){
  const table=collegeRankingTable();
  const rows=(table?.rankings||[]).filter(r=>Number.isFinite(Number(r.rating)));
  if(!rows.length)return '';
  const best=(key,dir)=>rows.filter(r=>Number.isFinite(Number(r[key])))
    .slice().sort((a,b)=>dir*(Number(b[key])-Number(a[key])))[0];
  const off=best('adj_o',1),def=best('adj_d',-1);
  const nonPower=rows.filter(r=>r.tier&&String(r.tier)!=='power')
    .slice().sort((a,b)=>Number(b.rating)-Number(a.rating))[0];
  const withheld=(table?.withheld||[]).length;
  const items=[];
  if(off)items.push(['Best offence',`${off.name}`,`${Number(off.adj_o).toFixed(1)} adj. points scored`]);
  if(def)items.push(['Best defence',`${def.name}`,`${Number(def.adj_d).toFixed(1)} adj. points allowed`]);
  if(nonPower)items.push(['Best outside the power tier',`${nonPower.name}`,`rated ${Number(nonPower.rating).toFixed(2)} at #${nonPower.rank}`]);
  if(!items.length)return '';
  return `<section class="boardMod modNotable"><header><h3>Notable</h3><span>from the full table</span></header>`
    +`<ul class="notableList">${items.map(([k,v,d])=>`<li><span class="ntKey">${esc(k)}</span><b>${esc(v)}</b><span class="ntDetail">${esc(d)}</span></li>`).join('')}</ul>`
    +(withheld?`<p class="modNote">${withheld} team${withheld===1?' is':'s are'} held out of the power rating — ratings earned mostly against FCS opposition, which the table would otherwise flatter.</p>`:'')
    +`</section>`;
}


/* Trim the power rating card to fit, rather than to a number someone liked.
   The board is three CSS columns and a column is as tall as what is in it, so
   the power rating card -- the only one whose length is arbitrary -- is what
   decides whether the other columns end in mid-air. Rather than guess a row
   count, the other cards are measured after layout and the list is cut to the
   largest number of rows that still fits inside the tallest of them.

   Everything cut is still reachable: the full rated table is on the
   Conferences tab, and the card says so. */
function fitRankingCard(){
  const card=document.querySelector('.boardMods .modTop25');
  const list=card?.querySelector('.modList');
  if(!card||!list)return;
  const others=Array.from(document.querySelectorAll('.boardMods .boardMod'))
    .filter(el=>el!==card).map(el=>el.offsetHeight).filter(h=>h>0);
  if(!others.length)return;
  const items=Array.from(list.children);
  if(items.length<2)return;
  const rowHeight=items[1].offsetHeight||items[0].offsetHeight;
  if(!rowHeight)return;
  // Room the list may occupy = tallest other card, minus this card's own
  // header, caption and notes.
  const budget=Math.max(...others)-(card.offsetHeight-list.offsetHeight);
  const fits=Math.floor(budget/rowHeight);
  // The overview has room for a complete Top 25, not a teaser. Keeping all 25
  // also lets the card use its share of the common column height with data
  // instead of an empty flex tail.
  const keep=Math.max(25,Math.min(items.length,fits));
  if(keep>=items.length)return;
  items.slice(keep).forEach(el=>el.remove());
  // The card's notes live behind its ? now (collapseBoardNotes), so the count
  // goes there too, in place of the pointer it used to replace.
  const help=card.querySelector('header .boardHelp');
  const full='Full power rating of every rated team on the Conferences tab.';
  if(help)setBoardHelp(help,String(help.dataset.tip||'').replace(full,'')+` Top ${keep} shown. ${full}`);
}

/* Pack the overview into real columns, shortest column first. CSS multi-column
   flow cannot promise a shared bottom edge when cards have different heights;
   these measured columns can, and their final cards stretch by the few pixels
   needed to close the rectangle. */
function balanceBoardMods(target){
  const board=target?.classList?.contains('boardMods')?target:document.querySelector('#view-matches > .boardMods');
  if(!board)return;
  const cards=Array.from(board.children).filter(el=>el.classList?.contains('boardMod'));
  const count=window.innerWidth>1180?3:window.innerWidth>720?2:1;
  if(count===1||cards.length<count)return;
  const heights=cards.map(card=>({card,height:card.offsetHeight}));
  const columns=Array.from({length:count},()=>({height:0,cards:[]}));
  heights.forEach(item=>{
    const column=columns.reduce((best,next)=>next.height<best.height?next:best);
    column.cards.push(item.card);
    column.height+=item.height+11;
  });
  board.replaceChildren(...columns.map(column=>{
    const el=document.createElement('div');
    el.className='modsCol';
    el.append(...column.cards);
    return el;
  }));
  board.classList.add('balanced');
}

const _renderCustomizeFullWidth=renderCustomize;
renderCustomize=function(){
  _renderCustomizeFullWidth();
  document.querySelectorAll('#view-customize .switchrow').forEach(row=>{
    if(row.textContent.includes('Right insight panel'))row.remove();
  });
};

/* Card explanations behind a ?, not under every card.
   Each board card ends in one or more `.modNote` paragraphs saying how to read
   it. Useful once, noise every visit after: across the board they were most of
   the text on screen. They move into the site's existing metricHelp button
   beside the card title -- hover or focus on desktop, tap on a phone (the
   metricHelp handler in app-1-core.js shows the bottom popover there).

   Built on the live DOM with textContent, never by reparsing HTML, so nothing
   the notes quote from a feed is ever re-read as markup. `.modWarn` stays
   visible: "this is a projection" is not an explanation, it is a caveat. */
function setBoardHelp(button,text){
  const label=button.dataset.label||'About this card';
  const copy=String(text||'').replace(/\s+/g,' ').trim();
  button.dataset.tip=copy;
  button.setAttribute('aria-label',`${label}: ${copy}`);
}
function collapseBoardNotes(root){
  (root||document).querySelectorAll('.boardMods .boardMod').forEach(card=>{
    const notes=Array.from(card.querySelectorAll('.modNote'));
    const title=card.querySelector('header h3');
    if(!notes.length||!title)return;
    let button=title.querySelector('.boardHelp');
    if(!button){
      button=document.createElement('button');
      button.type='button';
      button.className='metricHelp boardHelp';
      button.textContent='?';
      button.dataset.label=`About ${title.textContent.trim()}`;
      button.setAttribute('aria-expanded','false');
      button.setAttribute('aria-controls','metricHelpPopover');
      title.appendChild(button);
    }
    setBoardHelp(button,notes.map(n=>n.textContent.trim()).filter(Boolean).join(' '));
    notes.forEach(n=>n.remove());
  });
}
// The card clips its overflow (rounded corners, the accent bar), so the CSS
// tooltip metricHelp normally draws would be cut off inside it. On desktop the
// text goes in one fixed box on <body> instead, placed beside the button.
function boardTip(){
  let tip=document.getElementById('boardTip');
  if(tip)return tip;
  tip=document.createElement('div');
  tip.id='boardTip';
  tip.className='boardTip';
  tip.setAttribute('role','tooltip');
  tip.hidden=true;
  document.body.appendChild(tip);
  return tip;
}
function showBoardTip(button){
  if(window.matchMedia('(max-width: 760px)').matches)return;
  const tip=boardTip(),box=button.getBoundingClientRect();
  tip.textContent=button.dataset.tip||'';
  tip.hidden=false;
  const width=Math.min(300,window.innerWidth-24);
  tip.style.width=width+'px';
  tip.style.left=Math.min(Math.max(12,box.left-12),window.innerWidth-width-12)+'px';
  const below=box.bottom+8,height=tip.offsetHeight;
  tip.style.top=(below+height>window.innerHeight-12?Math.max(12,box.top-height-8):below)+'px';
  button.setAttribute('aria-describedby','boardTip');
}
function hideBoardTip(){
  const tip=document.getElementById('boardTip');
  if(tip)tip.hidden=true;
  document.querySelectorAll('.boardHelp[aria-describedby="boardTip"]').forEach(b=>b.removeAttribute('aria-describedby'));
}
document.addEventListener('pointerover',e=>{const b=e.target.closest?.('.boardHelp');if(b)showBoardTip(b)});
document.addEventListener('pointerout',e=>{if(e.target.closest?.('.boardHelp'))hideBoardTip()});
document.addEventListener('focusin',e=>{const b=e.target.closest?.('.boardHelp');b?showBoardTip(b):hideBoardTip()});
document.addEventListener('focusout',e=>{if(e.target.closest?.('.boardHelp'))hideBoardTip()});
window.addEventListener('scroll',hideBoardTip,true);

/* The week's upset call.
   Editorial, and labelled that way in the card rather than only in a tooltip.
   The engine ships a caveat with this pick saying disagreement of exactly this
   kind has historically predicted WORSE results on graded college samples, and
   that it must never be published as a recommended bet. That text is rendered
   as written -- paraphrasing a warning is how warnings get softened. */
function modUpsetOfWeek(){
  const u=(typeof MATCHDAY_BETBETTER_UPSET!=='undefined')?MATCHDAY_BETBETTER_UPSET:null;
  // Up to three calls a week since 2026-09-15. `picks` is the list; an older
  // handoff carries only `pick`, which still renders as one.
  const picks=u&&u.available?bbSportRows((u.picks&&u.picks.length)?u.picks:[u.pick].filter(Boolean)):[];
  if(!picks.length)return '';
  const one=p=>{
    const model=Number(p.model_pct),market=Number(p.market_pct),gap=Number(p.disagreement_points);
    const away=String(p.selection||'').toLowerCase()===String(p.away||'').toLowerCase();
    const status=typeof upsetStatusText==='function'?upsetStatusText(p,away):'';
    return `<div class="upsetPick">
<div class="modPickTeam">${esc(p.selection||'')}${Number.isFinite(gap)?`<em class="upsetGap">+${gap.toFixed(1)}</em>`:''}</div>
<div class="modPickGame">${esc(p.away||'')} at ${esc(p.home||'')}${status?` · ${esc(status)}`:''}</div>
<div class="upsetBars">
  <div><span>model</span><i style="width:${Math.max(2,Math.min(100,model))}%"></i><b>${communityModelPctLabel(model)}</b></div>
  <div class="mkt"><span>market</span><i style="width:${Math.max(2,Math.min(100,market))}%"></i><b>${Number.isFinite(market)?market.toFixed(1)+'%':'—'}</b></div>
</div></div>`;
  };
  return `<section class="boardMod modUpset"><header><h3>${picks.length>1?'Upsets of the week':'Upset of the week'}</h3><span>up to 3 a week</span></header>
${picks.map(one).join('')}
<p class="modNote">Up to three calls a week, picked from ${u.considered||0} games inside ${u.horizon_days||7} days: ${esc(u.basis||'')}. To watch and grade, not recommended bets.</p>
</section>`;
}

/* @timurknowsball's picks, against the model and the market.
   Three honesty constraints ship with this data and all three are obeyed:
   `reportable` false means the sample is too small to state a record as though
   it meant something; `excluded` counts picks recorded after kickoff, which are
   listed rather than dropped so nothing disappears silently; and `note` says
   these are predictions with no stake, price or balance attached. */
function modMyPicks(){
  const u=(typeof MATCHDAY_BETBETTER_USER_PICKS!=='undefined')?MATCHDAY_BETBETTER_USER_PICKS:null;
  // Every recorded pick is listed and every recorded pick counts. The engine
  // stamps recorded_at from when a pick reached it, which is not always when it
  // was made, so its own `record` field -- which totals only the rows it read as
  // pregame -- is not used here. The record below is computed from all of them.
  const picks=bbSportRows(u?.picks||[]);
  if(!picks.length)return '';
  const rec=u.record||{};
  const pct=v=>v!=null&&Number.isFinite(Number(v))?communityModelPctLabel(Number(v)*100):'—';
  // Newest first and capped. A record that keeps growing should not make this
  // card keep growing with it -- the older rows are still in the totals above.
  const MAX_ROWS=6;
  const ordered=picks.slice().sort((a,b)=>String(b.starts_at||'').localeCompare(String(a.starts_at||'')));
  const rows=ordered.slice(0,MAX_ROWS).map(p=>{
    const done=p.outcome===0||p.outcome===1;
    const won=p.outcome===1;
    return `<li><span class="modTeam">${esc(p.selection||'')}</span>`
      +`<span class="mpNum" title="my pick vs the model's frozen figure">${pct(p.model_probability)}</span>`
      +`<span class="mpNum mkt" title="market probability">${pct(p.market_probability)}</span>`
      +`<i class="mpFlag ${p.model_agreed?'agree':'differ'}" title="${p.model_agreed?'the model agreed':'the model disagreed'}">${p.model_agreed?'with':'vs'}</i>`
      +`<i class="mpOut ${done?(won?'won':'lost'):'wait'}">${done?(won?'W':'L'):'·'}</i></li>`;
  }).join('');
  const settled=picks.filter(p=>p.outcome===0||p.outcome===1);
  const wins=settled.filter(p=>p.outcome===1).length;
  const losses=settled.length-wins;
  const agreed=settled.filter(p=>p.model_agreed).length;
  const record=`<div class="modStatSub"><b>${wins}–${losses}</b> on settled picks · the model agreed on ${agreed}</div>`;
  return `<section class="boardMod modMine"><header><h3>@timurknowsball picks</h3><span>vs model &amp; market</span></header>
${record}
<div class="mpHead"><span>pick</span><span>model</span><span>market</span></div>
<ul class="modList">${rows}</ul>
${ordered.length>MAX_ROWS?`<p class="modNote">Showing the ${MAX_ROWS} most recent of ${ordered.length}. The record above counts them all.</p>`:''}
<p class="modNote">${esc(u.note||'')}</p></section>`;
}

/* A useful table for the foot of a research column.
   Toughest schedules, because it is the one number this week's upstream work
   was about and the board otherwise only shows SoS as a value beside a rating,
   never ranked on its own. Ranked teams only: the hardest schedule in the
   country belongs to a team rated -5 at #115, which is true and tells a reader
   nothing. */
function modToughestSchedules(){
  const table=collegeRankingTable();
  const rows=(table?.rankings||[]).filter(r=>Number.isFinite(Number(r.sos)));
  if(rows.length<10)return '';
  const pool=rows.filter(r=>(r.rank||999)<=40);
  const top=(pool.length>=10?pool:rows).slice().sort((a,b)=>Number(b.sos)-Number(a.sos)).slice(0,16);
  if(!top.length)return '';
  const body=top.map(r=>`<tr><td class="tsTeam" title="${esc(r.name)}"><span class="tsTeamName">${teamMark(r.name)}<span>${esc(r.name)}</span></span></td>`
    +`<td>#${r.rank}</td>`
    +`<td class="tsNum">${Number(r.sos).toFixed(2)}</td>`
    +`<td class="tsNum">${Number(r.rating).toFixed(2)}</td></tr>`).join('');
  return `<section class="boardMod modTough"><header><h3>Toughest schedules</h3><span>top 40 only</span></header>
<table class="tsTable"><thead><tr><th>Team</th><th>Rk</th><th>SoS</th><th>Rating</th></tr></thead><tbody>${body}</tbody></table>
<p class="modNote">Highest strength of schedule among ranked teams. Across the whole table the hardest schedules belong to teams nobody is ranking, which is true and says nothing.</p></section>`;
}

function modConferenceTable(){
  const table=collegeRankingTable();
  const rows=(table?.rankings||[]).filter(r=>r.conference&&Number.isFinite(Number(r.rating)));
  if(rows.length<20)return '';
  const by={};
  rows.forEach(r=>{(by[r.conference]||=[]).push(r)});
  const conferences=Object.entries(by).filter(([,teams])=>teams.length>=4)
    .map(([name,teams])=>{
      const sorted=teams.slice().sort((a,b)=>Number(b.rating)-Number(a.rating));
      return {name,n:teams.length,mean:teams.reduce((sum,r)=>sum+Number(r.rating),0)/teams.length,
              best:Number(sorted[0].rating),leaders:sorted.slice(0,3).map(r=>r.name)};
    }).sort((a,b)=>b.mean-a.mean);
  if(conferences.length<4)return '';
  const body=conferences.map(c=>`<tr><td class="tsTeam">${esc(c.name)}<small class="confLeader" title="Top rated: ${esc(c.leaders.join(', '))}">Top: ${esc(c.leaders.join(' · '))}</small></td>`
    +`<td>${c.n}</td><td class="tsNum">${c.mean.toFixed(1)}</td>`
    +`<td class="tsNum">${c.best.toFixed(1)}</td></tr>`).join('');
  return `<section class="boardMod modTier"><header><h3>Conference table</h3><span>every rated league</span></header>
<table class="tsTable"><thead><tr><th>Conference</th><th>Teams</th><th>Mean</th><th>Best</th></tr></thead><tbody>${body}</tbody></table>
<p class="modNote">Every conference with at least four rated teams, ordered by its average opponent-adjusted rating. Best shows the league's highest-rated team.</p></section>`;
}


/* Conference parity.
   Conference strength already answers "which league is best" with a mean. This
   answers a question no other card asks: how far apart its own teams are. A
   league can be strong and lopsided (a couple of giants dragging the average up)
   or weaker and tightly packed, and the mean cannot tell those apart.

   Spread is the population standard deviation of the rated teams' ratings, with
   the best and worst in the same row so the number has something to stand on. */
function modConferenceParity(){
  const table=collegeRankingTable();
  const rows=(table?.rankings||[]).filter(r=>r.conference&&Number.isFinite(Number(r.rating)));
  if(rows.length<30)return '';
  const by={};
  rows.forEach(r=>{(by[r.conference]||=[]).push(r)});
  const stats=Object.entries(by).filter(([,v])=>v.length>=6).map(([name,v])=>{
    const mean=v.reduce((a,r)=>a+Number(r.rating),0)/v.length;
    const sd=Math.sqrt(v.reduce((a,r)=>a+(Number(r.rating)-mean)**2,0)/v.length);
    const sorted=v.slice().sort((a,b)=>Number(b.rating)-Number(a.rating));
    return {name,sd,top:Number(sorted[0].rating),bottom:Number(sorted[sorted.length-1].rating),
      topName:sorted[0].name,bottomName:sorted[sorted.length-1].name,n:v.length};
  }).sort((a,b)=>b.sd-a.sd);
  if(stats.length<3)return '';
  const body=stats.map(c=>
    `<tr><td class="tsTeam">${esc(c.name)}<small class="confLeader" title="Best: ${esc(c.topName)}; lowest: ${esc(c.bottomName)}">${esc(c.topName)} → ${esc(c.bottomName)}</small></td>`
    +`<td class="tsNum">${c.sd.toFixed(1)}</td>`
    +`<td>${c.top.toFixed(1)}</td><td>${c.bottom.toFixed(1)}</td></tr>`).join('');
  return `<section class="boardMod modParity"><header><h3>Conference parity</h3><span>every rated league</span></header>
<table class="tsTable"><thead><tr><th>Conference</th><th>Spread</th><th>Best</th><th>Worst</th></tr></thead><tbody>${body}</tbody></table>
<p class="modNote">Every conference with at least six rated teams, ordered from most to least spread. This measures how far apart a conference's own teams are, not how good it is.</p></section>`;
}

function collegeModules(){
  // Upset of the week leads: CSS columns fill in source order, so first in this
  // array is the top of the left column.
  const cards=[modUpsetOfWeek(),modTopPick(),modMyPicks(),modStatOfWeek(),modNotable(),modRatingScatter(),modConferenceStrength(),modBallot(),modTop25(),modUpsets(),modToughestSchedules(),modConferenceTable(),modConferenceParity()].filter(Boolean);
  return cards.length?`<div class="boardMods">${cards.join('')}</div>`:'';
}

/* Research page layout.
   One reading order instead of eleven equal cards: featured read, then the
   week's opportunities beside a narrow rail, then the rating/schedule chart,
   then conference context, then reference data. Nothing is dropped -- longer
   lists sit behind "View all" and the conference views behind tabs. Colour
   carries meaning only: green for the model's signal, red for a miss. */
function rsHead(label,aside){
  return `<div class="rsHead"><h2 class="seclbl">${label}</h2>${aside?`<span class="rsAside">${aside}</span>`:''}</div>`;
}
function rsShortName(name){
  // "Texas A&M Aggies" -> "Texas A&M". Nicknames are the last word, or two
  // for the handful of two-word nicknames.
  const s=String(name||'');
  const two=/(Crimson Tide|Blue Devils|Tar Heels|Yellow Jackets|Red Raiders|Horned Frogs|Golden Gophers|Nittany Lions|Fighting Irish|Sun Devils|Demon Deacons|Mean Green|Black Knights|Golden Hurricane|Scarlet Knights|Ragin' Cajuns|Red Wolves|Golden Eagles|Golden Flashes|Blue Raiders|Green Wave|Rainbow Warriors|Blue Hens|Thundering Herd|Red Storm)$/;
  const m=s.match(two);
  if(m)return s.slice(0,-m[0].length).trim()||s;
  const parts=s.split(' ');
  return parts.length>1?parts.slice(0,-1).join(' '):s;
}
function rsFeatured(){
  const fp=typeof featuredPick==='function'?featuredPick():null;
  if(!fp)return '';
  const {m,p}=fp;
  const model=Number(p.model_pct),market=Number(p.market_pct),gap=Number(p.edge_points);
  const home=m.home?.name||m.home||'',away=m.away?.name||m.away||'';
  const team=rsShortName(p.pick_name);
  const read=Number.isFinite(gap)&&Math.abs(gap)>=1
    ?`Matchday is ${Math.abs(gap)>=5?'meaningfully ':''}${gap<0?'cooler':'warmer'} on ${esc(team)} than the market this week.`
    :`Matchday and the market see this one about the same.`;
  const open=m.id?`<button type="button" class="rsLink" onclick="openMatchModal('${esc(String(m.id))}')">Open matchup <span aria-hidden="true">→</span></button>`:'';
  return `<section class="rsFeatured">`
    +`<div class="rsFeatMain"><span class="seclbl">Featured read</span>`
    +`<div class="rsFeatGame">${esc(rsShortName(away))} at ${esc(rsShortName(home))}</div>`
    +`<div class="rsFeatTeam">${esc(p.pick_name||'')}</div>`
    +`<div class="rsFeatPct"><b>${communityModelPctLabel(model)}</b><span>Model win probability</span></div></div>`
    +`<div class="rsFeatSide"><dl class="rsFeatNums">`
    +(Number.isFinite(market)?`<div><dt>Market</dt><dd>${market.toFixed(1)}%</dd></div>`:'')
    +(Number.isFinite(gap)?`<div><dt>Difference</dt><dd>${gap>0?'+':'−'}${Math.abs(gap).toFixed(1)} pts</dd></div>`:'')
    +`</dl><p class="rsFeatRead">${read}</p>`
    +`<p class="rsFine">A live read that moves until kickoff and is not graded. A wide model–market gap is context, not a signal.</p>${open}</div>`
    +`</section>`;
}
function rsUpsetRadar(){
  const u=(typeof MATCHDAY_BETBETTER_UPSET!=='undefined')?MATCHDAY_BETBETTER_UPSET:null;
  const calls=u&&u.available?bbSportRows((u.picks&&u.picks.length)?u.picks:[u.pick].filter(Boolean)):[];
  const board=(typeof MATCHDAY_BETBETTER_UPSETS!=='undefined'&&MATCHDAY_BETBETTER_UPSETS)||{};
  const shots=String(DATA.comp_key||'').toUpperCase()==='NCAAF'?(board.upsets||[]):[];
  if(!calls.length&&!shots.length)return '';
  const gaps=calls.map(p=>{
    const model=Number(p.model_pct),market=Number(p.market_pct),gap=Number(p.disagreement_points);
    const away=String(p.selection||'').toLowerCase()===String(p.away||'').toLowerCase();
    const status=typeof upsetStatusText==='function'?upsetStatusText(p,away):'';
    return `<li class="rsGapRow"><div class="rsGapGame"><b>${esc(rsShortName(p.selection))}</b>`
      +`<span>${esc(rsShortName(p.away))} at ${esc(rsShortName(p.home))}${status?` · ${esc(status)}`:''}</span></div>`
      +`<span class="rsNum"><b>${communityModelPctLabel(model)}</b><small>model</small></span>`
      +`<span class="rsNum"><b>${Number.isFinite(market)?market.toFixed(1)+'%':'—'}</b><small>market</small></span>`
      +`<span class="rsNum rsSignal"><b>${Number.isFinite(gap)?'+'+gap.toFixed(1):'—'}</b><small>gap</small></span></li>`;
  }).join('');
  const shotRow=x=>`<li class="rsShotRow" title="${esc(`${x.winner} ${x.winner_score}–${x.loser_score} ${x.loser} · ${String(x.played_on||'')}`)}">`
    +`<span><b>${esc(rsShortName(x.winner))}</b> beat ${esc(rsShortName(x.loser))} <em>${Number(x.winner_score)}–${Number(x.loser_score)}</em></span>`
    +`<span class="rsNum"><b>${Number.isFinite(Number(x.winner_pregame_pct))?Math.round(Number(x.winner_pregame_pct))+'%':'—'}</b></span></li>`;
  const more=shots.slice(3,8);
  return `<section class="rsBlock">${rsHead('Upset radar')}`
    +(gaps?`<div class="rsSub">Biggest model–market gaps this week</div><ul class="rsList">${gaps}</ul>`
      +`<p class="rsFine">Up to three calls a week${u.considered?`, from ${u.considered} games`:''}. To watch and grade, not recommended bets.</p>`:'')
    +(shots.length?`<div class="rsSub">Longest-shot winners this season <span>pregame chance</span></div><ul class="rsList">${shots.slice(0,3).map(shotRow).join('')}</ul>`
      +(more.length?`<details class="rsMore"><summary>View all <span aria-hidden="true">→</span></summary><ul class="rsList">${more.map(shotRow).join('')}</ul></details>`:''):'')
    +`</section>`;
}
function rsStat(){
  const table=collegeRankingTable();
  const rows=(table?.rankings||[]).filter(r=>Number.isFinite(Number(r.movement_since_preseason)));
  const riser=rows.slice().sort((a,b)=>Number(b.movement_since_preseason)-Number(a.movement_since_preseason))[0];
  if(riser&&Number(riser.movement_since_preseason)>0){
    return `<div class="rsRailBlock"><span class="seclbl">Stat of the week</span>`
      +`<b class="rsRailBig">${esc(riser.name)}</b>`
      +`<span class="rsRailSub"><em class="rsSignal">↑${Number(riser.movement_since_preseason)} spots</em> since the preseason, now #${riser.rank}</span></div>`;
  }
  const sos=(table?.rankings||[]).filter(r=>Number.isFinite(Number(r.sos))&&(r.rank||999)<=25);
  const hardest=sos.slice().sort((a,b)=>Number(b.sos)-Number(a.sos))[0];
  if(!hardest)return '';
  return `<div class="rsRailBlock"><span class="seclbl">Stat of the week</span><b class="rsRailBig">${esc(hardest.name)}</b>`
    +`<span class="rsRailSub">Toughest schedule in the top 25 · SoS ${Number(hardest.sos).toFixed(2)}</span></div>`;
}
function rsNotable(){
  const table=collegeRankingTable();
  const rows=(table?.rankings||[]).filter(r=>Number.isFinite(Number(r.rating)));
  if(!rows.length)return '';
  const best=(key,dir)=>rows.filter(r=>Number.isFinite(Number(r[key]))).slice().sort((a,b)=>dir*(Number(b[key])-Number(a[key])))[0];
  const off=best('adj_o',1),def=best('adj_d',-1);
  const g5=rows.filter(r=>r.tier&&String(r.tier)!=='power').slice().sort((a,b)=>Number(b.rating)-Number(a.rating))[0];
  const items=[];
  if(off)items.push(['Best offense',rsShortName(off.name),`${Number(off.adj_o).toFixed(1)} adj. points scored`]);
  if(def)items.push(['Best defense',rsShortName(def.name),`${Number(def.adj_d).toFixed(1)} adj. points allowed`]);
  if(g5)items.push(['Outside the power tier',rsShortName(g5.name),`${Number(g5.rating).toFixed(2)} rating · #${g5.rank}`]);
  if(!items.length)return '';
  return `<div class="rsRailBlock"><span class="seclbl">Notable</span><dl class="rsNotable">`
    +items.map(([k,v,d])=>`<div><dt>${esc(k)}</dt><dd><b>${esc(v)}</b><span>${esc(d)}</span></dd></div>`).join('')+`</dl></div>`;
}
function rsMyPicks(){
  const u=(typeof MATCHDAY_BETBETTER_USER_PICKS!=='undefined')?MATCHDAY_BETBETTER_USER_PICKS:null;
  const picks=bbSportRows(u?.picks||[]);
  if(!picks.length)return '';
  const ordered=picks.slice().sort((a,b)=>String(b.starts_at||'').localeCompare(String(a.starts_at||'')));
  const settled=picks.filter(p=>p.outcome===0||p.outcome===1);
  const wins=settled.filter(p=>p.outcome===1).length,agreed=settled.filter(p=>p.model_agreed).length;
  const pct=v=>v!=null&&Number.isFinite(Number(v))?communityModelPctLabel(Number(v)*100):'—';
  const row=p=>{
    const done=p.outcome===0||p.outcome===1,won=p.outcome===1;
    return `<li title="Model ${pct(p.model_probability)} · market ${pct(p.market_probability)} · model ${p.model_agreed?'agreed':'disagreed'}">`
      +`<span>${esc(rsShortName(p.selection))}</span><b class="${done?(won?'rsWin':'rsLoss'):'rsWait'}">${done?(won?'W':'L'):'·'}</b></li>`;
  };
  return `<div class="rsRailBlock"><span class="seclbl">@timurknowsball</span>`
    +`<b class="rsRailBig">${wins}–${settled.length-wins}</b><span class="rsRailSub">settled picks · ${agreed} of ${settled.length} agreed with Matchday</span>`
    +`<ul class="rsPicks">${ordered.slice(0,5).map(row).join('')}</ul>`
    +(ordered.length>5?`<details class="rsMore"><summary>All picks <span aria-hidden="true">→</span></summary><ul class="rsPicks">${ordered.slice(5).map(row).join('')}</ul></details>`:'')
    +`</div>`;
}
function rsScatter(){
  const table=collegeRankingTable();
  const rows=(table?.rankings||[]).filter(r=>Number.isFinite(Number(r.rating))&&Number.isFinite(Number(r.sos)));
  if(rows.length<12)return '';
  const W=1000,H=340,PL=40,PR=16,PT=14,PB=32;
  const xs=rows.map(r=>Number(r.sos)),ys=rows.map(r=>Number(r.rating));
  const x0=Math.min(...xs),x1=Math.max(...xs),y0=Math.min(...ys),y1=Math.max(...ys);
  const sx=v=>PL+((v-x0)/((x1-x0)||1))*(W-PL-PR);
  const sy=v=>H-PB-((v-y0)/((y1-y0)||1))*(H-PT-PB);
  const med=a=>{const b=a.slice().sort((m,n)=>m-n);return b[Math.floor(b.length/2)]};
  const mx=sx(med(xs)),my=sy(med(ys));
  // Label only the three highest-rated teams. Everything else is a tooltip:
  // labelling a cluster just stacks names on top of each other.
  const top=rows.slice().sort((a,b)=>Number(b.rating)-Number(a.rating)).slice(0,3);
  const dots=rows.map(r=>{
    const power=String(r.tier||'')==='power',hi=top.includes(r);
    return `<circle cx="${sx(Number(r.sos)).toFixed(1)}" cy="${sy(Number(r.rating)).toFixed(1)}" r="${hi?4.5:3}" class="${hi?'dotHi':power?'dotP':'dotG'}"><title>${esc(r.name)} — rating ${Number(r.rating).toFixed(2)}, SoS ${Number(r.sos).toFixed(2)}${r.conference?' · '+esc(r.conference):''}</title></circle>`;
  }).join('');
  let lastY=-99;
  const labels=top.slice().sort((a,b)=>sy(Number(a.rating))-sy(Number(b.rating))).map(r=>{
    let y=sy(Number(r.rating))+4;if(y-lastY<13)y=lastY+13;lastY=y;
    const x=sx(Number(r.sos)),left=x>W-180;
    return `<text class="rsLbl" x="${(left?x-8:x+8).toFixed(1)}" y="${y.toFixed(1)}" text-anchor="${left?'end':'start'}">${esc(rsShortName(r.name))}</text>`;
  }).join('');
  const anyG5=rows.some(r=>String(r.tier||'')&&String(r.tier)!=='power');
  return `<section class="rsBlock">${rsHead('Rating vs schedule',`${rows.length} teams`)}`
    +`<svg viewBox="0 0 ${W} ${H}" class="rsScatter" role="img" aria-label="Scatter plot of team rating against strength of schedule">`
    +`<line class="scAx" x1="${PL}" y1="${H-PB}" x2="${W-PR}" y2="${H-PB}"/><line class="scAx" x1="${PL}" y1="${PT}" x2="${PL}" y2="${H-PB}"/>`
    +`<line class="scMed" x1="${mx.toFixed(1)}" y1="${PT}" x2="${mx.toFixed(1)}" y2="${H-PB}"/><line class="scMed" x1="${PL}" y1="${my.toFixed(1)}" x2="${W-PR}" y2="${my.toFixed(1)}"/>`
    +`${dots}${labels}<text class="scAxLbl" x="${(W/2).toFixed(0)}" y="${H-8}" text-anchor="middle">strength of schedule →</text>`
    +`<text class="scAxLbl" transform="rotate(-90 12 ${(H/2).toFixed(0)})" x="12" y="${(H/2).toFixed(0)}" text-anchor="middle">rating →</text></svg>`
    +`<div class="rsLegend"><span><i class="dotKeyP"></i>Power</span>${anyG5?'<span><i class="dotKeyG"></i>Group of Five</span>':''}<span>Lines are medians · hover a dot for the team</span></div>`
    +`<p class="rsFine">Up and to the right is a strong rating earned against a hard schedule; up and to the left is a rating built on a soft one.</p></section>`;
}
function rsConfTab(btn,key){
  const box=btn.closest('.rsConf');if(!box)return;
  box.dataset.tab=key;
  box.querySelectorAll('.rsTabs button').forEach(b=>b.setAttribute('aria-pressed',String(b===btn)));
}
function rsConferences(){
  const table=collegeRankingTable();
  const rows=(table?.rankings||[]).filter(r=>r.conference&&Number.isFinite(Number(r.rating)));
  if(rows.length<20)return '';
  const by={};rows.forEach(r=>{(by[r.conference]||=[]).push(r)});
  const confs=Object.entries(by).filter(([,v])=>v.length>=4).map(([name,v])=>{
    const s=v.slice().sort((a,b)=>Number(b.rating)-Number(a.rating));
    const mean=v.reduce((a,r)=>a+Number(r.rating),0)/v.length;
    const sd=Math.sqrt(v.reduce((a,r)=>a+(Number(r.rating)-mean)**2,0)/v.length);
    return {name,n:v.length,mean,sd,best:s[0],worst:s[s.length-1],leaders:s.slice(0,3)};
  }).sort((a,b)=>b.mean-a.mean);
  if(confs.length<3)return '';
  const hi=Math.max(...confs.map(c=>c.mean)),lo=Math.min(...confs.map(c=>c.mean)),span=(hi-lo)||1;
  const parity=confs.filter(c=>c.n>=6).slice().sort((a,b)=>a.sd-b.sd);
  const strength=confs.map(c=>`<li><span>${esc(c.name)}</span><i class="rsBar"><b style="width:${Math.max(3,Math.round((c.mean-lo)/span*100))}%"></b></i><span class="rsNum"><b>${c.mean.toFixed(1)}</b></span><span class="rsNum rsMuted">${c.n}</span></li>`).join('');
  const parityRows=parity.map(c=>`<tr><td>${esc(c.name)}</td><td>${c.sd.toFixed(1)}</td><td>${Number(c.best.rating).toFixed(1)}</td><td>${Number(c.worst.rating).toFixed(1)}</td></tr>`).join('');
  const teamRows=confs.map(c=>`<tr><td>${esc(c.name)}</td><td class="rsLeft">${c.leaders.map(r=>esc(rsShortName(r.name))).join(' · ')}</td><td>${Number(c.best.rating).toFixed(1)}</td><td>${Number(c.worst.rating).toFixed(1)}</td></tr>`).join('');
  const balanced=parity[0],widest=parity[parity.length-1];
  return `<section class="rsBlock rsConf" data-tab="strength">${rsHead('Conference landscape')}`
    +`<div class="rsTabs" role="group" aria-label="Conference view">`
    +[['strength','Strength'],['parity','Parity'],['teams','Teams']].map(([k,l],i)=>`<button type="button" aria-pressed="${i===0}" onclick="rsConfTab(this,'${k}')">${l}</button>`).join('')+`</div>`
    +`<div class="rsPane" data-pane="strength"><div class="rsBarHead"><span>Conference</span><span></span><span>Mean rating</span><span>Teams</span></div><ul class="rsBars">${strength}</ul>`
    +`<dl class="rsSummary"><div><dt>Strongest</dt><dd>${esc(confs[0].name)}</dd></div>`
    +(balanced?`<div><dt>Most balanced</dt><dd>${esc(balanced.name)}</dd></div><div><dt>Widest spread</dt><dd>${esc(widest.name)}</dd></div>`:'')+`</dl></div>`
    +`<div class="rsPane" data-pane="parity"><div class="scTableWrap"><table class="scTable"><thead><tr><th>Conference</th><th>Spread</th><th>Best</th><th>Worst</th></tr></thead><tbody>${parityRows}</tbody></table></div>`
    +`<p class="rsFine">Spread is how far apart a conference's own teams are rated (standard deviation), not how good the conference is. Most balanced first.</p></div>`
    +`<div class="rsPane" data-pane="teams"><div class="scTableWrap"><table class="scTable"><thead><tr><th>Conference</th><th class="rsLeft">Top three</th><th>Best</th><th>Worst</th></tr></thead><tbody>${teamRows}</tbody></table></div></div>`
    +`</section>`;
}
function rsSchedules(){
  const table=collegeRankingTable();
  const rows=(table?.rankings||[]).filter(r=>Number.isFinite(Number(r.sos)));
  if(rows.length<10)return '';
  const pool=rows.filter(r=>(r.rank||999)<=40);
  const top=(pool.length>=10?pool:rows).slice().sort((a,b)=>Number(b.sos)-Number(a.sos));
  const row=(r,i)=>`<tr><td class="rsLeft"><span class="rsRank">${i+1}</span>${esc(rsShortName(r.name))}</td><td>#${r.rank}</td><td>${Number(r.sos).toFixed(2)}</td><td>${Number(r.rating).toFixed(2)}</td></tr>`;
  const head=`<thead><tr><th class="rsLeft">Team</th><th>Rank</th><th>SoS</th><th>Rating</th></tr></thead>`;
  return `<section class="rsBlock">${rsHead('Toughest schedules','Top 40 teams')}`
    +`<div class="scTableWrap"><table class="scTable">${head}<tbody>${top.slice(0,5).map(row).join('')}</tbody></table></div>`
    +(top.length>5?`<details class="rsMore"><summary>View all ${top.length} <span aria-hidden="true">→</span></summary><div class="scTableWrap"><table class="scTable"><tbody>${top.slice(5).map((r,i)=>row(r,i+5)).join('')}</tbody></table></div></details>`:'')
    +`</section>`;
}
function collegeResearchModules(){
  if(!['NCAAF','NCAAM'].includes(String(DATA?.comp_key||'').toUpperCase()))return '';
  const featured=rsFeatured(),radar=rsUpsetRadar();
  const rail=[rsStat(),rsNotable(),rsMyPicks()].filter(Boolean).join('');
  const lower=[rsScatter(),rsConferences(),rsSchedules()].filter(Boolean).join('');
  if(!featured&&!radar&&!rail&&!lower)return '';
  return `<section class="collegeResearch" aria-label="Weekly watch and college analysis">
    ${featured}
    <div class="rsGrid"><div class="rsMain">${radar}</div>${rail?`<aside class="rsRail" aria-label="This week">${rail}</aside>`:''}</div>
    ${lower}
  </section>`;
}
