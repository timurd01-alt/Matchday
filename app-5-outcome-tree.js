// Outcome Tree: exact published outcomes combined under an explicit
// independence assumption. Keep the math helpers side-effect free so the
// calculation can be regression-tested without a browser.
var OUTCOME_TREE_SELECTED=new Map();
var OUTCOME_TREE_SEARCH='';
var OUTCOME_TREE_NOTICE='';
var OUTCOME_TREE_MAX_LEGS=8;

function outcomeTreeJointProbability(percentages){
  if(!Array.isArray(percentages)||!percentages.length)return 1;
  return percentages.reduce((joint,value)=>{
    const pct=Math.max(0,Math.min(100,Number(value)||0));
    return joint*(pct/100);
  },1);
}

function outcomeTreeFairOdds(probability){
  const p=Number(probability);
  if(!(p>0&&p<=1))return {decimal:null,american:null};
  const decimal=1/p;
  if(decimal===1)return {decimal,american:null};
  const american=Math.round(decimal>=2?(decimal-1)*100:-100/(decimal-1));
  return {decimal,american};
}

function outcomeTreeMatchKey(match){
  return `${match?._comp||DATA?.comp_key||currentSportKey()||'all'}|${match?.id||''}`;
}

function outcomeTreeMatches(){
  return (DATA?.matches||[])
    .filter(match=>isVisibleUpcoming(match)&&outcomeTreeOptions(match).length>=2)
    .sort((a,b)=>String(a.kickoff||'').localeCompare(String(b.kickoff||'')));
}

function outcomeTreeProbability(match,side){
  const value=Number(officialPredictionProbabilities(match)?.[side]);
  return Number.isFinite(value)?Math.max(0,Math.min(100,value)):null;
}

function outcomeTreeOptions(match){
  const options=[{side:'h',name:`${match?.home?.name||'Home'} wins`,team:match?.home?.name||'Home'}];
  if((outcomeTreeProbability(match,'d')||0)>0)options.push({side:'d',name:'Draw',team:null});
  options.push({side:'a',name:`${match?.away?.name||'Away'} wins`,team:match?.away?.name||'Away'});
  return options.filter(option=>outcomeTreeProbability(match,option.side)!=null);
}

function outcomeTreeSelectedLeg(match,side){
  const option=outcomeTreeOptions(match).find(item=>item.side===side);
  if(!option)return null;
  const probability=outcomeTreeProbability(match,side);
  if(probability==null)return null;
  return {
    key:outcomeTreeMatchKey(match),side,probability,
    outcome:option.name,team:option.team,
    home:match?.home?.name||'Home',away:match?.away?.name||'Away',
    kickoff:match?.kickoff||'',stage:match?.stage||'',
    competition:match?._competition||match?._comp||DATA?.competition||'',
    source:Object.keys(lockedPredictionSnapshot(match)||{}).length?'locked public snapshot':'current published model'
  };
}

function outcomeTreeToggle(key,side){
  const match=outcomeTreeMatches().find(item=>outcomeTreeMatchKey(item)===key);
  if(!match)return;
  const existing=OUTCOME_TREE_SELECTED.get(key);
  if(existing?.side===side){
    OUTCOME_TREE_SELECTED.delete(key);
    OUTCOME_TREE_NOTICE='';
  }else{
    if(!existing&&OUTCOME_TREE_SELECTED.size>=OUTCOME_TREE_MAX_LEGS){
      OUTCOME_TREE_NOTICE=`Choose up to ${OUTCOME_TREE_MAX_LEGS} events so every branch stays readable.`;
      renderOutcomeTree();return;
    }
    const leg=outcomeTreeSelectedLeg(match,side);
    if(!leg)return;
    OUTCOME_TREE_SELECTED.set(key,leg);
    OUTCOME_TREE_NOTICE=existing?'Outcome replaced for this game. Only one exact result can occur.':'';
  }
  renderOutcomeTree();
}

function outcomeTreeReset(render=true){
  OUTCOME_TREE_SELECTED.clear();OUTCOME_TREE_SEARCH='';OUTCOME_TREE_NOTICE='';
  if(render&&typeof renderOutcomeTree==='function')renderOutcomeTree();
}

