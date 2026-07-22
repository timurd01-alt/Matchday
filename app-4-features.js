function renderInsight(){
  const host=$('#insight'),M=DATA.matches||[];
  const focus=M.find(m=>m.status==='LIVE'&&isFavoriteMatch(m))||M.filter(m=>isFavoriteMatch(m)&&isVisibleUpcoming(m)).sort(fixtureSort)[0]||M.find(m=>m.status==='LIVE')||M.filter(isVisibleUpcoming).sort(fixtureSort)[0]||M.find(m=>isFavoriteMatch(m)&&m.status==='FINISHED')||M.find(m=>m.status==='FINISHED')||M[0];
  let h=`<div class="seclbl">In focus</div>`;
  if(focus){
    h+=`<div class="ins-match">${esc(focus.home?.name||'Home')} <span class="evs">v</span> ${esc(focus.away?.name||'Away')}</div><div class="ins-sub">${focus.status==='LIVE'?`LIVE ${focus.minute||''}' · ${focus.score?.home??0}–${focus.score?.away??0}`:`${esc(focus.stage||'')} · ${kickIn(focus.kickoff)}`}</div>`;
    h+=insightModelBlock(focus);
    const x=(focus.markets||{})['1x2']||{};
    if(x.home_pct!=null)h+=`<div class="prob insightProb"><div class="problbl"><span>${esc(focus.home?.code||'H')}</span><span>draw</span><span>${esc(focus.away?.code||'A')}</span></div>${bar1x2(x.home_pct,x.draw_pct,x.away_pct)}</div>`;
    const bd=edgeBreakdown(focus);
    if(bd)h+=`<div class="seclbl" style="margin-top:16px">Model read</div><div class="ins-summary"><p>${esc(bd)}</p></div>`;
  }else{
    h+=`<div class="faintline">No match in focus yet.</div>`;
  }
  const n=diverseNews(6);
  if(n.length)h+=`<div class="seclbl" style="margin-top:18px">Latest from multiple sources</div>`+n.map(a=>`<a class="ins-news" href="${esc(a.link||a.url||'#')}" target="_blank" rel="noopener"><span class="insSource">${esc(sourceName(a))}</span><br>${esc(a.headline||a.title||'Untitled')}</a>`).join('');
  host.innerHTML=h;
}





/* ===== V9 PATCH: restore missing match stats helpers =====
   V8 accidentally removed the statsPanel/statMetric helpers that the expanded
   match view uses. This restores them safely so the modal can render again. */
function fmtStat(v){return (v===undefined||v===null||v==='')?'-':String(v)}
function statMetric(label,h,a){
  const hn=statNum(h),an=statNum(a),tot=Math.max(1,hn+an);
  const hw=hn||an?Math.max(4,hn/tot*100):50;
  const aw=hn||an?Math.max(4,an/tot*100):50;
  return `<div class="statMetric"><div class="val home">${esc(fmtStat(h))}</div><div class="mid"><div class="lab"><span>${esc(label)}</span><span>${hn>an?esc(window.DATA_HNAME||'Home'):an>hn?esc(window.DATA_ANAME||'Away'):'even'}</span></div><div class="metricBar"><i style="width:${hw}%"></i><i style="width:${aw}%"></i></div></div><div class="val away">${esc(fmtStat(a))}</div></div>`;
}
function statsPanel(m){
  window.DATA_HNAME=m?.home?.code||'Home';
  window.DATA_ANAME=m?.away?.code||'Away';
  const sx=m?.stats_extra,hs=sx?.home||{},as=sx?.away||{};
  const ph=sx?pressure(sx,'home'):0,pa=sx?pressure(sx,'away'):0;
  const leader=!sx?'Waiting':ph===pa?'Balanced':ph>pa?(m?.home?.code||m?.home?.name):(m?.away?.code||m?.away?.name);
  let html=`<div class="statsBoard"><div class="seclbl">Match read</div><div class="matchRead">${teamSnap(m?.home||{},'home')}<div class="snapMid"><span>${esc(m?.status||'')}</span><b>${scoreText(m||{}).replace(/<[^>]+>/g,'–')}</b><span>${esc(m?.stage||'')}</span></div>${teamSnap(m?.away||{},'away')}</div>`;
  if(sx){
    html+=`<div class="statHero"><div class="pressureChip"><div class="label">Pressure index</div><div class="value">${Math.round(ph)}–${Math.round(pa)}</div><div class="sub">${esc(leader)} ${leader==='Balanced'?'match':'lean'} · not xG</div></div><div class="pressureChip"><div class="label">Best public signal</div><div class="value">${esc(leader)}</div><div class="sub">based on shots, SOT, possession, corners and cards</div></div></div><div class="statMetrics">${statMetric('Shots',hs.shots,as.shots)}${statMetric('Shots on target',hs.shots_on_target,as.shots_on_target)}${statMetric('Possession',hs.possession,as.possession)}${statMetric('Corners',hs.corners,as.corners)}${statMetric('Fouls',hs.fouls,as.fouls)}${statMetric('Offsides',hs.offsides,as.offsides)}${statMetric('Saves',hs.saves,as.saves)}${statMetric('Cards',`${hs.yellow_cards||0}Y ${hs.red_cards||0}R`,`${as.yellow_cards||0}Y ${as.red_cards||0}R`)}</div>`;
  }else{
    html+=`<div class="emptyStats"><b>${m.status==='FINISHED'?'Box score unavailable':m.status==='LIVE'?'Live stats loading…':'Box score not yet available'}</b><span>${m.status==='UPCOMING'?'Stats appear once the match kicks off.':'This source has not released team stats for this fixture. The model is using form, odds, standings, ratings and market movement instead.'}</span></div>`;
  }
  return html+`</div>`;
}

/* ===== EXPANDED MATCH VIEW FIX — v8 =====
   Restores reliable card expansion by overriding the modal opener with a safe,
   global version. It keeps Forecast/Model/In Focus work, but prevents one bad
   panel from blocking the whole match window. */
