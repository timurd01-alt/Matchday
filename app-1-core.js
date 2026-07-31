
const $=s=>document.querySelector(s);let DATA={matches:[],news:[],standings:[]},BYID={},VIEW='matches',LAST_OK=false,LAST_ERROR='',LOAD_TIMER=null,NEWS_FILTER='all';
const CAROUSELS={};
function prefersReducedMotion(){return !!(window.matchMedia&&matchMedia('(prefers-reduced-motion: reduce)').matches)}
// Small rotating carousel used by the welcome preview and the insight panel's
// "In focus" match -- cycles a fade-transitioned item every `intervalMs`,
// pauses on hover, and never auto-rotates for prefers-reduced-motion users
// (a single static item is shown instead, not a softened animation).
function runCarousel(key,items,host,renderFn,intervalMs){
  if(!host)return;
  const prev=CAROUSELS[key];if(prev&&prev.timer)clearInterval(prev.timer);
  if(!items||items.length<2){delete CAROUSELS[key];return}
  const st=CAROUSELS[key]={idx:0,items,renderFn,timer:null};
  st.advance=()=>{
    const s=CAROUSELS[key];if(!s)return;
    s.idx=(s.idx+1)%s.items.length;
    host.classList.remove('carouselFade');void host.offsetWidth;
    host.innerHTML=s.renderFn(s.items[s.idx]);
    host.classList.add('carouselFade');
  };
  if(!prefersReducedMotion())st.timer=setInterval(st.advance,intervalMs);
  if(!host.dataset.carouselBound){
    host.addEventListener('mouseenter',()=>{const s=CAROUSELS[key];if(s&&s.timer){clearInterval(s.timer);s.timer=null}});
    host.addEventListener('mouseleave',()=>{const s=CAROUSELS[key];if(s&&!s.timer&&s.items.length>1&&!prefersReducedMotion())s.timer=setInterval(s.advance,intervalMs)});
    host.dataset.carouselBound='1';
  }
}
const DEFAULT_SETTINGS={accent:'green',density:'normal',panel:'glass',defaultView:'matches',refresh:900,showInsight:true,showFinished:false,showDetails:false,favoriteTeam:'',alertsKickoff:true,alertsLive:false,alertsUpset:false,alertsModel:true,alertsData:true};
let SETTINGS={...DEFAULT_SETTINGS};try{SETTINGS={...DEFAULT_SETTINGS,...JSON.parse(localStorage.getItem('matchday.settings')||'{}')}}catch(e){}
// Refresh cadence is product-controlled so visitors cannot accidentally create
// excessive polling or make the dashboard feel stale.
SETTINGS.refresh=900;
// The analysis format intentionally has no in-game score or upset alerts.
// Clear older locally-saved preferences so the removed alert types cannot
// quietly reappear for returning visitors.
SETTINGS.alertsLive=false;
SETTINGS.alertsUpset=false;
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
  document.querySelectorAll('.navbtn .lbl,.navExternal .lbl').forEach(el=>{const en=el.getAttribute('data-en')||el.textContent.trim();el.setAttribute('data-en',en);el.textContent=dict[en]||en;});
  const walker=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT);
  let node;
  while((node=walker.nextNode())){
    if(node.parentElement?.closest('script,style,.navbtn,.navExternal,.nhead,.ndesc,.teamName,.modalName,.ins-match'))continue;
    const raw=node.nodeValue||'',trimmed=raw.trim();if(!trimmed)continue;
    const en=node.__matchdayEnglish||trimmed;node.__matchdayEnglish=en;
    const translated=translateUiText(en,dict);
    if(translated!==trimmed)node.nodeValue=raw.replace(trimmed,translated);
  }
  document.documentElement.lang=LANG||'en';
}
function t(s){if(!LANG||!window.MD_I18N||!MD_I18N[LANG])return s;return translateUiText(s,MD_I18N[LANG]);}
function setLang(v){LANG=v;try{localStorage.setItem('matchday.lang',v)}catch(e){};renderStrip();renderCurrent();renderInsight&&renderInsight();applyStaticI18n();renderAlerts();}
let DATA_FILE='';try{DATA_FILE=localStorage.getItem('matchday.sport')||'';if(/^data_nhl\.json$/i.test(DATA_FILE)){DATA_FILE='';localStorage.setItem('matchday.sport','')}}catch(e){}
const SPORT_LABELS={wc:'World Cup',ucl:'Champions League',epl:'Premier League',laliga:'La Liga',seriea:'Serie A',bundesliga:'Bundesliga',ligue1:'Ligue 1',nfl:'NFL',ncaaf:'College Football',ncaam:"Men's College Basketball",nba:'NBA',mlb:'MLB',nhl:'NHL'};
const FIXTURE_PAGE_SIZE=40;
let MATCH_VISIBLE=FIXTURE_PAGE_SIZE,RESULT_VISIBLE=FIXTURE_PAGE_SIZE;

// ---- per-sport sidebar (data-driven, follows the SELECTION) ---------------
// Each sport declares exactly which views exist for it, in order.
const NAV_DEF={
  all:         ['matches','results','advanced','community','tree','sandbox','news','insights','status','updates','customize'],
  soccer_cup:  ['matches','results','groups','title','edge','advanced','score','bracket','third','tott','community','tree','sandbox','news','insights','status','updates','customize'],
  soccer_club: ['matches','results','groups','title','edge','advanced','score','bracket','tott','community','tree','sandbox','news','insights','status','updates','customize'],
  us_sport:    ['matches','results','groups','title','edge','advanced','score','community','tree','sandbox','news','insights','status','updates','customize'],
  college:     ['matches','results','groups','bracket','title','edge','advanced','score','community','tree','sandbox','news','insights','status','updates','customize'],
  college_basketball:['matches','results','groups','bracket','title','edge','advanced','score','community','tree','sandbox','news','insights','status','updates','customize'],
  soccer_league:['matches','results','groups','title','edge','advanced','score','tott','community','tree','sandbox','news','insights','status','updates','customize']
};
const SPORT_KIND={'':'all',wc:'soccer_cup',ucl:'soccer_club',epl:'soccer_league',laliga:'soccer_league',seriea:'soccer_league',bundesliga:'soccer_league',ligue1:'soccer_league',nfl:'us_sport',ncaaf:'college',ncaam:'college_basketball',nba:'us_sport',mlb:'us_sport',nhl:'us_sport'};
function currentSportKey(){const m=(DATA_FILE||'').match(/data_(\w+)\.json/);return m?m[1]:'';}
function navProfile(){return SPORT_KIND[currentSportKey()]||'all';}
const NAV_LABELS={soccer_club:{groups:'League Phase'},us_sport:{groups:'Standings'},college:{groups:'Rankings',bracket:'CFP Bracket'},college_basketball:{groups:'Conferences',bracket:'Bracketology'},soccer_league:{groups:'Table',tott:'Team of the Season'}};
function applySportNav(){
  const prof=navProfile();
  const allowed=NAV_DEF[prof];
  const labels=NAV_LABELS[prof]||{};
  document.querySelectorAll('.navbtn[data-v]').forEach(b=>{
    b.style.display=allowed.includes(b.dataset.v)?'':'none';
    const l=b.querySelector('.lbl');
    if(l){const en=l.getAttribute('data-en')||l.textContent.trim();l.setAttribute('data-en',en);
      l.textContent=labels[b.dataset.v]||t(en);
      // sidebar icons carry no visible label outside the guided tour, so a
      // native tooltip is the only way to tell them apart on hover
      b.title=l.textContent;}});
  document.querySelectorAll('.navGroup').forEach(g=>{
    g.hidden=!g.querySelector('.navbtn[data-v]:not([style*="display: none"]),.navExternal');
  });
  if(!allowed.includes(VIEW))setView('matches');
}
function loadingBoardHTML(){return '<div class="loadingBoard" aria-label="Loading matches"><span></span><span></span><span></span><span></span></div>'}
function showMatchLoading(){const host=$('#view-matches');if(host)host.innerHTML=loadingBoardHTML()}
function changeSport(v){DATA_FILE=v?('data_'+v+'.json'):'';MATCH_VISIBLE=FIXTURE_PAGE_SIZE;RESULT_VISIBLE=FIXTURE_PAGE_SIZE;if(typeof outcomeTreeReset==='function')outcomeTreeReset(false);try{localStorage.setItem('matchday.sport',DATA_FILE)}catch(e){};applySportNav();showMatchLoading();load(true);}