function outcomeTreeLegs(){
  return [...OUTCOME_TREE_SELECTED.values()].sort((a,b)=>String(a.kickoff).localeCompare(String(b.kickoff)));
}

function outcomeTreeBuild(legs){
  let cumulative=1;
  return (legs||[]).map((leg,index)=>{
    cumulative*=Math.max(0,Math.min(100,Number(leg.probability)||0))/100;
    return {...leg,index:index+1,cumulative};
  });
}

function outcomeTreeSharedTeams(legs){
  const seen=new Map(),shared=new Set();
  (legs||[]).forEach(leg=>[leg.home,leg.away].filter(Boolean).forEach(team=>{
    const key=String(team).toLowerCase().trim();
    if(seen.has(key))shared.add(team);else seen.set(key,team);
  }));
  return [...shared];
}

function outcomeTreePercent(probability){
  const pct=Number(probability)*100;
  if(pct>=10)return `${pct.toFixed(2).replace(/\.00$/,'')}%`;
  if(pct>=1)return `${pct.toFixed(2)}%`;
  if(pct>=.01)return `${pct.toFixed(3)}%`;
  return `${pct.toPrecision(2)}%`;
}

function outcomeTreeAmerican(value){
  if(value==null)return '—';
  return `${value>0?'+':''}${value}`;
}

function outcomeTreeSearch(value){
  OUTCOME_TREE_SEARCH=String(value||'').toLowerCase().trim();
  const host=document.getElementById('view-tree');if(!host)return;
  let visible=0;
  host.querySelectorAll('.outcomeMatch').forEach(row=>{
    const show=!OUTCOME_TREE_SEARCH||String(row.dataset.search||'').includes(OUTCOME_TREE_SEARCH);
    row.hidden=!show;if(show)visible++;
  });
  const count=host.querySelector('[data-tree-count]');
  if(count)count.textContent=`${visible} game${visible===1?'':'s'}`;
  const empty=host.querySelector('[data-tree-empty]');
  if(empty)empty.hidden=visible!==0;
}

function outcomeTreeMatchRow(match){
  const key=outcomeTreeMatchKey(match),selected=OUTCOME_TREE_SELECTED.get(key);
  const competition=match?._competition||match?._comp||DATA?.competition||'';
  const search=[match?.home?.name,match?.away?.name,match?.stage,competition].join(' ').toLowerCase();
  const buttons=outcomeTreeOptions(match).map(option=>{
    const probability=outcomeTreeProbability(match,option.side),active=selected?.side===option.side;
    return `<button type="button" class="outcomeChoice ${active?'selected':''}" data-tree-key="${esc(key)}" data-tree-side="${option.side}" aria-pressed="${active}"><span>${esc(option.name)}</span><b>${probability}%</b></button>`;
  }).join('');
  return `<article class="outcomeMatch" data-search="${esc(search)}"><div class="outcomeMatchTop"><div><b>${esc(match?.home?.name)} <span>vs</span> ${esc(match?.away?.name)}</b><small>${esc(competition)}${match?.stage?` · ${esc(match.stage)}`:''}</small></div><time>${match?.kickoff?esc(dt(match.kickoff)):'TBD'}</time></div><div class="outcomeChoices">${buttons}</div></article>`;
}

