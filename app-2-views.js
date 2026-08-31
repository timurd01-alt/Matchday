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
  const you=g.filter(p=>p.you_hit).length, model=g.filter(p=>p.model_hit).length;
  const beat=g.filter(p=>p.you_hit&&!p.model_hit).length; // you right, model wrong
  // current streak (most recent graded backwards)
  const chron=g.slice().sort((a,b)=>b.ts-a.ts);let streak=0;
  for(const p of chron){if(p.you_hit)streak++;else break;}
  return {n:g.length,you,model,beat,streak,
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
function communityPickProbs(m){
  const market=(m.markets||{})['1x2'];
  if(market&&market.home_pct!=null)return {h:+market.home_pct,d:+(market.draw_pct||0),a:+market.away_pct,source:'market'};
  const prediction=m.prediction||{};
  const model=prediction.regulation_probs||prediction.adjusted||prediction.blend||prediction.model;
  if(!model||model.h==null||model.a==null)return {h:null,d:null,a:null,source:'none'};
  return {h:+model.h,d:+(model.d||0),a:+model.a,source:'model'};
}
function btmChallenge(db){
  // a framed "where do you stand" prompt on the next unpicked upcoming match with a model+market split
  const picked=new Set(Object.keys(db.picks||{}));
  const cand=(DATA.matches||[]).filter(m=>isCommunityPickOpen(m)&&m.prediction&&communityPickProbs(m)&&!picked.has(String(m.id)));
  if(!cand.length)return null;
  // pick the one where model disagrees most with the market favorite (most interesting call)
  const score=m=>{const x=communityPickProbs(m);if(x.source!=='market')return 0;const mk={h:x.h,d:x.d,a:x.a};
    const mfav=Object.keys(mk).reduce((a,b)=>mk[b]>mk[a]?b:a);
    return officialPrediction(m).side!==mfav?2:1;};
  cand.sort((a,b)=>score(b)-score(a)||(a.kickoff||'').localeCompare(b.kickoff||''));
  const m=cand[0],x=communityPickProbs(m),mk={h:x.h,d:x.d,a:x.a};
  const mfav=Object.keys(mk).reduce((a,b)=>mk[b]>mk[a]?b:a);
  const nm=s=>s==='h'?m.home.name:s==='a'?m.away.name:'a draw';
  const official=officialPrediction(m),disagree=official.side!==mfav;
  return {id:m.id,home:m.home.name,away:m.away.name,
    line:x.source!=='market'
      ?`The model likes <b>${esc(nm(official.side))}</b> at ${official.confidence}%. No bookmaker line is available, so this pick will be graded without the market benchmark.`
      :disagree
      ?`The model likes <b>${esc(nm(official.side))}</b>, but the market favors <b>${esc(nm(mfav))}</b>. Who's right?`
      :`The model and market agree on <b>${esc(nm(official.side))}</b> (${official.confidence}%). Fade them or follow?`};
}
function pickBtm(id,side){if(submitPick(id,side)){}}
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
  return `<div class="acctRow"><span class="acctState">Playing as a guest — clearing this browser loses your handle and record. Sign in to keep them.</span>
    <span class="acctBtns">${buttons}</span>${note}</div>`;
}
function renderCommunity(){ensureHandle();const host=$('#view-community');const fullDb=btmGrade();const db=btmScoped(fullDb);const s=btmStats(db);
  const scopeName=communityScope()==='ALL'?'All sports':(DATA.competition||DATA.comp_key||'This sport');
  const eligible=(DATA.matches||[]).filter(m=>isCommunityPickOpen(m)).sort((a,b)=>(a.kickoff||'').localeCompare(b.kickoff||''));
  const firstKick=eligible.length?kickMs(eligible[0]):0;
  // A missing market can expose an entire season at once. Show the next
  // fixture slate instead of rendering hundreds of model-only cards.
  const open=eligible.filter(m=>communityPickProbs(m).source==='market'||kickMs(m)<=firstKick+4*864e5).slice(0,40);
  const picks=db.picks||{};
  let h=`<div class="vhead">Community &middot; ${esc(scopeName)}</div>
  <div class="banner"><b>Games open seven days before kickoff.</b> Pick any listed matchup before it starts. When available, the model and market are graded beside you.</div>
  ${renderWeeklyAwards()}
  <div class="status-grid">
   <div class="statuscard ${s.you>=s.model&&s.n?'ok':'info'}"><span class="slbl">Your record</span><div class="sval">${s.you}/${s.n||0}</div><div class="hint">${s.n?Math.round(s.you/s.n*100)+'% correct':'no graded picks yet'}</div></div>
   <div class="statuscard info"><span class="slbl">Model record</span><div class="sval">${s.model}/${s.n||0}</div><div class="hint">the opponent you are chasing</div></div>
   <div class="statuscard ${s.beat?'ok':'info'}"><span class="slbl">Model beaten</span><div class="sval">${s.beat}</div><div class="hint">you right when the model was wrong</div></div>
   <div class="statuscard info"><span class="slbl">Streak</span><div class="sval">${s.streak}${s.streak>=3?' &#128293;':''}</div><div class="hint">${s.pending} awaiting result</div></div>
  </div>`;
  // head-to-head insight: how often you agreed with the model, and who won when you split
  if(s.n>=3){
    const g=Object.values(picks).filter(p=>p.result);
    const withModel=g.filter(p=>p.pick===p.modelPick).length;
    const split=g.filter(p=>p.pick!==p.modelPick);
    const splitWins=split.filter(p=>p.you_hit&&!p.model_hit).length;
    h+=`<div class="h2hbar"><div class="h2hitem"><b>${Math.round(withModel/g.length*100)}%</b><span>of your picks matched the model</span></div><div class="h2hitem"><b>${splitWins}/${split.length||0}</b><span>you won when you went your own way</span></div><div class="h2hitem"><b>${s.n?Math.round((s.you-s.model)/s.n*100):0>0?'+':''}${s.you-s.model}</b><span>your net record vs the model</span></div></div>`;
  }
  const badges=btmBadges(s,db);
  if(badges.length)h+=`<div class="seclbl" style="margin-top:16px">Badges</div><div class="fchips">`+badges.map(b=>`<span class="fchip good" title="${esc(b[1])}">${esc(b[0])}</span>`).join('')+`</div>`;
  // personal analytics
  const an=btmAnalytics(db);
  if(an){
    h+=`<div class="seclbl" style="margin-top:20px">Your tendencies</div><div class="anGrid">`;
    if(an.favN>=3)h+=`<div class="anCard"><div class="anPct">${an.favPct}%</div><div class="anLbl">on favorites <span>(${an.favN})</span></div></div>`;
    if(an.dogN>=3)h+=`<div class="anCard"><div class="anPct">${an.dogPct}%</div><div class="anLbl">on underdogs <span>(${an.dogN})</span></div></div>`;
    if(an.splitN>=3)h+=`<div class="anCard"><div class="anPct">${an.splitPct}%</div><div class="anLbl">when you defy the model <span>(${an.splitN})</span></div></div>`;
    if(an.withN>=3)h+=`<div class="anCard"><div class="anPct">${an.withPct}%</div><div class="anLbl">when you side with it <span>(${an.withN})</span></div></div>`;
    h+=`</div>`;
    if(an.comps.length>=2){h+=`<div class="anByComp">`+an.comps.map(c=>`<div class="anCompRow"><span>${esc(c.comp)}</span><div class="anBar"><div style="width:${c.pct}%"></div></div><span>${c.pct}% <i>(${c.n})</i></span></div>`).join('')+`</div>`;}
  }
  // streak seasons
  const seasons=btmSeason(db);
  if(seasons&&seasons.length){
    h+=`<div class="seclbl" style="margin-top:20px">Seasons <span class="faintline" style="font-weight:400">· 4-week runs</span></div>`;
    h+=seasons.slice(0,6).map(s=>`<div class="seasonRow ${s.current?'live':''}"><span class="seasonName">${s.current?'Current season':'Season '+(s.n+1)}</span><span class="seasonRec">you ${s.you} · model ${s.model} <i>of ${s.total}</i></span>${s.current?'<span class="seasonTag">current</span>':(s.you>s.model?'<span class="seasonTag win">won</span>':s.you<s.model?'<span class="seasonTag loss">lost</span>':'<span class="seasonTag">tied</span>')}</div>`).join('');
  }
  const ch=btmChallenge(db);
  if(ch)h+=`<div class="challengeCard" onclick="openMatchModal('${ch.id}')"><div class="challengeTag">Today's call</div><div class="challengeMatch">${esc(ch.home)} v ${esc(ch.away)}</div><div class="challengeLine">${ch.line}</div><div class="challengeHint">tap to make your pick →</div></div>`;
  h+=`<div class="seclbl" style="margin-top:18px">Make your picks</div>`;
  if(!open.length)h+=`<div class="empty">No games are inside the seven-day pick window yet.<br><span class="faintline">They appear automatically one week before kickoff.</span></div>`;
  open.forEach(m=>{const p=picks[m.id],x=communityPickProbs(m),official=officialPrediction(m);
    const sideBtn=(side,label,pct)=>{const locked=p&&p.pick===side;const disabled=p?'disabled':'';
      return `<button class="btmbtn ${locked?'locked':''}" ${disabled} onclick="pickBtm('${m.id}','${side}')">${esc(label)}${pct!=null?` <b>${pct}%</b>`:''}</button>`;};
    h+=`<div class="btmcard"><div class="btmmatch">${esc(m.home.name)} <span class="mvvs">v</span> ${esc(m.away.name)}${p?`<span class="btmlocked">your pick: ${esc(p.pick==='h'?m.home.code:p.pick==='a'?m.away.code:'Draw')}</span>`:''}</div>
      <div class="btmrow">${sideBtn('h',m.home.code||'Home',x.h)}${x.d>0?sideBtn('d',t('Draw'),x.d):''}${sideBtn('a',m.away.code||'Away',x.a)}</div>
      <div class="btmmeta">${official.side?`model: <b>${esc(official.name)}</b> ${official.confidence??'—'}% &middot; `:'model pick pending &middot; '}${x.source==='model'?'model probabilities · market unavailable · ':x.source==='none'?'probabilities pending · ':''}${p?'locked — graded when final':'pick before kickoff to play'}</div></div>`;});
  const graded=Object.values(picks).filter(p=>p.result).sort((a,b)=>b.ts-a.ts);
  if(graded.length){h+=`<div class="seclbl" style="margin-top:18px">Your results</div>`+graded.slice(0,20).map(p=>{
    const nm=p.pick==='h'?p.code.h:p.pick==='a'?p.code.a:'Draw';
    return `<div class="btmres ${p.you_hit?'hit':'miss'}"><span>${esc(p.home)} v ${esc(p.away)}</span><span class="btmpick">you: ${esc(nm)} ${p.you_hit?'&#10003;':'&#10007;'}</span><span class="btmvs ${p.model_hit?'mok':'mno'}">model ${p.model_hit?'&#10003;':'&#10007;'}</span></div>`;}).join('');}
  // leaderboard section (only when configured)
  if(LEADERBOARD_URL){
    const hn=myHandle();
    const period=lbPeriod();
    const tab=(p,label)=>`<button class="lbTab ${p===period?'on':''}" onclick="setLbPeriod('${p}')">${label}</button>`;
    h+=`<div class="seclbl" style="margin-top:20px">Global leaderboard</div>`;
    h+=`<div class="btmmeta" style="margin-bottom:8px">You appear as <b>${esc(hn)}</b> — assigned automatically so the board stays free of offensive names.${canReshuffleHandle()?` <button class="btmbtn" style="margin-left:8px;padding:3px 9px;font-size:var(--fs-sm)" onclick="reshuffleHandle()">Reshuffle (1 left)</button>`:''}</div>`;
    h+=renderAccountRow();
    h+=`<div class="lbTabs">${tab('all','All time')}${tab('week','This week')}${tab('month','This month')}</div>`;
    h+=`<div id="lbBoard" class="empty">Loading board…</div>`;
  } else {
    h+=`<div class="seclbl" style="margin-top:20px">Global leaderboard</div><div class="empty">Coming soon — compete with other players once the shared board launches.</div>`;
  }
  host.innerHTML=h;
  if(LEADERBOARD_URL&&myHandle()){fetchLeaderboard(lbPeriod()).then(board=>{const el=$('#lbBoard');if(!el)return;
    const empties={all:'No ranked players yet — be the first with 10+ graded picks.',
      week:'No one has 3+ graded picks this week yet — check back soon.',
      month:'No one has 3+ graded picks this month yet — check back soon.'};
    if(!board||!board.length){el.innerHTML=empties[lbPeriod()]||empties.all;return;}
    el.className='';el.innerHTML=board.map((r,i)=>`<div class="lbrow"><span class="lbrk">${i+1}</span><span class="lbname">${esc(r.handle)}</span><span class="lbrec">${r.hits}/${r.graded}</span><span class="lbpct">${r.graded?Math.round(r.hits/r.graded*100):0}%</span></div>`).join('');});}
}