const COLORS={orange:'#ffb02e',blue:'#4cc2ff',green:'#3ad17a',red:'#ff4d5e',purple:'#b16cff'};
function saveSettings(){localStorage.setItem('matchday.settings',JSON.stringify(SETTINGS))}
function applySettings(){document.documentElement.style.setProperty('--signal',COLORS[SETTINGS.accent]||COLORS.orange);document.body.classList.toggle('compact',SETTINGS.density==='compact');document.body.classList.toggle('spacious',SETTINGS.density==='spacious');$('#app').classList.toggle('flat',SETTINGS.panel==='flat');$('#app').classList.toggle('noinsight',!SETTINGS.showInsight);document.body.classList.toggle('hideStats',!SETTINGS.showDetails)}
function updateSetting(k,v){if(k==='refresh')return;if(k==='showInsight'||k==='showDetails'||k==='showFinished'||k.startsWith('alerts'))v=!!v;SETTINGS[k]=v;saveSettings();applySettings();renderCurrent();if(k==='favoriteTeam'&&typeof renderInsight==='function')renderInsight();if(k.startsWith('alerts'))renderAlerts();scheduleNextLoad()}
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
function teamInitials(team){
  const code=String(team?.code||'').replace(/[^A-Za-z0-9]/g,'').slice(0,3).toUpperCase();
  if(code)return code;
  const words=String(team?.name||'Team').replace(/\b(fc|cf|afc|sc|club|united)\b/ig,' ').trim().split(/\s+/).filter(Boolean);
  return (words.length>1?words.slice(0,3).map(w=>w[0]).join(''):words[0]?.slice(0,3)||'TM').toUpperCase();
}
function teamHue(team){let h=0;for(const ch of String(team?.name||team?.code||'team'))h=(h*31+ch.charCodeAt(0))%360;return h}
function teamMarkHTML(team,extra=''){return `<span class="teamMark ${esc(extra)}" style="--team-hue:${teamHue(team)}" aria-hidden="true">${esc(teamInitials(team))}</span>`}
function metricHelp(label,copy){return `<span class="metricHelp" tabindex="0" role="note" aria-label="${esc(label)}: ${esc(copy)}" data-tip="${esc(copy)}">?</span>`}
function favoriteTeam(){return String(SETTINGS.favoriteTeam||'').trim()}
function favoriteNewsTerm(){return teamKey(favoriteTeam()).replace(/\b(fc|afc|cf|sc|football club)\b/g,'').replace(/\s+/g,' ').trim()}
function isFavoriteTeam(name){const fav=teamKey(favoriteTeam());return !!fav&&teamKey(name)===fav}
function isFavoriteMatch(m){return !!m&&(isFavoriteTeam(m.home?.name)||isFavoriteTeam(m.away?.name))}
function favoriteFixtureSort(a,b){return Number(isFavoriteMatch(b))-Number(isFavoriteMatch(a))||fixtureSort(a,b)}
function favoriteTeamOptions(){const names=new Set();(DATA.matches||[]).forEach(m=>{if(m.home?.name)names.add(m.home.name);if(m.away?.name)names.add(m.away.name)});(DATA.standings||[]).forEach(g=>(g.teams||[]).forEach(team=>{if(team.name)names.add(team.name)}));if(favoriteTeam())names.add(favoriteTeam());return [...names].sort((a,b)=>a.localeCompare(b)).map(name=>`<option value="${esc(name)}" ${name===favoriteTeam()?'selected':''}>${esc(name)}</option>`).join('')}
function liveClock(m){const v=m?.minute;if(v==null||v==='')return'';return typeof v==='number'||/^\d+$/.test(v)?`${v}'`:String(v)}
const SCORE_DIFF_TERM={mlb:'run diff',nfl:'point diff',nba:'point diff',ncaaf:'point diff',ncaam:'point diff',nhl:'goal diff'};
function scoreDiffLabel(m){return SCORE_DIFF_TERM[String(m?._comp||DATA.comp_key||'').toLowerCase()]||'goal diff';}
function scoreText(m){if(m.status==='LIVE')return'<span class="pendingScore" aria-label="Score shown after final">—</span>';const done=m.status==='FINISHED';if(isStaleUpcoming(m))return'<span class="kick">Past kickoff</span>';return done?`${m.score?.home??'-'}<span class="sep">–</span>${m.score?.away??'-'}${m.score?.pens?`<span class="pensTag">(${m.score.pens.home}-${m.score.pens.away} pens)</span>`:''}`:`<span class="kick">${dt(m.kickoff).split(', ').pop()||'TBD'}</span>`}
function statNum(v){const m=String(v??'').match(/-?\d+(\.\d+)?/);return m?Number(m[0]):0}
function pressure(stats,side){if(!stats)return 0;const s=stats[side]||{};return statNum(s.shots_on_target)*4+statNum(s.shots)*1.2+statNum(s.corners)*1.4+statNum(String(s.possession).replace('%',''))*.08-statNum(s.red_cards)*4}
function statRow(label,h,a){const hn=statNum(h),an=statNum(a),tot=Math.max(1,hn+an);return `<div class="home">${esc(h||'-')}</div><div class="lab">${label}</div><div class="away">${esc(a||'-')}</div><div class="statbar"><i style="width:${hn/tot*100}%"></i><i style="width:${an/tot*100}%"></i></div>`}
function pct(v){v=Number(v);return Number.isFinite(v)?Math.max(0,Math.min(100,Math.round(v))):0}
function bar1x2(h,d,a){h=pct(h);d=pct(d);a=pct(a);return `<div class="bar"><div class="seg h" style="flex-basis:${h}%"><span>${h}%</span></div><div class="seg d" style="flex-basis:${d}%"><span>${d}%</span></div><div class="seg a" style="flex-basis:${a}%"><span>${a}%</span></div></div>`}
// The backend owns the published pick. UI components may explain that pick,
// but must never promote a live model or market inference over a locked record.
function lockedPredictionSnapshot(m){
  const pr=m?.prediction||{};
  const candidates=[m?.locked_prediction,m?.prediction_snapshot,pr.locked_snapshot,pr.snapshot,pr.locked];
  const found=candidates.find(x=>x&&typeof x==='object'&&!Array.isArray(x));
  return found?.prediction&&typeof found.prediction==='object'?found.prediction:(found||{});
}
function officialPrediction(m){
  const pr=m?.prediction||{},locked=lockedPredictionSnapshot(m);
  const side=locked.pick??pr.pick??'';
  const name=locked.pick_name??pr.pick_name??(side==='h'?m?.home?.name:side==='a'?m?.away?.name:side==='d'?'Draw':'');
  return {side,name,confidence:locked.confidence??pr.confidence??null,locked};
}
function officialPredictionProbabilities(m){
  const pr=m?.prediction||{},locked=lockedPredictionSnapshot(m);
  return locked.adjusted||locked.blend||locked.probs||pr.adjusted||pr.blend||pr.model||{};
}
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
  const gate=$('#welcomeGate'),app=$('#app');
  const finish=()=>{
    if(gate){gate.hidden=true;gate.classList.remove('welcomeLeaving')}
    document.body.classList.remove('welcomeOpen','welcomeExiting');
    if(app)app.classList.remove('appRevealing');
    renderCurrent();const main=document.querySelector('.content');if(main)main.focus?.();
    if(!tourSeen())setTimeout(startTour,500);
  };
  if(!gate||prefersReducedMotion()){finish();return}
  gate.classList.add('welcomeLeaving');
  document.body.classList.remove('welcomeOpen');document.body.classList.add('welcomeExiting');
  if(app)app.classList.add('appRevealing');
  setTimeout(finish,260);
}

