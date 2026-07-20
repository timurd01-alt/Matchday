
const $=s=>document.querySelector(s);let DATA={matches:[],news:[],standings:[]},BYID={},VIEW='matches',LAST_OK=false,LAST_ERROR='',LOAD_TIMER=null,NEWS_FILTER='all';
const DEFAULT_SETTINGS={accent:'green',density:'normal',panel:'glass',defaultView:'matches',refresh:60,showInsight:true,showFinished:false,showDetails:false,favoriteTeam:''};
let SETTINGS={...DEFAULT_SETTINGS};try{SETTINGS={...DEFAULT_SETTINGS,...JSON.parse(localStorage.getItem('matchday.settings')||'{}')}}catch(e){}
// Refresh cadence is product-controlled so visitors cannot accidentally create
// excessive polling or make the dashboard feel stale.
SETTINGS.refresh=60;
let LANG='';try{LANG=localStorage.getItem('matchday.lang')||''}catch(e){}
function translateUiText(source,dict){
  if(!LANG||!dict||!source)return source;
  if(dict[source])return dict[source];
  // Generated UI commonly combines a stable phrase with a number or timestamp.
  // Translate those known fragments without touching provider-owned content.
  return Object.keys(dict).sort((a,b)=>b.length-a.length).reduce((out,key)=>
    key.length>2?out.split(key).join(dict[key]):out,source);
}
function applyStaticI18n(){
  const dict=(LANG&&window.MD_I18N&&MD_I18N[LANG])||{};
  document.querySelectorAll('.navbtn .lbl').forEach(el=>{const en=el.getAttribute('data-en')||el.textContent.trim();el.setAttribute('data-en',en);el.textContent=dict[en]||en;});
  const walker=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT);
  let node;
  while((node=walker.nextNode())){
    if(node.parentElement?.closest('script,style,.nhead,.ndesc,.teamName,.modalName,.ins-match'))continue;
    const raw=node.nodeValue||'',trimmed=raw.trim();if(!trimmed)continue;
    const en=node.__matchdayEnglish||trimmed;node.__matchdayEnglish=en;
    const translated=translateUiText(en,dict);
    if(translated!==trimmed)node.nodeValue=raw.replace(trimmed,translated);
  }
  document.documentElement.lang=LANG||'en';
}
function t(s){if(!LANG||!window.MD_I18N||!MD_I18N[LANG])return s;return translateUiText(s,MD_I18N[LANG]);}
function setLang(v){LANG=v;try{localStorage.setItem('matchday.lang',v)}catch(e){};renderStrip();renderCurrent();renderInsight&&renderInsight();applyStaticI18n();renderAlerts();}
let DATA_FILE='';try{DATA_FILE=localStorage.getItem('matchday.sport')||'';if(/^data_(mlb|nhl)\.json$/i.test(DATA_FILE)){DATA_FILE='';localStorage.setItem('matchday.sport','')}}catch(e){}
const SPORT_LABELS={wc:'World Cup',ucl:'Champions League',epl:'Premier League',laliga:'La Liga',seriea:'Serie A',bundesliga:'Bundesliga',ligue1:'Ligue 1',nfl:'NFL',ncaaf:'College Football',ncaam:"Men's College Basketball",nba:'NBA',mlb:'MLB',nhl:'NHL'};
const FIXTURE_PAGE_SIZE=40;
let MATCH_VISIBLE=FIXTURE_PAGE_SIZE,RESULT_VISIBLE=FIXTURE_PAGE_SIZE;

// ---- per-sport sidebar (data-driven, follows the SELECTION) ---------------
// Each sport declares exactly which views exist for it, in order.
const NAV_DEF={
  all:         ['matches','results','community','sandbox','news','status','updates','customize'],
  soccer_cup:  ['matches','results','groups','title','edge','score','bracket','third','tott','community','sandbox','news','status','updates','customize'],
  soccer_club: ['matches','results','groups','title','edge','score','bracket','tott','community','sandbox','news','status','updates','customize'],
  us_sport:    ['matches','results','groups','title','edge','score','community','sandbox','news','status','updates','customize'],
  college:     ['matches','results','groups','bracket','title','edge','score','community','sandbox','news','status','updates','customize'],
  college_basketball:['matches','results','groups','bracket','title','edge','score','community','sandbox','news','status','updates','customize'],
  soccer_league:['matches','results','groups','title','edge','score','tott','community','sandbox','news','status','updates','customize']
};
const SPORT_KIND={'':'all',wc:'soccer_cup',ucl:'soccer_club',epl:'soccer_league',laliga:'soccer_league',seriea:'soccer_league',bundesliga:'soccer_league',ligue1:'soccer_league',nfl:'us_sport',ncaaf:'college',ncaam:'college_basketball',nba:'us_sport',mlb:'us_sport',nhl:'us_sport'};
function currentSportKey(){const m=(DATA_FILE||'').match(/data_(\w+)\.json/);return m?m[1]:'';}
function navProfile(){return SPORT_KIND[currentSportKey()]||'all';}
const NAV_LABELS={soccer_club:{groups:'League Phase'},us_sport:{groups:'Standings'},college:{groups:'Rankings',bracket:'CFP Bracket'},college_basketball:{groups:'Conferences',bracket:'Bracketology'},soccer_league:{groups:'Table',tott:'Team of the Season'}};
function applySportNav(){
  const prof=navProfile();
  const allowed=NAV_DEF[prof];
  const labels=NAV_LABELS[prof]||{};
  document.querySelectorAll('.navbtn').forEach(b=>{
    b.style.display=allowed.includes(b.dataset.v)?'':'none';
    const l=b.querySelector('.lbl');
    if(l){const en=l.getAttribute('data-en')||l.textContent.trim();l.setAttribute('data-en',en);
      l.textContent=labels[b.dataset.v]||t(en);}});
  if(!allowed.includes(VIEW))setView('matches');
}
function changeSport(v){DATA_FILE=v?('data_'+v+'.json'):'';MATCH_VISIBLE=FIXTURE_PAGE_SIZE;RESULT_VISIBLE=FIXTURE_PAGE_SIZE;try{localStorage.setItem('matchday.sport',DATA_FILE)}catch(e){};applySportNav();load(true);}

