function _insightFocusHTML(focus){
  let h=`<div class="seclbl">In focus</div>`;
  if(focus){
    h+=`<div class="ins-match">${esc(focus.home?.name||'Home')} <span class="evs">v</span> ${esc(focus.away?.name||'Away')}</div><div class="ins-sub">${focus.status==='LIVE'?'Awaiting final':focus.status==='FINISHED'?`Final · ${esc(scorePlainText(focus))}`:`${esc(focus.stage||'')} · ${kickIn(focus.kickoff)}`}</div>`;
    h+=insightModelBlock(focus);
    const x=(focus.markets||{})['1x2']||{};
    if(x.home_pct!=null){const twoWay=_isTwoWay(focus);h+=`<div class="prob insightProb"><div class="problbl"><span>${esc(focus.home?.code||'H')}</span>${twoWay?'':'<span>draw</span>'}<span>${esc(focus.away?.code||'A')}</span></div>${bar1x2(x.home_pct,twoWay?null:x.draw_pct,x.away_pct)}</div>`;}
  }else{
    h+=`<div class="faintline">No match in focus yet.</div>`;
  }
  return h;
}
function _insightFocusPool(M){
  const eligible=M;
  const primary=eligible.filter(m=>isFavoriteMatch(m)&&isVisibleUpcoming(m)).sort(fixtureSort)[0]||eligible.filter(isVisibleUpcoming).sort(fixtureSort)[0]||eligible.find(m=>isFavoriteMatch(m)&&m.status==='FINISHED')||eligible.find(m=>m.status==='FINISHED')||eligible.find(m=>m.status==='LIVE')||eligible[0];
  if(!primary)return [];
  // rotate the primary focus alongside a few other upcoming games within a
  // near-term window so a months-away fixture can't outrank this week's games
  const candidates=eligible.filter(m=>isVisibleUpcoming(m)&&m.id!==primary.id);
  const others=nearTermPool(candidates,4).slice(0,4);
  return [primary,...others];
}
function renderInsight(){
  const host=$('#insight');
  if(!host)return;
  const M=DATA.matches||[];
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
    const hmeta=t=>esc(teamStandingsMeta(t,m._comp,{form:true,hideStaleRecord:_v15CompetitionKey(m)==='NCAAF'}).join(' · '));
    const rawScore=scorePlainText(m).trim()||'TBD';
    const body=safeMatchDetails(m);
    modal.innerHTML=`<section class="matchSheet modernMatchSheet" role="dialog" aria-modal="true" aria-label="Expanded matchup analysis"><div class="modalHero"><button class="modalClose" onclick="closeMatchModal()" aria-label="Close">×</button><div class="modalStage"><span>${esc(m.stage||'Matchup')}</span><b>${esc(m.status==='LIVE'?'LIVE':m.status||'UPCOMING')}</b></div><div class="modalFixture"><div class="modalTeam"><div class="modalCode">${teamFlagHTML(m.home)}${esc(m.home?.code||'HOME')}</div><div class="modalName">${teamMarkHTML(m.home)}<span>${esc(m.home?.name||'Home')}</span></div><div class="modalMeta">${hmeta(m.home)}</div></div><div class="modalScore"><div class="bigScore">${esc(rawScore)}</div><div class="modalStatus">${m.status==='LIVE'?'Final score pending':kickIn(m.kickoff)}</div></div><div class="modalTeam away"><div class="modalCode">${esc(m.away?.code||'AWAY')}${teamFlagHTML(m.away,true)}</div><div class="modalName"><span>${esc(m.away?.name||'Away')}</span>${teamMarkHTML(m.away,'away')}</div><div class="modalMeta">${hmeta(m.away)}</div></div></div></div><div class="modalBody">${body}</div></section>`;
    modal.dataset.matchId=key;
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
function _isTwoWay(m){return SANDBOX_TWO_WAY.has(String(m?._comp||DATA.comp_key||'').toLowerCase());}
const US_SCORE_TERM={ncaaf:'points',ncaam:'points'};
function _totalsUnit(m){return US_SCORE_TERM[String(m?._comp||DATA.comp_key||'').toLowerCase()]||'goals';}
/* dedup */
// The rail shows the engine's read or it shows nothing. Matchday's own
// `prediction` used to sit beneath it under "Locked model pick" -- a second
// model under the same word, and on a college fixture with no market it printed
// a confidence beside "no market to compare against" for a number this site
// does not stand behind.
function insightModelBlock(m){
  return matchdayLivePickHTML(m)
    ||'<div class="seclbl">Model read</div><div class="nomk">No model read on this fixture yet.</div>';
}
// Same lookup the expanded view uses, so the row on the card and the panel it
// opens onto cannot name different sides. It used to read m.betbetter_pick
// alone, which only a scheduled build writes -- on a push deploy the card
// therefore carried no pick at all while the expanded view still showed one.
function matchdayLivePickHTML(m){const p=betbetterReadFor(m);if(!p)return'';const model=Number(p.model_pct);return `<div class="pick matchdayLivePick"><span class="pl">Model</span><span class="pn">${esc(p.pick_name||'No pick')}</span><span class="pc">${modelPctLabel(model)}</span><span class="pnote">${p.graded===false?`<span title="${esc(p.grading_note||'')}">Not graded · FBS vs FCS</span>`:'Live prediction · updates until kickoff'}</span></div>`}
// Game cards give each name about 83px at their narrowest (a 360px card).
// These schools have one word wider than that, so the card uses a short form
// the school itself goes by instead of splitting the word ("Tennesse / e").
// Audited 2026-09-25 against every NCAAF and NCAAM fixture name; hyphenated
// names are left alone because they break cleanly at the hyphen.
const CARD_SHORT_NAMES={
  'Northwestern':'NU','Massachusetts':'UMass','Pennsylvania':'Penn',
  'Florida International':'FIU','Columbia International':'CIU','Northeastern':'NEU',
  'Northwestern State':'NW State','Jacksonville State':'Jax State','Jacksonville':'JU',
  'Youngstown State':'YSU','SIU Edwardsville':'SIUE','St. Bonaventure':'St. Bona',
  'Presbyterian':'PC','Misericordia':'MU'
};
function cardTeamName(name){return CARD_SHORT_NAMES[String(name||'').trim()]||name}
function cardHTML(m,opts){
  opts=opts||{};
  const pending=m.status==='LIVE',stale=isStaleUpcoming(m);
  const displayStatus=stale?'PAST / REFRESH':pending?'AWAITING FINAL':m.status;
  const statusClass=stale?'PAST_REFRESH':pending?'RESULT_PENDING':m.status;
  const x=(m.markets&&m.markets['1x2'])||{};const hfl=teamFlagHTML(m.home),afl=teamFlagHTML(m.away,true);
  const probTop=x.home_pct!=null?`<div class="prob"><div class="problbl"><span>${esc(m.home.code||m.home.name)}</span><span>Market read</span><span>${esc(m.away.code||m.away.name)}</span></div>${bar1x2(x.home_pct,_isTwoWay(m)?null:x.draw_pct,x.away_pct)}</div>`:`<div class="prob"><div class="nomk">${esc(oddsEtaLabel(m)||'No market snapshot yet')}</div></div>`;
  // One pick per card, and it is the model's. The card used to stack two rows
  // from two different prediction systems: the Bet Better model out of
  // betbetter_picks.json, and `m.prediction` out of the data payload. They are
  // not the same model and they disagree -- Florida State v SMU read "Florida
  // State 60.4%" above "SMU 53%" on the same card -- so a reader had no way to
  // know which one the site actually stands behind. `m.prediction` is no longer
  // rendered anywhere: the card, the rail and the expanded view all read the
  // engine, and a fixture it has not modeled says so instead.
  const livePick=opts.hidePick?'':matchdayLivePickHTML(m);
  const pick=livePick;
  const probChanged=!!probabilityMovement(m);
  const timing=pending?'score after final':m.status==='FINISHED'?'postgame':stale?'past kickoff':kickIn(m.kickoff);
  return `<article class="card${SETTINGS.showDetails?'':' compactCard'}${probChanged?' probChanged':''}" data-id="${esc(m.id)}"><div class="head" onclick="openMatchModal(this.closest('article').dataset.id)"><div class="metarow"><span class="stage">${esc(m.stage||'Fixture')}</span>${m._comp&&!DATA_FILE?`<span class="compTag">${esc(m._comp)}</span>`:''}<span class="wstar ${wlHas(m.home.name)||wlHas(m.away.name)?'on':''}" onclick="event.stopPropagation();wlToggle('${esc(m.home.name)}')" title="Watch">&#9733;</span>${m.weather?`<a class="wxchip" href="${esc(m.weather.source_url||'https://open-meteo.com/')}" target="_blank" rel="noopener noreferrer" onclick="event.stopPropagation()" title="Weather data by Open-Meteo"><b>${Math.round(m.weather.temp_c*9/5+32)}&deg;F</b>${m.weather.wind_kph>=20?` ${Math.round(m.weather.wind_kph*0.621371)} mph`:''}${m.weather.rain_pct>=40?` &#9730;${m.weather.rain_pct}%`:''}<small> Open-Meteo</small></a>`:''}<span class="spacer"></span><span class="pill ${esc(statusClass)}">${esc(displayStatus)}</span></div><div class="fixture"><div class="side"><div class="tname">${teamMarkHTML(m.home)}<span class="teamNameText" title="${esc(m.home.name)}">${hfl}${esc(cardTeamName(m.home.name))}</span></div><div class="tsub"><span>${esc(m.home.code)}</span>${teamStandingsMeta(m.home,m._comp).map(p=>`<span>${esc(p)}</span>`).join('')}</div></div><div class="center"><div class="score">${scoreText(m)}</div><div class="kick">${timing}</div></div><div class="side away"><div class="tname"><span class="teamNameText" title="${esc(m.away.name)}">${esc(cardTeamName(m.away.name))}${afl}</span>${teamMarkHTML(m.away,'away')}</div><div class="tsub"><span>${esc(m.away.code)}</span>${teamStandingsMeta(m.away,m._comp).map(p=>`<span>${esc(p)}</span>`).join('')}</div></div></div>${probTop}${pick}<div class="expander"></div></div></article>`;
}
// The panel details() falls back to if it throws. It carried its own copy of the
// prediction-driven "Model read" card; it now shows the same engine read the
// real expanded view does, so a render error cannot resurrect the other model.
function simpleMatchFallbackPanel(m){
  const bb=typeof betbetterReadFor==='function'?betbetterReadFor(m):null;
  const played=(typeof howItPlayedPanel==='function'?howItPlayedPanel(m):'')||(typeof finalSummaryPanel==='function'?finalSummaryPanel(m):'');
  const read=bb?betbetterModelRead(m,bb):(played||betbetterNoReadPanel());
  return `<div class="detailGrid v8Fallback"><div class="readCard modelReadCard">${read}</div><div class="readCard">${marketPanel(m)}</div>${rosterPanel(m)}</div>`;
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
// The tree follows fixed CFP seed paths, not the provider's array order.
// Left: 1 / (8,9) and 4 / (5,12). Right: 2 / (7,10) and 3 / (6,11).
function _cfpTeam(m,side){
  const obj=m?.[side],name=String(_v11TeamName(obj));
  const prefix=name.match(/^\((\d+)\)\s*/);
  const slot=m?.[side+'_slot']??m?.[side+'Slot']??m?.[side+'_seed']??obj?.seed;
  const seed=/^\d+$/.test(String(slot))?Number(slot):prefix?Number(prefix[1]):null;
  return {name:name.replace(/^\(\d+\)\s*/,''),seed};
}
function _cfpWinner(m,label){
  const h=m?.score?.home,a=m?.score?.away;
  if(String(m?.status||'').toUpperCase()==='FINISHED'&&h!=null&&a!=null&&h!==''&&a!==''&&Number.isFinite(Number(h))&&Number.isFinite(Number(a))&&Number(h)!==Number(a))return _cfpTeam(m,Number(h)>Number(a)?'home':'away');
  return {name:'Winner '+label,seed:null};
}
function _cfpPlaceholder(team){return /winner|^TBD$|^Seed\b/i.test(team.name)}
function _cfpBracketTree(){
  const rounds={first:[],quarter:[],semi:[],final:[]};
  (Array.isArray(DATA.bracket)?DATA.bracket:[]).forEach(r=>{
    const key=_cfpRoundKey(r.round||r.stage||r.name);
    if(key)rounds[key].push(...(r.matches||[]));
  });
  if(!Object.values(rounds).some(r=>r.length))return [];
  const seeds=new Map();
  Object.values(rounds).flat().forEach(m=>['home','away'].forEach(side=>{const t=_cfpTeam(m,side);if(t.seed)seeds.set(t.name,t.seed)}));
  const hasSeed=(m,n)=>['home','away'].some(side=>{const t=_cfpTeam(m,side);return (t.seed||seeds.get(t.name))===n});
  const nodes=[];
  const make=(id,label,m,x,y,fallback)=>{
    const teams=['home','away'].map((side,i)=>{
      const t=_cfpTeam(m,side);
      // Replace only unknown slots; never overwrite a provider's named team.
      const selected=(!m||_cfpPlaceholder(t))&&fallback?.[i]?fallback[i]:t;
      return {...selected,seed:selected.seed||seeds.get(selected.name)||null};
    });
    const node={id,label,m,x,y,teams};nodes.push(node);return node;
  };
  const branches=[{seed:1,pair:[8,9],x:18,qx:222,y:128},{seed:4,pair:[5,12],x:18,qx:222,y:392},{seed:2,pair:[7,10],x:1242,qx:1038,y:128},{seed:3,pair:[6,11],x:1242,qx:1038,y:392}];
  const usedFirst=new Set(),usedQuarter=new Set();
  branches.forEach((b,i)=>{
    const first=rounds.first.find(m=>b.pair.some(n=>hasSeed(m,n))&&!usedFirst.has(m));
    if(first)usedFirst.add(first);
    const fr=make('fr'+b.seed,b.pair.join(' / '),first,b.x,b.y,b.pair.map(n=>({name:'Seed '+n,seed:n})));
    const quarter=rounds.quarter.find(m=>hasSeed(m,b.seed)&&!usedQuarter.has(m));
    if(quarter)usedQuarter.add(quarter);
    const incoming=_cfpWinner(first,b.pair.join(' / '));
    const away=_cfpTeam(quarter,'away'),byeAway=(away.seed||seeds.get(away.name))===b.seed;
    const bye={name:'Seed '+b.seed,seed:b.seed};
    make('qf'+b.seed,'QF '+(i+1),quarter,b.qx,b.y,byeAway?[incoming,bye]:[bye,incoming]);
    // Both endpoints belong to this branch; the line terminates at its winner slot.
    fr.next='qf'+b.seed;
    fr.nextRow=byeAway?0:1;
  });
  // Without seed identity an official game's position is unknown; never hide
  // a supplied game or invent its path from its array index.
  if(usedFirst.size!==rounds.first.length||usedQuarter.size!==rounds.quarter.length)return [];
  const usedSemi=new Set();
  [[1,4,5,8,9,12],[2,3,6,7,10,11]].forEach((side,i)=>{
    const semi=rounds.semi.find(m=>side.some(n=>hasSeed(m,n))&&!usedSemi.has(m))||rounds.semi.find(m=>!usedSemi.has(m)&&!Array.from({length:12},(_,j)=>j+1).some(seed=>hasSeed(m,seed)));
    if(semi)usedSemi.add(semi);
    const qfs=nodes.filter(n=>n.id.startsWith('qf')).slice(i*2,i*2+2);
    const n=make('sf'+(i+1),'Semifinal '+(i+1),semi,i?834:426,260,qfs.map(q=>_cfpWinner(q.m,q.label)));
    qfs.forEach((q,j)=>{q.next=n.id;const winner=_cfpWinner(q.m,q.label);const actual=n.teams.findIndex(t=>t.name===winner.name);q.nextRow=actual<0?j:actual});
    n.next='final';n.nextRow=i;
  });
  if(usedSemi.size!==rounds.semi.length||rounds.final.length>1)return [];
  const semis=nodes.filter(n=>n.id.startsWith('sf'));
  const title=make('final','National championship',rounds.final[0],630,260,semis.map(n=>_cfpWinner(n.m,n.label)));
  semis.forEach(n=>{const actual=title.teams.findIndex(t=>t.name===_cfpWinner(n.m,n.label).name);if(actual>=0)n.nextRow=actual});
  return nodes;
}
function _cfpLogoFallback(img){
  const rest=(img.getAttribute('data-fallback')||'').split('|').filter(Boolean);
  if(rest.length){img.setAttribute('data-fallback',rest.slice(1).join('|'));img.setAttribute('href','team-logos/'+rest[0])}
  else{img.style.display='none';img.nextElementSibling.style.display='block'}
}
function _cfpSchoolName(name){
  // Display only: preserve the original identity for logo lookup and advancement.
  if(name==='James Madison Dukes')return 'James Madison';
  if(typeof _TEAM_LOGO_ENTRIES==='undefined')return name;
  const entry=_TEAM_LOGO_ENTRIES.filter(([school])=>name===school||(name.startsWith(school+' ')&&_safeLogoSuffix(name.slice(school.length).trim().split(/\s+/)[0]))).sort((a,b)=>a[0].length-b[0].length)[0];
  return entry?entry[0]:name;
}
function _cfpSvgCard(n){
  const final=n.id==='final',status=String(n.m?.status||'').toUpperCase();
  const score=side=>status==='FINISHED'?n.m?.score?.[side]:null;
  const h=score('home'),a=score('away');
  const settled=h!=null&&a!=null&&h!==''&&a!==''&&Number.isFinite(Number(h))&&Number.isFinite(Number(a));
  const rows=n.teams.map((t,i)=>{
    const path=_cfpPlaceholder(t),y=28+i*44,sc=score(i?'away':'home');
    const won=settled&&(i?Number(a)>Number(h):Number(h)>Number(a));
    const logos=!path&&typeof teamLogoCandidates==='function'?teamLogoCandidates(t.name):[];
    const file=logos.shift();
    const initials=t.name.split(/\s+/).slice(0,2).map(w=>w[0]).join('');
    const mark=path?`<text x="42" y="${y+27}" class="cfpSvgSlot">—</text>`:`<rect x="25" y="${y+4}" width="36" height="36" rx="5" class="cfpLogoTile"/>${file?`<image href="team-logos/${esc(file)}" data-fallback="${esc(logos.join('|'))}" x="28" y="${y+7}" width="30" height="30" onerror="_cfpLogoFallback(this)"/>`:''}<text x="44" y="${y+26}" text-anchor="middle" class="cfpMonogram" ${file?'style="display:none"':''}>${esc(initials)}</text>`;
    const limit=sc!=null?11:14,width=sc!=null?74:88;
    const words=_cfpSchoolName(t.name).split(/\s+/),lines=[''];
    words.forEach(w=>{const last=lines.length-1;if((lines[last]+' '+w).trim().length>limit&&lines[last])lines.push(w);else lines[last]+=(lines[last]?' ':'')+w});
    const label=lines.length<=2?lines:[lines[0],lines.slice(1).join(' ')];
    return `<g class="cfpSvgTeam ${path?'cfpSvgPath':''} ${won?'cfpSvgWinner':''}"><title>${esc((t.seed?'Seed '+t.seed+': ':'')+t.name+(sc!=null?', score '+sc:'')+(won?', winner':''))}</title>${won?`<rect x="1" y="${y}" width="178" height="44" class="cfpWinFill"/>`:''}<text x="15" y="${y+27}" text-anchor="middle" class="cfpSvgSeed">${t.seed||'–'}</text>${mark}<text x="66" y="${y+(label.length>1?19:27)}" class="cfpSvgName">${label.map((line,j)=>`<tspan x="66" dy="${j?15:0}" ${line.length>limit?`textLength="${width}" lengthAdjust="spacingAndGlyphs"`:''}>${esc(line)}</tspan>`).join('')}</text>${sc!=null?`<text x="168" y="${y+27}" text-anchor="end" class="cfpSvgScore">${esc(sc)}</text>`:''}</g>`;
  }).join('');
  const description=n.teams.map(t=>(t.seed?'Seed '+t.seed+' ':'')+t.name).join(' versus ');
  const meta=status==='FINISHED'?'FINAL':'';
  return `<g class="cfpSvgCard ${n.teams.every(_cfpPlaceholder)?'cfpUnresolved':''} ${final?'cfpSvgFinal':''}" data-node="${n.id}" tabindex="0" role="button" aria-label="${esc(description)}. Highlight route to championship" onmouseenter="_cfpHighlight(this)" onmouseleave="_cfpHighlight(this,false)" onfocus="_cfpHighlight(this)" onblur="_cfpHighlight(this,false)" onclick="_cfpHighlight(this)" onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();_cfpHighlight(this)}if(event.key==='Escape'){_cfpHighlight(this,false)}" transform="translate(${n.x} ${n.y})"><title>${esc(n.label+': '+description)}</title><rect y="${meta?0:28}" width="180" height="${meta?116:88}" rx="7" class="cfpCardSurface"/><path d="${meta?'M 0 28 H 180 ':''}M 0 72 H 180" class="cfpCardDivider"/><text x="12" y="18" class="cfpSvgMeta">${esc(meta)}</text>${rows}</g>`;
}
function _cfpSvgConnector(n,nodes){
  const to=nodes.find(t=>t.id===n.next);if(!to)return '';
  const right=n.x>to.x;
  const x1=n.x+(right?0:180),x2=to.x+(right?180:0),y1=n.y+72;
  const row=n.nextRow??1,y2=to.y+50+row*44,mid=(x1+x2)/2;
  return `<path class="cfpConnector" data-from="${n.id}" data-to="${to.id}" d="M ${x1} ${y1} H ${mid} V ${y2} H ${x2}"/>`;
}
function _cfpFirstFourOut(nodes){
  const poll=typeof MATCHDAY_CFB_AP_POLL!=='undefined'?MATCHDAY_CFB_AP_POLL.rankings:[];
  if(!Array.isArray(poll))return [];
  const key=name=>typeof primaryTeamLogo==='function'?primaryTeamLogo(name):String(name).toLowerCase().trim();
  const field=new Map();
  nodes.flatMap(n=>n.teams).forEach(t=>{if(t.seed>=1&&t.seed<=12&&!_cfpPlaceholder(t))field.set(t.seed,key(t.name))});
  // An incomplete field cannot establish which teams missed it.
  if(field.size!==12)return [];
  const included=new Set(field.values()),seen=new Set();
  return poll.filter(t=>t.name&&Number.isInteger(Number(t.rank))&&Number(t.rank)>0)
    .slice().sort((a,b)=>Number(a.rank)-Number(b.rank)).filter(t=>{
      const identity=key(t.name);if(included.has(identity)||seen.has(identity))return false;
      seen.add(identity);return true;
    }).slice(0,4);
}
function _cfpOutRow(nodes,official){
  if(official)return '';
  const teams=_cfpFirstFourOut(nodes);if(!teams.length)return '';
  return `<section class="cfpOut" aria-labelledby="cfp-out-title"><h3 id="cfp-out-title">First four out</h3><div class="cfpOutGrid">${teams.map(t=>`<article class="cfpOutTeam">${teamMark(t.name)}<div><b>${esc(_cfpSchoolName(t.name))}</b><span>AP #${esc(t.rank)}${t.record?' · '+esc(t.record):''}</span></div></article>`).join('')}</div></section>`;
}
function _cfpHighlight(el,active=true){
  const svg=el.closest('svg'),nodes=_cfpBracketTree(),route=new Set();
  let node=nodes.find(n=>n.id===el.dataset.node);
  while(node){route.add(node.id);node=nodes.find(n=>n.id===node.next)}
  svg.querySelectorAll('[data-node],[data-from]').forEach(item=>item.classList.toggle('cfpRoute',active&&route.has(item.dataset.node||item.dataset.from)));
}
function _cfpRoundSelect(button){
  const section=button.closest('.cfpRounds'),key=button.dataset.round;
  section.querySelectorAll('[data-round]').forEach(b=>b.setAttribute('aria-pressed',String(b===button)));
  section.querySelectorAll('[data-panel]').forEach(p=>p.hidden=p.dataset.panel!==key);
}
function _cfpRoundCard(n,nodes){
  const done=String(n.m?.status||'').toUpperCase()==='FINISHED',next=nodes.find(t=>t.id===n.next);
  return `<article class="cfpRoundCard"><h3>${esc(n.label)}${done?' · Final':''}</h3>${n.teams.map((t,i)=>{
    const path=_cfpPlaceholder(t),score=done?n.m?.score?.[i?'away':'home']:null;
    return `<div class="cfpRoundTeam ${path?'cfpPending':''}"><span class="cfpRoundSeed">${t.seed||'–'}</span>${path?'<span class="cfpRoundSlot" aria-hidden="true">—</span>':teamMark(t.name)}<b>${esc(_cfpSchoolName(t.name))}</b>${score!=null?`<strong>${esc(score)}</strong>`:''}</div>`;
  }).join('')}${next?`<p>Advances to ${esc(next.label)}</p>`:''}</article>`;
}
function _cfpResponsiveBracket(nodes){
  const rounds=[['fr','First round'],['qf','Quarterfinals'],['sf','Semifinals'],['final','Championship']];
  return `<section class="cfpRounds" aria-label="Playoff rounds"><nav aria-label="Choose a playoff round">${rounds.map(([key,label],i)=>`<button type="button" data-round="${key}" aria-controls="cfp-round-${key}" aria-pressed="${i===0}" onclick="_cfpRoundSelect(this)">${label}</button>`).join('')}</nav>${rounds.map(([key,label],i)=>`<section id="cfp-round-${key}" data-panel="${key}" aria-label="${label}" ${i?'hidden':''}><h2>${label}</h2><div class="cfpRoundGrid">${nodes.filter(n=>n.id.startsWith(key)).map(n=>_cfpRoundCard(n,nodes)).join('')}</div></section>`).join('')}</section>`;
}
function _renderCFPBracket(host){
  const official=Array.isArray(DATA.bracket)&&DATA.bracket.some(r=>
    !/project(?:ed|ion)/i.test(String(r.round||r.stage||r.name||''))
    &&(r.matches||[]).some(m=>!['PROJECTED','TBD'].includes(String(m.status||'').toUpperCase())));
  const nodes=_cfpBracketTree();
  if(!nodes.length){host.innerHTML='<div class="vhead">CFP Playoff</div><div class="empty">The playoff bracket is waiting for complete seed information.</div>';return}
  const trophy=`<g class="cfpTrophy" transform="translate(720 151)" aria-hidden="true"><path d="M 0 -39 C -34 -13 -26 12 0 28 C 26 12 34 -13 0 -39 Z M 0 -29 V 17 M -8 -12 H 8 M -8 -3 H 8 M -8 6 H 8 M -13 23 L -9 47 H 9 L 13 23 M -20 49 H 20"/><path d="M -26 56 H 26"/></g>`;
  host.innerHTML=`<section class="cfpShell"><header class="cfpHero"><div><span class="cfpEyebrow">College Football Playoff</span><h2>The road to a champion</h2></div><span class="cfpBadge">${official?'Playoff bracket':'Projected field'}</span></header><p class="cfpContext">${official?'Official playoff bracket.':'Projected from the AP Poll · Not the official CFP bracket.'} Seeds 1–4 enter in the quarterfinals.</p>${_cfpResponsiveBracket(nodes)}<details class="cfpFullBracket" open><summary>Full bracket</summary><div class="cfpCanvas" tabindex="0" role="region" aria-label="Full playoff bracket; scroll horizontally on smaller screens"><svg class="cfpDiagram" viewBox="17 80 1406 448" role="group" aria-labelledby="cfp-title cfp-description"><title id="cfp-title">Connected College Football Playoff bracket</title><desc id="cfp-description">${official?'Official matchups and unresolved paths.':'Projected from the current AP Poll. Not the official CFP bracket.'} Seeds 1–4 enter in the quarterfinals. First-round games on the outside feed quarterfinals, then semifinals, and the championship in the center. ${esc(nodes.map(n=>n.label+': '+n.teams.map(t=>(t.seed?'seed '+t.seed+' ':'')+t.name).join(' versus ')).join('. '))}</desc>${[[108,'FIRST ROUND'],[312,'QUARTERFINALS'],[516,'SEMIFINALS'],[924,'SEMIFINALS'],[1128,'QUARTERFINALS'],[1332,'FIRST ROUND']].map(([x,label])=>`<text x="${x}" y="106" text-anchor="middle" class="cfpRoundHeading">${label}</text>`).join('')}${trophy}<text x="720" y="238" text-anchor="middle" class="cfpChampLabel">NATIONAL CHAMPIONSHIP</text>${nodes.map(n=>_cfpSvgConnector(n,nodes)).join('')}${nodes.map(_cfpSvgCard).join('')}</svg></div><button type="button" class="cfpClearRoute" onclick="this.closest('.cfpFullBracket').querySelectorAll('.cfpRoute').forEach(el=>el.classList.remove('cfpRoute'))">Clear highlighted route</button></details><footer class="cfpFoot"><span><i aria-hidden="true"></i> Select a matchup to highlight its route</span><span>12 teams · 4 rounds · No reseeding</span></footer>${_cfpOutRow(nodes,official)}</section>`;
  host.querySelector('.cfpFullBracket').open=window.matchMedia('(min-width:1401px)').matches;
}

function renderBracket(){
  const host=$('#view-bracket');
  if(!host)return;
  if(DATA.comp_key==='NCAAM'){MatchdayBracketology.render(host);return}
  if(DATA.comp_key==='NCAAF'){_renderCFPBracket(host);return}
  // Everything else fell through to a generic 32-team group-into-knockout
  // renderer -- a World Cup shape. Drawn over college conference standings it
  // produced a "Round of 32" seeded by conference, which no college postseason
  // has, and on the merged board it was reachable with no sport selected at
  // all. There is no bracket to show here, and saying so beats inventing one.
  host.innerHTML=`<div class="vhead">Bracket</div><div class="empty">Choose College Football or Men's College Basketball to see its bracket projection.</div>`;
}
function _v12Round(v){return Math.max(0,Math.min(100,Math.round(Number(v)||0)))}
function _v12ProbTile(label,pct,side,active){
  const cls=side==='h'?'home':side==='d'?'draw':'away';
  return `<div class="probTile ${cls} ${active?'pickSide':''}"><span class="probSide">${esc(label)}</span><b class="probPct">${_v12Round(pct)}%</b><span class="probMiniTrack"><i style="width:${Math.max(3,_v12Round(pct))}%"></i></span>${active?'<em class="probTag">pick</em>':''}</div>`;
}
function _v15Num(v){
  if(v===null||v===undefined||v==='')return null;
  const n=Number(v);return Number.isFinite(n)?n:null;
}
function _v15Record(team,m){
  if(_v15CompetitionKey(m)==='NCAAF'&&team?.season_stale)return null;
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
  if(['NCAAF','NCAAM'].includes(comp))return 'Conference position';
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
/* The team comparison from the expanded view, restored without the model.

   This card used to sit inside modelBlock(), so deleting that panel took it out
   too -- and most of it had nothing to do with the forecast. Its four KPIs did:
   model separation, probability adjustment, the modelled expected total, and the
   sample the model had to work from. Those are gone with the model that
   produced them.

   Everything below them is the two teams' own record: results, placement,
   opponent-adjusted rating, scoring for and against, form, and who is listed
   out. That is worth reading whoever is forecasting the game, so it comes back
   on its own. */
function matchProfilePanel(m){
  const unit=_totalsUnit(m);
  const homeOut=Array.isArray(m?.injuries?.home)?m.injuries.home.length:0;
  const awayOut=Array.isArray(m?.injuries?.away)?m.injuries.away.length:0;
  const rows=[
    _v15CompareRow('Record',_v15Record(m?.home,m),_v15Record(m?.away,m)),
    _v15CompareRow(_v15PlacementLabel(m),_v15Placement(m?.home),_v15Placement(m?.away)),
    _v15CompareRow(_v15RankLabel(m),_v15Num(m?.home?.model_rank)!=null?`#${m.home.model_rank}`:null,_v15Num(m?.away?.model_rank)!=null?`#${m.away.model_rank}`:null),
    _v15CompareRow('Opponent-adjusted rating',_v15Num(m?.home?.srs)!=null?Number(m.home.srs).toFixed(1):null,_v15Num(m?.away?.srs)!=null?Number(m.away.srs).toFixed(1):null),
    _v15CompareRow(`Avg ${unit} scored`,_v15Rate(m?.home,'gf'),_v15Rate(m?.away,'gf')),
    _v15CompareRow(`Avg ${unit} allowed`,_v15Rate(m?.home,'ga'),_v15Rate(m?.away,'ga')),
    _v15CompareRow('Recent form',_v15Form(m?.home),_v15Form(m?.away),true),
    _v15CompareRow('Listed absences',String(homeOut),String(awayOut))
  ].filter(Boolean).join('');
  // Every row can be absent -- a team with no games played has no record, no
  // form and no rates -- and an empty card is worse than no card.
  if(!rows)return '';
  return `<div class="readCard matchProfileCard"><div class="readHead"><span>Profile</span><b>Team comparison</b></div><div class="profileCompareHead"><b>${esc(m?.home?.code||m?.home?.name||'Home')}</b><span>this season</span><b>${esc(m?.away?.code||m?.away?.name||'Away')}</b></div><div class="profileCompareRows">${rows}</div></div>`;
}
const startupParams=new URLSearchParams(window.location.search);
const requestedView=startupParams.get('view');
const requestedSport=String(startupParams.get('sport')||'').toLowerCase();
const requestedMatch=startupParams.get('match');
if(Object.prototype.hasOwnProperty.call(SPORT_LABELS,requestedSport)){
  DATA_FILE=`data_${requestedSport}.json`;
  try{localStorage.setItem('matchday.sport',DATA_FILE)}catch(e){}
}
// Insights left the sidebar (it duplicates the Content hub); it stays reachable
// by ?view=insights, but a stale saved default should no longer land there.
const savedView=safeView(SETTINGS.defaultView||'matches');
const requestedSafeView=requestedView?safeView(requestedView):'';
const initialView=requestedSafeView&&document.getElementById('view-'+requestedSafeView)?requestedSafeView:savedView;
applySettings();applySportNav();setView(initialView,{history:false});
bootAccount(); // resolves a returning sign-in redirect, or restores an existing session
load().then(()=>{
  if(requestedSafeView&&document.getElementById('view-'+requestedSafeView))setView(requestedSafeView,{history:false});
  if(requestedMatch&&BYID[requestedMatch])openMatchModal(requestedMatch);
});
window.addEventListener('popstate',()=>{
  const params=new URLSearchParams(window.location.search),target=safeView(params.get('view')||'matches');
  const sport=String(params.get('sport')||'').toLowerCase();
  if(Object.prototype.hasOwnProperty.call(SPORT_LABELS,sport)&&currentSportKey()!==sport){
    DATA_FILE=`data_${sport}.json`;MATCH_VISIBLE=FIXTURE_PAGE_SIZE;RESULT_VISIBLE=FIXTURE_PAGE_SIZE;
    try{localStorage.setItem('matchday.sport',DATA_FILE)}catch(e){}
    applySportNav();showMatchLoading();clearCompetitionViewsForLoad();
    load(true).then(()=>setView(target,{history:false}));
  }else setView(target,{history:false});
});
