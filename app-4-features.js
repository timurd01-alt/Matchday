function _insightFocusHTML(focus){
  let h=`<div class="seclbl">In focus</div>`;
  if(focus){
    h+=`<div class="ins-match">${esc(focus.home?.name||'Home')} <span class="evs">v</span> ${esc(focus.away?.name||'Away')}</div><div class="ins-sub">${focus.status==='LIVE'?'Awaiting final':focus.status==='FINISHED'?`Final · ${esc(scorePlainText(focus))}`:`${esc(focus.stage||'')} · ${kickIn(focus.kickoff)}`}</div>`;
    h+=insightModelBlock(focus);
    const x=(focus.markets||{})['1x2']||{};
    if(isMlbForecastPaused(focus)&&x.home_pct!=null)h+='<div class="seclbl" style="margin-top:12px">Market odds</div>';
    if(x.home_pct!=null){const twoWay=_isTwoWay(focus);h+=`<div class="prob insightProb"><div class="problbl"><span>${esc(focus.home?.code||'H')}</span>${twoWay?'':'<span>draw</span>'}<span>${esc(focus.away?.code||'A')}</span></div>${bar1x2(x.home_pct,twoWay?null:x.draw_pct,x.away_pct)}</div>`;}
    const bd=edgeBreakdown(focus);
    if(bd)h+=`<div class="seclbl" style="margin-top:16px">Model read</div><div class="ins-summary"><p>${esc(bd)}</p></div>`;
  }else{
    h+=`<div class="faintline">No match in focus yet.</div>`;
  }
  return h;
}
function _insightFocusPool(M){
  const eligible=M.filter(m=>!_modelIsPast(m)||_modelHasVerifiedLock(m));
  const primary=eligible.filter(m=>isFavoriteMatch(m)&&isVisibleUpcoming(m)).sort(fixtureSort)[0]||eligible.filter(isVisibleUpcoming).sort(fixtureSort)[0]||eligible.find(m=>isFavoriteMatch(m)&&m.status==='FINISHED')||eligible.find(m=>m.status==='FINISHED')||eligible.find(m=>m.status==='LIVE')||eligible[0];
  if(!primary)return [];
  // rotate the primary focus alongside a few other upcoming games worth
  // surfacing, ranked by watchability within a near-term window so a
  // months-away fixture can't outrank this week's games
  const candidates=eligible.filter(m=>isVisibleUpcoming(m)&&m.id!==primary.id);
  const others=nearTermPool(candidates,4)
    .sort((a,b)=>(b.watchability||0)-(a.watchability||0)).slice(0,4);
  return [primary,...others];
}
function renderInsight(){
  const host=$('#insight'),M=DATA.matches||[];
  const pool=_insightFocusPool(M);
  const n=diverseNews(6);
  const newsHTML=n.length?`<div class="seclbl" style="margin-top:18px">Latest from multiple sources</div>`+n.map(a=>`<a class="ins-news" href="${esc(a.link||a.url||'#')}" target="_blank" rel="noopener"><span class="insSource">${esc(sourceName(a))}</span><br>${esc(a.headline||a.title||'Untitled')}</a>`).join(''):'';
  host.innerHTML=`<div id="insightFocus">${_insightFocusHTML(pool[0]||null)}</div>${newsHTML}`;
  runCarousel('insight',pool,$('#insightFocus'),_insightFocusHTML,6000);
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
  let html=`<div class="statsBoard"><div class="seclbl">Match read</div><div class="matchRead">${teamSnap(m?.home||{},'home',m?._comp)}<div class="snapMid"><span>${esc(m?.status||'')}</span><b>${esc(scorePlainText(m||{}))}</b><span>${esc(m?.stage||'')}</span></div>${teamSnap(m?.away||{},'away',m?._comp)}</div>`;
  if(sx){
    html+=`<div class="statHero"><div class="pressureChip"><div class="label">Pressure index</div><div class="value">${Math.round(ph)}–${Math.round(pa)}</div><div class="sub">${esc(leader)} ${leader==='Balanced'?'match':'lean'} · not xG</div></div><div class="pressureChip"><div class="label">Best public signal</div><div class="value">${esc(leader)}</div><div class="sub">based on shots, SOT, possession, corners and cards</div></div></div><div class="statMetrics">${statMetric('Shots',hs.shots,as.shots)}${statMetric('Shots on target',hs.shots_on_target,as.shots_on_target)}${statMetric('Possession',hs.possession,as.possession)}${statMetric('Corners',hs.corners,as.corners)}${statMetric('Fouls',hs.fouls,as.fouls)}${statMetric('Offsides',hs.offsides,as.offsides)}${statMetric('Saves',hs.saves,as.saves)}${statMetric('Cards',`${hs.yellow_cards||0}Y ${hs.red_cards||0}R`,`${as.yellow_cards||0}Y ${as.red_cards||0}R`)}</div>`;
  }else{
    html+=`<div class="emptyStats"><b>${m.status==='FINISHED'?'Box score unavailable':m.status==='LIVE'?'Postgame stats pending':'Box score not yet available'}</b><span>${m.status==='UPCOMING'?'Stats appear in the postgame review.':'This source has not released final team stats for this fixture. The pregame model used form, odds, standings, ratings and market movement instead.'}</span></div>`;
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
    const hmeta=t=>esc(teamStandingsMeta(t,m._comp,{form:true,hideStaleRecord:['NCAAF','NFL'].includes(_v15CompetitionKey(m))}).join(' · '));
    const rawScore=scorePlainText(m).trim()||'TBD';
    const body=safeMatchDetails(m);
    modal.innerHTML=`<section class="matchSheet" role="dialog" aria-modal="true"><div class="modalHero"><button class="modalClose" onclick="closeMatchModal()" aria-label="Close">×</button><div class="modalStage">${esc(m.stage||'Fixture')} · ${esc(m.status==='LIVE'?'AWAITING FINAL':m.status||'')}</div><div class="modalFixture"><div class="modalTeam"><div class="modalCode">${teamFlagHTML(m.home)}${esc(m.home?.code||'HOME')}</div><div class="modalName">${esc(m.home?.name||'Home')}</div><div class="modalMeta">${hmeta(m.home)}</div></div><div class="modalScore"><div class="bigScore">${esc(rawScore)}</div><div class="modalStatus">${m.status==='LIVE'?'Score shown after final':kickIn(m.kickoff)}</div></div><div class="modalTeam away"><div class="modalCode">${esc(m.away?.code||'AWAY')}${teamFlagHTML(m.away,true)}</div><div class="modalName">${esc(m.away?.name||'Away')}</div><div class="modalMeta">${hmeta(m.away)}</div></div></div></div><div class="modalBody">${body}</div></section>`;
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
  const official=officialPrediction(m);
  if(side===official.side&&Number.isFinite(Number(official.confidence)))return Math.round(Number(official.confidence));
  const v=Number(officialPredictionProbabilities(m)?.[side]);
  return Number.isFinite(v)?Math.round(v):null;
}
function _v10OfficialPick(m){
  const pr=m?.prediction||{};
  const u=pr.upset||{};
  const published=officialPrediction(m);
  const market=_v10MarketMap(m);
  // Do not recalculate a pick from live probabilities, odds, or box-score
  // state here. The backend has already applied its gate and frozen the pick.
  const officialSide=published.side;
  const name=published.name||_v10SideName(m,officialSide);
  const conf=Number.isFinite(Number(published.confidence))?Math.round(Number(published.confidence)):null;
  const cand=u.candidate||'';
  const rawSide=officialSide,rawName=name;
  const blocked=!!cand&&u.blocked===true;
  const marketGap=Number.isFinite(Number(u.market_gap_pct))?Math.round(Number(u.market_gap_pct)):null;
  const gateReason=u.gate_reason||u.block_reason||(marketGap!=null?`market gap ${marketGap} pts`:'backend gate');
  const marketPct=_v10Has(market[officialSide])?Math.round(market[officialSide]):null;
  const candName=u.candidate_name||_v10SideName(m,cand);
  const candPct=Number.isFinite(Number(u.candidate_pct))?Math.round(Number(u.candidate_pct)):_v10PctFor(m,cand);
  const officialNote=blocked
    ? `Upset watch: ${candName}. ${gateReason}; the locked pick remains ${name}.`
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
function _isTwoWay(m){return SANDBOX_TWO_WAY.has(String(m?._comp||DATA.comp_key||'').toLowerCase());}
const US_SCORE_TERM={nfl:'points',nba:'points',ncaaf:'points',ncaam:'points',mlb:'runs',nhl:'goals'};
function _totalsUnit(m){return US_SCORE_TERM[String(m?._comp||DATA.comp_key||'').toLowerCase()]||'goals';}
function edgeBreakdown(m){
  const pr=m?.prediction, x=(m?.markets||{})['1x2']||{};
  if(!pr)return '';
  const op=_v10OfficialPick(m);
  const pickSide=op.side;
  const mkmap={h:x.home_pct,d:x.draw_pct,a:x.away_pct};
  const modelP=officialPredictionProbabilities(m)?.[pickSide];
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
    let goalsLine=`${unit[0].toUpperCase()+unit.slice(1)} market: over ${tot.line} ${tot.over_pct}%, under ${tot.line} ${tot.under_pct}%.`;
    if(modelTot&&modelTot.pick)goalsLine+=` Model expects ${modelTot.expected} — leans ${modelTot.pick}.`;
    bits.push(goalsLine);
  }else if(modelTot&&modelTot.expected!=null){
    bits.push(`Model expects ${modelTot.expected} ${_totalsUnit(m)} — no market line yet.`);
  }
  return bits.join(' ');
}
function _v6UpsetBox(m){
  const pr=m?.prediction||{},u=pr.upset||{},op=_v10OfficialPick(m);
  if(!u.radar)return `<div class="analystBox upsetBox"><div class="analystBoxTitle">Upset radar</div><div class="emptyForecast" style="padding:12px">No upset risk: this match does not have both a clear standings mismatch and an 8+ point model/market disagreement.</div></div>`;
  const shownActive=!!u.triggered&&!op.blocked;
  const cls=_v6UpsetClass(u.score,shownActive);
  const status=op.blocked?'watch only · gate blocked':shownActive?'upset pick active':'watch only';
  const upsetTwoWay=_isTwoWay(m);
  const fallbackReason=upsetTwoWay?'Volatility profile calculated from low-scoring profile, favorite softness, and team gap.':'Volatility profile calculated from draw pressure, low-scoring profile, favorite softness, and team gap.';
  const reason=op.blocked?`${u.reason||'Volatility profile detected.'} · ${op.gateReason}.`:u.reason||fallbackReason;
  return `<div class="analystBox upsetBox"><div class="analystBoxTitle">Upset radar</div><div class="upsetHero"><div class="candidate"><span>candidate</span><b>${esc(u.candidate_name||'Underdog')}</b></div><div class="upsetScoreDial ${cls}"><b>${esc(u.score??'—')}</b><small>/100</small></div></div><div class="probLines"><div class="probLine"><span class="sideName">${esc(u.favorite_name||'Favorite')}</span><span class="probTrack"><i class="probFill h" style="width:${Math.max(3,Number(u.favorite_pct)||0)}%"></i></span><span class="pct">${esc(u.favorite_pct??'—')}%</span></div><div class="probLine"><span class="sideName">${esc(u.candidate_name||'Underdog')}</span><span class="probTrack"><i class="probFill a" style="width:${Math.max(3,Number(u.candidate_pct)||0)}%"></i></span><span class="pct">${esc(u.candidate_pct??'—')}%</span></div></div><div class="upsetMath"><span>Temp<b class="hot">T ${esc(u.temperature??'—')}</b></span><span>Variance<b>${esc(u.variance_pct??'—')}%</b></span><span>${upsetTwoWay?'Low scoring':'Low goals'}<b>${esc(u.low_goal_pct??'—')}%</b></span></div><p class="upsetReason">${esc(reason)}</p><span class="upsetTriggered ${op.blocked?'blocked':shownActive?'':'watch'}">${esc(status)}</span></div>`;
}
/* dedup */
function insightModelBlock(m){
  if(isMlbForecastPaused(m))return forecastPauseHTML(m);
  const pr=m&&m.prediction;
  if(!pr)return '<div class="seclbl">Model pick</div><div class="nomk">No model pick yet.</div>';
  const op=_v10OfficialPick(m),edge=_v10OfficialEdge(m,op);
  const cls=(edge!=null&&Math.abs(edge)>=6?'edge ':'')+(op.blocked?'gate':'');
  return `<div class="seclbl">Model pick</div><div class="pick insightPick ${cls}"><span class="pl">Pick</span><span class="pn">${esc(op.name)}</span><span class="pc">${esc(op.confidence??'—')}%</span><span class="pnote">${esc(op.note)}</span></div>`;
}
function cardHTML(m,opts){
  opts=opts||{};
  const pending=m.status==='LIVE',stale=isStaleUpcoming(m);
  const displayStatus=stale?'PAST / REFRESH':pending?'AWAITING FINAL':m.status;
  const statusClass=stale?'PAST_REFRESH':pending?'RESULT_PENDING':m.status;
  const x=(m.markets&&m.markets['1x2'])||{};const hfl=teamFlagHTML(m.home),afl=teamFlagHTML(m.away,true);
  const probTop=x.home_pct!=null?`<div class="prob"><div class="problbl"><span>${esc(m.home.code||m.home.name)}</span><span>Market read</span><span>${esc(m.away.code||m.away.name)}</span></div>${bar1x2(x.home_pct,_isTwoWay(m)?null:x.draw_pct,x.away_pct)}</div>`:`<div class="prob"><div class="nomk">${esc(oddsEtaLabel(m)||'No market snapshot yet')}</div></div>`;
  const pr=m.prediction;const op=pr?_v10OfficialPick(m):null;const edge=op?_v10OfficialEdge(m,op):null;const trend=probabilitySparkline(m);
  const pick=isMlbForecastPaused(m)?forecastPauseHTML(m):(!opts.hidePick&&op)?`<div class="pick ${edge!=null&&Math.abs(edge)>=6?'edge':''} ${op.blocked?'gate':''}"><span class="pl">Pick</span><span class="pn">${esc(op.name)}</span><span class="pc">${esc(op.confidence??'—')}%</span><span class="pnote">${esc(op.note||'')}</span>${trend}</div>`:'';
  const probChanged=!!probabilityMovement(m);
  const timing=pending?'score after final':m.status==='FINISHED'?'postgame':stale?'past kickoff':kickIn(m.kickoff);
  return `<article class="card${SETTINGS.showDetails?'':' compactCard'}${probChanged?' probChanged':''}" data-id="${esc(m.id)}"><div class="head" onclick="openMatchModal(this.closest('article').dataset.id)"><div class="metarow"><span class="stage">${esc(m.stage||'Fixture')}</span>${m._comp&&!DATA_FILE?`<span class="compTag">${esc(m._comp)}</span>`:''}<span class="wstar ${wlHas(m.home.name)||wlHas(m.away.name)?'on':''}" onclick="event.stopPropagation();wlToggle('${esc(m.home.name)}')" title="Watch">&#9733;</span>${m.weather?`<a class="wxchip" href="${esc(m.weather.source_url||'https://open-meteo.com/')}" target="_blank" rel="noopener noreferrer" onclick="event.stopPropagation()" title="Weather data by Open-Meteo"><b>${m.weather.temp_c}&deg;</b>${m.weather.wind_kph>=20?` ${m.weather.wind_kph}km/h`:''}${m.weather.rain_pct>=40?` &#9730;${m.weather.rain_pct}%`:''}<small> Open-Meteo</small></a>`:''}<span class="spacer"></span><span class="pill ${esc(statusClass)}">${esc(displayStatus)}</span></div><div class="fixture"><div class="side"><div class="tname">${teamMarkHTML(m.home)}<span class="teamNameText">${hfl}${esc(m.home.name)}</span></div><div class="tsub"><span>${esc(m.home.code)}</span>${teamStandingsMeta(m.home,m._comp).map(p=>`<span>${esc(p)}</span>`).join('')}</div></div><div class="center"><div class="score">${scoreText(m)}</div><div class="kick">${timing}</div></div><div class="side away"><div class="tname"><span class="teamNameText">${esc(m.away.name)}${afl}</span>${teamMarkHTML(m.away,'away')}</div><div class="tsub"><span>${esc(m.away.code)}</span>${teamStandingsMeta(m.away,m._comp).map(p=>`<span>${esc(p)}</span>`).join('')}</div></div></div>${probTop}${pick}<div class="expander"></div></div></article>`;
}
function _modelRow(m){
  const pr=m.prediction||{},op=_v10OfficialPick(m),kind=_modelEdgeKind(pr),tag=_modelTag(m),arch=_modelIsArchived(m);
  const edgeVal=_v10OfficialEdge(m,op);const edge=(edgeVal==null||arch)?'':`${edgeVal>0?'+':''}${edgeVal}`;
  const sub=arch?`${op.confidence??'—'}% · ${_modelFinalText(m)}`:`${op.confidence??'—'}% · ${_modelMarketText(m,op.side)}`;
  const statusKind=op.blocked?'gate':tag.kind;const statusTxt=op.blocked?'UPSET WATCH':tag.txt;
  return `<div class="modelRow ${arch?'archived':''}" onclick="openMatchModal('${esc(String(m.id||''))}')"><div class="modelMatch"><div class="teams">${esc(m.home?.code||m.home?.name||'H')} v ${esc(m.away?.code||m.away?.name||'A')}</div><div class="meta">${esc(m.stage||'Fixture')} · ${_modelWhen(m)}</div></div><div class="modelChoice"><div class="small">${arch?'Archived pick':'Official pick'}</div><div class="main">${esc(op.name||'No pick')}</div><div class="sub">${esc(sub)}</div></div>${_modelBars(m)}<div class="modelStatus"><span class="tag ${statusKind}">${statusTxt}</span>${edge?`<span class="tag ${kind}">${edge} edge</span>`:''}</div></div>`;
}
function _modelSpotlight(list){
  const pregame=(list||[]).filter(isVisibleUpcoming);const m=pregame.find(x=>(_v10OfficialEdge(x,_v10OfficialPick(x))||0)>=6)||pregame[0];if(!m)return'';
  const pr=m.prediction||{},op=_v10OfficialPick(m),kind=op.blocked?'gate':_modelEdgeKind(pr);const edgeVal=_v10OfficialEdge(m,op);const edge=edgeVal==null?'No edge data':`${edgeVal>0?'+':''}${edgeVal} vs market`;
  return `<div class="modelSpot"><div class="modelSpotHead"><span>Best current read</span><span>${esc(m.stage||'Fixture')} · ${_modelWhen(m)}</span></div><div class="modelSpotBody"><div class="modelSpotTeam"><span class="code">${esc(m.home?.code||'HOME')}</span><div class="name">${esc(m.home?.name||'Home')}</div></div><div class="modelPickDial"><div class="lbl">Official pick</div><div class="pickName">${esc(op.name||'No pick')}</div><div class="conf">${op.confidence??'—'}%</div><span class="edgePill ${kind}">${esc(op.blocked?'upset watch only':edge)}</span></div><div class="modelSpotTeam away"><span class="code">${esc(m.away?.code||'AWAY')}</span><div class="name">${esc(m.away?.name||'Away')}</div></div></div></div>`;
}
function _v4UpsetRows(){
  const M=(DATA.matches||[]).filter(isVisibleUpcoming).filter(m=>m.prediction?.upset?.radar);
  return M.map(m=>{
    const pr=m.prediction||{},u=pr.upset||{},op=_v10OfficialPick(m);
    if(u.radar){
      const risk=Number(u.score)||0;const active=!!u.triggered&&!op.blocked;const cls=active?'trigger':risk>=70?'high':risk>=50?'med':'low';
      const reason=`${u.candidate_name||'Underdog'} · standings gap ${u.standings_gap_pct??'—'} pts · model ${u.upset_edge>0?'+':''}${u.upset_edge??'—'} vs market`;
      return {m,risk,cls,reason,triggered:active,blocked:op.blocked};
    }
  }).sort((a,b)=>b.risk-a.risk).slice(0,6);
}
function simpleMatchFallbackPanel(m){
  const pr=m?.prediction||{},op=_v10OfficialPick(m);const x=(m?.markets||{})['1x2']||{};const probs=officialPredictionProbabilities(m);
  const pH=Math.round(Number(probs.h??x.home_pct??0));const pD=Math.round(Number(probs.d??x.draw_pct??0));const pA=Math.round(Number(probs.a??x.away_pct??0));
  return `<div class="detailGrid v8Fallback"><div class="readCard"><div class="seclbl">Model read</div><div class="pick insightPick ${op.blocked?'gate':''}"><span class="pl">Pick</span><span class="pn">${esc(op.name||'No pick')}</span><span class="pc">${esc(op.confidence??'—')}%</span><span class="pnote">${esc(op.note||'')}</span></div><div class="prob" style="margin-top:12px"><div class="problbl"><span>${esc(m?.home?.code||'Home')}</span><span>draw</span><span>${esc(m?.away?.code||'Away')}</span></div>${bar1x2(pH,pD,pA)}</div>${edgeBreakdown(m)?`<div class="ins-summary" style="margin-top:12px"><p>${esc(edgeBreakdown(m))}</p></div>`:''}</div><div class="readCard">${marketPanel(m)}</div><div class="statsBoard">${statsPanel(m)}</div><div class="lineupBoard">${lineupsPanel(m)}</div></div>`;
}


/* ===== BRACKET V11 — render readable round-by-round board ===== */
function _v11RoundLabel(name){
  const x=String(name||'');
  return {'Quarter-finals':'Quarterfinals','Semi-finals':'Semifinals','Third-place playoff':'Third place'}[x]||x;
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
  if(String(m?.status||'').toUpperCase()!=='FINISHED')return null;
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
  try{fl=code?uiFlag(code):''}catch(e){fl=''}
  return `<div class="brWideTeam ${win?'win':''} ${isPath?'path':''}"><div class="brWideName">${slot?`<span class="brWideSlot">${esc(slot)}</span>`:''}${fl?`<span class="flag">${fl}</span>`:''}${code?`<span class="brWideCode">${esc(code)}</span>`:''}<span class="brWideText">${esc(nm)}</span></div><div class="brWideScore">${score!=null&&score!==''?esc(score):''}</div></div>`;
}
function _v11StatusText(m){
  const st=String(m?.status||'').toUpperCase();
  if(st==='LIVE')return 'AWAITING FINAL';
  if(st==='FINISHED')return 'FT';
  if(m?.kickoff){try{return dt(m.kickoff)}catch(e){return 'Scheduled'}}
  return st&&st!=='PROJECTED'?'TBD':'Path';
}
function _v11MatchCard(m,roundName){
  if(!m)return `<div class="brWideEmpty">Waiting for matchup</div>`;
  const st=String(m.status||'').toUpperCase();
  const cls=`brWideMatch ${st==='FINISHED'?'done':''} ${/Final/i.test(roundName)?'final':''} ${/Third/i.test(roundName)?'third':''}`;
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
function scrollBracket(direction){
  const shell=$('#view-bracket .bracketWideShell');
  if(!shell)return;
  const reduceMotion=window.matchMedia&&window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  shell.classList.remove('isGliding');void shell.offsetWidth;shell.classList.add('isGliding');
  clearTimeout(window.__bracketMotionTimer);window.__bracketMotionTimer=setTimeout(()=>shell.classList.remove('isGliding'),420);
  shell.scrollBy({left:direction*Math.max(300,shell.clientWidth*.72),behavior:reduceMotion?'auto':'smooth'});
}
function _bracketScrollControls(){
  return `<div class="bracketScrollTools"><span>Browse rounds</span><button type="button" class="bracketScrollBtn" onclick="scrollBracket(-1)" aria-label="Scroll bracket left">&larr;</button><button type="button" class="bracketScrollBtn" onclick="scrollBracket(1)" aria-label="Scroll bracket right">&rarr;</button></div>`;
}
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
  host.innerHTML=`<div class="bracketStageHeader"><div class="vhead">Bracket Simulator</div><div class="bracketLegend">${toggle}<button class="btmbtn" onclick="bracketSimReset()">Reset to model picks</button></div></div><div class="bracketWideHint"><span>Click a team to override the model's pick for that match — it cascades through the rest of the bracket.</span>${_bracketScrollControls()}</div><div class="bracketWideShell"><div class="bracketWideBoard">${cols}</div></div>`;
}
// The CFP is a 12-team single-elimination bracket (4 first-round games,
// seeds 5-12; the top 4 seeds get byes straight to the quarterfinals) --
// nothing like a 32-team World Cup knockout stage. The generic bracket
// renderer below hardcodes exactly that WC shape (Round of 32 down to a
// third-place playoff) and silently drops any round whose name doesn't
// canonicalize to one of those soccer labels, which is every CFP round
// name the backend actually sends ("CFP First Round (model projection)"
// etc.) -- so NCAAF always fell back to a fake 32-team bracket built from
// group standings that don't apply to college football at all.
function _cfpRoundKey(name){
  const x=String(name||'').toLowerCase();
  if(/first round/.test(x))return'first';
  if(/quarter/.test(x))return'quarter';
  if(/semi/.test(x))return'semi';
  if(/national championship|championship|^final$/.test(x))return'final';
  return'';
}
function _cfpBracketRounds(){
  const grouped={first:[],quarter:[],semi:[],final:[]};
  (Array.isArray(DATA.bracket)?DATA.bracket:[]).forEach(r=>{
    const key=_cfpRoundKey(r.round||r.stage||r.name);
    if(key)grouped[key].push(...(r.matches||[]));
  });
  // The model can only seed the first two rounds (quarterfinal matchups
  // depend on results the first round hasn't produced yet), so later
  // rounds get the same "Winner of X" placeholder-path treatment the WC
  // bracket already uses for its own not-yet-knowable rounds.
  if(!grouped.semi.length)grouped.semi=[
    {stage:'Semifinal 1',home:'Winner QF 1',home_slot:'path',away:'Winner QF 2',away_slot:'path',status:'TBD',score:{}},
    {stage:'Semifinal 2',home:'Winner QF 3',home_slot:'path',away:'Winner QF 4',away_slot:'path',status:'TBD',score:{}}
  ];
  if(!grouped.final.length)grouped.final=[
    {stage:'National Championship',home:'Winner SF 1',home_slot:'path',away:'Winner SF 2',away_slot:'path',status:'TBD',score:{}}
  ];
  return [
    {label:'First Round',matches:grouped.first},
    {label:'Quarterfinals',matches:grouped.quarter},
    {label:'Semifinals',matches:grouped.semi},
    {label:'National Championship',matches:grouped.final}
  ];
}
function _renderCFPBracket(host){
  const official=Array.isArray(DATA.bracket)&&DATA.bracket.some(r=>(r.matches||[]).length);
  const rounds=_cfpBracketRounds();
  host.innerHTML=`<div class="bracketStageHeader"><div class="vhead">CFP Bracket</div><div class="bracketLegend">${official?'Official + projected paths':'Projected bracket (model seeding)'}</div></div><div class="bracketWideShell"><div class="bracketWideBoard">${rounds.map(r=>`<section class="brWideRound"><div class="brWideTitle"><b>${esc(r.label)}</b><span>${r.matches.length||0}</span></div><div class="brWideStack">${(r.matches.length?r.matches:[null]).map(m=>_v11MatchCard(m,r.label)).join('')}</div></section>`).join('')}</div></div>`;
}
function _uclRoundTies(fixtures,singleMatch=false){
  if(singleMatch)return (fixtures||[]).map((match,index)=>({key:`final-${index}`,legs:[match],teams:[match.home,match.away]}));
  const ties=new Map();
  (fixtures||[]).forEach((match,index)=>{
    const teams=[match.home,match.away].filter(Boolean);
    const key=teams.length===2?teams.map(team=>String(team).toLowerCase()).sort().join('|'):`unknown-${index}`;
    if(!ties.has(key))ties.set(key,{key,legs:[],teams:[match.home,match.away]});
    ties.get(key).legs.push(match);
  });
  return [...ties.values()];
}
function _uclTieCard(tie,roundName){
  if(roundName==='Final')return _v11MatchCard(tie.legs[0],roundName);
  const teams=tie.teams||[],totals=new Map(teams.map(team=>[String(team||''),0]));
  let scoredLegs=0;
  (tie.legs||[]).forEach(leg=>{
    const hs=Number(leg?.score?.home),as=Number(leg?.score?.away);
    if(Number.isFinite(hs)&&Number.isFinite(as)){
      totals.set(String(leg.home||''),(totals.get(String(leg.home||''))||0)+hs);
      totals.set(String(leg.away||''),(totals.get(String(leg.away||''))||0)+as);
      scoredLegs+=1;
    }
  });
  const legNote=(tie.legs||[]).map((leg,index)=>{
    const hs=leg?.score?.home,as=leg?.score?.away,score=hs!=null&&as!=null?`${hs}–${as}`:_v11StatusText(leg);
    return `Leg ${index+1}: ${leg.home||'TBD'} ${score} ${leg.away||'TBD'}`;
  }).join(' · ');
  const row=team=>`<div class="brWideTeam"><div class="brWideName"><span class="brWideCode">${esc(codeForTeam(team,'')||'')}</span><span class="brWideText">${esc(team||'TBD')}</span></div><div class="brWideScore">${scoredLegs?esc(totals.get(String(team||''))||0):''}</div></div>`;
  return `<article class="brWideMatch ${scoredLegs===2?'done':''}"><div class="brWideMeta"><span>${scoredLegs?'Aggregate':'Two-leg tie'}</span><span class="brWideStatus">${scoredLegs}/2 legs</span></div>${teams.map(row).join('')}<div class="faintline">${esc(legNote)}</div></article>`;
}
function _renderUCLBracket(host){
  const rounds=_bracketSourceMap(DATA.bracket||[]);
  const names=['Knockout phase play-offs','Round of 16','Quarter-finals','Semi-finals','Final'];
  const columns=names.filter(name=>(rounds[name]||[]).length).map(name=>{
    const ties=_uclRoundTies(rounds[name]||[],name==='Final');
    return `<section class="brWideRound"><div class="brWideTitle"><b>${esc(name)}</b><span>${ties.length} ${ties.length===1?'tie':'ties'}</span></div><div class="brWideStack">${ties.map(tie=>_uclTieCard(tie,name)).join('')}</div></section>`;
  }).join('');
  host.innerHTML=`<div class="bracketStageHeader"><div class="vhead">Champions League knockout bracket</div><div class="bracketLegend">Official knockout ties</div></div><div class="bracketWideHint"><span>Playoffs through semifinals are decided on aggregate over two legs. The final is one match.</span>${_bracketScrollControls()}</div><div class="bracketWideShell"><div class="bracketWideBoard">${columns}</div></div>`;
}
function renderBracket(){
  const host=$('#view-bracket');
  if(!host)return;
  if(DATA.comp_key==='NCAAM'&&DATA.bracketology){_v14RenderBracketology(host,DATA.bracketology);return}
  if(DATA.comp_key==='NCAAF'){_renderCFPBracket(host);return}
  if(DATA.comp_key==='UCL'){_renderUCLBracket(host);return}
  if(navProfile()==='us_sport'){
    // NFL/NBA/MLB/NHL playoffs are real single-elimination brackets, but
    // nothing in the backend computes their seeding (no NFL wild-card/bye
    // logic, no NBA/NHL conference bracket, no MLB Division/Championship
    // Series structure) the way CFP and March Madness projections exist.
    // Falling through to the generic renderer below would silently show
    // the same fake 32-team World Cup group-into-knockout shape here too,
    // built from standings data that isn't even grouped for these sports
    // -- an honest "not available" beats a wrong bracket.
    host.innerHTML=`<div class="vhead">Playoff Bracket</div><div class="empty">Playoff bracket projections aren\'t built for this league yet.</div>`;
    return;
  }
  const mode=window.__bracketMode||'view';
  const toggle=`<button class="btmbtn" onclick="window.__bracketMode='${mode==='view'?'simulate':'view'}';renderBracket();">${mode==='view'?'Simulate the bracket':'Back to bracket view'}</button>`;
  if(mode==='simulate'){renderBracketSim(host,toggle);return;}
  const official=Array.isArray(DATA.bracket)&&DATA.bracket.some(r=>(r.matches||[]).length);
  const rounds=typeof _completeRounds==='function'?_completeRounds():projectedRounds();
  const names=['Round of 32','Round of 16','Quarter-finals','Semi-finals','Final','Third-place playoff'];
  const projectedCount=(()=>{try{return Math.min(getProjectedSlots().length,32)}catch(e){return 0}})();
  host.innerHTML=`<div class="bracketStageHeader"><div class="vhead">Tournament bracket</div><div class="bracketLegend">${toggle}${official?'Official + projected paths':'Projected bracket'}</div></div><div class="bracketWideHint"><span><b>${projectedCount}</b> projected qualifiers · cards stay readable instead of shrinking</span>${_bracketScrollControls()}</div><div class="bracketWideShell"><div class="bracketWideBoard">${names.map(n=>_v11RoundCol(rounds,n)).join('')}</div></div>`;
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
  const unit=_totalsUnit(m);
  const twoWay=_isTwoWay(m);
  const drawNote=twoWay?null:(dp>=30?'high draw pressure':dp>=25?'moderate draw pressure':'low draw pressure');
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
  const classMeta=sportClassMeta(m?.prediction||{},m);
  const compareLabel1=hasMarket?'Market on pick':(classMeta.label||'Personnel edge');
  const classEdge=why.class!=null?why.class*sideSign:null;
  const compareVal1=hasMarket?`${marketPct}%`:(classMeta.edge_available===false?'Not scored':classMeta.coverage==='unavailable'?'Not available':classEdge!=null?`${classMeta.coverage==='partial'?'Partial · ':''}${pts(classEdge)}`:'—');
  const compareLabel2=hasMarket?'Model edge':'Elo edge';
  const eloEdge=why.elo!=null?why.elo*sideSign:null;
  const compareCls2=hasMarket?edgeCls:(eloEdge==null?'edgeFlat':eloEdge>0?'edgePos':eloEdge<0?'edgeNeg':'edgeFlat');
  const compareVal2=hasMarket?(edge!=null?`${edge>0?'+':''}${edge} pts`:'—'):(eloEdge!=null?pts(eloEdge):'—');
  const risk=op?.blocked?`Upset gate blocked · ${esc(op.gateReason||'market gap too wide')}`:(drawNote?`${drawNote} · ${goalNote}`:goalNote);
  return `<div class="analystBox probMatrixCard"><div class="analystBoxTitle">Probability check</div><div class="probMatrix"><div class="probTiles">${_v12ProbTile(m?.home?.code||m?.home?.name||'Home',hp,'h',side==='h')}${twoWay?'':_v12ProbTile('Draw',dp,'d',side==='d')}${_v12ProbTile(m?.away?.code||m?.away?.name||'Away',ap,'a',side==='a')}</div><div class="probCompareGrid"><div class="probCompareItem"><span>Official side</span><b>${esc(op?.name||'No pick')}</b></div><div class="probCompareItem"><span>${compareLabel1}</span><b>${esc(compareVal1)}</b></div><div class="probCompareItem ${compareCls2}"><span>${compareLabel2}</span><b>${esc(compareVal2)}</b></div></div><p class="probContextLine">${risk}</p></div></div>`;
}
function _v15Num(v){
  if(v===null||v===undefined||v==='')return null;
  const n=Number(v);return Number.isFinite(n)?n:null;
}
function _v15Record(team,m){
  if(['NCAAF','NFL'].includes(_v15CompetitionKey(m))&&team?.season_stale)return null;
  const p=_v15Num(team?.pld),w=_v15Num(team?.w),d=_v15Num(team?.d),l=_v15Num(team?.l);
  if(!p||w==null||l==null)return null;
  const twoWay=SANDBOX_TWO_WAY.has(String(m?._comp||DATA.comp_key||'').toLowerCase());
  return (d==null||twoWay)?`${w}-${l}`:`${w}-${d}-${l}`;
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
function _v15CompetitionKey(m){
  return String(m?._comp||DATA.comp_key||'').toUpperCase();
}
function _v15PlacementLabel(m){
  const comp=_v15CompetitionKey(m);
  if(['WC','UCL','EPL','LALIGA','SERIEA','BUNDESLIGA','LIGUE1'].includes(comp))return 'Table position';
  if(['NFL','MLB','NHL'].includes(comp))return 'Division position';
  if(['NBA','NCAAF','NCAAM'].includes(comp))return 'Conference position';
  return 'Standings position';
}
function _v15Ordinal(value){
  const n=_v15Num(value);if(n==null)return null;
  const whole=Math.trunc(n),mod100=whole%100;
  const suffix=mod100>=11&&mod100<=13?'th':({1:'st',2:'nd',3:'rd'}[whole%10]||'th');
  return `${whole}${suffix}`;
}
function _v15Placement(team){
  const position=_v15Ordinal(team?.pos);if(!position)return null;
  const context=team?.group?` · ${team.group}`:'';
  const stale=team?.season_stale?' · prior season':'';
  return `${position}${context}${stale}`;
}
function _v15RankLabel(m){
  const sources=[m?.home?.rank_source,m?.away?.rank_source].filter(Boolean);
  if(sources.includes('model_projection'))return 'Model projection rank';
  if(sources.includes('poll'))return 'Poll rank';
  return ['NCAAF','NCAAM'].includes(_v15CompetitionKey(m))?'Poll / model rank':'Model rank';
}
function _v15MatchProfile(m,op){
  const pr=m?.prediction||{},probs=_v4ModelProbs(m)||{},side=op?.side||'';
  const quality=pr.data_quality||{},sample=quality.games||{};
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
    ['Model separation',separation!=null?`${separation} pts`:'—','Gap between the two most likely model outcomes.'],
    ['Probability adjustment',adjustment!=null?`${adjustment>0?'+':''}${adjustment} pts`:'—','Difference between the raw model and the final official probability.'],
    [totalLabel,scoringBaseline!=null?`${Number(scoringBaseline).toFixed(1)} ${unit}`:'Not modeled'],
    ['Data sample',sample.home!=null&&sample.away!=null?`${sample.home} / ${sample.away} games`:'Not reported',quality.note||'Current-season games available to the model.']
  ].map(([label,value,help])=>`<div class="profileKpi"><span>${esc(label)}${help?metricHelp(label,help):''}</span><b>${esc(value)}</b></div>`).join('');
  const rows=[
    _v15CompareRow('Record',_v15Record(m?.home,m),_v15Record(m?.away,m)),
    _v15CompareRow(_v15PlacementLabel(m),_v15Placement(m?.home),_v15Placement(m?.away)),
    _v15CompareRow(_v15RankLabel(m),_v15Num(m?.home?.model_rank)!=null?`#${m.home.model_rank}`:null,_v15Num(m?.away?.model_rank)!=null?`#${m.away.model_rank}`:null),
    _v15CompareRow('Opponent-adjusted rating',_v15Num(m?.home?.srs)!=null?Number(m.home.srs).toFixed(1):null,_v15Num(m?.away?.srs)!=null?Number(m.away.srs).toFixed(1):null),
    _v15CompareRow(`Avg ${unit} scored`,hScored,aScored),
    _v15CompareRow(`Avg ${unit} allowed`,_v15Rate(m?.home,'ga'),_v15Rate(m?.away,'ga')),
    _v15CompareRow('Recent form',_v15Form(m?.home),_v15Form(m?.away),true),
    _v15CompareRow('Listed absences',String(homeOut),String(awayOut))
  ].join('');
  return `<div class="analystBox matchProfileCard"><div class="analystBoxTitle">Match profile</div><div class="profileKpis">${kpis}</div><div class="profileCompareHead"><b>${esc(m?.home?.code||m?.home?.name||'Home')}</b><span>team comparison</span><b>${esc(m?.away?.code||m?.away?.name||'Away')}</b></div><div class="profileCompareRows">${rows}</div></div>`;
}
function neutralVenuePanel(m){
  // pr.neutral_venue_probs is a real second predict() run with the home-
  // advantage term zeroed (fetch_data.py), not a client-side estimate --
  // only present on matches that haven't finished, and dropped entirely
  // once a pick locks (apply_locked_picks() replaces the whole prediction
  // object), so this can never imply the official, locked forecast changed.
  const pr=m?.prediction;
  if(!pr||!pr.neutral_venue_probs)return'';
  const side=pr.regulation_pick||pr.pick;
  const probs=pr.adjusted||pr.blend||{};
  const cur=Number(probs[side]),neu=Number(pr.neutral_venue_probs[side]);
  if(!Number.isFinite(cur)||!Number.isFinite(neu))return'';
  const delta=Math.round(neu)-Math.round(cur);
  const pickName=esc(_v4PickSideLabel(m,side));
  return `<div class="analystBox neutralVenueBox"><div class="analystBoxTitle">Neutral venue <span class="hypotheticalTag">hypothetical, not the official forecast</span></div><div class="neutralVenueRow"><span>Current (home field)</span><b>${pickName} ${Math.round(cur)}%</b></div><div class="neutralVenueRow"><span>If this were a neutral site</span><b>${pickName} ${Math.round(neu)}%</b></div><div class="neutralVenueDelta ${delta<0?'down':delta>0?'up':''}">${delta===0?'No change — home field isn’t moving this pick':`${delta>0?'+':''}${delta} point${Math.abs(delta)===1?'':'s'} from removing home advantage`}</div></div>`;
}
function modelBlock(m){
  const pr=m?.prediction;
  if(!pr)return '<section class="analystPanel"><div class="analystTop"><div class="analystTitle">Model read</div></div><div class="emptyForecast">No model pick yet.</div></section>';
  const op=_v10OfficialPick(m);
  const marketText=op.marketPct!=null?`Consensus snapshot: ${op.marketPct}%`:'No consensus snapshot';
  const summary=edgeBreakdown(m)||`${op.name} is the official model side${op.confidence!=null?` at ${op.confidence}%`:''}.`;
  const base=op.blocked?`<small>Raw upset trigger: ${esc(op.rawName)}</small>`:(pr.base_pick&&pr.base_pick!==op.side?`<small>Base favorite: ${esc(pr.base_pick_name||_v4PickSideLabel(m,pr.base_pick))}</small>`:'');
  const gate=op.blocked?`<div class="upsetGateNotice"><b>Upset watch only:</b> ${esc(op.candidateName)} was flagged by volatility, but ${esc(op.gateReason)}. The official pick remains ${esc(op.name)}.</div>`:'';
  return `<section class="analystPanel"><div class="analystTop"><div class="analystTitle">Model read</div><div class="analystBadge ${op.blocked?'gate':''}">${op.blocked?'upset gate':'official probabilities'}</div></div><div class="analystHero"><div class="analystMain"><div class="analystLabel">Official pick</div><div class="analystPick">${esc(op.name)}</div><p class="analystNote">${esc(op.note)}</p>${gate}</div><div class="analystConfidence"><b>${esc(op.confidence??'—')}%</b><span>official probability</span><small>${esc(marketText)}</small>${base}</div></div><div class="analystGrid upsetGrid"><div class="modelReadColumn">${_v12OutcomeCard(m,op)}${_v15MatchProfile(m,op)}</div><div class="modelReadColumn">${_v6UpsetBox(m)}<div class="analystBox driversBox"><div class="analystBoxTitle">Main drivers</div><div class="factorRows">${_v4FactorRows(pr,m)}</div></div>${neutralVenuePanel(m)}</div></div><p class="analystSummary">${esc(summary)}</p></section>`;
}

const startupParams=new URLSearchParams(window.location.search);
const requestedView=startupParams.get('view');
const requestedSport=String(startupParams.get('sport')||'').toLowerCase();
const requestedMatch=startupParams.get('match');
if(Object.prototype.hasOwnProperty.call(SPORT_LABELS,requestedSport)){
  DATA_FILE=`data_${requestedSport}.json`;
  try{localStorage.setItem('matchday.sport',DATA_FILE)}catch(e){}
}
const initialView=requestedView&&document.getElementById('view-'+requestedView)?requestedView:(SETTINGS.defaultView||'matches');
applySettings();applySportNav();setView(initialView);
bootAccount(); // resolves a returning sign-in redirect, or restores an existing session
load().then(()=>{
  if(requestedView&&document.getElementById('view-'+requestedView))setView(requestedView);
  if(requestedMatch&&BYID[requestedMatch])openMatchModal(requestedMatch);
});
