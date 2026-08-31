
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
const DEFAULT_SETTINGS={accent:'green',density:'normal',panel:'glass',defaultView:'matches',refresh:900,showInsight:true,showFinished:false,showDetails:false,favoriteTeam:'',favoriteTeams:[],alertsKickoff:true,alertsLive:false,alertsUpset:false,alertsModel:true,alertsData:true};
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
const SPORT_LABELS={ncaaf:'College Football',ncaam:"Men's College Basketball"};
// The sports we actually publish data for. SPORT_LABELS above still knows about
// NHL so a restored sport picks up its name for free, but nothing fetches a file
// that isn't there.
const ALL_SPORT_KEYS=['ncaaf','ncaam'];
const COLLEGE_BOARD_KEYS=new Set(['ncaaf','ncaam']);
const FIXTURE_PAGE_SIZE=40;
// The model board used to render every pick in one scroll (1,300+ rows on a
// full slate). Same pager the fixture list already uses, smaller page: a pick
// row is denser reading than a match card.
const MODEL_PAGE_SIZE=25;
let MATCH_VISIBLE=FIXTURE_PAGE_SIZE,RESULT_VISIBLE=FIXTURE_PAGE_SIZE,MODEL_VISIBLE=MODEL_PAGE_SIZE;
// Site-wide publication pause, mirroring forecast_pause.py. One flag: clear
// FORECAST_PAUSE_ACTIVE when the coverage gaps close and every sport falls back
// to its own gate below rather than publishing unconditionally.
const FORECAST_PAUSE_ACTIVE=false;
const FORECAST_PAUSE_MESSAGE='Predictions are paused while the model is rebuilt on a new data engine.';

function forecastPublicationState(payload,match){
  const value=x=>typeof x==='string'?x:(x&&typeof x==='object'?(x.state||x.status||x.publication_state):'');
  const candidates=[
    match?._forecast_paused?'paused':'',match?.forecast_publication_state,match?.prediction_publication_state,
    match?.publication_state,match?.forecast_publication,match?.prediction?.publication_state,
    payload?.forecast_publication_state,payload?.prediction_publication_state,payload?.publication_state,
    payload?.forecast_publication,payload?.prediction_publication,
  ];
  const states=candidates.map(value).filter(Boolean).map(x=>String(x).toLowerCase());
  if(states.includes('paused'))return 'paused';
  const dataset=String(value(payload?.forecast_publication)||value(payload?.prediction_publication)||'').toLowerCase();
  if(dataset==='eligible')return 'eligible';
  return states[0]||'';
}
function isForecastPaused(match,payload=DATA){
  // Finished matches keep the pick they were graded on: that is the public
  // record, and hiding it would scrub the model's own results. Everything not
  // yet settled -- upcoming and in-play alike -- loses its forecast, because an
  // in-play pick is still an ungraded model call being presented as live
  // analysis, percentages included.
  if(String(match?.status||'').toUpperCase()==='FINISHED')return false;
  if(FORECAST_PAUSE_ACTIVE)return true;
  // The site switch is authoritative. A last-good dataset can retain yesterday's
  // paused marker when a provider refresh is rate-limited; it must not resurrect
  // a banner after publication has deliberately resumed.
  return false;
}
function applyForecastPublicationPauses(payload){
  if(!payload||!Array.isArray(payload.matches))return payload;
  payload.matches.forEach(match=>{
    if(!isForecastPaused(match,payload))return;
    match._forecast_paused=true;
    match._forecast_pause_message=FORECAST_PAUSE_MESSAGE;
    ['prediction','locked_prediction','prediction_snapshot','official_pick','model_pick','model_confidence',
     'confidence','edge','upset','watchability','watch_score','forecast','predicted_score',
     'predicted_home_score','predicted_away_score','predicted_margin','expected_margin','model_margin',
     'model_alert','model_vs_market_alert'].forEach(key=>delete match[key]);
  });
  return payload;
}
function forecastPauseHTML(match){
  // Two inline children with no rule of their own rendered as one run-on line
  // ("Forecast pausedPicks are on hold..."). Block them out and give the notice
  // the same warn treatment the top-of-view banner already uses.
  return isForecastPaused(match)?`<div class="emptyForecast forecastPaused" role="status"><b>Forecast paused</b><span>${esc(FORECAST_PAUSE_MESSAGE)}</span><em>Scores, results, stats and market odds are all still here.</em></div>`:'';
}

