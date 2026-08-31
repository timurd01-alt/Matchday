function scorecardAuditCount(v,preferred='total'){if(v==null)return 0;if(typeof v==='object')return Number(v[preferred]??v.total??v.graded??v.count)||0;return Number(v)||0}
function scorecardMarketComparisonPick(p){if(['h','d','a'].includes(p?.market_comparison_pick))return p.market_comparison_pick;return p?.outcome_basis==='ultimate_winner'||p?.prediction_snapshot?.is_knockout?p?.regulation_pick:p?.pick}
function scorecardUnderdogTag(p){if(!p?.upset_score||!p?.upset_snapshot?.radar||p?.upset_snapshot?.standings_gap_pct==null)return'';const name=esc(p.upset_name||'Underdog'),score=esc(p.upset_score);if(!p.upset_triggered)return` <i class="scsplit upsetTag">underdog risk · ${name} ${score}/100</i>`;const outcome=p.result?(p.upset_hit?' &#10003;':' &#10007;'):'';return` <i class="scsplit upsetTag">upset pick · ${name} ${score}/100${outcome}</i>`}
// The scorecard is deliberately two numbers.
//
// It used to carry Brier, log loss, calibration bands, CLV, upset radar,
// home/away splits and four audit buckets. Those are real measurements and the
// modules that compute them are untouched -- market_benchmark.py and the
// research posts still report them. They are not on this page any more because
// a reader asking "is it any good" wants a record, and thirty cards answered a
// question nobody had asked yet.
//
// Won and lost come from graded picks only. A pick that is locked but not yet
// final is pending and counts toward neither.
function renderScore(){
  const sc=DATA.scorecard||{},host=$('#view-score');
  const graded=Number(sc.graded)||0;
  const won=Number(sc.model_hits)||0;
  const lost=Math.max(0,graded-won);
  const pending=Number(sc.pending)||0;
  const graded_rows=(sc.picks||[]).filter(p=>p.result);

  // Nothing graded is the honest state right now: no college pick has ever
  // been graded, and forecasting is paused, so the record starts at zero
  // rather than borrowing another sport's history.
  const note=graded
    ? `<div class="hint" style="margin-top:10px">${graded} graded${pending?` \u00b7 ${pending} awaiting a final score`:''}</div>`
    : `<div class="empty">No picks graded yet. Picks lock before kickoff and are graded once the game is final.${pending?` ${pending} locked and awaiting a result.`:''}</div>`;

  const log=graded_rows.length
    ? `<div class="seclbl" style="margin-top:16px">Pick log</div>`+graded_rows.map(p=>{
        const hit=!!p.model_hit;
        return `<div class="scrow ${hit?'hit':'miss'}"><span class="scmatch">${esc(p.home)} v ${esc(p.away)}</span><span class="scbadge">${hit?'WON':'LOST'}</span></div>`;
      }).join('')
    : '';

  host.innerHTML=`<div class="vhead">Scorecard</div>
<div class="status-grid">
  <div class="statuscard ${won?'ok':'info'}"><span class="slbl">Picks won</span><div class="sval">${won}</div></div>
  <div class="statuscard info"><span class="slbl">Picks lost</span><div class="sval">${lost}</div></div>
</div>${note}${log}
<div class="edisc">Only picks locked before kickoff are graded. Displayed scores are factual and unchanged. Probabilities remain estimates.</div>`;
}
function highlightFavoriteRows(){if(!favoriteTeam())return;document.querySelectorAll('.gtable .gteam').forEach(cell=>{if(teamKey(cell.textContent).includes(teamKey(favoriteTeam())))cell.closest('tr')?.classList.add('favoriteTeamRow')})}
function renderCurrent(){captureSignalsIfFresh();({matches:renderMatches,results:renderResults,groups:renderStandings,bracket:renderBracket,score:renderScore,news:renderNews,community:renderCommunity}[VIEW]||renderMatches)();renderWelcome();highlightFavoriteRows();applyStaticI18n()}
function renderStrip(){const M=DATA.matches||[],next=M.filter(isVisibleUpcoming).sort((a,b)=>(a.kickoff||'').localeCompare(b.kickoff||''))[0];const parts=[];
const isSample=(DATA.source_note||'').toLowerCase().includes('sample');
const freshness=DATA.source_freshness||{},fallback=freshness.state==='fallback';
parts.push(isSample?`<span class="ls-badge sample">${t("sample data")}</span>`:`<span class="ls-badge ok">${t("data feed")}</span>`);
const streakStats=btmStats(btmGrade());
if(streakStats.streak>=2)parts.push(`<span class="ls-streak" title="Beat the Model: ${streakStats.streak} correct in a row" onclick="setView('community')">\u{1F525} ${streakStats.streak}</span>`);
if(next)parts.push(`<span class="ls-next ls-clickable" data-mid="${esc(next.id)}" onclick="openMatchModal(this.dataset.mid)" role="button" tabindex="0" title="Open expanded view">Next · <b>${esc(next.home.code)} v ${esc(next.away.code)}</b> ${kickIn(next.kickoff)}</span>`);else parts.push(`<span class="ls-next">No upcoming fixtures</span>`);parts.push(`<span class="ls-upd">${fallback?`<b class="stale">fallback snapshot ${ago(freshness.last_successful_at||DATA.updated)}</b> · `:(()=>{try{const a=(Date.now()-new Date(DATA.updated))/60000;if(a>360)return `<b class="stale">data ${ago(DATA.updated)}</b> · `;}catch(e){}return 'Updated '+ago(DATA.updated)+' · ';})()}${t("independent · built for fans")} · <b style="color:var(--signal)">build ${currentBuild()}</b></span>`);$('#strip').innerHTML=parts.join('')}
/* removed duplicate (diverseNews) */
/* removed duplicate (renderInsight) */
function setView(v){VIEW=safeView(v);v=VIEW;if(typeof closeNavSheet==='function')closeNavSheet();
  // Leaving the board is the signal that the visitor wants more than the board
  // payload holds. Renders now from what's loaded, then again once the full
  // per-sport files arrive.
  if(!DATA_FILE&&DATA?._summary&&VIEWS_NEEDING_FULL_DATA.has(v))escalateAllSports();document.querySelectorAll('.navbtn[data-v]').forEach(b=>b.setAttribute('aria-pressed',b.dataset.v===v));document.querySelectorAll('.view').forEach(el=>el.style.display=el.id==='view-'+v?((v==='matches'||v==='results')?'grid':'block'):'none');renderCurrent();const active=$('#view-'+v);if(active){active.classList.remove('viewEntering');void active.offsetWidth;active.classList.add('viewEntering')}}