/* dedup */
function safeMatchDetails(m){
  try{
    const html=details(m);
    if(html&&String(html).trim())return html;
  }catch(err){
    console.error('Match details failed; using fallback panel:',err);
  }
  try{return simpleMatchFallbackPanel(m)}
  catch(err2){
    console.error('Fallback details also failed:',err2);
    return `<div class="emptyStats">Expanded match view could not render this fixture. Open the browser console for details.</div>`;
  }
}
window.closeMatchModal=function(){
  const modal=document.getElementById('matchModal');
  if(modal)modal.classList.remove('show');
  document.body.classList.remove('modalOpen');
};
window.openMatchModal=function(id){
  try{
    if(id&&typeof id==='object'&&id.closest){
      const art=id.closest('article.card,[data-id]');
      id=art?art.dataset.id:id;
    }
    const key=String(id??'');
    const m=BYID[key]||(DATA.matches||[]).find(x=>String(x.id)===key);
    if(!m){console.warn('Match not found for expanded view:',id);return;}
    let modal=document.getElementById('matchModal');
    if(!modal){
      modal=document.createElement('div');
      modal.id='matchModal';
      modal.className='matchModal';
      modal.addEventListener('click',e=>{if(e.target===modal)window.closeMatchModal()});
      document.body.appendChild(modal);
    }
    const hmeta=t=>`${t?.pos?`#${t.pos} · `:''}${t?.pts??0} pts${t?.form?` · ${esc(t.form)}`:''}`;
    const rawScore=String(scoreText(m)||'').replace(/<[^>]+>/g,'').trim()||'TBD';
    const body=safeMatchDetails(m);
    modal.innerHTML=`<section class="matchSheet" role="dialog" aria-modal="true"><div class="modalHero"><button class="modalClose" onclick="closeMatchModal()" aria-label="Close">×</button><div class="modalStage">${esc(m.stage||'Fixture')} · ${esc(m.status||'')}</div><div class="modalFixture"><div class="modalTeam"><div class="modalCode">${teamFlagHTML(m.home)}${esc(m.home?.code||'HOME')}</div><div class="modalName">${esc(m.home?.name||'Home')}</div><div class="modalMeta">${hmeta(m.home)}</div></div><div class="modalScore"><div class="bigScore">${esc(rawScore)}</div><div class="modalStatus">${m.status==='LIVE'?`LIVE ${m.minute||''}'`:kickIn(m.kickoff)}</div></div><div class="modalTeam away"><div class="modalCode">${esc(m.away?.code||'AWAY')}${teamFlagHTML(m.away,true)}</div><div class="modalName">${esc(m.away?.name||'Away')}</div><div class="modalMeta">${hmeta(m.away)}</div></div></div></div><div class="modalBody">${body}</div></section>`;
    modal.classList.add('show');
    document.body.classList.add('modalOpen');
  }catch(err){
    console.error('openMatchModal failed:',err);
    alert('Expanded view failed to open. Check the browser console for details.');
  }
};
document.addEventListener('keydown',e=>{if(e.key==='Escape')window.closeMatchModal()});


/* ===== OFFICIAL PICK / UPSET WATCH SEPARATION — v10 =====
   UI-side safety gate: an upset candidate can be shown as dangerous without
   replacing the official pick when the market gap is too large. */
