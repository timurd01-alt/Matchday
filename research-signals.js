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
  const cfbGroups=[
    ['Offense',[
      ['ppa','Predicted Points Added','Quality created per play','number',true],
      ['success_rate','Success rate','Plays that keep the offense on schedule','percent',true],
      ['explosiveness','Explosiveness','Impact generated on successful plays','number',true],
      ['line_yards','Line yards','Rushing push credited to the offensive line','number',true],
      ['power_success','Power success','Short-yardage runs converted','percent',true],
      ['stuff_rate','Stuff rate','Runs stopped at or behind the line','percent',false]
    ]],
    ['Defense',[
      ['def_ppa_allowed','PPA allowed','Opponent quality allowed per play','number',false],
      ['def_success_rate_allowed','Success allowed','Opponent plays kept on schedule','percent',false],
      ['def_explosiveness_allowed','Explosiveness allowed','Impact conceded on successful plays','number',false]
    ]]
  ];
  function cfbSeasonLabel(meta){
    const coverage=meta?.coverage||{},season=coverage.season,role=String(coverage.season_role||'').replace(/_/g,' ');
    if(!season)return 'Completed-season team profile';
    return `${season} ${role==='prior completed'?'completed-season':role||'season'} profile`;
  }
  function cfbMetricRow(metric,home,away){
    const [key,label,help,type,higher]=metric,hv=finite(home[key]),av=finite(away[key]);
    if(hv==null&&av==null)return '';
    const leader=hv==null||av==null||hv===av?'':((higher?hv>av:hv<av)?'home':'away');
    const direction=higher?'Higher is stronger':'Lower is stronger';
    return `<div class="cfbMetric" role="row"><div class="cfbMetricLabel" role="rowheader"><b>${esc(label)}</b><span>${esc(help)} · ${esc(direction)}</span></div><div class="cfbMetricValue ${leader==='home'?'stronger':''}" role="cell">${esc(format(hv,type))}${leader==='home'?'<small>Stronger</small>':''}</div><div class="cfbMetricValue ${leader==='away'?'stronger':''}" role="cell">${esc(format(av,type))}${leader==='away'?'<small>Stronger</small>':''}</div></div>`;
  }
  function cfbSignalsPanel(m,meta){
    const profiles=m?.advanced_metrics||{},home=profiles.home||{},away=profiles.away||{};
    const homeName=m?.home?.code||m?.home?.name||'Home',awayName=m?.away?.code||m?.away?.name||'Away';
    const groups=cfbGroups.map(([title,items])=>{
      const rows=items.map(metric=>cfbMetricRow(metric,home,away)).filter(Boolean);
      if(!rows.length)return '';
      const visible=rows.slice(0,3).join(''),extra=rows.slice(3).join('');
      return `<div class="cfbMetricGroup"><h4>${esc(title)}</h4><div class="cfbMetricRows" role="table" aria-label="${esc(title)} advanced profile"><div class="cfbTeamHead" role="row"><span role="columnheader">Metric</span><b role="columnheader">${esc(homeName)}</b><b role="columnheader">${esc(awayName)}</b></div>${visible}${extra?`<details class="cfbMore"><summary>Show ${rows.length-3} more ${esc(title.toLowerCase())} metric${rows.length-3===1?'':'s'}</summary>${extra}</details>`:''}</div></div>`;
    }).join('');
    const missing=[];if(!profiles.home)missing.push(homeName);if(!profiles.away)missing.push(awayName);
    const missingNote=missing.length?`<p class="cfbMissing">Profile unavailable for ${esc(missing.join(' and '))}. Available data is shown without inventing a replacement.</p>`:'';
    return `<section class="analystPanel researchPanel cfbResearch" aria-labelledby="cfbResearchTitle"><div class="cfbResearchTop"><div><span class="cfbEyebrow">Team profile</span><h3 id="cfbResearchTitle">Advanced CFB profile</h3><p>${esc(cfbSeasonLabel(meta))}</p></div></div><p class="cfbIntro">A side-by-side profile of how each team played, from the same opponent-adjusted work the ratings are solved from.</p>${groups||'<p class="cfbMissing">No matchup-linked advanced metrics are available for either team.</p>'}${missingNote}<div class="cfbReceipt"><span>${esc(meta?.source||'Approved research source')}</span><span>${esc(meta?.generated_at?`Built ${String(meta.generated_at).slice(0,10)}`:'Build date unavailable')}</span></div></section>`;
  }
  function shadowBlock(m){
    const nfl=m?.nfl_challenger_shadow,mlb=m?.mlb_challenger_shadow,shadow=nfl||mlb;if(!shadow)return '';
    const official=finite(m?.prediction?.adjusted?.h??m?.prediction?.regulation_probs?.h??m?.prediction?.model?.h);
    const learned=finite(shadow.home_win_probability);
    if(mlb){const audit=DATA?.research_scorecards?.mlb,evidence=audit?`<div><span>Prospective evidence</span><b>${esc(`${audit.eligible_games}/${audit.required_games} games · ${audit.game_date_blocks}/${audit.required_game_date_blocks} dates`)}</b></div>`:'';return `<div class="researchShadow"><div><span>Official home probability</span><b>${official==null?'—':esc(`${official.toFixed(1)}%`)}</b></div><div><span>Run-strength shadow</span><b>${learned==null?'—':esc(`${(learned*100).toFixed(1)}%`)}</b></div>${evidence}</div><p class="researchCaution">The lean MLB model cleared historical out-of-sample testing and is now collecting prospective evidence with zero probability weight. Starting pitchers, confirmed lineups, and bullpen availability remain missing.</p><p class="researchCaution">${esc(shadow.retrosheet_notice||'Historical training data: Retrosheet.')}</p>`;}
    const calibrated=finite(shadow.calibrated_elo_home_probability),audit=DATA?.research_scorecards?.nfl;
    const evidence=audit?`<div><span>Prospective evidence</span><b>${esc(`${audit.eligible_games}/${audit.required_games} games · ${audit.kickoff_week_blocks}/${audit.required_kickoff_week_blocks} weeks`)}</b></div>`:'';
    const promotion=m?.prediction?.research_promotion,move=finite(promotion?.applied_shift_points),pilot=promotion?.promotion_basis==='historical_oos_pilot';
    const applied=pilot?`<div><span>Capped adjustment</span><b>${move==null?'—':esc(`${move>0?'+':''}${move.toFixed(1)} pts · 10% weight`)}</b></div>`:'';
    return `<div class="researchShadow"><div><span>Official home probability</span><b>${official==null?'—':esc(`${official.toFixed(1)}%`)}</b></div><div><span>Calibrated Elo shadow</span><b>${calibrated==null?'—':esc(`${(calibrated*100).toFixed(1)}%`)}</b></div><div><span>Learned shadow</span><b>${learned==null?'—':esc(`${(learned*100).toFixed(1)}%`)}</b></div>${applied}${evidence}</div><p class="researchCaution">Calibrated Elo beat raw Elo in historical out-of-sample testing. Its historical pilot is capped at 10% weight and three probability points with no pick flip; prospective evidence will determine whether it stays. The failed learned NFL residual remains audit-only.</p>`;
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
      // The match's own competition, not the board's. On the merged "All
      // sports" board DATA.comp_key is 'ALL', so every one of these sports
      // failed the test and the panel vanished silently -- the same board
      // where needsDetailHydration() has already read m._comp to decide the
      // fixture was worth hydrating for this very panel.
      const comp=String(m?._comp||DATA?.comp_key||'').toUpperCase();
      if(!['NFL','NCAAF','NBA','NCAAM','MLB'].includes(comp))return '';
      return `<section class="analystPanel researchPanel unavailable"><div class="researchHead"><div><span>Research signals</span><b>Authorized profile unavailable</b></div><em>official model unchanged</em></div><p class="researchCaution">This build has no fresh, matchup-linked advanced profile from an approved source. Matchday leaves the signal missing instead of inventing a neutral value.</p></section>`;
    }
    if(String(m?._comp||DATA?.comp_key||'').toUpperCase()==='NCAAF'&&meta)return cfbSignalsPanel(m,meta);
    const applied=finite(m?.prediction?.research_promotion?.production_weight),weight=applied&&applied>0?`production weight ${(applied*100).toFixed(0)}%`:'production weight 0';
    const historicalPilot=m?.prediction?.research_promotion?.promotion_basis==='historical_oos_pilot';
    const caution=historicalPilot?'A historical out-of-sample gate authorized this small capped pilot. The immutable raw shadow and prospective counter remain separate for auditing.':applied&&applied>0?'A manually reviewed prospective gate authorized this capped blend. The immutable raw shadow remains separate for auditing.':'These fields expand the reasoning record. They do not change the official probability until a frozen out-of-sample and prospective promotion gate passes.';
    return `<section class="analystPanel researchPanel"><div class="researchHead"><div><span>Research signals</span><b>${esc(meta?.source||(m?.mlb_challenger_shadow?'MLB run-strength prospective shadow':'NFL challenger shadow'))}</b></div><em>${esc(weight)}</em></div>${metrics?`<div class="researchTeams"><b>${esc(m?.home?.code||m?.home?.name||'Home')}</b><span>authorized derived profile</span><b>${esc(m?.away?.code||m?.away?.name||'Away')}</b></div><div class="researchMetrics">${metrics}</div>`:''}${shadow}<div class="researchReceipt"><span>${esc(coverageText(meta)||'point-in-time shadow receipt')}</span><span>${esc(meta?.license||'research artifact')}</span></div><p class="researchCaution">${esc(caution)}</p></section>`;
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