$('#nav').addEventListener('click',e=>{const b=e.target.closest('.navbtn[data-v]');if(b?.dataset.v)setView(b.dataset.v)});
function aggregateScorecards(datasets){
  const sources=(datasets||[]).filter(d=>d?.scorecard).map(d=>({comp:d.comp_key||d.competition||'',sc:d.scorecard}));
  if(!sources.length)return null;
  const sum=key=>sources.reduce((n,x)=>n+(Number(x.sc[key])||0),0);
  const weighted=(key,countKey='graded',digits=3,strictCount=false)=>{let total=0,n=0;sources.forEach(({sc})=>{const v=Number(sc[key]),w=Number(strictCount?sc[countKey]:(sc[countKey]??sc.graded));if(Number.isFinite(v)&&w>0){total+=v*w;n+=w}});return n?Number((total/n).toFixed(digits)):null};
  const out={graded:sum('graded'),pending:sum('pending'),model_hits:sum('model_hits'),
    market_graded:sum('market_graded'),market_hits:sum('market_hits'),
    post_lock_market_graded:sum('post_lock_market_graded'),post_lock_market_hits:sum('post_lock_market_hits'),
    disagree:sum('disagree'),disagree_hits:sum('disagree_hits')};
  out.brier_graded=sum('brier_graded');out.brier=weighted('brier','brier_graded',3,true);out.brier3_graded=sum('brier3_graded');out.log_loss_graded=sum('log_loss_graded');out.brier3=weighted('brier3','brier3_graded',3,true);out.log_loss=weighted('log_loss','log_loss_graded',3,true);
  out.advancement_graded=sum('advancement_graded');out.log_loss_advancement_graded=sum('log_loss_advancement_graded');out.brier_advancement=weighted('brier_advancement','advancement_graded',3,true);out.log_loss_advancement=weighted('log_loss_advancement','log_loss_advancement_graded',3,true);
  out.clv_n=sum('clv_n');out.clv_avg=weighted('clv_avg','clv_n',1);out.clv_beat=sum('clv_beat');

  const bands=new Map();sources.forEach(({sc})=>(sc.calibration||[]).forEach(c=>{const row=bands.get(c.band)||{band:c.band,n:0,hits:0};row.n+=Number(c.n)||0;row.hits+=Number(c.hits)||0;bands.set(c.band,row)}));
  out.calibration=[...bands.values()];
  const combineSplit=key=>{const merged={};sources.forEach(({sc})=>Object.entries(sc[key]||{}).forEach(([side,v])=>{const row=merged[side]||{n:0,hits:0};row.n+=Number(v?.n)||0;row.hits+=Number(v?.hits)||0;merged[side]=row}));return merged};
  out.home_away=combineSplit('home_away');
  out.market_agreement=combineSplit('market_agreement');
  const combineRate=(path)=>{let n=0,hits=0,beTotal=0,beN=0;sources.forEach(({sc})=>{const v=path.reduce((o,k)=>o?.[k],sc)||{};const vn=Number(v.n)||0;n+=vn;hits+=Number(v.hits)||0;if(v.be!=null&&vn){beTotal+=Number(v.be)*vn;beN+=vn}});return {n,hits,be:beN?Math.round(beTotal/beN):null}};
  out.value={all:combineRate(['value','all']),chances:combineRate(['value','chances']),pending:sources.reduce((n,{sc})=>n+(Number(sc.value?.pending)||0),0)};
  out.signal_quality={};sources.forEach(({sc})=>Object.entries(sc.signal_quality||{}).forEach(([k,v])=>{const row=out.signal_quality[k]||{n:0,hits:0};row.n+=Number(v.n)||0;row.hits+=Number(v.hits)||0;out.signal_quality[k]=row}));
  const upsetWatched=sources.reduce((n,{sc})=>n+(Number(sc.upset?.watched)||0),0);
  const upsetScoreTotal=sources.reduce((n,{sc})=>n+((Number(sc.upset?.avg_score)||0)*(Number(sc.upset?.watched)||0)),0);
  out.upset={watched:upsetWatched,hits:sources.reduce((n,{sc})=>n+(Number(sc.upset?.hits)||0),0),triggered:sources.reduce((n,{sc})=>n+(Number(sc.upset?.triggered)||0),0),triggered_hits:sources.reduce((n,{sc})=>n+(Number(sc.upset?.triggered_hits)||0),0),avg_score:upsetWatched?Number((upsetScoreTotal/upsetWatched).toFixed(1)):null};
  out.picks=sources.flatMap(({comp,sc})=>(sc.picks||[]).map(p=>({...p,_comp:comp}))).sort((a,b)=>String(b.kickoff||'').localeCompare(String(a.kickoff||''))).slice(0,80);
  out.misses=sources.flatMap(({comp,sc})=>(sc.misses||[]).map(m=>({...m,_comp:comp}))).slice(0,20);

  // Newer scorecards expose provenance exclusions. Keep each class separate;
  // never fold unverifiable history into the official graded denominator.
  const provenance={legacy:['legacy','legacy_count','legacy_picks'],quarantined:['quarantined','quarantined_count','quarantined_picks'],late_unverifiable:['late_unverifiable','late_unverifiable_count'],excluded:['excluded','excluded_count']};
  Object.entries(provenance).forEach(([name,keys])=>{let present=false,scalar=0,nested=null;sources.forEach(({sc})=>{for(const key of keys){const v=sc[key]??sc.provenance?.[key];if(v==null)continue;present=true;if(v&&typeof v==='object'&&!Array.isArray(v)){nested=nested||{};['total','graded','pending','model_hits','count'].forEach(k=>{if(v[k]!=null)nested[k]=(Number(nested[k])||0)+(Number(v[k])||0)});if(v.label&&!nested.label)nested.label=v.label}else scalar+=Array.isArray(v)?v.length:(Number(v)||0);break}});if(present){if(nested){nested.total=(Number(nested.total)||0)+scalar;if(nested.graded&&nested.model_hits!=null)nested.accuracy=Number((nested.model_hits/nested.graded*100).toFixed(1));out[name]=nested}else out[name]=scalar}});
  // The all-time tally has to be rebuilt from the merged per-sport figures,
  // not summed from each sport's own `combined` block: on the All-sports
  // board (the default view) this aggregate IS the scorecard, so without
  // this the "All-time total" card silently disappears on the exact screen
  // most people land on, which is where it's most worth showing.
  const legacyGraded=Number(out.legacy?.graded ?? out.quarantined?.graded)||0;
  const legacyHits=Number(out.legacy?.model_hits ?? out.quarantined?.model_hits)||0;
  const combinedGraded=(Number(out.graded)||0)+legacyGraded;
  const combinedHits=(Number(out.model_hits)||0)+legacyHits;
  out.combined={graded:combinedGraded,model_hits:combinedHits,
    accuracy:combinedGraded?Number((combinedHits/combinedGraded*100).toFixed(1)):null,
    verified_graded:Number(out.graded)||0,verified_hits:Number(out.model_hits)||0,
    legacy_graded:legacyGraded,legacy_hits:legacyHits,
    note:'Includes legacy/migrated picks without recoverable proof of pregame timing alongside verified pregame-locked picks. See the pick log below for which is which.'};
  return out;
}
// A unique ?_=<timestamp> on every poll made each request a distinct URL, so
// no browser or CDN cache could ever serve or revalidate it: each refresh
// re-downloaded the full payload -- 9.8MB across the all-sports view -- to
// receive bytes that only change when the hourly build publishes. cache
// 'no-cache' revalidates instead of guessing: the browser sends the ETag it
// holds and a server with nothing new answers 304 with no body at all. Data
// arrives exactly as promptly, having cost a few hundred bytes instead of
// megabytes. Not 'no-store', which would forbid keeping a copy to revalidate
// against and put us straight back to full downloads.
const REVALIDATE={cache:'no-cache'};
// Views that need more than the landing board holds -- full season history, the
// research detail behind a pick, standings. Opening one escalates the merged
// "All sports" view from the summary payload to the real per-sport files.
const VIEWS_NEEDING_FULL_DATA=new Set(['results','groups','title','edge','score','bracket','third','tott','tree','sandbox']);
let ALL_SPORTS_FULL=false;
function allSportsNeedsFull(){return ALL_SPORTS_FULL||VIEWS_NEEDING_FULL_DATA.has(VIEW)}
// Escalate on demand: called when a visitor leaves the board or opens a match,
// so the cost of the full files is paid by people who asked for what's in them.
async function escalateAllSports(){
  if(DATA_FILE||!DATA?._summary||ALL_SPORTS_FULL)return;
  ALL_SPORTS_FULL=true;
  await load(true);
}
async function load(manual=false){if(LOAD_TIMER){clearTimeout(LOAD_TIMER);LOAD_TIMER=null}try{
  let usedSummary=false;
  if(!DATA_FILE&&!allSportsNeedsFull()){
    // The landing board needs a slate and a scorecard, not twelve seasons of
    // fixtures and the research detail behind every one of them. board_summary
    // .json carries exactly what this view renders; if it is missing or stale
    // the merge below still works, just slowly, so a failed build degrades to
    // the old behaviour rather than to an empty page.
    const summary=await fetch('board_summary.json',REVALIDATE).then(r=>r.ok?r.json():null).catch(()=>null);
    if(summary&&(summary.matches||[]).length){
      applyForecastPublicationPauses(summary);
      DATA=Object.assign({},summary,{
        scorecard:aggregateScorecards(summary.scorecard_sources||[]),
        standings:[],third_race:[],scorers:[],leaders:{},bracket:[],
        _summary:true});
      delete DATA.scorecard_sources;
      usedSummary=true;
    }
  }
  if(usedSummary){/* board payload already in DATA */}
  else if(!DATA_FILE){ // ALL SPORTS: merge every sport file that exists
    // NHL is retired for now: data_nhl.json is not published, so asking for it
    // cost every visitor a 404 on every load. The NHL entries elsewhere (labels,
    // score units, sandbox sizes) stay put so restoring the sport is a one-word
    // change here rather than a hunt.
    const keys=ALL_SPORT_KEYS;
    const results=await Promise.all(keys.map(k=>fetch('data_'+k+'.json',REVALIDATE).then(r=>r.ok?r.json():null).catch(()=>null)));
    let base=null;const merged=[];let news=[];let latest='';
    const titleBySport=[];
    results.forEach((d,i)=>{if(!d)return;applyForecastPublicationPauses(d);if(!base)base=d;
      if(COLLEGE_BOARD_KEYS.has(keys[i]))(d.matches||[]).forEach(m=>{m._comp=(d.comp_key||keys[i].toUpperCase());merged.push(m);});
      const comp=d.comp_key||keys[i].toUpperCase();
      const compLabel=SPORT_LABELS[String(comp).toLowerCase()]||d.competition||comp;
      if(COLLEGE_BOARD_KEYS.has(keys[i])){const currentNews=(d.news||[]).filter(isFreshNews).sort((a,b)=>newsTime(b)-newsTime(a));news=news.concat(currentNews.slice(0,8).map(a=>({...a,_comp:a.competition||comp,feed:compLabel})));}
      if((d.updated||'')>latest)latest=d.updated;
      const top=(d.title_odds||[])[0];
      if(top)titleBySport.push({comp,label:compLabel,team:top.team,code:top.code,pct:top.pct});});
    if(!base){const r0=await fetch('data.json',REVALIDATE);if(!r0.ok)throw new Error('no data files yet — run a fetch');base=await r0.json();(base.matches||[]).forEach(m=>merged.push(m));news=base.news||[];latest=base.updated;}
    merged.sort((a,b)=>(a.kickoff||'').localeCompare(b.kickoff||''));
    DATA=Object.assign({},base,{matches:merged,news:news,updated:latest,competition:'All sports',comp_key:'ALL',standings:[],third_race:[],scorers:[],leaders:{},scorecard:aggregateScorecards(results.some(Boolean)?results:[base]),title_by_sport:titleBySport});
  } else {
    const r=await fetch(DATA_FILE,REVALIDATE);if(!r.ok)throw new Error('HTTP '+r.status);DATA=stripPastSeasonCompetitionViews(await r.json());applyForecastPublicationPauses(DATA);
  }DATA.news=(DATA.news||[]).filter(isFreshNews).sort((a,b)=>newsTime(b)-newsTime(a));BYID={};(DATA.matches||[]).forEach(m=>BYID[m.id]=m);LAST_OK=true;LAST_ERROR='';const cn=$('#compName');if(cn)cn.textContent=DATA.competition?' · '+DATA.competition:'';const tb=document.querySelector('.navbtn[data-v="third"]');if(tb)tb.style.display=(DATA.third_race&&DATA.third_race.length)?'':'none';const gb2=document.querySelector('.navbtn[data-v="groups"]');if(gb2)gb2.style.display=(DATA.standings&&DATA.standings.length)?'':'none';// .some() passes (element,index): the index landed on isForecastPaused's
  // `payload` parameter, so the competition check read match._comp, which only
  // the merged build sets -- the banner fired on every board except MLB's own.
  // Scoped to the MLB board as well: in the merged "All sports" view MLB's
  // fixtures sit alongside eleven other competitions, and announcing "Forecast
  // paused" above all of them read as the whole site being down. Paused MLB
  // cards still carry their own pause shell there.
  const paused=(DATA.matches||[]).some(m=>isForecastPaused(m));$('#banner').innerHTML=paused?`<div class="marketBanner"><b>Predictions are paused.</b> ${esc(FORECAST_PAUSE_MESSAGE)} Everything else is unaffected: live scores, final results, standings, stats, Elo and market odds all keep updating. <a href="qa.html#pause">Why, and what comes next</a></div>`:DATA.markets_quota_out?`<div class="marketBanner"><b>Market odds temporarily unavailable.</b> Our monthly betting-market data quota is used up, so market comparisons are paused. The model's own predictions still work normally — market lines return when the quota resets.</div>`:'';applySportNav();renderStrip();renderInsight();renderCurrent();applyStaticI18n();renderAlerts()}catch(e){console.error(e);applySportNav();
  const sel=currentSportKey();
  if(sel&&(!DATA||((DATA.comp_key||'').toLowerCase()!==sel))){
    DATA={matches:[],news:[],standings:[],third_race:[],bracket:null,scorecard:null,title_odds:[],scorers:[],team_of_tournament:null,
          comp_key:sel.toUpperCase(),competition:(SPORT_LABELS[sel]||sel),updated:'',_missing:true};
    BYID={};
  }
  applySportNav();LAST_OK=false;LAST_ERROR=String(e.message||e);$('#strip').textContent='no data';const selKey=(DATA_FILE.match(/data_(\w+)\.json/)||[])[1];$('#view-matches').innerHTML=`<div class="empty" style="grid-column:1/-1">${selKey?`No ${esc(SPORT_LABELS[selKey]||selKey.toUpperCase())} data yet.<br><span class="faintline">Run start_${esc(selKey)}.bat once to pull it, or <a href="#" onclick="changeSport('');return false" style="color:var(--signal)">switch back to Auto</a>.</span>`:`Data file not loaded.<br><span class="faintline">${esc(LAST_ERROR)}</span>`}</div>`;if(VIEW==='status')renderStatus()}finally{const ss=$('#sportSel');if(ss)ss.value=(DATA_FILE.match(/data_(\w+)\.json/)||['',''])[1];scheduleNextLoad()}}
function scheduleNextLoad(){if(LOAD_TIMER)clearTimeout(LOAD_TIMER);LOAD_TIMER=setTimeout(()=>load(),Math.max(30,Number(SETTINGS.refresh)||60)*1000)}


/* ===== UI PATCH: keep data untouched; improve news source logic and match opening ===== */
/* removed duplicate (_srcClean) */
/* removed duplicate (_srcFromTitle) */
/* removed duplicate (_srcFromLink) */
/* removed duplicate (sourceName) */
/* removed duplicate (feedName) */
/* removed duplicate (newsBuckets) */
/* removed duplicate (newsSources) */
/* removed duplicate (diverseNews) */
/* removed duplicate (renderNews) */
// Polls and Matchday rankings are separate tables; keep their provenance
// visible even though the college table renderer is shared with conferences.
const _renderGroupsWithRankingSources=renderGroups;
renderGroups=function(){
  _renderGroupsWithRankingSources();
  if(!['NCAAF','NCAAM'].includes(String(DATA.comp_key||'').toUpperCase()))return;
  document.querySelectorAll('#view-groups .groupHead').forEach(head=>{
    const label=String(head.childNodes[0]?.textContent||'').trim();
    const note=head.querySelector('span');
    if(!note)return;
    if(label==='Matchday Top 25')note.textContent='Matchday model · separate from the poll';
    else if(/(?:AP Top 25|playoff|coaches|national poll)/i.test(label))note.textContent='official national poll';
  });
};
/* dedup */
function ensureMatchModal(){let modal=document.getElementById('matchModal');if(modal)return modal;modal=document.createElement('div');modal.id='matchModal';modal.className='matchModal';modal.addEventListener('click',e=>{if(e.target===modal)closeMatchModal()});document.body.appendChild(modal);return modal}

/* ===== Team Stats — compiled per-team profile, one page per team =========
   Every number here is data the app already collects (standings, form,
   class/Elo rating, split form, schedule) -- no new data source. No
   individual player stats: only soccer's top-20 scorers are ever
   available, and NFL/NBA have no free player-stat access at all, so a
   "per player" page would be mostly empty for most players. */