/* ===== Matchup Sandbox — hypothetical same-competition matchups ===========
   Client-side port of predict()/predict_totals()'s standings-based strength
   calc (points/goal-diff/form/preseason class rating/home-advantage --
   no injuries or market data, since there's no real scheduled game to
   attach any of that to). Runs entirely in the browser against
   DATA.standings, or DATA.matches when standings are empty (preseason). */
const SANDBOX_TWO_WAY=new Set(['nfl','ncaaf','ncaam','mlb','nhl','nba']);
// Same full-season game counts predict() uses server-side, so a team's
// record/form don't get full-confidence weight off a handful of games --
// and season_stale (provider had no current-season sample yet and fell
// back to last season's final record) dents it further, matching the
// backend fix for the same P4-loses-class-edge-to-a-stale-record bug.
const SANDBOX_FULL_GAMES={nfl:10,ncaaf:10,nba:20,ncaam:18,mlb:30,nhl:20};
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
    const msg=String(DATA.comp_key||'').toUpperCase()==='ALL'
      ?'Pick a specific sport (not "All sports") to build a matchup — standings aren\'t loaded for a merged view.'
      :'No teams to build a matchup with yet — check back once fixtures are scheduled for this sport.';
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
    <div class="banner"><b>Build any matchup.</b> Pick two ${esc(DATA.competition||'')} teams and see what the model — using this season's real standings — thinks.</div>
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
  host.innerHTML=`<div class="vhead">Insights</div><div class="banner"><b>Matchday's own recaps.</b> Auto-generated weekly from the model's own graded picks — hit rate, calibration, and this week's storylines. Not third-party news. Want the tactics behind the numbers instead? See the <a href="content.html" style="color:inherit;text-decoration:underline">Content hub</a>.</div><div class="seclbl" style="margin-top:16px">Research</div><div class="hint" style="margin-bottom:8px">How the model itself performs: methodology notes and measured results.</div><div id="researchList" class="insightsList"><div class="empty">Loading…</div></div><div class="seclbl" style="margin-top:20px">Weekly recaps</div><div class="hint" style="margin-bottom:8px">Completed scorecards built from verified, locked picks.</div><div id="insightsList" class="insightsList"><div class="empty">Loading…</div></div><div class="seclbl" style="margin-top:20px">Analysis &amp; features</div><div class="hint" style="margin-bottom:8px">Opening boards, availability desks, simulations, and methodology notes.</div><div id="featuresList" class="insightsList"><div class="empty">Loading…</div></div>`;
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
function renderCustomize(){const host=$('#view-customize');host.innerHTML=`<div class="vhead">Customize</div><div class="banner"><b>Personalize your analysis desk.</b> These settings save locally in this browser/app window.</div><div class="settings-grid"><div class="setcard"><label>Accent color</label><select onchange="updateSetting('accent',this.value)">${opt('orange','Matchday orange',SETTINGS.accent)}${opt('blue','Electric blue',SETTINGS.accent)}${opt('green','Pitch green',SETTINGS.accent)}${opt('red','Signal red',SETTINGS.accent)}${opt('purple','Night purple',SETTINGS.accent)}</select><div class="hint">Changes highlights, buttons and the brand dot.</div></div><div class="setcard"><label>Language</label><select onchange="setLang(this.value)">${lopt('','English',LANG)}${lopt('es','Español',LANG)}${lopt('fr','Français',LANG)}${lopt('de','Deutsch',LANG)}${lopt('pt','Português',LANG)}${lopt('ru','Русский',LANG)}</select><div class="hint">Translates the interface. Match data stays as provided by sources.</div></div><div class="setcard"><label>Card density</label><select onchange="updateSetting('density',this.value)">${opt('compact','Compact',SETTINGS.density)}${opt('normal','Normal',SETTINGS.density)}${opt('spacious','Spacious',SETTINGS.density)}</select><div class="hint">Compact fits more matches on screen; spacious gives each card more room.</div></div><div class="setcard"><label>Panel style</label><select onchange="updateSetting('panel',this.value)">${opt('glass','Soft glass',SETTINGS.panel)}${opt('flat','Flat dark',SETTINGS.panel)}</select><div class="hint">Flat mode is lighter on older laptops.</div></div><div class="setcard"><label>Default tab</label><select onchange="updateSetting('defaultView',this.value)">${['matches','groups','title','edge','bracket','third','news','status','updates'].map(v=>opt(v,v[0].toUpperCase()+v.slice(1),SETTINGS.defaultView)).join('')}</select><div class="hint">Selected when the page starts.</div></div><div class="setcard"><label>Refresh rate</label><select onchange="updateSetting('refresh',this.value)">${opt(900,'Every 15 minutes',SETTINGS.refresh)}${opt(1800,'Every 30 minutes',SETTINGS.refresh)}${opt(3600,'Every 60 minutes',SETTINGS.refresh)}</select><div class="hint">Reloads published analysis; provider refreshes run hourly.</div></div><div class="setcard"><label>Display</label><div class="switchrow"><span>Right insight panel</span><input type="checkbox" ${checked(SETTINGS.showInsight)} onchange="updateSetting('showInsight',this.checked)"></div><div class="switchrow" style="margin-top:10px"><span>Match detail panels</span><input type="checkbox" ${checked(SETTINGS.showDetails)} onchange="updateSetting('showDetails',this.checked)"></div></div></div><div class="btnline"><button class="actionbtn" onclick="resetSettings()">Reset settings</button><button class="actionbtn" onclick="setView('status')">Check app status</button><button class="actionbtn" onclick="startTour()">Replay tour</button></div>`}
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
     model-market gap predicted WORSE results -- the sign is inverted -- so the
     top pick is chosen by model probability and the gap is shown as context
     with its warning attached.
   * A poll for a season that has not started is not a poll about this season.
     season_in_progress drives the caveat, and the engine's own `note` is
     rendered rather than paraphrased.
