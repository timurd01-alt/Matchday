/* Authorized research evidence for the expanded match view. Never changes the official pick. */
(function(){
  const definitions=[
    ['epa_per_play','EPA / play','number',true],
    ['success_rate','Success rate','percent',true],
    ['cpoe','CPOE','points',true],
    ['explosive_play_rate','Explosive play rate','percent',true],
    ['def_epa_allowed_per_play','Def. EPA allowed','number',false],
    ['def_success_rate_allowed','Def. success allowed','percent',false],
    ['epa_per_drive','EPA / drive','number',true],
    ['drive_score_rate','Drive score rate','percent',true],
    ['ppa','PPA','number',true],
    ['success_rate','Success rate','percent',true],
    ['explosiveness','Explosiveness','number',true],
    ['def_ppa_allowed','Def. PPA allowed','number',false],
    ['def_success_rate_allowed','Def. success allowed','percent',false],
    ['line_yards','Line yards','number',true],
    ['adjusted_net_rating','Adjusted net rating','number',true],
    ['efg','Effective FG%','percent',true],
    ['tov_rate','Turnover rate','percent',false],
    ['orb_rate','Offensive rebound rate','percent',true],
    ['ft_rate','Free-throw rate','percent',true],
    ['tempo','Tempo','number',null]
  ];
  function finite(value){const number=Number(value);return Number.isFinite(number)?number:null}
  function format(value,type){
    const number=finite(value);if(number==null)return '—';
    if(type==='percent')return `${(number*100).toFixed(1)}%`;
    if(type==='points')return `${number>0?'+':''}${number.toFixed(1)}`;
    return `${number>0?'+':''}${number.toFixed(3).replace(/0+$/,'').replace(/\.$/,'')}`;
  }
  function metricRows(m){
    const profiles=m?.advanced_metrics||{},home=profiles.home||{},away=profiles.away||{};
    const seen=new Set(),rows=[];
    for(const [key,label,type,higher] of definitions){
      if(seen.has(key)||finite(home[key])==null||finite(away[key])==null)continue;
      seen.add(key);const hv=finite(home[key]),av=finite(away[key]);
      const leader=higher==null||hv===av?'':((higher?hv>av:hv<av)?'home':'away');
      rows.push(`<div class="researchMetric ${leader}"><span>${esc(label)}</span><b>${esc(format(hv,type))}</b><i>${esc(format(av,type))}</i></div>`);
      if(rows.length>=7)break;
    }
    return rows.join('');
  }
  function shadowBlock(m){
    const nfl=m?.nfl_challenger_shadow,mlb=m?.mlb_challenger_shadow,shadow=nfl||mlb;if(!shadow)return '';
    const official=finite(m?.prediction?.adjusted?.h??m?.prediction?.regulation_probs?.h??m?.prediction?.model?.h);
    const learned=finite(shadow.home_win_probability);
    if(mlb)return `<div class="researchShadow"><div><span>Official home probability</span><b>${official==null?'—':esc(`${official.toFixed(1)}%`)}</b></div><div><span>Run-strength shadow</span><b>${learned==null?'—':esc(`${(learned*100).toFixed(1)}%`)}</b></div></div><p class="researchCaution">The lean MLB model cleared historical out-of-sample testing and is now collecting prospective evidence with zero probability weight. Starting pitchers, confirmed lineups, and bullpen availability remain missing.</p><p class="researchCaution">${esc(shadow.retrosheet_notice||'Historical training data: Retrosheet.')}</p>`;
    const calibrated=finite(shadow.calibrated_elo_home_probability);
    return `<div class="researchShadow"><div><span>Official home probability</span><b>${official==null?'—':esc(`${official.toFixed(1)}%`)}</b></div><div><span>Calibrated Elo shadow</span><b>${calibrated==null?'—':esc(`${(calibrated*100).toFixed(1)}%`)}</b></div><div><span>Learned shadow</span><b>${learned==null?'—':esc(`${(learned*100).toFixed(1)}%`)}</b></div></div><p class="researchCaution">The learned NFL challenger failed its promotion gate and has zero probability weight. It is shown as audit evidence, not a second official pick.</p>`;
  }
  function coverageText(meta){
    const coverage=meta?.coverage||{},parts=[];
    if(coverage.season)parts.push(`season ${coverage.season}`);
    if(coverage.season_role)parts.push(String(coverage.season_role).replace(/_/g,' '));
    if(coverage.teams)parts.push(`${coverage.teams} teams`);
    if(meta?.generated_at)parts.push(`built ${String(meta.generated_at).slice(0,10)}`);
    return parts.join(' · ');
  }
  function researchSignalsPanel(m){
    const metrics=metricRows(m),shadow=shadowBlock(m),meta=m?.advanced_metrics_meta;
    if(!metrics&&!shadow){
      const comp=String(DATA?.comp_key||'').toUpperCase();
      if(!['NFL','NCAAF','NBA','NCAAM','MLB'].includes(comp))return '';
      return `<section class="analystPanel researchPanel unavailable"><div class="researchHead"><div><span>Research signals</span><b>Authorized profile unavailable</b></div><em>official model unchanged</em></div><p class="researchCaution">This build has no fresh, matchup-linked advanced profile from an approved source. Matchday leaves the signal missing instead of inventing a neutral value.</p></section>`;
    }
    return `<section class="analystPanel researchPanel"><div class="researchHead"><div><span>Research signals</span><b>${esc(meta?.source||(m?.mlb_challenger_shadow?'MLB run-strength prospective shadow':'NFL challenger shadow'))}</b></div><em>production weight 0</em></div>${metrics?`<div class="researchTeams"><b>${esc(m?.home?.code||m?.home?.name||'Home')}</b><span>authorized derived profile</span><b>${esc(m?.away?.code||m?.away?.name||'Away')}</b></div><div class="researchMetrics">${metrics}</div>`:''}${shadow}<div class="researchReceipt"><span>${esc(coverageText(meta)||'point-in-time shadow receipt')}</span><span>${esc(meta?.license||'research artifact')}</span></div><p class="researchCaution">These fields expand the reasoning record. They do not change the official probability until a frozen out-of-sample and prospective promotion gate passes.</p></section>`;
  }
  if(typeof details==='function'){
    const priorDetails=details;
    details=function(m){
      const html=String(priorDetails(m)||''),panel=researchSignalsPanel(m);
      if(!panel)return html;
      const end=html.lastIndexOf('</div>');
      return end<0?html+panel:html.slice(0,end)+panel+html.slice(end);
    };
  }
  window.researchSignalsPanel=researchSignalsPanel;
})();