function ensureTeamModal(){let modal=document.getElementById('teamModal');if(modal)return modal;modal=document.createElement('div');modal.id='teamModal';modal.className='matchModal teamModal';modal.addEventListener('click',e=>{if(e.target===modal)closeTeamModal()});document.body.appendChild(modal);return modal}
function closeTeamModal(){const modal=document.getElementById('teamModal');if(modal)modal.classList.remove('show');document.body.classList.remove('modalOpen')}
function computeTeamProfile(name){
  const key=teamKey(name);
  let standRec=null;
  (DATA.standings||[]).filter(g=>g.table_type!=='power_ratings').forEach(g=>(g.teams||[]).forEach(t=>{if(teamKey(t.name)===key)standRec=t;}));
  const matches=(DATA.matches||[]).filter(m=>teamKey(m.home?.name)===key||teamKey(m.away?.name)===key);
  let side=null;
  for(const m of matches){side=(teamKey(m.home?.name)===key)?m.home:(teamKey(m.away?.name)===key?m.away:null);if(side)break;}
  const rec=standRec||side||{name};
  const finished=matches.filter(m=>m.status==='FINISHED').sort((a,b)=>(b.kickoff||'').localeCompare(a.kickoff||''));
  const next=matches.filter(isVisibleUpcoming).sort((a,b)=>(a.kickoff||'').localeCompare(b.kickoff||''))[0];
  return {
    name: rec.name||name, code: rec.code||side?.code||'',
    pos: rec.pos??null, pld: rec.pld??side?.pld??0, w: rec.w??null, d: rec.d??null, l: rec.l??null,
    gf: rec.gf??side?.gf??0, ga: rec.ga??side?.ga??0, gd: rec.gd??side?.gd??0,
    pts: rec.pts??side?.pts??0, form: rec.form||side?.form||'',
    formHome: side?.form_home||'', formAway: side?.form_away||'',
    rating: side?.rating??rec.rating??null,
    next, recent: finished.slice(0,5)
  };
}
function teamProfileHTML(p){
  const twoWay=SANDBOX_TWO_WAY.has(String(DATA.comp_key||'').toLowerCase());
  const unit=_totalsUnit({});
  const diffLabel=`${unit[0].toUpperCase()+unit.slice(1)} diff`;
  const winPct=p.pld?((Number(p.w)||0)/p.pld*100).toFixed(1)+'%':'—';
  const formRow=(label,str)=>str?`<div class="tpFormRow"><span class="tpFormLbl">${esc(label)}</span><span class="tpFormDots">${str.trim().split(' ').map(r=>`<i class="tpDot ${r}">${esc(r)}</i>`).join('')}</span></div>`:'';
  const recentRows=(p.recent||[]).map(m=>{
    const home=teamKey(m.home.name)===teamKey(p.name);
    const opp=home?m.away:m.home;
    const gf=home?m.score?.home:m.score?.away, ga=home?m.score?.away:m.score?.home;
    const res=gf>ga?'W':gf<ga?'L':'D';
    return `<div class="tpRecentRow"><i class="tpDot ${res}">${res}</i><span>${home?'vs':'@'} ${esc(opp.code||opp.name)}</span><b>${gf}-${ga}</b><span class="tpFaint">${esc(dt(m.kickoff).split(', ').pop()||'')}</span></div>`;
  }).join('');
  const nextLine=p.next?`<div class="tpNext"><span class="tpFaint">Next</span> ${teamKey(p.next.home.name)===teamKey(p.name)?'vs':'@'} <b>${esc(teamKey(p.next.home.name)===teamKey(p.name)?p.next.away.code||p.next.away.name:p.next.home.code||p.next.home.name)}</b> · ${kickIn(p.next.kickoff)}</div>`:'';
  const record=(p.w!=null)?`${p.w}-${p.l}${!twoWay&&p.d!=null?`-${p.d}`:''}`:'—';
  return `<div class="tpHead"><button class="modalClose" onclick="closeTeamModal()" aria-label="Close">×</button>
    <div class="tpCode">${esc(p.code)}</div><div class="tpName">${esc(p.name)}</div>
    <div class="tpMeta">${p.pos?`#${p.pos} · `:''}${p.pld} played · record ${record}</div></div>
    <div class="tpBody">
      <div class="tpStatGrid">
        <div class="tpStat"><span class="tpStatLbl">${twoWay?'Win%':'Points'}</span><b>${twoWay?winPct:p.pts}</b></div>
        <div class="tpStat"><span class="tpStatLbl">${diffLabel}</span><b>${p.gd>0?'+':''}${p.gd}</b></div>
        <div class="tpStat"><span class="tpStatLbl">For</span><b>${p.gf}</b></div>
        <div class="tpStat"><span class="tpStatLbl">Against</span><b>${p.ga}</b></div>
        <div class="tpStat"><span class="tpStatLbl">Class rating</span><b>${p.rating!=null?p.rating.toFixed(1):'—'}</b></div>
      </div>
      ${formRow('Overall form',p.form)}
      ${formRow('Home form',p.formHome)}
      ${formRow('Away form',p.formAway)}
      ${nextLine}
      ${recentRows?`<div class="tpSeclbl">Recent results</div>${recentRows}`:''}
    </div>`;
}
function openTeamModal(name){
  const p=computeTeamProfile(name);
  const modal=ensureTeamModal();
  modal.innerHTML=`<section class="matchSheet teamSheet" role="dialog" aria-modal="true">${teamProfileHTML(p)}</section>`;
  modal.classList.add('show');document.body.classList.add('modalOpen');
}
/* modalModel removed */
/* removed duplicate (openMatchModal) */
function closeMatchModal(){const modal=document.getElementById('matchModal');if(modal)modal.classList.remove('show');document.body.classList.remove('modalOpen')}
document.addEventListener('keydown',e=>{if(e.key==='Escape')closeMatchModal()});
/* removed duplicate (cardHTML) */



/* ===== PATCH: better source diversity + compact two-sided bracket ===== */
const _ISO3={AFG:'AF',ALB:'AL',ALG:'DZ',AND:'AD',ANG:'AO',ARG:'AR',ARM:'AM',AUS:'AU',AUT:'AT',AZE:'AZ',BAH:'BS',BHR:'BH',BAN:'BD',BEL:'BE',BIH:'BA',BOL:'BO',BRA:'BR',BUL:'BG',CAM:'CM',CAN:'CA',CHI:'CL',CHN:'CN',COL:'CO',CRC:'CR',CRO:'HR',CUB:'CU',CZE:'CZ',DEN:'DK',DOM:'DO',ECU:'EC',EGY:'EG',ENG:'GB',ESP:'ES',FIN:'FI',FRA:'FR',GER:'DE',GHA:'GH',GRE:'GR',GUA:'GT',HAI:'HT',HON:'HN',HUN:'HU',IND:'IN',IDN:'ID',IRN:'IR',IRQ:'IQ',IRL:'IE',ISR:'IL',ITA:'IT',JAM:'JM',JPN:'JP',KOR:'KR',KUW:'KW',MAR:'MA',MEX:'MX',NED:'NL',NOR:'NO',NZL:'NZ',PAN:'PA',PAR:'PY',PER:'PE',POL:'PL',POR:'PT',QAT:'QA',ROU:'RO',RSA:'ZA',RUS:'RU',KSA:'SA',SCO:'GB',SEN:'SN',SRB:'RS',SUI:'CH',SVK:'SK',SVN:'SI',SWE:'SE',TUN:'TN',TUR:'TR',UKR:'UA',URU:'UY',USA:'US',VEN:'VE',WAL:'GB',CPV:'CV',CIV:'CI',CUW:'CW'};
function flagEmoji(code){code=String(code||'').toUpperCase().trim();let c=_ISO3[code]||(/^[A-Z]{2}$/.test(code)?code:'');if(!c)return'';return c.replace(/./g,ch=>String.fromCodePoint(127397+ch.charCodeAt(0)))}
function codeForTeam(name,explicit){if(explicit)return explicit;const n=String(name||'').toLowerCase();for(const g of DATA.standings||[])for(const t of g.teams||[])if(String(t.name||'').toLowerCase()===n)return t.code||'';for(const m of DATA.matches||[]){if(String(m.home?.name||'').toLowerCase()===n)return m.home.code||'';if(String(m.away?.name||'').toLowerCase()===n)return m.away.code||''}return''}
function bracketTeam(name,code,slot,score,win,live){const nm=name||'TBD',cd=codeForTeam(nm,code),fl=uiFlag(cd);return `<div class="bmTeam ${win?'win':''} ${live?'live':''}"><div class="bmName">${slot?`<span class="bmSlot">${esc(slot)}</span>`:''}${fl?`<span class="flag">${fl}</span>`:''}<span class="bmCode">${esc(cd||'')}</span><span>${nm==='TBD'?'<span class="bmTbd">TBD</span>':esc(nm)}</span></div><div class="bmScore">${score!=null?esc(score):''}</div></div>`}
function compactBracketMatch(km,last=false,side='left',isFinal=false){const pending=km.status==='LIVE',done=km.status==='FINISHED';const hs=km.score?.home,as=km.score?.away;const hw=done&&Number(hs)>Number(as),aw=done&&Number(as)>Number(hs);const cls=`brMini ${done?'done':''} ${isFinal?'finalCard':''} ${last?'':side==='right'?'connectL':'connectR'} ${(!km.home&&!km.away)?'tbd':''}`;return `<div class="${cls}">${isFinal?'<div class="finalBadge">Final</div>':''}<div class="bmMeta"><span>${esc(km.stage||km.round||'Match')}</span><span>${pending?'AWAITING FINAL':done?'FT':km.kickoff?dt(km.kickoff):'TBD'}</span></div>${bracketTeam(km.home,km.home_code||km.homeCode||'',km.home_slot||'',done?hs:null,hw,false)}${bracketTeam(km.away,km.away_code||km.awayCode||'',km.away_slot||'',done?as:null,aw,false)}</div>`}
/* removed duplicate (compactProjectedMatch) */
/* removed duplicate (roundMatches) */
function shortRoundName(name){return name.replace('Round of ','R').replace('Quarter-finals','QF').replace('Semi-finals','SF').replace('Third-place playoff','3rd')}
/* removed duplicate (bracketColumn) */
/* removed duplicate (renderBracket) */

function _srcClean(x){x=String(x||'').replace(/\s+/g,' ').trim();if(!x)return'';x=x.replace(/^www\./i,'').replace(/\.com$/i,'');const map=[[/espn|espn fc/i,'ESPN'],[/bbc/i,'BBC Sport'],[/guardian/i,'The Guardian'],[/sky\s*sports|skysports/i,'Sky Sports'],[/cbs/i,'CBS Sports'],[/fox\s*sports|foxsports/i,'FOX Sports'],[/reuters/i,'Reuters'],[/associated\s*press|^ap$/i,'Associated Press'],[/fifa/i,'FIFA'],[/le\s*monde|lemonde/i,'Le Monde'],[/marca/i,'Marca'],[/goal/i,'Goal'],[/yahoo/i,'Yahoo Sports'],[/nbc/i,'NBC Sports'],[/google\s*news/i,'Google News']];for(const [re,n] of map)if(re.test(x))return n;return x.split('|')[0].trim()}
function newsTime(a){const ts=Date.parse(a?.published||'');return Number.isFinite(ts)?ts:0}
function isFreshNews(a){const ts=newsTime(a),age=Date.now()-ts;return !!ts&&age>=-24*3600000&&age<=7*86400000}
function _srcFromTitle(a){const h=String(a.headline||a.title||'');const parts=h.split(/\s[-–—]\s/g).map(x=>x.trim()).filter(Boolean);if(parts.length>1){const tail=parts[parts.length-1];if(tail.length<=42&&!/world cup|football|soccer|latest|news|live/i.test(tail))return _srcClean(tail)}return''}
function _srcFromLink(a){try{const u=new URL(a.link||a.url||'',location.href);let h=u.hostname.replace(/^www\./,'');if(h.includes('news.google.'))return'';if(h.includes('espn'))return'ESPN';if(h.includes('bbc'))return'BBC Sport';if(h.includes('theguardian'))return'The Guardian';if(h.includes('skysports'))return'Sky Sports';if(h.includes('cbssports'))return'CBS Sports';if(h.includes('foxsports'))return'FOX Sports';if(h.includes('reuters'))return'Reuters';if(h.includes('apnews'))return'Associated Press';if(h.includes('fifa'))return'FIFA';if(h.includes('marca'))return'Marca';if(h.includes('goal'))return'Goal';return _srcClean(h.split('.')[0])}catch(e){return''}}
function sourceName(a){const raw=_srcClean(a.source_name||a.publisher||a.provider||a.source||a.feed_source||'');const feed=_srcClean(a.feed||'');const titleSrc=_srcFromTitle(a),linkSrc=_srcFromLink(a);const generic=s=>!s||/^(news|headlines|football|soccer|rss|google news|world cup)$/i.test(s);if(raw&&!generic(raw))return raw;if(titleSrc&&!generic(titleSrc))return titleSrc;if(linkSrc&&!generic(linkSrc))return linkSrc;if(feed&&!generic(feed))return feed;return raw||feed||'News'}
function feedName(a){const f=_srcClean(a.feed||'');return f&&f!==sourceName(a)?f:''}
function newsBuckets(){const buckets={};(DATA.news||[]).filter(isFreshNews).forEach((a,i)=>{const src=sourceName(a);(buckets[src] ||= []).push({...a,_idx:i})});Object.values(buckets).forEach(items=>items.sort((a,b)=>newsTime(b)-newsTime(a)));return buckets}
function newsSources(){const buckets=newsBuckets();return ['all',...Object.keys(buckets).sort((a,b)=>a.localeCompare(b))]}
function diverseNews(limit=12){
  const all=(DATA.news||[]).filter(isFreshNews),allSports=DATA.comp_key==='ALL'||DATA.competition==='All sports';
  const buckets={};
  all.forEach((a,i)=>{const key=allSports?(a._comp||a.competition||'OTHER'):sourceName(a);(buckets[key]||=[]).push({...a,_idx:i})});
  Object.values(buckets).forEach(items=>items.sort((a,b)=>newsTime(b)-newsTime(a)));
  const keys=Object.keys(buckets).sort((a,b)=>newsTime(buckets[b][0])-newsTime(buckets[a][0])),out=[];let row=0;
  while(out.length<limit&&keys.length){let moved=false;for(const key of keys){const item=buckets[key][row];if(item){out.push(item);moved=true;if(out.length>=limit)break}}if(!moved)break;row++}
  const result=out.length?out:all.slice(0,limit),fav=favoriteNewsTerm();
  return fav?result.sort((a,b)=>Number(teamKey(`${b.headline||b.title||''} ${b.desc||''}`).includes(fav))-Number(teamKey(`${a.headline||a.title||''} ${a.desc||''}`).includes(fav))):result;
}
function renderNews(){const n=DATA.news||[],host=$('#view-news'),diag=DATA.diagnostics||[];const buckets=newsBuckets(),srcs=newsSources();if(NEWS_FILTER!=='all'&&!buckets[NEWS_FILTER])NEWS_FILTER='all';let list=NEWS_FILTER==='all'?diverseNews(Math.max(n.length,18)):buckets[NEWS_FILTER]||[];host.innerHTML=`<div class="vhead">News cycle</div><div class="srcCount">${n.length} headlines · ${srcs.length-1} detected sources</div><div class="newsTools">${srcs.map(s=>`<button class="chip ${s==='all'?'allchip':''} ${NEWS_FILTER===s?'on':''}" data-src="${esc(s)}" onclick="NEWS_FILTER=this.dataset.src;renderNews()">${esc(s==='all'?'All sources':s)}<span class="count">${s==='all'?n.length:(buckets[s]||[]).length}</span></button>`).join('')}</div>`+(list.length?`<div class="newsGrid">`+list.map(a=>`<a class="ncard" href="${esc(a.link||a.url||'#')}" target="_blank" rel="noopener"><div class="srcTop"><span class="srcBadge">${esc(sourceName(a))}</span>${feedName(a)?`<span class="feedBadge">via ${esc(feedName(a))}</span>`:''}</div><div class="nhead">${esc(a.headline||a.title||'Untitled')}</div>${a.desc||a.description?`<div class="ndesc">${esc(a.desc||a.description)}</div>`:''}<div class="nmeta">${a.published?ago(a.published):''}</div></a>`).join('')+`</div>`:`<div class="empty">No headlines yet.</div>`)+(diag.length?`<div class="diagList">${diag.filter(d=>String(d).toLowerCase().includes('news')).map(d=>`<div>${esc(d)}</div>`).join('')}</div>`:'')}



/* ===== UI PATCH: model dashboard polish only; data untouched ===== */
function _modelHasVerifiedLock(m){return m?.prediction?.publication_state==='locked'}
function _modelIsPast(m){return m.status==='FINISHED'||isStaleUpcoming(m)}
function _modelIsArchived(m){return _modelIsPast(m)&&_modelHasVerifiedLock(m)}
function _highConfidenceAllowed(m){return m?.prediction?.lock_readiness?.confidence_guard?.high_confidence_label_allowed!==false}
function _modelEdgeKind(pr){if(!pr||pr.edge==null)return'level';return pr.edge>=6?'value':pr.edge<=-6?'fade':'level'}
function _modelSortScore(m){const pr=m.prediction||{};const archived=_modelIsArchived(m)?-10000:0;const upcoming=isVisibleUpcoming(m)?500:0;const edge=pr.edge==null?0:Math.max(0,pr.edge)*10;const conf=Number(pr.confidence)||0;return archived+upcoming+edge+conf}
function _modelMarketText(m,side){if(_modelIsArchived(m))return 'archived pick';const mk=(m.markets||{})['1x2']||{};const v={h:mk.home_pct,d:mk.draw_pct,a:mk.away_pct}[side];return v==null?'market n/a':`${v}% market`}
function _modelWhen(m){if(m.status==='LIVE')return 'Awaiting final';if(m.status==='FINISHED')return 'Finished';if(isStaleUpcoming(m))return 'Past kickoff';return kickIn(m.kickoff)}
function _modelTag(m){const pr=m.prediction||{},kind=_modelEdgeKind(pr);if(_modelIsArchived(m))return {txt:'ARCHIVE',kind:'level'};if(m.status==='LIVE')return {txt:'LOCKED',kind:'level'};if(kind==='value')return {txt:'VALUE',kind:'value'};if(kind==='fade')return {txt:'CAUTION',kind:'fade'};if((Number(pr.confidence)||0)>=65&&_highConfidenceAllowed(m))return {txt:'HIGH CONF',kind:'level'};return {txt:'MODEL',kind:'level'}}
function _modelBars(m){const md=officialPredictionProbabilities(m);const rows=_isTwoWay(m)?[['H','home',md.h],['A','away',md.a]]:[['H','home',md.h],['D','draw',md.d],['A','away',md.a]];return `<div class="modelBars">${rows.map(([lab,cls,val])=>{val=Math.max(0,Math.min(100,Number(val)||0));return `<div class="modelBarLine"><span>${lab}</span><div class="modelBarTrack"><span class="modelBarFill ${cls}" style="width:${Math.max(2,val)}%"></span></div><span>${Math.round(val)}%</span></div>`}).join('')}</div>`}
function _modelFinalText(m){const s=m.score||{};if(m.status==='FINISHED'&&s.home!=null&&s.away!=null)return `${s.home}–${s.away}`;return _modelWhen(m)}
/* dedup */
/* dedup */
function _modelApplyFilter(all){const f=window.MODEL_FILTER||'action';return all.filter(m=>{const archived=_modelIsArchived(m),pr=m.prediction||{},edge=Number(pr.edge)||0,conf=Number(pr.confidence)||0,hasOdds=!!((m.markets||{})['1x2']);if(f==='archive')return archived;if(archived)return false;if(f==='all')return true;if(f==='action'||f==='upcoming')return isVisibleUpcoming(m);if(f==='value')return isVisibleUpcoming(m)&&edge>=6;if(f==='caution')return isVisibleUpcoming(m)&&edge<=-6;if(f==='high')return isVisibleUpcoming(m)&&conf>=65&&_highConfidenceAllowed(m);if(f==='odds')return isVisibleUpcoming(m)&&hasOdds;return true})}
function _modelFilterBtn(key,label,count){const on=(window.MODEL_FILTER||'action')===key;return `<button class="chip ${on?'on':''}" onclick="window.MODEL_FILTER='${key}';MODEL_VISIBLE=MODEL_PAGE_SIZE;renderEdge()">${label}<span class="count">${count}</span></button>`}
function _archiveRow(m){const op=officialPrediction(m);return `<div class="archiveRow" onclick="openMatchModal('${esc(String(m.id||''))}')"><div><div class="archiveTeams">${esc(m.home?.code||m.home?.name||'H')} v ${esc(m.away?.code||m.away?.name||'A')}</div><div class="archiveMeta">${esc(m.stage||'Fixture')} · ${_modelWhen(m)}</div></div><div class="archiveResult">${esc(_modelFinalText(m))}</div><div class="archivePick">Pick <b>${esc(op.name||'—')}</b> · ${op.confidence??'—'}%</div><div class="archiveBadge">Review</div></div>`}
function renderEdge(){const host=$('#view-edge');const all=(DATA.matches||[]).filter(m=>m.prediction&&(!_modelIsPast(m)||_modelHasVerifiedLock(m))).sort((a,b)=>_modelSortScore(b)-_modelSortScore(a));if(!all.length){host.innerHTML=`<div class="vhead">Model</div>${(()=>{const sc=DATA.scorecard;if(!sc||!sc.graded)return '';const rec=`${sc.model_hits}-${sc.graded-sc.model_hits}`;const br=sc.brier3??sc.brier_advancement??sc.brier??'—';const brLabel=sc.brier3!=null?'Outcome Brier':sc.brier_advancement!=null?'Advancement Brier':'Pick-event Brier';const cl=sc.clv_avg!=null?(sc.clv_avg>0?'+':'')+sc.clv_avg+' pp':'—';const vs=sc.value&&sc.value.all?`${sc.value.all.hits}/${sc.value.all.n}`:'—';return `<div class="credstrip"><span class="credtag">Model record</span><span class="creditem"><b>${rec}</b> last ${sc.graded}</span><span class="creditem">${brLabel} <b>${br}</b></span><span class="creditem">Line movement <b>${cl}</b></span><span class="creditem">Value <b>${vs}</b></span>${sc.graded<20?'<span class="crednote">small sample</span>':''}</div>`;})()}${FORECAST_PAUSE_ACTIVE?`<div class="empty forecastPaused" role="status"><b>Pick board is paused</b><span>${esc(FORECAST_PAUSE_MESSAGE)}</span><em>Graded picks return here once publication resumes. <a href="qa.html#pause">Why, and what comes next</a></em></div>`:'<div class="empty">No model picks yet.</div>'}`;return}if(!window.MODEL_FILTER||window.MODEL_FILTER==='finished'||window.MODEL_FILTER==='live')window.MODEL_FILTER='action';
  // Paused: the pregame tab is empty by construction, so open on the graded
  // record rather than dropping the reader onto a blank board.
  if(FORECAST_PAUSE_ACTIVE&&window.MODEL_FILTER==='action'&&!all.some(isVisibleUpcoming))window.MODEL_FILTER='archive';const archived=all.filter(_modelIsArchived).sort((a,b)=>new Date(b.kickoff||0)-new Date(a.kickoff||0));const active=all.filter(m=>!_modelIsArchived(m));const counts={all:active.length,action:active.filter(isVisibleUpcoming).length,upcoming:active.filter(isVisibleUpcoming).length,value:active.filter(m=>isVisibleUpcoming(m)&&(m.prediction?.edge||0)>=6).length,caution:active.filter(m=>isVisibleUpcoming(m)&&(m.prediction?.edge||0)<=-6).length,high:active.filter(m=>isVisibleUpcoming(m)&&(Number(m.prediction?.confidence)||0)>=65&&_highConfidenceAllowed(m)).length,odds:active.filter(m=>isVisibleUpcoming(m)&&!!((m.markets||{})['1x2'])).length,archive:archived.length};const list=_modelApplyFilter(all).sort((a,b)=>_modelSortScore(b)-_modelSortScore(a));const actionable=active.filter(isVisibleUpcoming);const value=active.filter(m=>isVisibleUpcoming(m)&&(m.prediction?.edge||0)>=6);const caution=active.filter(m=>isVisibleUpcoming(m)&&(m.prediction?.edge||0)<=-6);const high=active.filter(m=>isVisibleUpcoming(m)&&(Number(m.prediction?.confidence)||0)>=65&&_highConfidenceAllowed(m));const archiveMode=window.MODEL_FILTER==='archive';const shownRows=list.slice(0,MODEL_VISIBLE),moreRows=Math.max(0,list.length-shownRows.length);let html=`<div class="modelShell"><div class="modelHero"><div><div class="modelHeroTitle">Pregame model</div><div class="modelHeroSub">Verified locked pregame picks, market context, and postgame grading.</div></div><div class="modelKpis"><div class="modelKpi"><span>Pregame</span><b>${actionable.length}</b></div><div class="modelKpi good"><span>Model leans</span><b>${value.length}</b></div><div class="modelKpi warn"><span>High confidence</span><b>${high.length}</b></div><div class="modelKpi bad"><span>Graded</span><b>${archived.length}</b></div></div></div><div class="modelToolbar">${_modelFilterBtn('action','Pregame',counts.action)}${_modelFilterBtn('value','Model lean',counts.value)}${_modelFilterBtn('archive','Results',counts.archive)}</div>${_modelSpotlight(active)}<div class="modelGrid"><section class="modelPanel"><div class="modelPanelHead"><h3>${archiveMode?'Postgame results':'Pregame pick board'}</h3><span>${shownRows.length} of ${list.length}</span></div><div class="modelList">${shownRows.length?shownRows.map(_modelRow).join(''):`<div class="modelEmptySmall">No matches in this filter.</div>`}</div>${moreRows?`<div class="fixturePager"><span>Showing ${shownRows.length} of ${list.length} picks</span><button class="actionbtn" onclick="MODEL_VISIBLE+=MODEL_PAGE_SIZE;renderEdge()">Load ${Math.min(MODEL_PAGE_SIZE,moreRows)} more</button></div>`:''}</section><section class="modelPanel modelDigestPanel"><div class="modelPanelHead"><h3>${archiveMode?'Postgame reads':'Quick reads'}</h3><span>digest</span></div><div class="modelReadList">`;const reads=(list.length?list:(archiveMode?archived:active)).slice(0,5);html+=reads.map((m,i)=>{const pr=m.prediction||{},tag=_modelTag(m),txt=_modelIsArchived(m)?`${pr.pick_name||'Model'} was ${pr.confidence||'—'}%. Result: ${_modelFinalText(m)}.`:(edgeBreakdown(m)||`${pr.pick_name||'Model'} at ${pr.confidence||'—'}%.`);return `<div class="modelRead" onclick="openMatchModal('${esc(String(m.id||''))}')"><div class="rtitle"><span>${tag.txt}</span>${esc(m.home?.code||'H')} v ${esc(m.away?.code||'A')}</div><p>${esc(txt)}</p></div>`}).join('');html+=`</div></section>`;if(!archiveMode&&archived.length){html+=`<section class="modelPanel modelArchivePanel"><div class="modelPanelHead"><h3>Postgame results <span class="archiveBadge">${archived.length}</span></h3><span><button class="chip" onclick="window.MODEL_FILTER='archive';MODEL_VISIBLE=MODEL_PAGE_SIZE;renderEdge()">View results</button></span></div><div class="modelList">${archived.slice(0,8).map(_archiveRow).join('')}</div></section>`}html+=`</div></div>`;host.innerHTML=html}



/* ===== UI PATCH: complete bracket render; UI only, data untouched ===== */
function _canonRoundName(name){
  const x=String(name||'').toLowerCase().replace(/[_-]/g,' ');
  if(/knockout.*play.?off|play off round/.test(x))return 'Knockout phase play-offs';
  if(/round of 32|last 32|r32/.test(x))return 'Round of 32';
  if(/round of 16|last 16|r16/.test(x))return 'Round of 16';
  if(/quarter/.test(x)||/qf/.test(x))return 'Quarter-finals';
  if(/semi/.test(x)||/sf/.test(x))return 'Semi-finals';
  if(/third|3rd/.test(x))return 'Third-place playoff';
  if(/final/.test(x))return 'Final';
  return String(name||'');
}
function _bracketSourceMap(rounds){
  const map={};
  (Array.isArray(rounds)?rounds:[]).forEach(r=>{
    const key=_canonRoundName(r.round||r.stage||r.name);
    if(!key)return;
    (map[key] ||= []).push(...(r.matches||[]));
  });
  return map;
}
function _slotTBD(label){return {slot:label,team:'TBD',code:'',pts:0,gd:0,live:false}}
function _projectedSlots32(){
  const src=getProjectedSlots();
  const out=[];
  for(let i=0;i<32;i++)out.push(src[i]||_slotTBD(`Seed ${i+1}`));
  return out;
}
function _pairFromSlots(slots,i,label){
  const a=slots[i]||_slotTBD(`Seed ${i+1}`),b=slots[i+1]||_slotTBD(`Seed ${i+2}`);
  return {stage:label,home:a.team,home_code:a.code,home_slot:a.slot,away:b.team,away_code:b.code,away_slot:b.slot,status:'PROJECTED',score:{}};
}
function _winnerPair(prev,idx,label){
  return {stage:label,home:`Winner ${prev} ${idx*2+1}`,home_slot:'path',away:`Winner ${prev} ${idx*2+2}`,away_slot:'path',status:'TBD',score:{}};
}
function _completeProjectedRounds(){
  const slots=_projectedSlots32();
  return [
    {round:'Round of 32',matches:Array.from({length:16},(_,i)=>_pairFromSlots(slots,i*2,`R32 ${i+1}`))},
    {round:'Round of 16',matches:Array.from({length:8},(_,i)=>_winnerPair('R32',i,`R16 ${i+1}`))},
    {round:'Quarter-finals',matches:Array.from({length:4},(_,i)=>_winnerPair('R16',i,`QF ${i+1}`))},
    {round:'Semi-finals',matches:Array.from({length:2},(_,i)=>_winnerPair('QF',i,`SF ${i+1}`))},
    {round:'Final',matches:[{stage:'Final',home:'Winner SF 1',home_slot:'path',away:'Winner SF 2',away_slot:'path',status:'TBD',score:{}}]},
    {round:'Third-place playoff',matches:[{stage:'Third place',home:'Loser SF 1',home_slot:'path',away:'Loser SF 2',away_slot:'path',status:'TBD',score:{}}]}
  ];
}
function _completeRounds(){
  const source=_bracketSourceMap(DATA.bracket||[]),projected=_completeProjectedRounds(),wanted=['Round of 32','Round of 16','Quarter-finals','Semi-finals','Final','Third-place playoff'];
  return wanted.map(name=>{
    const fallback=projected.find(r=>r.round===name)?.matches||[];
    const official=source[name]||[];
    if(!official.length)return {round:name,matches:fallback};
    const need=fallback.length||official.length;
    const merged=[];
    for(let i=0;i<need;i++)merged.push(official[i]||fallback[i]);
    return {round:name,matches:merged};
  });
}
function projectedRounds(){return _completeProjectedRounds()}
function roundMatches(rounds,name){const key=_canonRoundName(name);const r=(rounds||[]).find(x=>_canonRoundName(x.round||x.stage||x.name)===key);return r?.matches||[]}
function compactProjectedMatch(km,last=false,side='left',isFinal=false){
  const cls=`brMini ${isFinal?'finalCard':''} ${last?'':side==='right'?'connectL':'connectR'} ${((km.home||'').includes('Winner')||(km.home||'')==='TBD')?'tbd':''}`;
  return `<div class="${cls}">${isFinal?'<div class="finalBadge">Final</div>':''}<div class="bmMeta"><span>${esc(km.stage||'Projected')}</span><span>${km.status==='PROJECTED'?'projected':'path'}</span></div>${bracketTeam(km.home,km.home_code||'',km.home_slot||'',null,false,false)}${bracketTeam(km.away,km.away_code||'',km.away_slot||'',null,false,false)}</div>`;
}
function bracketColumn(title,matches,side,official,connect=true){
  return `<section class="brCol"><div class="roundTitle">${esc(shortRoundName(title))}</div>${(matches||[]).map(m=>{
    const real=m&&m.status&&m.status!=='TBD'&&m.status!=='PROJECTED';
    return (official&&real)?compactBracketMatch(m,!connect,side,false):compactProjectedMatch(m,!connect,side,false);
  }).join('')}</section>`;
}
/* dedup */



/* ===== UI PATCH: pitch lineups, flags, and richer odds board; UI only ===== */
function uiFlag(code){if(String(DATA?.comp_key||'')!=='WC')return'';try{return flagEmoji(code||'')||''}catch(e){return''}}
function uiTeamFlag(team){return uiFlag(team?.code||codeForTeam(team?.name||'',team?.code||''))}
function teamFlagHTML(team,away=false){const fl=uiTeamFlag(team);return fl?`<span class="flagIcon ${away?'away':''}">${fl}</span>`:''}
function shortPlayerName(name){const s=String(name||'').trim();if(!s)return'';const parts=s.split(/\s+/).filter(Boolean);return parts.length>1?parts[parts.length-1]:s}
function formationParts(f){const nums=String(f||'').match(/\d+/g);return nums?nums.map(Number).filter(n=>n>0):[]}
function normalizePlayer(p){return {n:String(p?.n??p?.number??'').trim(),name:String(p?.name??p?.shortName??p?.athlete?.displayName??'').trim(),out:!!p?.out}}
function lineupRows(xi,formation){const players=(xi||[]).map(normalizePlayer).filter(p=>p.n||p.name);if(!players.length)return[];const parts=formationParts(formation);if(!parts.length){const rows=[];for(let i=0;i<players.length;i+=3)rows.push(players.slice(i,i+3));return rows}const rows=[];let idx=0;rows.push(players.slice(idx,idx+1));idx+=1;parts.forEach(c=>{rows.push(players.slice(idx,idx+c));idx+=c});if(idx<players.length)rows.push(players.slice(idx));return rows.filter(r=>r.length)}
function pitchPlayer(p){const nm=shortPlayerName(p.name)||`#${p.n||'?'}`;return `<div class="pitchPlayer ${p.out?'out':''}" title="${esc((p.n?('#'+p.n+' '):'')+(p.name||''))}"><div class="num">${esc(p.n||'—')}</div><div class="pname">${esc(nm)}</div>${p.out?'<span class="subMark">sub</span>':''}</div>`}
function pitchTeamCard(team,line,side){const rows=lineupRows(line?.xi||[],line?.formation||'');const fl=teamFlagHTML(team);const form=line?.formation||'XI';return `<div class="pitchCard ${side}"><div class="pitchHeader"><div class="pitchTeamName">${fl}<span>${esc(team?.name||side)}</span></div><div class="formationBadge">${esc(form)}</div></div>${rows.length?`<div class="pitch">${rows.map(r=>`<div class="pitchRow">${r.map(pitchPlayer).join('')}</div>`).join('')}</div>`:`<div class="emptyStats">Lineup not available.</div>`}<div class="lineupFoot"><span>${esc(team?.code||'')}</span><span>${rows.reduce((a,r)=>a+r.length,0)} players shown</span></div></div>`}
function marketHitterCard(team,line){const players=(line?.xi||[]).map(normalizePlayer).filter(p=>p.name);return `<div class="marketHitterCard"><div class="marketHitterHead"><b>${esc(team?.name||'Team')}</b><span>${players.length} listed</span></div><div class="marketHitterList">${players.map(p=>`<span>${esc(p.name)}</span>`).join('')}</div></div>`}
function lineupsPanel(m){
  const l=m.lineups;
  if(l?.basis&&((l.home?.xi||[]).length||(l.away?.xi||[]).length))return `<div class="lineupBoard marketHitterBoard"><div class="seclbl">Likely active hitters</div><div class="marketInferenceNote">Inferred from non-ESPN batting-hit markets. These names are unordered and unconfirmed; this is not an official batting card.</div><div class="marketHitterGrid">${marketHitterCard(m.home,l.home||{})}${marketHitterCard(m.away,l.away||{})}</div></div>`;
  if(l&&((l.home?.xi||[]).length||(l.away?.xi||[]).length))return `<div class="lineupBoard pitchMode"><div class="seclbl">Lineups</div><div class="pitchGrid">${pitchTeamCard(m.home,l.home||{},'home')}${pitchTeamCard(m.away,l.away||{},'away')}</div></div>`;
  const comp=String(m?._comp||DATA.comp_key||'').toUpperCase();
  const soccer=['WC','UCL','EPL','LALIGA','SERIEA','BUNDESLIGA','LIGUE1'].includes(comp);
  const ctx=m.pregame_context||m.prediction?.lock_readiness;
  const checked=!!m.personnel?.lineups_feed_checked;
  const lead=Number(ctx?.lead_time_hours);
  let title='No cleared lineup feed for this competition';
  let note='Matchday will not infer a lineup or scrape an unlicensed source.';
  if(!ctx){title='Readiness receipt unavailable';note='This published snapshot predates pregame-context tracking.'}
  else if(soccer&&Number.isFinite(lead)&&lead>2){title='Lineups are not due yet';note='The authorized feed is checked during the final two hours before kickoff.'}
  else if(soccer&&checked){title='Provider checked — no confirmed lineup';note='The feed has not published a usable starting XI yet.'}
  else if(soccer){title='Awaiting the near-kickoff lineup check';note='The authorized feed is checked during the final two hours before kickoff.'}
  return `<div class="lineupBoard pitchMode"><div class="seclbl">Lineups</div><div class="emptyStats"><b>${esc(title)}</b><span>${esc(note)}</span></div></div>`;
}
function teamSnap(team,side,comp){return `<div class="teamSnap ${side==='away'?'away':''}"><div class="snapCode">${teamFlagHTML(team,side==='away')}${esc(team?.code||side)}</div><div class="snapName">${esc(team?.name||'TBD')}</div><div class="snapMeta">${esc(teamStandingsMeta(team,comp,{diff:true,form:true,hideStaleRecord:['NCAAF','NFL'].includes(String(comp||'').toUpperCase())}).join(' · '))}</div></div>`}
/* dedup */
function _v15RenderLeagueTable(st,host){const seen=new Set(),teams=[];(st||[]).forEach(g=>(g.teams||[]).forEach(t=>{const key=String(t.name||t.code||'').toLowerCase();if(key&&!seen.has(key)){seen.add(key);teams.push(t)}}));teams.sort((a,b)=>(Number(a.pos)||999)-(Number(b.pos)||999)||(Number(b.pts)||0)-(Number(a.pts)||0)||(Number(b.gd)||0)-(Number(a.gd)||0));host.innerHTML=`<div class="vhead">Table</div><div class="tablewrap leagueTableWrap"><div class="groupHead">${esc(DATA.competition||'League table')}<span>${teams.length} clubs · full table</span></div><table class="gtable"><thead><tr><th>Team</th><th>P</th><th>W</th><th>D</th><th>L</th><th>GF</th><th>GA</th><th>GD</th><th>Pts</th><th>Form</th></tr></thead><tbody>${teams.map((t,i)=>{const q=t.qual?`<span class="qbadge ${esc(t.qual.status||'')}" title="${esc(t.qual.note||'')}">${esc(t.qual.status||t.qual.note||'')}</span>`:'';return `<tr><td><div class="gteam teamClickable" data-team="${esc(t.name||'')}" onclick="openTeamModal(this.dataset.team)"><span class="pos">${t.pos||i+1}</span><span class="code">${esc(t.code||'')}</span>${esc(t.name||'')} ${q}</div></td><td>${t.pld??'—'}</td><td>${t.w??'—'}</td><td>${t.d??'—'}</td><td>${t.l??'—'}</td><td>${t.gf??'—'}</td><td>${t.ga??'—'}</td><td>${t.gd??'—'}</td><td><b>${t.pts??'—'}</b></td><td class="form">${esc(t.form||'')}</td></tr>`}).join('')}</tbody></table></div>`}
function _renderUCLLeagueTable(st,host){const teams=(st||[]).flatMap(group=>group.teams||[]).sort((a,b)=>(Number(a.pos)||999)-(Number(b.pos)||999));host.innerHTML=`<div class="vhead">League Phase</div><div class="tablewrap leagueTableWrap"><div class="groupHead">Champions League<span>36 clubs · eight league-phase matches each</span></div><table class="gtable"><thead><tr><th>Team</th><th>P</th><th>W</th><th>D</th><th>L</th><th>GF</th><th>GA</th><th>GD</th><th>Pts</th><th>Form</th></tr></thead><tbody>${teams.map((t,i)=>{const pos=Number(t.pos)||i+1,q=t.qual?`<span class="qbadge ${esc(t.qual.status||'')}" title="${esc(t.qual.note||'')}">${esc(t.qual.status||'')}</span>`:'';return `<tr class="${pos<=8?'qual':pos<=24?'third':''}"><td><div class="gteam teamClickable" data-team="${esc(t.name||'')}" onclick="openTeamModal(this.dataset.team)"><span class="pos">${pos}</span><span class="code">${esc(t.code||'')}</span>${esc(t.name||'')} ${q}</div></td><td>${t.pld??'—'}</td><td>${t.w??'—'}</td><td>${t.d??'—'}</td><td>${t.l??'—'}</td><td>${t.gf??'—'}</td><td>${t.ga??'—'}</td><td>${t.gd??'—'}</td><td><b>${t.pts??'—'}</b></td><td class="form">${esc(t.form||'')}</td></tr>`}).join('')}</tbody></table></div>`}
function _proRecord(t){return t.record||`${t.w??0}-${t.l??0}${Number(t.d)?'-'+t.d:''}`}
function _proWinPct(t){return t.win_pct!=null?Number(t.win_pct):(((Number(t.w)||0)+.5*(Number(t.d)||0))/Math.max(1,Number(t.pld)||0))}
function _proGamesBack(t,leader){const gb=((Number(leader.w)||0)-(Number(t.w)||0)+(Number(t.l)||0)-(Number(leader.l)||0))/2;return gb<=0?'—':(Number.isInteger(gb)?String(gb):gb.toFixed(1))}
function _renderProStandings(st,host){
  const comp=String(DATA.comp_key||'').toUpperCase(),scoreLabels={MLB:['RF','RA'],NFL:['PF','PA'],NBA:['PF','PA']}[comp]||['For','Against'];
  const official=(st||[]).filter(g=>g.table_type!=='power_ratings'),power=(st||[]).find(g=>g.table_type==='power_ratings');
  const showGb=comp==='MLB'||comp==='NBA';
  const officialHtml=official.map(g=>{const teams=g.teams||[],leader=teams[0]||{},tableKind=comp==='NBA'?'conference':'division';const groupLabel=g.group||SPORT_LABELS[String(DATA.comp_key||'').toLowerCase()]||'Full table';return `<div class="tablewrap proDivisionTable"><div class="groupHead">${esc(groupLabel)}<span>${tableKind} standings · win percentage</span></div><table class="gtable proTable"><thead><tr><th>Team</th><th>Record</th><th>PCT</th>${showGb?'<th>GB</th>':''}<th>${scoreLabels[0]}</th><th>${scoreLabels[1]}</th><th>Diff</th><th>L5</th></tr></thead><tbody>${teams.map((t,i)=>{const hasScores=Number(t.gf)!==0||Number(t.ga)!==0;return `<tr><td><div class="gteam teamClickable" data-team="${esc(t.name||'')}" onclick="openTeamModal(this.dataset.team)"><span class="pos">${t.pos||i+1}</span><span class="code">${esc(t.code||'')}</span>${esc(t.name||'')}</div></td><td><b>${esc(_proRecord(t))}</b></td><td>${(_proWinPct(t)*100).toFixed(1)}%</td>${showGb?`<td>${_proGamesBack(t,leader)}</td>`:''}<td>${hasScores?esc(t.gf):'—'}</td><td>${hasScores?esc(t.ga):'—'}</td><td>${hasScores?esc(t.gd):'—'}</td><td class="form">${esc(t.form||'—')}</td></tr>`}).join('')}</tbody></table></div>`}).join('');
  const powerHtml=power?`<div class="tablewrap proPowerTable"><div class="groupHead">Power Ratings<span>Matchday model · league-wide, separate from standings</span></div><table class="gtable proTable"><thead><tr><th>Team</th><th>Rating</th><th>Record</th><th>PCT</th><th>Diff</th><th>L5</th></tr></thead><tbody>${(power.teams||[]).map((t,i)=>`<tr><td><div class="gteam teamClickable" data-team="${esc(t.name||'')}" onclick="openTeamModal(this.dataset.team)"><span class="pos">${t.pos||i+1}</span><span class="code">${esc(t.code||'')}</span>${esc(t.name||'')}</div></td><td><b>${t.rating!=null?Number(t.rating).toFixed(2):'—'}</b></td><td>${esc(_proRecord(t))}</td><td>${(_proWinPct(t)*100).toFixed(1)}%</td><td>${t.gd??'—'}</td><td class="form">${esc(t.form||'—')}</td></tr>`).join('')}</tbody></table></div>`:'';
  host.innerHTML=`<div class="vhead">Standings</div><div class="proStandingsGrid">${officialHtml}</div>${powerHtml}`;
}
function renderStandings(){const comp=String(DATA.comp_key||'').toUpperCase();if(comp==='UCL'){const host=$('#view-groups'),st=deriveStandings();if(!st.length){host.innerHTML='<div class="vhead">League Phase</div><div class="empty">No current league-phase standings yet.</div>';return}_renderUCLLeagueTable(st,host);return}if(['MLB','NFL','NBA'].includes(comp)){const host=$('#view-groups'),st=deriveStandings();if(!st.length){host.innerHTML='<div class="vhead">Standings</div><div class="empty">No standings data found yet.</div>';return}_renderProStandings(st,host);return}renderGroups()}
function renderGroups(){const st=deriveStandings(),host=$('#view-groups'),sc=DATA.scorers||[];if(!st.length){host.innerHTML=`<div class="vhead">${DATA.comp_key==='NCAAM'?'Conferences':navProfile()==='soccer_league'?'Table':'Groups'}</div><div class="empty">No group data found yet.</div>`;return}if(navProfile()==='soccer_league'){_v15RenderLeagueTable(st,host);return}if(DATA.comp_key==='NCAAM'){host.innerHTML=`<div class="vhead">Conferences</div>`+st.map(g=>`<div class="tablewrap"><div class="groupHead">${esc(g.group)}<span>${g.group==='Top 25'?'national poll':'raw season records'}</span></div><table class="gtable ncaamTable"><thead><tr><th>Team</th><th>Rating</th><th>Record</th><th>Win%</th><th>PF/G</th><th>PA/G</th><th>Diff</th><th>Streak</th></tr></thead><tbody>${(g.teams||[]).map(t=>`<tr><td><div class="gteam teamClickable" data-team="${esc(t.name||'')}" onclick="openTeamModal(this.dataset.team)"><span class="pos">${t.pos||''}</span><span class="code">${esc(t.code||'')}</span>${esc(t.name||'')}</div></td><td>${t.rating!=null?Number(t.rating).toFixed(2):'—'}</td><td><b>${esc(t.record||`${t.w??'—'}-${t.l??'—'}`)}</b></td><td>${t.win_pct!=null?(Number(t.win_pct)*100).toFixed(1)+'%':'—'}</td><td>${t.avg_pf!=null&&Number(t.avg_pf)?Number(t.avg_pf).toFixed(1):'—'}</td><td>${t.avg_pa!=null&&Number(t.avg_pa)?Number(t.avg_pa).toFixed(1):'—'}</td><td>${t.gd!=null?esc(t.gd):'—'}</td><td class="form">${esc(t.form||'—')}</td></tr>`).join('')}</tbody></table></div>`).join('');return}const groupsTwoWay=SANDBOX_TWO_WAY.has(String(DATA.comp_key||'').toLowerCase());const americanSport=navProfile()==='us_sport'||navProfile()==='college';const ratingSorted=['nfl','nba','mlb'].includes(String(DATA.comp_key||'').toLowerCase());const US_SCORE_UNIT={nfl:['PF','PA'],nba:['PF','PA'],ncaaf:['PF','PA'],mlb:['RF','RA'],nhl:['GF','GA']};const[fLabel,aLabel]=US_SCORE_UNIT[String(DATA.comp_key||'').toLowerCase()]||['GF','GA'];const winPct=t=>t.pld?((Number(t.w)||0)/t.pld*100).toFixed(1)+'%':'—';host.innerHTML=`<div class="vhead">${americanSport?'Standings':'Groups'}</div>`+st.map(g=>`<div class="tablewrap"><div class="groupHead">${americanSport?esc(g.group||'Full table'):esc(g.group)}<span>${americanSport?(ratingSorted?'ranked by model rating':'ranked by win rate'):'Top 2 · 3rd'}</span></div><table class="gtable"><thead><tr><th>Team</th>${americanSport?'<th>Rating</th>':''}<th>P</th><th>W</th>${groupsTwoWay?'':'<th>D</th>'}<th>L</th><th>${fLabel}</th><th>${aLabel}</th><th>${americanSport?'Diff':'GD'}</th><th>${americanSport?'Win%':'Pts'}</th><th>Form</th></tr></thead><tbody>${(g.teams||[]).map(t=>{const fl=uiFlag(t.code);const q=t.qual?`<span class="qbadge ${esc(t.qual.status)}" title="${esc(t.qual.note)}">${esc(t.qual.note)}</span>`:'';return `<tr class="${americanSport?'':(t.pos<=2?'qual':t.pos===3?'third':'')}"><td><div class="gteam teamClickable" data-team="${esc(t.name||'')}" onclick="openTeamModal(this.dataset.team)"><span class="pos">${t.pos||''}</span>${fl?`<span class="flagIcon">${fl}</span>`:''}<span class="code">${esc(t.code||'')}</span>${esc(t.name)} ${t.live?'<span class="liveMark">*</span>':''}${q}</div></td>${americanSport?`<td>${t.rating!=null?Number(t.rating).toFixed(2):'—'}</td>`:''}<td>${t.pld??'—'}</td><td>${t.w??'—'}</td>${groupsTwoWay?'':`<td>${t.d??'—'}</td>`}<td>${t.l??'—'}</td><td>${t.gf??'—'}</td><td>${t.ga??'—'}</td><td>${t.gd??'—'}</td><td><b>${americanSport?winPct(t):(t.pts??'—')}</b></td><td class="form">${esc(t.form||'')}</td></tr>`}).join('')}</tbody></table></div>`).join('')}
/* dedup */
// Sports whose expanded view has a research-signals panel (see research-signals
// .js). Only these are worth re-fetching a full sport file for when the board is
// running on the summary payload -- everywhere else the summary already holds
// everything the modal renders.
const RESEARCH_SIGNAL_COMPS=new Set(['NFL','NCAAF','NBA','NCAAM','MLB']);
const SPORT_FILE_CACHE={};
function fetchSportFile(key){
  if(!key)return Promise.resolve(null);
  if(!SPORT_FILE_CACHE[key])SPORT_FILE_CACHE[key]=fetch('data_'+key+'.json',REVALIDATE).then(r=>r.ok?r.json():null).catch(()=>null);
  return SPORT_FILE_CACHE[key];
}
// Fill in the detail fields the summary payload leaves out, for one match only.
// Mutates the match in place so BYID and DATA.matches see it too.
async function hydrateMatchDetail(m){
  const key=String(m?._comp||'').toLowerCase();
  const full=await fetchSportFile(key);
  const hit=(full?.matches||[]).find(x=>String(x.id)===String(m.id));
  if(!hit)return false;
  Object.assign(m,hit,{_comp:m._comp});
  return true;
}
// True when this match is being shown from the summary payload and its sport
// has a research panel whose fields the summary leaves out. app-4-features.js
// overrides openMatchModal with a hardened version; the hook lives there.
function needsDetailHydration(m){
  if(!DATA?._summary||!m)return false;
  if(!RESEARCH_SIGNAL_COMPS.has(String(m._comp||'').toUpperCase()))return false;
  return !m.advanced_metrics&&!m.nfl_challenger_shadow&&!m.mlb_challenger_shadow;
}
function openMatchModal(id){const m=BYID[id]||(DATA.matches||[]).find(x=>String(x.id)===String(id));if(!m)return;const modal=ensureMatchModal();const hmeta=t=>esc(teamStandingsMeta(t,m._comp,{form:true}).join(' · '));modal.innerHTML=`<section class="matchSheet" role="dialog" aria-modal="true"><div class="modalHero"><button class="modalClose" onclick="closeMatchModal()" aria-label="Close">×</button><div class="modalStage">${esc(m.stage||'Fixture')} · ${esc(m.status==='LIVE'?'AWAITING FINAL':m.status||'')}</div><div class="modalFixture"><div class="modalTeam"><div class="modalCode">${teamFlagHTML(m.home)}${esc(m.home?.code||'HOME')}</div><div class="modalName">${esc(m.home?.name||'Home')}</div><div class="modalMeta">${hmeta(m.home)}</div></div><div class="modalScore"><div class="bigScore">${esc(scorePlainText(m))}</div><div class="modalStatus">${m.status==='LIVE'?'Score shown after final':kickIn(m.kickoff)}</div></div><div class="modalTeam away"><div class="modalCode">${esc(m.away?.code||'AWAY')}${teamFlagHTML(m.away,true)}</div><div class="modalName">${esc(m.away?.name||'Away')}</div><div class="modalMeta">${hmeta(m.away)}</div></div></div></div><div class="modalBody">${details(m)}</div></section>`;modal.classList.add('show');document.body.classList.add('modalOpen')}




/* ===== MODEL PICK REDESIGN — v3 =====
   This override intentionally avoids the old .pick/.fchip markup inside the modal.
   It prevents vertical letters, cramped chips, and overlap. */
/* dedup */
/* dedup */



/* ===== MATCH MODAL + FORECAST BOARD REDESIGN — v4 ===== */
function _v4PickSideLabel(m,side){
  if(side==='h')return m.home?.name||'Home';
  if(side==='a')return m.away?.name||'Away';
  if(side==='d')return 'Draw';
  return 'No pick';
}
function _v4ModelProbs(m){
  return officialPredictionProbabilities(m);
}
function sportClassMeta(pr,m){
  if(pr?.class_meta)return pr.class_meta;
  // Locked predictions created before class provenance was added keep their
  // immutable snapshot. Derive only the honest display label here; pro-sport
  // legacy "class" values were market proxies, so never present them as a
  // roster/personnel edge.
  const comp=String(m?._comp||DATA.comp_key||'').toUpperCase();
  const labels={NCAAF:'Roster talent edge',NCAAM:'Recruiting edge',MLB:'Personnel edge',NFL:'Roster edge',NBA:'Star / rotation edge',NHL:'Roster / goalie edge'};
  if(['MLB','NFL','NBA','NHL'].includes(comp))return {label:labels[comp],coverage:'unavailable',edge_available:false,coverage_label:comp==='NFL'?'Roster coverage':null};
  return {label:labels[comp]||'Squad edge',coverage:'partial'};
}
function _v4FactorRows(pr,m){
  const classMeta=sportClassMeta(pr,m),legacyMarketClass=!pr?.class_meta&&classMeta.coverage==='unavailable';
  const classLabel=legacyMarketClass?'legacy championship market power':classMeta.label.toLowerCase();
  const labels={class:classLabel,market_power:'championship market power',pts:'points',gd:scoreDiffLabel(m),record:'season record',margin:'scoring margin',rank:'poll rank',srs:'opponent-adjusted rating',form:'form',adv:'home field',rest:'rest',elo:'elo rating',h2h:'head-to-head',injuries:'injuries'};
  const rows=[];
  const classVal=pr?.why?.class!=null?(Number(pr.why.class)||0):null;
  const classListed=classVal!=null&&Math.abs(classVal)>=0.3;
  if(pr&&pr.why){
    Object.entries(pr.why).filter(([k,v])=>labels[k]&&Math.abs(Number(v)||0)>=0.3)
      .sort((a,b)=>Math.abs(Number(b[1])||0)-Math.abs(Number(a[1])||0))
      .forEach(([k,v])=>{v=Number(v)||0;rows.push(`<div class="factorRow ${v>0?'pos':v<0?'neg':'neu'}"><span class="fName">${esc(labels[k])}</span><span class="fVal">${v>0?'+':''}${v.toFixed(1)}</span></div>`)});
  }
  // Two very different things used to look identical here: a roster/talent
  // signal that grades the two teams level, and one the provider never
  // covered. Both fell under the 0.3 threshold above and were dropped
  // silently, so the talent edge simply vanished for 41 of 160 live NCAAF
  // fixtures with nothing on screen saying why. State it either way.
  if(!classListed){
    if(classMeta.edge_available===false){
      rows.push(`<div class="factorRow neu" title="${esc(classMeta.note||`No validated player-quality grades are available, so ${classLabel} is not scored.`)}"><span class="fName">${esc(classLabel)}</span><span class="fVal">not scored</span></div>`);
    }else{
      const covered=classMeta.coverage!=='unavailable'&&classVal!=null;
      rows.push(`<div class="factorRow neu" title="${esc(covered?`${classLabel} is in the model for this matchup and grades the two teams level.`:`No verified ${classLabel} data for this matchup, so the model assigned no edge rather than a fabricated one.`)}"><span class="fName">${esc(classLabel)}</span><span class="fVal">${covered?'level':'no data'}</span></div>`);
    }
  }
  if(classMeta.coverage_label&&classMeta.coverage!=='unavailable')rows.push(`<div class="factorRow neu" title="Expected depth-chart coverage only; this does not assert confirmed gameday actives or player quality."><span class="fName">${esc(classMeta.coverage_label)}</span><span class="fVal">${classMeta.coverage==='complete'?'both teams':'partial'}</span></div>`);
  if(pr&&Number(pr.damp_pct))rows.push(`<div class="factorRow neu"><span class="fName">variance control</span><span class="fVal">−${esc(pr.damp_pct)}%</span></div>`);
  if(pr&&Number(pr.mkt_pull))rows.push(`<div class="factorRow neu"><span class="fName">consensus pull</span><span class="fVal">${Number(pr.mkt_pull)>0?'+':''}${esc(pr.mkt_pull)}</span></div>`);
  // Surfaces the locked pick's own data-availability snapshot as an explicit
  // uncertainty signal, rather than letting a missing input pass silently.
  if(pr&&pr.data_availability){
    const availLabels={market:'market odds',box_score:'box score',lineups:'lineups',injuries:'injury reports',weather:'weather',personnel:'sport-specific personnel',venue_context:'venue context'};
    Object.entries(pr.data_availability).filter(([k,v])=>v==='unavailable'&&availLabels[k])
      .forEach(([k])=>rows.push(`<div class="factorRow neu" title="No ${esc(availLabels[k])} were available when this pick locked, so the model could not use them."><span class="fName">${esc(availLabels[k])}</span><span class="fVal">no data</span></div>`));
  }
  return rows.length?rows.join(''):'<div class="factorRow neu"><span class="fName">No factor detail</span><span class="fVal">—</span></div>';
}
/* dedup */
function matchStory(m){const pr=m.prediction;if(!pr)return '';
  const up=pr.upset||{},official=officialPrediction(m),conf=official.confidence;
  const pickName=esc(official.name||'');
  // lead sentence
  let lead;
  const cls=up.upset_class||'unknown';
  const radar=up.radar;const edge=up.upset_edge;
  const magnitude={major:'a heavy underdog',solid:'a real underdog',minor:'a live underdog'}[cls]||'the underdog';
  if(up.triggered&&up.candidate_name&&up.candidate===official.side){
    lead=`<b>${esc(up.candidate_name)}</b> is the upset call — ${magnitude} the model rates high enough to back outright.`;
  }else if(radar&&up.candidate_name){
    lead=`<b>${pickName}</b> is the official pick${conf?` at ${conf}%`:''}, but <b>${esc(up.candidate_name)}</b> is on the upset radar — ${magnitude} the model prices ${edge>0?`${edge} points above`:'above'} the market.${up.market_gate===false?' The gap is too wide to make it the pick, so it remains a watch signal.':''}`;
  }else if(cls==='pickem'){
    lead=`<b>${pickName}</b> is the lean in what is essentially a coin-flip — the market can barely separate these two.`;
  }else{
    lead=`<b>${pickName}</b> is the model's pick${conf?` at ${conf}%`:''}${conf&&conf>=60?' — a confident, clean call with no live upset threat':''}. ${esc(pr.note||'')}.`;
  }
  // why bullets from factor attribution (top 3 by magnitude)
  const L={pts:'points on the table',gd:scoreDiffLabel(m),record:'season record',margin:'per-game scoring margin',rank:'poll rank',srs:'opponent-adjusted rating',elo:'Elo rating',form:'recent form',adv:'home-listing edge',class:'squad class and ranking',rest:'rest advantage'};
  const why=pr.why||{};
  const bullets=Object.entries(why).filter(([k,v])=>Math.abs(v)>=0.4&&L[k]).sort((a,b)=>Math.abs(b[1])-Math.abs(a[1])).slice(0,3)
    .map(([k,v])=>{const who=v>0?esc(m.home.name):esc(m.away.name);return `<li>${who} leads on ${L[k]}</li>`;});
  if(pr.damp_pct>=10)bullets.push(`<li>Knockout/conditions variance is damping confidence by ${pr.damp_pct}%</li>`);
  if(up.triggered&&up.candidate===official.side)bullets.push(`<li>Upset gate: OPEN — backing ${esc(up.candidate_name)} as the locked pick</li>`);
  else if(up.radar&&up.market_gate===false)bullets.push(`<li>Upset radar: ${esc(up.candidate_name)} is underpriced by the market but the gap is too wide to back outright</li>`);
  else if(up.radar)bullets.push(`<li>Upset radar: model rates ${esc(up.candidate_name)} ${up.upset_edge>0?'+'+up.upset_edge:up.upset_edge} vs the market</li>`);
  const tot=(m.prediction||{}).totals||null;
  const totalsUnit=_totalsUnit(m);
  let goals='';
  if(m.markets&&m.markets.totals){
    const mktLean=m.markets.totals.over_pct>=m.markets.totals.under_pct?'over':'under';
    const extra=(tot&&tot.pick)?(tot.pick===mktLean?` · model agrees (${tot.expected} expected)`:` · model leans ${tot.pick} instead (${tot.expected} expected)`):'';
    goals=`<li>Market leans ${mktLean} ${esc(m.markets.totals.line)} ${totalsUnit}${extra}</li>`;
  } else if(tot&&tot.expected!=null){
    goals=`<li>Model expects ${tot.expected} ${totalsUnit} — no market line yet</li>`;
  }
  return `<div class="storyCard"><div class="storyTag">Match Story</div><p class="storyLead">${lead}</p>${(bullets.length||goals)?`<ul class="storyWhy">${bullets.join('')}${goals}</ul>`:''}</div>`;}
function pregameContextPanel(m){
  const ctx=m.pregame_context||m.prediction?.lock_readiness;
  if(!ctx)return `<div class="readCard pregameContextCard"><div class="seclbl">Pregame context</div><div class="emptyStats"><b>No readiness receipt for this fixture</b><span>This forecast was published before Matchday started recording which pregame inputs it had. The pick still stands as locked; only the receipt is missing.</span></div></div>`;
  const labels={market:'market',injuries:'injuries',lineups:'lineups',weather:'weather',venue:'venue',starting_pitchers:'starting pitchers',bullpen:'bullpen availability',rotation:'rotation',key_players:'QB / key players',starting_goalies:'starting goalies'};
  const state=m.prediction?.publication_state||ctx.phase||'preliminary';
  const stateLabel=state==='locked'?'Locked forecast':state==='lock_candidate'?'Inside lock window':'Preliminary forecast';
  const inWindow=state==='locked'||state==='lock_candidate';
  // Outside the lock window an unconfirmed input is the schedule working, not
  // a fault -- lineups for a fixture two days out have not been named yet. The
  // panel used to render one grey "missing" row per input plus a red "Needed
  // before lock" alert on every such fixture, which is every soccer and
  // college fixture on the board, so a normal pregame card read as a broken
  // one. The full receipt is kept for inside the window, where a missing input
  // genuinely blocks the lock.
  const inputPairs=Object.entries(ctx.inputs||{});
  const confirmedPairs=inputPairs.filter(([,value])=>String(value)==='confirmed');
  const pendingPairs=inputPairs.filter(([,value])=>String(value)!=='confirmed');
  const rows=(inWindow?inputPairs:confirmedPairs).map(([key,value])=>`<div class="factorRow ${value==='confirmed'?'pos':'neu'}"><span class="fName">${esc(labels[key]||key)}</span><span class="fVal">${esc(value)}</span></div>`).join('');
  const lead=Number(ctx.lead_time_hours);
  const pendingLine=(!inWindow&&pendingPairs.length)?`<div class="contextPending"><b>Still to arrive</b><span>${pendingPairs.map(([key])=>esc(labels[key]||key)).join(' · ')}</span><small>${lead>0?`Kickoff is ${lead>=48?Math.round(lead/24)+' days':Math.round(lead)+'h'} away — these confirm closer to it.`:'These confirm closer to kickoff.'}</small></div>`:'';
  // Only a licensed feed writes starting_pitchers; SportsGameOdds writes its
  // market-listed inference under starter_candidates so the two can never be
  // confused. Reading only the first meant this card showed nothing at all on
  // every fixture, and the "not confirmed" wording below was unreachable.
  const pitchers=m.personnel?.starting_pitchers||m.personnel?.starter_candidates||{};
  const pitchersConfirmed=!!(m.personnel?.starting_pitchers&&m.personnel?.starting_pitchers_confirmed);
  const starterNames=['home','away'].map(side=>pitchers[side]?.name).filter(Boolean);
  const marketHitters=m.personnel?.market_listed_hitters||{};
  const bullpen=m.personnel?.bullpen||{};
  const injuries=m.injuries||{};
  const injuryDetails=m.personnel?.injury_details||{};
  const injuryCount=(injuries.home||[]).length+(injuries.away||[]).length+
    (injuryDetails.home||[]).length+(injuryDetails.away||[]).length;
  const depth=m.personnel?.depth_chart||{};
  const depthPositions=new Set(['QB','RB','LWR','RWR','SLWR','TE','LDE','RDE','MLB','LCB','RCB','FS','SS']);
  const depthLine=side=>{
    const chart=depth[side]||{},players=(chart.players||[]).filter(p=>depthPositions.has(String(p.position||'').toUpperCase())).slice(0,8);
    if(!players.length)return'';
    const team=side==='home'?m.home:m.away;
    return `${esc(team?.code||team?.name||side)} expected: ${players.map(p=>`${esc(p.position||'')} ${esc(p.name||'')}${p.roster_status&&p.roster_status!=='ACT'?` <b>(${esc(p.roster_status)})</b>`:''}`).join(' · ')}`;
  };
  const detailNotes=[];
  if(starterNames.length)detailNotes.push(`<div class="contextNote"><b>${pitchersConfirmed?'Confirmed starters':'Starter candidates'}</b><span>${starterNames.map(esc).join(' · ')}</span>${pitchersConfirmed?'':'<small>Market-listed, not confirmed</small>'}</div>`);
  if((marketHitters.home||[]).length||(marketHitters.away||[]).length)detailNotes.push(`<div class="contextNote"><b>Likely active hitters</b><span>${(marketHitters.home||[]).length} home · ${(marketHitters.away||[]).length} away</span><small>From player markets; unordered and unconfirmed</small></div>`);
  if(injuryCount)detailNotes.push(`<div class="contextNote"><b>Availability report</b><span>${injuryCount} unavailable or questionable player${injuryCount===1?'':'s'}</span></div>`);
  ['home','away'].map(depthLine).filter(Boolean).forEach(line=>detailNotes.push(`<div class="contextNote contextNoteWide"><b>Expected depth</b><span>${line}</span></div>`));
  const depthObserved=depth.home?.observed_at||depth.away?.observed_at;
  if(depthObserved)detailNotes.push(`<div class="contextNote contextNoteWide"><b>Depth-chart timestamp</b><span>${esc(new Date(depthObserved).toLocaleString())}</span><small>Expected hierarchy, not confirmed gameday actives</small></div>`);
  const missing=(ctx.missing_critical||[]).map(k=>labels[k]||k);
  const comp=String(m?._comp||DATA.comp_key||'').toUpperCase();
  const soccer=['WC','UCL','EPL','LALIGA','SERIEA','BUNDESLIGA','LIGUE1'].includes(comp);
  if(soccer&&inWindow&&ctx.inputs?.injuries==='missing')detailNotes.push('<div class="contextNote contextNoteWide"><b>Update schedule</b><span>Injuries inside 72h · lineups inside 2h</span></div>');
  const bullpenBlock=(bullpen.home||bullpen.away)?(()=>{
    const sideCard=side=>{const x=bullpen[side]||{},team=side==='home'?m.home:m.away,status=String(x.status||'unknown').toLowerCase(),cls=status==='elevated'?'warn':status==='normal'?'ok':'unknown';return `<div class="bullpenSide ${cls}"><div class="bullpenSideHead"><b>${esc(team?.code||team?.name||side)}</b><span>${esc(status)}</span></div><div class="bullpenMetrics"><div><strong>${esc(x.games_last_72h??'—')}</strong><small>games / 72h</small></div><div><strong>${x.hours_since_last_game!=null?esc(x.hours_since_last_game)+'h':'—'}</strong><small>since last game</small></div></div></div>`};
    return `<section class="contextSection"><div class="contextSectionHead"><span>Bullpen workload</span><small>Schedule estimate</small></div><div class="bullpenGrid">${sideCard('home')}${sideCard('away')}</div><p class="contextSource">Team rest only · individual reliever usage unavailable</p></section>`;
  })():'';
  const missingBlock=(inWindow&&missing.length)?`<div class="contextAlert"><span aria-hidden="true">!</span><div><b>Needed before lock</b><p>${missing.map(x=>esc(x)).join(' · ')}</p></div></div>`:'';
  return `<div class="readCard pregameContextCard"><div class="seclbl">Pregame context</div><div class="pick insightPick ${state==='locked'?'':'gate'}"><span class="pl">State</span><span class="pn">${esc(stateLabel)}</span><span class="pc">${esc(ctx.coverage_pct??0)}%</span><span class="pnote">${inWindow?`input coverage · locks on the first successful refresh inside the ${esc(ctx.lock_window_hours??2)}h pregame window`:`input coverage so far · the pick locks inside the ${esc(ctx.lock_window_hours??2)}h window before kickoff`}</span></div>${rows?`<div class="factorRows contextFactorRows">${rows}</div>`:''}${pendingLine}<div class="contextDetails">${bullpenBlock}${detailNotes.length?`<div class="contextNoteGrid">${detailNotes.join('')}</div>`:''}${missingBlock}</div><div class="contextResearch"><span>Research-only</span><p>New personnel and venue inputs are tracked, but do not change the model yet.</p></div></div>`;
}
function details(m){
  if(isForecastPaused(m))return `<div class="detailGrid v4Detail">${forecastPauseHTML(m)}<div class="detailTop"><div class="readCard forecastMarketCard">${marketPanel(m)}</div></div><div class="detailLow">${statsPanel(m)}${lineupsPanel(m)}</div></div>`;
  return `<div class="detailGrid v4Detail">${matchStory(m)}${pregameContextPanel(m)}<div class="detailTop"><div class="readCard modelReadCard">${modelBlock(m)}</div><div class="readCard forecastMarketCard">${marketPanel(m)}</div></div><div class="detailLow">${statsPanel(m)}${lineupsPanel(m)}</div></div>`;
}
/* dedup */
function _v4TitleRows(t){
  if(!t.length)return '<div class="emptyForecast">No title-race snapshot yet.</div>';
  const max=Number(t[0].pct)||1;
  return t.slice(0,12).map((x,i)=>`<div class="raceRow"><span class="raceRank">${i+1}</span><div><div class="raceTeam">${uiFlag(x.code)?`<span class="flagIcon">${uiFlag(x.code)}</span>`:''}${esc(x.team)}</div><div class="raceMeta">title probability snapshot</div></div><span class="raceBar"><i style="width:${Math.max(4,Math.round((Number(x.pct)||0)/max*100))}%"></i></span><span class="racePct">${esc(x.pct??'—')}%</span></div>`).join('');
}
function _v4TitleBySportRows(list){
  if(!list||!list.length)return '<div class="emptyForecast">No per-sport title snapshot yet.</div>';
  return list.map(x=>`<div class="raceRow"><span class="raceRank">${esc(x.label||x.comp||'')}</span><div><div class="raceTeam">${uiFlag(x.code)?`<span class="flagIcon">${uiFlag(x.code)}</span>`:''}${esc(x.team||'—')}</div><div class="raceMeta">favorite to win it all</div></div><span class="raceBar"><i style="width:${Math.max(4,Math.round(Number(x.pct)||0))}%"></i></span><span class="racePct">${esc(x.pct??'—')}%</span></div>`).join('');
}
function _v4ScorerRows(sc){
  if(!sc.length)return '<div class="emptyForecast">No scorer data yet.</div>';
  return sc.slice(0,10).map((p,i)=>`<div class="scorerRow"><span class="scorerRank">${i+1}</span><div><div class="scorerName">${esc(p.name||'')}</div><div class="scorerMeta">${esc(p.code||p.team||'')}</div></div><span class="scorerGoals">${esc(p.goals??0)} G${p.assists?` · ${esc(p.assists)} A`:''}</span></div>`).join('');
}
function _v13LeaderPanel(sc){
  const board=DATA.leaders||{},cats=board.categories||[];
  if(cats.length){
    const meta=[board.season,board.source].filter(Boolean).join(' · ');
    const cards=cats.map(c=>`<div class="leaderCategory"><div class="leaderCategoryHead"><span>${esc(c.label||c.key||'Leader')}</span><b>${esc(c.abbr||'')}</b></div><div class="leaderRows">${(c.leaders||[]).slice(0,3).map((p,i)=>`<div class="leaderRow"><span>${i+1}</span><strong>${esc(p.name||'')}</strong><b>${esc(p.value??'—')}</b></div>`).join('')}</div></div>`).join('');
    return `<section class="forecastPanel leaderPanel"><div class="forecastPanelHead"><h3>Season leaders</h3><span>${esc(meta||'verified stats')}</span></div><div class="leaderCategoryGrid">${cards}</div></section>`;
  }
  if(sc.length)return `<section class="forecastPanel"><div class="forecastPanelHead"><h3>Scoring leaders</h3><span>goals & assists</span></div><div class="scorerList">${_v4ScorerRows(sc)}</div></section>`;
  return '';
}
function _v4MatchSnapshots(){
  const M=(DATA.matches||[]).filter(m=>m.status!=='FINISHED'&&!isStaleUpcoming(m)&&(m.markets?.['1x2']||m.prediction)).sort((a,b)=>(a.kickoff||'').localeCompare(b.kickoff||'')).slice(0,8);
  if(!M.length)return '<div class="emptyForecast">No upcoming match snapshots yet.</div>';
  return M.map(m=>{const pr=m.prediction||{},x=(m.markets||{})['1x2']||{};const probs=_v4ModelProbs(m);const twoWay=_isTwoWay(m);const hp=Math.round(Number(probs.h??x.home_pct??0)),dp=Math.round(Number(probs.d??x.draw_pct??0)),ap=Math.round(Number(probs.a??x.away_pct??0));const drawLine=twoWay?'':`<div class="probLine"><span class="sideName">Draw</span><span class="probTrack"><i class="probFill d" style="width:${Math.max(3,dp)}%"></i></span><span class="pct">${dp}%</span></div>`;return `<div class="matchSnapRow" onclick="openMatchModal('${esc(String(m.id||''))}')"><div><div class="matchSnapTeams">${esc(m.home?.code||m.home?.name||'H')} v ${esc(m.away?.code||m.away?.name||'A')}</div><div class="matchSnapMeta">${isForecastPaused(m)?'Market odds · ':''}${esc(m.stage||'')} \u2013 ${kickIn(m.kickoff)}</div></div><div class="probLines"><div class="probLine"><span class="sideName">${esc(m.home?.code||'H')}</span><span class="probTrack"><i class="probFill h" style="width:${Math.max(3,hp)}%"></i></span><span class="pct">${hp}%</span></div>${drawLine}<div class="probLine"><span class="sideName">${esc(m.away?.code||'A')}</span><span class="probTrack"><i class="probFill a" style="width:${Math.max(3,ap)}%"></i></span><span class="pct">${ap}%</span></div></div></div>`}).join('');
}
function _v4AdvancementTable(adv){
  if(!adv.length)return '';
  const stages=Object.keys(adv[0].stages||{});
  const advCols=`grid-template-columns:minmax(150px,1.6fr) repeat(${stages.length},minmax(56px,1fr))`;
  return `<section class="forecastPanel"><div class="forecastPanelHead"><h3>Advancement path</h3><span>model projection</span></div><div class="advtable v4"><div class="advrow advhead" style="${advCols}"><span>Team</span>${stages.map(sg=>`<span>${esc(sg==='Champion'?'Win':sg.replace('-finals','F').replace('Round of ','R'))}</span>`).join('')}</div>${adv.slice(0,18).map(r=>`<div class="advrow" style="${advCols}"><span class="advteam">${uiFlag(r.code)?`<span class="flagIcon">${uiFlag(r.code)}</span> `:''}${esc(r.team)}</span>${stages.map(sg=>{const v=r.stages[sg];return `<span class="advpct ${v>=50?'hi':v<10?'lo':''}">${v!=null?v+'%':'&mdash;'}</span>`}).join('')}</div>`).join('')}</div><div class="forecastDisclaimer">Projection only. Later rounds depend on the field that actually survives.</div></section>`;
}
function renderTitle(){
  const t=DATA.title_odds||[],adv=DATA.advancement||[],sc=DATA.scorers||[],upsets=_v4UpsetRows();
  const upcoming=(DATA.matches||[]).filter(m=>m.status!=='FINISHED'&&!isStaleUpcoming(m)).length;
  let html=`<div class="forecastShell"><div class="marketBanner"><b>Still calibrating.</b> Much of Matchday is still being built, and the model runs on free-tier data for now, so some of these forecasts are rougher than they will be. Treat this board as a testing ground rather than a finished read. Accuracy should improve as the data sources and tuning improve.</div><div class="forecastHero"><div><h2>Forecast board</h2><p>Tournament probabilities, upset risk, advancement paths, and scorer races, in one place.</p></div><div class="forecastKpis"><div class="forecastKpi"><span>Upcoming</span><b>${upcoming}</b></div><div class="forecastKpi"><span>Upset watch</span><b>${upsets.length}</b></div><div class="forecastKpi"><span>Title teams</span><b>${t.length||'—'}</b></div></div></div>`;
  const leaderPanel=_v13LeaderPanel(sc);
  html+=`<div class="forecastGrid ${leaderPanel?'':'single'}"><section class="forecastPanel"><div class="forecastPanelHead"><h3>Upset radar</h3><span>${upsets.length} matches</span></div><div class="upsetList">${upsets.length?upsets.map(x=>`<div class="upsetRow" onclick="openMatchModal('${esc(String(x.m.id||''))}')"><div><div class="upsetMatch">${esc(x.m.home?.code||x.m.home?.name||'H')} v ${esc(x.m.away?.code||x.m.away?.name||'A')}</div><div class="upsetWhy">${esc(x.reason)}</div></div><div class="upsetWhy">${esc(x.m.stage||'')} · ${kickIn(x.m.kickoff)}</div><span class="riskPill ${x.cls}">${x.triggered?'active upset pick':x.risk>=70?'high variance':x.risk>=50?'medium variance':'low variance'}</span></div>`).join(''):'<div class="emptyForecast">No upcoming matches to analyze.</div>'}</div></section>${leaderPanel}</div>`;
  const titleBySport=DATA.title_by_sport||[];
  html+=`<div class="forecastGrid"><section class="forecastPanel"><div class="forecastPanelHead"><h3>Title race</h3><span>probability snapshot</span></div><div class="raceList">${_v4TitleRows(t)}</div></section><section class="forecastPanel"><div class="forecastPanelHead"><h3>Match snapshots</h3><span>next fixtures</span></div><div class="matchSnapList">${_v4MatchSnapshots()}</div></section></div>`;
  if(titleBySport.length)html+=`<div class="forecastGrid single"><section class="forecastPanel"><div class="forecastPanelHead"><h3>Title forecasts — every sport</h3><span>${titleBySport.length} competitions</span></div><div class="raceList">${_v4TitleBySportRows(titleBySport)}</div></section></div>`;
  html+=_v4AdvancementTable(adv);
  html+=`<div class="forecastNote">Read these as probabilities, not calls: a 38% pick is supposed to lose most of the time.</div></div>`;
  const host=$('#view-title');host.innerHTML=html;
}



/* ===== IN-FOCUS PANEL RESTORE — v5 =====
   Keep the expanded match window using the new v4 analyst card,
   but restore the right-side In Focus panel to the original compact read.
   This prevents the large expanded-window model layout from breaking the sidebar. */
/* dedup */