function _v10SideName(m,side){
  if(side==='h')return m?.home?.name||'Home';
  if(side==='a')return m?.away?.name||'Away';
  if(side==='d')return 'Draw';
  return 'No pick';
}
function _v10SideCode(m,side){
  if(side==='h')return m?.home?.code||m?.home?.name||'H';
  if(side==='a')return m?.away?.code||m?.away?.name||'A';
  if(side==='d')return 'Draw';
  return '—';
}
function _v10MarketMap(m){
  const x=(m?.markets||{})['1x2']||{};
  return {h:Number(x.home_pct),d:Number(x.draw_pct),a:Number(x.away_pct)};
}
function _v10Has(v){return Number.isFinite(Number(v))}
function _v10TopSide(map,includeDraw=true){
  const sides=includeDraw?['h','d','a']:['h','a'];
  let best='',val=-Infinity;
  sides.forEach(s=>{const n=Number(map?.[s]);if(Number.isFinite(n)&&n>val){best=s;val=n;}});
  return best;
}
function _v10PctFor(m,side){
  const pr=m?.prediction||{};
  const market=_v10MarketMap(m);
  const sources=[pr.base_blend,pr.adjusted,pr.blend,pr.model,market];
  for(const src of sources){const v=Number(src?.[side]);if(Number.isFinite(v))return Math.round(v)}
  return Number.isFinite(Number(pr.confidence))?Math.round(Number(pr.confidence)):null;
}
function _v10OfficialPick(m){
  const pr=m?.prediction||{};
  const u=pr.upset||{};
  const adjusted=pr.adjusted||pr.blend||pr.model||{};
  const baseBlend=pr.base_blend||pr.raw_blend||pr.pre_upset||{};
  const market=_v10MarketMap(m);
  const marketTop=_v10TopSide(market,true);
  const marketTopNoDraw=_v10TopSide(market,false);
  let rawSide=pr.pick||_v10TopSide(adjusted,true)||_v10TopSide(baseBlend,true)||marketTop||'';
  let rawName=pr.pick_name||_v10SideName(m,rawSide);
  const cand=u.candidate||((u.triggered&&rawSide&&rawSide!=='d')?rawSide:'');
  const fav=u.favorite||marketTopNoDraw||_v10TopSide(baseBlend,false)||_v10TopSide(adjusted,false)||'';
  let officialSide=rawSide;
  let blocked=false;
  let marketGap=null;
  let gateReason='';

  if(cand&&rawSide===cand&&marketTopNoDraw&&marketTopNoDraw!==cand&&_v10Has(market[marketTopNoDraw])&&_v10Has(market[cand])){
    marketGap=Math.abs(Number(market[marketTopNoDraw])-Number(market[cand]));
    const boxEdge=Number(u.box_score_edge??u.box_edge??0);
    const strongBox=boxEdge>=0.35||u.box_score_gate===true;
    const backendBlocked=u.blocked===true||u.market_gate===false;
    if(backendBlocked || (marketGap>12 && !(Number(u.score||0)>=75&&strongBox))){
      blocked=true;
      officialSide=(pr.base_pick&&pr.base_pick!==cand)?pr.base_pick:
        (_v10TopSide(baseBlend,true)&&_v10TopSide(baseBlend,true)!==cand)?_v10TopSide(baseBlend,true):
        marketTopNoDraw;
      gateReason=`market gap ${Math.round(marketGap)} pts blocks override`;
    }
  }

  const name=_v10SideName(m,officialSide);
  const conf=_v10PctFor(m,officialSide);
  const marketPct=_v10Has(market[officialSide])?Math.round(market[officialSide]):null;
  const candName=u.candidate_name||_v10SideName(m,cand);
  const candPct=Number.isFinite(Number(u.candidate_pct))?Math.round(Number(u.candidate_pct)):_v10PctFor(m,cand);
  const officialNote=blocked
    ? `Upset watch: ${candName}. ${gateReason}; official pick stays ${name}.`
    : (u.triggered&&cand===officialSide ? 'Upset pick passed the gate.' : (pr.note||'model read'));
  return {side:officialSide,name,confidence:conf,marketPct,rawSide,rawName,blocked,gateReason,marketGap,
          candidate:cand,candidateName:candName,candidatePct:candPct,upsetScore:Number(u.score||0),
          upsetTriggered:!!u.triggered, note:officialNote};
}
function _v10OfficialEdge(m,op){
  const market=_v10MarketMap(m); const mk=Number(market[op.side]);
  if(!Number.isFinite(mk)||op.confidence==null)return null;
  return Math.round(Number(op.confidence)-mk);
}
function _totalsUnit(m){return SANDBOX_TWO_WAY.has(String(m?._comp||DATA.comp_key||'').toLowerCase())?'points':'goals';}
function edgeBreakdown(m){
  const pr=m?.prediction, x=(m?.markets||{})['1x2']||{};
  if(!pr)return '';
  const op=_v10OfficialPick(m);
  const pickSide=op.side;
  const mkmap={h:x.home_pct,d:x.draw_pct,a:x.away_pct};
  const modelP=(pr.base_blend&&pr.base_blend[pickSide]!=null)?pr.base_blend[pickSide]:(pr.model?pr.model[pickSide]:null);
  const mktP=mkmap[pickSide];
  const edge=_v10OfficialEdge(m,op);
  const team=(pickSide==='h')?m.home:(pickSide==='a')?m.away:null;
  let bits=[];
  if(op.blocked){
    bits.push(`Official pick stays ${op.name}${op.confidence!=null?` at ${op.confidence}%`:''}. Upset radar flagged ${op.candidateName}${op.upsetScore?` (${op.upsetScore}/100)`:''}, but ${op.gateReason}.`);
  }else if(edge!=null&&mktP!=null&&modelP!=null){
    if(edge>=6)bits.push(`The model rates ${op.name} higher than the market (${modelP}% vs ${mktP}%).`);
    else if(edge<=-6)bits.push(`The model is cooler on ${op.name} than the market (${modelP}% vs ${mktP}%).`);
    else bits.push(`Model and market broadly agree on ${op.name} (${modelP}% vs ${mktP}%).`);
  }else{
    bits.push(`Official model pick is ${op.name}${op.confidence!=null?` at ${op.confidence}%`:''}.`);
  }
  if(team){
    const f=String(team.form||'').split(' ').filter(Boolean);
    if(f.length)bits.push(`${team.name} form: ${f.join(' ')} · GD ${Number(team.gd||0)>0?'+':''}${team.gd??0}.`);
  }
  const tot=(m?.markets||{}).totals;
  const modelTot=(m?.prediction||{}).totals;
  if(tot){
    const unit=_totalsUnit(m);
    let goalsLine=`${unit==='goals'?'Goals':'Points'} market: over ${tot.line} ${tot.over_pct}%, under ${tot.line} ${tot.under_pct}%.`;
    if(modelTot&&modelTot.pick)goalsLine+=` Model expects ${modelTot.expected} — leans ${modelTot.pick}.`;
    bits.push(goalsLine);
  }else if(modelTot&&modelTot.expected!=null){
    bits.push(`Model expects ${modelTot.expected} ${_totalsUnit(m)} — no market line yet.`);
  }
  return bits.join(' ');
}
function _v6UpsetBox(m){
  const pr=m?.prediction||{},u=pr.upset||{},op=_v10OfficialPick(m);
  if(!u.candidate)return `<div class="analystBox upsetBox"><div class="analystBoxTitle">Upset radar</div><div class="emptyForecast" style="padding:12px">No upset profile yet.</div></div>`;
  const shownActive=!!u.triggered&&!op.blocked;
  const cls=_v6UpsetClass(u.score,shownActive);
  const status=op.blocked?'watch only · gate blocked':shownActive?'upset pick active':'watch only';
  const reason=op.blocked?`${u.reason||'Volatility profile detected.'} · ${op.gateReason}.`:u.reason||'Volatility profile calculated from draw pressure, low-scoring profile, favorite softness, and team gap.';
  return `<div class="analystBox upsetBox"><div class="analystBoxTitle">Upset radar</div><div class="upsetHero"><div class="candidate"><span>candidate</span><b>${esc(u.candidate_name||'Underdog')}</b></div><div class="upsetScoreDial ${cls}"><b>${esc(u.score??'—')}</b><small>/100</small></div></div><div class="probLines"><div class="probLine"><span class="sideName">${esc(u.favorite_name||'Favorite')}</span><span class="probTrack"><i class="probFill h" style="width:${Math.max(3,Number(u.favorite_pct)||0)}%"></i></span><span class="pct">${esc(u.favorite_pct??'—')}%</span></div><div class="probLine"><span class="sideName">${esc(u.candidate_name||'Underdog')}</span><span class="probTrack"><i class="probFill a" style="width:${Math.max(3,Number(u.candidate_pct)||0)}%"></i></span><span class="pct">${esc(u.candidate_pct??'—')}%</span></div></div><div class="upsetMath"><span>Temp<b class="hot">T ${esc(u.temperature??'—')}</b></span><span>Variance<b>${esc(u.variance_pct??'—')}%</b></span><span>Low goals<b>${esc(u.low_goal_pct??'—')}%</b></span></div><p class="upsetReason">${esc(reason)}</p><span class="upsetTriggered ${op.blocked?'blocked':shownActive?'':'watch'}">${esc(status)}</span></div>`;
}
/* dedup */
function insightModelBlock(m){
  const pr=m&&m.prediction;
  if(!pr)return '<div class="seclbl">Model pick</div><div class="nomk">No model pick yet.</div>';
  const op=_v10OfficialPick(m),edge=_v10OfficialEdge(m,op);
  const cls=(edge!=null&&Math.abs(edge)>=6?'edge ':'')+(op.blocked?'gate':'');
  return `<div class="seclbl">Model pick</div><div class="pick insightPick ${cls}"><span class="pl">Pick</span><span class="pn">${esc(op.name)}</span><span class="pc">${esc(op.confidence??'—')}%</span><span class="pnote">${esc(op.note)}</span></div>`;
}
function cardHTML(m){
  const live=m.status==='LIVE',stale=isStaleUpcoming(m),displayStatus=stale?'PAST / REFRESH':m.status;
  const x=(m.markets&&m.markets['1x2'])||{};const hfl=teamFlagHTML(m.home),afl=teamFlagHTML(m.away,true);
  const probTop=x.home_pct!=null?`<div class="prob"><div class="problbl"><span>${esc(m.home.code||m.home.name)}</span><span>Market read</span><span>${esc(m.away.code||m.away.name)}</span></div>${bar1x2(x.home_pct,x.draw_pct,x.away_pct)}</div>`:`<div class="prob"><div class="nomk">No market snapshot yet</div></div>`;
  const pr=m.prediction;const op=pr?_v10OfficialPick(m):null;const edge=op?_v10OfficialEdge(m,op):null;
  const pick=op?`<div class="pick ${edge!=null&&Math.abs(edge)>=6?'edge':''} ${op.blocked?'gate':''}"><span class="pl">Pick</span><span class="pn">${esc(op.name)}</span><span class="pc">${esc(op.confidence??'—')}%</span><span class="pnote">${esc(op.note||'')}</span></div>`:'';
  return `<article class="card${live?' liveCard':''}${SETTINGS.showDetails?'':' compactCard'}" data-id="${esc(m.id)}"><div class="head" onclick="openMatchModal(this.closest('article').dataset.id)"><div class="metarow"><span class="stage">${esc(m.stage||'Fixture')}</span>${m._comp&&!DATA_FILE?`<span class="compTag">${esc(m._comp)}</span>`:''}<span class="wstar ${wlHas(m.home.name)||wlHas(m.away.name)?'on':''}" onclick="event.stopPropagation();wlToggle('${esc(m.home.name)}')" title="Watch">&#9733;</span>${m.weather?`<span class="wxchip"><b>${m.weather.temp_c}&deg;</b>${m.weather.wind_kph>=20?` ${m.weather.wind_kph}km/h`:''}${m.weather.rain_pct>=40?` &#9730;${m.weather.rain_pct}%`:''}</span>`:''}<span class="spacer"></span><span class="pill ${esc(displayStatus)}">${live?'<span class="blink"></span>':''}${esc(displayStatus)}</span></div><div class="fixture"><div class="side"><div class="tname">${hfl}${esc(m.home.name)}</div><div class="tsub"><span>${esc(m.home.code)}</span><span>${m.home.pos?`#${m.home.pos}`:''}</span><span>${m.home.pts??0} pts</span></div></div><div class="center"><div class="score">${scoreText(m)}</div>${live?`<div class="minute">${m.minute||''}'</div>`:`<div class="kick">${stale?'past kickoff':kickIn(m.kickoff)}</div>`}</div><div class="side away"><div class="tname">${esc(m.away.name)}${afl}</div><div class="tsub"><span>${esc(m.away.code)}</span><span>${m.away.pos?`#${m.away.pos}`:''}</span><span>${m.away.pts??0} pts</span></div></div></div>${probTop}${pick}<div class="expander"></div></div></article>`;
}
function _modelRow(m){
  const pr=m.prediction||{},op=_v10OfficialPick(m),kind=_modelEdgeKind(pr),tag=_modelTag(m),arch=_modelIsArchived(m);
  const edgeVal=_v10OfficialEdge(m,op);const edge=(edgeVal==null||arch)?'':`${edgeVal>0?'+':''}${edgeVal}`;
  const sub=arch?`${op.confidence??'—'}% · ${_modelFinalText(m)}`:`${op.confidence??'—'}% · ${_modelMarketText(m,op.side)}`;
  const statusKind=op.blocked?'gate':tag.kind;const statusTxt=op.blocked?'UPSET WATCH':tag.txt;
  return `<div class="modelRow ${arch?'archived':''}" onclick="openMatchModal('${esc(String(m.id||''))}')"><div class="modelMatch"><div class="teams">${esc(m.home?.code||m.home?.name||'H')} v ${esc(m.away?.code||m.away?.name||'A')}</div><div class="meta">${esc(m.stage||'Fixture')} · ${_modelWhen(m)}</div></div><div class="modelChoice"><div class="small">${arch?'Archived pick':'Official pick'}</div><div class="main">${esc(op.name||'No pick')}</div><div class="sub">${esc(sub)}</div></div>${_modelBars(pr)}<div class="modelStatus"><span class="tag ${statusKind}">${statusTxt}</span>${edge?`<span class="tag ${kind}">${edge} edge</span>`:''}</div></div>`;
}
function _modelSpotlight(list){
  const liveList=(list||[]).filter(m=>!_modelIsArchived(m));const m=liveList.find(x=>(_v10OfficialEdge(x,_v10OfficialPick(x))||0)>=6)||liveList[0];if(!m)return'';
  const pr=m.prediction||{},op=_v10OfficialPick(m),kind=op.blocked?'gate':_modelEdgeKind(pr);const edgeVal=_v10OfficialEdge(m,op);const edge=edgeVal==null?'No edge data':`${edgeVal>0?'+':''}${edgeVal} vs market`;
  return `<div class="modelSpot"><div class="modelSpotHead"><span>Best current read</span><span>${esc(m.stage||'Fixture')} · ${_modelWhen(m)}</span></div><div class="modelSpotBody"><div class="modelSpotTeam"><span class="code">${esc(m.home?.code||'HOME')}</span><div class="name">${esc(m.home?.name||'Home')}</div></div><div class="modelPickDial"><div class="lbl">Official pick</div><div class="pickName">${esc(op.name||'No pick')}</div><div class="conf">${op.confidence??'—'}%</div><span class="edgePill ${kind}">${esc(op.blocked?'upset watch only':edge)}</span></div><div class="modelSpotTeam away"><span class="code">${esc(m.away?.code||'AWAY')}</span><div class="name">${esc(m.away?.name||'Away')}</div></div></div></div>`;
}
function _v4UpsetRows(){
  const M=(DATA.matches||[]).filter(m=>m.status!=='FINISHED'&&!isStaleUpcoming(m));
  return M.map(m=>{
    const pr=m.prediction||{},u=pr.upset||{},op=_v10OfficialPick(m);
    if(u.candidate){
      const risk=Number(u.score)||0;const active=!!u.triggered&&!op.blocked;const cls=active?'trigger':risk>=70?'high':risk>=50?'med':'low';
      const reason=op.blocked?`${u.candidate_name||'Underdog'} ${u.candidate_pct??'—'}% · ${op.gateReason}`:`${u.candidate_name||'Underdog'} ${u.candidate_pct??'—'}% · ${u.reason||'upset profile'}`;
      return {m,risk,cls,reason,triggered:active,blocked:op.blocked};
    }
    const hp=_v4OutcomePct(m,'h'),dp=_v4OutcomePct(m,'d'),ap=_v4OutcomePct(m,'a');
    const fav=hp>=ap&&hp>=dp?'h':ap>=hp&&ap>=dp?'a':'d';const favPct=Math.max(hp,ap,dp),margin=Math.abs(hp-ap),draw=dp;
    let risk=0,reason='balanced profile';
    if(draw>=30){risk=72;reason=`draw pressure is high at ${Math.round(draw)}%`}
    else if(favPct<46){risk=66;reason=`favorite is not dominant (${Math.round(favPct)}%)`}
    else if(Number((m.prediction||{}).confidence||0)<45){risk=58;reason=`low model confidence (${(m.prediction||{}).confidence||'—'}%)`}
    else if(margin<9){risk=52;reason='teams are close on win probability'}
    else {risk=34;reason='favorite profile is cleaner'}
    const cls=risk>=70?'high':risk>=50?'med':'low';return {m,risk,cls,reason,triggered:false,blocked:false};
  }).sort((a,b)=>b.risk-a.risk).slice(0,6);
}
function simpleMatchFallbackPanel(m){
  const pr=m?.prediction||{},op=_v10OfficialPick(m);const x=(m?.markets||{})['1x2']||{};const probs=pr.adjusted||pr.blend||pr.model||{};
  const pH=Math.round(Number(probs.h??x.home_pct??0));const pD=Math.round(Number(probs.d??x.draw_pct??0));const pA=Math.round(Number(probs.a??x.away_pct??0));
  return `<div class="detailGrid v8Fallback"><div class="readCard"><div class="seclbl">Model read</div><div class="pick insightPick ${op.blocked?'gate':''}"><span class="pl">Pick</span><span class="pn">${esc(op.name||'No pick')}</span><span class="pc">${esc(op.confidence??'—')}%</span><span class="pnote">${esc(op.note||'')}</span></div><div class="prob" style="margin-top:12px"><div class="problbl"><span>${esc(m?.home?.code||'Home')}</span><span>draw</span><span>${esc(m?.away?.code||'Away')}</span></div>${bar1x2(pH,pD,pA)}</div>${edgeBreakdown(m)?`<div class="ins-summary" style="margin-top:12px"><p>${esc(edgeBreakdown(m))}</p></div>`:''}</div><div class="readCard">${marketPanel(m)}</div><div class="statsBoard">${statsPanel(m)}</div><div class="lineupBoard">${lineupsPanel(m)}</div></div>`;
}


