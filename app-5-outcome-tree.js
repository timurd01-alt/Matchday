// Outcome Tree: exact published outcomes combined under an explicit
// independence assumption. Keep the math helpers side-effect free so the
// calculation can be regression-tested without a browser.
var OUTCOME_TREE_SELECTED=new Map();
var OUTCOME_TREE_NOTICE='';
var OUTCOME_TREE_DRAFT_MATCH='';
var OUTCOME_TREE_DRAFT_SIDE='';
var OUTCOME_TREE_MAX_LEGS=5;

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

function outcomeTreeAdd(key,side){
  const match=outcomeTreeMatches().find(item=>outcomeTreeMatchKey(item)===key);
  if(!match)return;
  if(OUTCOME_TREE_SELECTED.has(key)){
    OUTCOME_TREE_NOTICE='That game is already in the scenario. Remove it before choosing a different result.';
    renderOutcomeTree();return;
  }
  if(OUTCOME_TREE_SELECTED.size>=OUTCOME_TREE_MAX_LEGS){
    OUTCOME_TREE_NOTICE=`Choose up to ${OUTCOME_TREE_MAX_LEGS} events so every branch stays readable.`;
    renderOutcomeTree();return;
  }
  const leg=outcomeTreeSelectedLeg(match,side);
  if(!leg)return;
  OUTCOME_TREE_SELECTED.set(key,leg);
  OUTCOME_TREE_DRAFT_MATCH='';OUTCOME_TREE_DRAFT_SIDE='';OUTCOME_TREE_NOTICE='';
  renderOutcomeTree();
}

function outcomeTreeRemove(key){
  OUTCOME_TREE_SELECTED.delete(key);OUTCOME_TREE_NOTICE='';renderOutcomeTree();
}

function outcomeTreeDraftMatch(key){
  OUTCOME_TREE_DRAFT_MATCH=String(key||'');OUTCOME_TREE_DRAFT_SIDE='';OUTCOME_TREE_NOTICE='';renderOutcomeTree();
}

function outcomeTreeDraftSide(side){
  OUTCOME_TREE_DRAFT_SIDE=String(side||'');OUTCOME_TREE_NOTICE='';renderOutcomeTree();
}

function outcomeTreeAddDraft(){
  if(OUTCOME_TREE_DRAFT_MATCH&&OUTCOME_TREE_DRAFT_SIDE)outcomeTreeAdd(OUTCOME_TREE_DRAFT_MATCH,OUTCOME_TREE_DRAFT_SIDE);
}

function outcomeTreeReset(render=true){
  OUTCOME_TREE_SELECTED.clear();OUTCOME_TREE_DRAFT_MATCH='';OUTCOME_TREE_DRAFT_SIDE='';OUTCOME_TREE_NOTICE='';
  if(render&&typeof renderOutcomeTree==='function')renderOutcomeTree();
}