const COLORS={orange:'#ffb02e',blue:'#4cc2ff',green:'#3ad17a',red:'#ff4d5e',purple:'#b16cff'};
function saveSettings(){localStorage.setItem('matchday.settings',JSON.stringify(SETTINGS))}
function applySettings(){document.documentElement.style.setProperty('--signal',COLORS[SETTINGS.accent]||COLORS.orange);document.body.classList.toggle('compact',SETTINGS.density==='compact');document.body.classList.toggle('spacious',SETTINGS.density==='spacious');$('#app').classList.toggle('flat',SETTINGS.panel==='flat');$('#app').classList.toggle('noinsight',!SETTINGS.showInsight);document.body.classList.toggle('hideStats',!SETTINGS.showDetails)}
function updateSetting(k,v){if(k==='refresh')return;if(k==='showInsight'||k==='showDetails'||k==='showFinished')v=!!v;SETTINGS[k]=v;saveSettings();applySettings();renderCurrent();if(k==='favoriteTeam'&&typeof renderInsight==='function')renderInsight();scheduleNextLoad()}
function resetSettings(){SETTINGS={...DEFAULT_SETTINGS};saveSettings();applySettings();setView(SETTINGS.defaultView);scheduleNextLoad()}
function esc(s){return String(s??'').replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]))}
function uiLocale(){return({es:'es',fr:'fr',de:'de',pt:'pt-BR',ru:'ru'})[LANG]||undefined}
function relativeTime(value,unit){return new Intl.RelativeTimeFormat(uiLocale(),{numeric:'auto'}).format(value,unit)}
function dt(iso){try{return new Date(iso).toLocaleString(uiLocale(),{weekday:'short',hour:'numeric',minute:'2-digit',month:'short',day:'numeric'})}catch(e){return''}}
function ago(iso){try{const s=(Date.now()-new Date(iso).getTime())/1000;if(!isFinite(s))return'';if(s<70)return relativeTime(0,'second');if(s<3600)return relativeTime(-Math.round(s/60),'minute');if(s<86400)return relativeTime(-Math.round(s/3600),'hour');return relativeTime(-Math.round(s/86400),'day')}catch(e){return''}}
function kickIn(iso){try{const m=Math.round((new Date(iso)-Date.now())/60000);if(m<=0)return relativeTime(0,'minute');if(m<60)return relativeTime(m,'minute');if(m<1440)return relativeTime(Math.round(m/60),'hour');return relativeTime(Math.round(m/1440),'day')}catch(e){return''}}
const STALE_MATCH_MINUTES=150;
function kickMs(m){const t=Date.parse(m?.kickoff||'');return Number.isFinite(t)?t:0}
function isStaleUpcoming(m){const t=kickMs(m);return m?.status==='UPCOMING'&&t>0&&(Date.now()-t)>STALE_MATCH_MINUTES*60000}
function isCompleteOrPast(m){return m?.status==='FINISHED'||isStaleUpcoming(m)}
function isVisibleUpcoming(m){return m?.status==='UPCOMING'&&!isStaleUpcoming(m)}
function fixtureSort(a,b){const o={LIVE:0,UPCOMING:1,FINISHED:2};return (o[a.status]??9)-(o[b.status]??9)||(a.kickoff||'').localeCompare(b.kickoff||'')}
function teamKey(name){return String(name||'').toLowerCase().replace(/[^a-z0-9]+/g,' ').trim()}
function favoriteTeam(){return String(SETTINGS.favoriteTeam||'').trim()}
function favoriteNewsTerm(){return teamKey(favoriteTeam()).replace(/\b(fc|afc|cf|sc|football club)\b/g,'').replace(/\s+/g,' ').trim()}
function isFavoriteTeam(name){const fav=teamKey(favoriteTeam());return !!fav&&teamKey(name)===fav}
function isFavoriteMatch(m){return !!m&&(isFavoriteTeam(m.home?.name)||isFavoriteTeam(m.away?.name))}
function favoriteFixtureSort(a,b){return Number(isFavoriteMatch(b))-Number(isFavoriteMatch(a))||fixtureSort(a,b)}
function favoriteTeamOptions(){const names=new Set();(DATA.matches||[]).forEach(m=>{if(m.home?.name)names.add(m.home.name);if(m.away?.name)names.add(m.away.name)});(DATA.standings||[]).forEach(g=>(g.teams||[]).forEach(team=>{if(team.name)names.add(team.name)}));if(favoriteTeam())names.add(favoriteTeam());return [...names].sort((a,b)=>a.localeCompare(b)).map(name=>`<option value="${esc(name)}" ${name===favoriteTeam()?'selected':''}>${esc(name)}</option>`).join('')}
function scoreText(m){const done=m.status==='FINISHED'||m.status==='LIVE';if(isStaleUpcoming(m))return'<span class="kick">Past kickoff</span>';return done?`${m.score?.home??'-'}<span class="sep">–</span>${m.score?.away??'-'}${m.score?.pens?`<span class="pensTag">(${m.score.pens.home}-${m.score.pens.away} pens)</span>`:''}`:`<span class="kick">${dt(m.kickoff).split(', ').pop()||'TBD'}</span>`}
function statNum(v){const m=String(v??'').match(/-?\d+(\.\d+)?/);return m?Number(m[0]):0}
function pressure(stats,side){if(!stats)return 0;const s=stats[side]||{};return statNum(s.shots_on_target)*4+statNum(s.shots)*1.2+statNum(s.corners)*1.4+statNum(String(s.possession).replace('%',''))*.08-statNum(s.red_cards)*4}
function statRow(label,h,a){const hn=statNum(h),an=statNum(a),tot=Math.max(1,hn+an);return `<div class="home">${esc(h||'-')}</div><div class="lab">${label}</div><div class="away">${esc(a||'-')}</div><div class="statbar"><i style="width:${hn/tot*100}%"></i><i style="width:${an/tot*100}%"></i></div>`}
function pct(v){v=Number(v);return Number.isFinite(v)?Math.max(0,Math.min(100,Math.round(v))):0}
function bar1x2(h,d,a){h=pct(h);d=pct(d);a=pct(a);return `<div class="bar"><div class="seg h" style="flex-basis:${h}%"><span>${h}%</span></div><div class="seg d" style="flex-basis:${d}%"><span>${d}%</span></div><div class="seg a" style="flex-basis:${a}%"><span>${a}%</span></div></div>`}
function duo(xl,xv,yl,yv){xv=pct(xv);yv=pct(yv);return `<div class="mkt"><div class="lbls"><span>${esc(xl)} <b>${xv}%</b></span><span><b>${yv}%</b> ${esc(yl)}</span></div><div class="duo"><i class="x" style="flex-basis:${xv}%">${xv}%</i><i class="y" style="flex-basis:${yv}%">${yv}%</i></div></div>`}
function marketPanel(m){const mk=m.markets||{},x=mk['1x2']||{};let h='<div class="seclbl">Odds tracker</div>';if(x.home_pct!=null){h+=`<div class="problbl"><span>${esc(m.home.code||m.home.name)} win</span><span>draw</span><span>${esc(m.away.code||m.away.name)} win</span></div>${bar1x2(x.home_pct,x.draw_pct,x.away_pct)}<div class="faintline" style="margin-top:6px">1X2 market · ${x.books||'?'} books</div>`;const arr=v=>v>0?`<span class="up">▲${v}</span>`:v<0?`<span class="down">▼${Math.abs(v)}</span>`:`<span class="flat">·</span>`;if(x.move&&(x.move.h||x.move.d||x.move.a)){h+=`<div class="oddsMove"><span class="mvlbl">Since open</span><span>${esc(m.home.code)} ${arr(x.move.h)}</span><span>X ${arr(x.move.d)}</span><span>${esc(m.away.code)} ${arr(x.move.a)}</span></div>`}else if(x.open){h+=`<div class="faintline" style="margin-top:4px">No line movement logged yet — it builds as the fetcher keeps running.</div>`}if(x.confidence){h+=`<div class="oddsDisagree ${esc(x.confidence)}"><span class="dgtag">${esc(x.confidence)}</span><span>books range ${x.spread_lo}–${x.spread_hi}% on ${esc(m.home.code)} win</span><span class="dgspread">±${x.spread}</span></div>`}}else h+='<div class="nomk">No 1X2 market odds yet.</div>';if(mk.totals)h+=`<div class="seclbl">Goals — over/under ${esc(mk.totals.line)}</div>`+duo(`Over ${mk.totals.line}`,mk.totals.over_pct,`Under ${mk.totals.line}`,mk.totals.under_pct);return h}
function _v6UpsetClass(score,triggered){score=Number(score)||0;if(triggered)return'trigger';return score>=70?'high':score>=50?'med':'low'}
/* dedup */
/* dedup */
/* dedup */
/* dedup */
/* removed duplicate (cardHTML) */

// ---- landing hero (first thing a visitor sees) ----------------------------
let HERO_FIRST_VISIT=false;try{HERO_FIRST_VISIT=!localStorage.getItem('matchday.heroVisited');if(HERO_FIRST_VISIT)localStorage.setItem('matchday.heroVisited','1')}catch(e){}
function heroSeen(){try{return localStorage.getItem('matchday.heroSeen')==='1'||!HERO_FIRST_VISIT}catch(e){return false}}
function heroDismiss(){try{localStorage.setItem('matchday.heroSeen','1')}catch(e){};renderCurrent();}
function welcomeDismissed(){try{return sessionStorage.getItem('matchday.welcome.entered')==='1'}catch(e){return false}}
function enterMatchday(){
  try{sessionStorage.setItem('matchday.welcome.entered','1');localStorage.setItem('matchday.heroSeen','1')}catch(e){}
  const gate=$('#welcomeGate');if(gate)gate.hidden=true;document.body.classList.remove('welcomeOpen');
  renderCurrent();const main=document.querySelector('.content');if(main)main.focus?.();
  if(!tourSeen())setTimeout(startTour,650);
}