// Providers can keep the season that just ended until the next schedule
// opens. Keep its games in Results, but never label its table or bracket as
// the new season's live competition state.
function competitionSeasonCutoff(comp,now=new Date()){
  const key=String(comp||'').toUpperCase(),year=now.getUTCFullYear();
  if(key==='MLB')return new Date(Date.UTC(year,0,1));
  const startYear=now.getUTCMonth()>=6?year:year-1;
  return new Date(Date.UTC(startYear,6,1));
}
function stripPastSeasonCompetitionViews(payload,now=new Date()){
  if(!payload||String(payload.comp_key||'').toUpperCase()==='ALL')return payload;
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
  // profile is the same six views; the pair is kept because NAV_LABELS still
  // names them differently per sport (Rankings/CFP Bracket vs
  // Conferences/Bracketology), which is the whole reason the table survives.
  all:               ['matches','results','groups','bracket','score','news','community'],
  college:           ['matches','results','groups','bracket','score','news','community'],
  college_basketball:['matches','results','groups','bracket','score','news','community']
};
// The only views that exist after the college pivot. A stored defaultView or a
// bookmarked hash can still name a removed one (Customize let people save
// 'news' or 'updates' for years), so every entry point clamps through this
// rather than trusting what it was handed and rendering into a null host.
const VIEWS=new Set(['matches','results','groups','bracket','score','news','community']);
function safeView(v){return VIEWS.has(v)?v:'matches';}
const SPORT_KIND={'':'all',ncaaf:'college',ncaam:'college_basketball'};
function currentSportKey(){const m=(DATA_FILE||'').match(/data_(\w+)\.json/);return m?m[1]:'';}
function navProfile(){return SPORT_KIND[currentSportKey()]||'all';}
const NAV_LABELS={all:{groups:'Conferences',bracket:'Playoffs'},college:{groups:'Conferences',bracket:'CFP Playoff'},college_basketball:{groups:'Conferences',bracket:'Bracketology'}};
// A domestic league plays a season, not a tournament. The nav button already
// said so via NAV_LABELS; the view's own heading did not.
function tottTitle(){return navProfile()==='soccer_league'?'Team of the Season':'Team of the Tournament'}
function applySportNav(){
  const prof=navProfile();
  const allowed=NAV_DEF[prof];
  const labels=NAV_LABELS[prof]||{};
  document.querySelectorAll('.navbtn[data-v]').forEach(b=>{
    const hasBracket=(Array.isArray(DATA?.bracket)&&DATA.bracket.some(r=>(r?.matches||[]).length))||!!DATA?.bracketology;
    const hasStandings=Array.isArray(DATA?.standings)&&DATA.standings.length>0;
    const hasThirdRace=Array.isArray(DATA?.third_race)&&DATA.third_race.length>0;
    const hasViewData=b.dataset.v==='bracket'?hasBracket:b.dataset.v==='groups'?hasStandings:b.dataset.v==='third'?hasThirdRace:true;
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
  if(!allowed.includes(VIEW))setView('matches');
}
function loadingBoardHTML(){return '<div class="loadingBoard" aria-label="Loading matches"><span></span><span></span><span></span><span></span></div>'}
function showMatchLoading(){const host=$('#view-matches');if(host)host.innerHTML=loadingBoardHTML()}
function clearCompetitionViewsForLoad(){
  ['groups','bracket','third'].forEach(view=>{const host=$('#view-'+view);if(host)host.innerHTML='<div class="empty">Loading current-season data…</div>'});
}
function changeSport(v){DATA_FILE=v?('data_'+v+'.json'):'';MATCH_VISIBLE=FIXTURE_PAGE_SIZE;RESULT_VISIBLE=FIXTURE_PAGE_SIZE;MODEL_VISIBLE=MODEL_PAGE_SIZE;try{localStorage.setItem('matchday.sport',DATA_FILE)}catch(e){};applySportNav();showMatchLoading();clearCompetitionViewsForLoad();load(true);}

const COLORS={orange:'#ffb02e',blue:'#4cc2ff',green:'#3ad17a',red:'#ff4d5e',purple:'#b16cff'};
function saveSettings(){localStorage.setItem('matchday.settings',JSON.stringify(SETTINGS))}
function applySettings(){document.documentElement.style.setProperty('--signal',COLORS[SETTINGS.accent]||COLORS.orange);document.body.classList.toggle('compact',SETTINGS.density==='compact');document.body.classList.toggle('spacious',SETTINGS.density==='spacious');$('#app').classList.toggle('flat',SETTINGS.panel==='flat');$('#app').classList.toggle('noinsight',!SETTINGS.showInsight);document.body.classList.toggle('hideStats',!SETTINGS.showDetails);syncRailToggle()}
function syncRailToggle(){
  const btn=$('#railToggle');
  if(!btn)return;
  const open=!!SETTINGS.showInsight,label=open?'Hide the in-focus rail':'Show the in-focus rail';
  btn.setAttribute('aria-expanded',String(open));
  btn.title=label;
  const sr=btn.querySelector('.srOnly');
  if(sr)sr.textContent=label;
}
function toggleInsightRail(){
  const open=!SETTINGS.showInsight;
  updateSetting('showInsight',open);
  // renderCurrent() never touches the rail, so a rail that was collapsed
  // before its first render would come back empty without this.
  if(open&&typeof renderInsight==='function')renderInsight();
}
function updateSetting(k,v){if(k==='refresh')return;if(k==='showInsight'||k==='showDetails'||k==='showFinished'||k.startsWith('alerts'))v=!!v;SETTINGS[k]=v;saveSettings();applySettings();renderCurrent();if((k==='favoriteTeam'||k==='favoriteTeams')&&typeof renderInsight==='function')renderInsight();if(k.startsWith('alerts'))renderAlerts();scheduleNextLoad()}
function resetSettings(){SETTINGS={...DEFAULT_SETTINGS};saveSettings();applySettings();setView(SETTINGS.defaultView);scheduleNextLoad()}
function esc(s){return String(s??'').replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]))}
function uiLocale(){return({es:'es',fr:'fr',de:'de',pt:'pt-BR',ru:'ru'})[LANG]||undefined}
function relativeTime(value,unit){return new Intl.RelativeTimeFormat(uiLocale(),{numeric:'auto'}).format(value,unit)}
function dt(iso){try{return new Date(iso).toLocaleString(uiLocale(),{weekday:'short',hour:'numeric',minute:'2-digit',month:'short',day:'numeric'})}catch(e){return''}}
function ago(iso){try{const s=(Date.now()-new Date(iso).getTime())/1000;if(!isFinite(s))return'';if(s<70)return relativeTime(0,'second');if(s<3600)return relativeTime(-Math.round(s/60),'minute');if(s<86400)return relativeTime(-Math.round(s/3600),'hour');return relativeTime(-Math.round(s/86400),'day')}catch(e){return''}}
function kickIn(iso){try{const m=Math.round((new Date(iso)-Date.now())/60000);if(m<=0)return relativeTime(0,'minute');if(m<60)return relativeTime(m,'minute');if(m<1440)return relativeTime(Math.round(m/60),'hour');return relativeTime(Math.round(m/1440),'day')}catch(e){return''}}
const ODDS_WINDOW_HOURS=3; // mirrors fetch_data.py's PREGAME_ODDS_WINDOW_HOURS quota gate
function oddsEtaLabel(m){try{const mins=(new Date(m.kickoff)-Date.now())/60000;if(mins>ODDS_WINDOW_HOURS*60)return `Market odds appear ~${ODDS_WINDOW_HOURS}h before kickoff`}catch(e){}return null}
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
const SCORE_DIFF_TERM={mlb:'run diff',nfl:'point diff',nba:'point diff',ncaaf:'point diff',ncaam:'point diff',nhl:'goal diff'};
function scoreDiffLabel(m){return SCORE_DIFF_TERM[String(m?._comp||DATA.comp_key||'').toLowerCase()]||'goal diff';}
const SCORE_DIFF_ABBR={mlb:'RD',nfl:'PD',nba:'PD',ncaaf:'PD',ncaam:'PD',nhl:'GD'};
// Only league/cup tables that actually award standings points have a real
// "pts" column. Every US sport ranks on win-loss record, so the pts value the
// pipeline derives for them (wins x 3) is an artefact of the soccer-shaped
// schema, not a number any fan of that sport recognises -- NCAAF showed
// "27 pts" for a 9-4 team. Show the record those sports rank on instead.
const TABLE_POINTS_COMPS=new Set(['WC','UCL','EPL','LALIGA','SERIEA','BUNDESLIGA','LIGUE1']);
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
    if(Number.isFinite(gd)&&(gd||Number(team?.gf)||Number(team?.ga)))parts.push(`${SCORE_DIFF_ABBR[String(comp??DATA.comp_key??'').toLowerCase()]||'GD'} ${gd>0?'+':''}${gd}`);
  }
  const form=String(team?.form||'').trim();
  if(opts.form&&form)parts.push(form);
  return parts;
}
function scoreText(m){if(m.status==='LIVE')return'<span class="pendingScore" aria-label="Score shown after final">—</span>';const done=m.status==='FINISHED';if(isStaleUpcoming(m))return'<span class="kick">Past kickoff</span>';return done?`${m.score?.home??'-'}<span class="sep">–</span>${m.score?.away??'-'}${m.score?.pens?`<span class="pensTag">(${m.score.pens.home}-${m.score.pens.away} pens)</span>`:''}`:`<span class="kick">${dt(m.kickoff).split(', ').pop()||'TBD'}</span>`}
function scorePlainText(m){if(m?.status==='LIVE')return '—';if(isStaleUpcoming(m))return 'Past kickoff';if(m?.status==='FINISHED'){const pens=m.score?.pens?` (${m.score.pens.home}-${m.score.pens.away} pens)`:'';return `${m.score?.home??'-'}–${m.score?.away??'-'}${pens}`;}return dt(m?.kickoff).split(', ').pop()||'TBD';}
function statNum(v){const m=String(v??'').match(/-?\d+(\.\d+)?/);return m?Number(m[0]):0}
function pressure(stats,side){if(!stats)return 0;const s=stats[side]||{};return statNum(s.shots_on_target)*4+statNum(s.shots)*1.2+statNum(s.corners)*1.4+statNum(String(s.possession).replace('%',''))*.08-statNum(s.red_cards)*4}
function pct(v){v=Number(v);return Number.isFinite(v)?Math.max(0,Math.min(100,Math.round(v))):0}
function bar1x2(h,d,a){h=pct(h);a=pct(a);const dSeg=d==null?'':(d=>`<div class="seg d" style="flex-basis:${d}%"><span>${d}%</span></div>`)(pct(d));return `<div class="bar"><div class="seg h" style="flex-basis:${h}%"><span>${h}%</span></div>${dSeg}<div class="seg a" style="flex-basis:${a}%"><span>${a}%</span></div></div>`}
// The backend owns the published pick. UI components may explain that pick,
// but must never promote a live model or market inference over a locked record.
function lockedPredictionSnapshot(m){
  const pr=m?.prediction||{};
  const candidates=[m?.locked_prediction,m?.prediction_snapshot,pr.locked_snapshot,pr.snapshot,pr.locked];
  const found=candidates.find(x=>x&&typeof x==='object'&&!Array.isArray(x));
  return found?.prediction&&typeof found.prediction==='object'?found.prediction:(found||{});
}
function officialPrediction(m){
  if(isForecastPaused(m))return {side:'',name:'',confidence:null,locked:{}};
  const pr=m?.prediction||{},locked=lockedPredictionSnapshot(m);
  const side=locked.pick??pr.pick??'';
  const name=locked.pick_name??pr.pick_name??(side==='h'?m?.home?.name:side==='a'?m?.away?.name:side==='d'?'Draw':'');
  return {side,name,confidence:locked.confidence??pr.confidence??null,locked};
}
function officialPredictionProbabilities(m){
  if(isForecastPaused(m))return {};
  const pr=m?.prediction||{},locked=lockedPredictionSnapshot(m);
  return locked.adjusted||locked.blend||locked.probs||pr.adjusted||pr.blend||pr.model||{};
}
function duo(xl,xv,yl,yv){xv=pct(xv);yv=pct(yv);return `<div class="mkt"><div class="lbls"><span>${esc(xl)} <b>${xv}%</b></span><span><b>${yv}%</b> ${esc(yl)}</span></div><div class="duo"><i class="x" style="flex-basis:${xv}%">${xv}%</i><i class="y" style="flex-basis:${yv}%">${yv}%</i></div></div>`}
function marketPanel(m){const mk=m.markets||{},x=mk['1x2']||{},twoWay=_isTwoWay(m);let h='<div class="seclbl">Odds tracker</div>';if(x.home_pct!=null){h+=`<div class="problbl"><span>${esc(m.home.code||m.home.name)} win</span>${twoWay?'':'<span>draw</span>'}<span>${esc(m.away.code||m.away.name)} win</span></div>${bar1x2(x.home_pct,twoWay?null:x.draw_pct,x.away_pct)}<div class="faintline" style="margin-top:6px">1X2 market · ${x.books||'?'} books</div>`;const arr=v=>v>0?`<span class="up">▲${v}</span>`:v<0?`<span class="down">▼${Math.abs(v)}</span>`:`<span class="flat">·</span>`;if(x.move&&(x.move.h||(!twoWay&&x.move.d)||x.move.a)){h+=`<div class="oddsMove"><span class="mvlbl">Since open</span><span>${esc(m.home.code)} ${arr(x.move.h)}</span>${twoWay?'':`<span>X ${arr(x.move.d)}</span>`}<span>${esc(m.away.code)} ${arr(x.move.a)}</span></div>`}else if(x.open){h+=`<div class="faintline" style="margin-top:4px">No line movement logged yet — it builds as the fetcher keeps running.</div>`}if(x.confidence){h+=`<div class="oddsDisagree ${esc(x.confidence)}"><span class="dgtag">${esc(x.confidence)}</span><span>books range ${x.spread_lo}–${x.spread_hi}% on ${esc(m.home.code)} win</span><span class="dgspread">±${x.spread}</span></div>`}}else h+=`<div class="nomk">${esc(oddsEtaLabel(m)||'No 1X2 market odds yet.')}</div>`;if(mk.totals)h+=`<div class="seclbl">Goals — over/under ${esc(mk.totals.line)}</div>`+duo(`Over ${mk.totals.line}`,mk.totals.over_pct,`Under ${mk.totals.line}`,mk.totals.under_pct);return h}
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
function enterMatchday(targetView='',startWithTour=false){
  try{sessionStorage.setItem('matchday.welcome.entered','1');localStorage.setItem('matchday.heroSeen','1')}catch(e){}
  const gate=$('#welcomeGate'),app=$('#app');
  const finish=()=>{
    if(gate){gate.hidden=true;gate.classList.remove('welcomeLeaving')}
    document.body.classList.remove('welcomeOpen','welcomeExiting');
    if(app)app.classList.remove('appRevealing');
    if(targetView&&typeof setView==='function')setView(targetView);else renderCurrent();
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
  {target:'#sportSel',title:'Start here',body:'Pick a competition to see its pregame predictions, accuracy tracking and brackets. "All sports" shows everything in one feed.'},
  {target:'.navbtn[data-v="matches"]',title:'Matches',body:'Every upcoming fixture with the model’s locked pregame pick shown next to the market’s.'},
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
function _welcomeCardHTML(m){
  const pr=m.prediction||{},op=(typeof _v10OfficialPick==='function'&&m.prediction)?_v10OfficialPick(m):null;
  const pick=op?.name||pr.pick_name||'',model=op?.confidence??pr.confidence,market=op?.marketPct;
  const edge=model!=null&&market!=null?Math.round(Number(model)-Number(market)):null;
  const meter=model!=null?`<div class="welcomeMeter" aria-hidden="true"><i style="--welcome-p:${pct(model)}%"></i></div>`:'';
  return `<div class="welcomeMatchMeta"><span>${esc(m._comp||DATA.comp_key||m.stage||'NEXT')}</span><span>${kickIn(m.kickoff)}</span></div><div class="welcomeTeams"><div><small>${esc(m.home?.code||'HOME')}</small><b>${esc(m.home?.name||'Home')}</b></div><em>v</em><div class="away"><small>${esc(m.away?.code||'AWAY')}</small><b>${esc(m.away?.name||'Away')}</b></div></div>${pick?`<div class="welcomeSignal"><span>${_isTwoWay(m)||!(Number(model)<50)?'MODEL':'MOST LIKELY'}</span><b>${esc(pick)} ${model!=null?esc(model)+'%':''}</b>${market!=null?`<i>market ${esc(market)}%${edge!=null?` · ${edge>0?'+':''}${edge} pt`:''}</i>`:''}</div>${meter}`:''}`;
}
// Real coverage numbers, counted from the slate that just loaded. Deliberately
// three short figures rather than another paragraph of claims.
function renderWelcomeStats(){
  const host=$('#welcomeStats');if(!host)return;
  const M=DATA.matches||[];
  const upcoming=M.filter(isVisibleUpcoming);
  if(!upcoming.length){host.innerHTML='';return}
  const priced=upcoming.filter(m=>!isForecastPaused(m)&&((typeof officialPrediction==='function'&&officialPrediction(m))||m.prediction)).length;
  // Competitions is the product's breadth, not the current selection's -- the
  // gate is the front door for all of it, and a single-sport view would
  // otherwise read "1 competitions".
  // While picks are paused, "0% model coverage" is a true number that reads
  // like a broken site. Say what is actually happening instead, and let the
  // graded record carry the third slot.
  const graded=Number(DATA.scorecard?.graded)||0;
  const cells=[[upcoming.length,'fixtures ahead'],
               [Object.keys(SPORT_LABELS).length,'competitions'],
               FORECAST_PAUSE_ACTIVE
                 ?[graded||'—','picks on the record']
                 :[`${Math.round(priced/upcoming.length*100)}%`,'model coverage']];
  host.innerHTML=cells.map(([v,l])=>`<div><b>${esc(v)}</b><span>${esc(l)}</span></div>`).join('');
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
  renderWelcomeStats();bindWelcomeTilt();
  const upcoming=(DATA.matches||[]).filter(isVisibleUpcoming);
  const soonest=[...upcoming].sort(fixtureSort)[0],host=$('#welcomeNext');
  if(!host)return;
  if(!soonest){
    host.innerHTML=`<div class="welcomeFallback"><span class="welcomeFallbackKicker">BOARD READY</span><strong>Fresh reads appear as matchups are published.</strong><p>Explore the dashboard for completed scorecards, model methodology, and every available competition.</p><div aria-hidden="true"><i></i><i></i><i></i></div></div>`;
    const state=$('#welcomeFeedState');if(state)state.textContent='ANALYSIS';
    return;
  }
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
  const rec=`<span class="heroRecLine">${sc&&sc.graded?`<span class="heroRec"><b>${sc.graded}</b> picks locked pregame and graded</span><span class="heroRec faintline">never edited after the result</span>`:`<span class="heroRec faintline">Model record begins as completed picks are graded</span>`}</span>`;
  if(slim)return `<div class="heroSlim">${rec}<button class="heroSlimLink" type="button" onclick="setView('score')">Open scorecard <span aria-hidden="true">→</span></button></div>`;
  return `<div class="heroBand">
    <img src="icon-192.png?v=4" class="heroLogo" alt="Matchday" width="192" height="192">
    <div class="heroTitle">Every pick, on the record.</div>
    <div class="heroSub">Locked before kickoff, graded after the final whistle, never edited in between. Free, and no ads.</div>
    <div class="heroRow">${rec}</div>
    ${heroMarquee()}
    <div class="heroActions">
      <button class="btmbtn heroBtn" onclick="heroDismiss()">Open the analysis</button>
      <button class="btmbtn heroBtn ghost" onclick="heroDismiss();setView('community')">Play against the model</button>
    </div>
  </div>`;
}
// Where a draw is possible the leading outcome is routinely under 50%, which
// reads as a broken model when it is presented as a flat "Pick". Both the card
// markup and the compact-card pass below label those "Most likely" instead, so
// they have to agree on when that is.
function hasThreeWayProbabilities(m){
  if(typeof _isTwoWay==='function'&&_isTwoWay(m))return false;
  const p=officialPredictionProbabilities(m)||{};
  return p.h!=null&&p.d!=null&&p.a!=null;
}
function leadsUnderHalf(m,confidence){return hasThreeWayProbabilities(m)&&Number(confidence)<50}
function enhanceMatchCards(host){
  host.querySelectorAll('.card .head').forEach(head=>{
    const card=head.closest('.card'),m=BYID[card?.dataset.id];
    if(isFavoriteMatch(m)){card.classList.add('favoriteMatch');if(!head.querySelector('.favoriteTag'))head.insertAdjacentHTML('beforeend',`<span class="favoriteTag">${t('My team')}</span>`)}
    head.setAttribute('role','button');head.setAttribute('tabindex','0');
    if(m)head.setAttribute('aria-label',`Open ${m.home?.name||'home'} versus ${m.away?.name||'away'}`);
    if(card.classList.contains('compactCard')&&m?.prediction){
      const op=_v10OfficialPick(m),edge=_v10OfficialEdge(m,op),label=card.querySelector('.pick .pl'),note=card.querySelector('.pick .pnote');
      if(label)label.textContent=leadsUnderHalf(m,op.confidence)?'Most likely':'Model';
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
// The marquee board deliberately reaches months ahead when a sport is between
// seasons (see nearTermPool), which is right -- an empty NBA slot would be worse
// than a distant one. What it lacked was any cue that it had done so, leaving a
// game 62 days out looking exactly like one tomorrow and the whole board reading
// as stale. Group by horizon so a quiet week is legible as a quiet week.
const BOARD_HORIZONS=[
  {key:'live',  label:'In play',        test:(m,now)=>m.status==='LIVE'},
  {key:'today', label:'Today',          test:(m,now)=>kickMs(m)&&kickMs(m)<now+86400000},
  {key:'week',  label:'This week',      test:(m,now)=>kickMs(m)&&kickMs(m)<now+7*86400000},
  {key:'later', label:'Further ahead',  test:()=>true}
];
function groupedBoardHTML(list){
  const now=Date.now(),buckets=new Map();
  list.forEach(m=>{
    const h=BOARD_HORIZONS.find(x=>x.test(m,now))||BOARD_HORIZONS[BOARD_HORIZONS.length-1];
    if(!buckets.has(h.key))buckets.set(h.key,[]);
    buckets.get(h.key).push(m);
  });
  return BOARD_HORIZONS.filter(h=>buckets.get(h.key)?.length).map(h=>{
    const games=buckets.get(h.key);
    return `<div class="boardHorizon"><span>${esc(h.label)}</span><i>${games.length} ${games.length===1?'game':'games'}</i></div>`+games.map(cardHTML).join('');
  }).join('');
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
    :`<div class="viewIntro"><div><div class="vhead">${t('Fixtures')}</div><p>${FORECAST_PAUSE_ACTIVE?'Fixtures, scores and market odds. Model picks are paused.':'Pregame model reads now; final scores and grading after the game.'}</p></div><span>${capped.length} games</span></div>`;
  const html=missing+landingHero()+(typeof collegeModules==='function'?collegeModules():'')+intro+
    (shown.length?(isAll?groupedBoardHTML(shown):shown.map(cardHTML).join('')):`<div class="empty" style="grid-column:1/-1">No upcoming matches to analyze.</div>`)+
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
function getProjectedSlots(){const slots=[];deriveStandings().forEach(g=>{const gl=groupLetter(g.group);(g.teams||[]).forEach(t=>{if(t.pos===1||t.pos===2)slots.push({slot:`${gl}${t.pos}`,team:t.name,code:t.code,pts:t.pts,gd:t.gd,live:t.live})})});getThirdRace().slice(0,8).forEach((t,i)=>slots.push({slot:`3rd #${i+1}`,team:t.team,code:t.code,pts:t.pts,gd:t.gd,live:t.live}));return slots}
/* removed duplicate (sourceName) */
/* removed duplicate (renderGroups) */
/* removed duplicate (bracketTeam) */
function bracketMatch(km,ri,mi,last=false){const pending=km.status==='LIVE',done=km.status==='FINISHED';const hs=km.score?.home,as=km.score?.away;const hw=done&&Number(hs)>Number(as),aw=done&&Number(as)>Number(hs);return `<div class="bracketMatch ${last?'':'hasNext'}"><div class="bmMeta"><span>${esc(km.stage||km.round||`Match ${mi+1}`)}</span><span>${pending?'AWAITING FINAL':done?'FT':km.kickoff?dt(km.kickoff):'TBD'}</span></div>${bracketTeam(km.home,km.home_code,'',done?hs:null,hw,false)}${bracketTeam(km.away,km.away_code,'',done?as:null,aw,false)}</div>`}
/* removed duplicate (projectedRounds) */
/* removed duplicate (renderBracket) */
function renderThird(){const host=$('#view-third'),third=getThirdRace();if(!third.length){host.innerHTML=`<div class="vhead">Third-place tracker</div><div class="empty">Third-place race not available yet.</div>`;return}const cut=third[7];host.innerHTML=`<div class="vhead">Third-place tracker</div><div class="thirdList"><div class="thirdHead"><span>Rank</span><span>Team</span><span>Group</span><span>Pts</span><span>GD</span><span>Status</span></div>${third.map((t,i)=>`<div class="thirdRow ${t.in?'in':'out'}"><div class="thirdRank">#${i+1}</div><div class="thirdTeam"><div class="name">${esc(t.code||'')} ${esc(t.team||'')} ${t.live?'<span class="liveMark">*</span>':''}</div><div class="group">${esc(t.group||'')} · GF ${t.gf??0}</div></div><div class="thirdNum">${esc(t.group||'')}</div><div class="thirdNum pts">${t.pts}</div><div class="thirdNum gd">${t.gd>0?'+':''}${t.gd}</div><div class="thirdBadge ${t.in?'in':''}">${t.in?'IN':'CHASE'}</div></div>`).join('')}<div class="thirdCut">Cut line: ${cut?`${esc(cut.team||cut.name)} at ${cut.pts} pts, GD ${cut.gd>0?'+':''}${cut.gd}`:'waiting for enough teams'}.</div></div>`}
/* removed duplicate (renderTitle) */
/* removed duplicate (renderEdge) */
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
function currentBuild(){return String(SYSTEM_UPDATES[0]?.date||'').replace(/^Build\s*/i,'').trim()||'dev';}
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

function renderStatus(){const host=$('#view-status'),M=DATA.matches||[],st=deriveStandings(),third=getThirdRace(),fresh=DATA.source_freshness||{};const up=M.filter(m=>m.status==='UPCOMING').length,fin=M.filter(m=>m.status==='FINISHED').length;const next=M.filter(isVisibleUpcoming).sort((a,b)=>(a.kickoff||'').localeCompare(b.kickoff||''))[0];host.innerHTML=`<div class="vhead">App Status</div><div class="hint" style="margin-bottom:10px">menu profile: <b>${esc(navProfile())}</b> · sport file: <b>${esc(DATA_FILE||'all (merged)')}</b></div><div class="status-grid"><div class="statuscard ${LAST_OK?'ok':'warn'}"><span class="slbl">Data file</span><div class="sval">${LAST_OK?'loaded':'not loaded'}</div><div class="hint">${LAST_ERROR?esc(LAST_ERROR):'Loaded'}</div></div><div class="statuscard info"><span class="slbl">Source</span><div class="sval">${esc(DATA.source_note||'unknown')}</div><div class="hint">${esc(fresh.primary_provider||'')}</div></div><div class="statuscard ${fresh.state==='fresh'?'ok':fresh.state?'warn':'info'}"><span class="slbl">Source freshness</span><div class="sval">${esc(fresh.state||'legacy snapshot')}</div><div class="hint">${esc(fresh.note||DATA.updated||'No source-age receipt')}</div></div><div class="statuscard info"><span class="slbl">Last successful</span><div class="sval">${fresh.last_successful_at?ago(fresh.last_successful_at):DATA.updated?ago(DATA.updated):'unknown'}</div><div class="hint">${esc(fresh.last_successful_at||DATA.updated||'—')}</div></div><div class="statuscard ${(DATA.quota_blocked_providers||[]).length?'warn':'ok'}"><span class="slbl">Provider quota</span><div class="sval">${(DATA.quota_blocked_providers||[]).length?'limited':'ok'}</div><div class="hint">${(DATA.quota_blocked_providers||[]).length?`${esc((DATA.quota_blocked_providers||[]).join(', '))} hit its safety reserve this run`:'no provider hit its safety reserve this run'}</div></div><div class="statuscard ${DATA.fixture_count_check?.anomaly?'warn':'ok'}"><span class="slbl">Fixture count</span><div class="sval">${DATA.fixture_count_check?.current??'—'}</div><div class="hint">${DATA.fixture_count_check?.anomaly?`well below the recent average of ${DATA.fixture_count_check.trailing_avg} — possible partial slate`:DATA.fixture_count_check?.trailing_avg!=null?`recent average ${DATA.fixture_count_check.trailing_avg}`:'building trailing history'}</div></div><div class="statuscard info"><span class="slbl">Matches</span><div class="sval">${M.length}</div><div class="hint">${up} upcoming · ${fin} final</div></div><div class="statuscard info"><span class="slbl">Groups</span><div class="sval">${st.length}</div><div class="hint">${third.length} third-place teams tracked</div></div><div class="statuscard info"><span class="slbl">News Items</span><div class="sval">${(DATA.news||[]).length}</div><div class="hint">${newsSources().filter(s=>s!=='all').join(' · ')}</div></div></div><div class="btnline"><button class="actionbtn" onclick="load(true)">Reload Data Now</button><button class="actionbtn" onclick="setView('groups')">Open Groups</button><button class="actionbtn" onclick="setView('third')">Open Thirds</button><button class="actionbtn" onclick="setView('updates')">System Updates</button></div>`}
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
  if(_alertEnabled('data')&&Array.isArray(DATA.quota_blocked_providers)&&DATA.quota_blocked_providers.length)out.push({t:'data',txt:`Some data is limited this run — ${DATA.quota_blocked_providers.join(', ')} hit its safety reserve, so a few signals may be missing even though the timestamp looks fresh.`,id:'quota'});
  if(_alertEnabled('data')&&DATA.fixture_count_check?.anomaly)out.push({t:'data',txt:`Fewer fixtures than usual this run (${DATA.fixture_count_check.current} vs. a recent average of ${DATA.fixture_count_check.trailing_avg}) — a provider may be returning a partial slate.`,id:'fixture-count'});
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
document.addEventListener('keydown',e=>{if(e.key==='Escape'&&navSheetOpen())closeNavSheet()});
document.addEventListener('click',e=>{if(navSheetOpen()&&!e.target.closest('#nav'))closeNavSheet()});
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
    if(!myHandle()||!assigned)assignHandle(); // first-time visitor, or force-migrates an old free-text handle
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
function setLbPeriod(p){try{localStorage.setItem('matchday.lbPeriod',p)}catch(e){};renderCommunity();}
function btmLoad(){try{return JSON.parse(localStorage.getItem('matchday.btm')||'{}')}catch(e){return {}}}
function btmSave(o){try{localStorage.setItem('matchday.btm',JSON.stringify(o))}catch(e){}}
function communityScope(){const k=String(DATA?.comp_key||'ALL').toUpperCase();return k==='ALL'?'ALL':k;}
function btmScoped(db){const scope=communityScope();if(scope==='ALL')return db;
  const picks={};Object.entries(db.picks||{}).forEach(([id,p])=>{if(String(p.comp||'WC').toUpperCase()===scope)picks[id]=p;});
  return {...db,picks};}
function isCommunityPickOpen(m){const kickoff=kickMs(m),now=Date.now();return m?.status==='UPCOMING'&&kickoff>now&&kickoff-now<=7*864e5&&!isStaleUpcoming(m)}
async function lockGlobalPick(matchId,pick,comp){
  const d=await lbPost('pick',{deviceId:deviceId(),matchId:String(matchId),pick,comp:String(comp||'').toLowerCase()});
  if(d&&d.ok)applyAccount(d);
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
