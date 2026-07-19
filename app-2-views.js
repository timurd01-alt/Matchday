function btmGrade(){ // fold finished results into the record
  const db=btmLoad();db.picks=db.picks||{};let changed=false;
  (DATA.matches||[]).forEach(m=>{const p=db.picks[m.id];
    if(p&&!p.result&&m.status==='FINISHED'&&m.score){
      const _r=(m.score.reg&&m.score.reg.home!=null)?m.score.reg:m.score;const res=_r.home>_r.away?'h':_r.home<_r.away?'a':'d';
      p.result=res;p.you_hit=(p.pick===res);
      p.model_hit=(p.modelPick===res);p.market_hit=(p.marketPick===res);changed=true;}});
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
function btmChallenge(db){
  // a framed "where do you stand" prompt on the next unpicked upcoming match with a model+market split
  const picked=new Set(Object.keys(db.picks||{}));
  const cand=(DATA.matches||[]).filter(m=>m.status==='UPCOMING'&&m.prediction&&m.markets&&(m.markets['1x2']||{}).home_pct!=null&&!picked.has(String(m.id)));
  if(!cand.length)return null;
  // pick the one where model disagrees most with the market favorite (most interesting call)
  const score=m=>{const x=m.markets['1x2'];const mk={h:x.home_pct,d:x.draw_pct,a:x.away_pct};
    const mfav=Object.keys(mk).reduce((a,b)=>mk[b]>mk[a]?b:a);
    return m.prediction.pick!==mfav?2:1;};
  cand.sort((a,b)=>score(b)-score(a)||(a.kickoff||'').localeCompare(b.kickoff||''));
  const m=cand[0];const x=m.markets['1x2'];const mk={h:x.home_pct,d:x.draw_pct,a:x.away_pct};
  const mfav=Object.keys(mk).reduce((a,b)=>mk[b]>mk[a]?b:a);
  const nm=s=>s==='h'?m.home.name:s==='a'?m.away.name:'a draw';
  const disagree=m.prediction.pick!==mfav;
  return {id:m.id,home:m.home.name,away:m.away.name,
    line:disagree
      ?`The model likes <b>${esc(nm(m.prediction.pick))}</b>, but the market favors <b>${esc(nm(mfav))}</b>. Who's right?`
      :`The model and market agree on <b>${esc(nm(m.prediction.pick))}</b> (${m.prediction.confidence}%). Fade them or follow?`};
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
function renderCommunity(){const host=$('#view-community');const fullDb=btmGrade();const db=btmScoped(fullDb);const s=btmStats(db);
  const scopeName=communityScope()==='ALL'?'All sports':(DATA.competition||DATA.comp_key||'This sport');
  const open=(DATA.matches||[]).filter(m=>m.status==='UPCOMING'&&m.markets&&m.markets['1x2']&&m.prediction).sort((a,b)=>(a.kickoff||'').localeCompare(b.kickoff||''));
  const picks=db.picks||{};
  let h=`<div class="vhead">Community &middot; ${esc(scopeName)}</div>
  <div class="banner"><b>Lock your pick before kickoff.</b> ${communityScope()==='ALL'?'Your combined record across every sport is shown here.':'This record and its picks belong only to '+esc(scopeName)+'.'} You, the model and the market are graded side by side.</div>
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
    h+=seasons.slice(0,6).map(s=>`<div class="seasonRow ${s.current?'live':''}"><span class="seasonName">${s.current?'Current season':'Season '+(s.n+1)}</span><span class="seasonRec">you ${s.you} · model ${s.model} <i>of ${s.total}</i></span>${s.current?'<span class="seasonTag">live</span>':(s.you>s.model?'<span class="seasonTag win">won</span>':s.you<s.model?'<span class="seasonTag loss">lost</span>':'<span class="seasonTag">tied</span>')}</div>`).join('');
  }
  const ch=btmChallenge(db);
  if(ch)h+=`<div class="challengeCard" onclick="openMatchModal('${ch.id}')"><div class="challengeTag">Today's call</div><div class="challengeMatch">${esc(ch.home)} v ${esc(ch.away)}</div><div class="challengeLine">${ch.line}</div><div class="challengeHint">tap to make your pick →</div></div>`;
  h+=`<div class="seclbl" style="margin-top:18px">Make your picks</div>`;
  if(!open.length)h+=`<div class="empty">No upcoming matches with a model line right now.<br><span class="faintline">New fixtures appear here before kickoff — lock a pick and see if you can out-read the model.</span></div>`;
  open.forEach(m=>{const p=picks[m.id];const x=m.markets['1x2'];
    const sideBtn=(side,label,pct)=>{const locked=p&&p.pick===side;const disabled=p?'disabled':'';
      return `<button class="btmbtn ${locked?'locked':''}" ${disabled} onclick="pickBtm('${m.id}','${side}')">${esc(label)}${pct!=null?` <b>${pct}%</b>`:''}</button>`;};
    h+=`<div class="btmcard"><div class="btmmatch">${esc(m.home.name)} <span class="mvvs">v</span> ${esc(m.away.name)}${p?`<span class="btmlocked">your pick: ${esc(p.pick==='h'?m.home.code:p.pick==='a'?m.away.code:'Draw')}</span>`:''}</div>
      <div class="btmrow">${sideBtn('h',m.home.code||'Home',x.home_pct)}${x.draw_pct!=null&&x.draw_pct>0?sideBtn('d',t('Draw'),x.draw_pct):''}${sideBtn('a',m.away.code||'Away',x.away_pct)}</div>
      <div class="btmmeta">model: <b>${esc(m.prediction.pick_name)}</b> ${m.prediction.confidence}% &middot; ${p?'locked — graded at full time':'pick before kickoff to play'}</div></div>`;});
  const graded=Object.values(picks).filter(p=>p.result).sort((a,b)=>b.ts-a.ts);
  if(graded.length){h+=`<div class="seclbl" style="margin-top:18px">Your results</div>`+graded.slice(0,20).map(p=>{
    const nm=p.pick==='h'?p.code.h:p.pick==='a'?p.code.a:'Draw';
    return `<div class="btmres ${p.you_hit?'hit':'miss'}"><span>${esc(p.home)} v ${esc(p.away)}</span><span class="btmpick">you: ${esc(nm)} ${p.you_hit?'&#10003;':'&#10007;'}</span><span class="btmvs ${p.model_hit?'mok':'mno'}">model ${p.model_hit?'&#10003;':'&#10007;'}</span></div>`;}).join('');}
  // leaderboard section (only when configured)
  if(LEADERBOARD_URL){
    const hn=myHandle();
    h+=`<div class="seclbl" style="margin-top:20px">Global leaderboard</div>`;
    if(!hn){h+=`<div class="btmcard"><div class="btmmeta" style="margin-bottom:8px">Pick a handle to appear on the shared board:</div><input id="handleInput" class="handleInput" maxlength="24" placeholder="your handle"><button class="btmbtn" style="margin-top:8px" onclick="setHandle(document.getElementById('handleInput').value)">Save handle</button></div>`;}
    else{h+=`<div class="btmmeta" style="margin-bottom:8px">You appear as <b>${esc(hn)}</b>. Need 10+ graded picks to rank.</div><div id="lbBoard" class="empty">Loading board…</div>`;}
  } else {
    h+=`<div class="seclbl" style="margin-top:20px">Global leaderboard</div><div class="empty">Coming soon — compete with other players once the shared board goes live.</div>`;
  }
  host.innerHTML=h;
  if(LEADERBOARD_URL&&myHandle()){fetchLeaderboard().then(board=>{const el=$('#lbBoard');if(!el)return;
    if(!board||!board.length){el.innerHTML='No ranked players yet — be the first with 10+ graded picks.';return;}
    el.className='';el.innerHTML=board.map((r,i)=>`<div class="lbrow"><span class="lbrk">${i+1}</span><span class="lbname">${esc(r.handle)}</span><span class="lbrec">${r.hits}/${r.graded}</span><span class="lbpct">${Math.round(r.hits/r.graded*100)}%</span></div>`).join('');});}
}
function renderTOTT(){const host=$('#view-tott');const t=DATA.team_of_tournament;
  if(!t||!t.xi||!t.xi.length){host.innerHTML=`<div class="vhead">Team of the Tournament</div><div class="empty">Builds once players have goals and assists logged. Check back after more matches.</div>`;return;}
  if(t.v!==2){host.innerHTML=`<div class="vhead">Team of the Tournament</div><div class="banner"><b>Positions need a rebuild.</b> This XI was generated before the real-position fix — run one fetch and players will group by their actual positions (no more strikers in goal).</div>`;return;}
  const byRole=r=>t.xi.filter(p=>p.role===r);
  const line=(label,arr)=>arr.length?`<div class="tottLine"><div class="tottLbl">${label}</div><div class="tottRow">${arr.map(p=>`<div class="tottCard"><div class="tottName">${esc(p.name||'')}</div><div class="tottTeam">${esc(p.code||p.team||'')}</div><div class="tottStat">${p.goals}G ${p.assists}A</div></div>`).join('')}</div></div>`:'';
  host.innerHTML=`<div class="vhead">Team of the Tournament</div>
    <div class="banner"><b>Model-built XI.</b> ${esc(t.note||'')}</div>
    <div class="tottPitch">${line('Forwards',byRole('FWD'))}${line('Midfield',byRole('MID'))}${line('Defence',byRole('DEF'))}${line('Goalkeeper',byRole('GK'))}</div>`;}
function renderCustomize(){const host=$('#view-customize');host.innerHTML=`<div class="vhead">Customize</div><div class="banner"><b>Personalize your terminal.</b> These settings save locally in this browser/app window.</div><div class="settings-grid"><div class="setcard"><label>Accent color</label><select onchange="updateSetting('accent',this.value)">${opt('orange','Matchday orange',SETTINGS.accent)}${opt('blue','Electric blue',SETTINGS.accent)}${opt('green','Pitch green',SETTINGS.accent)}${opt('red','Live red',SETTINGS.accent)}${opt('purple','Night purple',SETTINGS.accent)}</select><div class="hint">Changes highlights, buttons and the brand dot.</div></div><div class="setcard"><label>Language</label><select onchange="setLang(this.value)">${lopt('','English',LANG)}${lopt('es','Español',LANG)}${lopt('fr','Français',LANG)}${lopt('de','Deutsch',LANG)}${lopt('pt','Português',LANG)}${lopt('ru','Русский',LANG)}</select><div class="hint">Translates the interface. Match data stays as provided by sources.</div></div><div class="setcard"><label>Card density</label><select onchange="updateSetting('density',this.value)">${opt('compact','Compact',SETTINGS.density)}${opt('normal','Normal',SETTINGS.density)}${opt('spacious','Spacious',SETTINGS.density)}</select><div class="hint">Compact fits more matches; spacious feels more premium.</div></div><div class="setcard"><label>Panel style</label><select onchange="updateSetting('panel',this.value)">${opt('glass','Soft glass',SETTINGS.panel)}${opt('flat','Flat dark',SETTINGS.panel)}</select><div class="hint">Flat mode is lighter on older laptops.</div></div><div class="setcard"><label>Default tab</label><select onchange="updateSetting('defaultView',this.value)">${['matches','groups','title','edge','bracket','third','news','status','updates'].map(v=>opt(v,v[0].toUpperCase()+v.slice(1),SETTINGS.defaultView)).join('')}</select><div class="hint">Selected when the page starts.</div></div><div class="setcard"><label>Refresh rate</label><select onchange="updateSetting('refresh',this.value)">${opt(30,'Every 30 seconds',SETTINGS.refresh)}${opt(60,'Every 60 seconds',SETTINGS.refresh)}${opt(180,'Every 3 minutes',SETTINGS.refresh)}${opt(300,'Every 5 minutes',SETTINGS.refresh)}</select><div class="hint">This controls the dashboard reload from data.json.</div></div><div class="setcard"><label>Display</label><div class="switchrow"><span>Right insight panel</span><input type="checkbox" ${checked(SETTINGS.showInsight)} onchange="updateSetting('showInsight',this.checked)"></div><div class="switchrow" style="margin-top:10px"><span>Match detail panels</span><input type="checkbox" ${checked(SETTINGS.showDetails)} onchange="updateSetting('showDetails',this.checked)"></div></div></div><div class="btnline"><button class="actionbtn" onclick="resetSettings()">Reset settings</button><button class="actionbtn" onclick="setView('status')">Check app status</button></div>`}
function factorChips(pr){if(!pr||!pr.why)return '';const L={pts:'points',gd:'goal diff',form:'form',adv:'home',class:'class',rest:'rest',injuries:'injuries'};
const chips=Object.entries(pr.why).filter(([k,v])=>Math.abs(v)>=0.3&&L[k]).sort((a,b)=>Math.abs(b[1])-Math.abs(a[1]))
 .map(([k,v])=>`<span class="fchip ${v>0?'pos':'neg'}">${L[k]} ${v>0?'+':''}${v.toFixed(1)}</span>`);
if(pr.damp_pct)chips.push(`<span class="fchip damp">variance &minus;${pr.damp_pct}%</span>`);
if(pr.mkt_pull)chips.push(`<span class="fchip mkt">market ${pr.mkt_pull>0?'+':''}${pr.mkt_pull}</span>`);
return chips.length?`<div class="fchips">${chips.join('')}</div>`:'';}
function scDeepTab(t){window._scTab=t;renderScore();}
function renderDeepDive(sc){const tab=window._scTab||'overview';
  const need=(min,label)=>sc.graded<min?`<div class="empty">${label} unlocks after ${min} graded picks. You have ${sc.graded}.</div>`:'';
  const tabs=['overview','calibration','signals','upsets','errors'];
  let h=`<div class="ddtabs">${tabs.map(x=>`<button class="ddtab ${x===tab?'on':''}" onclick="scDeepTab('${x}')">${x[0].toUpperCase()+x.slice(1)}</button>`).join('')}</div>`;
  if(tab==='overview'){
    h+=`<div class="status-grid">
      <div class="statuscard ${sc.model_hits>=(sc.graded-sc.model_hits)?'ok':'info'}"><span class="slbl">Model</span><div class="sval">${sc.model_hits}/${sc.graded}</div><div class="hint">${sc.graded?Math.round(sc.model_hits/sc.graded*100):0}% correct</div></div>
      <div class="statuscard info"><span class="slbl">Market favourite</span><div class="sval">${sc.market_hits}/${sc.market_graded}</div><div class="hint">the baseline we chase</div></div>
      <div class="statuscard ${sc.disagree_hits>sc.disagree-sc.disagree_hits?'ok':'info'}"><span class="slbl">When we split</span><div class="sval">${sc.disagree_hits}/${sc.disagree}</div><div class="hint">picks that differed from market</div></div>
      <div class="statuscard info"><span class="slbl">Brier</span><div class="sval">${sc.brier??'—'}</div><div class="hint">under 0.20 = sharp</div></div></div>`;
  } else if(tab==='calibration'){
    h+=need(20,'Calibration')||`<div class="seclbl">When the model says X%, how often does it happen?</div>`+(sc.calibration||[]).map(c=>`<div class="ddrow"><span>${c.band}%</span><div class="ddbarwrap"><div class="ddbar" style="width:${Math.round(c.hits/c.n*100)}%"></div></div><span>${Math.round(c.hits/c.n*100)}% <i class="ssnote">(${c.n})</i></span></div>`).join('');
  } else if(tab==='signals'){
    h+=need(20,'Signal quality')||`<div class="seclbl">When a factor favoured the pick, did the pick hit?</div>`+Object.entries(sc.signal_quality||{}).filter(([k,v])=>v.n).map(([k,v])=>{const L={class:'Class / ranking',form:'Recent form',gd:'Goal difference',rest:'Rest',pts:'Points'}[k]||k;const pct=Math.round(v.hits/v.n*100);return `<div class="ddrow"><span>${L}</span><div class="ddbarwrap"><div class="ddbar ${pct>=55?'good':pct<45?'bad':''}" style="width:${pct}%"></div></div><span>${v.hits}/${v.n} <i class="ssnote">${pct}%</i></span></div>`;}).join('');
  } else if(tab==='upsets'){
    const u=sc.upset||{};h+=`<div class="status-grid">
      <div class="statuscard info"><span class="slbl">Upsets watched</span><div class="sval">${u.watched||0}</div><div class="hint">flagged on the radar</div></div>
      <div class="statuscard ${u.hits?'ok':'info'}"><span class="slbl">Radar hits</span><div class="sval">${u.hits||0}/${u.watched||0}</div><div class="hint">flagged underdog won</div></div>
      <div class="statuscard info"><span class="slbl">Triggered picks</span><div class="sval">${u.triggered_hits||0}/${u.triggered||0}</div><div class="hint">upset became the pick</div></div>
      <div class="statuscard info"><span class="slbl">Avg score</span><div class="sval">${u.avg_score??'—'}</div><div class="hint">of watched upsets</div></div></div>`;
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
  if(grid.querySelector('.favoriteTeamSetting'))return;
  const card=document.createElement('div');
  card.className='setcard favoriteTeamSetting';
  card.innerHTML=`<label>${t('My team')}</label><select onchange="updateSetting('favoriteTeam',this.value)"><option value="">${t('No favorite selected')}</option>${favoriteTeamOptions()}</select><div class="hint">${t('Your team moves to the front of matches, news, tables and the insight panel.')}</div>`;
  const language=[...grid.querySelectorAll('.setcard')].find(item=>item.querySelector('label')?.textContent.trim()==='Language');
  if(language)language.insertAdjacentElement('afterend',card);else grid.prepend(card);
};