// ---- guided tour (first-visit walkthrough) --------------------------------
const TOUR_STEPS=[
  {target:'#sportSel',title:'Start here',body:'Pick a competition to unlock the full toolkit — live predictions, model accuracy tracking, brackets and more. "All sports" just shows a combined feed across everything.'},
  {target:'.navbtn[data-v="matches"]',title:'Matches',body:'Every fixture, live scores, and the model’s pick shown right next to the market’s.'},
  {target:'.navbtn[data-v="edge"]',title:'Model',body:'See exactly why the model favors a side — points, form, ratings, injuries and more, broken down factor by factor.'},
  {target:'.navbtn[data-v="score"]',title:'Scorecard',body:'Every locked pick, tracked in public. Nothing gets rewritten after the fact — good calls or bad ones.'},
  {target:'.navbtn[data-v="sandbox"]',title:'Sandbox',body:'Build a hypothetical matchup between any two teams and see what the model thinks, on the spot.'},
  {target:'.navbtn[data-v="bracket"]',title:'Bracket',body:'Simulate an entire knockout bracket round by round, using the model’s own predictions.'},
  {target:'.navbtn[data-v="community"]',title:'Community',body:'Set a handle, make your own picks, and see how you stack up against the model on the leaderboard.'},
  {target:'.navbtn[data-v="customize"]',title:'Customize',body:'Tune the accent color, layout density, language, and your favorite team here. You can replay this tour anytime from this tab.'}
];
let TOUR_I=0;
function tourSeen(){try{return localStorage.getItem('matchday.tourSeen')==='1'}catch(e){return true}}
function tourMarkSeen(){try{localStorage.setItem('matchday.tourSeen','1')}catch(e){}}
function tourVisibleSteps(){return TOUR_STEPS.filter(s=>{const el=document.querySelector(s.target);return el&&el.offsetParent!==null;});}
function startTour(){
  const steps=tourVisibleSteps();
  if(!steps.length)return;
  window._tourSteps=steps;TOUR_I=0;
  document.body.classList.add('tourOpen');
  tourRenderStep();
}
function tourEnd(){
  tourMarkSeen();
  document.body.classList.remove('tourOpen');
  document.querySelectorAll('.tourHighlight').forEach(el=>el.classList.remove('tourHighlight'));
  const ov=$('#tourOverlay');if(ov)ov.remove();
}
function tourNext(){
  const steps=window._tourSteps||[];
  if(TOUR_I>=steps.length-1){tourEnd();return;}
  TOUR_I++;tourRenderStep();
}
function tourBack(){if(TOUR_I<=0)return;TOUR_I--;tourRenderStep();}
function tourRenderStep(){
  const steps=window._tourSteps||[];
  const step=steps[TOUR_I];if(!step){tourEnd();return;}
  document.querySelectorAll('.tourHighlight').forEach(el=>el.classList.remove('tourHighlight'));
  const target=document.querySelector(step.target);
  if(!target){tourNext();return;}
  target.classList.add('tourHighlight');
  target.scrollIntoView({block:'center',inline:'center',behavior:'smooth'});
  let ov=$('#tourOverlay');
  if(!ov){ov=document.createElement('div');ov.id='tourOverlay';ov.className='tourOverlay';document.body.appendChild(ov);}
  const last=TOUR_I===steps.length-1;
  ov.innerHTML=`<div class="tourBackdrop" onclick="tourEnd()"></div>
    <div class="tourCard" role="dialog" aria-modal="true" aria-label="Guided tour">
      <div class="tourStepNum">${TOUR_I+1} / ${steps.length}</div>
      <h3>${esc(step.title)}</h3>
      <p>${esc(step.body)}</p>
      <div class="tourActions">
        <button class="tourSkip" type="button" onclick="tourEnd()">Skip tour</button>
        <div class="tourNav">
          ${TOUR_I>0?'<button class="tourBack" type="button" onclick="tourBack()">Back</button>':''}
          <button class="tourNextBtn" type="button" onclick="tourNext()">${last?'Done':'Next'}</button>
        </div>
      </div>
    </div>`;
  tourPositionCard(target,ov.querySelector('.tourCard'));
}
function tourPositionCard(target,card){
  const r=target.getBoundingClientRect();
  const cw=card.offsetWidth||300,ch=card.offsetHeight||160;
  const vw=window.innerWidth,vh=window.innerHeight;
  let left=r.right+16,top=r.top+r.height/2-ch/2;
  if(left+cw>vw-12){
    left=Math.max(12,Math.min(vw-cw-12,r.left));
    top=r.bottom+14;
    if(top+ch>vh-12)top=Math.max(12,r.top-ch-14);
  }
  top=Math.max(12,Math.min(vh-ch-12,top));
  left=Math.max(12,Math.min(vw-cw-12,left));
  card.style.left=left+'px';card.style.top=top+'px';
}
document.addEventListener('keydown',e=>{if(e.key==='Escape'&&document.body.classList.contains('tourOpen'))tourEnd();});
function renderWelcome(){
  const gate=$('#welcomeGate');if(!gate)return;
  const dismissed=welcomeDismissed();gate.hidden=dismissed;document.body.classList.toggle('welcomeOpen',!dismissed);if(dismissed)return;
  const matches=(DATA.matches||[]).filter(m=>m.status==='LIVE'||isVisibleUpcoming(m)).sort(fixtureSort),m=matches[0],host=$('#welcomeNext');
  if(!host||!m)return;
  const pr=m.prediction||{},op=(typeof _v10OfficialPick==='function'&&m.prediction)?_v10OfficialPick(m):null;
  const pick=op?.name||pr.pick_name||'',model=op?.confidence??pr.confidence,market=op?.marketPct;
  const edge=model!=null&&market!=null?Math.round(Number(model)-Number(market)):null;
  host.innerHTML=`<div class="welcomeMatchMeta"><span>${esc(m._comp||DATA.comp_key||m.stage||'NEXT')}</span><span class="${m.status==='LIVE'?'isLive':''}">${m.status==='LIVE'?'LIVE':kickIn(m.kickoff)}</span></div><div class="welcomeTeams"><div><small>${esc(m.home?.code||'HOME')}</small><b>${esc(m.home?.name||'Home')}</b></div><em>${m.status==='LIVE'?esc(scoreText(m).replace(/<[^>]+>/g,'')):'v'}</em><div class="away"><small>${esc(m.away?.code||'AWAY')}</small><b>${esc(m.away?.name||'Away')}</b></div></div>${pick?`<div class="welcomeSignal"><span>MODEL</span><b>${esc(pick)} ${model!=null?esc(model)+'%':''}</b>${market!=null?`<i>market ${esc(market)}%${edge!=null?` · ${edge>0?'+':''}${edge} pt`:''}</i>`:''}</div>`:''}`;
  const state=$('#welcomeFeedState');if(state)state.textContent=(DATA.matches||[]).some(x=>x.status==='LIVE')?'LIVE NOW':'NEXT MATCH';
}
function heroMarquee(){
  const up=(DATA.matches||[]).filter(m=>m.status==='LIVE'||(m.status==='UPCOMING'&&m.prediction&&m.markets));
  if(!up.length)return '';
  // marquee = live game first, else the next kickoff with the strongest read
  const live=up.find(m=>m.status==='LIVE');
  const pick=live||up.sort((a,b)=>(a.kickoff||'').localeCompare(b.kickoff||''))[0];
  const pr=pick.prediction||{};
  return `<div class="heroMatch" onclick="openMatchModal('${esc(String(pick.id))}')">
    <div class="heroMatchTeams">${esc(pick.home.name)} <span class="mvvs">v</span> ${esc(pick.away.name)}
      ${pick._comp?`<span class="compTag">${esc(pick._comp)}</span>`:''}
      ${pick.status==='LIVE'?'<span class="heroLive">LIVE</span>':''}</div>
    ${pr.pick_name?`<div class="heroMatchPick">model: <b>${esc(pr.pick_name)}</b>${pr.confidence?` ${pr.confidence}%`:''}</div>`:''}
  </div>`;
}
function landingHero(){
  const sc=DATA.scorecard;
  const slim=heroSeen();
  const rec=sc&&sc.graded?`<span class="heroRec"><b>${sc.model_hits}-${sc.graded-sc.model_hits}</b> record</span>${sc.brier!=null?`<span class="heroRec">Brier <b>${sc.brier}</b></span>`:''}${sc.clv_avg!=null?`<span class="heroRec">CLV <b>${sc.clv_avg>0?'+':''}${sc.clv_avg}</b></span>`:''}`:`<span class="heroRec faintline">record builds as picks grade</span>`;
  if(slim)return `<div class="heroSlim">${rec}<span class="heroSlimLink" onclick="setView('score')">full scorecard →</span></div>`;
  return `<div class="heroBand">
    <img src="logo.png?v=4" class="heroLogo" alt="Matchday">
    <div class="heroTitle">A transparent sports model.</div>
    <div class="heroSub">Every pick locked before kickoff, graded in public — across football, and more sports as their seasons start. No tips, no ads, just an accountable model.</div>
    <div class="heroRow">${rec}</div>
    ${heroMarquee()}
    <div class="heroActions">
      <button class="btmbtn heroBtn" onclick="heroDismiss()">Enter the terminal</button>
      <button class="btmbtn heroBtn ghost" onclick="heroDismiss();setView('community')">Think you can beat the model?</button>
    </div>
  </div>`;
}
function enhanceMatchCards(host){
  host.querySelectorAll('.card .head').forEach(head=>{
    const card=head.closest('.card'),m=BYID[card?.dataset.id];
    if(isFavoriteMatch(m)){card.classList.add('favoriteMatch');if(!head.querySelector('.favoriteTag'))head.insertAdjacentHTML('beforeend',`<span class="favoriteTag">${t('My team')}</span>`)}
    head.setAttribute('role','button');head.setAttribute('tabindex','0');
    if(m)head.setAttribute('aria-label',`Open ${m.home?.name||'home'} versus ${m.away?.name||'away'}`);
    if(card.classList.contains('compactCard')&&m?.prediction){
      const op=_v10OfficialPick(m),edge=_v10OfficialEdge(m,op),label=card.querySelector('.pick .pl'),note=card.querySelector('.pick .pnote');
      if(label)label.textContent='Model';
      if(note&&op.marketPct!=null){note.textContent=`market ${op.marketPct}%${edge==null?'':` · ${edge>0?'+':''}${edge} pt`}`;note.classList.add('compactSignal')}
    }
    const setFinishedLabel=()=>{if(m?.status!=='FINISHED')return;const status=document.querySelector('.matchModal.show .modalStatus');if(status)status.textContent='FT'};
    if(m?.status==='FINISHED'){const when=card.querySelector('.center>.kick');if(when)when.textContent='FT';head.addEventListener('click',setFinishedLabel)}
    head.addEventListener('keydown',event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();openMatchModal(card.dataset.id);setFinishedLabel()}});
  });
}
function renderMatches(){const M=DATA.matches||[];
  const active=M.filter(m=>!isCompleteOrPast(m)).sort(favoriteFixtureSort);
  const shown=active.slice(0,MATCH_VISIBLE),remaining=Math.max(0,active.length-shown.length);
  const missing=DATA._missing?`<div class="banner" style="grid-column:1/-1"><b>No ${esc(DATA.competition||'this sport')} data yet.</b> Fetch it once its season is available — run the matching start file (e.g. start_ucl.bat) or keep an eye out when the season begins.</div>`:'';
  const html=missing+landingHero()+`<div class="vhead">${t('Fixtures')}</div>`+
    (shown.length?shown.map(cardHTML).join(''):`<div class="empty" style="grid-column:1/-1">No live or upcoming matches to show.</div>`)+
    (remaining?`<div class="fixturePager"><span>Showing ${shown.length} of ${active.length} fixtures</span><button class="actionbtn" onclick="MATCH_VISIBLE+=FIXTURE_PAGE_SIZE;renderMatches()">Load ${Math.min(FIXTURE_PAGE_SIZE,remaining)} more</button></div>`:'');
  $('#view-matches').innerHTML=html;enhanceMatchCards($('#view-matches'));}
