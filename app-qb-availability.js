// Official availability context is kept outside the frozen forecasting engine.
function qbReportName(name){
  const aliases={'Mississippi':'Ole Miss','North Carolina State':'NC State','Southern California':'USC','California-Los Angeles':'UCLA','Pittsburgh':'Pitt','Miami (FL)':'Miami'};
  return aliases[String(name||'')]||String(name||'');
}
function qbAvailabilityFor(m,now=Date.now()){
  if(String(m?._comp||DATA.comp_key||'').toLowerCase()!=='ncaaf')return null;
  const data=globalThis.MATCHDAY_QB_AVAILABILITY||{},kickoff=Date.parse(m.kickoff||'');
  if(!Number.isFinite(kickoff))return {state:'unknown',reason:'No verified kickoff time for report matching.'};
  const matches=(data.reports||[]).filter(r=>{
    const time=Date.parse(r.kickoff||''),published=Date.parse(r.published_at||'');
    if(!Number.isFinite(time)||Math.abs(time-kickoff)>6*3600e3||!Number.isFinite(published)||published>now)return false;
    const teams=r.teams||[];
    if(teams.length!==2)return false;
    const same=(a,b)=>bbNameMatches(qbReportName(a),qbReportName(b));
    return (same(teams[0].name,m.home?.name)&&same(teams[1].name,m.away?.name))
      ||(same(teams[1].name,m.home?.name)&&same(teams[0].name,m.away?.name));
  });
  if(!matches.length)return {state:'unknown',reason:'No official QB report collected for this matchup yet.'};
  // Competing fixture identities are ambiguous; a newer timestamp is not
  // permission to choose a different game or a different conference's report.
  const identities=new Set(matches.map(r=>r.conference+':'+r.report_id));
  if(identities.size!==1)return {state:'unknown',reason:'The available reports do not identify one unambiguous matchup.'};
  const report=matches.sort((a,b)=>Date.parse(b.published_at)-Date.parse(a.published_at))[0];
  const source=(data.sources||{})[report.conference]||{},checked=Date.parse(source.checked_at||'');
  const stale=source.state!=='ok'||!Number.isFinite(checked)||now-checked>4*3600e3;
  return {state:stale?'stale':'reported',report,source,historical:now>=kickoff};
}
function qbAvailabilityPanel(m){
  const result=qbAvailabilityFor(m);
  if(!result)return '';
  const links=Object.entries((globalThis.MATCHDAY_QB_AVAILABILITY||{}).sources||{}).map(([name,s])=>
    `<a href="${esc(s.source_url)}" target="_blank" rel="noopener noreferrer">${esc(name==='B10'?'Big Ten':name==='B12'?'Big 12':name)}</a>`).join(' · ');
  if(!result.report)return `<section class="qbAvailability" aria-label="Quarterback availability"><header><b>QB availability</b><span>Unknown</span></header><p>${esc(result.reason)} Missing reports do not mean every quarterback is available.</p>${links?`<div class="qbReportMeta">Official reports: ${links}</div>`:''}</section>`;
  const r=result.report;
  const teamHTML=(r.teams||[]).map(team=>{
    const qbs=team.quarterbacks||[],affected=qbs.filter(q=>q.status!=='Available');
    const summary=!qbs.length?'No QB status listed':affected.length
      ?[...new Set(affected.map(q=>q.status))].map(status=>`${affected.filter(q=>q.status===status).length} ${status.toLowerCase()}`).join(' · ')
      :`All ${qbs.length} reported QBs available`;
    return `<div class="qbReportTeam"><b>${esc(team.name)}</b><span class="${affected.length?'qbReportAlert':''}">${esc(summary)}</span>${qbs.length?`<details><summary>View ${qbs.length} reported quarterbacks</summary><ul>${qbs.map(q=>`<li><span>${esc(q.name)}</span><b>${esc(q.status)}</b></li>`).join('')}</ul></details>`:''}</div>`;
  }).join('');
  const when=new Date(r.published_at).toLocaleString(undefined,{month:'short',day:'numeric',hour:'numeric',minute:'2-digit',timeZoneName:'short'});
  const collected=new Date(r.first_observed_at).toLocaleString(undefined,{month:'short',day:'numeric',hour:'numeric',minute:'2-digit',timeZoneName:'short'});
  const label=result.state==='stale'?'Source update unavailable / stale':result.historical?'Historical report':'Official report';
  return `<section class="qbAvailability${result.state==='stale'?' qbReportStale':''}" aria-label="Quarterback availability"><header><b>QB availability</b><span>${esc(label)}</span></header><div class="qbReportTeams">${teamHTML}</div><div class="qbReportMeta"><a href="${esc(r.source_url)}" target="_blank" rel="noopener noreferrer">${esc(r.conference==='B10'?'Big Ten':r.conference==='B12'?'Big 12':r.conference)} · ${esc(r.report_type)}</a><span>Published ${esc(when)}</span><span>First collected ${esc(collected)}${r.observed_before_kickoff===false?' · after kickoff':''}</span></div><p class="qbReportNote">Reported QB group, not a confirmed starting lineup. These reports do not change the forecast.</p></section>`;
}