/* ===== BRACKET V11 — render readable round-by-round board ===== */
function _v11RoundLabel(name){
  const x=String(name||'');
  return x.replace('Round of 32','Round of 32').replace('Round of 16','Round of 16').replace('Quarter-finals','Quarterfinals').replace('Semi-finals','Semifinals').replace('Third-place playoff','Third place');
}
function _v11TeamName(v){
  if(v&&typeof v==='object')return v.name||v.team||v.code||'TBD';
  return v||'TBD';
}
function _v11TeamCode(m,side){
  const obj=side==='h'?m?.home:m?.away;
  const direct=side==='h'?(m?.home_code||m?.homeCode):(m?.away_code||m?.awayCode);
  if(direct)return direct;
  if(obj&&typeof obj==='object'&&obj.code)return obj.code;
  const nm=_v11TeamName(obj);
  if(/^Winner\b|^Loser\b|^Seed\b|^TBD$/i.test(String(nm)))return '';
  try{return codeForTeam(nm,'')||''}catch(e){return ''}
}
function _v11TeamSlot(m,side){
  const obj=side==='h'?m?.home:m?.away;
  const direct=side==='h'?(m?.home_slot||m?.homeSlot):(m?.away_slot||m?.awaySlot);
  if(direct)return direct;
  if(obj&&typeof obj==='object')return obj.slot||obj.group||'';
  return '';
}
function _v11Score(m,side){
  const sc=m?.score||{};
  return side==='h'?sc.home:sc.away;
}
function _v11IsWin(m,side){
  const st=String(m?.status||'').toUpperCase();
  const hs=Number(_v11Score(m,'h')),as=Number(_v11Score(m,'a'));
  if(st!=='FINISHED'||!Number.isFinite(hs)||!Number.isFinite(as)||hs===as)return false;
  return side==='h'?hs>as:as>hs;
}
function _v11TeamRow(m,side){
  const nm=_v11TeamName(side==='h'?m?.home:m?.away);
  const code=_v11TeamCode(m,side);
  const slot=_v11TeamSlot(m,side);
  const score=_v11Score(m,side);
  const win=_v11IsWin(m,side);
  const isPath=/^(Winner|Loser|Seed)\b|^TBD$/i.test(String(nm));
  let fl='';
  try{fl=code?flagEmoji(code):''}catch(e){fl=''}
  return `<div class="brWideTeam ${win?'win':''} ${isPath?'path':''}"><div class="brWideName">${slot?`<span class="brWideSlot">${esc(slot)}</span>`:''}${fl?`<span class="flag">${fl}</span>`:''}${code?`<span class="brWideCode">${esc(code)}</span>`:''}<span class="brWideText">${esc(nm)}</span></div><div class="brWideScore">${score!=null&&score!==''?esc(score):''}</div></div>`;
}
function _v11StatusText(m){
  const st=String(m?.status||'').toUpperCase();
  if(st==='LIVE')return 'LIVE';
  if(st==='FINISHED')return 'FT';
  if(m?.kickoff){try{return dt(m.kickoff)}catch(e){return 'Scheduled'}}
  return st&&st!=='PROJECTED'?'TBD':'Path';
}
function _v11MatchCard(m,roundName){
  if(!m)return `<div class="brWideEmpty">Waiting for matchup</div>`;
  const st=String(m.status||'').toUpperCase();
  const cls=`brWideMatch ${st==='LIVE'?'live':''} ${st==='FINISHED'?'done':''} ${/Final/i.test(roundName)?'final':''} ${/Third/i.test(roundName)?'third':''}`;
  const label=m.stage||m.round||roundName||'Match';
  return `<article class="${cls}"><div class="brWideMeta"><span>${esc(label)}</span><span class="brWideStatus">${esc(_v11StatusText(m))}</span></div>${_v11TeamRow(m,'h')}${_v11TeamRow(m,'a')}</article>`;
}
function _v11RoundCol(rounds,name){
  const matches=roundMatches(rounds,name)||[];
  const safe=matches.length?matches:[null];
  return `<section class="brWideRound"><div class="brWideTitle"><b>${esc(_v11RoundLabel(name))}</b><span>${matches.length||0}</span></div><div class="brWideStack">${safe.map(m=>_v11MatchCard(m,name)).join('')}</div></section>`;
}
function _v14BubbleRows(rows){
  return (rows||[]).length?(rows||[]).map(t=>`<div class="bubbleTeam"><div><b>${esc(t.name||'')}</b><span>${esc(t.conference||'')} · ${esc(t.record||'')}</span></div><strong>${esc(t.model_score??'—')}</strong></div>`).join(''):'<div class="bracketologyEmpty">Not enough current-season data yet.</div>';
}
function _v14RenderBracketology(host,b){
  const firstFour=(b.first_four||[]).map(g=>`<article class="firstFourGame"><div class="firstFourMeta"><span>${esc(g.kind||'First Four')}</span><b>${esc(g.region||'')} · ${g.seed?`Seed ${esc(g.seed)}`:'seed pending'}</b></div>${(g.teams||[]).map(t=>`<div class="firstFourTeam"><div><strong>${esc(t.name||'')}</strong><span>${esc(t.conference||'')} · ${esc(t.record||'')}</span></div><b>${esc(t.model_score??'—')}</b></div>`).join('')}</article>`).join('');
  const regions=Object.entries(b.regions||{}).map(([name,teams])=>`<section class="regionCard"><div class="regionHead"><h3>${esc(name)}</h3><span>projected region</span></div><div class="regionSeeds">${(teams||[]).map(t=>`<div class="regionSeed ${t.bid==='First Four'?'playin':''}"><b>${esc(t.seed||'—')}</b><div><strong>${esc(t.name||'')}</strong><span>${esc(t.record||'')} · ${esc(t.bid||'At-large')}</span></div><em>${esc(t.model_score??'—')}</em></div>`).join('')}</div></section>`).join('');
  host.innerHTML=`<div class="bracketologyShell"><header class="bracketologyHero"><div><span class="bracketologyEyebrow">Matchday model · ${esc(b.version||'beta')}</span><h2>Bracketology</h2><p>${esc(b.source_note||'Independent field projection from raw team results.')}</p></div><div class="bracketologyKpis"><div><span>Projected field</span><b>${esc(b.field_size||'—')}</b></div><div><span>Automatic bids</span><b>${(b.first_four||[]).filter(g=>g.kind==='Automatic bids').length? 'conference leaders':'—'}</b></div></div></header><div class="methodStrip"><b>Current beta formula</b><span>${esc(b.methodology||'')}</span><em>Not yet historically calibrated</em></div><section class="firstFourSection"><div class="bracketologySectionHead"><h3>First Four</h3><span>lowest automatic and at-large lines</span></div><div class="firstFourGrid">${firstFour||'<div class="bracketologyEmpty">First Four projection unavailable.</div>'}</div></section><div class="bubbleGrid"><section><div class="bracketologySectionHead"><h3>Last Four Byes</h3><span>inside the field</span></div>${_v14BubbleRows(b.last_four_byes)}</section><section><div class="bracketologySectionHead"><h3>First Four Out</h3><span>first teams outside</span></div>${_v14BubbleRows(b.first_four_out)}</section><section><div class="bracketologySectionHead"><h3>Next Four Out</h3><span>bubble watch</span></div>${_v14BubbleRows(b.next_four_out)}</section></div><div class="regionGrid">${regions}</div><p class="bracketologyFoot">This is a Matchday projection, not the NCAA selection committee's bracket. Data providers supply raw records and scores; the selection and seeding shown here are calculated locally.</p></div>`;
}
/* ===== Bracket Simulator — cascading model picks, clickable overrides ===== */
function bracketSimPredict(homeName,awayName){
  if(!homeName||!awayName||homeName==='TBD'||awayName==='TBD')return null;
  const r=typeof sandboxRun==='function'?sandboxRun(homeName,awayName):null;
  if(!r)return null;
  return {winner:r.probs.h>=r.probs.a?homeName:awayName,pct:Math.max(r.probs.h,r.probs.a)};
}
function bracketSimCascade(){
  const slots=_projectedSlots32();
  const overrides=window.__bracketSim||(window.__bracketSim={});
  const codeOf=name=>(sandboxTeams().find(t=>t.name===name)||{}).code||'';
  let current=[];
  for(let i=0;i<16;i++){
    const a=slots[i*2]||_slotTBD(`Seed ${i*2+1}`),b=slots[i*2+1]||_slotTBD(`Seed ${i*2+2}`);
    const key=`R32#${i}`,pred=bracketSimPredict(a.team,b.team);
    current.push({key,home:a.team,homeCode:a.code,away:b.team,awayCode:b.code,
      winner:overrides[key]||(pred?pred.winner:null),pred});
  }
  const rounds=[{round:'Round of 32',matches:current}];
  for(const rn of ['Round of 16','Quarter-finals','Semi-finals']){
    const next=[];
    for(let i=0;i<current.length/2;i++){
      const a=current[i*2],b=current[i*2+1];
      const home=a?.winner,away=b?.winner;
      const key=`${rn}#${i}`,pred=bracketSimPredict(home,away);
      next.push({key,home,homeCode:codeOf(home),away,awayCode:codeOf(away),
        winner:overrides[key]||(pred?pred.winner:null),pred});
    }
    rounds.push({round:rn,matches:next});
    current=next;
  }
  const sf=current;
  const finalHome=sf[0]?.winner,finalAway=sf[1]?.winner;
  const finalKey='Final#0',finalPred=bracketSimPredict(finalHome,finalAway);
  rounds.push({round:'Final',matches:[{key:finalKey,home:finalHome,homeCode:codeOf(finalHome),away:finalAway,awayCode:codeOf(finalAway),
    winner:overrides[finalKey]||(finalPred?finalPred.winner:null),pred:finalPred}]});
  return rounds;
}
function bracketSimMatchByKey(key){
  for(const r of bracketSimCascade())for(const m of r.matches)if(m.key===key)return m;
  return null;
}
function bracketSimPick(key,side){
  const m=bracketSimMatchByKey(key);
  if(!m)return;
  window.__bracketSim=window.__bracketSim||{};
  window.__bracketSim[key]=side==='home'?m.home:m.away;
  renderBracket();
}
function bracketSimReset(){window.__bracketSim={};renderBracket();}
function _bracketSimCard(m){
  const clickable=m.home&&m.away&&m.home!=='TBD'&&m.away!=='TBD';
  const row=(name,code,side)=>{
    const label=esc(name||'TBD');
    const won=m.winner&&name&&m.winner===name;
    return `<div class="bmTeam ${won?'simWinner':''} ${clickable?'simClickable':''}" ${clickable?`onclick="bracketSimPick('${m.key}','${side}')"`:''}><span>${label}${code?` <small>${esc(code)}</small>`:''}</span>${won?'<b>&#10003;</b>':''}</div>`;
  };
  const note=m.pred?`${m.pred.pct}% model` : (clickable?'no standings data':'');
  return `<div class="brMini simMatch"><div class="bmMeta"><span>${esc(note)}</span></div>${row(m.home,m.homeCode,'home')}${row(m.away,m.awayCode,'away')}</div>`;
}
function renderBracketSim(host,toggle){
  const rounds=bracketSimCascade();
  const cols=rounds.map(r=>`<section class="brCol"><div class="roundTitle">${esc(r.round)}</div>${r.matches.map(_bracketSimCard).join('')}</section>`).join('');
  host.innerHTML=`<div class="bracketStageHeader"><div class="vhead">Bracket Simulator</div><div class="bracketLegend">${toggle}<button class="btmbtn" onclick="bracketSimReset()">Reset to model picks</button></div></div><div class="bracketWideHint"><span>Click a team to override the model's pick for that match — it cascades through the rest of the bracket.</span></div><div class="bracketWideShell"><div class="bracketWideBoard">${cols}</div></div>`;
}
function renderBracket(){
  const host=$('#view-bracket');
  if(!host)return;
  if(DATA.comp_key==='NCAAM'&&DATA.bracketology){_v14RenderBracketology(host,DATA.bracketology);return}
  const mode=window.__bracketMode||'view';
  const toggle=`<button class="btmbtn" onclick="window.__bracketMode='${mode==='view'?'simulate':'view'}';renderBracket();">${mode==='view'?'Simulate the bracket':'Back to bracket view'}</button>`;
  if(mode==='simulate'){renderBracketSim(host,toggle);return;}
  const official=Array.isArray(DATA.bracket)&&DATA.bracket.some(r=>(r.matches||[]).length);
  const rounds=typeof _completeRounds==='function'?_completeRounds():projectedRounds();
  const names=['Round of 32','Round of 16','Quarter-finals','Semi-finals','Final','Third-place playoff'];
  const projectedCount=(()=>{try{return Math.min(getProjectedSlots().length,32)}catch(e){return 0}})();
  host.innerHTML=`<div class="bracketStageHeader"><div class="vhead">Tournament bracket</div><div class="bracketLegend">${toggle}${official?'Official + projected paths':'Projected bracket'}</div></div><div class="bracketWideHint"><span><b>${projectedCount}</b> projected qualifiers · cards stay readable instead of shrinking</span><span>Scroll sideways to see the full path →</span></div><div class="bracketWideShell"><div class="bracketWideBoard">${names.map(n=>_v11RoundCol(rounds,n)).join('')}</div></div>`;
}