// ---- guided tour (first-visit walkthrough) --------------------------------
const TOUR_STEPS=[
  {target:'#sportSel',title:'Start here',body:'Pick a competition to unlock pregame predictions, model accuracy tracking, brackets and more. "All sports" shows a combined analysis feed.'},
  {target:'.navbtn[data-v="matches"]',title:'Matches',body:'Every upcoming fixture with the model’s locked pregame pick shown next to the market’s.'},
  {target:'.navbtn[data-v="edge"]',title:'Model',body:'See exactly why the model favors a side — points, form, ratings, injuries and more, broken down factor by factor.'},
  {target:'.navbtn[data-v="score"]',title:'Scorecard',body:'Every locked pick, tracked in public. Nothing gets rewritten after the fact — good calls or bad ones.'},
  {target:'.navbtn[data-v="tree"]',title:'Outcome Tree',body:'Combine exact outcomes from different games and see the model probability of the whole scenario, branch by branch.'},
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
function _welcomeCardHTML(m){
  const pr=m.prediction||{},op=(typeof _v10OfficialPick==='function'&&m.prediction)?_v10OfficialPick(m):null;
  const pick=op?.name||pr.pick_name||'',model=op?.confidence??pr.confidence,market=op?.marketPct;
  const edge=model!=null&&market!=null?Math.round(Number(model)-Number(market)):null;
  const meter=model!=null?`<div class="welcomeMeter" aria-hidden="true"><i style="--welcome-p:${pct(model)}%"></i></div>`:'';
  return `<div class="welcomeMatchMeta"><span>${esc(m._comp||DATA.comp_key||m.stage||'NEXT')}</span><span>${kickIn(m.kickoff)}</span></div><div class="welcomeTeams"><div><small>${esc(m.home?.code||'HOME')}</small><b>${esc(m.home?.name||'Home')}</b></div><em>v</em><div class="away"><small>${esc(m.away?.code||'AWAY')}</small><b>${esc(m.away?.name||'Away')}</b></div></div>${pick?`<div class="welcomeSignal"><span>MODEL</span><b>${esc(pick)} ${model!=null?esc(model)+'%':''}</b>${market!=null?`<i>market ${esc(market)}%${edge!=null?` · ${edge>0?'+':''}${edge} pt`:''}</i>`:''}</div>${meter}`:''}`;
}
function renderWelcome(){
  const gate=$('#welcomeGate');if(!gate)return;
  const dismissed=welcomeDismissed();gate.hidden=dismissed;document.body.classList.toggle('welcomeOpen',!dismissed);if(dismissed){runCarousel('welcome',null);return}
  const upcoming=(DATA.matches||[]).filter(isVisibleUpcoming);
  const soonest=[...upcoming].sort(fixtureSort)[0],host=$('#welcomeNext');
  if(!host||!soonest)return;
  // most urgent kickoff shown first, then rotates through a small pool of
  // the other featured games (by watchability, narrowed to a near-term
  // window so a months-away fixture can't outrank this week's games)
  const featured=nearTermPool(upcoming.filter(m=>m.id!==soonest.id),4)
    .sort((a,b)=>(b.watchability||0)-(a.watchability||0)).slice(0,4);
  const pool=[soonest,...featured];
  host.innerHTML=_welcomeCardHTML(soonest);
  runCarousel('welcome',pool,host,_welcomeCardHTML,4500);
  const state=$('#welcomeFeedState');if(state)state.textContent='PREGAME';
}
function heroMarquee(){
  const up=(DATA.matches||[]).filter(m=>m.status==='UPCOMING'&&m.prediction&&m.markets);
  if(!up.length)return '';
  const pick=up.sort((a,b)=>(a.kickoff||'').localeCompare(b.kickoff||''))[0];
  const pr=pick.prediction||{};
  return `<div class="heroMatch" onclick="openMatchModal('${esc(String(pick.id))}')">
    <div class="heroMatchTeams">${esc(pick.home.name)} <span class="mvvs">v</span> ${esc(pick.away.name)}
      ${pick._comp?`<span class="compTag">${esc(pick._comp)}</span>`:''}
      <span class="heroLive">PREGAME</span></div>
    ${pr.pick_name?`<div class="heroMatchPick">model: <b>${esc(pr.pick_name)}</b>${pr.confidence?` ${pr.confidence}%`:''}</div>`:''}
  </div>`;
}
function landingHero(){
  const sc=DATA.scorecard;
  const slim=heroSeen();
  const rec=sc&&sc.graded?`<span class="heroRec"><b>${sc.model_hits}-${sc.graded-sc.model_hits}</b> record</span>${sc.brier!=null?`<span class="heroRec">Probability accuracy ${metricHelp('Brier score','Measures probability accuracy. Lower is better.')} <b>${sc.brier}</b></span>`:''}${sc.clv_avg!=null?`<span class="heroRec">Market movement ${metricHelp('Closing line value','How the recorded probability compares with the final market snapshot.')} <b>${sc.clv_avg>0?'+':''}${sc.clv_avg}</b></span>`:''}`:`<span class="heroRec faintline">Model record begins as completed picks are graded</span>`;
  if(slim)return `<div class="heroSlim">${rec}<button class="heroSlimLink" type="button" onclick="setView('score')">Open scorecard <span aria-hidden="true">→</span></button></div>`;
  return `<div class="heroBand">
    <img src="logo.png?v=4" class="heroLogo" alt="Matchday">
    <div class="heroTitle">A transparent sports model.</div>
    <div class="heroSub">Every pick locked before kickoff, graded in public — across football, and more sports as their seasons start. No tips, no ads, just an accountable model.</div>
    <div class="heroRow">${rec}</div>
    ${heroMarquee()}
    <div class="heroActions">
      <button class="btmbtn heroBtn" onclick="heroDismiss()">Open the analysis</button>
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
const MARQUEE_COUNT=16;
const MARQUEE_PER_COMP=3;
// Watchability alone doesn't know or care how far away a game is -- an
// off-season fixture months out can outscore something happening this week.
// Narrow to the soonest reasonable window before ranking by watchability,
// widening only if that window doesn't have enough candidates (e.g. every
// active sport is between seasons at once).
const NEAR_TERM_WINDOWS_DAYS=[14,30,60,120];
function nearTermPool(matches,minCount){
  const now=Date.now();
  for(const days of NEAR_TERM_WINDOWS_DAYS){
    const cutoff=now+days*86400000;
    const within=matches.filter(m=>m.status==='LIVE'||(kickMs(m)&&kickMs(m)<=cutoff));
    if(within.length>=minCount)return within;
  }
  return matches;
}
function watchabilityFixtureSort(a,b){return Number(isFavoriteMatch(b))-Number(isFavoriteMatch(a))||(Number(b.watchability)||0)-(Number(a.watchability)||0)||fixtureSort(a,b)}
// Marquee selection for the merged "All sports" board. A pure global
// watchability ranking buries whole sports: soccer's team ratings sit on a
// higher numeric scale than the US sports', so its ~5 leagues at 90+ fill
// every slot before NFL (tops ~82) or college football (~62) get a look.
// Instead, round-robin by competition -- take each active competition's
// TOP game first, then everyone's 2nd, then 3rd -- so every sport with
// games showing gets its marquee matchup surfaced, capped at
// MARQUEE_PER_COMP each. Within each round, higher watchability goes first
// so the very biggest games still lead. Favorite-team matches are pinned
// to the very front regardless.
function marqueeSelect(active){
  const favs=active.filter(isFavoriteMatch);
  // favorites stay eligible regardless of how far out they are; the
  // watchability-ranked rest gets narrowed to a near-term window first, so a
  // months-away fixture can't outrank something happening this week
  const rest=active.filter(m=>!isFavoriteMatch(m));
  const byComp={};
  rest.forEach(m=>{const c=m._comp||m.competition||'OTHER';(byComp[c]||=[]).push(m);});
  // Widen each competition's window independently rather than pooling every
  // sport together first: a high-volume in-season sport (e.g. MLB in July)
  // satisfies a combined count threshold at the narrowest window on its own,
  // which permanently starved every other sport of ever widening far enough
  // to reach its own next fixture and let one sport fill every marquee slot.
  Object.keys(byComp).forEach(c=>{byComp[c]=nearTermPool(byComp[c],MARQUEE_PER_COMP)});
  Object.values(byComp).forEach(list=>list.sort((a,b)=>(Number(b.watchability)||0)-(Number(a.watchability)||0)));
  const picked=[...favs];const seen=new Set(favs);
  for(let round=0;round<MARQUEE_PER_COMP&&picked.length<MARQUEE_COUNT;round++){
    // order this round's competitions by their round-th game's watchability,
    // so the strongest leagues still appear earlier within each pass
    const contenders=Object.values(byComp).filter(list=>list[round])
      .sort((a,b)=>(Number(b[round].watchability)||0)-(Number(a[round].watchability)||0));
    for(const list of contenders){
      if(picked.length>=MARQUEE_COUNT)break;
      const m=list[round];if(seen.has(m))continue;picked.push(m);seen.add(m);
    }
  }
  return picked;
}
function renderMatches(){const M=DATA.matches||[];
  // "All sports" merges every competition's fixtures into one list (often
  // 1000+ matches) -- instead of dumping everything, rank by a
  // watchability score (team class rating, how close the model's own
  // probabilities are, upset potential, knockout stakes) and show the
  // biggest games, capped per competition so no one sport dominates.
  // Picking a specific sport still shows its full schedule.
  const isAll=String(DATA.comp_key||'ALL').toUpperCase()==='ALL';
  const active=M.filter(m=>!isCompleteOrPast(m)).sort(isAll?watchabilityFixtureSort:favoriteFixtureSort);
  const capped=isAll?marqueeSelect(active):active;
  const shown=capped.slice(0,MATCH_VISIBLE),remaining=Math.max(0,capped.length-shown.length);
  const missing=DATA._missing?`<div class="banner" style="grid-column:1/-1"><b>No ${esc(DATA.competition||'this sport')} data yet.</b> Fetch it once its season is available — run the matching start file (e.g. start_ucl.bat) or keep an eye out when the season begins.</div>`:'';
  const intro=isAll
    ?`<div class="viewIntro"><div><div class="vhead">Top matchups</div><p>The strongest and closest games across every sport. Choose a sport above to see its complete schedule.</p></div><span>${shown.length} featured</span></div>`
    :`<div class="viewIntro"><div><div class="vhead">${t('Fixtures')}</div><p>Pregame model reads now; final scores and grading after the game.</p></div><span>${capped.length} games</span></div>`;
  const html=missing+landingHero()+intro+
    (shown.length?shown.map(cardHTML).join(''):`<div class="empty" style="grid-column:1/-1">No upcoming matches to analyze.</div>`)+
    (remaining?`<div class="fixturePager"><span>Showing ${shown.length} of ${capped.length} fixtures</span><button class="actionbtn" onclick="MATCH_VISIBLE+=FIXTURE_PAGE_SIZE;renderMatches()">Load ${Math.min(FIXTURE_PAGE_SIZE,remaining)} more</button></div>`:'');
  $('#view-matches').innerHTML=html;enhanceMatchCards($('#view-matches'));}
function renderResults(){const M=DATA.matches||[];
  const past=M.filter(isCompleteOrPast).sort((a,b)=>Number(isFavoriteMatch(b))-Number(isFavoriteMatch(a))||(b.kickoff||'').localeCompare(a.kickoff||''));
  const shown=past.slice(0,RESULT_VISIBLE),remaining=Math.max(0,past.length-shown.length);
  $('#view-results').innerHTML=`<div class="vhead">${t('Results')}</div>`+
    (shown.length?shown.map(m=>cardHTML(m,{hidePick:true})).join(''):`<div class="empty" style="grid-column:1/-1">No completed matches yet.</div>`)+
    (remaining?`<div class="fixturePager"><span>Showing ${shown.length} of ${past.length} results</span><button class="actionbtn" onclick="RESULT_VISIBLE+=FIXTURE_PAGE_SIZE;renderResults()">Load ${Math.min(FIXTURE_PAGE_SIZE,remaining)} more</button></div>`:'');enhanceMatchCards($('#view-results'));}
function groupLetter(g){return String(g||'').replace(/^Group\s*/i,'').replace(/^GROUP_/i,'').trim()}
function cleanGroup(g){g=String(g||'').trim();if(!g)return'';if(/^GROUP_/i.test(g))return g.replace('GROUP_','Group ').replaceAll('_',' ').replace(/\b\w/g,c=>c.toUpperCase());if(/^Group\s+/i.test(g))return 'Group '+groupLetter(g).toUpperCase();return g}
function rowKey(n){return String(n||'').toLowerCase().replace(/[^a-z0-9]+/g,' ').trim()}
function ensureRow(map,team,group){const key=rowKey(team?.name);if(!key)return null;if(!map[key])map[key]={name:team?.name||'',code:team?.code||'',group:cleanGroup(group||team?.group),pld:0,w:0,d:0,l:0,gf:0,ga:0,gd:0,pts:0,form:'',live:false,results:[]};else{map[key].code=map[key].code||team?.code||'';map[key].group=map[key].group||cleanGroup(group||team?.group)}return map[key]}
function addResult(row,gf,ga,live,kick){row.pld++;row.gf+=gf;row.ga+=ga;row.gd=row.gf-row.ga;if(gf>ga){row.w++;row.pts+=3;row.results.push([kick,'W'+(live?'*':'')])}else if(gf<ga){row.l++;row.results.push([kick,'L'+(live?'*':'')])}else{row.d++;row.pts+=1;row.results.push([kick,'D'+(live?'*':'')])}row.live=row.live||live}
function deriveStandings(){if(Array.isArray(DATA.standings)&&DATA.standings.length)return DATA.standings;const rows={},M=DATA.matches||[];M.forEach(m=>{const g=cleanGroup(m.home?.group||m.away?.group||(/^Group/i.test(m.stage||'')?m.stage:''));if(!g)return;const h=ensureRow(rows,m.home,g),a=ensureRow(rows,m.away,g);const sh=m.score?.home,sa=m.score?.away;if(h&&a&&m.status==='FINISHED'&&Number.isFinite(Number(sh))&&Number.isFinite(Number(sa))){addResult(h,Number(sh),Number(sa),false,m.kickoff||'');addResult(a,Number(sa),Number(sh),false,m.kickoff||'')}});Object.values(rows).forEach(r=>{r.results.sort((a,b)=>String(a[0]).localeCompare(String(b[0])));r.form=r.results.slice(-5).map(x=>x[1]).join(' ')});const by={};Object.values(rows).forEach(r=>{if(!r.group)return;(by[r.group] ||= []).push(r)});return Object.keys(by).sort((a,b)=>groupLetter(a).localeCompare(groupLetter(b))).map(g=>{by[g].sort((x,y)=>(y.pts-x.pts)||(y.gd-x.gd)||(y.gf-x.gf)||String(x.name).localeCompare(y.name));by[g].forEach((r,i)=>r.pos=i+1);return {group:g,teams:by[g]}})}
function getThirdRace(){let third=Array.isArray(DATA.third_race)&&DATA.third_race.length?DATA.third_race.map(x=>({...x})):deriveStandings().flatMap(g=>(g.teams||[]).filter(t=>t.pos===3).map(t=>({team:t.name,name:t.name,code:t.code,group:g.group,pts:t.pts,gd:t.gd,gf:t.gf,live:t.live})));third.sort((a,b)=>(b.pts-a.pts)||(b.gd-a.gd)||(b.gf-a.gf)||String(a.team||a.name).localeCompare(String(b.team||b.name)));third.forEach((t,i)=>{t.in=i<8;t.team=t.team||t.name});return third}
function getProjectedSlots(){const existing=DATA.projected_bracket?.slots||[];if(existing.length)return existing;const slots=[];deriveStandings().forEach(g=>{const gl=groupLetter(g.group);(g.teams||[]).forEach(t=>{if(t.pos===1||t.pos===2)slots.push({slot:`${gl}${t.pos}`,team:t.name,code:t.code,pts:t.pts,gd:t.gd,live:t.live})})});getThirdRace().slice(0,8).forEach((t,i)=>slots.push({slot:`3rd #${i+1}`,team:t.team,code:t.code,pts:t.pts,gd:t.gd,live:t.live}));return slots}
/* removed duplicate (sourceName) */
/* removed duplicate (renderGroups) */
/* removed duplicate (bracketTeam) */
function bracketMatch(km,ri,mi,last=false){const pending=km.status==='LIVE',done=km.status==='FINISHED';const hs=km.score?.home,as=km.score?.away;const hw=done&&Number(hs)>Number(as),aw=done&&Number(as)>Number(hs);return `<div class="bracketMatch ${last?'':'hasNext'}"><div class="bmMeta"><span>${esc(km.stage||km.round||`Match ${mi+1}`)}</span><span>${pending?'AWAITING FINAL':done?'FT':km.kickoff?dt(km.kickoff):'TBD'}</span></div>${bracketTeam(km.home,km.home_code,'',done?hs:null,hw,false)}${bracketTeam(km.away,km.away_code,'',done?as:null,aw,false)}</div>`}
/* removed duplicate (projectedRounds) */
function projectedMatch(km,ri,mi,last=false){return `<div class="bracketMatch ${last?'':'hasNext'}"><div class="bmMeta"><span>${esc(km.stage||'Projected')}</span><span>${ri===0?'field':'path'}</span></div>${bracketTeam(km.home,km.home_code,km.home_slot,null,false,false)}${bracketTeam(km.away,km.away_code,km.away_slot,null,false,false)}</div>`}
/* removed duplicate (renderBracket) */
function renderThird(){const host=$('#view-third'),third=getThirdRace();if(!third.length){host.innerHTML=`<div class="vhead">Third-place tracker</div><div class="empty">Third-place race not available yet.</div>`;return}const cut=third[7];host.innerHTML=`<div class="vhead">Third-place tracker</div><div class="thirdList"><div class="thirdHead"><span>Rank</span><span>Team</span><span>Group</span><span>Pts</span><span>GD</span><span>Status</span></div>${third.map((t,i)=>`<div class="thirdRow ${t.in?'in':'out'}"><div class="thirdRank">#${i+1}</div><div class="thirdTeam"><div class="name">${esc(t.code||'')} ${esc(t.team||'')} ${t.live?'<span class="liveMark">*</span>':''}</div><div class="group">${esc(t.group||'')} · GF ${t.gf??0}</div></div><div class="thirdNum">${esc(t.group||'')}</div><div class="thirdNum pts">${t.pts}</div><div class="thirdNum gd">${t.gd>0?'+':''}${t.gd}</div><div class="thirdBadge ${t.in?'in':''}">${t.in?'IN':'CHASE'}</div></div>`).join('')}<div class="thirdCut">Cut line: ${cut?`${esc(cut.team||cut.name)} at ${cut.pts} pts, GD ${cut.gd>0?'+':''}${cut.gd}`:'waiting for enough teams'}.</div></div>`}
/* removed duplicate (renderTitle) */
/* removed duplicate (renderEdge) */
/* removed duplicate (newsSources) */
/* removed duplicate (renderNews) */

const SYSTEM_UPDATES=[
  {date:'Build 0730A',tag:'Fix',title:'Watch-only underdogs read differently from official upset picks again',items:[
    'A scorecard tag that should say "underdog risk" had drifted to "upset risk", leaving the watch-only line one mid-string word away from the "upset pick" line it exists to contrast with. Both now read distinctly at a glance, matching how the match view already separates watch only from an active pick.'
  ]},
  {date:'Build 0728G',tag:'Fix',title:'Verified roster talent is restored during the current provider outage',items:[
    'Seeded the derived model fields for 15 teams from the project\'s already live-verified 2025 CollegeFootballData spot checks, including Michigan State and Toledo. This is an immediate bridge while the account remains rate-limited; it does not copy or publish the provider\'s raw payload.',
    'Michigan State-Toledo now has complete roster-talent coverage: MSU receives the positive talent edge and becomes the narrow model favorite despite Toledo\'s stronger prior-season record. The automatic full-field refresh will replace and expand this bridge when quota is available.'
  ]},
  {date:'Build 0728F',tag:'Fix',title:'Roster talent can no longer disappear when the provider rate-limits a refresh',items:[
    'The live Michigan State-Toledo audit showed both roster inputs marked unavailable after CollegeFootballData returned HTTP 429, which zeroed the talent edge and left the dampened prior-season record to decide the game. The displayed 51% Toledo pick was therefore missing its most important preseason input.',
    'Talent enrichment now runs in one quota-light request before the broader data build and persists atomically to the tracked ratings file after every successful refresh. Later provider or cache failures therefore keep the last licensed snapshot instead of silently publishing zero roster talent.'
  ]},
  {date:'Build 0728E',tag:'Fix',title:'Outcome Tree is now a compact five-event builder',items:[
    'Replaced the endlessly scrolling fixture list with a two-step selection menu: choose a game, choose its exact outcome, then add it to the scenario. A scenario is capped at five events so it stays readable on desktop and mobile.',
    'The visualization now uses neutral branches: X is the selected exact outcome and Y is any other result. Real team names remain in the selection list where they are needed, but no longer clutter the outcome tree itself.'
  ]},
  {date:'Build 0728D',tag:'Model',title:'“Class” now means a real sport-specific talent signal',items:[
    'College football now labels its 247 Team Talent Composite input as Roster talent edge; college basketball labels its narrower input as Recruiting edge; soccer uses Squad edge.',
    'Championship futures no longer overwrite or masquerade as college talent. They remain a separate Championship market power factor, with reduced college weight because the signals overlap.',
    'MLB, NFL, NBA and NHL now say when a real personnel or roster edge is unavailable instead of showing a generic class number sourced from market opinion. The model still uses result history, Elo, opponent-adjusted performance and real markets where available.',
    'College talent and recruiting snapshots now keep a last-good cache, so a temporary provider or quota failure cannot erase the entire signal from a published build.'
  ]},
  {date:'Build 0728C',tag:'Fix',title:'Outcome Tree no longer prevents the whole site from loading',items:[
    'The page referenced the new Outcome Tree script, but the deployment artifact forgot to include the file. That missing script stopped the dashboard at Loading. The artifact now packages it and a regression test protects the deploy list.'
  ]},
  {date:'Build 0728B',tag:'Fix',title:'Team of the Tournament is finally a real eleven-player team',items:[
    'The completed Champions League page was calling six scorer-feed players a "Model-built XI" while leaving the entire defence and goalkeeper empty. It now shows UEFA\'s complete, attributed 2025/26 Team of the Season: one goalkeeper, four defenders, four midfielders and two forwards, with a direct link to the organizer\'s published selection.',
    'Official organizer selections are explicitly labeled as official-source editorial content, never as Matchday model output. Scoring figures appear only for players covered by Matchday\'s licensed scorer feed; the remaining cards say "Official XI" instead of inventing statistics.',
    'For competitions without a complete official selection or enough lineup coverage, a partial scorer list is now honestly labeled "Model attacking leaders" and empty position bands are hidden instead of presenting an unfinished team as an XI.',
    'Fixed a separate formation bug in the model-generated version: its position caps added up to 12 players. A complete model XI now uses a real 4-3-3.'
  ]},
  {date:'Build 0728A',tag:'New',title:'Outcome Tree combines exact model scenarios without pretending to be a sportsbook',items:[
    'Added an Outcome Tree for combining up to five published game outcomes into one transparent scenario probability.',
    'The result shows each selected branch, its individual official probability, the cumulative path probability, and model-implied fair decimal and American odds. Locked prediction snapshots take priority, so a public pick is never silently replaced by a later calculation.',
    'Only one exact outcome can be selected from the same game. The tree clearly discloses that multiplication assumes different games are independent, warns when selected games share a team, and does not present the result as a sportsbook price or betting recommendation.',
    'The tree cannot improve its source predictions: missing talent, pitcher, injury, lineup, or market inputs carry directly into the combined estimate.'
  ]},
  {date:'Build 0727A',tag:'Fix',title:'The pick ledger could silently erase itself, and a "one-time" step was quietly duplicating it',items:[
    'Root-caused why the scorecard kept reading as an almost-empty record: the file holding every locked pick was never actually stored anywhere permanent. It lived only in the build system\'s temporary cache, which is designed to be disposable -- so a single cache miss silently reset the entire pick history to nothing, with no error, no warning, and nothing in the logs to show it had happened. Confirmed this is exactly what occurred. The ledger is now committed to the project\'s real version history after every refresh, the same way team ratings already were, so it can no longer vanish and every change to it is permanently traceable.',
    'Found a second, opposite problem in the same area: a setup step labelled "one-time" had in fact been re-running on every single refresh for days, re-adding the same 19 World Cup picks over and over under slightly different internal names. The ledger had quietly grown to 38 records for 19 real matches, and every duplicate was being counted again in the all-time tally. Worse, the re-added copies carried old penalty-shootout scorelines the app had already corrected (showing a shootout as if it were the actual score), so each refresh reintroduced data that had been deliberately fixed. Removed the step, cleaned the duplicates out, and added a guard so a repeated pick can never be double-counted again.',
    'Games that get postponed or cancelled no longer sit forever labelled "upcoming" long after their scheduled start. They now resolve properly and are never graded as though they finished 0-0.',
    'Live game status for baseball, basketball and football now reads "3rd inning" or "3rd quarter" instead of a raw, unreliable clock like "3 0:00" -- the current data plan doesn\'t expose a trustworthy minute-by-minute clock for those sports, so it shows what it can actually stand behind. Soccer\'s real match minute is unchanged.',
    'Baseball, football and basketball no longer borrow soccer\'s vocabulary: the expanded match breakdown, match story and matchup sandbox now say "run diff"/"runs" and "point diff"/"points" where they used to say "goal diff"/"goals" for every sport regardless. This was also leaking on the default All-sports screen specifically, where the labels ignored which sport each match actually belonged to.',
    'The all-time pick tally (verified picks plus older ones that can\'t prove when they were locked, clearly labelled) now appears on the All-sports screen too, not just inside a single sport -- it was missing from the exact screen most people land on first.',
    'The "Top matchups" board was showing only three games, all from one sport, because a single sport in a busy stretch of its season could satisfy the selection rule on its own and lock every other sport out. Now shows the biggest games across every sport in season -- currently 16 games spanning 8 competitions.',
    'Fixed the transparent scorecard\'s pick log overflowing its own rows on phones, where the match name was being squeezed to zero width and disappearing entirely.',
    'Standings for MLB, NBA and NFL now rank by the model\'s own strength rating rather than raw win rate, and say so. These aren\'t real division tables -- the current data plan doesn\'t provide divisions for them, so everything sits in one flat list, and sorting that by win percentage made it look like an official standings page it isn\'t. College football and basketball, which do come with real conference tables, keep their true win-loss order.',
    'Every sport\'s standings and conference tables now show the model\'s rating next to the record, so a team riding an easy schedule to a strong record is no longer unexplained next to how strong the model actually thinks it is.',
    'Added a plain-language failure report: if a sport\'s data refresh crashes, the reason is now published where it can actually be read, instead of disappearing into build logs that require special access.']},
  {date:'Build 0726B',tag:'Fix',title:'A ratings collision that was quietly wrecking Week 1 college blowouts, a false-alarm upset tag, and a real Top 25',items:[
    'Traced the Alabama-vs-East-Carolina case all the way to the actual number and found something worse than the earlier fixes caught: the internal step that matches a recruiting-talent feed\'s team name back to the schedule\'s own name was, for any school sharing a first word with a real program ("Alabama" vs "Alabama A&M"/"Alabama State", "Ohio" vs "Ohio State", "Texas" vs "Texas A&M"/"Texas Tech", dozens of these pairs nationally), sometimes letting the WEAKER sibling school\'s rating silently overwrite the real program\'s rating in memory -- because the national talent feed covers every team in the country, including ones not playing that particular week, and the matching logic kept trimming the name down until it accidentally matched the wrong school. That\'s exactly why Alabama specifically was still reading as a alarmingly close game after every earlier fix: its real elite recruiting rating was being clobbered by Alabama A&M\'s, a much smaller program, right before the prediction ran. Fixed so a name is only trimmed down that far when what\'s left over is definitely just mascot noise, never a real second campus/program name.',
    'Found and fixed the root cause of the "upset watch" tag showing up on ordinary, clearly-favored picks across NFL, college football and Premier League alike: the badge was being triggered any time a match simply had no fresh betting line to check against yet (the normal state for most of a match\'s life), instead of only when the model\'s own volatility signal actually flagged it as a real upset candidate. A 73%-confidence, nothing-unusual-about-it pick was showing the exact same warning tag as a genuine live long-shot. Now it only shows when the model itself raised a flag.',
    'Replaced a fake "Top 25" for men\'s college basketball that was quietly sorting every Division I team nationwide by plain win/loss record with no adjustment at all for schedule strength -- meaning a small-conference team that ran up a gaudy record against weak competition could rank above blue-blood programs that play a brutal schedule every night (this is exactly why a MAC school was reading as the #1 team in the country). Now pulls the real, live AP Top 25 poll from the same licensed provider, same as college football already did.',
    'Investigated why defenders/goalkeepers still don\'t appear in Champions League Team of the Tournament and built a one-time tool to backfill them from real archived lineups. Live-tested it against the actual data provider and confirmed it\'s a hard wall on our current free data plan, not something we can code around: that provider will only hand over lineup data from within about the last three days, full stop, for any date -- and the Champions League season in question already finished back in the spring. The honest note already shown in that panel (we only show defenders once real data can back them, we never invent a lineup) stays accurate; this becomes fixable automatically once a season currently being played finishes, or if a paid tier of that data plan is ever brought on.']},
  {date:'Build 0726A',tag:'Fix',title:'Chasing down why the biggest programs still didn\'t look like the biggest programs',items:[
    'Kept digging on the same complaint from a user who plays close attention: real sportsbook lines for season-opening "buy games" show some of the biggest college programs favored by 90-99% -- our model was still capping out in the 55-65% range for the exact same matchups even after the previous fix. Root-caused it further: a leftover "fifa_rank" component was being added to every American-sports team\'s class score at an identical, frozen default value forever, diluting the one real signal instead of contributing anything real -- removed it. Re-verified against real, live 2025-26 recruiting-composite data across a real Week 1 2026 schedule (50 real Power-4-vs-Group-of-5 matchups): 30 of 50 now read 80%+ for the power-conference side, using real data, not hand-picked examples.',
    'Found and fixed something worse than the original complaint: the baseline-weight fix from the prior pass had a side effect nobody had caught -- a safety floor meant to stop a team\'s strength score from going negative was getting hit far more often at the new, lower baseline, occasionally producing false near-100%-certainty picks for ordinary bad-but-real teams instead of a believable read. That\'s now fixed with a sport-appropriate floor instead of one value for every sport.',
    'Fixed real cross-sport data bleed: any school fielding both a football and a basketball program (there are dozens) was having its two programs\' historical performance tracked in the exact same bucket, meaning a good basketball season could quietly inflate that same school\'s football rating and vice versa. Every sport now keeps fully separate history per school, and the one-time reset this required is documented below.',
    'Verified the 2026 college football recruiting-class rankings for the upcoming season aren\'t published by the data provider yet at all -- confirmed by checking directly, not assumed -- so the ratings/predictions pipeline now automatically averages the last several years that ARE available instead of only ever trying one single season and coming up empty.',
    'Started a one-time historical backfill covering real past seasons -- multiple decades for NFL/NBA/MLB/college football/college basketball, and as many recent seasons as any current data source actually makes available for soccer competitions including the Champions League and World Cup -- so every team starts with a real trailing track record instead of a blank slate. This is what should meaningfully close the remaining gap for the biggest, most historically dominant programs specifically, since a single recruiting class snapshot can\'t capture "this program has been elite for a decade" the way real results can.',
    'Evaluated five more outside data sources at the user\'s suggestion (a well-known sports-stats database family, a soccer results site, two live-score platforms, and a major commercial sports-data vendor) by reading each one\'s actual current terms of use, not assuming. All five are blocked -- four have explicit bans on exactly this kind of automated use, and the fifth has no way for a project this size to access it at all. None of them were a shortcut we were missing.']},
  {date:'Build 0725H',tag:'New',title:'A visible calibration notice, and one title forecast covering every sport at once',items:[
    'The Forecast board now leads with a plain notice that the model is still being calibrated and these numbers are a testing ground, not a finished read -- shown everywhere the forecast is, not buried in a footnote.',
    'The "All sports" view\'s Forecast board now shows a single list with every sport\'s current title favorite side by side, instead of only ever showing whichever one sport happened to load first. Empty until the market-odds quota resets and championship-odds data starts flowing again for each sport -- this only reads real per-sport data, it never guesses.']},
  {date:'Build 0725G',tag:'Fix',title:'Independent audit of the last calibration pass caught a real regression, plus a coverage-gap investigation',items:[
    'The previous build\'s baseline-weight fix (0725F) had a side effect nobody caught at the time: a safety floor meant to keep a team\'s strength score from going negative was getting hit far more often at the new, smaller baseline, producing false near-100%-certainty picks for ordinary bad-but-real teams instead of a believable read. An independent audit against real cached matchups and cached market odds caught this directly -- 14.7% of NFL games were rounding to a 99/1 split. The floor is now sport-appropriate instead of one-size-fits-all, and the false-certainty cases are gone (0 of 224 re-checked NFL games) without losing 0725F\'s original calibration gains.',
    'Found and fixed a second, unrelated bug while investigating: college programs that field both a football and basketball team (Kansas, Duke, Ohio State, etc.) were sharing one strength-history bucket keyed only by school name -- a basketball season\'s results could silently bleed into that same school\'s football rating and vice versa. Each sport now keeps its own separate history per school.',
    'Traced why several soccer leagues still looked underpowered even after 0725F: six championship-odds market identifiers this app has requested since its very first commit (for the Premier League, La Liga, Serie A, Bundesliga, Ligue 1, and the Champions League) do not exist in the provider\'s real market catalog -- confirmed by calling the provider\'s own listing endpoint directly. Those leagues were never actually receiving the enrichment this mechanism is supposed to provide; removed the dead identifiers so a fetch cycle no longer wastes a request chasing a market that was never real. The underlying gap -- most teams in these leagues still lack any curated strength rating at all -- remains open; there is no automatic per-team data source for it yet among this app\'s current providers, only hand-entered coverage for a portion of each league.',
    'Investigated using a prediction-market platform as an outside check on the model\'s own numbers. Rejected after reading its actual terms directly: it prohibits automated data collection outright, with no carve-out for internal, non-public, non-commercial use. The good news is a second check isn\'t actually needed for this -- the market-odds provider already used elsewhere in this app covers every sport here just fine; its monthly usage allowance is just temporarily used up.',
    'Looked into pulling in past-season results (multiple prior years, not just the current season) as a foundation for the team-strength-history system, the same way a small hand-picked set of historical picks already seeds this app\'s public track record. Early finding: several of the data sources already in use here support this for free with no extra cost, which would let every team start a season with a real trailing history instead of a blank slate -- still under evaluation before anything is built.']},
  {date:'Build 0725F',tag:'Fix',title:'Predictions were too timid across every sport, and NHL is now fully turned off',items:[
    'A user flagged the NFL’s "upset watch" firing constantly and stronger teams reading as barely favored. Measured it directly against real cached matchups: 31% of all NFL games, 54% of NCAAF, 55% of MLB, and roughly half of every domestic soccer league were being flagged, with median favorite confidence often barely above a coin flip -- even for objectively lopsided matchups, and even with a full season of real results behind the numbers.',
    'Root cause #1 (NFL/NCAAF/NCAAM/MLB): predictions start from a flat baseline weight that was too large relative to how much a real season’s worth of record/margin/schedule-adjusted-rating/class differences can move it, capping most favorites in the high-50s/low-60s no matter how one-sided the season actually was. That baseline is now roughly half what it was; verified against real matchups it lifted NFL’s median favorite from 60% to 67% and cut upset-watch flags from 31% to 19%, with similar gains for NCAAF and MLB.',
    'Root cause #2 (every domestic soccer league): three separate places in the model each independently checked whether a match’s stage "starts with the word group" to decide if it was a risky one-off knockout fixture -- correct for the World Cup/Champions League’s group-then-knockout format, but a domestic league match’s stage is "Regular Season", which never starts with "group" either. Every single EPL/LaLiga/SerieA/Bundesliga/Ligue1 match was being silently treated as knockout-risky by all three. All three now check against the real list of knockout-round names instead, and a plain league match no longer gets penalized for something it never was.',
    'Root cause #3 (soccer specifically): the model’s draw probability was a flat 26% for every match regardless of how mismatched the two teams were -- a real blowout draws much less often than an even game in practice, and the flat number was also quietly feeding an elevated, constant floor into the upset-risk formula. It now tapers down as the model’s own pre-draw split gets more lopsided (26% at a dead-even match, down to 12% at a heavy mismatch).',
    'Root cause #4 (soccer specifically): a preseason class-strength gap (e.g. a big club with no games played yet) got no extra weight the way the American-sports side of the model already leaned on preseason priors -- it now gets the same boost, tapering back to no change at all once a real in-season sample exists.',
    'NHL is now fully switched off rather than just hidden from the sport picker: it’s no longer fetched by the automated hourly refresh or published to the live site at all (its data source’s billing/plan status is still unconfirmed -- see ROTATE_KEYS.md). MLB, which was reachable from the sport picker since Build 0725A but was never actually included in that same automated refresh or publish step, now is.']},
  {date:'Build 0725E',tag:'New',title:'Defensive & advanced stat categories, and less timid preseason predictions',items:[
    'Season leaders now covers defense too, not just offense: NFL adds sacks, interceptions, solo tackles, tackles for loss and QB hits (from the same free nflverse feed already powering passing/rushing/receiving); NCAAF adds tackles, sacks, tackles for loss and passes defended (same CFBD call, confirmed live to already include a "defensive" category alongside offense); NCAAM adds steals and turnovers per game (same CBBD call); NHL adds plus/minus, hits, takeaways and shots on goal (same SportsDataIO call). None of this cost an extra request against any provider’s quota — every field already existed on a call this build was already making.',
    'NBA and MLB do not get this treatment yet: BALLDONTLIE’s free-tier key was checked live against its stats endpoints for both and came back unauthorized, matching what the adapter’s own comments already said — a plan upgrade (or a different provider) is needed before either gets a real stats feed.',
    'A user flagged that preseason predictions looked too tame for objectively mismatched teams. Diagnosed: with zero games played, record/margin/form/schedule-adjusted rating are all correctly at zero, leaving the recruiting-talent/market-strength "class" prior, poll rank, and in-house Elo to carry the entire signal alone, at a fixed weight tuned assuming the other signals also contribute — flattening a real on-paper blowout toward a near-coin-flip. Those three now scale up as the average current-season sample shrinks, tapering back to exactly no change once the season is established, so this cannot affect any already-tuned in-season prediction.']},
  {date:'Build 0725D',tag:'New',title:'Real soccer box scores and a first injuries feed, both actually wired in this time',items:[
    'API-FOOTBALL box-score stats and starting lineups (shots, shots on target, possession, corners, fouls, cards) were fully built but never actually called from anywhere -- confirmed dead code since the very first commit. They now run for every soccer competition, and the "box score dominance" override used in upset detection (also dead for the same reason, since it reads this same data) can trigger on real data for the first time.',
    'Soccer also gets a real injuries feed for the first time -- every provider path previously left it empty, so the Model\'s injury-weighting nudge had nothing to work with for any soccer competition. A new API-FOOTBALL call now supplies confirmed-out and doubtful player status pre-kickoff and live, sharing the same free-plan key and daily request budget as box scores/lineups with its own small, separate cap.',
    'Along the way, live testing against the provider caught API-FOOTBALL\'s injuries endpoint silently repeating every player twice in its own response -- that\'s now deduplicated before it reaches the model, so an absence can\'t accidentally count double.']},
  {date:'Build 0725C',tag:'New',title:'College football and basketball now have real season leaders',items:[
    'NCAAF and NCAAM previously had no player-stat leaders at all -- the "Season leaders" panel only ever populated from SportsDataIO, which those two sports never use, so it silently stayed empty. CollegeFootballData and CollegeBasketballData (the same licensed keys already powering schedules, standings, talent and recruiting for these sports) now supply real current-season passing/rushing/receiving leaders for NCAAF and points/rebounds/assists/blocks-per-game leaders for NCAAM, shown in the same Season leaders panel every other sport already uses.',
    'CFBD reports player stats as one row per player per stat type rather than a per-player table; that gets reshaped into a proper per-player object before any leaderboard is built. Both feeds also needed a real Division-I/FBS filter -- neither provider\'s own classification filter actually restricts the player-stats endpoint, so an unfiltered pull would let a small-school stat leader with far weaker competition out-rank the real national leaders.',
    'Each feed pulls the whole league in a single request (team is an optional filter on both endpoints, not required) rather than looping per team, and is cached for 24 hours separately from the schedule data -- CFBD\'s full-league pull alone is tens of megabytes, so it rides its own longer cache instead of refetching on every run. This is a display-only addition: player stats are not read anywhere in the prediction model.']},
  {date:'Build 0725B',tag:'Fix',title:'Class ratings: blue-blood programs were silently landing on the same neutral number as everyone else',items:[
    'A user flagged Alabama looking barely favored over East Carolina. Traced it to two bugs: championship-odds and recruiting-talent data for NCAAF/NCAAM get written under whatever name the provider hands back ("Alabama Crimson Tide" from the odds book) instead of the schedule\'s bare school name ("Alabama"), so it silently landed on a key predict() never reads -- checked every NCAAF team with a live championship-futures price and found zero survived the old exact-name match. Provider names now resolve to the schedule\'s own name before anything gets written, so "Alabama Crimson Tide" and "Texas A&M Aggies" land on the same team the schedule and predict() already agree on. NCAAM\'s curated Top 25 file was a second instance of the identical bug (25 of 25 entries keyed by mascot -- "Blue Devils", "Wolverines" -- never matched a school name either).',
    'Separately, the "Class rating" shown on team profiles/Sandbox/watchability for NCAAF/NCAAM/every US sport with championship odds was computed BEFORE that run\'s recruiting-talent and championship-odds data got folded in, not after -- so the number on screen was always one enrichment step stale relative to what predict() itself used moments later in the same run. Now computed after.',
    'Two specific name-identity mismatches fixed the same way: the NHL\'s Utah franchise renamed from "Utah Hockey Club" to "Utah Mammoth" and stopped matching its own rating; Champions League\'s curated file still said "Inter Milan" while live fixtures use the official "FC Internazionale Milano". Both now resolve correctly.']},
  {date:'Build 0725A',tag:'New',title:'MLB is now selectable — plus a Baseball guide and SEO wiring',items:[
    'MLB has quietly had a full data pipeline since launch (standings, model picks, championship odds) but was never reachable from the sport picker; it was even actively stripped back out of "All sports" and localStorage if selected. It now appears in the sport dropdown, joins the "All sports" merged view, and is no longer forced back to Auto.',
    'NHL stays off the picker for now since its data file has zero current matches (off-season) -- it will get the same treatment once games resume.',
    'The Legal &amp; data sources page now names MLB alongside NBA and NFL in the BALLDONTLIE disclosure, matching what the app actually displays.',
    'A full "Patience, run differential &amp; the long season" baseball tactics guide existed on disk but was never linked from Content, never tagged with a sport in the content hub, and never listed in the sitemap -- it is now wired into all three, plus a new Baseball filter on the Content page.']},
  {date:'Build 0724Z',tag:'Fix',title:'NFL/NBA/MLB/NHL no longer fall back to a fake soccer bracket',items:[
    'The Bracket tab isn\'t currently shown in the sidebar for these four leagues, but the underlying render path was still reachable and, like the CFP bracket before it, would have silently shown the same fake 32-team World Cup group-into-knockout shape — built from standings data that isn\'t even grouped for these sports, since nothing computes real NFL wild-card, NBA/NHL conference-bracket, or MLB Division/Championship Series seeding. It now shows an honest "not built yet" message instead of a wrong bracket.']},
  {date:'Build 0724Y',tag:'Fix',title:'A real CFP bracket instead of a fake World Cup one — and a stray national flag',items:[
    'The CFP Bracket tab was quietly showing a fake 32-team, Round-of-32-through-third-place bracket built from World Cup group-standings logic, because the shared bracket renderer only recognizes soccer round names — it silently discarded the real "CFP First Round" / "CFP Quarter-finals" projection the model already computes correctly and fell back to a generic knockout shape that has nothing to do with a 12-team, bye-seeded college football playoff. NCAAF now gets its own bracket: First Round, Quarterfinals, Semifinals, National Championship, built from the model\'s actual seeding.',
    'That same shared renderer also called the flag-lookup function directly instead of through the check that limits flags to actual soccer competitions — any two-letter college or NFL code that happened to match a real country\'s ISO code rendered that country\'s flag (Ole Miss\'s code matched Montserrat\'s). Flags are now correctly gated for every bracket-style view, not just the ones that already had the check.']},
  {date:'Build 0724X',tag:'New',title:'Real soccer lineups, replacing what ESPN used to supply',items:[
    'Every match\'s lineups came back empty since ESPN was removed: every provider adapter hardcoded lineups to nothing, and the licensed alternative (Sportmonks) needs a subscription that isn\'t set up. Soccer matches now get real starting XIs and formations from API-FOOTBALL\'s free tier — the same key already used for box-score stats — for live matches, finished matches from the last 2 days, and upcoming matches within 2 hours of kickoff. Capped and cached separately from box stats so both stay within the shared free-plan daily limit.',
    'The Team of the Tournament defenders/keepers ranking — dormant since ESPN\'s lineup feed was removed, deliberately showing attackers only rather than fake data — now backfills from these real lineups as they accumulate. Coverage builds up gradually run over run rather than backfilling a full season instantly, so early rankings should be read as still-warming-up.']},
  {date:'Build 0724W',tag:'Fix',title:'A stale ESPN article was still slipping into the News tab',items:[
    'ESPN was already rejected the moment a fresh headline was fetched, but that filter only ran on newly-fetched items. The separate step that keeps News diverse across a temporary feed outage carries forward the previous run\'s cached headlines too, and that carry-forward path never re-checked the source — so an ESPN item that got in before the stricter filter existed (an NCAAM bracketology piece, confirmed live in the current cache) could keep resurfacing indefinitely instead of aging out. ESPN is now excluded at that step as well, closing the gap for good.']},
  {date:'Build 0724V',tag:'New',title:'Real power ratings for teams outside the curated files',items:[
    'Every team\'s "Class rating" (team profiles, standings, Sandbox, the watchability score) came from a hand-curated preseason-strength file. Soccer and NFL/NBA/MLB/NHL have full league coverage, but NCAAF only has 24 of 130+ FBS teams curated and NCAAM only 25 of 360+ — every other team silently fell back to the same flat, neutral number, indistinguishable from every other uncurated team.',
    'Ratings now blend in the app\'s existing self-updating Elo (already computed from real final scores for its own place in the model, previously never surfaced anywhere) — teams in the curated file keep trusting it early and lean on Elo more as real games accumulate, and teams missing from the file entirely now get a real, differentiated rating from Elo alone once they\'ve played a handful of games, instead of the same default as every other unlisted team.',
    'Also fixed: the flat NFL/NBA/MLB/NHL standings table (used when the free-tier provider has no conference/division breakdown) never included a rating field at all — team profiles for those leagues silently lost their Class rating the moment they were looked up via that table instead of a live match.']},
  {date:'Build 0724U',tag:'Fix',title:'American sports were dressed up in soccer terminology',items:[
    'NFL/NBA/NCAAF standings borrowed soccer\'s "Groups" screen wholesale: a blank group header next to a "Top 2 · 3rd" qualification subtitle that means nothing outside a World Cup-style group stage, green "qualified" row highlighting applied to plain win-loss rankings, and columns literally labeled GF/GA (goals) and Pts. These sports now get their own "Standings" heading, real conference names where available (or "Full table" when the source has none), no qualification highlighting, sport-correct column labels (PF/PA for football and basketball, RF/RA for baseball, GF/GA stays for hockey), and Win% instead of a synthetic points figure nobody actually ranks these leagues by.',
    'The same soccer-vs-American mismatch showed up in the team profile card ("Goal/point diff", a flat "Points" tile) and in match-read totals language ("points" for every two-way sport including baseball and hockey). Both now use the sport\'s real term: goals for hockey and soccer, runs for baseball, points for football/basketball.']},
  {date:'Build 0724T',tag:'Fix',title:'CFP poll rankings showed "null" instead of a dash',items:[
    'The Matchday Top 25 rows in the College Football standings table (poll-ranked teams with no games-played record of their own) rendered the literal text "null" in every P/W/L/GF/GA/GD/Pts cell, since those fields are intentionally empty for poll rankings and the table printed them unguarded. They now show a dash like every other "not available" value in the app.']},
  {date:'Build 0724S',tag:'Fix',title:'Draws no longer show up for sports that can\'t have them',items:[
    'College football (and every other two-way sport — NFL, NCAAM, NBA, MLB, NHL) showed a "Draw" tile and draw-pressure language in the match modal\'s probability check, plus a 0% draw bar in the Model dashboard\'s row list, even though those sports can\'t end level. Both are now hidden for two-way sports instead of always rendering a meaningless 0%.',
    'Team records everywhere — the model-read match profile card and the Standings/Conferences table\'s D column — showed a literal 0 draws for these same sports. Records now read as W-L for two-way sports and W-D-L only where a draw is actually possible (soccer).']},
  {date:'Build 0724R',tag:'UI',title:'Color tokens that were quietly working against clarity',items:[
    'A "warn" KPI on the Model dashboard rendered in the exact same green as a "good" one, because both fell back to the same brand-accent variable — there was no dedicated warning color at all. Introduced a real amber warn token and pointed the warn state at it.',
    'The two amber accents already in use (the market-hours banner and the content hub\'s "current data" indicator) were two different hardcoded hex values with no relationship to each other. Both now reference the same token.',
    'The away side of every stat bar, probability split, and score line rendered in a warm red-orange that sat in the same hue family as the loss/live indicators, baking an unintended "danger" read into whichever team happened to be listed second. Moved it to a distinct violet so it no longer competes with result-status colors.',
    'The dimmest text tier (small labels like table headers and timestamps) computed to roughly 2.7:1 contrast against the background, under the WCAG floor even for large text. Lightened it to clear AA contrast for small text on both the app shell and the content hub.']},
  {date:'Build 0724Q',tag:'Fix',title:'The match modal\'s "model read" text could disagree with the locked pick',items:[
    'The pick badge and percentage were pinned to the locked, graded value in the last build, but the "model read" sentence in the match modal (e.g. "model agrees with the market" / upset-watch language) was still being reset to a generic placeholder. It\'s now rebuilt from the same locked edge and upset data the pick itself uses, so the read always matches the pick it\'s describing.']},
  {date:'Build 0724P',tag:'Fix',title:'A finished match\'s pick could quietly change after the fact',items:[
    'Predictions were recomputed for every match on every data refresh, including ones already decided — so a finished game\'s "Model" pick could drift away from the pick that was actually locked in and graded, sometimes even naming the other team. Results cards no longer show a pick at all (just the final score), and once a pick locks it is now pinned everywhere for that match, through kickoff and after full time.',
    'Picks now lock 2 hours before kickoff instead of the moment a fixture first appears (which was often days out, before there was even market data to weigh against) — giving the model more real information to use before its call is final.',
    'Domestic leagues with a scheduled but not-yet-started season (e.g. Bundesliga, Ligue 1) were showing a completely empty table, because standings were only built from teams with at least one finished match — every team now gets a 0-played row from the day the fixture list exists, not just after kickoff.']},
  {date:'Build 0724O',tag:'Fix',title:'A P4 team\'s bad prior season could outweigh its real talent edge',items:[
    'Live example: Michigan State was an underdog to Toledo for a season opener, entirely because CFBD had no 2026 games yet and silently fell back to MSU\'s rough 2025 record (4-8), which the model then trusted at nearly full confidence — swamping MSU\'s much larger recruiting/talent edge.',
    'That stale carryover record is now flagged and heavily discounted instead of trusted like real current-season form, and the match correctly shows as "preseason" data quality instead of "established."',
    'Also widened the recruiting/talent and championship-odds strength scale, which was undershooting its own ceiling and flattening the gap between a solid recruiting class and an elite one.',
    'The Matchup Sandbox had the same stale-record blind spot for every American sport (it never discounted for games played or a stale prior season) — now scaled the same way as real predictions.']},
  {date:'Build 0724N',tag:'Fix',title:'Made a silent model-data gap visible',items:[
    'The NCAAF/NCAAM team-talent fix from earlier tonight tested correctly against a local key but is returning zero teams live in production — found by auditing real deployed data, not by re-testing locally. The code was silently treating "provider returned nothing" the same as "nothing to apply," so there was no trace of the gap anywhere. It now logs a clear diagnostic line instead, so this stops being invisible on future runs while the actual cause (a live-key/plan access question) gets sorted out.']},
  {date:'Build 0724M',tag:'UI',title:'Clearer navigation, calmer spacing, and a real learning hub',items:[
    'Desktop navigation now shows labels, mobile navigation stays in one reachable horizontal row, and Content remains accessible from the bottom navigation instead of disappearing on small screens.',
    'The match board has one compact introduction instead of a repeated banner and heading, technical scorecard terms use plain-language labels first, and the welcome screen now hands off smoothly to the dashboard.',
    'The Content page is now organized around starting points, model recaps, and sport-by-sport learning with direct links and more efficient spacing.']},
  {date:'Build 0724L',tag:'UI',title:'A livelier welcome screen',items:[
    'Two soft, slowly drifting color blobs behind the welcome screen instead of a static gradient, the headline and preview card now reveal in sequence rather than all at once, and the "Enter Matchday" button gets a periodic light sweep to draw the eye.',
    'All of it — the drift, the staggered reveal, the sweep, and the earlier featured-match rotation — turns off automatically for anyone with reduced-motion enabled at the OS level.']},
  {date:'Build 0724K',tag:'UI',title:'A sidebar that\'s easier to scan, and a more visible Content page',items:[
    'The sidebar\'s 16 icons now sit in labeled groups (Games, Competition, Model, Content, Community, More) with dividers between them, and every icon has a hover tooltip — the sidebar has no visible text labels outside the guided tour, so there was previously no way to tell them apart without hovering blind.',
    'The Content link in the top bar is now a filled accent button instead of a small text link, since that\'s a more effective spot for it than adding a 17th unlabeled sidebar icon.']},
  {date:'Build 0724J',tag:'Fix',title:'Team of the Tournament — fixed for good this time',items:[
    'Defenders and keepers were meant to stay hidden until Matchday has a real lineup data source, but stale entries left over from before ESPN lineups were removed kept silently reappearing anyway — a fix from July 20 addressed the symptom, not the cause. Now structurally gated off regardless of what the old data file contains, verified live against the actual stale file.']},
  {date:'Build 0724I',tag:'New',title:'NCAAF/NCAAM class ratings now cover the whole field',items:[
    'Team class was previously only reachable for the handful of teams with championship futures odds, which for college sports is a tiny slice of the field. It now also pulls from CFBD/CBBD\'s own recruiting-talent data — the same licensed account already used for schedules — covering 130-150+ teams instead of a dozen. Live-verified: NCAAF class went from 0 populated matches to 153 of 160; NCAAM from 0 to 39 of 40.',
    'Live market data still refines the number for whichever teams do have real championship odds; recruiting/talent is the broad baseline underneath it.']},
  {date:'Build 0724H',tag:'New',title:'A Content hub, and tactics breakdowns for every sport',items:[
    'New Content page links every recap, the Q&A, and a new "Tactics & decisions" explainer per sport family — soccer, American football, basketball, baseball, and hockey — covering what actually decides these games and how the model reads it.',
    'Added a Content link next to Q&A and Legal in the top bar.']},
  {date:'Build 0724G',tag:'Fix',title:'Team-class ratings were silently zeroed for most club soccer, and dead for NCAAF/NCAAM',items:[
    'Ratings files hand-written with short club names ("Arsenal") never matched official live fixture names ("Arsenal FC"), silently zeroing the class factor for most matches across every club competition — fixed with a suffix-tolerant lookup.',
    'NCAAF and NCAAM class ratings were completely dead — leftover from the deleted ESPN code, keyed by mascot names that never matched real school names. Both sports now build class ratings live from championship odds instead, the same honest mechanism NFL/NBA/NHL already used, and NCAAM gets a live poll-rank factor for the first time.']},
  {date:'Build 0724F',tag:'Fix',title:'Reliability fixes for NFL/NBA/MLB predictions',items:[
    'Fixed a rare case where the season pull could get cut short by a rate limit and quietly cache an incomplete season for hours; it now retries and falls back cleanly instead of caching a lie.',
    'The rest-days factor no longer silently drops across a bye week or break — it now checks the full season, not just the last week.']},
  {date:'Build 0724E',tag:'UI',title:'A little more motion in the welcome screen and insight panel',items:[
    'The welcome screen now rotates through a few of the day\'s most watchable games instead of showing just one static matchup.',
    'The right-side insight panel does the same for its "In focus" match, pausing whenever you hover over it, and skips the animation entirely if your system prefers reduced motion.']},
  {date:'Build 0724D',tag:'New',title:'Matchday now writes its own recaps, plus a Q&A page',items:[
    'A new Insights tab publishes short, auto-generated recap posts per sport — hit rate, calibration, and the week\'s biggest storylines — built entirely from the model\'s own graded picks, not third-party content.',
    'A new Q&A page explains what confidence, edge, Elo and the opponent-adjusted rating actually mean, and how the model is graded.']},
  {date:'Build 0724C',tag:'Fix',title:'NFL/NBA/MLB predictions were only seeing last week\'s games',items:[
    'Standings, the opponent-adjusted rating and Elo training for these sports now pull the full season instead of a rolling 7-day window, so records and model confidence reflect the real season instead of resetting to "early" on every refresh.']},
  {date:'Build 0724B',tag:'Data',title:'Removed ESPN\'s unlicensed site feeds',items:[
    'Deleted the dormant ESPN scoreboard/summary/rankings/standings/leaders code paths and the standalone backfill script that used them — Matchday has no licensed ESPN developer feed. ESPN headline links in News are unaffected.']},
  {date:'Build 0724A',tag:'New',title:'Native prediction model for NFL, NBA, MLB, NHL, and college sports',items:[
    'These sports now use sport-native factors — season record, scoring margin, rest, poll rank — plus a new opponent-adjusted rating, instead of being forced through soccer-shaped inputs.',
    'Match results now carry a winner only once a game is actually final, closing a class of "phantom result" bugs.']},
  {date:'Build 0722G',tag:'Fix',title:'News layout, clickable top bar, and a market-outage notice',items:[
    'The News tab now flows into a multi-column grid on wider screens instead of one full-width column stacked like a phone.',
    'The live score and "Next" fixture in the top bar are now clickable — tap them to jump straight to the expanded match view.',
    'When our monthly betting-market data quota runs out, a clear banner now explains that market comparisons are paused (model predictions keep working) instead of markets silently vanishing.']},
  {date:'Build 0722F',tag:'New',title:'Watchability index picks the marquee matchups',items:[
    'The "All sports" screen no longer dumps every fixture — it ranks games by a watchability score (team strength, how close the model rates it, upset potential, knockout stakes) and shows the biggest ones.',
    'Balanced across sports: it takes the top game from each active competition first, so college football, NFL and others surface alongside soccer instead of being buried.',
    'Some sports (NBA, college basketball) have no games until their seasons start — they\'ll join automatically once schedules publish.']},
  {date:'Build 0722E',tag:'New',title:'Team Stats profiles',items:[
    'Click any team in the Standings/Groups table to open a compiled profile: points, goal/point difference, scoring rates, class rating, home/away form and recent results.']},
  {date:'Build 0722D',tag:'New',title:'Weekly & monthly leaderboards',items:[
    'The community leaderboard now has "This week" and "This month" views alongside all-time, so new players aren\'t permanently buried behind early adopters — each period resets on its own.']},
  {date:'Build 0722C',tag:'New',title:'Pick streak + Weekly awards',items:[
    'A flame streak counter now rides in the top bar once you string together 2+ correct Beat-the-Model picks.',
    'The Community tab shows weekly awards — biggest upset, the model\'s best call and biggest miss, and the closest game — drawn from the last 7 days of real results.']},
  {date:'Build 0722B',tag:'UI',title:'Expanded match view fills its space',items:[
    'The expanded model read now includes a Match profile card (records, scoring rates, form, absences) and lays out as two balanced columns on wide screens instead of leaving empty gaps.']},
  {date:'Build 0722A',tag:'Fix',title:'Sidebar glitch + model-read detail',items:[
    'Fixed a sidebar flicker during normal use (nav labels were flashing in clipped on hover).',
    'The Elo and head-to-head factors added recently now actually appear in the "Main drivers" list, and the market-comparison cells show class/Elo edges instead of blank dashes when no market line exists yet.']},
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
function renderSystemUpdates(){const host=$('#view-updates');const seen=localStorage.getItem('matchday.updates.lastSeen');const latest='build 0730A';host.innerHTML=`<div class="updatesShell"><div class="updatesHero"><section class="updatesIntro"><h2>System updates</h2><span class="safePill">UI</span></section><aside class="buildCard"><div class="tiny">Current build</div><div class="build">${esc(latest)}</div><div class="hint">Last viewed: ${seen?esc(ago(seen)):'not marked yet'}</div><div class="updateActions"><button class="miniBtn" onclick="markUpdatesRead()">Mark as read</button><button class="miniBtn" onclick="setView('status')">Open Status</button></div></aside></div><section class="timeline"><div class="timelineHead"><h3>Release notes</h3><span>${SYSTEM_UPDATES.length} entries</span></div>${SYSTEM_UPDATES.map(u=>`<article class="updateItem"><div class="updateDate">${esc(u.date)}</div><div><div class="updateTitle"><span>${esc(u.title)}</span><span class="updateBadge">${esc(u.tag)}</span></div><ul>${u.items.map(i=>`<li>${esc(i)}</li>`).join('')}</ul></div></article>`).join('')}</section></div>`}

function renderStatus(){const host=$('#view-status'),M=DATA.matches||[],st=deriveStandings(),third=getThirdRace();const up=M.filter(m=>m.status==='UPCOMING').length,fin=M.filter(m=>m.status==='FINISHED').length;const next=M.filter(isVisibleUpcoming).sort((a,b)=>(a.kickoff||'').localeCompare(b.kickoff||''))[0];host.innerHTML=`<div class="vhead">App Status</div><div class="hint" style="margin-bottom:10px">menu profile: <b>${navProfile()}</b> · sport file: <b>${DATA_FILE||'all (merged)'}</b></div><div class="status-grid"><div class="statuscard ${LAST_OK?'ok':'warn'}"><span class="slbl">Data file</span><div class="sval">${LAST_OK?'loaded':'not loaded'}</div><div class="hint">${LAST_ERROR?esc(LAST_ERROR):'Loaded'}</div></div><div class="statuscard info"><span class="slbl">Source</span><div class="sval">${esc(DATA.source_note||'unknown')}</div><div class="hint">${esc(DATA.standings_mode||'')}</div></div><div class="statuscard info"><span class="slbl">Updated</span><div class="sval">${DATA.updated?ago(DATA.updated):'unknown'}</div><div class="hint">${esc(DATA.updated||'—')}</div></div><div class="statuscard info"><span class="slbl">Matches</span><div class="sval">${M.length}</div><div class="hint">${up} upcoming · ${fin} final</div></div><div class="statuscard info"><span class="slbl">Groups</span><div class="sval">${st.length}</div><div class="hint">${third.length} third-place teams tracked</div></div><div class="statuscard info"><span class="slbl">News Items</span><div class="sval">${(DATA.news||[]).length}</div><div class="hint">${newsSources().filter(s=>s!=='all').join(' · ')}</div></div></div><div class="btnline"><button class="actionbtn" onclick="load(true)">Reload Data Now</button><button class="actionbtn" onclick="setView('groups')">Open Groups</button><button class="actionbtn" onclick="setView('third')">Open Thirds</button><button class="actionbtn" onclick="setView('updates')">System Updates</button></div>`}
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
    if(!watched)return;
    if(m.status==='UPCOMING'&&m.kickoff){const mins=Math.round((new Date(m.kickoff)-now)/60000);
      if(mins>0&&mins<=90)out.push({t:'soon',txt:`${esc(m.home.name)} v ${esc(m.away.name)} — kickoff in ${mins}m`,id:m.id});}
  });
  return out.slice(0,6);}
function renderAlerts(){const bar=$('#alertBar');if(!bar)return;const a=computeAlerts();
  if(!a.length){bar.style.display='none';return;}
  bar.style.display='';bar.innerHTML=a.map(x=>`<span class="alertPill ${x.t}" onclick="openMatchModal('${x.id}')">${x.t==='upset'?'&#9889; ':x.t==='live'?'&#128308; ':'&#9203; '}${x.txt}</span>`).join('');}
// Alert center, probability movement, and alert preferences. These override
// the original compact alert renderer above while retaining its watchlist API.
let MATCH_SIGNAL_CHANGES={},SCORE_SIGNAL_CHANGES={},LIVE_ENTRY_CHANGES={},MODEL_HISTORY={},LAST_SIGNAL_CAPTURE='';
function _signalId(m){return `${m?._comp||DATA.comp_key||'sport'}:${m?.id||''}`}
function _alertReadJSON(key,fallback){try{return JSON.parse(localStorage.getItem(key)||JSON.stringify(fallback))}catch(e){return fallback}}
function captureMatchSignals(matches){
  const previous=_alertReadJSON('matchday.signalSnapshot',{}),next={},history=_alertReadJSON('matchday.modelHistory',{}),now=Date.now();
  MATCH_SIGNAL_CHANGES={};SCORE_SIGNAL_CHANGES={};LIVE_ENTRY_CHANGES={};
  (matches||[]).filter(m=>m&&m.status!=='FINISHED').slice(0,220).forEach(m=>{
    const id=_signalId(m),op=typeof _v10OfficialPick==='function'?_v10OfficialPick(m):null;
    const confidence=Number(op?.confidence??m.prediction?.confidence),market=Number(op?.marketPct);
    const score=`${m.score?.home??''}-${m.score?.away??''}`;
    next[id]={confidence:Number.isFinite(confidence)?confidence:null,market:Number.isFinite(market)?market:null,status:m.status,score,at:now};
    const old=previous[id];
    if(old&&m.status==='LIVE'&&old.score!==score)SCORE_SIGNAL_CHANGES[id]={previous:old.score,current:score};
    if(old&&old.status!=='LIVE'&&m.status==='LIVE')LIVE_ENTRY_CHANGES[id]=true;
    if(old&&Number.isFinite(old.confidence)&&Number.isFinite(confidence)){
      const delta=Math.round(confidence-old.confidence);
      if(Math.abs(delta)>=3)MATCH_SIGNAL_CHANGES[id]={delta,previous:old.confidence,current:confidence};
    }
    const points=Array.isArray(history[id])?history[id]:[];
    if(Number.isFinite(confidence)&&(!points.length||points[points.length-1].p!==confidence))points.push({t:now,p:confidence});
    history[id]=points.slice(-8);
  });
  MODEL_HISTORY=history;
  try{localStorage.setItem('matchday.signalSnapshot',JSON.stringify(next));localStorage.setItem('matchday.modelHistory',JSON.stringify(history))}catch(e){}
}
function captureSignalsIfFresh(){const fingerprint=(DATA.matches||[]).slice(0,80).map(m=>`${m.id}:${m.prediction?.confidence??''}:${m.status}:${m.score?.home??''}-${m.score?.away??''}`).join('|');const token=`${DATA.comp_key||''}:${DATA.updated||''}:${fingerprint}`;if(token!==LAST_SIGNAL_CAPTURE){LAST_SIGNAL_CAPTURE=token;captureMatchSignals(DATA.matches||[])}}
function probabilityMovement(m){return MATCH_SIGNAL_CHANGES[_signalId(m)]||null}
function probabilitySparkline(m){
  const points=MODEL_HISTORY[_signalId(m)]||[];if(points.length<2)return '';
  const vals=points.map(x=>Number(x.p)).filter(Number.isFinite),lo=Math.min(...vals),hi=Math.max(...vals),span=Math.max(1,hi-lo);
  const coords=vals.map((v,i)=>`${Math.round(i/(vals.length-1)*54)+1},${Math.round(17-(v-lo)/span*14)}`).join(' ');
  const delta=Math.round(vals[vals.length-1]-vals[0]),cls=delta>0?'up':delta<0?'down':'flat';
  return `<span class="probTrend ${cls}" title="Model probability movement: ${delta>0?'+':''}${delta} points"><svg viewBox="0 0 56 20" aria-hidden="true"><polyline points="${coords}"/></svg><b>${delta>0?'+':''}${delta}</b></span>`;
}
function _alertEnabled(type){if(type==='live'||type==='upset')return false;const map={soon:'alertsKickoff',model:'alertsModel',market:'alertsModel',data:'alertsData'};return SETTINGS[map[type]]!==false}
function _alertIcon(type){return ({soon:'&#9203;',model:'&#8597;',market:'&#8644;',data:'&#9888;'})[type]||'&#8226;'}
function _alertKey(a){return `${a.t}:${a.id||'app'}:${a.txt}`}
function _alertSeen(){return new Set(_alertReadJSON('matchday.alertsSeen',[]))}
function computeSignalAlerts(){
  const out=[],now=Date.now(),watchedNames=new Set(wlLoad()),updated=Date.parse(DATA.updated||'');
  if(_alertEnabled('data')&&Number.isFinite(updated)&&(now-updated)>180*60000)out.push({t:'data',txt:`Match data was last updated ${ago(DATA.updated)}.`,id:''});
  (DATA.matches||[]).forEach(m=>{
    const watched=watchedNames.has(m.home?.name)||watchedNames.has(m.away?.name)||isFavoriteMatch(m),up=m.prediction?.upset;
    if(_alertEnabled('upset')&&m.status==='LIVE'&&up&&up.radar)out.push({t:'upset',txt:`${up.candidate_name||'Underdog'} is on the live upset radar.`,id:m.id});
    if(!watched)return;
    if(_alertEnabled('live')&&m.status==='LIVE')out.push({t:'live',txt:`${m.home?.code||m.home?.name} ${m.score?.home??0}-${m.score?.away??0} ${m.away?.code||m.away?.name} is live.`,id:m.id});
    if(_alertEnabled('soon')&&m.status==='UPCOMING'&&m.kickoff){const mins=Math.round((new Date(m.kickoff)-now)/60000);if(mins>0&&mins<=90)out.push({t:'soon',txt:`${m.home?.name} v ${m.away?.name} starts in ${mins}m.`,id:m.id});}
    const change=probabilityMovement(m);
    if(_alertEnabled('model')&&change)out.push({t:'model',txt:`${m.prediction?.pick_name||'Model pick'} moved ${change.delta>0?'+':''}${change.delta} probability points.`,id:m.id});
    if(_alertEnabled('market')&&m.prediction&&typeof _v10OfficialPick==='function'){
      const op=_v10OfficialPick(m),edge=_v10OfficialEdge(m,op);
      if(edge!=null&&Math.abs(edge)>=8)out.push({t:'market',txt:`Model and market differ by ${Math.abs(edge)} points on ${op.name}.`,id:m.id});
    }
  });
  return out.filter((a,i,list)=>list.findIndex(b=>_alertKey(b)===_alertKey(a))===i).slice(0,12);
}
function openAlertMatch(id){toggleAlertCenter(false);if(id)openMatchModal(id)}
function markAlertsRead(alerts=computeSignalAlerts()){try{localStorage.setItem('matchday.alertsSeen',JSON.stringify(alerts.map(_alertKey).slice(-80)))}catch(e){}renderSignalAlerts()}
function toggleAlertCenter(force){
  const panel=$('#alertCenter'),bell=$('#alertBell');if(!panel)return;
  const open=force===undefined?panel.hidden:!!force;panel.hidden=!open;
  if(bell){bell.setAttribute('aria-expanded',String(open));bell.setAttribute('aria-label',open?'Close alerts':'Open alerts')}
  if(open){markAlertsRead(computeSignalAlerts());panel.querySelector('.alertCenterClose')?.focus()}
}
function renderSignalAlerts(){
  const bar=$('#alertBar'),panel=$('#alertCenter'),bell=$('#alertBell'),count=$('#alertCount'),alerts=computeSignalAlerts(),seen=_alertSeen();
  const unseen=alerts.filter(a=>!seen.has(_alertKey(a))).length;
  if(count){count.textContent=unseen;count.hidden=!unseen}bell?.classList.toggle('hasAlerts',!!alerts.length);bell?.classList.toggle('hasUnseen',unseen>0);
  if(bar){const urgent=alerts.filter(a=>a.t==='live'||a.t==='upset'||a.t==='model').slice(0,3);bar.style.display=urgent.length?'':'none';bar.innerHTML=urgent.map(a=>`<button class="alertPill ${a.t}" onclick="openAlertMatch('${esc(a.id)}')">${_alertIcon(a.t)} ${esc(a.txt)}</button>`).join('')}
  if(panel)panel.innerHTML=`<div class="alertCenterHead"><div><span>Signal center</span><b>${alerts.length?`${alerts.length} active`:'All quiet'}</b></div><button class="alertCenterClose" onclick="toggleAlertCenter(false)" aria-label="Close alerts">&times;</button></div><div class="alertCenterList">${alerts.length?alerts.map(a=>`<button class="alertItem ${a.t}" onclick="openAlertMatch('${esc(a.id)}')"><i>${_alertIcon(a.t)}</i><span><b>${a.t==='soon'?'Kickoff':a.t==='market'?'Model vs market':a.t[0].toUpperCase()+a.t.slice(1)}</b><small>${esc(a.txt)}</small></span></button>`).join(''):`<div class="alertEmpty"><span>&#10003;</span><b>No active signals</b><p>Star a team to receive kickoff, model-movement and market-gap alerts.</p></div>`}</div><div class="alertCenterFoot"><button onclick="markAlertsRead()">Mark all read</button><button onclick="toggleAlertCenter(false);setView('customize')">Alert settings</button></div>`;
}
computeAlerts=computeSignalAlerts;
renderAlerts=renderSignalAlerts;
document.addEventListener('keydown',e=>{if(e.key==='Escape'&&!$('#alertCenter')?.hidden)toggleAlertCenter(false)});
document.addEventListener('click',e=>{const panel=$('#alertCenter');if(panel&&!panel.hidden&&!e.target.closest('#alertCenter,#alertBell'))toggleAlertCenter(false)});

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
async function pushScore(){ // server grades only picks it locked before kickoff
  if(!LEADERBOARD_URL)return;
  try{const r=await fetch(LEADERBOARD_URL+'?action=sync',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({deviceId:deviceId()})});const d=await r.json();
    if(d.ok&&d.handle){localStorage.setItem('matchday.handle',d.handle);localStorage.setItem('matchday.handleAssigned','1')}}catch(e){}
}
async function fetchLeaderboard(period){
  if(!LEADERBOARD_URL)return null;
  try{const r=await fetch(LEADERBOARD_URL+'?action=leaderboard&period='+(period||'all'));const d=await r.json();return d.ok?d.board:null;}catch(e){return null;}
}
function lbPeriod(){try{return localStorage.getItem('matchday.lbPeriod')||'all'}catch(e){return 'all'}}
function setLbPeriod(p){try{localStorage.setItem('matchday.lbPeriod',p)}catch(e){};renderCommunity();}
function btmLoad(){try{return JSON.parse(localStorage.getItem('matchday.btm')||'{}')}catch(e){return {}}}
function btmSave(o){try{localStorage.setItem('matchday.btm',JSON.stringify(o))}catch(e){}}
function communityScope(){const k=String(DATA?.comp_key||'ALL').toUpperCase();return k==='ALL'?'ALL':k;}
function btmScoped(db){const scope=communityScope();if(scope==='ALL')return db;
  const picks={};Object.entries(db.picks||{}).forEach(([id,p])=>{if(String(p.comp||'WC').toUpperCase()===scope)picks[id]=p;});
  return {...db,picks};}