---------------------------------------------------------------------------- */
function collegeRankingTable(){
  const key=(typeof currentSportKey==='function'?currentSportKey():'')||'';
  if(key==='ncaam')return typeof MATCHDAY_NCAAM_RANKINGS!=='undefined'?MATCHDAY_NCAAM_RANKINGS:null;
  return typeof MATCHDAY_CFB_RANKINGS!=='undefined'?MATCHDAY_CFB_RANKINGS:null;
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
  if(row?.previous_rank==null)return '<i class="mvNew" title="first edition of this poll">new</i>';
  return '';
}
function modTop25(){
  const table=collegeRankingTable();
  const rows=(table?.top25||[]).slice(0,25);
  if(!rows.length)return '';
  const stale=table.season_in_progress===false;
  const caption=stale
    ?`<div class="modWarn">Projection — the season has not started. This ranks the completed season.</div>`
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
  return `<section class="boardMod modTop25"><header><h3>Top 25</h3>`
    +`<span>${esc(table.basis?.label||'Model rating')}</span></header>${caption}`
    +`<ol class="modList">${body}</ol>`
    +`<p class="modNote">${esc(String(table.note||'').replace(/\.\./g,'.'))}</p>`+`<p class="modNote">Full table of every rated team on the Rankings tab.</p></section>`;
}
function modTopScores(){
  let done=(DATA.matches||[]).filter(m=>m.status==='FINISHED'
    &&Number.isFinite(Number(m.score?.home))&&Number.isFinite(Number(m.score?.away)));
  // If the fixture feed carries no finals -- which it does not while the
  // provider quota is spent -- read the handoff's own results instead.
  if(!done.length&&typeof MATCHDAY_BETBETTER_RESULTS!=='undefined'){
    done=MATCHDAY_BETBETTER_RESULTS.slice()
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
function modTopPick(){
  // Two sources on purpose. A scheduled build attaches the pick to the fixture;
  // a push build does not run the fetch that does so. The handoff is committed,
  // so fall back to it rather than let the card blink out of existence
  // depending on which kind of deploy shipped last.
  const attached=(DATA.matches||[]).filter(m=>m.status==='UPCOMING'&&m.betbetter_pick)
    .map(m=>({m,p:m.betbetter_pick}));
  const baked=attached.length?[]:(typeof MATCHDAY_BETBETTER_PICKS!=='undefined'?MATCHDAY_BETBETTER_PICKS:[])
    .filter(p=>new Date(p.kickoff)>new Date())
    .map(p=>({m:{home:{name:p.home},away:{name:p.away}},p}));
  const picks=attached.concat(baked)
    .filter(x=>Number.isFinite(Number(x.p.model_pct)))
    // Sorted by the model's own probability. Deliberately NOT by edge_points.
    .sort((a,b)=>Number(b.p.model_pct)-Number(a.p.model_pct));
  if(!picks.length)return '';
  const {m,p}=picks[0];
  const gap=Number(p.edge_points);
  return `<section class="boardMod modPick"><header><h3>Top pick</h3><span>live shadow read</span></header>`
    +`<div class="modPickTeam">${esc(p.pick_name||'')}</div>`
    +`<div class="modPickGame">${esc(m.home?.name||m.home||'')} v ${esc(m.away?.name||m.away||'')}</div>`
    +`<div class="modPickBar"><i style="width:${Math.max(0,Math.min(100,Number(p.model_pct)))}%"></i></div>`
    +`<div class="modPickNums"><b>${Number(p.model_pct).toFixed(1)}%</b> model`
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
    .sort((a,b)=>b.mean-a.mean).slice(0,8);
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
    +(withheld?`<p class="modNote">${withheld} team${withheld===1?' is':'s are'} held out of the ranking — ratings earned mostly against FCS opposition, which the table would otherwise flatter.</p>`:'')
    +`</section>`;
}


/* Trim the ranking card to fit, rather than to a number someone liked.
   The board is three CSS columns and a column is as tall as what is in it, so
   the ranking card -- the only one whose length is arbitrary -- is what decides
   whether the other columns end in mid-air. Rather than guess a row count, the
   other cards are measured after layout and the list is cut to the largest
   number of rows that still fits inside the tallest of them.

   Everything cut is still reachable: the full rated table is on the Rankings
   tab, and the card says so. */
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
  // A ranking shorter than ten is not a ranking; longer than what we rendered
  // is not available. Between those, the layout decides.
  const keep=Math.max(10,Math.min(items.length,fits));
  if(keep>=items.length)return;
  items.slice(keep).forEach(el=>el.remove());
  const note=card.querySelector('.modNote:last-of-type');
  if(note)note.textContent=`Top ${keep} shown. Full table of every rated team on the Rankings tab.`;
}

/* The week's upset call.
   Editorial, and labelled that way in the card rather than only in a tooltip.
   The engine ships a caveat with this pick saying disagreement of exactly this
   kind has historically predicted WORSE results on graded college samples, and
   that it must never be published as a recommended bet. That text is rendered
   as written -- paraphrasing a warning is how warnings get softened. */
function modUpsetOfWeek(){
  const u=(typeof MATCHDAY_BETBETTER_UPSET!=='undefined')?MATCHDAY_BETBETTER_UPSET:null;
  const p=u&&u.available?u.pick:null;
  if(!p)return '';
  const model=Number(p.model_pct),market=Number(p.market_pct);
  return `<section class="boardMod modUpset"><header><h3>Upset of the week</h3><span>editorial</span></header>
<div class="modPickTeam">${esc(p.selection||'')}</div>
<div class="modPickGame">${esc(p.away||'')} at ${esc(p.home||'')}</div>
<div class="upsetBars">
  <div><span>model</span><i style="width:${Math.max(2,Math.min(100,model))}%"></i><b>${Number.isFinite(model)?model.toFixed(1)+'%':'—'}</b></div>
  <div class="mkt"><span>market</span><i style="width:${Math.max(2,Math.min(100,market))}%"></i><b>${Number.isFinite(market)?market.toFixed(1)+'%':'—'}</b></div>
</div>
<div class="modPickNums">${esc(u.basis||'')} · ${u.considered||0} games considered</div>
<div class="modWarn">${esc(u.caveat||'')}</div></section>`;
}

/* My picks, against the model and the market.
   Three honesty constraints ship with this data and all three are obeyed:
   `reportable` false means the sample is too small to state a record as though
   it meant something; `excluded` counts picks recorded after kickoff, which are
   listed rather than dropped so nothing disappears silently; and `note` says
   these are predictions with no stake, price or balance attached. */
function modMyPicks(){
  const u=(typeof MATCHDAY_BETBETTER_USER_PICKS!=='undefined')?MATCHDAY_BETBETTER_USER_PICKS:null;
  const picks=(u?.picks||[]).filter(p=>p.before_kickoff);
  if(!picks.length)return '';
  const rec=u.record||{};
  const pct=v=>Number.isFinite(Number(v))?(Number(v)*100).toFixed(0)+'%':'—';
  const rows=picks.slice().sort((a,b)=>String(b.starts_at||'').localeCompare(String(a.starts_at||''))).map(p=>{
    const done=p.outcome===0||p.outcome===1;
    const won=p.outcome===1;
    return `<li><span class="modTeam">${esc(p.selection||'')}</span>`
      +`<span class="mpNum" title="my pick vs the model's frozen figure">${pct(p.model_probability)}</span>`
      +`<span class="mpNum mkt" title="market probability">${pct(p.market_probability)}</span>`
      +`<i class="mpFlag ${p.model_agreed?'agree':'differ'}" title="${p.model_agreed?'the model agreed':'the model disagreed'}">${p.model_agreed?'with':'vs'}</i>`
      +`<i class="mpOut ${done?(won?'won':'lost'):'wait'}">${done?(won?'W':'L'):'·'}</i></li>`;
  }).join('');
  const excluded=Number(u?.excluded?.recorded_after_kickoff)||0;
  const record=u.reportable
    ? `<div class="modStatSub"><b>${rec.wins||0}\u2013${rec.losses||0}</b> on graded picks · model agreed on ${rec.model_agreed_on||0}</div>`
    : `<div class="modStatSub"><b>${rec.wins||0}\u2013${rec.losses||0}</b> so far \u2014 too few graded picks to call it a record</div>`;
  return `<section class="boardMod modMine"><header><h3>My picks</h3><span>vs model &amp; market</span></header>
${record}
<div class="mpHead"><span>pick</span><span>model</span><span>market</span></div>
<ul class="modList">${rows}</ul>
${excluded?`<p class="modNote">${excluded} pick${excluded===1?'':'s'} recorded after kickoff are excluded from the record. Listed as excluded rather than removed, so nothing disappears without saying why.</p>`:''}
<p class="modNote">${esc(u.note||'')}</p></section>`;
}
function collegeModules(){
  const cards=[modTopPick(),modUpsetOfWeek(),modMyPicks(),modStatOfWeek(),modNotable(),modRatingScatter(),modConferenceStrength(),modTop25(),modTopScores()].filter(Boolean);
  return cards.length?`<div class="boardMods">${cards.join('')}</div>`:'';
}