/* ===== MODEL OUTCOME PROBABILITY CARD — v12 ===== */
function _v12Round(v){return Math.max(0,Math.min(100,Math.round(Number(v)||0)))}
function _v12ProbTile(label,pct,side,active){
  const cls=side==='h'?'home':side==='d'?'draw':'away';
  return `<div class="probTile ${cls} ${active?'pickSide':''}"><span class="probSide">${esc(label)}</span><b class="probPct">${_v12Round(pct)}%</b><span class="probMiniTrack"><i style="width:${Math.max(3,_v12Round(pct))}%"></i></span>${active?'<em class="probTag">pick</em>':''}</div>`;
}
function _v12OutcomeCard(m,op){
  const probs=_v4ModelProbs(m)||{};
  const market=_v10MarketMap(m)||{};
  const side=op?.side||'';
  const hp=_v12Round(probs.h), dp=_v12Round(probs.d), ap=_v12Round(probs.a);
  const marketPct=_v10Has(market[side])?_v12Round(market[side]):null;
  const edge=op?_v10OfficialEdge(m,op):null;
  const edgeCls=edge==null?'edgeFlat':edge>0?'edgePos':edge<0?'edgeNeg':'edgeFlat';
  const tot=(m?.markets||{}).totals||{};
  const modelTot=(m?.prediction||{}).totals;
  const drawNote=dp>=30?'high draw pressure':dp>=25?'moderate draw pressure':'low draw pressure';
  const unit=_totalsUnit(m);
  const goalNote=tot.under_pct!=null?`Under ${esc(tot.line||2.5)}: ${esc(tot.under_pct)}%${modelTot&&modelTot.pick?` (model: ${esc(modelTot.pick)})`:''}`
    :(modelTot&&modelTot.expected!=null?`Model expects ${esc(modelTot.expected)} ${unit}`:`No ${unit} market yet`);
  // Without a market yet, "market on pick" / "model edge" have nothing to
  // show -- swap in the class-rating and Elo edges (from the pick's own
  // perspective; why values are stored home-minus-away) instead of a pair
  // of blank dashes. Both are always present in why{} once a pick exists.
  const why=(m?.prediction||{}).why||{};
  const sideSign=side==='a'?-1:1;
  const pts=v=>`${v>0?'+':''}${v.toFixed(1)} pts`;
  const hasMarket=marketPct!=null;
  const compareLabel1=hasMarket?'Market on pick':'Class edge';
  const compareVal1=hasMarket?`${marketPct}%`:(why.class!=null?pts(why.class*sideSign):'—');
  const compareLabel2=hasMarket?'Model edge':'Elo edge';
  const eloEdge=why.elo!=null?why.elo*sideSign:null;
  const compareCls2=hasMarket?edgeCls:(eloEdge==null?'edgeFlat':eloEdge>0?'edgePos':eloEdge<0?'edgeNeg':'edgeFlat');
  const compareVal2=hasMarket?(edge!=null?`${edge>0?'+':''}${edge} pts`:'—'):(eloEdge!=null?pts(eloEdge):'—');
  const risk=op?.blocked?`Upset gate blocked · ${esc(op.gateReason||'market gap too wide')}`:`${drawNote} · ${goalNote}`;
  return `<div class="analystBox probMatrixCard"><div class="analystBoxTitle">Probability check</div><div class="probMatrix"><div class="probTiles">${_v12ProbTile(m?.home?.code||m?.home?.name||'Home',hp,'h',side==='h')}${_v12ProbTile('Draw',dp,'d',side==='d')}${_v12ProbTile(m?.away?.code||m?.away?.name||'Away',ap,'a',side==='a')}</div><div class="probCompareGrid"><div class="probCompareItem"><span>Official side</span><b>${esc(op?.name||'No pick')}</b></div><div class="probCompareItem"><span>${compareLabel1}</span><b>${esc(compareVal1)}</b></div><div class="probCompareItem ${compareCls2}"><span>${compareLabel2}</span><b>${esc(compareVal2)}</b></div></div><p class="probContextLine">${risk}</p></div></div>`;
}
function _v15Num(v){
  if(v===null||v===undefined||v==='')return null;
  const n=Number(v);return Number.isFinite(n)?n:null;
}
function _v15Record(team){
  const p=_v15Num(team?.pld),w=_v15Num(team?.w),d=_v15Num(team?.d),l=_v15Num(team?.l);
  if(!p||w==null||l==null)return null;
  return d==null?`${w}-${l}`:`${w}-${d}-${l}`;
}
function _v15Rate(team,key){
  const p=_v15Num(team?.pld),v=_v15Num(team?.[key]);
  return p&&v!=null&&v>0?Number(v/p).toFixed(1):null;
}
function _v15Form(team){
  const vals=String(team?.form||'').trim().split(/[\s,]+/).filter(v=>/^[WDL]$/i.test(v)).slice(-5);
  return vals.length?vals.map(v=>`<i class="profileFormDot ${v.toUpperCase()}">${v.toUpperCase()}</i>`).join(''):null;
}
function _v15CompareRow(label,home,away,html){
  if(home==null&&away==null)return '';
  const val=v=>v==null?'—':html?v:esc(v);
  return `<div class="profileCompareRow"><b>${val(home)}</b><span>${esc(label)}</span><b>${val(away)}</b></div>`;
}
function _v15MatchProfile(m,op){
  const pr=m?.prediction||{},probs=_v4ModelProbs(m)||{},side=op?.side||'';
  const ordered=['h','d','a'].map(k=>_v15Num(probs[k])).filter(v=>v!=null).sort((a,b)=>b-a);
  const separation=ordered.length>1?Math.max(0,Math.round(ordered[0]-ordered[1])):null;
  const base=pr.base_blend||pr.model||{};
  const basePick=_v15Num(base[side]),official=_v15Num(op?.confidence);
  const adjustment=basePick!=null&&official!=null?Math.round(official-basePick):null;
  const unit=_totalsUnit(m);
  const expected=_v15Num(pr?.totals?.expected);
  const hScored=_v15Rate(m?.home,'gf'),aScored=_v15Rate(m?.away,'gf');
  const scoringBaseline=expected!=null?expected:(hScored!=null&&aScored!=null?Number(hScored)+Number(aScored):null);
  const totalLabel=expected!=null?'Expected total':'Scoring baseline';
  const homeOut=Array.isArray(m?.injuries?.home)?m.injuries.home.length:0;
  const awayOut=Array.isArray(m?.injuries?.away)?m.injuries.away.length:0;
  const kpis=[
    ['Model separation',separation!=null?`${separation} pts`:'—'],
    ['Probability adjustment',adjustment!=null?`${adjustment>0?'+':''}${adjustment} pts`:'—'],
    [totalLabel,scoringBaseline!=null?`${Number(scoringBaseline).toFixed(1)} ${unit}`:'Not modeled'],
    ['Listed absences',`${homeOut+awayOut}`]
  ].map(([label,value])=>`<div class="profileKpi"><span>${esc(label)}</span><b>${esc(value)}</b></div>`).join('');
  const rows=[
    _v15CompareRow('Record',_v15Record(m?.home),_v15Record(m?.away)),
    _v15CompareRow('Rank',_v15Num(m?.home?.pos)!=null?`#${m.home.pos}`:null,_v15Num(m?.away?.pos)!=null?`#${m.away.pos}`:null),
    _v15CompareRow(`Avg ${unit} scored`,hScored,aScored),
    _v15CompareRow(`Avg ${unit} allowed`,_v15Rate(m?.home,'ga'),_v15Rate(m?.away,'ga')),
    _v15CompareRow('Recent form',_v15Form(m?.home),_v15Form(m?.away),true),
    _v15CompareRow('Listed absences',String(homeOut),String(awayOut))
  ].join('');
  return `<div class="analystBox matchProfileCard"><div class="analystBoxTitle">Match profile</div><div class="profileKpis">${kpis}</div><div class="profileCompareHead"><b>${esc(m?.home?.code||m?.home?.name||'Home')}</b><span>team comparison</span><b>${esc(m?.away?.code||m?.away?.name||'Away')}</b></div><div class="profileCompareRows">${rows}</div></div>`;
}
function modelBlock(m){
  const pr=m?.prediction;
  if(!pr)return '<section class="analystPanel"><div class="analystTop"><div class="analystTitle">Model read</div></div><div class="emptyForecast">No model pick yet.</div></section>';
  const op=_v10OfficialPick(m);
  const marketText=op.marketPct!=null?`Consensus snapshot: ${op.marketPct}%`:'No consensus snapshot';
  const summary=edgeBreakdown(m)||`${op.name} is the official model side${op.confidence!=null?` at ${op.confidence}%`:''}.`;
  const base=op.blocked?`<small>Raw upset trigger: ${esc(op.rawName)}</small>`:(pr.base_pick&&pr.base_pick!==op.side?`<small>Base favorite: ${esc(pr.base_pick_name||_v4PickSideLabel(m,pr.base_pick))}</small>`:'');
  const gate=op.blocked?`<div class="upsetGateNotice"><b>Upset watch only:</b> ${esc(op.candidateName)} was flagged by volatility, but ${esc(op.gateReason)}. The official pick remains ${esc(op.name)}.</div>`:'';
  return `<section class="analystPanel"><div class="analystTop"><div class="analystTitle">Model read</div><div class="analystBadge ${op.blocked?'gate':''}">${op.blocked?'upset gate':'official probabilities'}</div></div><div class="analystHero"><div class="analystMain"><div class="analystLabel">Official pick</div><div class="analystPick">${esc(op.name)}</div><p class="analystNote">${esc(op.note)}</p>${gate}</div><div class="analystConfidence"><b>${esc(op.confidence??'—')}%</b><span>official probability</span><small>${esc(marketText)}</small>${base}</div></div><div class="analystGrid upsetGrid"><div class="modelReadColumn">${_v12OutcomeCard(m,op)}${_v15MatchProfile(m,op)}</div><div class="modelReadColumn">${_v6UpsetBox(m)}<div class="analystBox driversBox"><div class="analystBoxTitle">Main drivers</div><div class="factorRows">${_v4FactorRows(pr)}</div></div></div></div><p class="analystSummary">${esc(summary)}</p></section>`;
}

applySettings();applySportNav();setView(SETTINGS.defaultView||'matches');load();