function outcomeTreeSummary(legs){
  if(!legs.length)return `<aside class="outcomeSummary"><div class="outcomeEmptyState"><div class="outcomeEmptyIcon">01</div><h3>Start a scenario</h3><p>Choose an exact result from two or more games. The tree will multiply the model probabilities and show where the path can branch.</p></div><div class="outcomeQuality"><b>What carries into this estimate</b><span>The tree does not improve the game predictions. Missing talent, pitcher, injury, lineup, or market inputs remain missing here too.</span></div></aside>`;
  const joint=outcomeTreeJointProbability(legs.map(leg=>leg.probability)),odds=outcomeTreeFairOdds(joint);
  const branches=outcomeTreeBuild(legs),shared=outcomeTreeSharedTeams(legs);
  return `<aside class="outcomeSummary"><div class="outcomeSummaryHead"><div><span>Selected path</span><b>${legs.length}/${OUTCOME_TREE_MAX_LEGS} events</b></div><button type="button" class="miniBtn" data-tree-reset>Reset</button></div>
    <div class="outcomeTotals"><div class="outcomeMainTotal"><span>Combined model probability</span><b>${outcomeTreePercent(joint)}</b></div><div><span>Fair decimal</span><b>${odds.decimal?odds.decimal.toFixed(2):'—'}</b></div><div><span>Fair American</span><b>${outcomeTreeAmerican(odds.american)}</b></div></div>
    ${OUTCOME_TREE_NOTICE?`<div class="outcomeNotice">${esc(OUTCOME_TREE_NOTICE)}</div>`:''}
    ${shared.length?`<div class="outcomeWarning"><b>Correlation warning</b><span>${esc(shared.join(', '))} appears in more than one selected game. Those events may not be independent, so the combined estimate can be too high or too low.</span></div>`:''}
    <div class="outcomeBranches">${branches.map(branch=>`<div class="outcomeBranch"><div class="outcomeBranchRail"><i>${branch.index}</i><span></span></div><div class="outcomeBranchCard"><small>${esc(branch.home)} vs ${esc(branch.away)}</small><div><b>${esc(branch.outcome)}</b><strong>${branch.probability}%</strong></div><p>${esc(branch.source)} · path now ${outcomeTreePercent(branch.cumulative)}</p><div class="outcomeExit"><span>Any other result</span><b>${100-branch.probability}%</b></div></div></div>`).join('')}</div>
    <div class="outcomeDisclosure"><b>Independence assumption</b><span>This multiplies published probabilities as if different games do not affect one another. Fair odds are model-implied, not a sportsbook price or betting recommendation.</span></div></aside>`;
}

function renderOutcomeTree(){
  const host=document.getElementById('view-tree');if(!host)return;
  const matches=outcomeTreeMatches(),legs=outcomeTreeLegs();
  host.innerHTML=`<div class="outcomeHero"><div><span class="outcomeEyebrow">Scenario analysis</span><h2>Combine exact model outcomes.</h2><p>Choose results such as Michigan State wins and Alabama loses. Each branch uses the official published probability, with locked snapshots taking priority.</p></div><div class="outcomeFormula"><span>JOINT PATH</span><b>p<sub>1</sub> × p<sub>2</sub> × … × p<sub>n</sub></b><small>assumes games are independent</small></div></div>
    <div class="outcomeShell"><section class="outcomePicker"><div class="outcomePickerHead"><div><h3>Upcoming outcomes</h3><span data-tree-count>${matches.length} game${matches.length===1?'':'s'}</span></div><label class="outcomeSearch"><svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="m16 16 5 5"/></svg><input type="search" value="${esc(OUTCOME_TREE_SEARCH)}" placeholder="Search team or competition" aria-label="Search upcoming outcomes"></label></div><div class="outcomeMatchList">${matches.map(outcomeTreeMatchRow).join('')}<div class="outcomeNoResults" data-tree-empty hidden>No upcoming games match that search.</div></div></section>${outcomeTreeSummary(legs)}</div>
    <div class="outcomeBottomNote"><b>Read this as a scenario, not a promise.</b> A 12% path means the model expects that exact combination roughly 12 times in 100 comparable sets only if the input probabilities are calibrated and the events are independent.</div>`;
  host.onclick=event=>{
    const reset=event.target.closest('[data-tree-reset]');if(reset){outcomeTreeReset();return;}
    const button=event.target.closest('[data-tree-key]');if(button)outcomeTreeToggle(button.dataset.treeKey,button.dataset.treeSide);
  };
  const search=host.querySelector('.outcomeSearch input');if(search)search.oninput=event=>outcomeTreeSearch(event.target.value);
  if(OUTCOME_TREE_SEARCH)outcomeTreeSearch(OUTCOME_TREE_SEARCH);
}
