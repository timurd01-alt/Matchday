function renderScore(){const sc=DATA.scorecard,host=$('#view-score');if(!sc||(!sc.graded&&!sc.pending)){host.innerHTML=`<div class="vhead">Scorecard</div><div class="empty">Picks are locked before kickoff and graded at full time.<br>Run the fetcher and check back after the next final whistle.</div>`;return}
const pctf=(h,n)=>n?Math.round(h/n*100)+'%':'—';
let h=`<div class="vhead">Scorecard</div>${renderDeepDive(sc)}<div class="status-grid">
<div class="statuscard info"><span class="slbl">Model record <button class="miniReload" title="Reload latest results" onclick="load(true)">\u21bb</button></span><div class="sval">${sc.model_hits}/${sc.graded}</div><div class="hint">${pctf(sc.model_hits,sc.graded)} of graded picks correct</div></div>
<div class="statuscard info"><span class="slbl">Market favourite</span><div class="sval">${sc.market_hits}/${sc.market_graded}</div><div class="hint">${pctf(sc.market_hits,sc.market_graded)} correct — the benchmark</div></div>
<div class="statuscard ${sc.disagree&&sc.disagree_hits/Math.max(1,sc.disagree)>=.5?'ok':'info'}"><span class="slbl">When we split with the market</span><div class="sval">${sc.disagree_hits}/${sc.disagree}</div><div class="hint">model record on disagreements</div></div>
<div class="statuscard info"><span class="slbl">Pending</span><div class="sval">${sc.pending}</div><div class="hint">picks locked, awaiting results</div></div></div>`;
const small=sc.graded<30?` <i class="ssnote">small sample</i>`:'';
h+=`<div class="status-grid" style="margin-top:10px">
	<div class="statuscard ${sc.clv_avg>0?'ok':'info'}"><span class="slbl">Closing line value</span><div class="sval">${sc.clv_avg!=null?(sc.clv_avg>0?'+':'')+sc.clv_avg:'—'}</div><div class="hint">${sc.clv_n?`beat the close ${sc.clv_beat}/${sc.clv_n}${small} — the sharps' favourite metric`:'builds as picks grade'}</div></div>
	<div class="statuscard ${sc.brier3!=null&&sc.brier3<0.55?'ok':'info'}"><span class="slbl">3-way Brier</span><div class="sval">${sc.brier3??sc.brier??'—'}</div><div class="hint">grades full home/draw/away probabilities${sc.log_loss!=null?` · log loss ${sc.log_loss}`:''}${small}</div></div>
	<div class="statuscard ${(sc.upset?.watched&&sc.upset.hits/sc.upset.watched>=.35)?'ok':'info'}"><span class="slbl">Upset radar</span><div class="sval">${sc.upset?.watched?`${sc.upset.hits}/${sc.upset.watched}`:'—'}</div><div class="hint">candidate won this often${sc.upset?.triggered?` · active picks ${sc.upset.triggered_hits}/${sc.upset.triggered}`:''}${sc.upset?.avg_score!=null?` · avg score ${sc.upset.avg_score}`:''}</div></div>
	<div class="statuscard info"><span class="slbl">Calibration</span><div class="sval" style="font-size:.9rem;line-height:1.7">${(sc.calibration||[]).map(c=>`${c.band}%: <b>${Math.round(c.hits/c.n*100)}%</b> <i class="ssnote">(${c.n})</i>`).join('<br>')||'—'}</div><div class="hint">when we say X%, how often it happens</div></div></div>`;
h+=`<div class="seclbl" style="margin-top:16px">Pick log</div>`+(sc.picks||[]).map(p=>{const done=!!p.result;const cls=done?(p.model_hit?'hit':'miss'):'wait';const badge=done?(p.model_hit?'HIT':'MISS'):'PENDING';return `<div class="scrow ${cls}"><span class="scst">${esc(p.stage||'')}</span><span class="scmatch">${esc(p.home)} v ${esc(p.away)}${p.score?` <b>${esc(p.score)}</b>`:''}</span><span class="scpick">${esc(p.pick_name||'')}${p.confidence?' · '+p.confidence+'%':''}${p.market_pick&&p.pick!==p.market_pick?' <i class="scsplit">vs market</i>':''}${p.value_side&&p.value_side!==p.pick?` <i class="scsplit vtag ${p.result?(p.value_hit?'vhit':'vmiss'):''}">chance: ${esc(p.value_name||'')} +${p.value_edge}${p.result?(p.value_hit?' &#10003;':' &#10007;'):''}</i>`:''}${p.upset_score?` <i class="scsplit upsetTag">upset ${esc(p.upset_name||'')} ${esc(p.upset_score)}/100${p.upset_triggered?' active':''}${p.result?(p.upset_hit?' &#10003;':' &#10007;'):''}</i>`:''}</span><span class="sctag ${cls}">${badge}</span></div>`}).join('');
h+=`<div class="edisc">Picks lock at first sighting before kickoff and are never rewritten. Knockout games level at full time grade as draws — shootout winners aren't counted. Model output, not betting advice.</div>`;
host.innerHTML=h}
function highlightFavoriteRows(){if(!favoriteTeam())return;document.querySelectorAll('.gtable .gteam').forEach(cell=>{if(teamKey(cell.textContent).includes(teamKey(favoriteTeam())))cell.closest('tr')?.classList.add('favoriteTeamRow')})}
function renderCurrent(){({matches:renderMatches,results:renderResults,tott:renderTOTT,groups:renderGroups,title:renderTitle,edge:renderEdge,score:renderScore,bracket:renderBracket,third:renderThird,news:renderNews,status:renderStatus,updates:renderSystemUpdates,community:renderCommunity,sandbox:renderSandbox,customize:renderCustomize}[VIEW]||renderMatches)();renderWelcome();highlightFavoriteRows();applyStaticI18n()}
function renderStrip(){const M=DATA.matches||[],live=M.filter(m=>m.status==='LIVE'),next=M.filter(isVisibleUpcoming).sort((a,b)=>(a.kickoff||'').localeCompare(b.kickoff||''))[0];const parts=[];
const isSample=(DATA.source_note||'').toLowerCase().includes('sample');
parts.push(isSample?`<span class="ls-badge sample">${t("sample data")}</span>`:live.length?`<span class="ls-badge live">${t("live data")}</span>`:`<span class="ls-badge ok">${t("live feed")}</span>`);
const streakStats=btmStats(btmGrade());
if(streakStats.streak>=2)parts.push(`<span class="ls-streak" title="Beat the Model: ${streakStats.streak} correct in a row" onclick="setView('community')">\u{1F525} ${streakStats.streak}</span>`);
if(live.length){const m=live[0];parts.push(`<span class="ls-tag"><span class="dot"></span>LIVE${m.minute?` ${m.minute}'`:''}</span>`);parts.push(`<span class="ls-live">${esc(m.home.code)} ${m.score?.home??0}–${m.score?.away??0} ${esc(m.away.code)}</span>`);if(live.length>1)parts.push(`<span class="ls-next">+${live.length-1} more live</span>`)}else parts.push(`<span class="ls-next">No live matches</span>`);if(next)parts.push(`<span class="ls-next">Next · <b>${esc(next.home.code)} v ${esc(next.away.code)}</b> ${kickIn(next.kickoff)}</span>`);else parts.push(`<span class="ls-next">No upcoming fixtures</span>`);parts.push(`<span class="ls-upd">${(()=>{try{const a=(Date.now()-new Date(DATA.updated))/60000;if(a>360)return `<b class="stale">data ${ago(DATA.updated)}</b> · `;}catch(e){}return 'Updated '+ago(DATA.updated)+' · ';})()}${t("analytics only, not betting advice")} · <b style="color:var(--signal)">build 0720F</b></span>`);$('#strip').innerHTML=parts.join('')}
/* removed duplicate (diverseNews) */
/* removed duplicate (renderInsight) */
function setView(v){VIEW=v;document.querySelectorAll('.navbtn').forEach(b=>b.setAttribute('aria-pressed',b.dataset.v===v));document.querySelectorAll('.view').forEach(el=>el.style.display=el.id==='view-'+v?((v==='matches'||v==='results')?'grid':'block'):'none');renderCurrent()}
$('#nav').addEventListener('click',e=>{const b=e.target.closest('.navbtn');if(b)setView(b.dataset.v)});
async function load(manual=false){if(LOAD_TIMER){clearTimeout(LOAD_TIMER);LOAD_TIMER=null}try{
  if(!DATA_FILE){ // ALL SPORTS: merge every sport file that exists
    const keys=['wc','ucl','epl','laliga','seriea','bundesliga','ligue1','nfl','ncaaf','ncaam','nba'];
    const results=await Promise.all(keys.map(k=>fetch('data_'+k+'.json?_='+Date.now()).then(r=>r.ok?r.json():null).catch(()=>null)));
    let base=null;const merged=[];let news=[];let latest='';
    results.forEach((d,i)=>{if(!d)return;if(!base)base=d;
      (d.matches||[]).forEach(m=>{m._comp=(d.comp_key||keys[i].toUpperCase());merged.push(m);});
      const comp=d.comp_key||keys[i].toUpperCase();
      const compLabel=SPORT_LABELS[String(comp).toLowerCase()]||d.competition||comp;
      news=news.concat((d.news||[]).slice(0,8).map(a=>({...a,_comp:a.competition||comp,feed:compLabel})));
      if((d.updated||'')>latest)latest=d.updated;});
    if(!base){const r0=await fetch('data.json?_='+Date.now());if(!r0.ok)throw new Error('no data files yet — run a fetch');base=await r0.json();(base.matches||[]).forEach(m=>merged.push(m));news=base.news||[];latest=base.updated;}
    merged.sort((a,b)=>(a.kickoff||'').localeCompare(b.kickoff||''));
    DATA=Object.assign({},base,{matches:merged,news:news,updated:latest,competition:'All sports',comp_key:'ALL',standings:[],third_race:[],scorecard:base.scorecard});
  } else {
    const r=await fetch(DATA_FILE+'?_='+Date.now());if(!r.ok)throw new Error('HTTP '+r.status);DATA=await r.json();
  }BYID={};(DATA.matches||[]).forEach(m=>BYID[m.id]=m);LAST_OK=true;LAST_ERROR='';const cn=$('#compName');if(cn)cn.textContent=DATA.competition?' · '+DATA.competition:'';const tb=document.querySelector('.navbtn[data-v="third"]');if(tb)tb.style.display=(DATA.third_race&&DATA.third_race.length)?'':'none';const gb2=document.querySelector('.navbtn[data-v="groups"]');if(gb2)gb2.style.display=(DATA.standings&&DATA.standings.length)?'':'none';const note=(DATA.source_note||'').toLowerCase();$('#banner').innerHTML=note.includes('sample')?``:'';applySportNav();renderStrip();renderInsight();renderCurrent();applyStaticI18n();renderAlerts()}catch(e){console.error(e);applySportNav();
  const sel=currentSportKey();
  if(sel&&(!DATA||((DATA.comp_key||'').toLowerCase()!==sel))){
    DATA={matches:[],news:[],standings:[],third_race:[],bracket:null,scorecard:null,title_odds:[],scorers:[],team_of_tournament:null,
          comp_key:sel.toUpperCase(),competition:(SPORT_LABELS[sel]||sel),updated:'',_missing:true};
    BYID={};
  }
  LAST_OK=false;LAST_ERROR=String(e.message||e);$('#strip').textContent='no data';const selKey=(DATA_FILE.match(/data_(\w+)\.json/)||[])[1];$('#view-matches').innerHTML=`<div class="empty" style="grid-column:1/-1">${selKey?`No ${SPORT_LABELS[selKey]||selKey.toUpperCase()} data yet.<br><span class="faintline">Run start_${esc(selKey)}.bat once to pull it, or <a href="#" onclick="changeSport('');return false" style="color:var(--signal)">switch back to Auto</a>.</span>`:`Data file not loaded.<br><span class="faintline">${esc(LAST_ERROR)}</span>`}</div>`;if(VIEW==='status')renderStatus()}finally{const ss=$('#sportSel');if(ss)ss.value=(DATA_FILE.match(/data_(\w+)\.json/)||['',''])[1];scheduleNextLoad()}}
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
  (DATA.standings||[]).forEach(g=>(g.teams||[]).forEach(t=>{if(teamKey(t.name)===key)standRec=t;}));
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
        <div class="tpStat"><span class="tpStatLbl">Points</span><b>${p.pts}</b></div>
        <div class="tpStat"><span class="tpStatLbl">Goal/point diff</span><b>${p.gd>0?'+':''}${p.gd}</b></div>
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
function compactBracketMatch(km,last=false,side='left',isFinal=false){const live=km.status==='LIVE',done=km.status==='FINISHED';const hs=km.score?.home,as=km.score?.away;const hw=done&&Number(hs)>Number(as),aw=done&&Number(as)>Number(hs);const cls=`brMini ${live?'live':''} ${done?'done':''} ${isFinal?'finalCard':''} ${last?'':side==='right'?'connectL':'connectR'} ${(!km.home&&!km.away)?'tbd':''}`;return `<div class="${cls}">${isFinal?'<div class="finalBadge">Final</div>':''}<div class="bmMeta"><span>${esc(km.stage||km.round||'Match')}</span><span>${live?'LIVE':done?'FT':km.kickoff?dt(km.kickoff):'TBD'}</span></div>${bracketTeam(km.home,km.home_code||km.homeCode||'',km.home_slot||'',done||live?hs:null,hw,live)}${bracketTeam(km.away,km.away_code||km.awayCode||'',km.away_slot||'',done||live?as:null,aw,live)}</div>`}
/* removed duplicate (compactProjectedMatch) */
function splitHalf(arr,half){arr=arr||[];const mid=Math.ceil(arr.length/2);return half==='left'?arr.slice(0,mid):arr.slice(mid)}
/* removed duplicate (roundMatches) */
function shortRoundName(name){return name.replace('Round of ','R').replace('Quarter-finals','QF').replace('Semi-finals','SF').replace('Third-place playoff','3rd')}
/* removed duplicate (bracketColumn) */
/* removed duplicate (renderBracket) */

function _srcClean(x){x=String(x||'').replace(/\s+/g,' ').trim();if(!x)return'';x=x.replace(/^www\./i,'').replace(/\.com$/i,'');const map=[[/espn|espn fc/i,'ESPN'],[/bbc/i,'BBC Sport'],[/guardian/i,'The Guardian'],[/sky\s*sports|skysports/i,'Sky Sports'],[/cbs/i,'CBS Sports'],[/fox\s*sports|foxsports/i,'FOX Sports'],[/reuters/i,'Reuters'],[/associated\s*press|^ap$/i,'Associated Press'],[/fifa/i,'FIFA'],[/le\s*monde|lemonde/i,'Le Monde'],[/marca/i,'Marca'],[/goal/i,'Goal'],[/yahoo/i,'Yahoo Sports'],[/nbc/i,'NBC Sports'],[/google\s*news/i,'Google News']];for(const [re,n] of map)if(re.test(x))return n;return x.split('|')[0].trim()}
function _srcFromTitle(a){const h=String(a.headline||a.title||'');const parts=h.split(/\s[-–—]\s/g).map(x=>x.trim()).filter(Boolean);if(parts.length>1){const tail=parts[parts.length-1];if(tail.length<=42&&!/world cup|football|soccer|latest|news|live/i.test(tail))return _srcClean(tail)}return''}
function _srcFromLink(a){try{const u=new URL(a.link||a.url||'',location.href);let h=u.hostname.replace(/^www\./,'');if(h.includes('news.google.'))return'';if(h.includes('espn'))return'ESPN';if(h.includes('bbc'))return'BBC Sport';if(h.includes('theguardian'))return'The Guardian';if(h.includes('skysports'))return'Sky Sports';if(h.includes('cbssports'))return'CBS Sports';if(h.includes('foxsports'))return'FOX Sports';if(h.includes('reuters'))return'Reuters';if(h.includes('apnews'))return'Associated Press';if(h.includes('fifa'))return'FIFA';if(h.includes('marca'))return'Marca';if(h.includes('goal'))return'Goal';return _srcClean(h.split('.')[0])}catch(e){return''}}
function sourceName(a){const raw=_srcClean(a.source_name||a.publisher||a.provider||a.source||a.feed_source||'');const feed=_srcClean(a.feed||'');const titleSrc=_srcFromTitle(a),linkSrc=_srcFromLink(a);const generic=s=>!s||/^(news|headlines|football|soccer|rss|google news|world cup)$/i.test(s);if(raw&&!generic(raw))return raw;if(titleSrc&&!generic(titleSrc))return titleSrc;if(linkSrc&&!generic(linkSrc))return linkSrc;if(feed&&!generic(feed))return feed;return raw||feed||'News'}
function feedName(a){const f=_srcClean(a.feed||'');return f&&f!==sourceName(a)?f:''}
function newsBuckets(){const buckets={};(DATA.news||[]).forEach((a,i)=>{const src=sourceName(a);(buckets[src] ||= []).push({...a,_idx:i})});return buckets}
function newsSources(){const buckets=newsBuckets();return ['all',...Object.keys(buckets).sort((a,b)=>a.localeCompare(b))]}
function diverseNews(limit=12){
  const all=DATA.news||[],allSports=DATA.comp_key==='ALL'||DATA.competition==='All sports';
  const buckets={};
  all.forEach((a,i)=>{const key=allSports?(a._comp||a.competition||'OTHER'):sourceName(a);(buckets[key]||=[]).push({...a,_idx:i})});
  const keys=Object.keys(buckets).sort((a,b)=>a.localeCompare(b)),out=[];let row=0;
  while(out.length<limit&&keys.length){let moved=false;for(const key of keys){const item=buckets[key][row];if(item){out.push(item);moved=true;if(out.length>=limit)break}}if(!moved)break;row++}
  const result=out.length?out:all.slice(0,limit),fav=favoriteNewsTerm();
  return fav?result.sort((a,b)=>Number(teamKey(`${b.headline||b.title||''} ${b.desc||''}`).includes(fav))-Number(teamKey(`${a.headline||a.title||''} ${a.desc||''}`).includes(fav))):result;
}
function renderNews(){const n=DATA.news||[],host=$('#view-news'),links=DATA.social_links||[],diag=DATA.diagnostics||[];const buckets=newsBuckets(),srcs=newsSources();if(NEWS_FILTER!=='all'&&!buckets[NEWS_FILTER])NEWS_FILTER='all';let list=NEWS_FILTER==='all'?diverseNews(Math.max(n.length,18)):buckets[NEWS_FILTER]||[];host.innerHTML=`<div class="vhead">News cycle</div>${links.length?`<div class="seclbl">Social / source quick links</div><div class="socialGrid">${links.map(l=>`<a href="${esc(l.url)}" target="_blank" rel="noopener">${esc(l.name)}</a>`).join('')}</div>`:''}<div class="srcCount">${n.length} headlines · ${srcs.length-1} detected sources</div><div class="newsTools">${srcs.map(s=>`<button class="chip ${s==='all'?'allchip':''} ${NEWS_FILTER===s?'on':''}" data-src="${esc(s)}" onclick="NEWS_FILTER=this.dataset.src;renderNews()">${esc(s==='all'?'All sources':s)}<span class="count">${s==='all'?n.length:(buckets[s]||[]).length}</span></button>`).join('')}</div>`+(list.length?list.map(a=>`<a class="ncard" href="${esc(a.link||a.url||'#')}" target="_blank" rel="noopener"><div class="srcTop"><span class="srcBadge">${esc(sourceName(a))}</span>${feedName(a)?`<span class="feedBadge">via ${esc(feedName(a))}</span>`:''}</div><div class="nhead">${esc(a.headline||a.title||'Untitled')}</div>${a.desc||a.description?`<div class="ndesc">${esc(a.desc||a.description)}</div>`:''}<div class="nmeta">${a.published?ago(a.published):''}</div></a>`).join(''):`<div class="empty">No headlines yet.</div>`)+(diag.length?`<div class="diagList">${diag.filter(d=>String(d).toLowerCase().includes('news')).map(d=>`<div>${esc(d)}</div>`).join('')}</div>`:'')}



/* ===== UI PATCH: model dashboard polish only; data untouched ===== */
function _modelIsArchived(m){return m.status==='FINISHED'||isStaleUpcoming(m)}
function _modelEdgeKind(pr){if(!pr||pr.edge==null)return'level';return pr.edge>=6?'value':pr.edge<=-6?'fade':'level'}
function _modelSortScore(m){const pr=m.prediction||{};const archived=_modelIsArchived(m)?-10000:0;const live=m.status==='LIVE'?1000:0;const upcoming=isVisibleUpcoming(m)?500:0;const edge=pr.edge==null?0:Math.max(0,pr.edge)*10;const conf=Number(pr.confidence)||0;return archived+live+upcoming+edge+conf}
function _modelMarketText(m,side){if(_modelIsArchived(m))return 'archived pick';const mk=(m.markets||{})['1x2']||{};const v={h:mk.home_pct,d:mk.draw_pct,a:mk.away_pct}[side];return v==null?'market n/a':`${v}% market`}
function _modelWhen(m){if(m.status==='LIVE')return `LIVE ${m.minute||''}'`;if(m.status==='FINISHED')return 'Finished';if(isStaleUpcoming(m))return 'Past kickoff';return kickIn(m.kickoff)}
function _modelTag(m){const pr=m.prediction||{},kind=_modelEdgeKind(pr);if(_modelIsArchived(m))return {txt:'ARCHIVE',kind:'level'};if(m.status==='LIVE')return {txt:'LIVE',kind:'live'};if(kind==='value')return {txt:'VALUE',kind:'value'};if(kind==='fade')return {txt:'CAUTION',kind:'fade'};if((Number(pr.confidence)||0)>=65)return {txt:'HIGH CONF',kind:'level'};return {txt:'MODEL',kind:'level'}}
function _modelBars(pr){const md=pr.model||pr.blend||{};const rows=[['H','home',md.h],['D','draw',md.d],['A','away',md.a]];return `<div class="modelBars">${rows.map(([lab,cls,val])=>{val=Math.max(0,Math.min(100,Number(val)||0));return `<div class="modelBarLine"><span>${lab}</span><div class="modelBarTrack"><span class="modelBarFill ${cls}" style="width:${Math.max(2,val)}%"></span></div><span>${Math.round(val)}%</span></div>`}).join('')}</div>`}
function _modelFinalText(m){const s=m.score||{};if(s.home!=null&&s.away!=null)return `${s.home}–${s.away}`;return _modelWhen(m)}
/* dedup */
/* dedup */
function _modelApplyFilter(all){const f=window.MODEL_FILTER||'action';return all.filter(m=>{const archived=_modelIsArchived(m),pr=m.prediction||{},edge=Number(pr.edge)||0,conf=Number(pr.confidence)||0,hasOdds=!!((m.markets||{})['1x2']);if(f==='archive')return archived;if(archived)return false;if(f==='all')return true;if(f==='action')return m.status==='LIVE'||isVisibleUpcoming(m);if(f==='live')return m.status==='LIVE';if(f==='upcoming')return isVisibleUpcoming(m);if(f==='value')return edge>=6;if(f==='caution')return edge<=-6;if(f==='high')return conf>=65;if(f==='odds')return hasOdds;return true})}
function _modelFilterBtn(key,label,count){const on=(window.MODEL_FILTER||'action')===key;return `<button class="chip ${on?'on':''}" onclick="window.MODEL_FILTER='${key}';renderEdge()">${label}<span class="count">${count}</span></button>`}
function _archiveRow(m){const pr=m.prediction||{};return `<div class="archiveRow" onclick="openMatchModal('${esc(String(m.id||''))}')"><div><div class="archiveTeams">${esc(m.home?.code||m.home?.name||'H')} v ${esc(m.away?.code||m.away?.name||'A')}</div><div class="archiveMeta">${esc(m.stage||'Fixture')} · ${_modelWhen(m)}</div></div><div class="archiveResult">${esc(_modelFinalText(m))}</div><div class="archivePick">Pick <b>${esc(pr.pick_name||'—')}</b> · ${pr.confidence??'—'}%</div><div class="archiveBadge">Review</div></div>`}
function renderEdge(){const host=$('#view-edge');const all=(DATA.matches||[]).filter(m=>m.prediction).sort((a,b)=>_modelSortScore(b)-_modelSortScore(a));if(!all.length){host.innerHTML=`<div class="vhead">Model</div>${(()=>{const sc=DATA.scorecard;if(!sc||!sc.graded)return '';const rec=`${sc.model_hits}-${sc.graded-sc.model_hits}`;const br=sc.brier!=null?sc.brier:'—';const cl=sc.clv_avg!=null?(sc.clv_avg>0?'+':'')+sc.clv_avg:'—';const vs=sc.value&&sc.value.all?`${sc.value.all.hits}/${sc.value.all.n}`:'—';return `<div class="credstrip"><span class="credtag">Model record</span><span class="creditem"><b>${rec}</b> last ${sc.graded}</span><span class="creditem">Brier <b>${br}</b></span><span class="creditem">CLV <b>${cl}</b></span><span class="creditem">Value <b>${vs}</b></span>${sc.graded<20?'<span class="crednote">small sample</span>':''}</div>`;})()}<div class="empty">No model picks yet.</div>`;return}if(!window.MODEL_FILTER||window.MODEL_FILTER==='finished')window.MODEL_FILTER='action';const archived=all.filter(_modelIsArchived).sort((a,b)=>new Date(b.kickoff||0)-new Date(a.kickoff||0));const active=all.filter(m=>!_modelIsArchived(m));const counts={all:active.length,action:active.filter(m=>m.status==='LIVE'||isVisibleUpcoming(m)).length,live:active.filter(m=>m.status==='LIVE').length,upcoming:active.filter(isVisibleUpcoming).length,value:active.filter(m=>(m.prediction?.edge||0)>=6).length,caution:active.filter(m=>(m.prediction?.edge||0)<=-6).length,high:active.filter(m=>(Number(m.prediction?.confidence)||0)>=65).length,odds:active.filter(m=>!!((m.markets||{})['1x2'])).length,archive:archived.length};const list=_modelApplyFilter(all).sort((a,b)=>_modelSortScore(b)-_modelSortScore(a));const actionable=active.filter(m=>m.status==='LIVE'||isVisibleUpcoming(m));const value=active.filter(m=>(m.prediction?.edge||0)>=6);const caution=active.filter(m=>(m.prediction?.edge||0)<=-6);const high=active.filter(m=>(Number(m.prediction?.confidence)||0)>=65);const archiveMode=window.MODEL_FILTER==='archive';let html=`<div class="modelShell"><div class="modelHero"><div><div class="modelHeroTitle">Model command center</div><div class="modelHeroSub">Current picks, consensus gap, and confidence.</div></div><div class="modelKpis"><div class="modelKpi"><span>Actionable</span><b>${actionable.length}</b></div><div class="modelKpi good"><span>Model leans</span><b>${value.length}</b></div><div class="modelKpi warn"><span>High confidence</span><b>${high.length}</b></div><div class="modelKpi bad"><span>Archived</span><b>${archived.length}</b></div></div></div><div class="modelToolbar">${_modelFilterBtn('action','Actionable',counts.action)}${_modelFilterBtn('live','Live',counts.live)}${_modelFilterBtn('upcoming','Upcoming',counts.upcoming)}${_modelFilterBtn('value','Model lean',counts.value)}${_modelFilterBtn('caution','Caution',counts.caution)}${_modelFilterBtn('high','High confidence',counts.high)}${_modelFilterBtn('odds','With market',counts.odds)}${_modelFilterBtn('all','All active',counts.all)}${_modelFilterBtn('archive','Archive',counts.archive)}</div>${_modelSpotlight(active)}<div class="modelGrid"><section class="modelPanel"><div class="modelPanelHead"><h3>${archiveMode?'Completed archive':'Active pick board'}</h3><span>${list.length} shown</span></div><div class="modelList">${list.length?list.map(_modelRow).join(''):`<div class="modelEmptySmall">No matches in this filter.</div>`}</div></section><section class="modelPanel"><div class="modelPanelHead"><h3>${archiveMode?'Archive reads':'Quick reads'}</h3><span>digest</span></div><div class="modelReadList">`;const reads=(list.length?list:(archiveMode?archived:active)).slice(0,5);html+=reads.map((m,i)=>{const pr=m.prediction||{},tag=_modelTag(m),txt=_modelIsArchived(m)?`${pr.pick_name||'Model'} was ${pr.confidence||'—'}%. Result: ${_modelFinalText(m)}.`:(edgeBreakdown(m)||`${pr.pick_name||'Model'} at ${pr.confidence||'—'}%.`);return `<div class="modelRead" onclick="openMatchModal('${esc(String(m.id||''))}')"><div class="rtitle"><span>${tag.txt}</span>${esc(m.home?.code||'H')} v ${esc(m.away?.code||'A')}</div><p>${esc(txt)}</p></div>`}).join('');html+=`</div></section>`;if(!archiveMode&&archived.length){html+=`<section class="modelPanel modelArchivePanel"><div class="modelPanelHead"><h3>Completed archive <span class="archiveBadge">${archived.length}</span></h3><span><button class="chip" onclick="window.MODEL_FILTER='archive';renderEdge()">View all</button></span></div><div class="modelList">${archived.slice(0,8).map(_archiveRow).join('')}</div></section>`}html+=`</div></div>`;host.innerHTML=html}



/* ===== UI PATCH: complete bracket render; UI only, data untouched ===== */
function _canonRoundName(name){
  const x=String(name||'').toLowerCase().replace(/[_-]/g,' ');
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
  const src=(DATA.projected_bracket&&Array.isArray(DATA.projected_bracket.slots)&&DATA.projected_bracket.slots.length)?DATA.projected_bracket.slots:getProjectedSlots();
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
function uiFlag(code){if(!['WC','UCL','EPL','LALIGA','SERIEA','BUNDESLIGA','LIGUE1'].includes(String(DATA?.comp_key||'')))return'';try{return flagEmoji(code||'')||''}catch(e){return''}}
function uiTeamFlag(team){return uiFlag(team?.code||codeForTeam(team?.name||'',team?.code||''))}
function teamFlagHTML(team,away=false){const fl=uiTeamFlag(team);return fl?`<span class="flagIcon ${away?'away':''}">${fl}</span>`:''}
function shortPlayerName(name){const s=String(name||'').trim();if(!s)return'';const parts=s.split(/\s+/).filter(Boolean);return parts.length>1?parts[parts.length-1]:s}
function formationParts(f){const nums=String(f||'').match(/\d+/g);return nums?nums.map(Number).filter(n=>n>0):[]}
function normalizePlayer(p){return {n:String(p?.n??p?.number??'').trim(),name:String(p?.name??p?.shortName??p?.athlete?.displayName??'').trim(),out:!!p?.out}}
function lineupRows(xi,formation){const players=(xi||[]).map(normalizePlayer).filter(p=>p.n||p.name);if(!players.length)return[];const parts=formationParts(formation);if(!parts.length){const rows=[];for(let i=0;i<players.length;i+=3)rows.push(players.slice(i,i+3));return rows}const rows=[];let idx=0;rows.push(players.slice(idx,idx+1));idx+=1;parts.forEach(c=>{rows.push(players.slice(idx,idx+c));idx+=c});if(idx<players.length)rows.push(players.slice(idx));return rows.filter(r=>r.length)}
function pitchPlayer(p){const nm=shortPlayerName(p.name)||`#${p.n||'?'}`;return `<div class="pitchPlayer ${p.out?'out':''}" title="${esc((p.n?('#'+p.n+' '):'')+(p.name||''))}"><div class="num">${esc(p.n||'—')}</div><div class="pname">${esc(nm)}</div>${p.out?'<span class="subMark">sub</span>':''}</div>`}
function pitchTeamCard(team,line,side){const rows=lineupRows(line?.xi||[],line?.formation||'');const fl=teamFlagHTML(team);const form=line?.formation||'XI';return `<div class="pitchCard ${side}"><div class="pitchHeader"><div class="pitchTeamName">${fl}<span>${esc(team?.name||side)}</span></div><div class="formationBadge">${esc(form)}</div></div>${rows.length?`<div class="pitch">${rows.map(r=>`<div class="pitchRow">${r.map(pitchPlayer).join('')}</div>`).join('')}</div>`:`<div class="emptyStats">Lineup not available.</div>`}<div class="lineupFoot"><span>${esc(team?.code||'')}</span><span>${rows.reduce((a,r)=>a+r.length,0)} players shown</span></div></div>`}
function lineupsPanel(m){const l=m.lineups;if(l&&((l.home?.xi||[]).length||(l.away?.xi||[]).length)){return `<div class="lineupBoard pitchMode"><div class="seclbl">Lineups</div><div class="pitchGrid">${pitchTeamCard(m.home,l.home||{},'home')}${pitchTeamCard(m.away,l.away||{},'away')}</div></div>`}return `<div class="lineupBoard pitchMode"><div class="seclbl">Lineups</div><div class="emptyStats">Lineups not available yet.</div></div>`}
function teamSnap(team,side){const gd=Number(team?.gd||0),form=String(team?.form||'').trim();return `<div class="teamSnap ${side==='away'?'away':''}"><div class="snapCode">${teamFlagHTML(team,side==='away')}${esc(team?.code||side)}</div><div class="snapName">${esc(team?.name||'TBD')}</div><div class="snapMeta">${team?.pos?`#${team.pos} · `:''}${team?.pts??0} pts · GD ${gd>0?'+':''}${gd}${form?` · ${esc(form)}`:''}</div></div>`}
function oddsTier(p,i){p=Number(p)||0;if(i<3)return'hot';if(p>=7)return'live';if(p>=3)return'chase';return''}
function oddsTierText(p,i){p=Number(p)||0;if(i<3)return'Contender';if(p>=7)return'In range';if(p>=3)return'Chaser';return'Long shot'}
function oddsCode(x){return x.code||codeForTeam(x.team||'',x.code||'')||''}
/* dedup */
function _v15RenderLeagueTable(st,host){const seen=new Set(),teams=[];(st||[]).forEach(g=>(g.teams||[]).forEach(t=>{const key=String(t.name||t.code||'').toLowerCase();if(key&&!seen.has(key)){seen.add(key);teams.push(t)}}));teams.sort((a,b)=>(Number(a.pos)||999)-(Number(b.pos)||999)||(Number(b.pts)||0)-(Number(a.pts)||0)||(Number(b.gd)||0)-(Number(a.gd)||0));host.innerHTML=`<div class="vhead">Table</div><div class="tablewrap leagueTableWrap"><div class="groupHead">${esc(DATA.competition||'League table')}<span>${teams.length} clubs · full table</span></div><table class="gtable"><thead><tr><th>Team</th><th>P</th><th>W</th><th>D</th><th>L</th><th>GF</th><th>GA</th><th>GD</th><th>Pts</th><th>Form</th></tr></thead><tbody>${teams.map((t,i)=>{const q=t.qual?`<span class="qbadge ${esc(t.qual.status||'')}" title="${esc(t.qual.note||'')}">${esc(t.qual.status||t.qual.note||'')}</span>`:'';return `<tr><td><div class="gteam teamClickable" data-team="${esc(t.name||'')}" onclick="openTeamModal(this.dataset.team)"><span class="pos">${t.pos||i+1}</span><span class="code">${esc(t.code||'')}</span>${esc(t.name||'')} ${q}</div></td><td>${t.pld??'—'}</td><td>${t.w??'—'}</td><td>${t.d??'—'}</td><td>${t.l??'—'}</td><td>${t.gf??'—'}</td><td>${t.ga??'—'}</td><td>${t.gd??'—'}</td><td><b>${t.pts??'—'}</b></td><td class="form">${esc(t.form||'')}</td></tr>`}).join('')}</tbody></table></div>`}
function renderGroups(){const st=deriveStandings(),host=$('#view-groups'),sc=DATA.scorers||[];if(!st.length){host.innerHTML=`<div class="vhead">${DATA.comp_key==='NCAAM'?'Conferences':navProfile()==='soccer_league'?'Table':'Groups'}</div><div class="empty">No group data found yet.</div>`;return}if(navProfile()==='soccer_league'){_v15RenderLeagueTable(st,host);return}if(DATA.comp_key==='NCAAM'){host.innerHTML=`<div class="vhead">Conferences</div>`+st.map(g=>`<div class="tablewrap"><div class="groupHead">${esc(g.group)}<span>${g.group==='Top 25'?'national poll':'raw season records'}</span></div><table class="gtable ncaamTable"><thead><tr><th>Team</th><th>Record</th><th>Win%</th><th>PF/G</th><th>PA/G</th><th>Diff</th><th>Streak</th></tr></thead><tbody>${(g.teams||[]).map(t=>`<tr><td><div class="gteam teamClickable" data-team="${esc(t.name||'')}" onclick="openTeamModal(this.dataset.team)"><span class="pos">${t.pos||''}</span><span class="code">${esc(t.code||'')}</span>${esc(t.name||'')}</div></td><td><b>${esc(t.record||`${t.w??'—'}-${t.l??'—'}`)}</b></td><td>${t.win_pct!=null?(Number(t.win_pct)*100).toFixed(1)+'%':'—'}</td><td>${t.avg_pf!=null&&Number(t.avg_pf)?Number(t.avg_pf).toFixed(1):'—'}</td><td>${t.avg_pa!=null&&Number(t.avg_pa)?Number(t.avg_pa).toFixed(1):'—'}</td><td>${t.gd!=null?esc(t.gd):'—'}</td><td class="form">${esc(t.form||'—')}</td></tr>`).join('')}</tbody></table></div>`).join('');return}host.innerHTML=`<div class="vhead">Groups</div>`+st.map(g=>`<div class="tablewrap"><div class="groupHead">${esc(g.group)}<span>Top 2 · 3rd</span></div><table class="gtable"><thead><tr><th>Team</th><th>P</th><th>W</th><th>D</th><th>L</th><th>GF</th><th>GA</th><th>GD</th><th>Pts</th><th>Form</th></tr></thead><tbody>${(g.teams||[]).map(t=>{const fl=uiFlag(t.code);const q=t.qual?`<span class="qbadge ${esc(t.qual.status)}" title="${esc(t.qual.note)}">${esc(t.qual.note)}</span>`:'';return `<tr class="${t.pos<=2?'qual':t.pos===3?'third':''}"><td><div class="gteam teamClickable" data-team="${esc(t.name||'')}" onclick="openTeamModal(this.dataset.team)"><span class="pos">${t.pos||''}</span>${fl?`<span class="flagIcon">${fl}</span>`:''}<span class="code">${esc(t.code||'')}</span>${esc(t.name)} ${t.live?'<span class="liveMark">*</span>':''}${q}</div></td><td>${t.pld}</td><td>${t.w}</td><td>${t.d}</td><td>${t.l}</td><td>${t.gf}</td><td>${t.ga}</td><td>${t.gd}</td><td><b>${t.pts}</b></td><td class="form">${esc(t.form||'')}</td></tr>`}).join('')}</tbody></table></div>`).join('')}
/* dedup */
function openMatchModal(id){const m=BYID[id]||(DATA.matches||[]).find(x=>String(x.id)===String(id));if(!m)return;const modal=ensureMatchModal();const hmeta=t=>`${t?.pos?`#${t.pos} · `:''}${t?.pts??0} pts${t?.form?` · ${esc(t.form)}`:''}`;modal.innerHTML=`<section class="matchSheet" role="dialog" aria-modal="true"><div class="modalHero"><button class="modalClose" onclick="closeMatchModal()" aria-label="Close">×</button><div class="modalStage">${esc(m.stage||'Fixture')} · ${esc(m.status||'')}</div><div class="modalFixture"><div class="modalTeam"><div class="modalCode">${teamFlagHTML(m.home)}${esc(m.home?.code||'HOME')}</div><div class="modalName">${esc(m.home?.name||'Home')}</div><div class="modalMeta">${hmeta(m.home)}</div></div><div class="modalScore"><div class="bigScore">${scoreText(m).replace(/<[^>]+>/g,'')}</div><div class="modalStatus">${m.status==='LIVE'?`LIVE ${m.minute||''}'`:kickIn(m.kickoff)}</div></div><div class="modalTeam away"><div class="modalCode">${esc(m.away?.code||'AWAY')}${teamFlagHTML(m.away,true)}</div><div class="modalName">${esc(m.away?.name||'Away')}</div><div class="modalMeta">${hmeta(m.away)}</div></div></div></div><div class="modalBody">${details(m)}</div></section>`;modal.classList.add('show');document.body.classList.add('modalOpen')}




/* ===== MODEL PICK REDESIGN — v3 =====
   This override intentionally avoids the old .pick/.fchip markup inside the modal.
   It prevents vertical letters, cramped chips, and overlap. */
function modelFactorCardsV3(pr){
  if(!pr)return'';
  const labels={pts:'points',gd:'goal diff',form:'form',adv:'home',class:'class',rest:'rest'};
  const cards=[];
  if(pr.why){
    Object.entries(pr.why)
      .filter(([k,v])=>Math.abs(Number(v)||0)>=0.3&&labels[k])
      .sort((a,b)=>Math.abs(Number(b[1])||0)-Math.abs(Number(a[1])||0))
      .forEach(([k,v])=>{
        v=Number(v)||0;
        cards.push(`<div class="mpFactor ${v>=0?'pos':'neg'}"><span class="label">${esc(labels[k])}</span><span class="value">${v>0?'+':''}${v.toFixed(1)}</span></div>`);
      });
  }
  if(pr.damp_pct){cards.push(`<div class="mpFactor damp"><span class="label">variance</span><span class="value">−${esc(pr.damp_pct)}%</span></div>`)}
  if(pr.mkt_pull){const v=Number(pr.mkt_pull)||0;cards.push(`<div class="mpFactor mkt"><span class="label">market pull</span><span class="value">${v>0?'+':''}${v}</span></div>`)}
  return cards.length?`<div class="mpFactors">${cards.join('')}</div>`:'';
}
/* dedup */
/* dedup */



/* ===== MATCH MODAL + FORECAST BOARD REDESIGN — v4 ===== */
function _v4PickSideLabel(m,side){
  if(side==='h')return m.home?.name||'Home';
  if(side==='a')return m.away?.name||'Away';
  if(side==='d')return 'Draw';
  return 'No pick';
}
function _v4SideCode(m,side){
  if(side==='h')return m.home?.code||'Home';
  if(side==='a')return m.away?.code||'Away';
  if(side==='d')return 'Draw';
  return '—';
}
function _v4ModelProbs(m){
  const pr=m.prediction||{};
  return pr.adjusted||pr.blend||pr.model||{};
}
function _v4MarketPct(m,side){
  const x=(m.markets||{})['1x2']||{};
  if(side==='h')return x.home_pct;
  if(side==='a')return x.away_pct;
  if(side==='d')return x.draw_pct;
  return null;
}
function _v4FactorRows(pr){
  const labels={class:'team class',pts:'points',gd:'goal diff',form:'form',adv:'home field',rest:'rest',elo:'elo rating',h2h:'head-to-head',injuries:'injuries'};
  const rows=[];
  if(pr&&pr.why){
    Object.entries(pr.why).filter(([k,v])=>labels[k]&&Math.abs(Number(v)||0)>=0.3)
      .sort((a,b)=>Math.abs(Number(b[1])||0)-Math.abs(Number(a[1])||0))
      .forEach(([k,v])=>{v=Number(v)||0;rows.push(`<div class="factorRow ${v>0?'pos':v<0?'neg':'neu'}"><span class="fName">${esc(labels[k])}</span><span class="fVal">${v>0?'+':''}${v.toFixed(1)}</span></div>`)});
  }
  if(pr&&Number(pr.damp_pct))rows.push(`<div class="factorRow neu"><span class="fName">variance control</span><span class="fVal">−${esc(pr.damp_pct)}%</span></div>`);
  if(pr&&Number(pr.mkt_pull))rows.push(`<div class="factorRow neu"><span class="fName">consensus pull</span><span class="fVal">${Number(pr.mkt_pull)>0?'+':''}${esc(pr.mkt_pull)}</span></div>`);
  return rows.length?rows.join(''):'<div class="factorRow neu"><span class="fName">No factor detail</span><span class="fVal">—</span></div>';
}
function _v4ProbabilityLines(m){
  const p=_v4ModelProbs(m);
  const rows=[['h',m.home?.code||m.home?.name||'Home','h'],['d','Draw','d'],['a',m.away?.code||m.away?.name||'Away','a']];
  return rows.map(([side,label,cls])=>{const v=Math.max(0,Math.min(100,Math.round(Number(p[side])||0)));return `<div class="probLine"><span class="sideName">${esc(label)}</span><span class="probTrack"><i class="probFill ${cls}" style="width:${Math.max(3,v)}%"></i></span><span class="pct">${v}%</span></div>`}).join('');
}
/* dedup */
function matchStory(m){const pr=m.prediction;if(!pr)return '';
  const up=pr.upset||{};const conf=pr.confidence;
  const pickName=esc(pr.pick_name||'');
  // lead sentence
  let lead;
  const cls=up.upset_class||'unknown';
  const radar=up.radar;const edge=up.upset_edge;
  const magnitude={major:'a heavy underdog',solid:'a real underdog',minor:'a live underdog'}[cls]||'the underdog';
  if(up.triggered&&up.candidate_name){
    lead=`<b>${esc(up.candidate_name)}</b> is the upset call — ${magnitude} the model rates high enough to back outright.`;
  }else if(radar&&up.candidate_name){
    lead=`<b>${pickName}</b> is the official pick${conf?` at ${conf}%`:''}, but <b>${esc(up.candidate_name)}</b> is on the upset radar — ${magnitude} the model prices ${edge>0?`${edge} points above`:'above'} the market.${up.market_gate===false?' The gap is too wide to make it the pick, but it is live.':''}`;
  }else if(cls==='pickem'){
    lead=`<b>${pickName}</b> is the lean in what is essentially a coin-flip — the market can barely separate these two.`;
  }else{
    lead=`<b>${pickName}</b> is the model's pick${conf?` at ${conf}%`:''}${conf&&conf>=60?' — a confident, clean call with no live upset threat':''}. ${esc(pr.note||'')}.`;
  }
  // why bullets from factor attribution (top 3 by magnitude)
  const L={pts:'points on the table',gd:'tournament goal difference',form:'recent form',adv:'home-listing edge',class:'squad class and ranking',rest:'rest advantage'};
  const why=pr.why||{};
  const bullets=Object.entries(why).filter(([k,v])=>Math.abs(v)>=0.4&&L[k]).sort((a,b)=>Math.abs(b[1])-Math.abs(a[1])).slice(0,3)
    .map(([k,v])=>{const who=v>0?esc(m.home.name):esc(m.away.name);return `<li>${who} leads on ${L[k]}</li>`;});
  if(pr.damp_pct>=10)bullets.push(`<li>Knockout/conditions variance is damping confidence by ${pr.damp_pct}%</li>`);
  if(up.triggered)bullets.push(`<li>Upset gate: OPEN — backing ${esc(up.candidate_name)} as the pick</li>`);
  else if(up.radar&&up.market_gate===false)bullets.push(`<li>Upset radar: ${esc(up.candidate_name)} is underpriced by the market but the gap is too wide to back outright</li>`);
  else if(up.radar)bullets.push(`<li>Upset radar: model rates ${esc(up.candidate_name)} ${up.upset_edge>0?'+'+up.upset_edge:up.upset_edge} vs the market</li>`);
  const tot=(m.prediction||{}).totals||null;
  let goals='';
  if(m.markets&&m.markets.totals){
    const mktLean=m.markets.totals.over_pct>=m.markets.totals.under_pct?'over':'under';
    const extra=(tot&&tot.pick)?(tot.pick===mktLean?` · model agrees (${tot.expected} expected)`:` · model leans ${tot.pick} instead (${tot.expected} expected)`):'';
    goals=`<li>Market leans ${mktLean} ${esc(m.markets.totals.line)} goals${extra}</li>`;
  } else if(tot&&tot.expected!=null){
    goals=`<li>Model expects ${tot.expected} goals — no market line yet</li>`;
  }
  return `<div class="storyCard"><div class="storyTag">Match Story</div><p class="storyLead">${lead}</p>${(bullets.length||goals)?`<ul class="storyWhy">${bullets.join('')}${goals}</ul>`:''}</div>`;}
function details(m){
  return `<div class="detailGrid v4Detail">${matchStory(m)}<div class="detailTop"><div class="readCard modelReadCard">${modelBlock(m)}</div><div class="readCard forecastMarketCard">${marketPanel(m)}</div></div><div class="detailLow">${statsPanel(m)}${lineupsPanel(m)}</div></div>`;
}
function _v4OutcomePct(m,side){
  const x=(m.markets||{})['1x2']||{},p=_v4ModelProbs(m);
  if(side==='h')return Number(x.home_pct??p.h??0);
  if(side==='d')return Number(x.draw_pct??p.d??0);
  if(side==='a')return Number(x.away_pct??p.a??0);
  return 0;
}
/* dedup */
function _v4TitleRows(t){
  if(!t.length)return '<div class="emptyForecast">No title-race snapshot yet.</div>';
  const max=Number(t[0].pct)||1;
  return t.slice(0,12).map((x,i)=>`<div class="raceRow"><span class="raceRank">${i+1}</span><div><div class="raceTeam">${uiFlag(x.code)?`<span class="flagIcon">${uiFlag(x.code)}</span>`:''}${esc(x.team)}</div><div class="raceMeta">title probability snapshot</div></div><span class="raceBar"><i style="width:${Math.max(4,Math.round((Number(x.pct)||0)/max*100))}%"></i></span><span class="racePct">${esc(x.pct??'—')}%</span></div>`).join('');
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
  return M.map(m=>{const pr=m.prediction||{},x=(m.markets||{})['1x2']||{};const probs=_v4ModelProbs(m);const hp=Math.round(Number(probs.h??x.home_pct??0)),dp=Math.round(Number(probs.d??x.draw_pct??0)),ap=Math.round(Number(probs.a??x.away_pct??0));return `<div class="matchSnapRow" onclick="openMatchModal('${esc(String(m.id||''))}')"><div><div class="matchSnapTeams">${esc(m.home?.code||m.home?.name||'H')} v ${esc(m.away?.code||m.away?.name||'A')}</div><div class="matchSnapMeta">${esc(m.stage||'')} · ${kickIn(m.kickoff)}</div></div><div class="probLines"><div class="probLine"><span class="sideName">${esc(m.home?.code||'H')}</span><span class="probTrack"><i class="probFill h" style="width:${Math.max(3,hp)}%"></i></span><span class="pct">${hp}%</span></div><div class="probLine"><span class="sideName">Draw</span><span class="probTrack"><i class="probFill d" style="width:${Math.max(3,dp)}%"></i></span><span class="pct">${dp}%</span></div><div class="probLine"><span class="sideName">${esc(m.away?.code||'A')}</span><span class="probTrack"><i class="probFill a" style="width:${Math.max(3,ap)}%"></i></span><span class="pct">${ap}%</span></div></div></div>`}).join('');
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
  let html=`<div class="forecastShell"><div class="forecastHero"><div><h2>Forecast board</h2><p>A cleaner view for tournament probabilities, upset risk, advancement paths, and scorer races. It avoids cramped rows and keeps the board focused on sports analytics rather than betting prompts.</p></div><div class="forecastKpis"><div class="forecastKpi"><span>Upcoming</span><b>${upcoming}</b></div><div class="forecastKpi"><span>Upset watch</span><b>${upsets.filter(x=>x.risk>=50).length}</b></div><div class="forecastKpi"><span>Title teams</span><b>${t.length||'—'}</b></div></div></div>`;
  const leaderPanel=_v13LeaderPanel(sc);
  html+=`<div class="forecastGrid ${leaderPanel?'':'single'}"><section class="forecastPanel"><div class="forecastPanelHead"><h3>Upset radar</h3><span>${upsets.length} matches</span></div><div class="upsetList">${upsets.length?upsets.map(x=>`<div class="upsetRow" onclick="openMatchModal('${esc(String(x.m.id||''))}')"><div><div class="upsetMatch">${esc(x.m.home?.code||x.m.home?.name||'H')} v ${esc(x.m.away?.code||x.m.away?.name||'A')}</div><div class="upsetWhy">${esc(x.reason)}</div></div><div class="upsetWhy">${esc(x.m.stage||'')} · ${kickIn(x.m.kickoff)}</div><span class="riskPill ${x.cls}">${x.triggered?'active upset pick':x.risk>=70?'high variance':x.risk>=50?'medium variance':'low variance'}</span></div>`).join(''):'<div class="emptyForecast">No upcoming matches to analyze.</div>'}</div></section>${leaderPanel}</div>`;
  html+=`<div class="forecastGrid"><section class="forecastPanel"><div class="forecastPanelHead"><h3>Title race</h3><span>probability snapshot</span></div><div class="raceList">${_v4TitleRows(t)}</div></section><section class="forecastPanel"><div class="forecastPanelHead"><h3>Match snapshots</h3><span>next fixtures</span></div><div class="matchSnapList">${_v4MatchSnapshots()}</div></section></div>`;
  html+=_v4AdvancementTable(adv);
  html+=`<div class="forecastNote">Analytics only. Use the model as a probability read: a 38% pick should still lose often. The app should surface uncertainty instead of hiding it.</div></div>`;
  host=$('#view-title');host.innerHTML=html;
}



/* ===== IN-FOCUS PANEL RESTORE — v5 =====
   Keep the expanded match window using the new v4 analyst card,
   but restore the right-side In Focus panel to the original compact read.
   This prevents the large expanded-window model layout from breaking the sidebar. */
/* dedup */
