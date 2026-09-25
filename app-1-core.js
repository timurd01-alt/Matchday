
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
const DEFAULT_SETTINGS={accent:'green',density:'normal',panel:'glass',defaultView:'home',refresh:900,showFinished:false,showDetails:false,favoriteTeam:'',favoriteTeams:[],alertsKickoff:true,alertsLive:false,alertsUpset:false,alertsModel:true,alertsData:true};
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
// Every board is a single sport's. A stored selection from before the merged
// "All college" board was removed (or from a sport we no longer publish) names
// a file nothing would load, so it is migrated to the default rather than left
// to fail: an empty DATA_FILE has no meaning now.
const DEFAULT_SPORT_FILE='data_ncaaf.json';
let DATA_FILE=DEFAULT_SPORT_FILE;try{const saved=localStorage.getItem('matchday.sport')||'';DATA_FILE=/^data_(ncaaf|ncaam)\.json$/i.test(saved)?saved:DEFAULT_SPORT_FILE;if(DATA_FILE!==saved)localStorage.setItem('matchday.sport',DATA_FILE)}catch(e){}
const SPORT_LABELS={ncaaf:'College Football',ncaam:"Men's College Basketball"};
// The only sports Matchday covers.
const ALL_SPORT_KEYS=['ncaaf','ncaam'];
const FIXTURE_PAGE_SIZE=40;
// The model board used to render every pick in one scroll (1,300+ rows on a
// full slate). Same pager the fixture list already uses, smaller page: a pick
// row is denser reading than a match card.
let MATCH_VISIBLE=FIXTURE_PAGE_SIZE,RESULT_VISIBLE=FIXTURE_PAGE_SIZE;
// Providers can keep the season that just ended until the next schedule
// opens. Keep its games in Results, but never label its table or bracket as
// the new season's live competition state.
function competitionSeasonCutoff(comp,now=new Date()){
  const key=String(comp||'').toUpperCase(),year=now.getUTCFullYear();
  const startYear=now.getUTCMonth()>=6?year:year-1;
  return new Date(Date.UTC(startYear,6,1));
}
function stripPastSeasonCompetitionViews(payload,now=new Date()){
  if(!payload)return payload;
  if(payload.season_context?.position_views_current===true)return payload;
  const key=String(payload.comp_key||'').toUpperCase(),cutoff=competitionSeasonCutoff(key,now);
  const matches=Array.isArray(payload.matches)?payload.matches:[];
  const currentResult=matches.some(m=>{
    const when=new Date(m?.kickoff||0);
    return ['FINISHED','LIVE'].includes(String(m?.status||'').toUpperCase())&&!Number.isNaN(+when)&&when>=cutoff;
  });
  const future=matches.some(m=>String(m?.status||'').toUpperCase()==='UPCOMING'&&new Date(m?.kickoff||0)>now);
  if(currentResult)return payload;
  const teams=(payload.standings||[]).flatMap(group=>group?.teams||[]);
  const cleanPreseasonTable=future&&teams.length&&teams.every(team=>team?.pld==null||Number(team.pld)===0);
  const currentProjection=payload.season_context?.projection_current===true;
  if(currentProjection){
    payload.standings=(payload.standings||[]).filter(group=>/projection/i.test(String(group?.group||'')));
  }else if(!cleanPreseasonTable){
    payload.standings=[];
  }
  if(!currentProjection)payload.bracket=[];
  if(!currentProjection)payload.bracketology=null;
  payload.third_race=[];
  payload.advancement=[];
  payload._season_views_suppressed=true;
  return payload;
}

// ---- per-sport sidebar (data-driven, follows the SELECTION) ---------------
// Each sport declares exactly which views exist for it, in order.
const NAV_DEF={
  // Matchday covers college football and men's college basketball only. Every
  // profile exposes the same destinations. The established route keys remain
  // in place so saved preferences and bookmarks continue to work.
  college:           ['home','matches','groups','results','news','score','bracket','community'],
  college_basketball:['home','matches','groups','results','news','score','bracket','community']
};
// The only views that exist after the college pivot. A stored defaultView or a
// bookmarked hash can still name a removed one (Customize let people save
// 'news' or 'updates' for years), so every entry point clamps through this
// rather than trusting what it was handed and rendering into a null host.
const VIEWS=new Set(['home','matches','results','groups','bracket','score','news','community']);
const VIEW_ALIASES={games:'matches',rankings:'groups',research:'news'};
function safeView(v){v=VIEW_ALIASES[v]||v;return VIEWS.has(v)?v:'home';}
const SPORT_KIND={ncaaf:'college',ncaam:'college_basketball'};
function currentSportKey(){const m=(DATA_FILE||'').match(/data_(\w+)\.json/);return m?m[1]:'';}
function navProfile(){return SPORT_KIND[currentSportKey()]||'college';}
const NAV_LABELS={college:{home:'Home',matches:'Games',groups:'Rankings',news:'Research',bracket:'CFP Playoff'},college_basketball:{home:'Home',matches:'Games',groups:'Rankings',news:'Research',bracket:'Bracketology'}};
function tottTitle(){return 'Team of the Tournament'}
function applySportNav(){
  const prof=navProfile();
  const allowed=NAV_DEF[prof];
  const labels=NAV_LABELS[prof]||{};
  document.querySelectorAll('.navbtn[data-v]').forEach(b=>{
    const hasBracket=(Array.isArray(DATA?.bracket)&&DATA.bracket.some(r=>(r?.matches||[]).length))||!!DATA?.bracketology;
    const hasThirdRace=Array.isArray(DATA?.third_race)&&DATA.third_race.length>0;
    const hasViewData=b.dataset.v==='bracket'?hasBracket:b.dataset.v==='third'?hasThirdRace:true;
    b.style.display=allowed.includes(b.dataset.v)&&hasViewData?'':'none';
    const l=b.querySelector('.lbl');
    if(l){const en=l.getAttribute('data-en')||l.textContent.trim();l.setAttribute('data-en',en);
      l.textContent=labels[b.dataset.v]||t(en);
      // sidebar icons carry no visible label outside the guided tour, so a
      // native tooltip is the only way to tell them apart on hover
      b.title=l.textContent;}});
  document.querySelectorAll('.navGroup').forEach(g=>{
    g.hidden=!g.querySelector('.navbtn[data-v]:not([style*="display: none"]),.navExternal');
  });
  const activeButton=document.querySelector(`.navbtn[data-v="${VIEW}"]`);
  if(!allowed.includes(VIEW)||!activeButton||activeButton.style.display==='none')setView('matches');
}
function loadingBoardHTML(){return '<div class="loadingBoard" aria-label="Loading matches"><span></span><span></span><span></span><span></span></div>'}
function showMatchLoading(){const host=$('#view-matches');if(host)host.innerHTML=loadingBoardHTML()}
function clearCompetitionViewsForLoad(){
  ['groups','bracket','third'].forEach(view=>{const host=$('#view-'+view);if(host)host.innerHTML='<div class="empty">Loading current-season data…</div>'});
}
function changeSport(v){DATA_FILE=/^(ncaaf|ncaam)$/.test(v)?('data_'+v+'.json'):DEFAULT_SPORT_FILE;MATCH_VISIBLE=FIXTURE_PAGE_SIZE;RESULT_VISIBLE=FIXTURE_PAGE_SIZE;try{localStorage.setItem('matchday.sport',DATA_FILE)}catch(e){};if(typeof syncViewLocation==='function')syncViewLocation(VIEW,'replace');const cached=SPORT_DATA_CACHE[DATA_FILE];if(cached){showSportData(cached,true)}else{applySportNav();showMatchLoading();clearCompetitionViewsForLoad()}load(true);}