function isCommunityPickOpen(m){const kickoff=kickMs(m);return m?.status==='UPCOMING'&&kickoff> Date.now()&&!isStaleUpcoming(m)}
async function lockGlobalPick(matchId,pick,comp){
  if(!LEADERBOARD_URL)return;
  try{const r=await fetch(LEADERBOARD_URL+'?action=pick',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({deviceId:deviceId(),matchId:String(matchId),pick,comp:String(comp||'').toLowerCase()})});
    const d=await r.json();if(d.ok&&d.handle){localStorage.setItem('matchday.handle',d.handle);localStorage.setItem('matchday.handleAssigned','1')}}catch(e){}
}
function submitPick(matchId,pick){
  ensureHandle();
  const db=btmLoad();db.picks=db.picks||{};
  if(db.picks[matchId])return false; // one locked pick per match, like the model
  const m=(DATA.matches||[]).find(x=>String(x.id)===String(matchId));if(!m)return false;
  // A feed can still say UPCOMING after the clock has passed kickoff. The
  // timestamp is therefore a second, mandatory lock check.
  if(!isCommunityPickOpen(m))return false;
  const official=officialPrediction(m);
  db.picks[matchId]={pick,ts:Date.now(),
    home:m.home.name,away:m.away.name,code:{h:m.home.code,a:m.away.code},
    comp:m._comp||DATA.comp_key||'',
    modelPick:official.side||null,
    marketPick:(()=>{const x=(m.markets||{})['1x2'];if(!x||x.home_pct==null)return null;const tr={h:x.home_pct,d:x.draw_pct,a:x.away_pct};return Object.keys(tr).reduce((a,b)=>tr[b]>tr[a]?b:a)})()};
  btmSave(db);renderCommunity();lockGlobalPick(matchId,pick,db.picks[matchId].comp);return true;
}
