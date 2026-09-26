/* Presentation only. Bet Better owns every selection, seed, rating and odds value. */
window.MatchdayBracketology=(()=>{
  const state={data:null,error:'',pending:null,loaded:0,tab:'bracket',region:'',compare:false,opener:null,staleTimer:null,observer:null};
  const h=v=>esc(String(v??''));
  const number=v=>typeof v==='number'&&Number.isFinite(v);
  const odds=v=>number(v)&&v>=0&&v<=1?(v>0&&v<.01?'<1%':new Intl.NumberFormat('en-US',{style:'percent',maximumFractionDigits:0}).format(v)):'Unavailable';
  const value=v=>v==null?'Unavailable':h(v);
  const statuses={locked:'Locked',in:'Projected in',bubble:'Bubble',out:'Outside projected field',auto_bid_only:'Auto bid only',eliminated:'Eliminated',tournament_eliminated:'Tournament eliminated'};
  const phaseNames={early:'Early projection',in_season:'Projected field',championship_week:'Championship week',official:'Official bracket'};
  const preview=()=>['localhost','127.0.0.1','[::1]'].includes(location.hostname)&&new URLSearchParams(location.search).get('bracketology_preview')==='1';
  function validate(d,allowMock=false){
    if(!d||d.version!=='0.1'||d.display_contract!=='matchday-1')throw Error('The bracketology handoff is not compatible with this view.');
    if(d.mock&&!allowMock)throw Error('Preview data cannot be shown as a live projection.');
    if(!['NCAAM','NCAAF'].includes(d.competition)||!d.season||!d.build_id||!phaseNames[d.phase]||typeof d.calibrated!=='boolean'||!['projected','official'].includes(d.bracket?.kind))throw Error('The handoff is missing its competition or publication state.');
    if((d.phase==='official')!==(d.bracket.kind==='official'))throw Error('The phase and bracket publication state disagree.');
    if(!Number.isFinite(Date.parse(d.as_of))||!Number.isFinite(Date.parse(d.valid_until)))throw Error('The handoff is missing its freshness dates.');
    if(Date.parse(d.valid_until)<=Date.parse(d.as_of))throw Error('The handoff freshness dates are invalid.');
    if(!Array.isArray(d.field)||!Number.isInteger(d.field_size)||d.field.length!==d.field_size||!d.teams||!Array.isArray(d.regions)||!Array.isArray(d.rounds)||!d.rounds.length||!Array.isArray(d.odds_rounds)||!d.odds_rounds.length||!Number.isInteger(d.max_seed)||d.max_seed<1||d.max_seed>32||!Array.isArray(d.bracket?.games))throw Error('The handoff is missing its field or bracket structure.');
    const rounds=new Set(d.rounds.map(r=>r.key)),ids=new Set(),keys=new Set();
    if(rounds.size!==d.rounds.length||new Set(d.regions).size!==d.regions.length||d.rounds.some(r=>!r.key||!r.label))throw Error('The handoff has duplicate or unnamed rounds.');
    for(const [key,t] of Object.entries(d.teams)){
      if(!key||!t.team_name||!t.conference||!statuses[t.status])throw Error('A team is missing its identity or status.');
      const probabilities=[t.odds?.make_field,t.odds?.auto_bid,...Object.values(t.odds?.seed||{}),...Object.values(t.odds?.rounds||{})];
      if(probabilities.some(p=>p!=null&&(!number(p)||p<0||p>1)))throw Error('A supplied probability is invalid.');
    }
    for(const t of d.field){if(!d.teams[t.team_key]||keys.has(t.team_key)||!Number.isInteger(t.seed)||t.seed<1||t.seed>d.max_seed)throw Error('The field has a duplicate or unknown team, or an invalid seed.');keys.add(t.team_key)}
    for(const game of d.bracket.games){
      if(!game.id||!game.label||ids.has(game.id)||!rounds.has(game.round)||!(d.regions.length?d.regions.includes(game.region):game.region==null)||!Array.isArray(game.slots)||game.slots.length!==2)throw Error('A bracket game has an invalid identity, round or slots.');
      ids.add(game.id);
      for(const slot of game.slots){if(!!slot.team_key===!!slot.source_game)throw Error('A bracket slot must have one participant or one feeder.');if(slot.team_key&&!d.teams[slot.team_key])throw Error('A bracket slot refers to an unknown team.');}
      if(game.winner_key&&!game.slots.some(s=>s.team_key===game.winner_key))throw Error('A game winner is not one of its supplied participants.');
    }
    for(const game of d.bracket.games){
      if(game.next_game&&(!ids.has(game.next_game)||![0,1].includes(game.next_slot)))throw Error('A bracket advancement path is missing.');
      for(const [slotIndex,slot] of game.slots.entries()){if(slot.source_game&&!ids.has(slot.source_game))throw Error('A bracket feeder game is missing.');if(slot.source_game){const source=d.bracket.games.find(g=>g.id===slot.source_game);if(source.next_game!==game.id||source.next_slot!==slotIndex)throw Error('A bracket feeder disagrees with its advancement destination.');}}
      if(game.next_game){const destination=d.bracket.games.find(g=>g.id===game.next_game),slot=destination.slots[game.next_slot];if(slot.source_game&&slot.source_game!==game.id)throw Error('A bracket advancement destination disagrees with its feeder.');}
      const visited=new Set();let current=game;
      while(current){if(visited.has(current.id))throw Error('The bracket contains a circular path.');visited.add(current.id);current=d.bracket.games.find(g=>g.id===current.next_game)}
    }
    for(const group of Object.values(d.bubble||{}))if(!Array.isArray(group)||group.some(k=>!d.teams[k]))throw Error('The bubble contains an unknown team.');
    if((d.eliminated||[]).some(t=>!d.teams[t.team_key])||(d.bid_thieves||[]).some(t=>!d.teams[t.team_key])||(d.conferences||[]).some(c=>Object.keys(c.auto_bid_odds||{}).some(k=>!d.teams[k])))throw Error('A report refers to an unknown team.');
    return d;
  }
  function current(){return state.compare&&state.data?.final_projection?state.data.final_projection:state.data}
  function expired(){return state.data&&Date.now()>Date.parse(state.data.valid_until)}
  function help(label,text){return `<details class="bkHelp"><summary aria-label="About ${h(label)}" title="${h(text)}">?</summary><p>${h(text)}</p></details>`}
  function movement(m){
    if(!m)return '';
    const parts=[];
    if(number(m.seed)&&m.seed!==0)parts.push(`${m.seed<0?'↑':'↓'} ${Math.abs(m.seed)} seed${Math.abs(m.seed)===1?'':'s'}`);
    if(number(m.make_field)&&m.make_field!==0)parts.push(`${m.make_field>0?'↑':'↓'} ${(Math.abs(m.make_field)*100).toFixed(1).replace(/\.0$/,'')} pp field odds`);
    return parts.length?`<span class="bkMovement">${h(parts.join(' · '))}</span>`:'';
  }
  function status(t){return `<span class="bkStatus bkStatus-${h(t.status)}">${h(statuses[t.status]||'Status unavailable')}</span>`}
  function teamButton(key,detail='',extra=''){
    const t=current().teams[key];if(!t)return '<span>Team unavailable</span>';
    return `<button type="button" class="bkTeam ${h(extra)}" data-team="${h(key)}">${teamMark(t.logo_key||t.team_name)}<span><b>${h(t.team_name)}</b>${detail?`<small>${detail}</small>`:''}</span><span class="bkOpen" aria-hidden="true">↗</span></button>`;
  }
  function bracket(d){
    const games=d.bracket.games.filter(g=>(g.region??null)===state.region);
    const columns=d.rounds.filter(r=>games.some(g=>g.round===r.key));
    return `<nav class="bkRegions" aria-label="Bracket region">${(d.regions.length?d.regions:[null]).map(r=>`<button type="button" data-region="${h(r??'')}" aria-pressed="${r===state.region}">${h(r??'Playoff')}</button>`).join('')}</nav><p class="bkHint">Select a school for its résumé. Scroll inside the bracket to follow the rounds.</p><div class="bkBracketFrame" role="region" tabindex="0" aria-label="${h(state.region)} bracket, scroll horizontally"><div class="bkBracketColumns">${columns.map(r=>`<section class="bkRound"><h3>${h(r.label)}</h3><div class="bkGames">${games.filter(g=>g.round===r.key).map(g=>{
      const next=d.bracket.games.find(n=>n.id===g.next_game);
      return `<article class="bkGame" data-game="${h(g.id)}"><div class="bkGameMeta">${h(g.label||g.id)}${g.status==='finished'?' · Final':d.bracket.kind==='official'?'':' · Projected'}</div>${g.slots.map((slot,i)=>{
        if(!slot.team_key)return `<div class="bkSlot"><span aria-hidden="true">—</span><span>${h(slot.label||'Awaiting team')}</span></div>`;
        const t=d.teams[slot.team_key],entry=d.field.find(f=>f.team_key===slot.team_key)||t;
        const bid={auto:'Projected auto',at_large:'At-large',auto_clinched:'🔒 Clinched auto'}[entry.bid]||'Bid unavailable';
        const eliminated=['eliminated','tournament_eliminated'].includes(t.status);
        const score=g.status==='finished'&&Array.isArray(g.score)?g.score[i]:null;
        return `<div class="bkGameTeam ${eliminated?'bkLost':''} ${g.winner_key===slot.team_key?'bkWinner':''}"><span class="bkSeed">${value(entry.seed)}</span>${teamButton(slot.team_key,`${h(bid)} · ${odds(t.odds?.seed?.[entry.seed])} at seed${eliminated?` · ${h(t.eliminated_round||statuses[t.status])}`:''}`)}${score!=null?`<strong class="bkScore">${value(score)}</strong>`:''}</div>`;
      }).join('')}${next?`<footer>→ ${h(next.label||next.id)}${next.region!==state.region?` · ${h(next.region)}`:''}</footer>`:''}</article>`;
    }).join('')}</div></section>`).join('')}</div></div>`;
  }
  function connectBracket(host,d){
    const board=host.querySelector('.bkBracketColumns');if(!board)return;
    const bounds=board.getBoundingClientRect(),svg=document.createElementNS('http://www.w3.org/2000/svg','svg');
    svg.setAttribute('class','bkConnections');svg.setAttribute('aria-hidden','true');svg.setAttribute('width',bounds.width);svg.setAttribute('height',bounds.height);
    const cards=new Map(Array.from(board.querySelectorAll('[data-game]')).map(el=>[el.dataset.game,el]));
    d.bracket.games.forEach(g=>{
      const from=cards.get(g.id),to=cards.get(g.next_game);if(!from||!to)return;
      const a=from.getBoundingClientRect(),b=to.getBoundingClientRect(),x1=a.right-bounds.left,x2=b.left-bounds.left,y1=a.top+a.height/2-bounds.top,y2=b.top+b.height/2-bounds.top;
      const path=document.createElementNS(svg.namespaceURI,'path');path.setAttribute('d',`M ${x1} ${y1} H ${(x1+x2)/2} V ${y2} H ${x2}`);svg.append(path);
    });board.prepend(svg);
  }
  function bubble(d){
    const groups=[['last_four_byes','Last four byes'],['last_four_in','Last four in'],['first_four_out','First four out'],['next_four_out','Next four out']];
    return `<div class="bkBubble">${groups.map(([key,label])=>`<section class="bkBubbleColumn"><h3>${label}</h3>${(d.bubble?.[key]||[]).map(key=>{const t=d.teams[key];return `<article>${teamButton(key,h(t.conference))}<div class="bkBubbleOdds"><b>${odds(t.odds?.make_field)}</b><span>make field</span></div>${status(t)}${movement(t.movement)}</article>`}).join('')||'<p class="bkHint">No teams supplied.</p>'}</section>`).join('')}</div><section class="bkSupport"><h3>Bid thieves ${help('bid thieves','Conference tournament outcomes identified by the model that could reduce available at-large places.')}</h3>${d.bid_thieves?.length?d.bid_thieves.map(t=>`<article class="bkThief">${teamButton(t.team_key,h(t.conference))}<span>${odds(t.auto_bid_odds)} auto bid</span><b>${value(t.at_large_spots_at_risk)} at-large place(s) at risk</b></article>`).join(''):'<p class="bkHint">No bid thieves supplied.</p>'}</section>`;
  }
  function table(headers,rows){return `<div class="bkTableFrame" tabindex="0" role="region" aria-label="Scrollable bracketology table"><table><thead><tr>${headers.map(s=>`<th scope="col">${s}</th>`).join('')}</tr></thead><tbody>${rows.join('')}</tbody></table></div>`}
  function seedList(d){return table(['S-curve','Seed','School','Conference','Power rating','Résumé rank','Q1','Make field','Movement'],d.field.slice().sort((a,b)=>a.overall_seed-b.overall_seed).map(f=>{const t=d.teams[f.team_key];return `<tr><td>${value(f.overall_seed)}</td><td>${value(f.seed)}</td><th scope="row">${teamButton(f.team_key)}</th><td>${h(t.conference)}</td><td>${value(t.power_rating)}</td><td>${value(t.resume_rank)}</td><td>${record(t.quadrants?.Q1)}</td><td>${odds(t.odds?.make_field)}</td><td>${movement(t.movement)||'—'}</td></tr>`}))}
  function record(v){return Array.isArray(v)&&v.length===2?v.map(value).join('–'):'Unavailable'}
  function conferences(d){return `<div class="bkConferenceGrid">${(d.conferences||[]).map(c=>`<section class="bkSupport"><h3>${h(c.conference)}</h3><p><b>${value(c.projected_bids)}</b> projected bids</p>${Object.entries(c.auto_bid_odds||{}).map(([key,p])=>`<div class="bkConferenceTeam">${teamButton(key)}<span>${odds(p)} auto bid</span></div>`).join('')}</section>`).join('')||'<p>Conference projections unavailable.</p>'}</div>`}
  function tournamentOdds(d){return table(['School',...d.odds_rounds.map(r=>h(r.label)),'Model alert'],d.field.map(f=>{const t=d.teams[f.team_key];return `<tr><th scope="row">${teamButton(f.team_key,`Seed ${h(f.seed)}`)}</th>${d.odds_rounds.map(r=>`<td>${odds(t.odds?.rounds?.[r.key])}</td>`).join('')}<td>${t.upset_alert?'⚑ Upset alert':'—'}</td></tr>`}))}
  function eliminated(d){return `<section class="bkSupport"><h3>Eliminated teams</h3>${(d.eliminated||[]).slice().sort((a,b)=>String(b.eliminated_on).localeCompare(String(a.eliminated_on))).map(t=>`<article class="bkEliminated">${teamButton(t.team_key)}<span>${h(t.eliminated_reason||'Reason unavailable')}</span><time>${h(t.eliminated_on||'Date unavailable')}</time></article>`).join('')||'<p class="bkHint">No eliminated teams supplied.</p>'}</section>`}
  function resume(key){
    const d=current(),t=d.teams[key];if(!t||expired())return;
    let dialog=document.getElementById('bk-resume');if(dialog)dialog.remove();
    dialog=document.createElement('dialog');dialog.id='bk-resume';dialog.className='bkResume';dialog.setAttribute('aria-labelledby','bk-resume-title');
    const f=d.field.find(f=>f.team_key===key),seedKeys=Array.from({length:d.max_seed},(_,i)=>String(i+1)).concat('out');
    const games=(label,rows)=>`<section><h3>${label}</h3>${rows?.length?`<ul class="bkResults">${rows.map(g=>`<li><b>${h(g.opponent||'Opponent unavailable')}</b><span>${h([g.site,g.date].filter(Boolean).join(' · '))}</span></li>`).join('')}</ul>`:'<p class="bkHint">None supplied.</p>'}</section>`;
    dialog.innerHTML=`<header><div>${teamMark(t.logo_key||t.team_name)}<h2 id="bk-resume-title">${h(t.team_name)}</h2></div><button type="button" data-close aria-label="Close résumé">×</button></header><div class="bkResumeBody">${d.mock?'<p class="bkMock">Design preview · Not a forecast</p>':''}${!d.calibrated?'<span class="bkStatus">Beta</span>':''}<p class="bkHint">${h(t.conference)} · ${h(t.record||'Record unavailable')}${f?` · ${d.bracket.kind==='official'?'':'Projected '}seed ${h(f.seed)}`:''}</p>${status(t)}${movement(t.movement)}${['eliminated','tournament_eliminated'].includes(t.status)?`<p>${h(t.eliminated_reason||'Reason unavailable')} · ${h(t.eliminated_on||'Date unavailable')}</p>`:''}<div class="bkRatingPair"><section><span>Who is best ${help('power rating','Opponent-adjusted, tempo-free team strength supplied by Bet Better. It is separate from tournament selection.')}</span><strong>${value(t.power_rating)}</strong><b>Power rating</b></section><section><span>Who earned a spot ${help('résumé rank','The model’s résumé measure of results earned. This is not the NCAA NET.')}</span><strong>${t.resume_rank!=null?'#'+value(t.resume_rank):'Unavailable'}</strong><b>Résumé rank</b></section></div><div class="bkQuadGrid">${['Q1','Q2','Q3','Q4'].map(q=>`<div><span>${q}</span><b>${record(t.quadrants?.[q])}</b></div>`).join('')}</div><dl class="bkStats"><div><dt>Strength of schedule</dt><dd>${t.sos_rank!=null?'#'+value(t.sos_rank):'Unavailable'}</dd></div><div><dt>Strength of record</dt><dd>${t.sor_rank!=null?'#'+value(t.sor_rank):'Unavailable'}</dd></div><div><dt>Make field</dt><dd>${odds(t.odds?.make_field)}</dd></div><div><dt>Auto bid</dt><dd>${odds(t.odds?.auto_bid)}</dd></div></dl><section><h3>Seed odds ${help('seed odds','Each bar is the supplied chance of that seed, including missing the field. Unavailable values are not zero.')}</h3><div class="bkSeedChart">${seedKeys.map(seed=>{const p=t.odds?.seed?.[seed];return `<div><span>${seed==='out'?'Out':seed}</span><span class="bkBar" aria-hidden="true"><i style="width:${number(p)?p*100:0}%"></i></span><b>${odds(p)}</b></div>`}).join('')}</div></section><section><h3>Tournament odds</h3><dl class="bkRoundOdds">${d.odds_rounds.map(r=>`<div><dt>${h(r.label)}</dt><dd>${odds(t.odds?.rounds?.[r.key])}</dd></div>`).join('')}</dl></section>${games('Best wins',t.best_wins)}${games('Worst losses',t.bad_losses)}</div>`;
    document.body.append(dialog);dialog.querySelector('[data-close]').onclick=()=>dialog.close();dialog.addEventListener('close',()=>{dialog.remove();if(state.opener?.isConnected)state.opener.focus()});dialog.showModal();
  }
  function draw(host){
    if(!host.isConnected)return;
    state.observer?.disconnect();
    const d=current();
    if(!d||expired()){
      host.innerHTML=`<section class="bkShell"><header class="bkHeader"><div><span class="bkEyebrow">Men’s college basketball</span><h2>Bracketology</h2></div></header><div class="bkUnavailable" role="status"><h3>${expired()?'Bracketology update overdue':'Bracketology unavailable'}</h3><p>${expired()?`The last handoff was updated ${h(new Date(state.data.as_of).toLocaleString())}. A fresh projection has not arrived.`:h(state.error||'Waiting for the Bet Better bracketology handoff.')}</p><button type="button" data-retry>Check for update</button></div></section>`;
      host.querySelector('[data-retry]').onclick=()=>load(host,true);return;
    }
    if(!d.regions.includes(state.region))state.region=d.regions[0]??null;
    const tabs=[['bracket','Bracket'],['bubble','Bubble'],['seeds','Seed list'],['conferences','Conferences'],['odds','Tournament odds'],['eliminated','Eliminated']];
    const body={bracket,bubble,seeds:seedList,conferences,odds:tournamentOdds,eliminated};
    host.innerHTML=`<section class="bkShell">${d.mock?'<div class="bkMock" role="status">DESIGN PREVIEW · Illustrative data · Not a forecast</div>':''}<header class="bkHeader"><div><span class="bkEyebrow">Men’s college basketball · ${h(d.season)}</span><h2>Bracketology</h2></div><div class="bkBadges">${!d.calibrated?'<span>Beta</span>':''}<span>${h(state.compare?'Final projection':phaseNames[d.phase])}</span></div></header><div class="bkAsOf"><span>Updated ${h(new Date(d.as_of).toLocaleString())}</span>${d.phase==='early'?'<span>Early-season uncertainty · Explore each team’s seed odds</span>':''}${d.final_projection?`<button type="button" data-compare>${state.compare?'View official bracket':'Compare final projection'}</button>`:state.compare?'<button type="button" data-compare>View official bracket</button>':''}</div><nav class="bkTabs" aria-label="Bracketology views">${tabs.map(([key,label])=>`<button type="button" data-tab="${key}" aria-pressed="${state.tab===key}">${label}</button>`).join('')}</nav><div class="bkContent">${body[state.tab](d)}</div><p class="bkSource">Selections, résumé measures and odds supplied by Bet Better.${d.odds_basis==='unconditional_season'?' Odds include the chance of reaching the field.':d.odds_basis==='conditional_on_field'?' Tournament odds assume a place in the field.':''}</p></section>`;
    if(state.tab==='bracket')requestAnimationFrame(()=>{const board=host.querySelector('.bkBracketColumns');if(!board)return;connectBracket(host,d);if(typeof ResizeObserver!=='undefined'){state.observer=new ResizeObserver(()=>{board.querySelector('.bkConnections')?.remove();connectBracket(host,d)});state.observer.observe(board)}});
    host.onclick=event=>{
      if(expired()){document.getElementById('bk-resume')?.close();draw(host);return}
      const button=event.target.closest('button');if(!button)return;
      if(button.dataset.team){state.opener=button;resume(button.dataset.team)}
      else if(button.dataset.tab){state.tab=button.dataset.tab;draw(host);host.querySelector(`[data-tab="${state.tab}"]`)?.focus()}
      else if(button.hasAttribute('data-region')){state.region=button.dataset.region||null;draw(host);Array.from(host.querySelectorAll('[data-region]')).find(b=>b.dataset.region===state.region)?.focus()}
      else if(button.hasAttribute('data-compare')){state.compare=!state.compare;draw(host);host.querySelector('[data-compare]')?.focus()}
    };
  }
  async function load(host,force=false){
    if(state.pending)return state.pending;
    if(!force&&state.loaded&&Date.now()-state.loaded<60000){draw(host);return}
    host.innerHTML='<div class="bkUnavailable" role="status">Loading bracketology…</div>';
    state.pending=(async()=>{
      const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),12000);
      try{
        const url=preview()?'docs/fixtures/bracketology_ncaam.mock.json':'bracketology_ncaam.json';
        const response=await fetch(url,{cache:'no-store',signal:controller.signal});
        if(!response.ok)throw Error(response.status===404?'The Bet Better bracketology handoff has not arrived yet.':'The bracketology handoff could not be loaded.');
        const data=validate(await response.json(),preview());
        if(data.final_projection)validate(data.final_projection,preview());
        state.data=data;state.error='';state.compare=false;
        clearTimeout(state.staleTimer);const delay=Date.parse(data.valid_until)-Date.now();
        if(delay>0&&delay<2147483647)state.staleTimer=setTimeout(()=>{document.getElementById('bk-resume')?.close();if(DATA.comp_key==='NCAAM')draw(host)},delay+10);
      }catch(error){state.data=null;state.error=error.name==='AbortError'?'The bracketology handoff timed out. Please try again.':error.message}
      finally{clearTimeout(timer);state.loaded=Date.now();state.pending=null;if(DATA.comp_key==='NCAAM')draw(host)}
    })();return state.pending;
  }
  return {render:load,validate,formatOdds:odds};
})();
