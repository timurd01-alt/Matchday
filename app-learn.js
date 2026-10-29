/* Learn: in-depth lessons on the numbers the rest of the site shows.

   The page is a topic-led library of lesson cards. A card opens the lesson in its own window: several short
   sections, a chart drawn from the same live data, and links into the part of
   the site the lesson explains. Every figure comes from data the site already
   publishes; a missing feed leaves its chart out rather than inventing one. */
(function(){
  const g=n=>{try{return (typeof window[n]!=='undefined'&&window[n])||eval(n)}catch(e){return null}};
  const cfb=()=>g('MATCHDAY_CFB_RANKINGS')?.rankings||[];
  const hoopsTeams=()=>g('MATCHDAY_TRDLAB_NCAAM_PROFILES')?.teams||{};
  const picks=()=>(g('MATCHDAY_TRDLAB_PICKS')||[]).filter(p=>p.sport==='ncaaf'&&p.model_pct!=null&&Date.parse(p.kickoff||'')>Date.now());
  const card=()=>g('MATCHDAY_TRDLAB_SCORECARD')?.sports?.ncaaf||null;
  const results=()=>(g('MATCHDAY_TRDLAB_RESULTS')||[]).filter(r=>r.play_metrics&&r.play_metrics.home&&r.play_metrics.away&&r.sport==='ncaaf');
  const short=n=>typeof rsShortName==='function'?rsShortName(n):String(n||'');
  const mark=n=>typeof teamMark==='function'?teamMark(n):'';
  const f1=v=>Number(v).toFixed(1);

  const bars=(rows,{max,fmt=f1,tone='signal'}={})=>{
    const top=max??Math.max(...rows.map(r=>Math.abs(r.value)),1);
    return `<div class="lnBars">${rows.map(r=>`<div class="lnBar"><span class="lnBarName">${r.team?mark(r.team):''}<span>${esc(r.label)}</span></span>`
      +`<i><b class="lnTone-${r.tone||tone}" style="width:${Math.max(3,Math.min(100,Math.abs(r.value)/top*100)).toFixed(1)}%"></b></i>`
      +`<em>${fmt(r.value)}</em></div>`).join('')}</div>`;
  };
  const stat=(big,label)=>`<div class="lnStat"><b>${big}</b><span>${esc(label)}</span></div>`;
  const go=(view,label)=>`<button type="button" class="lnGo" onclick="window.__learnClose();setView('${view}')">${esc(label)} <span aria-hidden="true">→</span></button>`;

  const LESSONS=[
    {id:'rating',title:'What a rating is',hook:'One number for how good a team is, and what it is not.',
     figure:()=>{const r=cfb()[0];return r?{big:f1(r.rating),cap:short(r.name)}:null},
     sections:()=>{const top=cfb().slice(0,10),a=top[0],b=cfb()[24];return [
      ['The idea','A rating is how many points a team is better than an average FBS team, on a neutral field. A team rated +20 would be expected to beat an average opponent by about 20. It is built from every game the team has played, with each result adjusted for how strong the opponent was.'],
      ['The top of the board right now',top.length?bars(top.map(t=>({label:short(t.name),team:t.name,value:t.rating}))):''],
      ['Reading two ratings together',a&&b?`Subtract one rating from another to get the expected margin on a neutral field. ${esc(short(a.name))} (${f1(a.rating)}) against ${esc(short(b.name))} (${f1(b.rating)}) works out to about ${f1(a.rating-b.rating)} points. Add roughly three points for the home team.`:'Subtract one rating from another to get the expected margin on a neutral field, then add roughly three points for the home team.'],
      ['What it is not','A rating is not a ranking of résumés. A team can rate highly after a narrow loss to a great opponent, and lower after a sloppy win over a weak one. It answers one question: how good is this team now?'],
      ['',go('groups','Open the ratings')]]}},
    {id:'sos',title:'Strength of schedule',hook:'Why a 5-0 team can rank below a 4-1 team.',
     figure:()=>{const r=[...cfb()].filter(x=>x.sos!=null).sort((x,y)=>y.sos-x.sos)[0];return r?{big:f1(r.sos),cap:`${short(r.name)}'s schedule`}:null},
     sections:()=>{const rs=cfb().filter(x=>x.sos!=null),hard=[...rs].sort((x,y)=>y.sos-x.sos).slice(0,5),easy=[...rs].sort((x,y)=>x.sos-y.sos).slice(0,5);return [
      ['The idea','Strength of schedule is the average rating of the opponents a team has played. It is why records alone mislead: going 5-0 against weak teams proves less than going 4-1 against strong ones.'],
      ['Toughest schedules so far',hard.length?bars(hard.map(t=>({label:short(t.name),team:t.name,value:t.sos}))):''],
      ['Easiest schedules so far',easy.length?bars(easy.map(t=>({label:short(t.name),team:t.name,value:t.sos,tone:'muted'}))):''],
      ['How the rating uses it','The rating does not add schedule strength on top; it is already inside. Every result is measured against what an average team would have done against the same opponent, so beating a strong team counts for more and losing to one costs less.'],
      ['',go('news','See Rating vs Schedule on Research')]]}},
    {id:'probability',title:'Win probability',hook:'70% means the favorite loses three times in ten.',
     figure:()=>{const sc=card();return sc?.record?{big:`${Math.round(sc.record.hit_rate_pct)}%`,cap:'of picks won'}:null},
     sections:()=>{const p=picks().find(x=>x.model_pct>=65&&x.model_pct<=80),pct=p?Number(p.model_pct):70,won=Math.round(pct/10);
      const dots=Array.from({length:10},(_,i)=>`<i class="${i<won?'win':'loss'}"></i>`).join(''),bands=card()?.by_confidence||[];return [
      ['The idea','A win probability is how often a team would win if the same game were played many times. It is not a promise that the favorite wins; it says how often it should.'],
      [p?`${short(p.pick_name)} at ${f1(pct)}%, ten times`:'A 70% favorite, ten times',`<div class="lnDots">${dots}</div><p class="lnNote">Played ten times, a ${Math.round(pct)}% favorite loses about ${10-won} of them. When one of those losses happens, the model was not wrong.</p>`],
      ['Did the model mean what it said?',bands.length?`<div class="lnCal">${bands.map(b=>`<div><span>${esc(b.band)}</span><i><b style="width:${b.hit_rate_pct}%"></b><s style="left:${b.expected_hit_rate_pct}%"></s></i><em>${Math.round(b.hit_rate_pct)}%</em></div>`).join('')}</div><p class="lnNote">Each bar is how often picks in that confidence band won; the tick is what the model said. Bars that end near their ticks mean the probabilities can be taken at face value. This is called calibration.</p>`:''],
      ['',go('score','Open the Scorecard')]]}},
    {id:'market',title:'Model vs market',hook:'The betting market is the toughest benchmark there is.',
     figure:()=>{const v=card()?.versus_market?.disagreed_with_market;return v?{big:`${v.wins}–${v.losses}`,cap:'against the market'}:null},
     sections:()=>{const vm=card()?.versus_market||{},rows=[['Agreed with the market',vm.agreed_with_market,'win'],['Disagreed with the market',vm.disagreed_with_market,'muted']].filter(([,b])=>b&&b.picks);return [
      ['The idea','Sportsbook prices, with the bookmaker\'s margin taken out, are the market\'s own win probabilities. A lot of money and information goes into them, so they are very hard to beat. Matchday compares against them as a test of the model, not as betting advice.'],
      ['The record so far',rows.length?bars(rows.map(([l,b,t])=>({label:`${l} · ${b.wins}–${b.losses}`,value:b.hit_rate_pct,tone:t})),{max:100,fmt:v=>`${Math.round(v)}%`}):''],
      ['How to read a disagreement','When the model and the market agree, the model mostly inherits the market\'s record: favorites win. The interesting games are the disagreements, and so far they have gone worse than the agreements. That is why Matchday shows them as games to watch and grade, not as tips.'],
      ['',go('news','See Model–market watch')]]}},
    {id:'efficiency',title:'Football efficiency',hook:'EPA and success rate: who actually played better.',
     figure:()=>{const r=results()[0];if(!r)return null;const v=Number(r.play_metrics.home.epa_per_play);return {big:`${v>=0?'+':''}${v.toFixed(2)}`,cap:`${short(r.home)}, EPA per play`}},
     sections:()=>{const all=results(),r=all.find(x=>Math.sign(x.home_score-x.away_score)!==Math.sign(x.play_metrics.home.epa_per_play-x.play_metrics.away.epa_per_play))||all[0];let ex='';
      if(r){const h=r.play_metrics.home,a=r.play_metrics.away,flip=Math.sign(r.home_score-r.away_score)!==Math.sign(h.epa_per_play-a.epa_per_play);
       ex=bars([{label:short(r.home),team:r.home,value:h.epa_per_play*100},{label:short(r.away),team:r.away,value:a.epa_per_play*100,tone:'muted'}],{fmt:v=>(v>=0?'+':'')+(v/100).toFixed(2)})
        +`<p class="lnNote">${esc(short(r.home))} ${r.home_score}, ${esc(short(r.away))} ${r.away_score}. ${flip?'The more efficient team lost: turnovers and short fields can swing a game against the run of play.':'The more efficient team also won.'}</p>`}
      return [
      ['Expected points added','Every snap starts with an expected number of points, based on down, distance and field position. EPA is how much a play changed that number. A 10-yard gain on 3rd and 5 is worth much more than the same 10 yards on 3rd and 15.'],
      ['Success rate','A simpler measure: the share of plays that kept the offense on schedule. That means gaining about half the yards needed on first down, 70% on second, and all of them on third or fourth.'],
      [r?'Expected points per play in a recent game':'',ex],
      ['',go('results','Open any result for How it played')]]}},
    {id:'basketball',title:'Basketball is different',hook:'Tempo, efficiency and why one game says little.',
     figure:()=>{const t=Object.entries(hoopsTeams()).filter(([,v])=>v.tempo&&v.games>=20).sort((a,b)=>b[1].tempo-a[1].tempo)[0];return t?{big:f1(t[1].tempo),cap:`${short(t[0])} tempo`}:null},
     sections:()=>{const all=Object.entries(hoopsTeams()).filter(([,v])=>v.tempo&&v.games>=20),fast=[...all].sort((a,b)=>b[1].tempo-a[1].tempo).slice(0,4),slow=[...all].sort((a,b)=>a[1].tempo-b[1].tempo).slice(0,4);return [
      ['Possessions, not points','Basketball teams play very different numbers of possessions, so points per game reward fast teams and punish slow ones. Ratings use efficiency instead: points scored and allowed per 100 possessions, adjusted for the opponent.'],
      ['Fastest and slowest teams',all.length?bars([...fast.map(([n,v])=>({label:short(n),team:n,value:v.tempo})),...slow.map(([n,v])=>({label:short(n),team:n,value:v.tempo,tone:'muted'}))],{max:Math.max(...all.map(([,v])=>v.tempo))}):''],
      ['The four factors','Most of a team\'s efficiency comes from four things: shooting (effective field-goal percentage), protecting the ball (turnover rate), second chances (offensive rebounding) and getting to the line (free-throw rate). Open any basketball game to see all four, for and against.'],
      ['One game says little','A season is about thirty games and shooting swings a lot from night to night, so one result moves a basketball rating far less than one football result does.']]}},
    {id:'preseason',title:'Preseason ratings',hook:'The shakiest numbers on the site, and how they are built.',
     figure:()=>{const r=g('MATCHDAY_NCAAM_RANKINGS')?.rankings?.[0];return r?{big:f1(r.rating),cap:short(r.name)}:null},
     sections:()=>{const top=(g('MATCHDAY_NCAAM_RANKINGS')?.rankings||[]).slice(0,8);return [
      ['Where it starts','Before a game is played, a team starts from last season\'s rating, pulled part of the way back toward average because rosters change.'],
      ['What moves it','Then the roster: the minutes and production that return, the transfers who arrive and how good their old teams were, the players who left for the NBA, the incoming recruiting class, and whether the team changed head coach. Each piece is weighted by how much it mattered in past seasons.'],
      ['The basketball preseason top eight',top.length?bars(top.map(t=>({label:short(t.name),team:t.name,value:t.rating}))):''],
      ['Why it fades','A preseason rating counts for about five games\' worth of evidence. By December the season\'s own results outweigh it, and by conference play it barely matters.']]}},
    {id:'scorecard',title:'Reading the scorecard',hook:'Locked an hour before kickoff, graded after, never rewritten.',
     figure:()=>{const sc=card();return sc?.record?{big:`${sc.record.wins}–${sc.record.losses}`,cap:'season record'}:null},
     sections:()=>{const sc=card();return [
      ['Locked, then graded','Every pick freezes an hour before kickoff, with the market price as it stood at that moment, and is graded once the game is final. A locked pick is never edited, so the record cannot be improved after the fact.'],
      ['The season so far',sc?.record?`<div class="lnStats">${stat(`${sc.record.wins}–${sc.record.losses}`,'record')}${stat(`${Math.round(sc.record.hit_rate_pct)}%`,'won')}${stat(`${Math.round(sc.record.expected_hit_rate_pct)}%`,'the model expected')}</div>`:''],
      ['Why the record alone misleads','Picking every favorite wins most college football games, so a strong record is the minimum, not the proof. The better questions: did picks win about as often as the model said, and how did the model do when it disagreed with the market?'],
      ['',go('score','Open the Scorecard')]]}}
  ];

  const GLOSSARY=[
    ['Rating','Points better than an average FBS team on a neutral field, schedule-adjusted.'],
    ['Strength of schedule','The average rating of the opponents a team has played.'],
    ['Adjusted offense / defense','Points a team would score / allow against an average opponent.'],
    ['Win probability','How often a team would win the same game played many times.'],
    ['Calibration','Whether picks at a given probability won about that often.'],
    ['Market','The sportsbook price with its margin removed, read as a win probability.'],
    ['Projected score','The most likely final score from many simulated games.'],
    ['EPA per play','Expected points added per play: how much each play changed the expected score.'],
    ['Success rate','Share of plays that kept the offense on schedule.'],
    ['Efficiency','Basketball points scored or allowed per 100 possessions.'],
    ['Tempo','Basketball possessions per game.'],
    ['Four factors','Shooting, turnovers, offensive rebounding and free throws: what basketball efficiency is made of.'],
    ['Preseason rating','A team\'s starting rating before games, from last season and its roster changes.'],
    ['FCS','The football division below FBS; games against FCS opponents are not graded.'],
  ];

  let OPEN=null,lastFocus=null;
  function lessonHTML(l){
    const i=LESSONS.indexOf(l),prev=LESSONS[i-1],next=LESSONS[i+1];
    const body=(()=>{try{return l.sections()}catch(e){return []}})().filter(([,h])=>h)
      .map(([t,h])=>`<section class="lnSection">${t?`<h3>${esc(t)}</h3>`:''}${/^\s*</.test(h)?h:`<p>${h}</p>`}</section>`).join('');
    const nav=`<nav class="lnNav">${prev?`<button type="button" onclick="window.__learnOpen('${prev.id}')"><span aria-hidden="true">←</span> ${esc(prev.title)}</button>`:'<span></span>'}${next?`<button type="button" onclick="window.__learnOpen('${next.id}')">${esc(next.title)} <span aria-hidden="true">→</span></button>`:''}</nav>`;
    return `<div class="lnSheet" role="dialog" aria-modal="true" aria-labelledby="lnTitle"><header class="lnHead"><div><span class="lnCount">Matchday field guide</span><h2 id="lnTitle">${esc(l.title)}</h2><p>${esc(l.hook)}</p></div><button type="button" class="lnClose" aria-label="Close lesson" onclick="window.__learnClose()">×</button></header><div class="lnBody">${body}${nav}</div></div>`;
  }
  window.__learnOpen=id=>{
    const l=LESSONS.find(x=>x.id===id);if(!l)return;
    let host=document.getElementById('learnModal');
    if(!host){host=document.createElement('div');host.id='learnModal';host.className='lnModal';
      host.addEventListener('click',e=>{if(e.target===host)window.__learnClose()});
      document.addEventListener('keydown',e=>{if(e.key==='Escape'&&OPEN)window.__learnClose()});
      document.body.appendChild(host)}
    if(!OPEN)lastFocus=document.activeElement;
    OPEN=id;host.innerHTML=lessonHTML(l);host.classList.add('show');host.scrollTop=0;
    host.querySelector('.lnClose')?.focus();
  };
  window.__learnClose=()=>{const host=document.getElementById('learnModal');if(host)host.classList.remove('show');OPEN=null;lastFocus?.focus?.()};
  window.openLesson=id=>{setView('learn');window.__learnOpen(id)};

  window.renderLearn=function(){
    const host=document.getElementById('view-learn');if(!host)return;
    const topics={rating:['Ratings','How team strength is measured.'],sos:['Schedule','Why the opponents matter as much as the record.'],probability:['Probability','What a win chance tells you—and what it cannot.'],market:['Market','How the model compares with sportsbook expectations.'],efficiency:['Football','Understand EPA, success rate and the story behind the score.'],basketball:['Basketball','Read the game through possessions, tempo and efficiency.'],preseason:['Preseason','Where the starting ratings come from, and why they change.'],scorecard:['Results','Follow every locked pick through to its final result.']};
    const icons={rating:'M5 19V13M12 19V8M19 19V4',sos:'M4 18l5-5 4 2 7-10M15 5h5v5',probability:'M12 3a9 9 0 1 0 9 9h-9V3Zm4 0v5h5',market:'M4 8h16M4 16h16M7 5 4 8l3 3M17 13l3 3-3 3',efficiency:'M4 17C4 8 8 4 20 4c0 12-4 16-16 16v-3Zm5-2 6-6M9 10l5 5M12 7l5 5',basketball:'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18ZM3 12h18M12 3v18M6 5c6 5 6 9 0 14M18 5c-6 5-6 9 0 14',preseason:'M5 5h14v16H5V5Zm3-2v4m8-4v4M5 10h14M9 15h6',scorecard:'M5 3h14v18H5V3Zm3 5 2 2 5-5M8 14h8M8 17h5'};
    const cards=LESSONS.map(l=>{
      const [category,description]=topics[l.id];
      return `<button type="button" class="lnCard" onclick="window.__learnOpen('${l.id}')"><span class="lnTopic"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="${icons[l.id]}"/></svg>${category}</span><strong>${esc(l.title)}</strong><span class="lnDescription">${esc(description)}</span><span class="lnRead">Explore topic <span aria-hidden="true">↗</span></span></button>`;
    }).join('');
    const terms=GLOSSARY.map(([t,d])=>`<div data-term="${esc((t+' '+d).toLowerCase())}"><dt>${esc(t)}</dt><dd>${esc(d)}</dd></div>`).join('');
    host.innerHTML=`<div class="lnIntro"><span class="lnEyebrow">THE MATCHDAY FIELD GUIDE</span><h1>Know what you’re looking at.</h1><p>The ratings, the probabilities, the record. Understand the numbers behind the game.</p></div>
      <div class="lnGrid">${cards}</div>
      <div class="lnGlossary"><input type="search" class="lnSearch" placeholder="Search the glossary" aria-label="Search the glossary" oninput="window.__learnFilter(this.value)"><dl class="learnGlossary">${terms}</dl></div>`;
  };
  window.__learnFilter=q=>{q=String(q||'').toLowerCase().trim();document.querySelectorAll('#view-learn .learnGlossary>div').forEach(d=>{d.hidden=!!q&&!d.dataset.term.includes(q)})};
})();
