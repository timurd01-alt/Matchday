/* Presentation only. The engine owns every selection, seed, rating and odds value. */
window.MatchdayBracketology=(()=>{
  const state={data:null,error:'',pending:null,loaded:0,tab:'bracket',region:'',full:false,zoom:null,conf:'',compare:false,opener:null,staleTimer:null,observer:null};
  const h=v=>esc(String(v??''));
  const number=v=>typeof v==='number'&&Number.isFinite(v);
  const odds=v=>number(v)&&v>=0&&v<=1?(v>0&&v<.01?'<1%':new Intl.NumberFormat('en-US',{style:'percent',maximumFractionDigits:0}).format(v)):'Unavailable';
  const value=v=>v==null?'Unavailable':h(v);
  const statuses={locked:'Locked',in:'Projected in',bubble:'Bubble',out:'Outside projected field',auto_bid_only:'Auto bid only',eliminated:'Eliminated',tournament_eliminated:'Tournament eliminated'};
  const phaseNames={early:'Early projection',in_season:'Projected field',championship_week:'Championship week',official:'Official bracket'};
  const preview=()=>['localhost','127.0.0.1','[::1]'].includes(location.hostname)&&new URLSearchParams(location.search).get('bracketology_preview')==='1';
  function currentBasketballSeason(){
    const today=new Date();
    const start=today.getUTCFullYear()-(today.getUTCMonth()<6?1:0);
    return `${start}-${String(start+1).slice(-2)}`;
  }
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
    if((d.eliminated||[]).some(t=>!d.teams[t.team_key])||(d.bid_thieves||[]).some(t=>!d.teams[t.team_key])||(d.conferences||[]).some(c=>Object.keys(c.auto_bid_odds||{}).some(k=>!d.teams[k])||(c.tournament?.seeds||[]).some(k=>!d.teams[k])||Object.keys(c.tournament?.odds||{}).some(k=>!d.teams[k])))throw Error('A report refers to an unknown team.');
    return d;
  }
  function current(){return state.compare&&state.data?.final_projection?state.data.final_projection:state.data}
  function expired(){return state.data&&Date.now()>Date.parse(state.data.valid_until)}
  function help(label,text){return `<details class="bkHelp"><summary aria-label="About ${h(label)}" title="${h(text)}">?</summary><p>${h(text)}</p></details>`}
  function movement(m){
    if(!m)return '';
    const parts=[];
    if(number(m.seed)&&m.seed!==0)parts.push(`${m.seed<0?'↑':'↓'} ${Math.abs(m.seed)} seed${Math.abs(m.seed)===1?'':'s'}`);
    if(number(m.make_field)&&m.make_field!==0)parts.push(`${m.make_field>0?'↑':'↓'} ${(Math.abs(m.make_field)*100).toFixed(1).replace(/\.0$/,'')} pts field odds since last update`);
    return parts.length?`<span class="bkMovement">${h(parts.join(' · '))}</span>`:'';
  }
  function status(t){return `<span class="bkStatus bkStatus-${h(t.status)}">${h(statuses[t.status]||'Status unavailable')}</span>`}
  function teamButton(key,detail='',extra='',short=false){
    const t=current().teams[key];if(!t)return '<span>Team unavailable</span>';
    // The slim full-bracket cards use the school name the rest of the site uses ("Duke").
    const name=short&&typeof rsShortName==='function'?rsShortName(t.team_name):t.team_name;
    return `<button type="button" class="bkTeam ${h(extra)}" data-team="${h(key)}" title="${h(t.team_name)}">${teamMark(t.logo_key||t.team_name)}<span><b>${h(name)}</b>${detail?`<small>${detail}</small>`:''}</span><span class="bkOpen" aria-hidden="true">↗</span></button>`;
  }
  // Teams that can arrive in a slot: every team seeded anywhere beneath its feeder game.
  function feederTeams(d,gameId,seen=new Set()){
    const g=d.bracket.games.find(n=>n.id===gameId);if(!g||seen.has(gameId))return [];seen.add(gameId);
    return g.slots.flatMap(slot=>slot.team_key?[slot.team_key]:slot.source_game?feederTeams(d,slot.source_game,seen):[]);
  }
  function likeliestSlot(d,g,slot){
    if(!slot.source_game||g.round==='FF')return null;
    let best=null;
    for(const key of feederTeams(d,slot.source_game)){const p=d.teams[key]?.odds?.rounds?.[g.round];if(number(p)&&(!best||p>best.p))best={key,p};}
    return best;
  }
  function gameCard(g,d,compact=false,meta=''){
      const next=d.bracket.games.find(n=>n.id===g.next_game);
      const head=meta?`<div class="bkGameMeta bkMetaCaps">${h(meta)}</div>`:compact?'':`<div class="bkGameMeta">${h(g.label||g.id)}${g.status==='finished'?' · Final':d.bracket.kind==='official'?'':' · Projected'}</div>`;
      return `<article class="bkGame${compact?' bkGameCompact':''}${compact==='mini'?' bkGameMini':''}" data-game="${h(g.id)}">${head}${g.slots.map((slot,i)=>{
        if(!slot.team_key){
          const likely=compact&&d.bracket.kind!=='official'?likeliestSlot(d,g,slot):null;
          if(likely)return `<div class="bkGameTeam bkLikely"><span class="bkSeed">${value(d.field.find(f=>f.team_key===likely.key)?.seed)}</span>${teamButton(likely.key,`${odds(likely.p)} to get here`,'',compact==='mini')}</div>`;
          return `<div class="bkSlot"><span aria-hidden="true">—</span><span>${h(slot.label||'Awaiting team')}</span></div>`;
        }
        const t=d.teams[slot.team_key],entry=d.field.find(f=>f.team_key===slot.team_key)||t;
        const bid={auto:'Projected auto',at_large:'At-large',auto_clinched:'🔒 Clinched auto'}[entry.bid]||'Bid unavailable';
        const eliminated=['eliminated','tournament_eliminated'].includes(t.status);
        const score=g.status==='finished'&&Array.isArray(g.score)?g.score[i]:null;
        return `<div class="bkGameTeam ${eliminated?'bkLost':''} ${g.winner_key===slot.team_key?'bkWinner':''}"><span class="bkSeed">${value(entry.seed)}</span>${teamButton(slot.team_key,`${h(bid)} · ${odds(t.odds?.seed?.[entry.seed])} at seed${eliminated?` · ${h(t.eliminated_round||statuses[t.status])}`:''}`,'',compact==='mini')}${score!=null?`<strong class="bkScore">${value(score)}</strong>`:''}</div>`;
      }).join('')}${next&&!compact?`<footer>→ ${h(next.label||next.id)}${next.region!==state.region?` · ${h(next.region)}`:''}</footer>`:''}</article>`;
  }
  // Which bracket: the NCAA tournament, or one conference's tournament.
  function picker(d){
    const tournaments=(d.conferences||[]).filter(c=>c.tournament?.games?.length);
    if(!tournaments.length)return '';
    return `<div class="bkPicker"><label for="bk-which">Bracketology</label><select id="bk-which" data-which><option value=""${state.conf?'':' selected'}>NCAA Tournament</option>${tournaments.map(c=>`<option value="${h(c.conference)}"${state.conf===c.conference?' selected':''}>${h(c.conference.replace(/ Conference$/,''))} Tournament</option>`).join('')}</select></div>`;
  }
  function conferenceGames(d){return (d.conferences||[]).find(c=>c.conference===state.conf)?.tournament?.games||[]}
  function conferenceBracket(d,c){
    const T=c?.tournament;
    if(!T)return '<p class="bkHint">This conference tournament has no projection right now.</p>';
    const o=key=>T.odds?.[key]||{};
    const feeders=(gid,seen=new Set())=>{const g=T.games.find(x=>x.id===gid);if(!g||seen.has(gid))return [];seen.add(gid);return g.slots.flatMap(sl=>sl.team_key?[sl.team_key]:sl.source_game?feeders(sl.source_game,seen):[])};
    const card=g=>`<article class="bkGame bkGameCompact" data-game="${h(g.id)}">${g.slots.map(sl=>{
      if(sl.team_key)return `<div class="bkGameTeam"><span class="bkSeed">${value(sl.seed)}</span>${teamButton(sl.team_key,g.round===0?`${odds(o(sl.team_key).qualify)} to qualify`:`${odds(o(sl.team_key).rounds?.[g.round])} to play here`)}</div>`;
      let best=null;for(const key of feeders(sl.source_game)){const p=o(key).rounds?.[g.round];if(number(p)&&(!best||p>best.p))best={key,p}}
      if(!best)return `<div class="bkSlot"><span aria-hidden="true">—</span><span>Winner advances</span></div>`;
      return `<div class="bkGameTeam bkLikely"><span class="bkSeed">${value(T.seeds.indexOf(best.key)+1||'')}</span>${teamButton(best.key,`${odds(best.p)} to get here`)}</div>`;
    }).join('')}</article>`;
    const columns=T.format.rounds.map((label,r)=>({label,games:T.games.filter(g=>g.round===r)})).filter(col=>col.games.length);
    const favourites=Object.entries(T.odds||{}).filter(([,v])=>number(v.title)&&v.title>0).sort((a,b)=>b[1].title-a[1].title).slice(0,6);
    const learned=T.format.learned_from?`the format it played in ${h(T.format.learned_from)}`:'a standard bracket (no earlier tournament on record)';
    const short=c.conference.replace(/ Conference$/,'');
    return `<p class="bkHint">${h(T.format.size)} teams, seeded by projected conference finish from this season’s results, in ${learned}. Later rounds show each slot’s likeliest team. Select a school for its résumé.</p><div class="bkBracketFrame" role="region" tabindex="0" aria-label="${h(short)} tournament bracket, scroll horizontally"><div class="bkBracketColumns">${columns.map(col=>`<section class="bkRound"><h3>${h(col.label)}</h3><div class="bkGames">${col.games.map(card).join('')}</div></section>`).join('')}${favourites.length?`<section class="bkRound bkRegionOdds"><h3>Title favourites</h3><div class="bkSupport"><p class="bkHint">Chance to win the ${h(short)} tournament and its automatic bid.</p>${favourites.map(([key,v])=>`<div class="bkConferenceTeam">${teamButton(key)}<span>${odds(v.title)}</span></div>`).join('')}</div></section>`:''}</div></div>`;
  }
  function bracket(d){
    if(state.conf){const c=(d.conferences||[]).find(x=>x.conference===state.conf);if(c)return picker(d)+conferenceBracket(d,c);state.conf=''}
    return picker(d)+ncaaBracket(d);
  }
  function ncaaBracket(d){
    if(state.full)return fullBracket(d);
    const games=d.bracket.games.filter(g=>(g.region??null)===state.region);
    const nav=`<nav class="bkRegions" aria-label="Bracket region"><button type="button" data-full="true" aria-pressed="false">Full bracket</button>${(d.regions.length?d.regions:[null]).map(r=>`<button type="button" data-region="${h(r??'')}" aria-pressed="${r===state.region}">${h(r??'Playoff')}</button>`).join('')}</nav>`;
    const final=games.find(g=>g.round==='F'&&!g.next_game),semis=final?games.filter(g=>g.next_game===final.id).sort((a,b)=>a.id.localeCompare(b.id)):[];
    if(final&&semis.length===2&&games.length===3)return nav+national(d,final,semis);
    if(games.length&&games.every(g=>g.round==='FF'))return nav+firstFour(d,games);
    const columns=d.rounds.filter(r=>games.some(g=>g.round===r.key));
    const last=columns[columns.length-1],nextRound=last&&d.rounds[d.rounds.findIndex(r=>r.key===last.key)+1];
    const contenders=nextRound&&state.region?[...new Set(games.flatMap(g=>g.slots.map(s=>s.team_key).filter(Boolean)))]
      .map(key=>({key,p:d.teams[key]?.odds?.rounds?.[nextRound.key]})).filter(t=>number(t.p)).sort((a,b)=>b.p-a.p).slice(0,6):[];
    const favourites=contenders.length&&last.key==='E8'?`<section class="bkRound bkRegionOdds"><h3>Region favourites</h3><div class="bkSupport"><p class="bkHint">Chance to win the ${h(state.region)} and reach the ${h(nextRound.label)}.</p>${contenders.map(t=>`<div class="bkConferenceTeam">${teamButton(t.key)}<span>${odds(t.p)}</span></div>`).join('')}</div></section>`:'';
    return `${nav}<p class="bkHint">Select a school for its résumé. Scroll inside the bracket to follow the rounds.</p><div class="bkBracketFrame" role="region" tabindex="0" aria-label="${h(state.region)} bracket, scroll horizontally"><div class="bkBracketColumns">${columns.map(r=>`<section class="bkRound"><h3>${h(r.label)}</h3><div class="bkGames">${games.filter(g=>g.round===r.key).map(g=>{
      return gameCard(g,d,true);
    }).join('')}</div></section>`).join('')}${favourites}</div></div>`;
  }
  // Outlined gold trophy in the football bracket's style: the basketball title
  // trophy's ball on a tall banded pedestal.
  const TROPHY=`<svg class="bkTrophy" viewBox="0 0 80 120" aria-hidden="true"><circle cx="40" cy="22" r="17"/><path d="M23 22h34M40 5v34M28 9.5c6 7 6 18 0 25M52 9.5c-6 7-6 18 0 25"/><path d="M33 40h14l-3 8h-8z"/><path d="M36 48h8l5 40H31z"/><path d="M31 62h18M30 76h20"/><path d="M24 88h32v10H24zM19 98h42v12H19z"/></svg>`;
  const championHead=`<div class="bkChampHead">${TROPHY}<span>National championship</span></div>`;
  // Play-in games sit side by side, each naming who its winner meets.
  function firstFour(d,games){
    const card=g=>{
      const next=d.bracket.games.find(n=>n.id===g.next_game),other=next?.slots.find(s=>s.source_game!==g.id&&s.team_key),t=other&&d.teams[other.team_key],entry=other&&d.field.find(f=>f.team_key===other.team_key);
      const html=gameCard(g,d,true).replace(/<\/article>$/,`<footer>Winner plays ${t?`${h(t.team_name)}${entry?.seed?` (${h(entry.seed)})`:''}`:'the Round of 64'} in the ${h(next?.region||'bracket')}</footer></article>`);
      return `<section class="bkFFGame"><h3>${h(g.region&&g.region!=='First Four'?g.region:next?.region||'')} · ${h(g.slots.map(s=>d.field.find(f=>f.team_key===s.team_key)?.seed).find(Boolean)||'')} seeds</h3>${html}</section>`;
    };
    return `<p class="bkHint">Four play-in games open the tournament. Each winner joins the Round of 64. Select a school for its résumé.</p><div class="bkFirstFour">${games.map(card).join('')}</div>`;
  }
  // The last weekend: both semifinals feed the championship in the middle.
  function national(d,final,semis){
    let champ=null;
    for(const key of feederTeams(d,final.id)){const p=d.teams[key]?.odds?.rounds?.champion;if(number(p)&&(!champ||p>champ.p))champ={key,p};}
    const semi=(g,i)=>`<section class="bkNatSide">${gameCard(g,d,true,`Semifinal ${i+1} · ${String(g.label||'').replace(/^Final Four · /,'')}`)}</section>`;
    return `<p class="bkHint">Two sides. One champion. Both national semifinals feed the title game in the middle. Select a school for its résumé.</p><div class="bkBracketFrame" role="region" tabindex="0" aria-label="National bracket"><div class="bkBracketColumns bkNational">${semi(semis[0],0)}<section class="bkNatCenter">${championHead}${champ&&d.bracket.kind!=='official'?`<div class="bkChampPick"><span>Projected champion</span>${teamButton(champ.key,`${odds(champ.p)} to win the title`)}</div>`:''}${gameCard(final,d,true,'Title game')}</section>${semi(semis[1],1)}</div></div>`;
  }
  function fullBracket(d){
    const games=d.bracket.games.filter(g=>g.round!=='FF'),positions=new Map(),roots=games.filter(g=>!g.next_game);
    const rounds=d.rounds.filter(r=>games.some(g=>g.round===r.key));
    const final=roots[0],step=192,center=(rounds.length-1)*step;
    const feeders=g=>games.filter(n=>n.next_game===g.id).sort((a,b)=>(a.next_slot??0)-(b.next_slot??0));
    const cursors=[40,40];
    function place(g,side){
      const incoming=feeders(g),children=incoming.map(n=>place(n,side));
      const y=children.length?children.reduce((sum,n)=>sum+n.y,0)/children.length:cursors[side];
      if(!children.length)cursors[side]+=76;
      const round=rounds.findIndex(r=>r.key===g.round),distance=(rounds.length-1-round)*step;
      const pos={x:center+(side?distance:-distance),y};positions.set(g.id,pos);return pos;
    }
    if(final){const branches=feeders(final);const placed=branches.map((g,i)=>place(g,i%2));positions.set(final.id,{x:center,y:placed.length?placed.reduce((sum,p)=>sum+p.y,0)/placed.length:60})}
    games.filter(g=>!positions.has(g.id)).forEach(g=>place(g,0));
    const height=Math.max(...cursors)+40,width=center*2+170,z=state.zoom??1,finalPos=final&&positions.get(final.id);
    return `<nav class="bkRegions" aria-label="Bracket layout"><button type="button" data-full="false" aria-pressed="false">By region</button><button type="button" data-full="true" aria-pressed="true">Full bracket</button><button type="button" data-scroll="-1" aria-label="Scroll bracket left">←</button><button type="button" data-scroll="1" aria-label="Scroll bracket right">→</button><span class="bkZoomControls" role="group" aria-label="Zoom"><button type="button" data-zoom="-1" aria-label="Zoom out"${z<=.4?' disabled':''}>−</button><button type="button" data-zoom="fit">Fit</button><button type="button" data-zoom="1" aria-label="Zoom in"${z>=1?' disabled':''}>+</button><output aria-live="polite">${Math.round(z*100)}%</output></span></nav><p class="bkHint">Two sides. One champion. Later rounds show each slot’s likeliest team. First Four games are in their own tab. Scroll sideways with either scrollbar, or Fit to see it all at once. Select a school for its résumé.</p><div class="bkTopScroll" aria-hidden="true"><div style="width:${Math.ceil(width*z)}px"></div></div><div class="bkBracketFrame bkFullFrame" tabindex="0" role="region" aria-label="Full bracket, scroll horizontally"><div class="bkZoomBox" style="width:${Math.ceil(width*z)}px;height:${Math.ceil(height*z)}px"><div class="bkBracketColumns bkFullBoard" style="width:${width}px;height:${height}px;transform:scale(${z})">${finalPos?`<div class="bkFullTrophy" style="left:${finalPos.x}px;top:${Math.max(0,finalPos.y-190)}px">${championHead}</div>`:''}${games.map(g=>{const p=positions.get(g.id);return `<div class="bkFullPosition ${g===final?'bkFullFinal':''}" style="left:${p.x}px;top:${p.y}px">${gameCard(g,d,'mini',g===final?'Title game':'')}</div>`}).join('')}</div></div></div>`;
  }
  function connectBracket(host,d){
    const board=host.querySelector('.bkBracketColumns');if(!board)return;
    const bounds=board.getBoundingClientRect(),svg=document.createElementNS('http://www.w3.org/2000/svg','svg');
    // A zoomed board is scaled with a transform; draw in its unscaled units.
    const k=board.offsetWidth?bounds.width/board.offsetWidth:1;
    svg.setAttribute('class','bkConnections');svg.setAttribute('aria-hidden','true');svg.setAttribute('width',board.offsetWidth||bounds.width);svg.setAttribute('height',board.offsetHeight||bounds.height);
    const cards=new Map(Array.from(board.querySelectorAll('[data-game]')).map(el=>[el.dataset.game,el]));
    (state.conf?conferenceGames(d):d.bracket.games).forEach(g=>{
      const from=cards.get(g.id),to=cards.get(g.next_game);if(!from||!to)return;
      const a=from.getBoundingClientRect(),b=to.getBoundingClientRect(),x1=((a.left>b.left?a.left:a.right)-bounds.left)/k,x2=((a.left>b.left?b.right:b.left)-bounds.left)/k,y1=(a.top+a.height/2-bounds.top)/k,y2=(b.top+b.height/2-bounds.top)/k;
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
  function conferences(d){
    // Team keys are numeric strings, which JavaScript objects iterate in id
    // order regardless of the handoff's order, so sort by the odds explicitly.
    const ranked=c=>Object.entries(c.auto_bid_odds||{}).sort((a,b)=>(number(b[1])?b[1]:-1)-(number(a[1])?a[1]:-1));
    return `<p class="bkHint">Each conference champion gets an automatic bid. The percentage is each team’s chance to win its conference tournament, so a conference’s chances add up to 100%.</p><div class="bkConferenceGrid">${(d.conferences||[]).map(c=>`<section class="bkSupport"><h3>${h(c.conference)}</h3><p class="bkConferenceBids"><span><b>${value(c.projected_bids)}</b> projected bid${Number(c.projected_bids)===1?'':'s'}</span><span>Win tournament</span></p>${ranked(c).map(([key,p])=>`<div class="bkConferenceTeam">${teamButton(key)}<span>${odds(p)}</span></div>`).join('')}</section>`).join('')||'<p>Conference projections unavailable.</p>'}</div>`}
  function tournamentOdds(d){return table(['School',...d.odds_rounds.map(r=>h(r.label)),'Model alert'],d.field.map(f=>{const t=d.teams[f.team_key];return `<tr><th scope="row">${teamButton(f.team_key,`Seed ${h(f.seed)}`)}</th>${d.odds_rounds.map(r=>`<td>${odds(t.odds?.rounds?.[r.key])}</td>`).join('')}<td>${t.upset_alert?'⚑ Upset alert':'—'}</td></tr>`}))}
  function eliminated(d){return `<section class="bkSupport"><h3>Eliminated teams</h3>${(d.eliminated||[]).slice().sort((a,b)=>String(b.eliminated_on).localeCompare(String(a.eliminated_on))).map(t=>`<article class="bkEliminated">${teamButton(t.team_key)}<span>${h(t.eliminated_reason||'Reason unavailable')}</span><time>${h(t.eliminated_on||'Date unavailable')}</time></article>`).join('')||'<p class="bkHint">No eliminated teams supplied.</p>'}</section>`}
  function resume(key){
    const d=current(),t=d.teams[key];if(!t||expired())return;
    let dialog=document.getElementById('bk-resume');if(dialog)dialog.remove();
    dialog=document.createElement('dialog');dialog.id='bk-resume';dialog.className='bkResume';dialog.setAttribute('aria-labelledby','bk-resume-title');
    const f=d.field.find(f=>f.team_key===key),seedKeys=Array.from({length:d.max_seed},(_,i)=>String(i+1)).concat('out');
    const games=(label,rows)=>`<section><h3>${label}</h3>${rows?.length?`<ul class="bkResults">${rows.map(g=>`<li><b>${h(g.opponent||'Opponent unavailable')}</b><span>${h([g.site,g.date].filter(Boolean).join(' · '))}</span></li>`).join('')}</ul>`:'<p class="bkHint">None supplied.</p>'}</section>`;
    dialog.innerHTML=`<header><div>${teamMark(t.logo_key||t.team_name)}<h2 id="bk-resume-title">${h(t.team_name)}</h2></div><button type="button" data-close aria-label="Close résumé">×</button></header><div class="bkResumeBody">${d.mock?'<p class="bkMock">Design preview · Not a forecast</p>':''}<p class="bkHint">${h(t.conference)} · ${h(t.record||'Record unavailable')}${f?` · ${d.bracket.kind==='official'?'':'Projected '}seed ${h(f.seed)}`:''}</p>${status(t)}${movement(t.movement)}${['eliminated','tournament_eliminated'].includes(t.status)?`<p>${h(t.eliminated_reason||'Reason unavailable')} · ${h(t.eliminated_on||'Date unavailable')}</p>`:''}<div class="bkRatingPair"><section><span>Who is best ${help('power rating','Opponent-adjusted, tempo-free team strength supplied by the engine. It is separate from tournament selection.')}</span><strong>${value(t.power_rating)}</strong><b>Power rating</b></section><section><span>Who earned a spot ${help('résumé rank','The model’s résumé measure of results earned. This is not the NCAA NET.')}</span><strong>${t.resume_rank!=null?'#'+value(t.resume_rank):'Unavailable'}</strong><b>Résumé rank</b></section></div><div class="bkQuadGrid">${['Q1','Q2','Q3','Q4'].map(q=>`<div><span>${q}</span><b>${record(t.quadrants?.[q])}</b></div>`).join('')}</div><dl class="bkStats"><div><dt>Strength of schedule</dt><dd>${t.sos_rank!=null?'#'+value(t.sos_rank):'Unavailable'}</dd></div><div><dt>Strength of record</dt><dd>${t.sor_rank!=null?'#'+value(t.sor_rank):'Unavailable'}</dd></div><div><dt>Make field</dt><dd>${odds(t.odds?.make_field)}</dd></div><div><dt>Auto bid</dt><dd>${odds(t.odds?.auto_bid)}</dd></div></dl><section><h3>Seed odds ${help('seed odds','Each bar is the supplied chance of that seed, including missing the field. Unavailable values are not zero.')}</h3><div class="bkSeedChart">${seedKeys.map(seed=>{const p=t.odds?.seed?.[seed];return `<div><span>${seed==='out'?'Out':seed}</span><span class="bkBar" aria-hidden="true"><i style="width:${number(p)?p*100:0}%"></i></span><b>${odds(p)}</b></div>`}).join('')}</div></section><section><h3>Tournament odds</h3><dl class="bkRoundOdds">${d.odds_rounds.map(r=>`<div><dt>${h(r.label)}</dt><dd>${odds(t.odds?.rounds?.[r.key])}</dd></div>`).join('')}</dl></section>${games('Best wins',t.best_wins)}${games('Worst losses',t.bad_losses)}</div>`;
    document.body.append(dialog);dialog.querySelector('[data-close]').onclick=()=>dialog.close();dialog.addEventListener('close',()=>{dialog.remove();if(state.opener?.isConnected)state.opener.focus()});dialog.showModal();
  }
  function draw(host){
    if(!host.isConnected)return;
    state.observer?.disconnect();
    const d=current();
    if(!d||expired()){
      host.innerHTML=`<section class="bkShell"><header class="bkHeader"><div><span class="bkEyebrow">Men’s college basketball</span><h2>Bracketology</h2></div></header><div class="bkUnavailable" role="status"><h3>${expired()?'Bracketology update overdue':'Bracketology unavailable'}</h3><p>${expired()?`The last handoff was updated ${h(new Date(state.data.as_of).toLocaleString())}. A fresh projection has not arrived.`:h(state.error||'Waiting for the engine’s bracketology update.')}</p><button type="button" data-retry>Check for update</button></div></section>`;
      host.querySelector('[data-retry]').onclick=()=>load(host,true);return;
    }
    if(!d.regions.includes(state.region))state.region=d.regions[0]??null;
    const tabs=[['bracket','Bracketology'],['bubble','Bubble'],['seeds','Seed list'],['conferences','Conferences'],['odds','Tournament odds'],['eliminated','Eliminated']];
    const body={bracket,bubble,seeds:seedList,conferences,odds:tournamentOdds,eliminated};
    host.innerHTML=`<section class="bkShell">${d.mock?'<div class="bkMock" role="status">DESIGN PREVIEW · Illustrative data · Not a forecast</div>':''}<header class="bkHeader"><div><span class="bkEyebrow">Men’s college basketball · ${h(d.season)}</span><h2>Bracketology</h2></div><div class="bkBadges"><span>${h(state.compare?'Final projection':d.power_basis?.basis==='preseason'?'Preseason projection':phaseNames[d.phase])}</span></div></header><div class="bkAsOf"><span>Updated ${h(new Date(d.as_of).toLocaleString())}</span>${d.power_basis?.basis==='preseason'?`<span class="bkBasis"><b>Preseason projection.</b> Team strength comes from the preseason ratings (last season plus roster changes). It switches to this season’s results alone once teams have played about ${h(d.power_basis.switch_at_games||10)} games${number(d.power_basis.median_games)?` (now ${h(d.power_basis.median_games)})`:''}.</span>`:d.power_basis?.basis==='season'?'<span class="bkBasis">Team strength from this season’s results only.</span>':''}${d.phase==='early'?'<span>Early-season uncertainty · Explore each team’s seed odds</span>':''}${d.final_projection?`<button type="button" data-compare>${state.compare?'View official bracket':'Compare final projection'}</button>`:state.compare?'<button type="button" data-compare>View official bracket</button>':''}</div><nav class="bkTabs" aria-label="Bracketology views">${tabs.map(([key,label])=>`<button type="button" data-tab="${key}" aria-pressed="${state.tab===key}">${label}</button>`).join('')}</nav><div class="bkContent">${body[state.tab](d)}</div><p class="bkSource">Selections, résumé measures and odds supplied by the engine.${d.odds_basis==='unconditional_season'?' Odds include the chance of reaching the field.':d.odds_basis==='conditional_on_field'?' Tournament odds assume a place in the field.':''}</p></section>`;
    if(state.tab==='bracket')requestAnimationFrame(()=>{const board=host.querySelector('.bkBracketColumns');if(!board)return;
connectBracket(host,d);if(typeof ResizeObserver!=='undefined'){state.observer=new ResizeObserver(()=>{board.querySelector('.bkConnections')?.remove();connectBracket(host,d)});state.observer.observe(board)}});
    const topScroll=host.querySelector('.bkTopScroll'),fullFrame=host.querySelector('.bkFullFrame');
    if(topScroll&&fullFrame){topScroll.onscroll=()=>{if(fullFrame.scrollLeft!==topScroll.scrollLeft)fullFrame.scrollLeft=topScroll.scrollLeft};fullFrame.onscroll=()=>{if(topScroll.scrollLeft!==fullFrame.scrollLeft)topScroll.scrollLeft=fullFrame.scrollLeft}}
    host.onchange=event=>{const select=event.target.closest('[data-which]');if(!select)return;state.conf=select.value;state.full=false;draw(host);host.querySelector('[data-which]')?.focus()};
    host.onclick=event=>{
      if(expired()){document.getElementById('bk-resume')?.close();draw(host);return}
      const button=event.target.closest('button');if(!button)return;
      if(button.dataset.team){state.opener=button;resume(button.dataset.team)}
      else if(button.dataset.tab){state.tab=button.dataset.tab;draw(host);host.querySelector(`[data-tab="${state.tab}"]`)?.focus()}
      else if(button.hasAttribute('data-full')){state.full=button.dataset.full==='true';draw(host);host.querySelector(`[data-full="${state.full}"]`)?.focus()}
      else if(button.hasAttribute('data-zoom')){
        const frame=host.querySelector('.bkBracketFrame'),board=host.querySelector('.bkFullBoard');
        state.zoom=button.dataset.zoom==='fit'&&frame&&board?Math.max(.4,Math.min(1,(frame.clientWidth-8)/board.offsetWidth)):Math.max(.4,Math.min(1,Math.round(((state.zoom??1)+Number(button.dataset.zoom)*.15)*100)/100));
        draw(host);host.querySelector(`[data-zoom="${button.dataset.zoom}"]`)?.focus()}
      else if(button.hasAttribute('data-scroll')){const frame=host.querySelector('.bkBracketFrame');frame.scrollBy({left:Number(button.dataset.scroll)*frame.clientWidth*.75,behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth'})}
      else if(button.hasAttribute('data-region')){state.region=button.dataset.region||null;draw(host);Array.from(host.querySelectorAll('[data-region]')).find(b=>b.dataset.region===state.region)?.focus()}
      else if(button.hasAttribute('data-compare')){state.compare=!state.compare;draw(host);host.querySelector('[data-compare]')?.focus()}
    };
  }
  async function loadData(force=false){
    if(state.pending)return state.pending;
    if(!force&&state.loaded&&Date.now()-state.loaded<60000)return state.data;
    state.pending=(async()=>{
      const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),12000);
      try{
        const url=preview()?'docs/fixtures/bracketology_ncaam.mock.json':'bracketology_ncaam.json';
        const response=await fetch(url,{cache:'no-store',signal:controller.signal});
        if(!response.ok)throw Error(response.status===404?'The engine’s bracketology update has not arrived yet.':'The bracketology handoff could not be loaded.');
        const data=validate(await response.json(),preview());
        if(data.competition!=='NCAAM'||(!preview()&&data.season!==currentBasketballSeason()))throw Error('A projection for the current basketball season has not been published yet.');
        if(data.final_projection)validate(data.final_projection,preview());
        state.data=data;state.error='';state.compare=false;
      }catch(error){state.data=null;state.error=error.name==='AbortError'?'The bracketology handoff timed out. Please try again.':error.message}
      finally{clearTimeout(timer);state.loaded=Date.now();state.pending=null}
      return state.data;
    })();return state.pending;
  }
  async function load(host,force=false){
    // The bracket handoff carries its own publication and freshness state.
    // Power Ratings may still reflect preseason when a projection is available.
    if(force||!state.loaded||Date.now()-state.loaded>=60000)host.innerHTML='<div class="bkUnavailable" role="status">Loading bracketology…</div>';
    await loadData(force);
    if(DATA.comp_key!=='NCAAM')return;
    clearTimeout(state.staleTimer);
    const delay=Date.parse(state.data?.valid_until)-Date.now();
    if(delay>0&&delay<2147483647)state.staleTimer=setTimeout(()=>{document.getElementById('bk-resume')?.close();if(DATA.comp_key==='NCAAM')draw(host)},delay+10);
    draw(host);
  }
  async function projectedTopSeeds(){
    const data=await loadData();
    if(data?.competition!=='NCAAM'||data.bracket.kind!=='projected'||expired())return [];
    const seeds=data.field.filter(team=>team.seed===1&&!team.first_four&&team.region&&team.team_name);
    if(seeds.length!==4||new Set(seeds.map(team=>team.region)).size!==4)return [];
    const sorted=seeds.sort((a,b)=>a.overall_seed-b.overall_seed);
    sorted.basis=data.power_basis?.basis||null;
    return sorted;
  }
  return {render:load,validate,formatOdds:odds,projectedTopSeeds};
})();