const COLORS={orange:'#ffb02e',blue:'#4cc2ff',green:'#3ad17a',red:'#ff4d5e',purple:'#b16cff'};
function saveSettings(){localStorage.setItem('matchday.settings',JSON.stringify(SETTINGS))}
function applySettings(){document.documentElement.style.setProperty('--signal',COLORS[SETTINGS.accent]||COLORS.orange);document.body.classList.toggle('compact',SETTINGS.density==='compact');document.body.classList.toggle('spacious',SETTINGS.density==='spacious');$('#app').classList.toggle('flat',SETTINGS.panel==='flat');document.body.classList.toggle('hideStats',!SETTINGS.showDetails)}
function updateSetting(k,v){if(k==='refresh')return;if(k==='showDetails'||k==='showFinished'||k.startsWith('alerts'))v=!!v;SETTINGS[k]=v;saveSettings();applySettings();renderCurrent();if(k.startsWith('alerts'))renderAlerts();scheduleNextLoad()}
function resetSettings(){SETTINGS={...DEFAULT_SETTINGS};saveSettings();applySettings();setView(SETTINGS.defaultView);scheduleNextLoad()}
// Feeds hand over headlines with HTML entities still in them ("Ducks&#39;"),
// and esc() would then print the entity itself. Decode once, on load.
const _NAMED_ENTITIES={amp:'&',lt:'<',gt:'>',quot:'"',apos:"'",nbsp:' ',rsquo:'\u2019',lsquo:'\u2018',rdquo:'\u201d',ldquo:'\u201c',ndash:'\u2013',mdash:'\u2014',hellip:'\u2026'};
// Pure string decoding: the text never passes through the DOM, so a headline
// can never be reinterpreted as markup. Callers still esc() before rendering.
function decodeEntities(s){let out=String(s??'');for(let i=0;i<3;i++){const next=out.replace(/&(#\d+|#x[0-9a-f]+|[a-z]+);/gi,(whole,body)=>{if(body[0]==='#'){const code=body[1]==='x'||body[1]==='X'?parseInt(body.slice(2),16):parseInt(body.slice(1),10);return Number.isFinite(code)&&code>0&&code<=0x10ffff?String.fromCodePoint(code):whole}const named=_NAMED_ENTITIES[body.toLowerCase()];return named===undefined?whole:named});if(next===out)break;out=next}return out}
function decodeNewsEntities(payload){(payload?.news||[]).forEach(a=>{for(const k of ['headline','title','desc','source','feed'])if(typeof a[k]==='string')a[k]=decodeEntities(a[k])});return payload}
function esc(s){return String(s??'').replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]))}
function uiLocale(){return({es:'es',fr:'fr',de:'de',pt:'pt-BR',ru:'ru'})[LANG]||undefined}
function relativeTime(value,unit){return new Intl.RelativeTimeFormat(uiLocale(),{numeric:'auto'}).format(value,unit)}
function dt(iso){try{return new Date(iso).toLocaleString(uiLocale(),{weekday:'short',hour:'numeric',minute:'2-digit',month:'short',day:'numeric'})}catch(e){return''}}
function ago(iso){try{const s=(Date.now()-new Date(iso).getTime())/1000;if(!isFinite(s))return'';if(s<70)return relativeTime(0,'second');if(s<3600)return relativeTime(-Math.round(s/60),'minute');if(s<86400)return relativeTime(-Math.round(s/3600),'hour');return relativeTime(-Math.round(s/86400),'day')}catch(e){return''}}
function kickIn(iso){try{const m=Math.round((new Date(iso)-Date.now())/60000);if(m<=0)return relativeTime(0,'minute');if(m<60)return relativeTime(m,'minute');if(m<1440)return relativeTime(Math.round(m/60),'hour');return relativeTime(Math.round(m/1440),'day')}catch(e){return''}}
const ODDS_WINDOW_HOURS=24; // mirrors fetch_data.py's PREGAME_ODDS_WINDOW_HOURS quota gate
function oddsEtaLabel(m){try{const mins=(new Date(m.kickoff)-Date.now())/60000;if(mins>ODDS_WINDOW_HOURS*60)return `Market odds checked from ${ODDS_WINDOW_HOURS}h before kickoff`}catch(e){}return null}
const STALE_MATCH_MINUTES=150;
// A kickoff with no announced time. The college feed stores those as midnight
// US Eastern on the game's date (04:00Z / 05:00Z), which rendered as "11:00 PM"
// the night before in Central time and filed a Saturday game under Friday. An
// explicit provider flag wins; otherwise exactly 00:00 Eastern is the marker.
function kickoffTimeTbd(m){
  if(m?.time_tbd===true)return true;if(m?.time_tbd===false)return false;
  const t=Date.parse(m?.kickoff||'');if(!Number.isFinite(t))return false;
  try{const p=new Intl.DateTimeFormat('en-US',{timeZone:'America/New_York',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).formatToParts(new Date(t));
    return p.find(x=>x.type==='hour')?.value==='00'&&p.find(x=>x.type==='minute')?.value==='00'}catch(e){return false}
}
function easternDayKey(ms){try{return new Intl.DateTimeFormat('en-CA',{timeZone:'America/New_York',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date(ms))}catch(e){return boardDayKey(ms)}}
function kickMs(m){const t=Date.parse(m?.kickoff||'');return Number.isFinite(t)?t:0}
function isStaleUpcoming(m){const t=kickMs(m);return m?.status==='UPCOMING'&&t>0&&(Date.now()-t)>STALE_MATCH_MINUTES*60000}
function isCompleteOrPast(m){return m?.status==='FINISHED'||isStaleUpcoming(m)}
function isVisibleUpcoming(m){return m?.status==='UPCOMING'&&!isStaleUpcoming(m)}
function fixtureSort(a,b){const o={LIVE:0,UPCOMING:1,FINISHED:2};return (o[a.status]??9)-(o[b.status]??9)||(a.kickoff||'').localeCompare(b.kickoff||'')}
// Pure function of the name, and the fixture merge calls it millions of times
// across a few hundred distinct schools, so the answer is kept.
const _TEAM_KEY_CACHE=new Map();
/* Apostrophes are deleted, not turned into a space.
   ESPN files the school as "Hawai'i Rainbow Warriors" and the odds feed as
   "Hawaii Rainbow Warriors". Replacing the apostrophe with a space gives
   "hawai i rainbow warriors", which matches "hawaii rainbow warriors" on no
   test at all -- not the exact key, and not the prefix rule either, since
   "hawai" is not a word in the other name. So Bet Better's card for Hawai'i at
   Wyoming sat in the payload unattached, and the fixture fell through to
   Matchday's own preseason model, which had zero games of evidence for either
   side. The same miss empties Hawai'i's record and its ratings lookup.
   Bet Better's `comparison._fold` deletes them for exactly this reason. */
function teamKey(name){
  const label=String(name||'');
  const hit=_TEAM_KEY_CACHE.get(label);
  if(hit!==undefined)return hit;
  const key=label.toLowerCase().replace(/['‘’ʻʼ]/g,'')
                 .replace(/[^a-z0-9]+/g,' ').trim();
  _TEAM_KEY_CACHE.set(label,key);
  return key;
}
function teamInitials(team){
  const code=String(team?.code||'').replace(/[^A-Za-z0-9]/g,'').slice(0,3).toUpperCase();
  if(code)return code;
  const words=String(team?.name||'Team').replace(/\b(fc|cf|afc|sc|club|united)\b/ig,' ').trim().split(/\s+/).filter(Boolean);
  return (words.length>1?words.slice(0,3).map(w=>w[0]).join(''):words[0]?.slice(0,3)||'TM').toUpperCase();
}
function teamHue(team){let h=0;for(const ch of String(team?.name||team?.code||'team'))h=(h*31+ch.charCodeAt(0))%360;return h}
function teamMarkHTML(team,extra=''){
  return teamMark(team?.name,extra);
}
function metricHelp(label,copy){return `<button type="button" class="metricHelp" aria-label="${esc(label)}: ${esc(copy)}" aria-expanded="false" aria-controls="metricHelpPopover" data-tip="${esc(copy)}">?</button>`}
function metricHelpPopover(){
  let pop=document.querySelector('#metricHelpPopover');
  if(pop)return pop;
  pop=document.createElement('div');
  pop.id='metricHelpPopover';
  pop.className='metricHelpPopover';
  pop.setAttribute('role','tooltip');
  pop.setAttribute('aria-live','polite');
  pop.hidden=true;
  document.body.appendChild(pop);
  return pop;
}
function syncMetricHelpPopover(help,open){
  const pop=document.querySelector('#metricHelpPopover');
  document.querySelectorAll('.metricHelp[aria-describedby="metricHelpPopover"]').forEach(item=>item.removeAttribute('aria-describedby'));
  if(pop)pop.hidden=true;
  if(!open||!help||!window.matchMedia('(max-width: 760px)').matches)return;
  const mobilePop=metricHelpPopover();
  mobilePop.textContent=help.getAttribute('aria-label')||help.dataset.tip||'';
  mobilePop.hidden=false;
  help.setAttribute('aria-describedby',mobilePop.id);
}
function closeMetricHelps(except){
  document.querySelectorAll('.metricHelp.isOpen').forEach(help=>{
    if(help===except)return;
    help.classList.remove('isOpen');
    help.setAttribute('aria-expanded','false');
  });
  syncMetricHelpPopover(null,false);
}
document.addEventListener('click',event=>{
  const help=event.target.closest?.('.metricHelp');
  if(!help){closeMetricHelps();return;}
  event.preventDefault();
  event.stopImmediatePropagation();
  const open=!help.classList.contains('isOpen');
  closeMetricHelps(help);
  help.classList.toggle('isOpen',open);
  help.setAttribute('aria-expanded',String(open));
  syncMetricHelpPopover(help,open);
  if(!open)help.blur();
},true);
document.addEventListener('keydown',event=>{
  if(event.key!=='Escape')return;
  const open=document.querySelector('.metricHelp.isOpen');
  if(!open)return;
  event.preventDefault();
  event.stopImmediatePropagation();
  closeMetricHelps();
  open.blur();
});
// Following was a single team, stored as a string. Plenty of people follow a
// handful -- three NFL teams, or a club and a national side -- and got a board
// no different from an anonymous visitor's. favoriteTeams() is the list;
// favoriteTeam() stays as the first entry because the news term and the insight
// rail are built around one subject and reading them for a whole list would just
// dilute both.
function favoriteTeams(){
  const raw=SETTINGS.favoriteTeams;
  if(Array.isArray(raw))return raw.map(name=>String(name||'').trim()).filter(Boolean);
  // Migration: honour a previously saved single favourite until it is re-saved.
  const one=String(SETTINGS.favoriteTeam||'').trim();
  return one?[one]:[];
}
function favoriteTeam(){return favoriteTeams()[0]||''}
function isFollowingTeam(name){const key=teamKey(name);return !!key&&favoriteTeams().some(fav=>teamKey(fav)===key)}
function toggleFavoriteTeam(name){
  const clean=String(name||'').trim();if(!clean)return;
  const next=isFollowingTeam(clean)?favoriteTeams().filter(fav=>teamKey(fav)!==teamKey(clean)):[...favoriteTeams(),clean];
  updateSetting('favoriteTeams',next);
}
function favoriteNewsTerm(){return teamKey(favoriteTeam()).replace(/\b(fc|afc|cf|sc|football club)\b/g,'').replace(/\s+/g,' ').trim()}
function isFavoriteTeam(name){return isFollowingTeam(name)}
function isFavoriteMatch(m){return !!m&&(isFavoriteTeam(m.home?.name)||isFavoriteTeam(m.away?.name))}
function favoriteFixtureSort(a,b){return Number(isFavoriteMatch(b))-Number(isFavoriteMatch(a))||fixtureSort(a,b)}
function favoriteTeamNames(){
  const names=new Set();
  (DATA.matches||[]).forEach(m=>{if(m.home?.name)names.add(m.home.name);if(m.away?.name)names.add(m.away.name)});
  (DATA.standings||[]).forEach(g=>(g.teams||[]).forEach(team=>{if(team.name)names.add(team.name)}));
  // A followed team whose sport is out of season isn't on the current slate;
  // keep it listed so it can still be removed.
  favoriteTeams().forEach(name=>names.add(name));
  return [...names].sort((a,b)=>a.localeCompare(b));
}
// The followed list, plus a picker that adds to it. Rendered as chips rather
// than a multi-select because removing one entry from a native multi-select
// means ctrl-clicking, which nobody discovers.
function favoriteTeamsControl(){
  const following=favoriteTeams();
  const chips=following.length
    ?following.map(name=>`<button type="button" class="favChip" onclick="toggleFavoriteTeam(${JSON.stringify(name).replace(/"/g,'&quot;')})" aria-label="${esc('Stop following '+name)}">${esc(name)}<span aria-hidden="true">&times;</span></button>`).join('')
    :`<span class="favEmpty">${t('No favorite selected')}</span>`;
  const available=favoriteTeamNames().filter(name=>!isFollowingTeam(name));
  const picker=`<select class="favAdd" onchange="if(this.value){toggleFavoriteTeam(this.value);this.value=''}" aria-label="${esc('Add a team to follow')}"><option value="">${t('Add a team')}…</option>${available.map(name=>`<option value="${esc(name)}">${esc(name)}</option>`).join('')}</select>`;
  return `<div class="favChips">${chips}</div>${picker}`;
}
const SCORE_DIFF_TERM={ncaaf:'point diff',ncaam:'point diff'};
function scoreDiffLabel(m){return SCORE_DIFF_TERM[String(m?._comp||DATA.comp_key||'').toLowerCase()]||'point diff';}
const SCORE_DIFF_ABBR={ncaaf:'PD',ncaam:'PD'};
// College tables rank on win-loss record, so the pts value the pipeline derives
// (wins x 3) is not a number any fan recognises -- NCAAF showed "27 pts" for a
// 9-4 team. No competition shows a standings-points column.
const TABLE_POINTS_COMPS=new Set();
function usesTablePoints(comp){return TABLE_POINTS_COMPS.has(String(comp??DATA.comp_key??'').toUpperCase())}
function teamRecordText(team){
  if(team?.record)return String(team.record);
  const w=Number(team?.w),l=Number(team?.l),d=Number(team?.d);
  if(!Number.isFinite(w)||!Number.isFinite(l))return '';
  return `${w}-${l}${Number.isFinite(d)&&d?`-${d}`:''}`;
}
// One standings blurb shared by the fixture card, the expanded view's hero and
// its match-read panel, so all three stay honest about the same sport.
function teamStandingsMeta(team,comp,opts){
  opts=opts||{};
  const parts=[];
  if(team?.pos)parts.push(`#${team.pos}`);
  if(usesTablePoints(comp)){
    const pts=Number(team?.pts);
    // Preseason there is no table yet, so "0 pts" is a placeholder pretending
    // to be a standing. Say nothing until a game has been played.
    if(Number.isFinite(pts)&&Number(team?.pld))parts.push(`${pts} pts`);
  }else if(!(opts.hideStaleRecord&&team?.season_stale)){
    const rec=teamRecordText(team);
    if(rec)parts.push(rec);
  }
  if(opts.diff){
    const gd=Number(team?.gd);
    // A team whose provider gave no scoring data at all reads gd 0 with gf/ga
    // 0 -- that is "unknown", not "dead even", so leave the row off entirely.
    if(Number.isFinite(gd)&&(gd||Number(team?.gf)||Number(team?.ga)))parts.push(`${SCORE_DIFF_ABBR[String(comp??DATA.comp_key??'').toLowerCase()]||'PD'} ${gd>0?'+':''}${gd}`);
  }
  const form=String(team?.form||'').trim();
  if(opts.form&&form)parts.push(form);
  return parts;
}
function scoreText(m){if(m.status==='LIVE')return'<span class="pendingScore" aria-label="Score shown after final">—</span>';const done=m.status==='FINISHED';if(isStaleUpcoming(m))return'<span class="kick">Past kickoff</span>';return done?`${m.score?.home??'-'}<span class="sep">–</span>${m.score?.away??'-'}${m.score?.pens?`<span class="pensTag">(${m.score.pens.home}-${m.score.pens.away} pens)</span>`:''}`:`<span class="kick">${kickoffTimeTbd(m)?'Time TBA':(dt(m.kickoff).split(', ').pop()||'TBD')}</span>`}
function scorePlainText(m){if(m?.status==='LIVE')return '—';if(isStaleUpcoming(m))return 'Past kickoff';if(m?.status==='FINISHED'){const pens=m.score?.pens?` (${m.score.pens.home}-${m.score.pens.away} pens)`:'';return `${m.score?.home??'-'}–${m.score?.away??'-'}${pens}`;}return dt(m?.kickoff).split(', ').pop()||'TBD';}
function statNum(v){const m=String(v??'').match(/-?\d+(\.\d+)?/);return m?Number(m[0]):0}
function pressure(stats,side){if(!stats)return 0;const s=stats[side]||{};return statNum(s.shots_on_target)*4+statNum(s.shots)*1.2+statNum(s.corners)*1.4+statNum(String(s.possession).replace('%',''))*.08-statNum(s.red_cards)*4}
function pct(v){v=Number(v);return Number.isFinite(v)?Math.max(0,Math.min(100,Math.round(v))):0}
function modelPctLabel(v){const n=Number(v);return v==null||!Number.isFinite(n)?'—':Math.max(0,Math.min(99.9,n)).toFixed(1)+'%'}
function bar1x2(h,d,a){h=pct(h);a=pct(a);const dSeg=d==null?'':(d=>`<div class="seg d" style="flex-basis:${d}%"><span>${d}%</span></div>`)(pct(d));return `<div class="bar"><div class="seg h" style="flex-basis:${h}%"><span>${h}%</span></div>${dSeg}<div class="seg a" style="flex-basis:${a}%"><span>${a}%</span></div></div>`}
function duo(xl,xv,yl,yv){xv=pct(xv);yv=pct(yv);return `<div class="mkt"><div class="lbls"><span>${esc(xl)} <b>${xv}%</b></span><span><b>${yv}%</b> ${esc(yl)}</span></div><div class="duo"><i class="x" style="flex-basis:${xv}%">${xv}%</i><i class="y" style="flex-basis:${yv}%">${yv}%</i></div></div>`}
function marketPanel(m){
  const mk=m.markets||{},x=mk['1x2']||{},twoWay=_isTwoWay(m);
  let h='<div class="seclbl">Market price</div>';
  if(x.home_pct!=null){
    h+=`<div class="problbl"><span>${esc(m.home.code||m.home.name)} win</span>${twoWay?'':'<span>draw</span>'}<span>${esc(m.away.code||m.away.name)} win</span></div>${bar1x2(x.home_pct,twoWay?null:x.draw_pct,x.away_pct)}<div class="faintline" style="margin-top:6px">1X2 market · ${x.books||'?'} books</div>`;
    const arr=v=>v>0?`<span class="up">▲${v}</span>`:v<0?`<span class="down">▼${Math.abs(v)}</span>`:`<span class="flat">·</span>`;
    if(x.move&&(x.move.h||(!twoWay&&x.move.d)||x.move.a)){
      h+=`<div class="oddsMove"><span class="mvlbl">Since open</span><span>${esc(m.home.code)} ${arr(x.move.h)}</span>${twoWay?'':`<span>X ${arr(x.move.d)}</span>`}<span>${esc(m.away.code)} ${arr(x.move.a)}</span></div>`;
    }else if(x.open){
      h+=`<div class="faintline" style="margin-top:4px">No line movement logged yet — it builds as the fetcher keeps running.</div>`;
    }
    if(x.confidence){
      h+=`<div class="oddsDisagree ${esc(x.confidence)}"><span class="dgtag">${esc(x.confidence)}</span><span>books range ${x.spread_lo}–${x.spread_hi}% on ${esc(m.home.code)} win</span><span class="dgspread">±${x.spread}</span></div>`;
    }
  }else{
    const read=typeof betbetterReadFor==='function'?betbetterReadFor(m):null;
    const price=read?.market_pct==null?NaN:Number(read.market_pct);
    if(Number.isFinite(price)&&price>=0&&price<=100){
      const stamp=Date.parse(read.generated_at||read.handoff_generated_at||'');
      const when=Number.isFinite(stamp)?` · ${esc(new Date(stamp).toLocaleString())}`:'';
      h+=`<div class="readSide"><span>${esc(read.pick_name||'Model pick')}</span><strong>${Math.min(99.9,price).toFixed(1)}%</strong></div><div class="faintline">Market probability recorded with the published forecast${when}. Snapshot, not a live quote.</div>`;
    }else{
      h+=`<div class="nomk">${esc(oddsEtaLabel(m)||'No market price available yet.')}</div>`;
    }
  }
  if(mk.totals)h+=`<div class="seclbl">Goals — over/under ${esc(mk.totals.line)}</div>`+duo(`Over ${mk.totals.line}`,mk.totals.over_pct,`Under ${mk.totals.line}`,mk.totals.under_pct);
  return h;
}
/* dedup */
/* dedup */
/* dedup */
/* dedup */
/* removed duplicate (cardHTML) */

// ---- landing hero (first thing a visitor sees) ----------------------------
let HERO_FIRST_VISIT=false;try{HERO_FIRST_VISIT=!localStorage.getItem('matchday.heroVisited');if(HERO_FIRST_VISIT)localStorage.setItem('matchday.heroVisited','1')}catch(e){}
function heroSeen(){try{return localStorage.getItem('matchday.heroSeen')==='1'||!HERO_FIRST_VISIT}catch(e){return false}}
function heroDismiss(){try{localStorage.setItem('matchday.heroSeen','1')}catch(e){};renderCurrent();}
function welcomeDismissed(){if(window.MATCHDAY_ENTERED)return true;try{return sessionStorage.getItem('matchday.welcome.entered')==='1'}catch(e){return false}}
// The Matchday wordmark in the top bar takes a fan back to the welcome page.
function openWelcome(){window.MATCHDAY_ENTERED=false;try{sessionStorage.removeItem('matchday.welcome.entered')}catch(e){}renderWelcome();window.scrollTo?.(0,0);document.getElementById('welcomeGate')?.focus?.()}
function enterMatchday(targetView='',startWithTour=false){
  window.MATCHDAY_ENTERED=true;
  try{sessionStorage.setItem('matchday.welcome.entered','1');localStorage.setItem('matchday.heroSeen','1')}catch(e){}
  const gate=$('#welcomeGate'),app=$('#app');
  const finish=()=>{
    if(gate){gate.hidden=true;gate.classList.remove('welcomeLeaving')}
    document.body.classList.remove('welcomeOpen','welcomeExiting');
    if(app)app.classList.remove('appRevealing');
    window.scrollTo?.(0,0);
    if(typeof setView==='function')setView(targetView||VIEW||'home',{replace:!targetView});else renderCurrent();
    const main=document.querySelector('.content');if(main)main.focus?.();
    if(startWithTour)setTimeout(startTour,500);
  };
  if(!gate||prefersReducedMotion()){finish();return}
  gate.classList.add('welcomeLeaving');
  document.body.classList.remove('welcomeOpen');document.body.classList.add('welcomeExiting');
  if(app)app.classList.add('appRevealing');
  setTimeout(finish,260);
}

// ---- guided tour (first-visit walkthrough) --------------------------------
const TOUR_STEPS=[
  {target:'#sportSel',title:'Start here',body:'Switch between College Football and Men’s College Basketball. Each has its own predictions, accuracy tracking and playoff picture.'},
  {target:'.navbtn[data-v="matches"]',title:'Matches',body:'Every upcoming fixture with the model’s locked pregame pick shown next to the market’s.'},
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
// The gate's IN FOCUS card is a model read like any other on the site, so it
// comes from the same engine as every other one: Bet Better's. It used to read
// m.prediction through _v10OfficialPick -- Matchday's own forecast -- so the
// front door quoted one model and every screen behind it quoted another, under
// the same word, "MODEL". A fixture the engine has not priced now shows the
// fixture with no number, rather than another model's number in its place.
function _welcomeCardHTML(m){
  const bb=typeof betbetterReadFor==='function'?betbetterReadFor(m):null;
  const pick=bb?.pick_name||'';
  // Number(null) is 0, and the handoff writes null for a fixture it never got
  // a price on -- straight through Number.isFinite, that renders "market 0.0%"
  // and "0.0 pts vs market" for a game with no market at all. A missing number
  // has to stay missing.
  const num=v=>{const n=Number(v);return v==null||v===''||!Number.isFinite(n)?NaN:n};
  const model=num(bb?.model_pct),market=num(bb?.market_pct),edge=num(bb?.edge_points);
  // renderWelcome only ever hands this a priced fixture, so there is no
  // no-number branch: a game without a read is not shown at all.
  const hasEdge=Number.isFinite(edge)&&Number.isFinite(market);
  const edgeChip=hasEdge
    ?`<em class="welcomeEdge ${edge>0?'up':edge<0?'down':''}">${edge>0?'+':''}${edge.toFixed(1)} pts vs market</em>`
    :'';
  // Two numbers on one bar rather than two numbers in a sentence: the fill is
  // the model's probability and the notch is the market's, so the gap between
  // them -- the only thing the pair is actually saying -- is the thing you see.
  const meter=Number.isFinite(model)
    ?`<div class="welcomeMeter" aria-hidden="true"><i style="--welcome-p:${pct(model)}%"></i>${Number.isFinite(market)?`<u style="--welcome-m:${pct(market)}%"></u>`:''}</div>
      <div class="welcomeMeterKey"><span><b></b>model ${modelPctLabel(model)}</span>${Number.isFinite(market)?`<span><i></i>market ${market.toFixed(1)}%</span>`:''}</div>`
    :'';
  const read=pick&&Number.isFinite(model)
    ?`<div class="welcomeRead"><div class="welcomeReadTop"><span>MODEL PICK</span>${edgeChip}</div>
       <div class="welcomeReadPick"><b>${esc(pick)}</b><strong>${modelPctLabel(model).slice(0,-1)}<small>%</small></strong></div>
       ${meter}</div>`
    :'';
  return `<div class="welcomeMatchMeta"><span>${esc(m._comp||DATA.comp_key||m.stage||'NEXT')}</span><span>${kickIn(m.kickoff)}</span></div><div class="welcomeTeams"><div><small>${esc(m.home?.code||'HOME')}</small><b>${esc(m.home?.name||'Home')}</b></div><em>v</em><div class="away"><small>${esc(m.away?.code||'AWAY')}</small><b>${esc(m.away?.name||'Away')}</b></div></div>${read}`;
}


// Real coverage numbers, counted from the slate that just loaded. Deliberately
// three short figures rather than another paragraph of claims.
// Every sport's graded record, not just the loaded board's. The scorecard is a
// static script carrying all of them, so this costs nothing -- and the gate is
// the front door for the whole site, where a per-sport figure understates it.
function scorecardTotals(){
  const all=(typeof MATCHDAY_BETBETTER_SCORECARD!=='undefined')?MATCHDAY_BETBETTER_SCORECARD:null;
  const sports=Object.values(all?.sports||{}).filter(s=>s?.available);
  return {picks:sports.reduce((n,s)=>n+(Number(s.record?.picks)||0),0),
          lockMinutes:sports.map(s=>Number(s.lock_policy?.lead_minutes)).find(Number.isFinite)??null};
}
function renderWelcomeStats(){
  const host=$('#welcomeStats');if(!host)return;
  const M=DATA.matches||[];
  const weekEnd=new Date();weekEnd.setHours(23,59,59,999);weekEnd.setDate(weekEnd.getDate()+7);
  const upcoming=M.filter(m=>isVisibleUpcoming(m)&&new Date(m.kickoff)<=weekEnd);
  if(!upcoming.length){host.innerHTML='';return}
  // The first two cells used to disagree about what they were counting: the
  // fixture count came from whichever board was loaded while the second cell
  // read a constant ("2 competitions") for the whole product. A board is one
  // sport now, so the fixture count says which sport it is counting, and the
  // product-wide claim is the graded record, which really is product-wide.
  // "Model coverage" is gone: it was 100% on every board that had a model at
  // all, which is not information, and 0% while picks were paused, which read
  // like a broken site.
  const sportLabel=SPORT_LABELS[currentSportKey()]||DATA.competition||'fixtures';
  const totals=scorecardTotals();
  const cells=[[upcoming.length,`${sportLabel} games next 7 days`]];
  if(totals.picks)cells.push([totals.picks,'picks graded in public']);
  else if(totals.lockMinutes)cells.push([`${totals.lockMinutes} min`,'locked before kickoff']);
  else cells.push([ALL_SPORT_KEYS.length,'sports covered']);
  host.innerHTML=cells.map(([v,l])=>`<div><b>${esc(v)}</b><span>${esc(l)}</span></div>`).join('');
}
// The gate used to state in hand-written copy that published picks were paused.
// That sentence outlived the pause: the flag went back to false, every fixture
// on the board carried a model read again, and the front door still told first
// -time visitors there were no forecasts. Render it from the flag instead, so
// it cannot describe a state the site is not in.
// The week's upset call, from the same handoff as everything else. The engine
// attaches a caveat to this one that the board already honours and the gate has
// to as well: disagreement of this kind has predicted WORSE results on its
// graded college samples, and it is to be published as something to watch and
// graded afterwards, never as a recommended bet. So it is labelled UPSET WATCH,
// it says what it is in a line underneath, and it never borrows the word "pick"
// from the locked read above it.
// "Won 24–17" / "Lost 10–31" with the selection's score first, "result
// pending" once kicked off without one, otherwise the countdown.
function upsetStatusText(p,selectionIsAway){
  if(!p)return'';
  const hs=Number(p.home_score),as=Number(p.away_score);
  if((p.result==='won'||p.result==='lost')&&p.home_score!=null&&p.away_score!=null&&Number.isFinite(hs)&&Number.isFinite(as)){
    const mine=selectionIsAway?as:hs,theirs=selectionIsAway?hs:as;
    return `${p.result==='won'?'Won':'Lost'} ${mine}–${theirs}`;
  }
  if(!p.kickoff)return'';
  return Date.parse(p.kickoff)<=Date.now()?'result pending':kickIn(p.kickoff);
}
function renderWelcomeUpset(){
  const host=$('#welcomeUpset');if(!host)return;
  const u=(typeof MATCHDAY_BETBETTER_UPSET!=='undefined')?MATCHDAY_BETBETTER_UPSET:null;
  const p=u&&u.available?u.pick:null;
  const sport=(typeof currentSportKey==='function'?currentSportKey():'')||'';
  // Scoped to the board being shown: an NCAAF upset above an NCAAM board would
  // be a call about a sport the visitor is not looking at.
  if(!p||(sport&&String(p.sport||'').toLowerCase()!==sport)){host.hidden=true;host.innerHTML='';return}
  const model=Number(p.model_pct),market=Number(p.market_pct),gap=Number(p.disagreement_points);
  if(!Number.isFinite(model)){host.hidden=true;host.innerHTML='';return}
  const bar=(cls,label,v)=>`<div class="${cls}"><span>${label}</span><i style="width:${Math.max(2,Math.min(100,v))}%"></i><b>${Number.isFinite(v)?(label==='model'?modelPctLabel(v):v.toFixed(1)+'%'):'—'}</b></div>`;
  host.hidden=false;
  // Name the opponent, not the fixture: the selection is already the headline,
  // so "Iowa State Cyclones / Iowa State Cyclones at Iowa Hawkeyes" said it twice.
  const norm=v=>String(v||'').toLowerCase();
  const sel=norm(p.selection);
  const opponent=sel&&norm(p.home)===sel?p.away:(sel&&norm(p.away)===sel?p.home:`${p.away||''} at ${p.home||''}`);
  const away=sel&&norm(p.away)===sel;
  // The week's recorded call stays up after kickoff, so a countdown would read
  // "now" all Saturday night. Past kickoff it shows the result, or that one is
  // still to come.
  const when=upsetStatusText(p,away);
  // The strip shows the biggest call; the board card lists the rest.
  const others=Math.max(0,(u.picks||[]).length-1);
  host.innerHTML=`<div class="wuTop"><span>UPSET WATCH${others?` · +${others} more on the board`:''}</span>${Number.isFinite(gap)?`<em class="wuGap">+${gap.toFixed(1)} pts clear of the market</em>`:'<em>up to 3 calls a week</em>'}</div>`
    +`<div class="wuPick"><b>${esc(p.selection||'')}</b><span>${away?'at':'vs'} ${esc(opponent)}${when?` · ${esc(when)}`:''}</span></div>`
    +`<div class="wuBars">${bar('','model',model)}${Number.isFinite(market)?bar('mkt','market',market):''}</div>`
    +`<p class="wuNote">The model's biggest contrarian call of the week — to watch and grade, not a recommended bet.</p>`;
}
// The record line under THE RECORD, summed from the scorecard's own graded
// totals. Absent data hides it -- the gate never states a number it cannot source.
function renderWelcomeRecord(){
  const host=$('#welcomeRecord');if(!host)return;
  const all=(typeof MATCHDAY_BETBETTER_SCORECARD!=='undefined')?MATCHDAY_BETBETTER_SCORECARD:null;
  const sports=Object.values(all?.sports||{}).filter(s=>s?.available);
  const w=sports.reduce((n,s)=>n+(Number(s.record?.wins)||0),0),l=sports.reduce((n,s)=>n+(Number(s.record?.losses)||0),0);
  if(!(w+l)){host.hidden=true;host.innerHTML='';return}
  host.hidden=false;
  host.innerHTML=`<b>${w}–${l}</b><span>${(100*w/(w+l)).toFixed(1)}% of graded picks correct</span>`;
}
function renderWelcomeStatusNote(){
  const host=$('#welcomeStatusNote');if(!host)return;
  const totals=scorecardTotals();
  host.innerHTML=`<p>The site covers college football and men's college basketball only. Fixtures on the
      board carry a model probability alongside the market's own number where one is priced${totals.lockMinutes?`, locked ${totals.lockMinutes} minutes before kickoff`:''}${totals.picks?` — ${totals.picks} of them have been graded against the result so far`:''}.</p>`;
}
// Slight parallax on the preview card. Pointer-only and opt-out aware, so it
// never interferes with touch scrolling or reduced-motion preferences.
function bindWelcomeTilt(){
  const card=document.querySelector('.welcomePreview');
  if(!card||card.dataset.tiltBound||prefersReducedMotion())return;
  if(!window.matchMedia?.('(hover:hover) and (pointer:fine)').matches)return;
  card.dataset.tiltBound='1';
  const reset=()=>{card.style.transform=''};
  card.addEventListener('pointermove',e=>{
    const r=card.getBoundingClientRect();
    const dx=(e.clientX-r.left)/r.width-0.5,dy=(e.clientY-r.top)/r.height-0.5;
    card.style.transform=`perspective(900px) rotateY(${dx*5.5}deg) rotateX(${-dy*5.5}deg) translateZ(6px)`;
  });
  card.addEventListener('pointerleave',reset);
  card.addEventListener('blur',reset,true);
}
function renderWelcome(){
  const gate=$('#welcomeGate');if(!gate)return;
  const dismissed=welcomeDismissed();gate.hidden=dismissed;document.body.classList.toggle('welcomeOpen',!dismissed);if(dismissed){runCarousel('welcome',null);return}
  renderWelcomeStats();renderWelcomeStatusNote();renderWelcomeUpset();renderWelcomeRecord();bindWelcomeTilt();
  // The card only ever shows a fixture the engine has priced. It is a model
  // read, so a game without one has nothing to say here -- an out-of-season
  // board (nothing 55 days out is priced) gets the standing panel below rather
  // than a fixture with an empty number beside it.
  const priced=(DATA.matches||[]).filter(m=>isVisibleUpcoming(m)&&(typeof betbetterReadFor==='function'&&betbetterReadFor(m)));
  const soonest=[...priced].sort(fixtureSort)[0],host=$('#welcomeNext');
  if(!host)return;
  if(!soonest){
    host.innerHTML=`<div class="welcomeFallback"><span class="welcomeFallbackKicker">BOARD READY</span><strong>Model reads appear as games are priced.</strong><p>Nothing on this board is priced yet. The scorecard, ratings and every graded pick are inside.</p><div aria-hidden="true"><i></i><i></i><i></i></div></div>`;
    const state=$('#welcomeFeedState');if(state)state.textContent='ANALYSIS';
    return;
  }
  // Soonest kickoff leads, then a small near-term pool behind it.
  const featured=nearTermPool(priced.filter(m=>m.id!==soonest.id),4)
    .sort((a,b)=>(b.watchability||0)-(a.watchability||0)).slice(0,4);
  const pool=[soonest,...featured];
  host.innerHTML=_welcomeCardHTML(soonest);
  runCarousel('welcome',pool,host,_welcomeCardHTML,4500);
  const state=$('#welcomeFeedState');if(state)state.textContent='PREGAME';
}
function landingHero(){
  // The engine's graded record, not the hand-typed block this used to read.
  const sc=typeof betbetterScorecard==='function'?betbetterScorecard():null;
  const gradedPicks=Number(sc?.record?.picks)||0;
  const slim=heroSeen();
  // What leads here is the property that is true regardless of how the model is
  // performing this month: the pick was published before kickoff and graded from
  // the record afterward. A bare W-L and a raw Brier score led instead, and both
  // mislead a first-time reader — a 139-129 record reads as a coin flip, and a
  // Brier score is unreadable without knowing that lower is better and that 0.25
  // is the do-nothing baseline. The full numbers, favourable or not, stay one
  // click away on the Scorecard, which has the room to give them context.
  // Both halves live in one baseline-aligned group: the count is set larger than
  // the words around it, so centring the two spans as separate flex items lined
  // up their boxes and left the second line's text visibly riding high.
  const rec=`<span class="heroRecLine">${gradedPicks?`<span class="heroRec"><b>${gradedPicks}</b> picks locked pregame and graded</span><span class="heroRec faintline">never edited after the result</span>`:`<span class="heroRec faintline">Model record begins as completed picks are graded</span>`}</span>`;
  if(slim)return `<div class="heroSlim">${rec}<button class="heroSlimLink" type="button" onclick="setView('score')">Open scorecard <span aria-hidden="true">→</span></button></div>`;
  return `<div class="heroBand">
    <img src="icon-192.png?v=4" class="heroLogo" alt="Matchday" width="192" height="192">
    <div class="heroTitle">Every pick, on the record.</div>
    <div class="heroSub">Locked before kickoff, graded after the final whistle, never edited in between. Free, and no ads.</div>
    <div class="heroRow">${rec}</div>
    <div class="heroActions">
      <button class="btmbtn heroBtn" onclick="heroDismiss()">Open the analysis</button>
      <button class="btmbtn heroBtn ghost" onclick="heroDismiss();setView('community')">Play against the model</button>
    </div>
  </div>`;
}
function enhanceMatchCards(host){
  host.querySelectorAll('.card .head').forEach(head=>{
    const card=head.closest('.card'),m=BYID[card?.dataset.id];
    if(isFavoriteMatch(m)){card.classList.add('favoriteMatch');if(!head.querySelector('.favoriteTag'))head.insertAdjacentHTML('beforeend',`<span class="favoriteTag">${t('My team')}</span>`)}
    head.setAttribute('role','button');head.setAttribute('tabindex','0');
    if(m)head.setAttribute('aria-label',`Open ${m.home?.name||'home'} versus ${m.away?.name||'away'}`);
    // This used to relabel the card's first `.pick` row as "Model" and rewrite
    // its note with `m.prediction`'s market and edge. Once a card carried both
    // prediction systems, the first row was the Bet Better pick, so the site
    // model's label and market numbers were stamped onto a different model's
    // pick -- which is how "MODEL Florida State 60.4%" came to sit above
    // "PICK SMU 53%". cardHTML now renders one pick row that labels and
    // annotates itself from its own source, so there is nothing to restate.
    const setFinishedLabel=()=>{if(m?.status!=='FINISHED')return;const status=document.querySelector('.matchModal.show .modalStatus');if(status)status.textContent='FT'};
    if(m?.status==='FINISHED'){const when=card.querySelector('.center>.kick');if(when)when.textContent='FT';head.addEventListener('click',setFinishedLabel)}
    head.addEventListener('keydown',event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();openMatchModal(card.dataset.id);setFinishedLabel()}});
  });
}
// A fixture's own kickoff says nothing about whether the schedule around it is
// busy: between seasons, the nearest game can be months out. Widen the window
// in steps until enough candidates exist, so the welcome card and the in-focus
// rail feature this week's games when there are any and fall back gracefully
// when there are not.
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
// The merged "All college" board is gone, and with it the cross-sport marquee:
// watchability ranking, the per-competition round-robin and the widening
// near-term window all existed to stop one sport filling a shared strip. A
// single sport's board shows that sport's own schedule in kickoff order,
// grouped by horizon below.
// A schedule can reach months ahead, and a game 62 days out looked exactly like
// one tomorrow, leaving the whole board reading as stale. Group by horizon so a
// quiet week is legible as a quiet week.
// One heading per calendar day, in the visitor's own time zone, after
// anything in play. The old horizons ("Today", "This week", "Further ahead")
// put Thursday night and Saturday noon under one label, so a week's slate read
// as one long list. Order inside a day is the order handed in (favourites
// pinned, then kickoff).
function boardDayKey(ms){const d=new Date(ms);return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`}
function boardDayLabel(key,now){
  const [y,mo,d]=key.split('-').map(Number),day=new Date(y,mo-1,d);
  const today=new Date(now);today.setHours(0,0,0,0);
  const diff=Math.round((day-today)/86400000);
  const date=day.toLocaleDateString(undefined,{month:'short',day:'numeric'});
  const weekday=day.toLocaleDateString(undefined,{weekday:'long'});
  if(diff===0)return `Today · ${weekday}, ${date}`;
  if(diff===1)return `Tomorrow · ${weekday}, ${date}`;
  return `${weekday} · ${date}`;
}
function groupedBoardHTML(list){
  const now=Date.now(),buckets=new Map();
  list.forEach(m=>{
    const ms=kickMs(m);
    // An unannounced kickoff belongs to its Eastern calendar date, and sits
    // after that day's timed games.
    const key=m.status==='LIVE'?'0-live':(ms?'1-'+(kickoffTimeTbd(m)?easternDayKey(ms):boardDayKey(ms)):'2-tbd');
    if(!buckets.has(key))buckets.set(key,[]);
    buckets.get(key).push(m);
  });
  buckets.forEach(games=>games.sort((a,b)=>Number(kickoffTimeTbd(a))-Number(kickoffTimeTbd(b))));
  return [...buckets.keys()].sort().map(key=>{
    const games=buckets.get(key);
    const label=key==='0-live'?'In play':key==='2-tbd'?'Date to be announced':boardDayLabel(key.slice(2),now);
    return `<div class="boardHorizon"><span>${esc(label)}</span><i>${games.length} ${games.length===1?'game':'games'}</i></div>`+games.map(cardHTML).join('');
  }).join('');
}

// The games-first summary deliberately reads the same Bet Better handoff as
// the fixture card and expanded view. Do not fill its gaps from m.prediction:
// that is a different forecast system and previously produced contradictory
// picks on the same fixture.
function gamesBoardRead(m){
  const read=typeof betbetterReadFor==='function'?betbetterReadFor(m):null;
  if(!read)return null;
  const number=v=>v==null||v===''?null:(Number.isFinite(Number(v))?Number(v):null);
  const model=number(read.model_pct),market=number(read.market_pct);
  if(!read.pick_name||model==null)return null;
  const supplied=number(read.edge_points);
  return {match:m,pick:read.pick_name,model,market,
    difference:market==null?null:(supplied==null?model-market:supplied)};
}
function featuredMatchupRead(reads){
  // Bet Better's game of the week is selected for two strong, closely rated
  // teams, not for the largest edge or simply the earliest kickoff.
  const game=(typeof MATCHDAY_BETBETTER_GAME_OF_THE_WEEK!=='undefined'
    &&MATCHDAY_BETBETTER_GAME_OF_THE_WEEK.available)?MATCHDAY_BETBETTER_GAME_OF_THE_WEEK.game:null;
  if(!game)return null;
  return reads.find(read=>{
    const m=read.match;
    if(String(m.kickoff||'').slice(0,10)!==String(game.kickoff||'').slice(0,10))return false;
    return (bbNameMatches(m.home?.name,game.home?.team)&&bbNameMatches(m.away?.name,game.away?.team))
      ||(bbNameMatches(m.home?.name,game.away?.team)&&bbNameMatches(m.away?.name,game.home?.team));
  })||null;
}
const TEAM_LOGO_FILES={
  'Texas Longhorns':'texas.png','Georgia Bulldogs':'georgia.png','Miami Hurricanes':'miami.png','Ole Miss Rebels':'oleMiss.png','Ohio State Buckeyes':'ohioState.png','Notre Dame Fighting Irish':'notreDame.png','Indiana Hoosiers':'indiana.png','Alabama Crimson Tide':'alabama.png','BYU Cougars':'byu.png','USC Trojans':'usc.png','Texas Tech Red Raiders':'texasTech.png','LSU Tigers':'lsu.png','Utah Utes':'utah.png','Louisville Cardinals':'louisville.png','Iowa Hawkeyes':'iowa.png','Penn State Nittany Lions':'pennState.png','Tennessee Volunteers':'tennessee.png','Florida Gators':'florida.png','Missouri Tigers':'missouri.png','Mississippi State Bulldogs':'mississippiState.png','Kentucky Wildcats':'kentucky.png','Houston Cougars':'houston.png','SMU Mustangs':'smu.png','Michigan Wolverines':'michigan.png','Duke Blue Devils':'duke.png','Coastal Carolina Chanticleers':'coastalCarolina.png','Liberty Flames':'liberty.png'
};
Object.assign(TEAM_LOGO_FILES,{
  Texas:'texas.png',Georgia:'georgia.png',Miami:'miami.png','Ole Miss':'oleMiss.png','Ohio State':'ohioState.png','Notre Dame':'notreDame.png',Indiana:'indiana.png',Alabama:'alabama.png',BYU:'byu.png',USC:'usc.png','Texas Tech':'texasTech.png',LSU:'lsu.png',Utah:'utah.png',Louisville:'louisville.png',Iowa:'iowa.png','Penn State':'pennState.png',Tennessee:'tennessee.png',Florida:'florida.png',Missouri:'missouri.png','Mississippi State':'mississippiState.png',Kentucky:'kentucky.png',Houston:'houston.png',SMU:'smu.png',Michigan:'michigan.png',Duke:'duke.png','Coastal Carolina':'coastalCarolina.png',Liberty:'liberty.png',
  Louisiana:'louisianaLafayette.png','UL Monroe':'louisianaMonroe.png','Louisiana Tech':'LouisianaTech.png',
  'Miami (OH)':'miamiOH.png',UConn:'connecticut.png','NC State':'ncState.png',
  'App State':'appalachianState.png','Southern Miss':'southernMississippi.png',FIU:'floridaIntl.png',
  FAU:'floridaAtlantic.png',NIU:'northernIllinois.png',UTSA:'texasSanAntonio.png',
  'Sam Houston':'samHoustonState.png','UT Martin':'tennesseeMartin.png',McNeese:'mcNeeseState.png',
  'Boston College':'boston.png','East Tennessee State':'eastTennessee.png','Florida A&M':'floridaAM.png',
  'Florida International':'floridaIntl.png','Houston Christian':'houstonBaptist.png',Nicholls:'nichollsState.png',
  'North Carolina A&T':'northCarolinaAT.png','San José State':'sanJoseState.png','SE Louisiana':'southeasternLouisiana.png',
  'Texas A&M':'texasAM.png','The Citadel':'citadel.png',UAlbany:'albany.png',
  'Michigan State':'michiganState.png','Michigan State Spartans':'michiganState.png',
  'Florida Atlantic':'floridaAtlantic.png','Florida Atlantic Owls':'floridaAtlantic.png',
  'Georgia Southern':'georgiaSouthern.png','Georgia Southern Eagles':'georgiaSouthern.png',
  'Georgia State':'georgiaState.png','Georgia State Panthers':'georgiaState.png',
  TCU:'TCU.png',"Hawai'i":'hawaii.png','Oklahoma State':'OklahomaState.png',
  Pennsylvania:'penn.png',Grambling:'gramblingState.png',Presbyterian:'presbyterianCollege.png','William & Mary':'williamMary.png'
});
const _INFERRED_LOGO_CACHE=new Map();
function inferredTeamLogoFile(name){
  const label=String(name||'');
  const hit=_INFERRED_LOGO_CACHE.get(label);
  if(hit!==undefined)return hit;
  const words=label.replace(/&/g,' and ').replace(/[^A-Za-z0-9]+/g,' ').trim().split(/\s+/).filter(Boolean);
  const file=words.length?words.map((word,i)=>i?word[0].toUpperCase()+word.slice(1):word.toLowerCase()).join('')+'.png':'';
  _INFERRED_LOGO_CACHE.set(label,file);
  return file;
}
// Hoisted out of the function: these never change, and rebuilding the set and
// the entry list on every call made the fixture merge quadratic in wall time.
const _DISTINCT_SCHOOL_WORD=new Set(['state','tech','university','college','international','christian','baptist','a&m','a']);
const _safeLogoSuffix=remaining=>!_DISTINCT_SCHOOL_WORD.has(String(remaining||'').toLowerCase());
// Longest school name first, so the prefix search can keep its ordering without
// re-sorting the table on every lookup.
const _TEAM_LOGO_ENTRIES=Object.entries(TEAM_LOGO_FILES).sort((a,b)=>b[0].length-a[0].length);
// The snapshot merge asks for the same few hundred schools millions of times.
// The computed list is kept and handed out as a copy, because callers such as
// teamMark() shift entries off the array they are given.
const _LOGO_CANDIDATE_CACHE=new Map();
function teamLogoCandidates(name){
  const label=String(name||'').trim();
  let candidates=_LOGO_CANDIDATE_CACHE.get(label);
  if(candidates===undefined){
    const words=label.replace(/&/g,' and ').replace(/[^A-Za-z0-9]+/g,' ').trim().split(/\s+/).filter(Boolean);
    const exact=TEAM_LOGO_FILES[label];
    // Every candidate is a school name the label starts with, tried longest
    // first whether it comes from the mapped table or from the words: "Utah
    // Valley" must be tried before a mapped "Utah", or Utah Valley wears the
    // Utes' mark (likewise Florida Gulf Coast, Texas A&M-Corpus Christi). A
    // mapped name wins a tie, because the map exists to correct inference.
    const ranked=[];
    for(let end=words.length;end>0;end--)if(_safeLogoSuffix(words[end]))ranked.push([words.slice(0,end).join(' ').length,1,inferredTeamLogoFile(words.slice(0,end).join(' '))]);
    for(const [school,file] of _TEAM_LOGO_ENTRIES){
      if(label.startsWith(school+' ')&&_safeLogoSuffix(label.slice(school.length).trim().split(/\s+/)[0]))ranked.push([school.length,0,file]);
    }
    ranked.sort((a,b)=>(b[0]-a[0])||(a[1]-b[1]));
    candidates=[...new Set([exact,...ranked.map(r=>r[2])].filter(Boolean))];
    _LOGO_CANDIDATE_CACHE.set(label,candidates);
  }
  return candidates.slice();
}
// The fixture merge only ever wants the first candidate, and copying the array
// for each of a few million comparisons is itself most of the cost.
function primaryTeamLogo(name){
  const label=String(name||'').trim();
  let candidates=_LOGO_CANDIDATE_CACHE.get(label);
  if(candidates===undefined){teamLogoCandidates(label);candidates=_LOGO_CANDIDATE_CACHE.get(label)}
  return candidates[0];
}
function teamLogoFallback(img){
  const remaining=String(img.dataset.logoFallback||'').split('|').filter(Boolean);
  if(remaining.length){img.dataset.logoFallback=remaining.slice(1).join('|');img.src='team-logos/'+remaining[0];return}
  img.hidden=true;img.nextElementSibling.hidden=false;
}
function teamMark(name,extra=''){
  const candidates=teamLogoCandidates(name),file=candidates.shift()||'';
  const letters=String(name||'').split(/\s+/).filter(Boolean).slice(0,2).map(w=>w[0]).join('').toUpperCase()||'?';
  return `<span class="teamMark ${esc(extra)}"><img src="team-logos/${esc(file)}" data-logo-fallback="${esc(candidates.join('|'))}" alt="" width="32" height="32" loading="lazy" onerror="teamLogoFallback(this)"><span class="teamMonogramText" hidden aria-hidden="true">${esc(letters)}</span></span>`;
}
function gamesSummaryHTML(active){
  const sport=SPORT_LABELS[currentSportKey()]||DATA.competition||'College sports';
  const weekEnd=Date.now()+7*86400000;
  const week=active.filter(m=>m.status==='LIVE'||(kickMs(m)&&kickMs(m)<=weekEnd));
  const reads=week.map(gamesBoardRead).filter(Boolean);
  const comparable=reads.filter(r=>r.market!=null&&r.difference!=null);
  const featured=featuredMatchupRead(reads)
    ||[...comparable].sort((a,b)=>fixtureSort(a.match,b.match))[0]
    ||[...reads].sort((a,b)=>fixtureSort(a.match,b.match))[0]
    ||(week[0]&&{match:week[0],pick:'',model:null,market:null,difference:null});
  const top=[...comparable].sort((a,b)=>Math.abs(b.difference)-Math.abs(a.difference)||fixtureSort(a.match,b.match)).slice(0,4);
  const feature=featured?gamesFeaturedHTML(featured):`<div class="gamesEmpty">No games in the next seven days. The full schedule remains below.</div>`;
  return `<section class="gamesLandingHead"><span>GAMES</span><h1>${esc(sport)}</h1><p>Predictions, market comparisons and the public record.</p></section>`
    +`<section class="gamesFeatured"><div class="gamesSectionHead"><span>This week's featured game</span><small>${featured?.model!=null?'Live model':'Next 7 days'}</small></div>${feature}</section>`
    +`<div class="gamesSupportGrid${top.length?'':' noComparisons'}">${top.length?gamesDifferencesHTML(top):''}<div class="gamesSideCol">${gamesRecordHTML()}${gamesBracketHTML()}</div></div>`
    +`<nav class="gamesExplore" aria-label="Explore Matchday"><span>Explore</span><div><button type="button" onclick="setView('matches')"><b>Games</b><small>Fixtures and matchups</small></button><button type="button" onclick="setView('groups')"><b>Rankings</b><small>Ratings and conferences</small></button><button type="button" onclick="setView('news')"><b>Research</b><small>Analysis and methodology</small></button><button type="button" onclick="setView('results')"><b>Results</b><small>Finals and grading</small></button></div></nav>`;
}
function renderHome(){
  const host=$('#view-home'),active=(DATA.matches||[]).filter(m=>!isCompleteOrPast(m)).sort(favoriteFixtureSort);
  const weekEnd=Date.now()+7*86400000,week=active.filter(m=>m.status==='LIVE'||(kickMs(m)&&kickMs(m)<=weekEnd));
  const reads=week.map(gamesBoardRead).filter(Boolean),priced=reads.filter(r=>r.market!=null&&r.difference!=null);
  const edges=priced.filter(r=>Math.abs(r.difference)>=5).length;
  const sc=typeof betbetterScorecard==='function'?betbetterScorecard():null;
  host.innerHTML=`<section class="homeIntro"><span>MATCHDAY TERMINAL</span><h1>College sports predictions &amp; research</h1><p>What matters now, before you choose where to go deeper.</p></section>`
    +`<section class="homeKpis" aria-label="This week's overview"><div><strong>${week.length}</strong><span>Games this week</span></div><div><strong>${priced.length?edges:'—'}</strong><span>${priced.length?'Model / market gaps':'Edges awaiting market'}</span></div><div><strong>${Number(sc?.record?.picks)||0}</strong><span>Picks graded</span></div></section>`
    +gamesSummaryHTML(active);
}
function gamesFeaturedHTML(read){
  const m=read.match;
  const comparison=read.market==null
    ?`<div><span>Market</span><b>No snapshot yet</b></div><div><span>Difference</span><b>Not available</b></div>`
    :`<div><span>Market</span><b>${read.market.toFixed(1)}%</b></div><div><span>Difference</span><b class="${read.difference>0?'up':read.difference<0?'down':''}">${read.difference>0?'+':''}${read.difference.toFixed(1)} pts</b></div>`;
  const model=read.model==null
    ?`<div><span>Live model</span><b>No prediction yet</b></div>`
    :`<div><span>Live model · ${esc(read.pick)}</span><b>${modelPctLabel(read.model)}</b></div>`;
  return `<button type="button" class="gamesFeaturedButton" onclick="openMatchModal('${esc(String(m.id))}')"><span class="gamesFeaturedWhen">${esc(m.stage||'Fixture')} · ${esc(kickIn(m.kickoff))}</span><strong><span class="gamesFeaturedTeam">${teamMark(m.home?.name)}<span>${esc(m.home?.name||'Home')}</span></span><i>vs</i><span class="gamesFeaturedTeam away">${teamMark(m.away?.name)}<span>${esc(m.away?.name||'Away')}</span></span></strong><div class="gamesFeaturedCompare">${model}${comparison}</div><em>View analysis <span aria-hidden="true">→</span></em></button>`;
}
function gamesDifferencesHTML(reads){
  const rows=reads.length?reads.map(read=>{
    const m=read.match,d=read.difference;
    const content=`<span><b>${esc(m.home?.name||'Home')} vs ${esc(m.away?.name||'Away')}</b><small>${esc(read.pick)} · model ${modelPctLabel(read.model)} · market ${read.market.toFixed(1)}%</small></span><strong class="${d>0?'up':d<0?'down':''}">${d>0?'+':''}${d.toFixed(1)} pts</strong>`;
    return `<button type="button" onclick="openMatchModal('${esc(String(m.id))}')">${content}</button>`;
  }).join(''):`<div class="gamesEmpty">Model and market comparisons will appear as games are priced.</div>`;
  return `<section class="gamesDifferences"><div class="gamesSectionHead"><span>Largest model / market differences</span><small>${reads.length?'Top '+reads.length:'Awaiting prices'}</small></div><div class="gamesDifferenceRows">${rows}</div><button type="button" class="gamesTextLink" onclick="document.querySelector('.gamesFixtureBoard')?.scrollIntoView({behavior:prefersReducedMotion()?'auto':'smooth'})">View all games <span aria-hidden="true">→</span></button></section>`;
}
/* The projected playoff field's top four seeds, from the same bracket data
   the Bracket tab draws, as a way into that tab from the home page. */
function gamesBracketHTML(){
  if(String(DATA?.comp_key||'').toUpperCase()!=='NCAAF')return '';
  const rounds=(typeof MATCHDAY_CFB_AP_BRACKET!=='undefined'&&MATCHDAY_CFB_AP_BRACKET)||[];
  const byes=(rounds.find(r=>/quarter/i.test(r.round||''))?.matches||[])
    .filter(m=>/^[1-4]$/.test(String(m.home_slot||''))).sort((a,b)=>Number(a.home_slot)-Number(b.home_slot));
  if(!byes.length)return '';
  const short=n=>typeof rsShortName==='function'?rsShortName(n):n;
  return `<section class="gamesRecord gamesBracket"><div><span>Playoff picture</span>`
    +`<ol class="gamesSeeds">${byes.map(m=>`<li><em>${esc(m.home_slot)}</em>${typeof teamMark==='function'?teamMark(m.home):''}<b>${esc(short(m.home))}</b></li>`).join('')}</ol></div>`
    +`<button type="button" onclick="setView('bracket')">View bracket <span aria-hidden="true">→</span></button></section>`;
}
function gamesRecordHTML(){
  const sc=typeof betbetterScorecard==='function'?betbetterScorecard():null;
  const r=sc?.record;
  if(!sc?.available||!r?.picks)return `<section class="gamesRecord"><div><span>Public record</span><strong>Record begins after picks are graded.</strong></div><button type="button" onclick="setView('score')">View Scorecard <span aria-hidden="true">→</span></button></section>`;
  const expected=Number(r.expected_hit_rate_pct),actual=Number(r.hit_rate_pct),gap=Number(r.calibration_gap_points);
  return `<section class="gamesRecord"><div><span>Public record</span><strong>${Number(r.wins)||0}–${Number(r.losses)||0}</strong><p>${r.picks} locked pregame picks · ${Number.isFinite(actual)?`${actual.toFixed(1)}% hit rate`:''}${Number.isFinite(expected)?` vs ${expected.toFixed(1)}% expected`:''}${Number.isFinite(gap)?` · ${gap>0?'+':''}${gap.toFixed(1)} calibration pts`:''}</p></div><button type="button" onclick="setView('score')">View Scorecard <span aria-hidden="true">→</span></button></section>`;
}
/* Games-board filters. Kind is one of all / top25 / ranked (both teams in the
   poll) / conf (same-conference game) / nonconf; conf narrows to one league.
   Poll rank is the published poll (AP for football, the ranking table's top
   25 for basketball) -- the same source the upset module reads. */
let GAME_FILTER={kind:'all',conf:''},GAME_TEAM_CACHE=new Map();
// Per-render memo: every chip count re-filters the whole schedule.
function gameTeamMemo(kind,name,fn){const k=kind+'|'+name;if(!GAME_TEAM_CACHE.has(k))GAME_TEAM_CACHE.set(k,fn());return GAME_TEAM_CACHE.get(k)}
function gamePollRank(name){return gameTeamMemo('rank',name,()=>gamePollRankUncached(name))}
function gamePollRankUncached(name){
  const poll=currentSportKey()==='ncaaf'
    ?(typeof MATCHDAY_CFB_AP_POLL!=='undefined'?MATCHDAY_CFB_AP_POLL.rankings||[]:[])
    :(typeof MATCHDAY_NCAAM_AP_POLL!=='undefined'&&MATCHDAY_NCAAM_AP_POLL.is_final===false&&MATCHDAY_NCAAM_AP_POLL.rankings?.length===25)
      // Last season's final poll says nothing about this season's games.
      ?MATCHDAY_NCAAM_AP_POLL.rankings
      :(typeof collegeRankingTable==='function'?(collegeRankingTable()?.top25||collegeRankingTable()?.rankings||[]):[]);
  const r=Number(poll.find(r=>bbNameMatches(r.name||r.team_name,name))?.rank);
  return Number.isFinite(r)&&r<=25?r:null;
}
// Live fixtures carry no conference; the power-rating table does.
function gameConference(side){
  if(side?.group)return side.group;
  return gameTeamMemo('conf',side?.name,()=>{
  const rows=typeof collegeRankingTable==='function'?(collegeRankingTable()?.rankings||[]):[];
  return rows.find(r=>bbNameMatches(r.name,side?.name))?.conference||'';
  });
}
function gameMatchesFilter(m,f){
  const hc=gameConference(m.home),ac=gameConference(m.away);
  if(f.conf&&hc!==f.conf&&ac!==f.conf)return false;
  const hr=gamePollRank(m.home?.name),ar=gamePollRank(m.away?.name);
  if(f.kind==='top25')return hr!=null||ar!=null;
  if(f.kind==='ranked')return hr!=null&&ar!=null;
  if(f.kind==='conf')return !!hc&&hc===ac;
  if(f.kind==='nonconf')return !!hc&&!!ac&&hc!==ac;
  return true;
}
function setGameFilter(patch){GAME_FILTER={...GAME_FILTER,...patch};MATCH_VISIBLE=FIXTURE_PAGE_SIZE;renderMatches()}
function gameFilterBarHTML(active){
  const confs=[...new Set(active.flatMap(m=>[gameConference(m.home),gameConference(m.away)]).filter(Boolean))].sort();
  if(GAME_FILTER.conf&&!confs.includes(GAME_FILTER.conf))GAME_FILTER.conf='';
  const kinds=[['all','All games'],['top25','Top 25'],['ranked','Ranked vs ranked'],['conf','Conference games'],['nonconf','Non-conference']];
  const chips=kinds.map(([k,label])=>{
    const n=active.filter(m=>gameMatchesFilter(m,{...GAME_FILTER,kind:k})).length;
    const on=GAME_FILTER.kind===k;
    return `<button type="button" class="chip ${on?'on':''}" aria-pressed="${on}" onclick="setGameFilter({kind:'${k}'})">${label}<span class="count">${n}</span></button>`;
  }).join('');
  const select=confs.length?`<label class="gameConfPick"><span>Conference</span><select onchange="setGameFilter({conf:this.value})"><option value="">All conferences</option>${confs.map(c=>`<option value="${esc(c)}" ${c===GAME_FILTER.conf?'selected':''}>${esc(c)}</option>`).join('')}</select></label>`:'';
  return `<div class="modelToolbar gameFilters" role="group" aria-label="Filter games">${chips}${select}</div>`;
}
function renderMatches(){const M=DATA.matches||[];
  // One sport's full schedule, in kickoff order with favorites pinned. The
  // horizon headings below (In play / Today / This week) do the work the old
  // merged board needed a watchability ranking for: a long schedule stays
  // readable because it is grouped by when it happens, not trimmed.
  GAME_TEAM_CACHE=new Map();
  const all=M.filter(m=>!isCompleteOrPast(m)).sort(favoriteFixtureSort);
  const filterBar=gameFilterBarHTML(all);
  const active=all.filter(m=>gameMatchesFilter(m,GAME_FILTER));
  const filtered=GAME_FILTER.kind!=='all'||!!GAME_FILTER.conf;
  const shown=active.slice(0,MATCH_VISIBLE),remaining=Math.max(0,active.length-shown.length);
  const missing=DATA._missing?`<div class="banner" style="grid-column:1/-1"><b>No ${esc(DATA.competition||'this sport')} data yet.</b> Fetch it once its season is available — run the matching start file (e.g. start_ucl.bat) or keep an eye out when the season begins.</div>`:'';
  const intro=`<div class="viewIntro gamesFixtureBoard"><div><div class="vhead">Games</div><p>This week comes first. Open any matchup for the full model, market and team analysis.</p></div><span>${filtered?`${active.length} of ${all.length}`:active.length} games</span></div>`;
  const empty=filtered&&all.length
    ?`<div class="empty" style="grid-column:1/-1">No upcoming games match these filters. <button type="button" class="actionbtn" onclick="setGameFilter({kind:'all',conf:''})">Clear filters</button></div>`
    :`<div class="empty" style="grid-column:1/-1">No upcoming matches to analyze.</div>`;
  const html=missing+intro+(all.length?filterBar:'')+
    (shown.length?groupedBoardHTML(shown):empty)+
    (remaining?`<div class="fixturePager"><span>Showing ${shown.length} of ${active.length} fixtures</span><button class="actionbtn" onclick="MATCH_VISIBLE+=FIXTURE_PAGE_SIZE;renderMatches()">Load ${Math.min(FIXTURE_PAGE_SIZE,remaining)} more</button></div>`:'');
  $('#view-matches').innerHTML=html;enhanceMatchCards($('#view-matches'));
  // Notes go behind each card's ? first, so the power rating card is trimmed
  // against the cards' real, shorter heights.
  if(typeof collapseBoardNotes==='function')collapseBoardNotes($('#view-matches'));
  if(typeof fitRankingCard==='function')fitRankingCard();
  if(typeof balanceBoardMods==='function')balanceBoardMods();}
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
/* A feed that carries only a poll (basketball's AP Top 25) still needs its
   conference tables derived from the schedule; the poll goes in front. */
function deriveStandings(){const given=Array.isArray(DATA.standings)?DATA.standings:[],polls=typeof isPollTable==='function'?given.filter(isPollTable):[];if(given.length>polls.length)return given;return polls.concat(_deriveStandingsFromMatches())}
function _deriveStandingsFromMatches(){const rows={},M=DATA.matches||[];M.forEach(m=>{const g=cleanGroup(m.home?.group||m.away?.group||(/^Group/i.test(m.stage||'')?m.stage:''));if(!g)return;/* Each side keeps its own conference: filing both under the home side's put Cornell and Navy in the A-10. */const own=m.home?.group||m.away?.group,side=t=>cleanGroup(t?.group)||(own?'':g);const h=ensureRow(rows,m.home,side(m.home)),a=ensureRow(rows,m.away,side(m.away));[[h,m.home],[a,m.away]].forEach(([r,t])=>{if(r&&r.rating==null&&Number.isFinite(Number(t?.rating)))r.rating=Number(t.rating)});const sh=m.score?.home,sa=m.score?.away;if(h&&a&&m.status==='FINISHED'&&Number.isFinite(Number(sh))&&Number.isFinite(Number(sa))){addResult(h,Number(sh),Number(sa),false,m.kickoff||'');addResult(a,Number(sa),Number(sh),false,m.kickoff||'');if(h.group===a.group&&Number(sh)!==Number(sa)){const[w,l]=Number(sh)>Number(sa)?[h,a]:[a,h];w.cw=(w.cw||0)+1;l.cl=(l.cl||0)+1}}});Object.values(rows).forEach(r=>{r.results.sort((a,b)=>String(a[0]).localeCompare(String(b[0])));r.form=r.results.slice(-5).map(x=>x[1]).join(' ')});const by={};Object.values(rows).forEach(r=>{if(!r.group)return;(by[r.group] ||= []).push(r)});return Object.keys(by).sort((a,b)=>groupLetter(a).localeCompare(groupLetter(b))).map(g=>{const pct=(w,l)=>w+l?w/(w+l):0;by[g].forEach(r=>{r.cw=r.cw||0;r.cl=r.cl||0;r.conf_record=`${r.cw}-${r.cl}`});by[g].sort(DATA.comp_key==='NCAAM'?(x,y)=>(pct(y.cw,y.cl)-pct(x.cw,x.cl))||(y.cw-x.cw)||(pct(y.w,y.l)-pct(x.w,x.l))||((Number(y.rating)||0)-(Number(x.rating)||0))||String(x.name).localeCompare(y.name):(x,y)=>(y.pts-x.pts)||(y.gd-x.gd)||(y.gf-x.gf)||String(x.name).localeCompare(y.name));by[g].forEach((r,i)=>r.pos=i+1);return {group:g,teams:by[g]}})}
function getThirdRace(){let third=Array.isArray(DATA.third_race)&&DATA.third_race.length?DATA.third_race.map(x=>({...x})):deriveStandings().flatMap(g=>(g.teams||[]).filter(t=>t.pos===3).map(t=>({team:t.name,name:t.name,code:t.code,group:g.group,pts:t.pts,gd:t.gd,gf:t.gf,live:t.live})));third.sort((a,b)=>(b.pts-a.pts)||(b.gd-a.gd)||(b.gf-a.gf)||String(a.team||a.name).localeCompare(String(b.team||b.name)));third.forEach((t,i)=>{t.in=i<8;t.team=t.team||t.name});return third}
function getProjectedSlots(){const slots=[];deriveStandings().forEach(g=>{const gl=groupLetter(g.group);(g.teams||[]).forEach(t=>{if(t.pos===1||t.pos===2)slots.push({slot:`${gl}${t.pos}`,team:t.name,code:t.code,pts:t.pts,gd:t.gd,live:t.live})})});getThirdRace().slice(0,8).forEach((t,i)=>slots.push({slot:`3rd #${i+1}`,team:t.team,code:t.code,pts:t.pts,gd:t.gd,live:t.live}));return slots}
/* removed duplicate (sourceName) */
/* removed duplicate (renderGroups) */
/* removed duplicate (bracketTeam) */
function bracketMatch(km,ri,mi,last=false){const pending=km.status==='LIVE',done=km.status==='FINISHED';const hs=km.score?.home,as=km.score?.away;const hw=done&&Number(hs)>Number(as),aw=done&&Number(as)>Number(hs);return `<div class="bracketMatch ${last?'':'hasNext'}"><div class="bmMeta"><span>${esc(km.stage||km.round||`Match ${mi+1}`)}</span><span>${pending?'AWAITING FINAL':done?'FT':km.kickoff?dt(km.kickoff):'TBD'}</span></div>${bracketTeam(km.home,km.home_code,'',done?hs:null,hw,false)}${bracketTeam(km.away,km.away_code,'',done?as:null,aw,false)}</div>`}
/* removed duplicate (projectedRounds) */
/* removed duplicate (renderBracket) */
function renderThird(){const host=$('#view-third'),third=getThirdRace();if(!third.length){host.innerHTML=`<div class="vhead">Third-place tracker</div><div class="empty">Third-place race not available yet.</div>`;return}const cut=third[7];host.innerHTML=`<div class="vhead">Third-place tracker</div><div class="thirdList"><div class="thirdHead"><span>Rank</span><span>Team</span><span>Group</span><span>Pts</span><span>GD</span><span>Status</span></div>${third.map((t,i)=>`<div class="thirdRow ${t.in?'in':'out'}"><div class="thirdRank">#${i+1}</div><div class="thirdTeam"><div class="name">${esc(t.code||'')} ${esc(t.team||'')} ${t.live?'<span class="liveMark">*</span>':''}</div><div class="group">${esc(t.group||'')} · GF ${t.gf??0}</div></div><div class="thirdNum">${esc(t.group||'')}</div><div class="thirdNum pts">${t.pts}</div><div class="thirdNum gd">${t.gd>0?'+':''}${t.gd}</div><div class="thirdBadge ${t.in?'in':''}">${t.in?'IN':'CHASE'}</div></div>`).join('')}<div class="thirdCut">Cut line: ${cut?`${esc(cut.team||cut.name)} at ${cut.pts} pts, GD ${cut.gd>0?'+':''}${cut.gd}`:'waiting for enough teams'}.</div></div>`}


/* removed duplicate (newsSources) */
/* removed duplicate (renderNews) */

// Release notes live one-per-file in updates/, assembled into updates.js by
// build_updates.py and loaded before this script. They used to be a single
// array literal right here, which made the same lines a guaranteed conflict
// for every concurrent branch (see build_updates.py's docstring).
const SYSTEM_UPDATES=Array.isArray(window.SYSTEM_UPDATES)?window.SYSTEM_UPDATES:[];
// The displayed build label is whatever the newest release note says, so no
// one hand-edits a build string in two places and leaves them disagreeing --
// which is exactly what had happened: the strip said 0728B while the Updates
// page said 0730A.
// "0830F" alone cannot be tracked back to anything: it carries no year, its
function currentBuild(){
  return String(SYSTEM_UPDATES[0]?.date||'').replace(/^Build\s*/i,'').trim()||'dev';
}
const UPDATES_PAGE_SIZE=10;
let UPDATES_EXPANDED=false;
function toggleUpdatesHistory(){UPDATES_EXPANDED=!UPDATES_EXPANDED;renderSystemUpdates()}
function markUpdatesRead(){localStorage.setItem('matchday.updates.lastSeen',new Date().toISOString());renderSystemUpdates()}
function renderSystemUpdates(){
  const host=$('#view-updates');if(!host)return;
  const seen=localStorage.getItem('matchday.updates.lastSeen');
  const el=(tag,className,text)=>{const node=document.createElement(tag);if(className)node.className=className;if(text!==undefined)node.textContent=String(text);return node};
  const shell=el('div','updatesShell'),hero=el('div','updatesHero'),intro=el('section','updatesIntro');
  intro.append(el('h2','', 'System updates'),el('span','safePill','UI'));
  const build=el('aside','buildCard');
  build.append(el('div','tiny','Current build'),el('div','build','build '+currentBuild()),el('div','hint',`Last viewed: ${seen?ago(seen):'not marked yet'}`));
  const actions=el('div','updateActions'),mark=el('button','miniBtn','Mark as read'),status=el('button','miniBtn','Open Status');
  mark.type=status.type='button';mark.addEventListener('click',markUpdatesRead);status.addEventListener('click',()=>setView('status'));actions.append(mark,status);build.append(actions);hero.append(intro,build);
  const timeline=el('section','timeline'),head=el('div','timelineHead');head.append(el('h3','','Release notes'),el('span','',`${SYSTEM_UPDATES.length} entries`));timeline.append(head);
  const visibleUpdates=UPDATES_EXPANDED?SYSTEM_UPDATES:SYSTEM_UPDATES.slice(0,UPDATES_PAGE_SIZE);
  visibleUpdates.forEach(update=>{const article=el('article','updateItem'),body=el('div'),title=el('div','updateTitle'),items=el('ul');title.append(el('span','',update?.title??''),el('span','updateBadge',update?.tag??''));(Array.isArray(update?.items)?update.items:[]).forEach(item=>items.append(el('li','',item)));body.append(title,items);article.append(el('div','updateDate',update?.date??''),body);timeline.append(article)});
  const hiddenCount=SYSTEM_UPDATES.length-visibleUpdates.length;
  if(hiddenCount>0||UPDATES_EXPANDED){const pager=el('div','fixturePager');
    pager.append(el('span','',`Showing ${visibleUpdates.length} of ${SYSTEM_UPDATES.length} releases`));
    const more=el('button','actionbtn',UPDATES_EXPANDED?'Show recent only':`Older releases (${hiddenCount})`);
    more.type='button';more.addEventListener('click',toggleUpdatesHistory);pager.append(more);timeline.append(pager)}
  shell.append(hero,timeline);host.replaceChildren(shell);
}

function renderStatus(){const host=$('#view-status'),M=DATA.matches||[],st=deriveStandings(),third=getThirdRace(),fresh=DATA.source_freshness||{};const up=M.filter(m=>m.status==='UPCOMING').length,fin=M.filter(m=>m.status==='FINISHED').length;const next=M.filter(isVisibleUpcoming).sort((a,b)=>(a.kickoff||'').localeCompare(b.kickoff||''))[0];host.innerHTML=`<div class="vhead">App Status</div><div class="hint" style="margin-bottom:10px">menu profile: <b>${esc(navProfile())}</b> · sport file: <b>${esc(DATA_FILE)}</b></div><div class="status-grid"><div class="statuscard ${LAST_OK?'ok':'warn'}"><span class="slbl">Data file</span><div class="sval">${LAST_OK?'loaded':'not loaded'}</div><div class="hint">${LAST_ERROR?esc(LAST_ERROR):'Loaded'}</div></div><div class="statuscard info"><span class="slbl">Source</span><div class="sval">${esc(DATA.source_note||'unknown')}</div><div class="hint">${esc(fresh.primary_provider||'')}</div></div><div class="statuscard ${fresh.state==='fresh'?'ok':fresh.state?'warn':'info'}"><span class="slbl">Source freshness</span><div class="sval">${esc(fresh.state||'legacy snapshot')}</div><div class="hint">${esc(fresh.note||DATA.updated||'No source-age receipt')}</div></div><div class="statuscard info"><span class="slbl">Last successful</span><div class="sval">${fresh.last_successful_at?ago(fresh.last_successful_at):DATA.updated?ago(DATA.updated):'unknown'}</div><div class="hint">${esc(fresh.last_successful_at||DATA.updated||'—')}</div></div><div class="statuscard ${(DATA.quota_blocked_providers||[]).length?'warn':'ok'}"><span class="slbl">Provider quota</span><div class="sval">${(DATA.quota_blocked_providers||[]).length?'limited':'ok'}</div><div class="hint">${(DATA.quota_blocked_providers||[]).length?`${esc((DATA.quota_blocked_providers||[]).join(', '))} hit its safety reserve this run`:'no provider hit its safety reserve this run'}</div></div><div class="statuscard ${DATA.fixture_count_check?.anomaly?'warn':'ok'}"><span class="slbl">Fixture count</span><div class="sval">${DATA.fixture_count_check?.current??'—'}</div><div class="hint">${DATA.fixture_count_check?.anomaly?`well below the recent average of ${DATA.fixture_count_check.trailing_avg} — possible partial slate`:DATA.fixture_count_check?.trailing_avg!=null?`recent average ${DATA.fixture_count_check.trailing_avg}`:'building trailing history'}</div></div><div class="statuscard info"><span class="slbl">Matches</span><div class="sval">${M.length}</div><div class="hint">${up} upcoming · ${fin} final</div></div><div class="statuscard info"><span class="slbl">Groups</span><div class="sval">${st.length}</div><div class="hint">${third.length} third-place teams tracked</div></div><div class="statuscard info"><span class="slbl">News Items</span><div class="sval">${(DATA.news||[]).length}</div><div class="hint">${newsSources().filter(s=>s!=='all').join(' · ')}</div></div></div><div class="btnline"><button class="actionbtn" onclick="load(true)">Reload Data Now</button><button class="actionbtn" onclick="setView('groups')">Open Groups</button><button class="actionbtn" onclick="setView('third')">Open Thirds</button><button class="actionbtn" onclick="setView('updates')">System Updates</button></div>`}
function lopt(v,label,cur){return `<option value="${v}" ${v===cur?'selected':''}>${label}</option>`}
function opt(v,label,cur){return `<option value="${v}" ${String(cur)===String(v)?'selected':''}>${label}</option>`}function checked(v){return v?'checked':''}

// ---- Watchlist + in-app alerts -------------------------------------------
function wlLoad(){try{return JSON.parse(localStorage.getItem('matchday.watch')||'[]')}catch(e){return []}}
function wlSave(a){try{localStorage.setItem('matchday.watch',JSON.stringify(a))}catch(e){}}
function wlHas(team){return wlLoad().includes(team)}
function wlToggle(team){let a=wlLoad();if(a.includes(team))a=a.filter(t=>t!==team);else a.push(team);wlSave(a);renderCurrent();renderAlerts();}
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
    const id=_signalId(m),bb=typeof betbetterReadFor==='function'?betbetterReadFor(m):null;
    const confidence=Number(bb?.model_pct),market=Number(bb?.market_pct);
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
function captureSignalsIfFresh(){const fingerprint=(DATA.matches||[]).slice(0,80).map(m=>`${m.id}:${m.betbetter_pick?.model_pct??''}:${m.status}:${m.score?.home??''}-${m.score?.away??''}`).join('|');const token=`${DATA.comp_key||''}:${DATA.updated||''}:${fingerprint}`;if(token!==LAST_SIGNAL_CAPTURE){LAST_SIGNAL_CAPTURE=token;captureMatchSignals(DATA.matches||[])}}
function probabilityMovement(m){return MATCH_SIGNAL_CHANGES[_signalId(m)]||null}
function probabilitySparkline(m){
  const points=MODEL_HISTORY[_signalId(m)]||[];if(points.length<2)return '';
  const vals=points.map(x=>Number(x.p)).filter(Number.isFinite),lo=Math.min(...vals),hi=Math.max(...vals),span=Math.max(1,hi-lo);
  const coords=vals.map((v,i)=>`${Math.round(i/(vals.length-1)*54)+1},${Math.round(17-(v-lo)/span*14)}`).join(' ');
  const delta=Math.round(vals[vals.length-1]-vals[0]),cls=delta>0?'up':delta<0?'down':'flat';
  return `<span class="probTrend ${cls}" title="Model probability movement: ${delta>0?'+':''}${delta} points"><svg viewBox="0 0 56 20" aria-hidden="true"><polyline points="${coords}"/></svg><b>${delta>0?'+':''}${delta}</b></span>`;
}
// The bell reports what changed for a reader: a new ratings edition, a new AP
// poll, this week's picks, results, and starred teams. Site-maintenance notes
// (quota reserves, fixture counts) belong on the QA page, not here -- they sat
// in the bell every visit and said nothing a reader could use.
//
// Every alert carries a stable `key` that never includes relative text such as
// "3h ago". The old key was the alert's text, so the clock alone minted a new,
// unread alert on each refresh.
function _alertEnabled(type){if(type==='live')return false;const map={soon:'alertsKickoff',final:'alertsKickoff',model:'alertsModel',market:'alertsModel',data:'alertsData'};return map[type]?SETTINGS[map[type]]!==false:true}
function _alertIcon(type){return ({soon:'&#9203;',final:'&#10003;',model:'&#8597;',market:'&#8644;',data:'&#9888;',pick:'&#9733;',result:'&#9873;',ratings:'&#9776;',poll:'&#9650;',ballot:'&#9998;',gotw:'&#9737;'})[type]||'&#8226;'}
function _alertLabel(type){return ({soon:'Kickoff',final:'Final',model:'Model moved',market:'Model vs market',data:'Data',pick:'Upset watch',result:'Upset watch graded',ratings:'Power ratings',poll:'AP Top 25',ballot:'TimurKnowsBall Ballot',gotw:'Game of the week'})[type]||type}
function _alertKey(a){return a.key||`${a.t}:${a.id||'app'}`}
function _alertSeen(){return new Set(_alertReadJSON('matchday.alertsSeen',[]))}
function _alertGlobal(name){try{return Function('return typeof '+name+'!=="undefined"?'+name+':null')()}catch(e){return null}}
function _alertMatchId(home,away){const m=(DATA.matches||[]).find(x=>x.home?.name===home&&x.away?.name===away);return m?m.id:''}
function _alertDay(iso){const v=String(iso||''),d=new Date(v.length===10?v+'T12:00:00':v);return Number.isFinite(d.getTime())?d.toLocaleDateString(undefined,{month:'short',day:'numeric'}):''}
function _alertPct(v){const n=Number(v);return Number.isFinite(n)?n.toFixed(1)+'%':'—'}
// The weekly college content lives in the football snapshot, so it is shown
// only while the football board is open.
function _collegeAlerts(){
  const out=[];
  if(/ncaam/.test(String(typeof DATA_FILE!=='undefined'?DATA_FILE:'')))return out;
  const upset=_alertGlobal('MATCHDAY_BETBETTER_UPSET');
  if(upset?.available&&upset.recorded){
    (upset.picks&&upset.picks.length?upset.picks:[upset.pick]).filter(Boolean).forEach(p=>{
      const id=_alertMatchId(p.home,p.away),slot=p.slot||1,other=p.selection===p.home?p.away:p.home;
      if(p.result)out.push({t:'result',key:`result:${upset.week}:${slot}`,id,view:'home',txt:`${p.selection} ${/win|hit|won/i.test(p.result)?'won':'lost'} against ${other}, ${p.away_score??''}–${p.home_score??''}. The model had ${_alertPct(p.model_pct)}, the market ${_alertPct(p.market_pct)}.`});
      else out.push({t:'pick',key:`pick:${upset.week}:${slot}`,id,view:'home',txt:`${p.selection} over ${other} (${_alertDay(p.kickoff)}). Model ${_alertPct(p.model_pct)} vs market ${_alertPct(p.market_pct)}.`});
    });
  }
  const gotw=_alertGlobal('MATCHDAY_BETBETTER_GAME_OF_THE_WEEK');
  if(gotw?.available&&gotw.game&&Date.parse(gotw.game.kickoff)>Date.now()){const g=gotw.game,rk=t=>t?.rank?` (#${t.rank})`:'';out.push({t:'gotw',key:`gotw:${g.event_id}`,id:_alertMatchId(g.home?.team,g.away?.team),view:'home',txt:`${g.away?.team}${rk(g.away)} at ${g.home?.team}${rk(g.home)}, ${_alertDay(g.kickoff)}.`})}
  const ratings=_alertGlobal('MATCHDAY_CFB_RANKINGS');
  if(ratings?.available&&ratings.published_on&&ratings.rankings?.length)out.push({t:'ratings',key:`ratings:${ratings.published_on}`,view:'groups',txt:`New edition, ${_alertDay(ratings.published_on)}. Top three: ${ratings.rankings.slice(0,3).map(r=>r.name).join(', ')}.`});
  const ap=_alertGlobal('MATCHDAY_CFB_AP_POLL');
  if(ap?.fetched_on&&ap.rankings?.length){
    const hasHistory=ap.rankings.some(r=>r.previous_rank!=null);
    const riser=ap.rankings.filter(r=>Number(r.movement)>0).sort((x,y)=>y.movement-x.movement)[0];
    const newcomers=hasHistory?ap.rankings.filter(r=>r.previous_rank==null):[];
    let txt=`No. 1 ${ap.rankings[0].name}.`;
    if(riser)txt+=` Biggest riser: ${riser.name}, up ${riser.movement} to No. ${riser.rank}.`;
    if(newcomers.length)txt+=` New: ${newcomers.slice(0,3).map(r=>r.name).join(', ')}.`;
    out.push({t:'poll',key:`poll:${ap.rankings.map(r=>r.name).join('|')}`,view:'groups',txt});
  }
  const ballot=_alertGlobal('MATCHDAY_BETBETTER_BALLOT');
  if(ballot?.available&&ballot.published_on)out.push({t:'ballot',key:`ballot:${ballot.published_on}`,view:'groups',txt:`New ballot, ${_alertDay(ballot.published_on)}.`});
  return out;
}
function computeSignalAlerts(){
  const out=[],now=Date.now(),watchedNames=new Set(wlLoad());
  // Freshness is the newer of the provider fetch and the engine handoff. The
  // college board is driven by the handoff, so a CFBD fetch frozen by its
  // monthly quota is not "stale data" while the handoff keeps arriving.
  const synced=_alertGlobal('MATCHDAY_BETBETTER_GENERATED_AT'),updatedIso=[DATA.updated,synced].filter(Boolean).sort((a,b)=>Date.parse(b)-Date.parse(a))[0]||'',updated=Date.parse(updatedIso);
  // Only a genuinely stale site is worth a reader's attention. Keyed by the
  // update it describes, so it is read once rather than once per refresh.
  if(_alertEnabled('data')&&Number.isFinite(updated)&&(now-updated)>24*3600000)out.push({t:'data',key:`data:stale:${updatedIso}`,txt:`Game data has not refreshed since ${_alertDay(updatedIso)}. Predictions shown may be out of date.`});
  (DATA.matches||[]).forEach(m=>{
    const watched=watchedNames.has(m.home?.name)||watchedNames.has(m.away?.name)||isFavoriteMatch(m);
    if(!watched)return;
    if(_alertEnabled('soon')&&m.status==='UPCOMING'&&m.kickoff){const mins=Math.round((new Date(m.kickoff)-now)/60000);if(mins>0&&mins<=180)out.push({t:'soon',key:`soon:${m.id}`,id:m.id,txt:`${m.away?.name} at ${m.home?.name} kicks off in ${mins>=90?Math.round(mins/60)+'h':mins+'m'}.`});}
    if(_alertEnabled('final')&&m.status==='FINISHED'&&m.kickoff&&now-Date.parse(m.kickoff)<48*3600000&&m.score&&m.score.home!=null)out.push({t:'final',key:`final:${m.id}`,id:m.id,txt:`${m.away?.name} ${m.score.away}, ${m.home?.name} ${m.score.home}.`});
    // Both alerts describe the engine's read, because that is the only read the
    // site publishes. The gap alert states the two numbers rather than ranking
    // on the gap: a wider gap has predicted worse results, so it is context.
    const change=probabilityMovement(m),bb=typeof betbetterReadFor==='function'?betbetterReadFor(m):null;
    if(_alertEnabled('model')&&change&&bb)out.push({t:'model',key:`model:${m.id}:${bb.pick_name}:${change.delta}`,id:m.id,txt:`${bb.pick_name||'Model read'} moved ${change.delta>0?'+':''}${change.delta} probability points.`});
    if(_alertEnabled('market')&&bb){const gap=Number(bb.edge_points);if(Number.isFinite(gap)&&Math.abs(gap)>=8)out.push({t:'market',key:`market:${m.id}:${bb.pick_name}`,id:m.id,txt:`Model ${modelPctLabel(bb.model_pct)} and market ${Number(bb.market_pct).toFixed(1)}% on ${bb.pick_name}.`});}
  });
  out.push(..._collegeAlerts());
  return out.filter((a,i,list)=>list.findIndex(b=>_alertKey(b)===_alertKey(a))===i).slice(0,14);
}
function openAlertMatch(id,view){toggleAlertCenter(false);if(id&&(BYID[id]||(DATA.matches||[]).some(m=>String(m.id)===String(id)))){openMatchModal(id);return}if(view)setView(view)}
function markAlertsRead(alerts=computeSignalAlerts(),render=true){try{const keys=alerts.map(_alertKey),kept=[..._alertSeen()].filter(k=>!keys.includes(k));localStorage.setItem('matchday.alertsSeen',JSON.stringify(kept.concat(keys).slice(-200)))}catch(e){}if(render)renderSignalAlerts()}
// Phone nav. Nineteen destinations in a 375px bar meant four were reachable and
// the labels sat at 8px; the rest were behind a horizontal scroll nobody finds.
// The bar now carries four primary views plus this trigger, and everything else
// lives in a sheet that opens over it. Desktop is untouched -- the sidebar has
// the room for the full list and always did.
function navSheetOpen(){return !!document.getElementById('nav')?.classList.contains('navSheet')}
function closeNavSheet(){
  const nav=document.getElementById('nav');if(!nav||!nav.classList.contains('navSheet'))return;
  nav.classList.remove('navSheet');
  nav.querySelector('.navMore')?.setAttribute('aria-expanded','false');
  document.body.classList.remove('navSheetOpen');
}
function toggleNavSheet(){
  const nav=document.getElementById('nav');if(!nav)return;
  if(nav.classList.contains('navSheet')){closeNavSheet();return}
  nav.classList.add('navSheet');
  nav.querySelector('.navMore')?.setAttribute('aria-expanded','true');
  document.body.classList.add('navSheetOpen');
  nav.querySelector('.navbtn[data-v]:not([data-primary]):not([style*="display: none"])')?.focus();
}
document.addEventListener('keydown',e=>{if(e.key==='Escape'&&navSheetOpen()){closeNavSheet();document.querySelector('#nav .navMore')?.focus()}});
document.addEventListener('click',e=>{if(navSheetOpen()&&!e.target.closest('#nav'))closeNavSheet()});
function toggleAlertCenter(force){
  const panel=$('#alertCenter'),bell=$('#alertBell');if(!panel)return;
  const open=force===undefined?panel.hidden:!!force;panel.hidden=!open;
  if(bell){bell.setAttribute('aria-expanded',String(open));bell.setAttribute('aria-label',open?'Close alerts':'Open alerts')}
  if(open){renderSignalAlerts();markAlertsRead(computeSignalAlerts(),false);const c=$('#alertCount');if(c)c.hidden=true;panel.querySelector('.alertCenterClose')?.focus()}else renderSignalAlerts()
}
function renderSignalAlerts(){
  const bar=$('#alertBar'),panel=$('#alertCenter'),bell=$('#alertBell'),count=$('#alertCount'),alerts=computeSignalAlerts(),seen=_alertSeen();
  const unseen=alerts.filter(a=>!seen.has(_alertKey(a))).length;
  if(count){count.textContent=unseen;count.hidden=!unseen}bell?.classList.toggle('hasAlerts',!!alerts.length);bell?.classList.toggle('hasUnseen',unseen>0);
  if(bar){const urgent=alerts.filter(a=>(a.t==='soon'||a.t==='final')&&!seen.has(_alertKey(a))).slice(0,3);bar.style.display=urgent.length?'':'none';bar.innerHTML=urgent.map(a=>`<button class="alertPill ${a.t}" onclick="openAlertMatch('${esc(a.id||'')}','${esc(a.view||'')}')">${_alertIcon(a.t)} ${esc(a.txt)}</button>`).join('')}
  if(panel)panel.innerHTML=`<div class="alertCenterHead"><div><span>Signal center</span><b>${unseen?`${unseen} new`:alerts.length?'All caught up':'All quiet'}</b></div><button class="alertCenterClose" onclick="toggleAlertCenter(false)" aria-label="Close alerts">&times;</button></div><div class="alertCenterList">${alerts.length?[...alerts].sort((x,y)=>seen.has(_alertKey(x))-seen.has(_alertKey(y))).map(a=>{const old=seen.has(_alertKey(a));return `<button class="alertItem ${a.t}${old?' read':''}" onclick="openAlertMatch('${esc(a.id||'')}','${esc(a.view||'')}')"><i>${_alertIcon(a.t)}</i><span><b>${_alertLabel(a.t)}${old?'':' <em class="alertNew">new</em>'}</b><small>${esc(a.txt)}</small></span></button>`}).join(''):`<div class="alertEmpty"><span>&#10003;</span><b>No active signals</b><p>New ratings, AP polls and weekly picks show up here. Star a team for kickoff and final-score alerts.</p></div>`}</div><div class="alertCenterFoot"><button onclick="markAlertsRead()">Mark all read</button><button onclick="toggleAlertCenter(false);setView('customize')">Alert settings</button></div>`;
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
// ---- Accounts: identity that outlives the browser ------------------------
// A device id lives and dies with localStorage, so clearing a browser or
// switching devices used to mean a new handle and an empty record. Signing in
// with Google/GitHub maps this browser onto a durable server-side account; the
// session token below is disposable, because signing in again finds the same
// account. Anonymous play is unchanged for anyone who never signs in.
const AUTH_BASE=LEADERBOARD_URL?LEADERBOARD_URL.replace(/\/api\/leaderboard\/?$/,''):'';
let ACCOUNT={signedIn:false,handle:'',canReshuffle:false};
let AUTH_PROVIDERS=[];
function authToken(){try{return localStorage.getItem('matchday.session')||''}catch(e){return ''}}
function setAuthToken(t){try{t?localStorage.setItem('matchday.session',t):localStorage.removeItem('matchday.session')}catch(e){}}
function applyAccount(d){
  if(!d)return;
  // `canReshuffle` is absent from pick responses; absent means unchanged, not false.
  ACCOUNT={signedIn:!!d.signedIn,handle:d.handle||ACCOUNT.handle,
    canReshuffle:d.canReshuffle===undefined?ACCOUNT.canReshuffle:!!d.canReshuffle};
  if(d.handle){try{localStorage.setItem('matchday.handle',d.handle);localStorage.setItem('matchday.handleAssigned','1')}catch(e){}}
}
async function lbPost(action,body){
  if(!LEADERBOARD_URL)return null;
  try{const r=await fetch(LEADERBOARD_URL+'?action='+action,{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({token:authToken()||undefined,...body})});return await r.json();}catch(e){return null;}
}
function signIn(provider){
  if(!AUTH_BASE)return;
  const url=AUTH_BASE+'/api/auth?provider='+encodeURIComponent(provider)
    +'&return='+encodeURIComponent(location.origin)+'&deviceId='+encodeURIComponent(deviceId());
  location.assign(url);
}
async function signOut(){
  await lbPost('signout',{});
  setAuthToken('');ACCOUNT={signedIn:false,handle:'',canReshuffle:false};SIGNIN_CLAIMED=0;
  // Drop the account's handle too, or a guest would keep wearing a name the
  // board no longer knows them by.
  try{localStorage.removeItem('matchday.handle');localStorage.removeItem('matchday.handleAssigned')}catch(e){}
  // The local record stays put; only the server identity is released.
  try{renderCommunity()}catch(e){}
}
// Deletion is irreversible and takes the graded picks with it, so it asks in
// those words rather than the usual "are you sure?" -- the cost of the action
// is the thing worth confirming, not the click.
async function deleteAccount(){
  const warning='Delete your account?\n\nThis removes your handle, your graded picks and your place on the leaderboard. It cannot be undone.\n\nSigning out instead keeps all of it.';
  if(!confirm(warning))return;
  const d=await lbPost('delete-account',{});
  if(!d||!d.ok){ACCOUNT_ERROR='Could not delete the account — please try again.';try{renderCommunity()}catch(e){};return;}
  setAuthToken('');ACCOUNT={signedIn:false,handle:'',canReshuffle:false};SIGNIN_CLAIMED=0;ACCOUNT_ERROR='';
  // Local picks are this browser's own copy and were never the server's to
  // delete; clearing them keeps the app from re-uploading what was just erased.
  try{localStorage.removeItem('matchday.handle');localStorage.removeItem('matchday.handleAssigned');
    localStorage.removeItem('matchday.btm');localStorage.removeItem('matchday.device')}catch(e){}
  ACCOUNT_DELETED=true;
  try{renderCommunity()}catch(e){}
}
let ACCOUNT_ERROR='';
let ACCOUNT_DELETED=false;
let SIGNIN_ERROR='';
let SIGNIN_CLAIMED=0;
// The callback hands back a single-use code in the fragment (never sent to a
// server). Trade it for a session token, then scrub it from the URL so a
// shared or reloaded link cannot replay a sign-in.
async function consumeSigninRedirect(){
  const m=/(?:^|&)mdsignin=([^&]+)/.exec(String(location.hash||'').replace(/^#/,''));
  if(!m)return false;
  const code=decodeURIComponent(m[1]);
  history.replaceState(null,'',location.pathname+location.search);
  if(code==='cancelled'||code==='failed'){SIGNIN_ERROR=code==='cancelled'?'Sign-in cancelled.':'Sign-in failed — please try again.';return false;}
  const d=await lbPost('session-exchange',{code,deviceId:deviceId()});
  if(d&&d.ok){applyAccount(d);SIGNIN_CLAIMED=Number(d.claimed||0);return true;}
  SIGNIN_ERROR='Sign-in failed — please try again.';return false;
}
async function refreshSession(){
  if(!authToken())return;
  const d=await lbPost('session',{});
  if(d&&d.ok){applyAccount(d);if(!d.signedIn)setAuthToken('');}
}
async function loadAuthProviders(){
  if(!LEADERBOARD_URL)return;
  try{const r=await fetch(LEADERBOARD_URL+'?action=providers');const d=await r.json();
    if(d&&d.ok)AUTH_PROVIDERS=d.providers||[];}catch(e){}
}
async function bootAccount(){
  if(!LEADERBOARD_URL)return;
  await loadAuthProviders();
  const signedInNow=await consumeSigninRedirect();
  if(!signedInNow)await refreshSession();
  // The community view may already have painted a guest state while this was
  // in flight, so repaint it whether or not it is the visible tab.
  try{renderCommunity()}catch(e){}
}
// ---- Community identity: assigned real-player names, never free text ------
// A free-text handle on a shared public board is an open door for offensive
// or trolling names. Rather than moderate input, there's no input at all --
// everyone is assigned a real player's name (their favorite team's, when we
// have live data for it; a curated pool otherwise), with exactly one
// reshuffle allowed if they don't like the draw.
const US_SPORT_NAME_POOL={
  ncaaf:['Herschel Walker','Doug Flutie','Charlie Ward','Vince Young','Bo Jackson','Tim Tebow'],
  ncaam:['Pete Maravich','Christian Laettner','Danny Manning','Grant Hill','Tyler Hansbrough','Bill Bradley'],
};
const GENERAL_NAME_POOL=[].concat(...Object.values(US_SPORT_NAME_POOL));
function _handlePool(){
  const sportKey=String(DATA?.comp_key||'').toLowerCase();
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
function canReshuffleHandle(){
  if(ACCOUNT.signedIn)return ACCOUNT.canReshuffle; // the account, not the browser, owns the one reshuffle
  try{return localStorage.getItem('matchday.handleReshuffled')!=='1'}catch(e){return false}
}
async function reshuffleHandle(){
  if(!canReshuffleHandle())return;
  if(ACCOUNT.signedIn){
    const d=await lbPost('reshuffle',{});
    if(d&&d.ok)applyAccount({signedIn:true,handle:d.handle,canReshuffle:false});
    renderCommunity();return;
  }
  const base=myHandle().replace(/\s#\d+$/,'');
  const h=_drawHandle(base);
  try{localStorage.setItem('matchday.handle',h);localStorage.setItem('matchday.handleReshuffled','1')}catch(e){}
  renderCommunity();
}
function ensureHandle(){
  if(ACCOUNT.signedIn)return; // server-assigned, and it outranks anything local
  try{
    const assigned=localStorage.getItem('matchday.handleAssigned')==='1';
    const collegeName=GENERAL_NAME_POOL.some(name=>myHandle().startsWith(name+' #'));
    if(!myHandle()||!assigned||!collegeName)assignHandle(); // legacy pro-sport guest aliases are replaced without losing device picks
  }catch(e){}
}
async function pushScore(){ // server grades only picks it locked before kickoff
  const d=await lbPost('sync',{deviceId:deviceId()});
  if(d&&d.ok)applyAccount(d);
}
async function fetchLeaderboard(period){
  if(!LEADERBOARD_URL)return null;
  try{const r=await fetch(LEADERBOARD_URL+'?action=leaderboard&period='+(period||'all'));const d=await r.json();return d.ok?d.board:null;}catch(e){return null;}
}
function lbPeriod(){try{return localStorage.getItem('matchday.lbPeriod')||'all'}catch(e){return 'all'}}
function setLbPeriod(p){try{localStorage.setItem('matchday.lbPeriod',p)}catch(e){};if(typeof COMM_BOARD!=='undefined'){COMM_BOARD=null;COMM_FETCHED=''}renderCommunity();}
function btmLoad(){try{return JSON.parse(localStorage.getItem('matchday.btm')||'{}')}catch(e){return {}}}
function btmSave(o){try{localStorage.setItem('matchday.btm',JSON.stringify(o))}catch(e){}}
function communityScope(){return String(DATA?.comp_key||'').toUpperCase();}
function btmScoped(db){const scope=communityScope();if(!scope)return db;
  const picks={};Object.entries(db.picks||{}).forEach(([id,p])=>{if(String(p.comp||'NCAAF').toUpperCase()===scope)picks[id]=p;});
  return {...db,picks};}
function isCommunityPickOpen(m){const kickoff=kickMs(m),now=Date.now();return m?.status==='UPCOMING'&&kickoff>now&&kickoff-now<=7*864e5&&!isStaleUpcoming(m)}
/* Resolves true only once the server has stored the pick. A failed lock used
   to be dropped silently: submitting five picks fired five requests at once,
   and only the one the server happened to accept ever reached Recent activity
   or the leaderboard. One retry covers a cold start or a momentary 429/500. */
async function lockGlobalPick(matchId,pick,comp){
  const body={deviceId:deviceId(),matchId:String(matchId),pick,comp:String(comp||'').toLowerCase()};
  for(let attempt=0;attempt<2;attempt++){
    if(attempt)await new Promise(r=>setTimeout(r,1500));
    const d=await lbPost('pick',body);
    if(d&&d.ok){applyAccount(d);return true}
    // A closed window or a rejected pick will not change on retry.
    if(d&&/window closed|invalid pick/.test(String(d.error||'')))return false;
  }
  return false;
}
function submitPick(matchId,pick,render=true,lock=true){
  ensureHandle();
  const db=btmLoad();db.picks=db.picks||{};
  // One pick per match. It can be changed until kickoff, then it is locked.
  const m=(DATA.matches||[]).find(x=>String(x.id)===String(matchId));if(!m)return false;
  if(db.picks[matchId]&&(db.picks[matchId].pick===pick||db.picks[matchId].result))return false;
  // A feed can still say UPCOMING after the clock has passed kickoff. The
  // timestamp is therefore a second, mandatory lock check.
  if(!isCommunityPickOpen(m))return false;
  const read=typeof betbetterReadFor==='function'?betbetterReadFor(m):m.betbetter_pick;
  db.picks[matchId]={pick,ts:Date.now(),
    home:m.home.name,away:m.away.name,code:{h:m.home.code,a:m.away.code},
    comp:m._comp||DATA.comp_key||'',
    modelPick:read?.pick||null,
    marketPick:(()=>{const x=(m.markets||{})['1x2'];if(!x||x.home_pct==null)return null;const tr={h:x.home_pct,d:x.draw_pct,a:x.away_pct};return Object.keys(tr).reduce((a,b)=>tr[b]>tr[a]?b:a)})()};
  btmSave(db);if(render)renderCommunity();if(lock)lockGlobalPick(matchId,pick,db.picks[matchId].comp);return true;
}