function renderResults(){const M=DATA.matches||[];
  const past=M.filter(isCompleteOrPast).sort((a,b)=>Number(isFavoriteMatch(b))-Number(isFavoriteMatch(a))||(b.kickoff||'').localeCompare(a.kickoff||''));
  const shown=past.slice(0,RESULT_VISIBLE),remaining=Math.max(0,past.length-shown.length);
  $('#view-results').innerHTML=`<div class="vhead">${t('Results')}</div>`+
    (shown.length?shown.map(cardHTML).join(''):`<div class="empty" style="grid-column:1/-1">No completed matches yet.</div>`)+
    (remaining?`<div class="fixturePager"><span>Showing ${shown.length} of ${past.length} results</span><button class="actionbtn" onclick="RESULT_VISIBLE+=FIXTURE_PAGE_SIZE;renderResults()">Load ${Math.min(FIXTURE_PAGE_SIZE,remaining)} more</button></div>`:'');enhanceMatchCards($('#view-results'));}
function groupLetter(g){return String(g||'').replace(/^Group\s*/i,'').replace(/^GROUP_/i,'').trim()}
function cleanGroup(g){g=String(g||'').trim();if(!g)return'';if(/^GROUP_/i.test(g))return g.replace('GROUP_','Group ').replaceAll('_',' ').replace(/\b\w/g,c=>c.toUpperCase());if(/^Group\s+/i.test(g))return 'Group '+groupLetter(g).toUpperCase();return g}
function rowKey(n){return String(n||'').toLowerCase().replace(/[^a-z0-9]+/g,' ').trim()}
function ensureRow(map,team,group){const key=rowKey(team?.name);if(!key)return null;if(!map[key])map[key]={name:team?.name||'',code:team?.code||'',group:cleanGroup(group||team?.group),pld:0,w:0,d:0,l:0,gf:0,ga:0,gd:0,pts:0,form:'',live:false,results:[]};else{map[key].code=map[key].code||team?.code||'';map[key].group=map[key].group||cleanGroup(group||team?.group)}return map[key]}
function addResult(row,gf,ga,live,kick){row.pld++;row.gf+=gf;row.ga+=ga;row.gd=row.gf-row.ga;if(gf>ga){row.w++;row.pts+=3;row.results.push([kick,'W'+(live?'*':'')])}else if(gf<ga){row.l++;row.results.push([kick,'L'+(live?'*':'')])}else{row.d++;row.pts+=1;row.results.push([kick,'D'+(live?'*':'')])}row.live=row.live||live}
function deriveStandings(){if(Array.isArray(DATA.standings)&&DATA.standings.length)return DATA.standings;const rows={},M=DATA.matches||[];M.forEach(m=>{const g=cleanGroup(m.home?.group||m.away?.group||(/^Group/i.test(m.stage||'')?m.stage:''));if(!g)return;const h=ensureRow(rows,m.home,g),a=ensureRow(rows,m.away,g);const sh=m.score?.home,sa=m.score?.away;const live=m.status==='LIVE';if(h&&a&&(m.status==='FINISHED'||m.status==='LIVE')&&Number.isFinite(Number(sh))&&Number.isFinite(Number(sa))){addResult(h,Number(sh),Number(sa),live,m.kickoff||'');addResult(a,Number(sa),Number(sh),live,m.kickoff||'')}});Object.values(rows).forEach(r=>{r.results.sort((a,b)=>String(a[0]).localeCompare(String(b[0])));r.form=r.results.slice(-5).map(x=>x[1]).join(' ')});const by={};Object.values(rows).forEach(r=>{if(!r.group)return;(by[r.group] ||= []).push(r)});return Object.keys(by).sort((a,b)=>groupLetter(a).localeCompare(groupLetter(b))).map(g=>{by[g].sort((x,y)=>(y.pts-x.pts)||(y.gd-x.gd)||(y.gf-x.gf)||String(x.name).localeCompare(y.name));by[g].forEach((r,i)=>r.pos=i+1);return {group:g,teams:by[g]}})}
function getThirdRace(){let third=Array.isArray(DATA.third_race)&&DATA.third_race.length?DATA.third_race.map(x=>({...x})):deriveStandings().flatMap(g=>(g.teams||[]).filter(t=>t.pos===3).map(t=>({team:t.name,name:t.name,code:t.code,group:g.group,pts:t.pts,gd:t.gd,gf:t.gf,live:t.live})));third.sort((a,b)=>(b.pts-a.pts)||(b.gd-a.gd)||(b.gf-a.gf)||String(a.team||a.name).localeCompare(String(b.team||b.name)));third.forEach((t,i)=>{t.in=i<8;t.team=t.team||t.name});return third}
function getProjectedSlots(){const existing=DATA.projected_bracket?.slots||[];if(existing.length)return existing;const slots=[];deriveStandings().forEach(g=>{const gl=groupLetter(g.group);(g.teams||[]).forEach(t=>{if(t.pos===1||t.pos===2)slots.push({slot:`${gl}${t.pos}`,team:t.name,code:t.code,pts:t.pts,gd:t.gd,live:t.live})})});getThirdRace().slice(0,8).forEach((t,i)=>slots.push({slot:`3rd #${i+1}`,team:t.team,code:t.code,pts:t.pts,gd:t.gd,live:t.live}));return slots}
/* removed duplicate (sourceName) */
/* removed duplicate (renderGroups) */
/* removed duplicate (bracketTeam) */
function bracketMatch(km,ri,mi,last=false){const live=km.status==='LIVE',done=km.status==='FINISHED';const hs=km.score?.home,as=km.score?.away;const hw=done&&Number(hs)>Number(as),aw=done&&Number(as)>Number(hs);return `<div class="bracketMatch ${last?'':'hasNext'}"><div class="bmMeta"><span>${esc(km.stage||km.round||`Match ${mi+1}`)}</span><span>${live?'LIVE':done?'FT':km.kickoff?dt(km.kickoff):'TBD'}</span></div>${bracketTeam(km.home,km.home_code,'',done||live?hs:null,hw,live)}${bracketTeam(km.away,km.away_code,'',done||live?as:null,aw,live)}</div>`}
/* removed duplicate (projectedRounds) */
function projectedMatch(km,ri,mi,last=false){return `<div class="bracketMatch ${last?'':'hasNext'}"><div class="bmMeta"><span>${esc(km.stage||'Projected')}</span><span>${ri===0?'field':'path'}</span></div>${bracketTeam(km.home,km.home_code,km.home_slot,null,false,false)}${bracketTeam(km.away,km.away_code,km.away_slot,null,false,false)}</div>`}
/* removed duplicate (renderBracket) */
function renderThird(){const host=$('#view-third'),third=getThirdRace();if(!third.length){host.innerHTML=`<div class="vhead">Third-place tracker</div><div class="empty">Third-place race not available yet.</div>`;return}const cut=third[7];host.innerHTML=`<div class="vhead">Third-place tracker</div><div class="thirdList"><div class="thirdHead"><span>Rank</span><span>Team</span><span>Group</span><span>Pts</span><span>GD</span><span>Status</span></div>${third.map((t,i)=>`<div class="thirdRow ${t.in?'in':'out'}"><div class="thirdRank">#${i+1}</div><div class="thirdTeam"><div class="name">${esc(t.code||'')} ${esc(t.team||'')} ${t.live?'<span class="liveMark">*</span>':''}</div><div class="group">${esc(t.group||'')} · GF ${t.gf??0}</div></div><div class="thirdNum">${esc(t.group||'')}</div><div class="thirdNum pts">${t.pts}</div><div class="thirdNum gd">${t.gd>0?'+':''}${t.gd}</div><div class="thirdBadge ${t.in?'in':''}">${t.in?'IN':'CHASE'}</div></div>`).join('')}<div class="thirdCut">Cut line: ${cut?`${esc(cut.team||cut.name)} at ${cut.pts} pts, GD ${cut.gd>0?'+':''}${cut.gd}`:'waiting for enough teams'}.</div></div>`}
/* removed duplicate (renderTitle) */
/* removed duplicate (renderEdge) */
/* removed duplicate (newsSources) */
/* removed duplicate (renderNews) */

const SYSTEM_UPDATES=[
  {date:'Build 0720F',tag:'Fix',title:'Predictions were flat/identical for every match — root cause fixed',items:[
    'Team power-rating files (public FIFA-rank/squad-value/preseason-strength data) were accidentally excluded from every deploy — every team fell back to the same default, so picks came down to home-field advantage alone. They\'re now correctly shipped with every build.',
    'The Matchup Sandbox had the same problem — it now uses the same class/power-rating signal, so picking a strong team against a weak one actually moves the percentages.',
    'Sandbox also falls back to the scheduled-fixtures team list when a sport has no standings yet (true preseason), instead of going blank.']},
  {date:'Build 0720E',tag:'Fix',title:'NFL and NBA back on real, current-season data',items:[
    'Both had drifted onto a provider whose free tier is hard-capped at the 2022-2024 seasons — reverted to a provider with real 2026 schedules and derive standings ourselves from finished results, since it has no standings endpoint.']},
  {date:'Build 0720D',tag:'New',title:'Community leaderboard is live',items:[
    'The shared "Beat the Model" board is connected to a real backend — no more free-text handles. Everyone is assigned a real player\'s name (from live scorer data or a curated pool) instead, so the board can\'t be used for offensive names. One reshuffle allowed if you don\'t like the draw.']},
  {date:'Build 0720C',tag:'New',title:'First-visit guided tour',items:[
    'New visitors get a short walkthrough of the tabs that are actually relevant to whatever sport they land on, replayable anytime from Customize.']},
  {date:'Build 0720B',tag:'Model',title:'Self-training Elo, head-to-head history, and recency-weighted form',items:[
    'A dynamic Elo rating now updates after every result and factors into every pick, alongside a real per-matchup head-to-head record — both start neutral and get more accurate the longer the site runs.',
    'Recent form now weights the last few games more than older ones, and home/away form are tracked separately instead of blended.',
    'Closed a gap where an underdog pick could flip with no market data to check it against — that now requires real evidence, not just the model\'s own math.']},
  {date:'Build 0720A',tag:'Fix',title:'Smaller display fixes',items:[
    'Team of the Tournament no longer claims defense data it doesn\'t have — an honest note instead of a misleading one.',
    'Sandbox team pickers are properly themed instead of raw white dropdowns.',
    'Combined score/points predictions for NFL, NBA and other non-soccer sports no longer say "goals."',
    'The match modal\'s Model read panel is full-width again instead of being squeezed next to the odds tracker.']},
  {date:'Build 0707B',tag:'Model',title:'Injuries now affect predictions',items:[
    'The model now factors in key players ruled OUT — data it already fetched but never used. A team missing stars is rated slightly weaker.',
    'Weighted per sport (one absence swings basketball far more than baseball) and kept deliberately small, since the market already prices injuries and we blend with it.',
    'Shows up as an "injuries" chip in the Match Story so you can see when it moved a pick.']},
  {date:'Build 0707A',tag:'New',title:'Title races for all five leagues',items:[
    'La Liga, Serie A, Bundesliga and Ligue 1 now have championship-odds panels like the Premier League — each big league shows its live title race.',
    'If a league is between seasons or a market is unavailable, the panel simply hides rather than erroring.']},
  {date:'Build 0706Z',tag:'Model',title:'Market-implied team strength for US sports',items:[
    'US sports (NFL, NBA, MLB, NHL, College Football) had no squad-value equivalent because salary caps make roster prices meaningless. They now derive team strength from championship odds — the market\'s own valuation of each team.',
    'This is the honest equivalent of soccer squad values, sourced live from the odds already fetched, replacing rough rank estimates.',
    'Still market-anchored, not yet per-sport calibrated — that needs a full season of results, which the pick log is now collecting.']},
  {date:'Build 0706Y',tag:'Fix',title:'Record grading corrected + easy refresh',items:[
    'Confirmed fix: the model record now correctly reads 12/17 — penalty-affected games like Argentina v Switzerland grade as HITs. The app self-heals old mis-gradings on every fetch.',
    'Added a small refresh button on the scorecard so new results show instantly without restarting (the app also auto-refreshes every 60 seconds).']},
  {date:'Build 0706W',tag:'Fix',title:'Scorecard self-heals mis-gradings on every fetch',items:[
    'The previous fix only corrected games still inside the fetch window; older rounds (like the quarter-finals) kept showing wrong results. The scorecard now re-checks EVERY stored pick on every build, so a non-level score can never display as a draw/miss.',
    'Argentina v Switzerland 2-0 and the other affected games now correctly show HIT.',
    'No separate script needed — just fetch once and the record corrects itself.']},
  {date:'Build 0706V',tag:'Fix',title:'Corrupted gradings repaired — record was understated',items:[
    'Found and fixed a grading bug: some finished games were wrongly stored as draws (a 2-0 counted as a draw), which counted correct picks as misses.',
    'Added a consistency guard so a non-level scoreline can never be graded as a draw again.',
    'New repair_picks.py corrects the historical mistakes in your saved record — run it once. Your model record was being understated (true record is higher).',
    'Your locked PICKS never changed — only the win/loss grading was wrong, and is now correct.']},
  {date:'Build 0706U',tag:'Brand',title:'New Matchday logo',items:[
    'The split-ring M logo is now the app icon everywhere — browser tab, phone home screen, and the landing screen.']},
  {date:'Build 0706T',tag:'Fix',title:'Multi-sport fetcher works on Windows',items:[
    'Fixed the real cause of the multi-sport fetcher failing: Windows terminals use a legacy text encoding that crashed on special characters (the checkmark in "Wrote data.json", accented player names). The fetcher now forces UTF-8 output.',
    'All sports should now fetch and refresh automatically as intended.']},
  {date:'Build 0706R',tag:'Security',title:'Security layer for non-coders',items:[
    'New one-click security check (check_security.bat): scans everything and tells you in plain English whether it is safe to share or publish — and exactly how to fix anything it finds.',
    'Plain-English SECURITY.md explains the real risks and the one habit that matters (keys only ever go in config_keys.py).',
    'Error messages now mask API keys even when they appear inside request headers, so no screenshot can leak them.']},
  {date:'Build 0706Q',tag:'New',title:'Community: achievements & challenge cards',items:[
    'Expanded achievements: Upset Caller (called an underdog the model missed), Perfect Week, All-Rounder (wins across 3+ sports), Oracle, Veteran and more.',
    'A "Today\'s Call" challenge card surfaces the most interesting upcoming match — where the model and market disagree — and frames it as a side to take.',
    'Both build on your existing picks; no new data needed.']},
  {date:'Build 0706P',tag:'New',title:'MLB + NHL, plus personal analytics & seasons',items:[
    'MLB and NHL added end-to-end (standings, model picks, championship odds) — twelve sports now share the platform.',
    'Community: a Your Tendencies panel shows whether you are sharper on favorites or underdogs, how you do when you defy the model, and your hit rate per competition.',
    'Community: 4-week Seasons that archive your record so a cold streak resets — chase Season winners over time.',
    'Both are local; the global leaderboard is still one deploy away.']},
  {date:'Build 0706O',tag:'Fix',title:'Picks settle on the 90-minute market',items:[
    'Draw picks now grade correctly: a knockout game level after regulation counts as a DRAW for the pick — extra time and penalties decide who advances, not the 1X2 result. This matches how the betting market your model predicts against actually settles.',
    'Past picks graded under the old rule are automatically corrected on the next fetch (the diagnostics list each regrade).',
    'Beat the Model picks follow the same convention.',
    'Scorelines still display the full story: final score plus the shootout tag.']},
  {date:'Build 0706N',tag:'App',title:'Multi-sport fetcher — one button, everything fresh',items:[
    'start_app.bat now keeps ALL ten sports updated automatically: live matches refetch every minute, upcoming ones hourly, near-season every 6 hours, offseason sports probe twice a day.',
    'Sports fetch one at a time with spacing, so API quotas never spike regardless of how many are in season.',
    'No more manual per-sport fetches — the one-off fetch_X_once.bat files remain for instant refreshes when you want them.',
    'Launching with a sport flag (e.g. start_nfl.bat) still runs that sport alone, as before.']},
  {date:'Build 0706M',tag:'New',title:'Top 5 leagues — Premier League, La Liga, Serie A, Bundesliga, Ligue 1',items:[
    'All five domestic leagues added end-to-end: fixtures and tables from football-data, odds and model picks, per-league scorecards, and Team of the Season from the player database.',
    'League tables carry real qualification zones: Champions League places, Europa League, and relegation (two-team zones for Germany and France where a playoff decides the third).',
    'Each league gets its own sidebar profile, ratings file (big-club values verified, others estimated), data file and one-click fetcher.',
    'Seasons start mid-August — ready before kickoff, same as everything else.']},
  {date:'Build 0706L',tag:'New',title:'NBA support — the four-sport platform is complete',items:[
    'Conference standings with direct playoff seeds (1-6) and the play-in zone (7-10) tagged.',
    'Season-length normalization: an 82-game NBA record and a 17-game NFL record now feed the model on the same scale.',
    'Per-game point differential handled correctly (ESPN reports NBA per-game, NFL season totals).',
    'ratings_nba.json seeds a 30-team power ranking; championship odds flow through the title pipeline.',
    'World Cup, Champions League, NFL, College Football and NBA now share one model, one scorecard system, one UI.']},
  {date:'Build 0706K',tag:'New',title:'College Football structure',items:[
    'Rankings are the spine: the app pulls the CFP rankings (AP Top 25 until they exist) and shows them as the lead table, with the top 12 tagged as projected playoff seeds.',
    'Rankings self-feed the model: ratings_ncaaf.json is rewritten from the live poll on every fetch — the model always rates teams by their current rank.',
    'Projected 12-team CFP bracket (straight seeding: 1-4 byes, 5v12, 6v11, 7v10, 8v9) renders in the new CFP Bracket tab until the real playoff exists.',
    'Conference standings via the same ESPN pipeline as the NFL.',
    'Season starts late August — the structure is ready first.']},
  {date:'Build 0706J',tag:'New',title:'NFL support',items:[
    'Real NFL standings: AFC/NFC division tables with records, point differential and current playoff seeds (top 7 per conference tagged).',
    'The model now feeds on real NFL data — wins, point differential and streaks map onto its inputs, predictions run two-way (no draws).',
    'Fixture window widened to show the past week and next month of games.',
    'New Standings tab in the US-sports menu; ratings_nfl.json seeds a 32-team power ranking (estimates, refine in season).',
    'Super Bowl odds already flow through the existing title-odds pipeline.']},
  {date:'Build 0706I',tag:'New',title:'Champions League support (2026-27 format)',items:[
    'Correct modern format: no group stage — a 36-team league phase table with the three real zones (top 8 straight to R16, 9-24 to the knockout playoffs, 25-36 out).',
    'Knockout playoff round added to the bracket and advancement chain between the league phase and the Round of 16.',
    'Sidebar shows "League Phase" instead of "Groups" in Champions League mode.',
    'ratings_ucl.json created: 21 confirmed qualifiers with UEFA coefficient ranks and club value estimates — the last 7 clubs arrive via qualifying in late August.',
    'Season starts September 8; the app is ready the day fixtures appear.']},
  {date:'Build 0706H',tag:'Fix',title:'Sports fully separated',items:[
    'Switching to a sport with no data no longer shows another sport\'s content — the app now clears the view and says honestly that this sport has no data yet and how to fetch it.',
    'Every tab (Forecast, Model, Groups…) now strictly shows the selected sport or an empty state, never a leftover.']},
  {date:'Build 0706G',tag:'New',title:'Landing hero',items:[
    'First-time visitors now land on a hero: what Matchday is (a transparent sports model, all sports), the live model record, today\'s marquee match with the model\'s pick, and a "beat the model" hook.',
    'After entering once, the hero collapses to a slim record strip for returning users.',
    'Sport-agnostic by design — the marquee and record follow whatever sports are in season.']},
  {date:'Build 0706F',tag:'New',title:'All Sports home + sidebar fix',items:[
    'The sport menu now starts on "All sports": a merged home feed showing every sport\'s fixtures and results together, each card tagged with its competition.',
    'Picking a sport filters everything down to that sport, with its own tailored sidebar.',
    'Fixed a scoping bug that could stop the sidebar adapting on switch.',
    'Status tab now shows the active menu profile — if the sidebar ever looks wrong, Status tells you what the app thinks it should be showing.']},
  {date:'Build 0706E',tag:'Fix',title:'Sidebar truly follows the sport',items:[
    'The menu now rebuilds from a per-sport definition the instant you pick a sport — before any data loads, even if that sport has no data yet.',
    'World Cup shows the full tournament menu; Champions League drops Thirds; NFL, College Football and NBA show a clean US-sports menu (no Groups, Bracket, Thirds or Team of the Tournament).',
    'If you are on a tab that does not exist for the new sport, you land on Matches.']},
  {date:'Build 0706D',tag:'New',title:'Player database + multi-sport groundwork',items:[
    'New player database: every finished match\'s lineup and result accumulates locally — appearances, starts, roles from formations, and clean sheets.',
    'Team of the Tournament now fields a real Defence and Goalkeeper line ranked by clean sheets (honest defensive data), alongside the goals/assists attack.',
    'One-time backfill script pulls every match since June 11 so the XI covers the whole tournament.',
    'The sidebar now adapts per sport — no more Groups/Bracket/Thirds when viewing NFL or NBA.',
    'College Football added to the sport menu (experimental, like NFL/NBA).',
    'All of it competition-generic: Champions League and other sports reuse the same system.']},
  {date:'Build 0706C',tag:'App',title:'Architecture + security hardening',items:[
    'The app is now modular: styles.css plus four JS modules instead of one 233KB file — split losslessly (verified byte-identical) so behavior is unchanged, but future edits get far safer.',
    'Removed live API keys that were embedded as fallbacks in the fetcher — shipped copies no longer contain credentials.',
    'Added ROTATE_KEYS.md (step-by-step key rotation) and a .gitignore protecting keys and personal data in any future repo.']},
  {date:'Build 0706B',tag:'Model',title:'Ratings toolchain',items:[
    'New update_ratings.py: merge fresh FIFA rankings from a downloaded CSV, set any value by hand, or print the table — one command each, with automatic backup.',
    'Per-competition ratings files supported: ratings_ucl.json (etc.) load automatically when running other competitions, falling back to the shared file.']},
  {date:'Build 0706A',tag:'Model',title:'Real market values + housekeeping',items:[
    'Squad values in the ratings file replaced with verified Transfermarkt figures (June 2026) for the top ~30 teams — the model now runs on real numbers, not estimates. Star-player values verified for the top squads (Mbappé, Haaland and Yamal all around €200M; Argentina\'s top value is Enzo Fernández/Julián Álvarez at ~€90M, not Messi).',
    'Removed the dead FIFA news feed that errored on every fetch (the working backup feed remains).',
    'Odds history now self-cleans: entries from other sports (inherited during an old migration) are pruned automatically.']},
  {date:'Build 0705Z',tag:'Fix',title:'Stale Team of the Tournament guard',items:[
    'Player positions are computed at fetch time — if the app is showing an XI built before the position fix, it now says so and asks for one fetch instead of displaying strikers in goal.']},
  {date:'Build 0705Y',tag:'Fix',title:'Team of the Tournament repaired',items:[
    'Players are now grouped by their REAL positions from the data — no more strikers relabeled as goalkeepers or defenders to fill a formation.',
    'Lines without scoring players (like goalkeepers) are honestly omitted instead of faked.',
    'Restored the missing pitch styling — the tab renders as a proper visual pitch again, not plain text.']},
  {date:'Build 0705X',tag:'UI',title:'Community tab depth',items:[
    'Added a head-to-head insight bar: how often your picks matched the model, how you did when you went your own way, and your net record against it.',
    'Warmer empty state that invites you to try out-reading the model.']},
  {date:'Build 0705W',tag:'Fix',title:'Penalty shootouts handled correctly',items:[
    'Knockout games decided on penalties now show the regulation scoreline (e.g. 1-1) with the shootout result noted separately, instead of counting penalties as goals.',
    'The winner — and pick grading — now resolves via the shootout, not by adding penalty kicks to the score.',
    'Standings and goal difference no longer inflated by shootout tallies.']},
  {date:'Build 0705V',tag:'Fix',title:'Scorecard tabs + empty space',items:[
    'Fixed the Scorecard deep-dive tabs rendering as plain white text — styles were missing.',
    'Forecast board now flows as balanced columns, so a short panel (like Upset radar) no longer leaves a big gap under it next to a long one (Golden Boot).']},
  {date:'Build 0705U',tag:'Fix',title:'Groups cleanup',items:[
    'Removed the stray Golden Boot race from the Groups tab — it lives on the Odds board where it belongs.']},
  {date:'Build 0705T',tag:'New',title:'Scorecard Deep Dive',items:[
    'Scorecard now has tabs: Overview, Calibration, Signals, Upsets, Errors.',
    'Signal quality shows which factors (class, form, goal diff, rest) actually help when they favour a pick.',
    'Error review lists recent misses with the evidence captured at lock time.',
    'Deeper tabs show honest "unlocks after N picks" states until the sample is real.']},
  {date:'Build 0705S',tag:'New',title:'Watchlist, alerts & Team of the Tournament',items:[
    'Star any team to add it to your Watchlist; an alert bar surfaces kickoffs, live scores and live upset flags for followed teams.',
    'Live upset alerts appear for any match the model flags, watched or not.',
    'New Team of the Tournament tab: a model-built XI ranked by goals, assists and team strength (honest impact ranking, not per-player match ratings).']},
  {date:'Build 0705R',tag:'Model',title:'Upset radar redefined + deep-dive capture',items:[
    'Upset radar now uses the real statistical definition: the market underdog\'s win probability sets the class (pickem / minor / solid / major), and the radar only fires when the model prices a genuine underdog above the market.',
    'Coin-flip games no longer flag as upsets; confident favourites read as confident.',
    'Every locked pick now captures a full evidence snapshot (factor values, market odds, gap, upset profile, box-score availability) for the coming Scorecard Deep Dive.']},
  {date:'Build 0705Q',tag:'Fix',title:'Upset radar only fires on real volatility',items:[
    'Match Story no longer says every game is "on the upset radar".',
    'Upset language is now gated on the model\'s own 0-100 score: live threat at 65+, mild watch at 50-64, and confident/clear reads below that.',
    'Confident favourites now read as confident, not as upset risks.']},
  {date:'Build 0705P',tag:'Fix',title:'Match Story visible + data order',items:[
    'Match Story card now actually renders at the top of the expanded match view (it was built but not shown).',
    'Stats and lineups now fetch BEFORE predictions, so the model uses them the same run.',
    'Box-score empty states rewritten to explain what the model falls back on.',
    'Clearer box-stat diagnostics showing attached/total and coverage warnings.']},
  {date:'Build 0705O',tag:'New',title:'Leaderboard ready (dormant)',items:[
    'Global leaderboard code is built and shipped but inactive — shows "Coming soon" until a server URL is set.',
    'When you deploy the backend and paste its URL, picks post automatically and the Community tab shows live rankings.',
    'Anonymous handle + device ID; no accounts. Server code and deploy guide included for two hosting paths.']},
  {date:'Build 0705N',tag:'UI',title:'Match Story + model credibility',items:[
    'Every expanded match now opens with a Match Story card: one clear read on who the model picks, whether an upset is live, and why — generated from the real model output.',
    'The Model tab now leads with a credibility strip: recent record, Brier, CLV and value-signal hit rate.',
    'Gives the app a clear main answer instead of many equal panels.']},
  {date:'Build 0705M',tag:'UI',title:'Results moved to its own tab',items:[
    'Completed matches now live in a dedicated Results tab — Fixtures stays clean with only live and upcoming.',
    'Reverted the dimmed inline section.']},
  {date:'Build 0705L',tag:'Fix',title:'Box scores confirmed + honest empty state',items:[
    'Box scores are attaching from ESPN and API-Football (verified via diagnostics).',
    'Finished matches without stats now say so honestly instead of "appears once the match kicks off".',
    'Widened the stats window to cover the last 20 finished matches, not 10.']},
  {date:'Build 0705K',tag:'UI',title:'Cleaner past matches',items:[
    'Completed matches now sit in their own separated, dimmed section below live and upcoming — no more flooding the fixtures board.',
    'Sorted newest-first, with a divider and a count.']},
  {date:'Build 0705J',tag:'New',title:'Community — Beat the Model',items:[
    'New Community tab: lock your own pick before kickoff and get graded against the model and the market.',
    'Tracks your record, current streak, times you beat the model, and earns badges.',
    'Runs locally for now; built to connect to a shared leaderboard next.']},
  {date:'Build 0705I',tag:'i18n',title:'Interface translations + box-score probe',items:[
    'Interface now available in Spanish, French, German, Portuguese and Russian — pick it under Customize > Language.',
    'Match data stays in source language; the app chrome translates.',
    'Added an ESPN payload probe to diagnostics to pin down why box scores are not attaching.']},
  {date:'Build 0705H',tag:'Data',title:'Free box scores via ESPN',items:[
    'Match statistics (shots, possession, corners, fouls, cards, saves) now come from ESPN — no key, no quota, using requests the lineups fetch already makes.',
    'Covers live matches and the last week of finished games.',
    'API-Football stays as an optional upgrade: with a paid key present it takes priority automatically.']},
  {date:'Build 0705G',tag:'App',title:'Box scores, adaptive upsets, cleanup',items:[
    'Box-score stats for recent matches via API-Football (optional key in config_keys.py).',
    'Upset candidates scored and tracked; the model self-tunes from graded results with strict small-sample guards.',
    'Safer match view: a fallback panel replaces blank screens if match data errors.',
    'Removed 17 duplicate function bodies introduced during recent edits.']},
  {date:'Build 0705E',tag:'Fix',title:'Stability and layout repairs',items:[
    'Restored from a bad build that broke loading — full function audit now runs before every release.',
    'Advancement odds table columns align across all rows.',
    'Expanded match view stacks panels until the window is genuinely wide.',
    'Factor receipt chips no longer overlap when wrapping.',
    'Fixed the "Box-score stats" empty-state sentence.']},
  {date:'Build 0705',tag:'Model',title:'Transparent scorecard and smarter model',items:[
    'Scorecard: picks lock before kickoff, grade at full time, never rewritten.',
    'Closing line value, Brier score and calibration bands.',
    'Value signals graded in parallel without overriding the pick.',
    'Ten-factor model with receipts on every pick.']},
  {date:'Build 0705',tag:'Odds',title:'Odds board expansion',items:[
    'Movers since open, bookmaker disagreement, match markets with the model inline, advancement odds, Golden Boot race, title odds with flags, decimals and movement.']},
  {date:'Build 0705',tag:'App',title:'Multi-sport groundwork and cleanup',items:[
    'Sport menu (WC, UCL, NFL, NBA), compact cards with a Customize toggle, live-match glow, data-status badge, analyst read, 29 duplicate functions removed, keys scrubbed, analytics-only disclaimers.']},
  {date:'Earlier',tag:'UI',title:'System updates hub',items:['Updates tab added.','Main screens cleaned.']},
  {date:'Recent',tag:'UI',title:'Model command center',items:[
    'Reworked the Model tab into compact KPIs, filter chips, a best-read spotlight, and a scan-friendly pick board.',
    'Clicking a model row still opens the larger match view with the original model and odds fields.'
  ]},
  {date:'Recent',tag:'UI',title:'Fixture spotlight modal',items:[
    'Match cards open in a larger modal instead of expanding downward and creating empty vertical space.',
    'The modal groups model pick, odds, match read, stats, and lineups into a more readable layout.'
  ]},
  {date:'Recent',tag:'UI',title:'Bracket, thirds, and live-strip polish',items:[
    'Bracket was redesigned into a smaller two-sided tournament view.',
    'Third-place tracker was changed into a top-to-bottom ranking table.',
    'Top strip text spacing and past-match hiding were cleaned up.'
  ]},
  {date:'Recent',tag:'Feeds',title:'News UI fixes',items:[
    'News cards preserve source labels better and the all-sources view is designed to avoid one feed visually dominating.',
    'This UI tab does not fetch news itself; it only displays what your existing data.json provides.'
  ]}
];
function markUpdatesRead(){localStorage.setItem('matchday.updates.lastSeen',new Date().toISOString());renderSystemUpdates()}
function renderSystemUpdates(){const host=$('#view-updates');const seen=localStorage.getItem('matchday.updates.lastSeen');const latest='build 0720F';host.innerHTML=`<div class="updatesShell"><div class="updatesHero"><section class="updatesIntro"><h2>System updates</h2><span class="safePill">UI</span></section><aside class="buildCard"><div class="tiny">Current build</div><div class="build">${esc(latest)}</div><div class="hint">Last viewed: ${seen?esc(ago(seen)):'not marked yet'}</div><div class="updateActions"><button class="miniBtn" onclick="markUpdatesRead()">Mark as read</button><button class="miniBtn" onclick="setView('status')">Open Status</button></div></aside></div><section class="timeline"><div class="timelineHead"><h3>Release notes</h3><span>${SYSTEM_UPDATES.length} entries</span></div>${SYSTEM_UPDATES.map(u=>`<article class="updateItem"><div class="updateDate">${esc(u.date)}</div><div><div class="updateTitle"><span>${esc(u.title)}</span><span class="updateBadge">${esc(u.tag)}</span></div><ul>${u.items.map(i=>`<li>${esc(i)}</li>`).join('')}</ul></div></article>`).join('')}</section></div>`}

function renderStatus(){const host=$('#view-status'),M=DATA.matches||[],st=deriveStandings(),third=getThirdRace();const live=M.filter(m=>m.status==='LIVE').length,up=M.filter(m=>m.status==='UPCOMING').length,fin=M.filter(m=>m.status==='FINISHED').length;const next=M.filter(isVisibleUpcoming).sort((a,b)=>(a.kickoff||'').localeCompare(b.kickoff||''))[0];host.innerHTML=`<div class="vhead">App Status</div><div class="hint" style="margin-bottom:10px">menu profile: <b>${navProfile()}</b> · sport file: <b>${DATA_FILE||'all (merged)'}</b></div><div class="status-grid"><div class="statuscard ${LAST_OK?'ok':'warn'}"><span class="slbl">Data file</span><div class="sval">${LAST_OK?'loaded':'not loaded'}</div><div class="hint">${LAST_ERROR?esc(LAST_ERROR):'Loaded'}</div></div><div class="statuscard info"><span class="slbl">Source</span><div class="sval">${esc(DATA.source_note||'unknown')}</div><div class="hint">${esc(DATA.standings_mode||'')}</div></div><div class="statuscard info"><span class="slbl">Updated</span><div class="sval">${DATA.updated?ago(DATA.updated):'unknown'}</div><div class="hint">${esc(DATA.updated||'—')}</div></div><div class="statuscard info"><span class="slbl">Matches</span><div class="sval">${M.length}</div><div class="hint">${live} live · ${up} upcoming · ${fin} finished</div></div><div class="statuscard info"><span class="slbl">Groups</span><div class="sval">${st.length}</div><div class="hint">${third.length} third-place teams tracked</div></div><div class="statuscard info"><span class="slbl">News Items</span><div class="sval">${(DATA.news||[]).length}</div><div class="hint">${newsSources().filter(s=>s!=='all').join(' · ')}</div></div></div><div class="btnline"><button class="actionbtn" onclick="load(true)">Reload Data Now</button><button class="actionbtn" onclick="setView('groups')">Open Groups</button><button class="actionbtn" onclick="setView('third')">Open Thirds</button><button class="actionbtn" onclick="setView('updates')">System Updates</button></div>`}
function lopt(v,label,cur){return `<option value="${v}" ${v===cur?'selected':''}>${label}</option>`}
function opt(v,label,cur){return `<option value="${v}" ${String(cur)===String(v)?'selected':''}>${label}</option>`}function checked(v){return v?'checked':''}

// ---- Watchlist + in-app alerts -------------------------------------------
function wlLoad(){try{return JSON.parse(localStorage.getItem('matchday.watch')||'[]')}catch(e){return []}}
function wlSave(a){try{localStorage.setItem('matchday.watch',JSON.stringify(a))}catch(e){}}
function wlHas(team){return wlLoad().includes(team)}
function wlToggle(team){let a=wlLoad();if(a.includes(team))a=a.filter(t=>t!==team);else a.push(team);wlSave(a);renderCurrent();renderAlerts();}
function watchedMatches(){const w=wlLoad();if(!w.length)return [];return (DATA.matches||[]).filter(m=>w.includes(m.home.name)||w.includes(m.away.name));}
function computeAlerts(){const out=[];const now=Date.now();
  (DATA.matches||[]).forEach(m=>{const watched=wlHas(m.home.name)||wlHas(m.away.name);
    // live upset on ANY match the model flags
    const up=m.prediction&&m.prediction.upset;
    if(m.status==='LIVE'&&up&&up.radar){out.push({t:'upset',txt:`Live upset alert: ${esc(up.candidate_name)} live vs the favourite`,id:m.id});}
    if(!watched)return;
    if(m.status==='LIVE'){out.push({t:'live',txt:`${esc(m.home.code)} ${m.score?.home??0}-${m.score?.away??0} ${esc(m.away.code)} — LIVE now`,id:m.id});}
    else if(m.status==='UPCOMING'&&m.kickoff){const mins=Math.round((new Date(m.kickoff)-now)/60000);
      if(mins>0&&mins<=90)out.push({t:'soon',txt:`${esc(m.home.name)} v ${esc(m.away.name)} — kickoff in ${mins}m`,id:m.id});}
  });
  return out.slice(0,6);}
function renderAlerts(){const bar=$('#alertBar');if(!bar)return;const a=computeAlerts();
  if(!a.length){bar.style.display='none';return;}
  bar.style.display='';bar.innerHTML=a.map(x=>`<span class="alertPill ${x.t}" onclick="openMatchModal('${x.id}')">${x.t==='upset'?'&#9889; ':x.t==='live'?'&#128308; ':'&#9203; '}${x.txt}</span>`).join('');}
// ---- Beat the Model (local, server-ready) --------------------------------
// All persistence flows through these two seams. Tier 2 swaps their bodies to
// also hit a server; nothing else in the feature changes.
// ---- Tier 2 leaderboard (dormant until LEADERBOARD_URL is set) -----------
const LEADERBOARD_URL = "https://matchday-lake-omega.vercel.app/api/leaderboard";
function deviceId(){let id;try{id=localStorage.getItem('matchday.device')}catch(e){}
  if(!id){id='mdx-'+Math.random().toString(36).slice(2)+Date.now().toString(36);try{localStorage.setItem('matchday.device',id)}catch(e){}}return id;}
function myHandle(){try{return localStorage.getItem('matchday.handle')||''}catch(e){return ''}}
// ---- Community identity: assigned real-player names, never free text ------
// A free-text handle on a shared public board is an open door for offensive
// or trolling names. Rather than moderate input, there's no input at all --
// everyone is assigned a real player's name (their favorite team's, when we
// have live data for it; a curated pool otherwise), with exactly one
// reshuffle allowed if they don't like the draw.
const US_SPORT_NAME_POOL={
  nfl:['Patrick Mahomes','Josh Allen','Christian McCaffrey','Justin Jefferson','Myles Garrett','CeeDee Lamb','Micah Parsons','Tyreek Hill','Nick Bosa',"Ja'Marr Chase"],
  nba:['Nikola Jokic','Luka Doncic','Shai Gilgeous-Alexander','Giannis Antetokounmpo','Jayson Tatum','Anthony Edwards','Victor Wembanyama','Devin Booker','Tyrese Haliburton','Anthony Davis'],
  ncaaf:['Arch Manning','Carson Beck','Dylan Raiola','Jeremiah Smith','Ryan Williams'],
  ncaam:['Cooper Flagg','Ace Bailey','Cameron Boozer','Darryn Peterson'],
};
const GENERAL_NAME_POOL=[].concat(...Object.values(US_SPORT_NAME_POOL));
function _handlePool(){
  const sportKey=String(DATA?.comp_key||'').toLowerCase();
  const scorers=(DATA?.scorers||[]).map(s=>s.name).filter(Boolean);
  if(favoriteTeam()&&scorers.length){
    const teamOnes=(DATA.scorers||[]).filter(s=>isFavoriteTeam(s.team)).map(s=>s.name).filter(Boolean);
    if(teamOnes.length>=3)return teamOnes;
  }
  if(scorers.length>=5)return scorers;
  return US_SPORT_NAME_POOL[sportKey]||GENERAL_NAME_POOL;
}
function _drawHandle(exclude){
  const pool=_handlePool();
  const options=exclude?pool.filter(n=>n!==exclude):pool;
  const name=(options.length?options:GENERAL_NAME_POOL)[Math.floor(Math.random()*(options.length||GENERAL_NAME_POOL.length))]||'Anonymous Player';
  const tag=Math.floor(1000+Math.random()*9000); // disambiguates two users drawing the same player
  return `${name} #${tag}`;
}
function assignHandle(){
  const h=_drawHandle();
  try{localStorage.setItem('matchday.handle',h);localStorage.setItem('matchday.handleAssigned','1');localStorage.setItem('matchday.handleReshuffled','0')}catch(e){}
  return h;
}
function canReshuffleHandle(){try{return localStorage.getItem('matchday.handleReshuffled')!=='1'}catch(e){return false}}
function reshuffleHandle(){
  if(!canReshuffleHandle())return;
  const base=myHandle().replace(/\s#\d+$/,'');
  const h=_drawHandle(base);
  try{localStorage.setItem('matchday.handle',h);localStorage.setItem('matchday.handleReshuffled','1')}catch(e){}
  renderCommunity();
}
function ensureHandle(){
  try{
    const assigned=localStorage.getItem('matchday.handleAssigned')==='1';
    if(!myHandle()||!assigned)assignHandle(); // first-time visitor, or force-migrates an old free-text handle
  }catch(e){}
}
async function pushScore(){ // called after grading; no-op until URL set + handle chosen
  if(!LEADERBOARD_URL||!myHandle())return;
  const s=btmStats(btmLoad());
  try{await fetch(LEADERBOARD_URL+'?action=score',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({deviceId:deviceId(),handle:myHandle(),hits:s.you,graded:s.n,streak:s.streak})});}catch(e){}
}
async function fetchLeaderboard(){
  if(!LEADERBOARD_URL)return null;
  try{const r=await fetch(LEADERBOARD_URL+'?action=leaderboard');const d=await r.json();return d.ok?d.board:null;}catch(e){return null;}
}
function btmLoad(){try{return JSON.parse(localStorage.getItem('matchday.btm')||'{}')}catch(e){return {}}}
function btmSave(o){try{localStorage.setItem('matchday.btm',JSON.stringify(o))}catch(e){}}
function communityScope(){const k=String(DATA?.comp_key||'ALL').toUpperCase();return k==='ALL'?'ALL':k;}
function btmScoped(db){const scope=communityScope();if(scope==='ALL')return db;
  const picks={};Object.entries(db.picks||{}).forEach(([id,p])=>{if(String(p.comp||'WC').toUpperCase()===scope)picks[id]=p;});
  return {...db,picks};}
function submitPick(matchId,pick){ // <-- Tier 2: also POST to server here
  ensureHandle();
  const db=btmLoad();db.picks=db.picks||{};
  if(db.picks[matchId])return false; // one locked pick per match, like the model
  const m=(DATA.matches||[]).find(x=>String(x.id)===String(matchId));if(!m)return false;
  db.picks[matchId]={pick,ts:Date.now(),
    home:m.home.name,away:m.away.name,code:{h:m.home.code,a:m.away.code},
    comp:m._comp||DATA.comp_key||'',
    modelPick:m.prediction?m.prediction.pick:null,
    marketPick:(()=>{const x=(m.markets||{})['1x2'];if(!x||x.home_pct==null)return null;const tr={h:x.home_pct,d:x.draw_pct,a:x.away_pct};return Object.keys(tr).reduce((a,b)=>tr[b]>tr[a]?b:a)})()};
  btmSave(db);renderCommunity();pushScore();return true;
}
