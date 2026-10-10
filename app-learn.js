/* Learn: short lessons on the numbers the rest of the site shows.

   Each lesson is a toggle (title + one-line hook, body on open), so the page
   reads as a list rather than a wall of copy. Where the data allows, a lesson
   carries a live example from this week's board; every example has a
   fallback, so a missing feed never leaves a lesson broken or empty. */
(function(){
  const rankings=()=>((typeof MATCHDAY_CFB_RANKINGS!=='undefined'&&MATCHDAY_CFB_RANKINGS?.rankings)||[]);
  const picks=()=>((typeof MATCHDAY_BETBETTER_PICKS!=='undefined'&&MATCHDAY_BETBETTER_PICKS)||[])
    .filter(p=>p.sport==='ncaaf'&&p.model_pct!=null&&String(p.kickoff||'')>=new Date().toISOString().slice(0,10));
  const num=(v,d=1)=>Number(v).toFixed(d);
  const short=name=>String(name||'').split(' ').slice(0,-1).join(' ')||String(name||'');

  function ratingExample(){
    const r=rankings();if(r.length<2)return '';
    const a=r[0],b=r[Math.min(24,r.length-1)];
    return `This week ${esc(short(a.team_name||a.name))} is rated <b>${num(a.rating)}</b> and ${esc(short(b.team_name||b.name))} (#${b.rank}) <b>${num(b.rating)}</b>. On a neutral field the model would expect about a ${num(a.rating-b.rating)}-point game between them.`;
  }
  function sosExample(){
    const r=rankings().filter(x=>x.sos!=null);if(r.length<10)return '';
    const hard=[...r].sort((x,y)=>y.sos-x.sos)[0],easy=[...r].sort((x,y)=>x.sos-y.sos)[0];
    return `Right now ${esc(short(hard.team_name||hard.name))} has the toughest schedule among rated teams (SoS <b>${num(hard.sos,2)}</b>) and ${esc(short(easy.team_name||easy.name))} the easiest (<b>${num(easy.sos,2)}</b>).`;
  }
  function probabilityExample(){
    const p=picks().filter(x=>x.model_pct>=65&&x.model_pct<=80)[0];if(!p)return '';
    const pct=Number(p.model_pct);
    return `${esc(short(p.pick_name))} is <b>${num(pct)}%</b> to win this week. If games like this were played ten times, they would lose about ${Math.round((100-pct)/10)} of them, and the model would still be right.`;
  }
  function marketExample(){
    const p=picks().filter(x=>x.market_pct!=null).sort((x,y)=>Math.abs(y.model_pct-y.market_pct)-Math.abs(x.model_pct-x.market_pct))[0];if(!p)return '';
    return `The biggest gap this week: the model gives ${esc(short(p.pick_name))} <b>${num(p.model_pct)}%</b>, the market <b>${num(p.market_pct)}%</b>. A gap is a question, not a tip; the record decides who was closer.`;
  }

  const LESSONS=[
    {id:'rating',title:'What a rating is',hook:'One number for how good a team is.',body:()=>`
      <p>A rating is how many points better a team is than an average FBS team, on a neutral field, after adjusting for who it played. A team rated 20 would be expected to beat an average team by about 20.</p>
      <p>Subtract two ratings to get the expected margin between two teams, then add a few points for the home side.</p>`,example:ratingExample,link:['groups','See the ratings']},
    {id:'sos',title:'Strength of schedule',hook:'Why 5-0 can rank below 4-1.',body:()=>`
      <p>Strength of schedule (SoS) is the average rating of the teams a team has played. Beating five weak teams says less than beating four good ones, so the rating discounts easy wins and credits hard losses.</p>
      <p>Teams that have mostly played FCS opponents are left out of the Top 25 until they have enough games against FBS teams to judge.</p>`,example:sosExample,link:['groups','See SoS beside each rating']},
    {id:'probability',title:'Win probability is not a promise',hook:'70% means the favorite loses 3 times in 10.',body:()=>`
      <p>A win probability is how often a team would win if the same game were played many times. A 70% favorite losing is not the model being wrong; it is the 30% happening.</p>
      <p>A model is judged on calibration: across all its 70% picks, did about 70% win?</p>`,example:probabilityExample,link:['score','See how the picks graded']},
    {id:'market',title:'Model vs market',hook:'Betting lines are the toughest benchmark there is.',body:()=>`
      <p>Sportsbook prices, with their margin removed, are the market's own win probabilities, and they are very hard to beat. Matchday compares its numbers against them as a forecasting test. It is research, not betting advice.</p>
      <p>The fairest test is the closing line, the last price before kickoff. A model whose numbers the line keeps moving toward is seeing something real.</p>`,example:marketExample,link:['matches','See model and market side by side']},
    {id:'efficiency',title:'Football efficiency stats',hook:'EPA and success rate, the numbers behind the profile.',body:()=>`
      <p><b>EPA per play</b> (expected points added) measures how much each play changed a team's expected score. A 10-yard gain on 3rd and 5 is worth more than the same gain on 3rd and 15.</p>
      <p><b>Success rate</b> is the share of plays that kept an offense on schedule: about half the yards needed on first down, 70% on second, all of them on third or fourth.</p>
      <p>Both are adjusted for the opponent in the team profile, so a good defense is not mistaken for a bad offense.</p>`,example:()=>'',link:['matches','Open any game for its profile']},
    {id:'basketball',title:'Basketball is different',hook:'Tempo, efficiency and why one game says little.',body:()=>`
      <p>Basketball teams play different numbers of possessions, so points per game mislead. Ratings use <b>efficiency</b>: points scored and allowed per 100 possessions, adjusted for opponent. <b>Tempo</b> is possessions per game.</p>
      <p>With about 30 games a season and big swings in shooting, one result moves a rating far less than one football game does.</p>`,example:()=>'',link:null},
    {id:'preseason',title:'Preseason guesses',hook:'The shakiest number on the site, and why.',body:()=>`
      <p>Before games are played, a rating starts from last season and adjusts for the roster: minutes and production returning, transfers in and out, players drafted, and the incoming recruiting class.</p>
      <p>It misses players who leave quietly and freshmen who outplay their ranking. Real results take over within a few weeks.</p>`,example:()=>'',link:['groups','See the preseason rankings']},
    {id:'scorecard',title:'How to read the scorecard',hook:'Locked, graded, never rewritten.',body:()=>`
      <p>Each pick locks before kickoff and is graded once the game is final. Locked picks are never edited, so the record cannot be improved after the fact.</p>
      <p>A hit rate alone misleads: picking every favorite wins most games. Look at how the model did when it disagreed with the market, and at calibration.</p>`,example:()=>'',link:['score','Open the scorecard']},
  ];

  const GLOSSARY=[
    ['Rating','Points better than an average FBS team on a neutral field, schedule-adjusted.'],
    ['SoS','Strength of schedule: the average rating of the opponents played.'],
    ['Adjusted offense / defense','Points a team would score / allow against an average opponent.'],
    ['Win probability','How often a team would win the same game played many times.'],
    ['Market','The sportsbook price with its margin removed, read as a win probability.'],
    ['Closing line','The last market price before kickoff; the hardest number to beat.'],
    ['Projected score','The most likely final score from many simulated games.'],
    ['EPA / play','Expected points added per play: how much each play changed the expected score.'],
    ['Success rate','Share of plays that kept the offense on schedule.'],
    ['Efficiency','Basketball points scored or allowed per 100 possessions.'],
    ['Tempo','Basketball possessions per game.'],
    ['Calibration','Whether picks at a given probability won about that often.'],
    ['FCS','The division below FBS; games against FCS teams count for less.'],
  ];

  let OPEN=null;
  window.renderLearn=function(){
    const host=document.getElementById('view-learn');if(!host)return;
    const lesson=l=>{
      const ex=(()=>{try{return l.example()}catch(e){return ''}})();
      const go=l.link?`<button type="button" class="learnLink" onclick="setView('${l.link[0]}')">${esc(l.link[1])} <span aria-hidden="true">→</span></button>`:'';
      return `<details class="learnLesson" id="learn-${l.id}" ${OPEN===l.id?'open':''} ontoggle="if(this.open)window.__learnOpen('${l.id}')">
        <summary><span class="learnTitle">${esc(l.title)}</span><span class="learnHook">${esc(l.hook)}</span></summary>
        <div class="learnBody">${l.body()}${ex?`<div class="learnExample"><span class="seclbl">This week</span><p>${ex}</p></div>`:''}${go}</div>
      </details>`;
    };
    host.innerHTML=`<div class="vhead">Learn</div>
      <div class="seclbl">Lessons</div>
      <div class="learnList">${LESSONS.map(lesson).join('')}</div>
      <div class="seclbl">Glossary</div>
      <dl class="learnGlossary">${GLOSSARY.map(([t,d])=>`<div><dt>${esc(t)}</dt><dd>${esc(d)}</dd></div>`).join('')}</dl>`;
  };
  window.__learnOpen=id=>{OPEN=id;document.querySelectorAll('.learnLesson[open]').forEach(d=>{if(d.id!=='learn-'+id)d.open=false})};
  // Lets any tooltip or panel send a reader straight to the right lesson.
  window.openLesson=id=>{OPEN=id;setView('learn');requestAnimationFrame(()=>document.getElementById('learn-'+id)?.scrollIntoView({block:'start'}))};
})();