function outcomeTreeLegs(){
  const available=new Set(outcomeTreeMatches().map(outcomeTreeMatchKey));
  for(const key of OUTCOME_TREE_SELECTED.keys())if(!available.has(key))OUTCOME_TREE_SELECTED.delete(key);
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

function outcomeTreeMatchLabel(match){
  const competition=match?._competition||match?._comp||DATA?.competition||'';
  const matchup=`${match?.home?.name||'Home'} vs ${match?.away?.name||'Away'}`;
  const kickoff=match?.kickoff?dt(match.kickoff):'TBD';
  return [competition,matchup,kickoff].filter(Boolean).join(' · ');
}

function outcomeTreeSelectionRow(leg,index){
  return `<article class="outcomeSelection"><span class="outcomeSelectionIndex">${index+1}</span><div><b>${esc(leg.outcome)}</b><small>${esc(leg.home)} vs ${esc(leg.away)} · ${leg.probability}%</small></div><button type="button" class="miniBtn" data-tree-remove="${esc(leg.key)}" aria-label="Remove ${esc(leg.outcome)}">Remove</button></article>`;
}

function outcomeTreeCompactPicker(matches,legs){
  const selectedKeys=new Set(legs.map(leg=>leg.key));
  const available=matches.filter(match=>!selectedKeys.has(outcomeTreeMatchKey(match)));
  if(OUTCOME_TREE_DRAFT_MATCH&&!available.some(match=>outcomeTreeMatchKey(match)===OUTCOME_TREE_DRAFT_MATCH)){
    OUTCOME_TREE_DRAFT_MATCH='';OUTCOME_TREE_DRAFT_SIDE='';
  }
  const draftMatch=available.find(match=>outcomeTreeMatchKey(match)===OUTCOME_TREE_DRAFT_MATCH);
  const matchOptions=available.map(match=>{
    const key=outcomeTreeMatchKey(match);
    return `<option value="${esc(key)}" ${key===OUTCOME_TREE_DRAFT_MATCH?'selected':''}>${esc(outcomeTreeMatchLabel(match))}</option>`;
  }).join('');
  const outcomeOptions=(draftMatch?outcomeTreeOptions(draftMatch):[]).map(option=>{
    const probability=outcomeTreeProbability(draftMatch,option.side);
    return `<option value="${option.side}" ${option.side===OUTCOME_TREE_DRAFT_SIDE?'selected':''}>${esc(option.name)} · ${probability}%</option>`;
  }).join('');
  const full=legs.length>=OUTCOME_TREE_MAX_LEGS;
  const empty=legs.length?'':`<div class="outcomePickerEmpty"><b>No events selected yet.</b><span>Use the two menus below to build a scenario with up to ${OUTCOME_TREE_MAX_LEGS} exact outcomes.</span></div>`;
  const rows=legs.map(outcomeTreeSelectionRow).join('');
  return `<div class="outcomeSelections">${empty}${rows}</div><div class="outcomeAddForm"><label><span>1. Choose a game</span><select data-tree-draft-match ${full||!available.length?'disabled':''}><option value="">Select a matchup</option>${matchOptions}</select></label><label><span>2. Choose X</span><select data-tree-draft-side ${full||!draftMatch?'disabled':''}><option value="">Select the exact outcome</option>${outcomeOptions}</select></label><button type="button" class="actionbtn" data-tree-add ${full||!OUTCOME_TREE_DRAFT_MATCH||!OUTCOME_TREE_DRAFT_SIDE?'disabled':''}>Add event</button></div><p class="outcomePickerHint">${full?'Five-event limit reached. Remove an event to choose another.':`${available.length} matchup${available.length===1?'':'s'} available · one outcome per game`}</p>`;
}

function outcomeTreeSummary(legs){
  if(!legs.length)return `<aside class="outcomeSummary"><div class="outcomeEmptyState"><div class="outcomeEmptyIcon">X/Y</div><h3>Start a scenario</h3><p>Choose one to five exact outcomes from the compact selector. The tree uses X for each selected outcome and Y for every other result.</p></div><div class="outcomeQuality"><b>What carries into this estimate</b><span>The tree does not improve the game predictions. Missing talent, pitcher, injury, lineup, or market inputs remain missing here too.</span></div></aside>`;
  const joint=outcomeTreeJointProbability(legs.map(leg=>leg.probability)),odds=outcomeTreeFairOdds(joint);
  const branches=outcomeTreeBuild(legs),shared=outcomeTreeSharedTeams(legs);
  return `<aside class="outcomeSummary"><div class="outcomeSummaryHead"><div><span>Selected path</span><b>${legs.length}/${OUTCOME_TREE_MAX_LEGS} events</b></div><button type="button" class="miniBtn" data-tree-reset>Reset</button></div>
    <div class="outcomeTotals"><div class="outcomeMainTotal"><span>Combined model probability</span><b>${outcomeTreePercent(joint)}</b></div><div><span>Fair decimal</span><b>${odds.decimal?odds.decimal.toFixed(2):'—'}</b></div><div><span>Fair American</span><b>${outcomeTreeAmerican(odds.american)}</b></div></div>
    ${OUTCOME_TREE_NOTICE?`<div class="outcomeNotice">${esc(OUTCOME_TREE_NOTICE)}</div>`:''}
    ${shared.length?`<div class="outcomeWarning"><b>Correlation warning</b><span>${shared.length} repeated team${shared.length===1?'':'s'} appears across the selected games. Those events may not be independent, so the combined estimate can be too high or too low.</span></div>`:''}
    <div class="outcomeTreeKey"><span><b>X</b> selected exact outcome</span><span><b>Y</b> any other result</span></div>
    <div class="outcomeBranches">${branches.map(branch=>`<div class="outcomeBranch"><div class="outcomeBranchRail"><i>${branch.index}</i><span></span></div><div class="outcomeBranchCard"><small>Event ${branch.index}</small><div><b>X</b><strong>${branch.probability}%</strong></div><p>Selected outcome · path now ${outcomeTreePercent(branch.cumulative)}</p><div class="outcomeExit"><span>Y</span><b>${100-branch.probability}%</b></div></div></div>`).join('')}</div>
    <div class="outcomeDisclosure"><b>Independence assumption</b><span>This multiplies published probabilities as if different games do not affect one another. Fair odds are model-implied, not a sportsbook price or betting recommendation.</span></div></aside>`;
}

function renderOutcomeTree(){
  const host=document.getElementById('view-tree');if(!host)return;
  const matches=outcomeTreeMatches(),legs=outcomeTreeLegs();
  host.innerHTML=`<div class="outcomeHero"><div><span class="outcomeEyebrow">Scenario analysis</span><h2>Build an exact five-event path.</h2><p>Choose up to five outcomes in the compact menu. In the tree, X is the selected exact outcome and Y is any other result. Locked prediction snapshots take priority.</p></div><div class="outcomeFormula"><span>JOINT PATH</span><b>p<sub>1</sub> × p<sub>2</sub> × … × p<sub>n</sub></b><small>assumes games are independent</small></div></div>
    <div class="outcomeShell"><section class="outcomePicker"><div class="outcomePickerHead"><div><h3>Scenario selections</h3><span>${legs.length}/${OUTCOME_TREE_MAX_LEGS} chosen</span></div></div>${OUTCOME_TREE_NOTICE&& !legs.length?`<div class="outcomeNotice">${esc(OUTCOME_TREE_NOTICE)}</div>`:''}${outcomeTreeCompactPicker(matches,legs)}</section>${outcomeTreeSummary(legs)}</div>
    <div class="outcomeBottomNote"><b>Read this as a scenario, not a promise.</b> A 12% path means the model expects that exact combination roughly 12 times in 100 comparable sets only if the input probabilities are calibrated and the events are independent.</div>`;
  host.onclick=event=>{
    const reset=event.target.closest('[data-tree-reset]');if(reset){outcomeTreeReset();return;}
    const remove=event.target.closest('[data-tree-remove]');if(remove){outcomeTreeRemove(remove.dataset.treeRemove);return;}
    const add=event.target.closest('[data-tree-add]');if(add)outcomeTreeAddDraft();
  };
  const matchSelect=host.querySelector('[data-tree-draft-match]');
  if(matchSelect)matchSelect.onchange=event=>outcomeTreeDraftMatch(event.target.value);
  const sideSelect=host.querySelector('[data-tree-draft-side]');
  if(sideSelect)sideSelect.onchange=event=>outcomeTreeDraftSide(event.target.value);
}
