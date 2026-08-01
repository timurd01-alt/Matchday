(function(){
  'use strict';

  const COMPETITIONS=[
    ['wc','World Cup','soccer'],['ucl','Champions League','soccer'],['epl','Premier League','soccer'],
    ['laliga','La Liga','soccer'],['seriea','Serie A','soccer'],['bundesliga','Bundesliga','soccer'],['ligue1','Ligue 1','soccer'],
    ['nfl','NFL','nfl'],['ncaaf','College Football','ncaaf'],['ncaam',"Men's College Basketball",'basketball'],
    ['nba','NBA','basketball'],['nhl','NHL','hockey'],['mlb','MLB','baseball']
  ].map(([key,label,sport])=>({key,label,sport}));
  const COMP_BY_KEY=Object.fromEntries(COMPETITIONS.map(comp=>[comp.key,comp]));
  const SPORT_LABELS={all:'All sports',soccer:'Soccer',nfl:'NFL',ncaaf:'College Football',basketball:'Basketball',hockey:'Hockey',baseball:'Baseball'};
  const FACTOR_LABELS={adv:'home context',form:'recent form',margin:'scoring margin',rest:'rest advantage',record:'season record',elo:'team strength',class:'roster strength',srs:'schedule-adjusted rating',rank:'ranking',h2h:'head-to-head history'};
  // The content hub is an editorial highlights surface, not a fixture mirror.
  // Watchability already combines team quality, competitiveness, upset drama,
  // and playoff/knockout stakes in fetch_data.py.
  const PREVIEW_HORIZON_DAYS=14;
  const UPCOMING_PREVIEWS_PER_COMP=2;
  const MATCH_RECAPS_PER_COMP=2;
  const SECOND_RECAP_MIN_WATCHABILITY=55;
  const GUIDE_ITEMS=[
    {id:'learn-soccer',type:'learn',sports:['soccer'],compLabel:'Soccer',title:'Shape, pressing & set pieces',summary:'Fixture congestion, draws, and the tactical details that move a match.',updated:'2026-07-24T12:00:00Z',minutes:8,url:'tactics-soccer.html',topic:'World Cup UCL Europe tactics pressing set pieces'},
    {id:'learn-football',type:'learn',sports:['nfl','ncaaf'],compLabel:'Football',title:'Situation, schedule & rest',summary:'Short weeks, opponent strength, and what changes between the professional and college games.',updated:'2026-07-24T12:00:00Z',minutes:7,url:'tactics-football.html',topic:'NFL College Football rest schedule strength'},
    {id:'learn-basketball',type:'learn',sports:['basketball'],compLabel:'Basketball',title:'Pace, spacing & back-to-backs',summary:'How possessions, fatigue, and bracket context shape the read.',updated:'2026-07-24T12:00:00Z',minutes:7,url:'tactics-basketball.html',topic:'NBA college basketball pace spacing fatigue'},
    {id:'learn-hockey',type:'learn',sports:['hockey'],compLabel:'Hockey',title:'Goalies, parity & special teams',summary:'Why rotation and thin margins make apparent upsets routine.',updated:'2026-07-24T12:00:00Z',minutes:6,url:'tactics-hockey.html',topic:'NHL hockey goalies special teams'},
    {id:'learn-baseball',type:'learn',sports:['baseball'],compLabel:'Baseball',title:'Patience, run differential & the long season',summary:"Why a 162-game season needs patience, run differential over time, and what the model honestly doesn't see.",updated:'2026-07-25T12:00:00Z',minutes:6,url:'tactics-baseball.html',topic:'MLB baseball run differential 162-game season'},
    {id:'learn-data',type:'learn',sports:['all'],compLabel:'Reference',title:'Data, privacy & limitations',summary:'Where the numbers come from and what Matchday does not claim to know.',updated:'2026-07-24T12:00:00Z',minutes:5,url:'qa.html#data',topic:'data privacy limitations model methodology'},
    {id:'learn-upsets',type:'learn',sports:['all'],compLabel:'Explainer',title:'What Upset Radar actually means',summary:'Who defines the underdog, what the model compares against, and why a radar flag is not always the official pick.',updated:'2026-07-27T12:00:00Z',minutes:3,url:'qa.html#upsets',topic:'upset radar underdog betting market official pick edge'}
  ];

  let datasets=[];
  let posts=[];
  let storyItems=[];
  let activeSport='all';
  let activeType='all';
  let searchQuery='';

  const byId=id=>document.getElementById(id);
  const escapeHTML=value=>String(value??'').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'})[char]);
  const safeGet=(key,fallback='')=>{try{return localStorage.getItem(key)||fallback}catch(error){return fallback}};
  const safeSet=(key,value)=>{try{localStorage.setItem(key,value)}catch(error){}};
  const validSport=value=>Object.prototype.hasOwnProperty.call(SPORT_LABELS,value)?value:'all';
  const compMeta=key=>COMP_BY_KEY[String(key||'').toLowerCase()]||{key:String(key||'').toLowerCase(),label:String(key||'Model').toUpperCase(),sport:'all'};
  const timestamp=value=>{const parsed=Date.parse(value||'');return Number.isFinite(parsed)?parsed:0};

  function timeAgo(value){
    const age=Date.now()-timestamp(value);if(!Number.isFinite(age)||age<0)return 'just updated';
    const mins=Math.round(age/60000);if(mins<2)return 'updated just now';if(mins<60)return `updated ${mins}m ago`;
    const hours=Math.round(mins/60);if(hours<24)return `updated ${hours}h ago`;
    const days=Math.round(hours/24);return `updated ${days}d ago`;
  }

  function formattedDate(value,includeTime=false){
    const parsed=new Date(value);if(Number.isNaN(parsed.getTime()))return 'Recent';
    const options=includeTime?{month:'short',day:'numeric',hour:'numeric',minute:'2-digit'}:{month:'short',day:'numeric',year:'numeric'};
    return new Intl.DateTimeFormat(undefined,options).format(parsed);
  }

  function dataStatus(updated){
    const age=Date.now()-timestamp(updated);
    if(age<2*3600000)return {label:'Fresh data',className:'fresh'};
    if(age<24*3600000)return {label:'Current data',className:'current'};
    return {label:'Older data',className:'stale'};
  }

  function winnerSide(match){
    if(match?.score?.winner)return match.score.winner;
    const home=Number(match?.score?.home),away=Number(match?.score?.away);
    if(!Number.isFinite(home)||!Number.isFinite(away))return null;
    return home===away?'d':home>away?'h':'a';
  }

  function winnerName(match){
    const side=winnerSide(match);return side==='h'?match.home?.name:side==='a'?match.away?.name:side==='d'?'Draw':'Unknown result';
  }

  function hasVerifiedModelCall(dataset,match){
    const fixtureId=String(match?.id??'');
    if(!fixtureId)return false;
    return ((dataset?.scorecard?.picks)||[]).some(pick=>
      String(pick?.fixture_id??'')===fixtureId&&
      pick?.integrity_eligible===true&&
      pick?.integrity_status==='verified'&&
      pick?.legacy!==true
    );
  }

  function strongestFactor(match){
    const why=match?.prediction?.why||{};
    const candidates=Object.entries(why).filter(([key,value])=>key!=='adv'&&Number.isFinite(Number(value)));
    candidates.sort((a,b)=>Math.abs(Number(b[1]))-Math.abs(Number(a[1])));
    const key=(candidates[0]||Object.entries(why).find(([,value])=>Number.isFinite(Number(value)))||[])[0];
    return FACTOR_LABELS[key]||'overall team profile';
  }

  function possessive(name){return /s$/i.test(String(name||''))?`${name}'`:`${name}'s`}

  function matchTakeaway(match,finished=false){
    const pick=match?.prediction?.pick_name||'the model pick',factor=strongestFactor(match);
    if(!finished)return `${pick} has the clearest ${factor} signal, but the probability still leaves room for the other side.`;
    const hit=winnerSide(match)===match?.prediction?.pick;
    if(hit)return `The model correctly identified ${possessive(pick)} ${factor} advantage.`;
    return `${winnerName(match)} overturned the model's ${factor} lean toward ${pick}.`;
  }

  function dashboardUrl(comp,view='matches',matchId=''){
    if(!comp&&['edge','score'].includes(view)){
      const available=filteredDatasets();
      const best=view==='score'?[...available].sort((a,b)=>Number(b.scorecard?.graded||0)-Number(a.scorecard?.graded||0))[0]:available[0];
      comp=best?.compKey||({soccer:'ucl',nfl:'nfl',ncaaf:'ncaaf',basketball:'nba',hockey:'nhl',baseball:'mlb'})[activeSport]||'ncaaf';
    }
    const params=new URLSearchParams();if(comp)params.set('sport',comp);if(view)params.set('view',view);if(matchId)params.set('match',matchId);
    return `index.html?${params.toString()}`;
  }

  function similarUrl(item){
    const sport=(item.sports||[]).find(value=>value!=='all')||'all';
    return `content.html?sport=${encodeURIComponent(sport)}#latest`;
  }

  function contextLinks(item){
    const firstSport=(item.sports||[]).find(value=>value!=='all');
    const comp=item.comp||({soccer:'ucl',nfl:'nfl',ncaaf:'ncaaf',basketball:'nba',hockey:'nhl',baseball:'mlb'})[firstSport]||'';
    const links=[];
    if(item.matchId)links.push(['View matchup',dashboardUrl(comp,'matches',item.matchId)]);
    links.push(['See model prediction',dashboardUrl(comp,'edge',item.matchId||'')]);
    links.push(['Open scorecard',dashboardUrl(comp,'score')]);
    links.push(['Explore similar',similarUrl(item)]);
    return links.slice(0,4);
  }

  function primaryLabel(item){return item.badgeType==='availability'?'Read tracker':item.badgeType==='ranking'?'Read rankings':item.badgeType==='simulation'?'Read simulation':item.type==='preview'?'Read preview':item.type==='recap'?'Read recap':'Read explainer'}

  function typeBadge(type){
    const label=type==='availability'?'Availability':type==='ranking'?'Rankings':type==='simulation'?'Simulation':type==='preview'?'Preview':type==='recap'?'Recap':'Learn';
    return `<span class="typeBadge type${label}">${label}</span>`;
  }

  function itemSearchText(item){
    return [item.title,item.summary,item.takeaway,item.compLabel,item.home,item.away,item.pick,item.topic,item.type].filter(Boolean).join(' ').toLowerCase();
  }

  function matchesSport(item){
    return activeSport==='all'||(item.sports||[]).includes('all')||(item.sports||[]).includes(activeSport);
  }

  function filteredItems(){
    const query=searchQuery.trim().toLowerCase();
    const filtered=storyItems.filter(item=>matchesSport(item)&&(activeType==='all'||item.type===activeType)&&(!query||itemSearchText(item).includes(query)));
    if(activeType!=='all')return filtered.sort((a,b)=>activeType==='preview'?(a.sortTime-b.sortTime):b.sortTime-a.sortTime).slice(0,18);
    const buckets={preview:[],recap:[],learn:[]};filtered.sort((a,b)=>b.sortTime-a.sortTime).forEach(item=>(buckets[item.type]||buckets.learn).push(item));
    buckets.preview.sort((a,b)=>a.sortTime-b.sortTime||b.watchability-a.watchability);
    const diverse=[],seen=new Set();
    for(let round=0;diverse.length<18;round++){
      let added=false;
      ['preview','recap','learn'].forEach(type=>{const item=buckets[type][round];if(item&&!seen.has(item.id)){diverse.push(item);seen.add(item.id);added=true}});
      if(!added)break;
    }
    return diverse.slice(0,18);
  }

  function statusMeta(item){
    if(item.type==='learn')return {label:'Reference',className:'reference'};
    if(item.type==='recap')return {label:item.resultLabel||'Final',className:item.hit===true?'hit':item.hit===false?'miss':'final'};
    return {label:item.kickoffLabel||'Upcoming',className:'upcoming'};
  }

  function storyCard(item){
    const status=statusMeta(item),fresh=dataStatus(item.dataUpdated||item.updated);
    const score=item.type==='recap'&&item.home?`<div class="storyFixture"><span>${escapeHTML(item.home)}</span><b>${escapeHTML(item.score||'Final')}</b><span>${escapeHTML(item.away)}</span></div>`:'';
    const pick=item.pick?`<div class="storyPick"><span>Model pick</span><b>${escapeHTML(item.pick)}${item.confidence!=null?` ${escapeHTML(item.confidence)}%`:''}</b>${item.type==='recap'?`<i class="${item.hit?'hit':'miss'}">${item.hit?'Correct':'Missed'}</i>`:''}</div>`:'';
    const links=contextLinks(item).map(([label,url])=>`<a href="${escapeHTML(url)}">${escapeHTML(label)}</a>`).join('');
    return `<article class="storyCard story${item.type[0].toUpperCase()+item.type.slice(1)}" data-story-id="${escapeHTML(item.id)}">
      <div class="storyTop">${typeBadge(item.badgeType||item.type)}<span class="storyStatus ${status.className}">${escapeHTML(status.label)}</span></div>
      <h3>${escapeHTML(item.title)}</h3>${score}${pick}
      <p>${escapeHTML(item.summary)}</p>
      ${item.takeaway?`<div class="storyTakeaway"><span>Takeaway</span>${escapeHTML(item.takeaway)}</div>`:''}
      <div class="storyMeta"><span>${escapeHTML(formattedDate(item.updated,item.type==='preview'))}</span><span>${escapeHTML(item.compLabel||'Matchday')}</span><span>${escapeHTML(item.minutes||3)} min read</span><span class="dataState ${fresh.className}">${escapeHTML(fresh.label)}</span></div>
      <a class="storyPrimary" href="${escapeHTML(item.url)}">${primaryLabel(item)} &rarr;</a>
      <nav class="contextLinks" aria-label="Related actions">${links}</nav>
    </article>`;
  }

  function buildPreviewItems(){
    const now=Date.now(),selected=[];
    datasets.forEach(dataset=>{
      const meta=compMeta(dataset.compKey),candidates=[];
      (dataset.matches||[]).forEach(match=>{
        const kick=timestamp(match.kickoff);
        if(!match.prediction||match.status!=='UPCOMING'||kick<now-3*3600000)return;
        const pick=match.prediction.pick_name||'No model lean';
        candidates.push({
          id:`preview-${meta.key}-${match.id}`,type:'preview',sports:[meta.sport],comp:meta.key,compLabel:meta.label,
          matchId:match.id,home:match.home?.name,away:match.away?.name,pick,confidence:match.prediction.confidence,
          title:`What to watch: ${match.home?.name} vs ${match.away?.name}`,
          summary:`The model leans ${pick}${match.prediction.confidence!=null?` at ${match.prediction.confidence}%`:''}. ${match.prediction.note||'The matchup remains open enough to reward context over certainty.'}`,
          takeaway:matchTakeaway(match),updated:match.kickoff,dataUpdated:dataset.updated,sortTime:kick,
          kickoffLabel:kick?formattedDate(match.kickoff,true):'Upcoming',minutes:3,
          url:dashboardUrl(meta.key,'edge',match.id),watchability:Number(match.watchability)||0,match
        });
      });
      const future=candidates.filter(item=>item.sortTime<=now+PREVIEW_HORIZON_DAYS*86400000)
        .sort((a,b)=>b.watchability-a.watchability||a.sortTime-b.sortTime);
      selected.push(...future.slice(0,UPCOMING_PREVIEWS_PER_COMP));
    });
    return selected;
  }

  function buildMatchRecaps(){
    const items=[];
    datasets.forEach(dataset=>{
      const meta=compMeta(dataset.compKey),candidates=[];
      // Finished fixtures receive a freshly calculated prediction in the data
      // feed for analysis, including games played before Matchday existed. A
      // recap is an accountability claim, so require evidence that the pick was
      // genuinely locked before kickoff in the verified scorecard ledger.
      (dataset.matches||[]).filter(match=>match.status==='FINISHED'&&match.prediction&&winnerSide(match)&&hasVerifiedModelCall(dataset,match)).forEach(match=>{
        const hit=winnerSide(match)===match.prediction.pick;
        candidates.push({
          id:`recap-${meta.key}-${match.id}`,type:'recap',sports:[meta.sport],comp:meta.key,compLabel:meta.label,matchId:match.id,
          home:match.home?.name,away:match.away?.name,score:`${match.score?.home??'—'}–${match.score?.away??'—'}`,
          pick:match.prediction.pick_name,confidence:match.prediction.confidence,hit,resultLabel:hit?'Model hit':'Model miss',
          title:`${match.home?.name} ${match.score?.home??'—'}–${match.score?.away??'—'} ${match.away?.name}`,
          summary:`The model picked ${match.prediction.pick_name}${match.prediction.confidence!=null?` at ${match.prediction.confidence}%`:''}; ${winnerName(match)} produced the result.`,
          takeaway:matchTakeaway(match,true),updated:match.kickoff,dataUpdated:dataset.updated,sortTime:timestamp(match.kickoff),minutes:3,
          url:dashboardUrl(meta.key,'matches',match.id),watchability:Number(match.watchability)||0,match
        });
      });
      candidates.sort((a,b)=>b.watchability-a.watchability||b.sortTime-a.sortTime);
      // Preserve one best recap per active competition even in a quiet week;
      // a second story must clear the explicit importance threshold.
      if(candidates[0])items.push(candidates[0]);
      items.push(...candidates.slice(1,MATCH_RECAPS_PER_COMP)
        .filter(item=>item.watchability>=SECOND_RECAP_MIN_WATCHABILITY));
    });
    return items.sort((a,b)=>b.sortTime-a.sortTime).slice(0,24);
  }

  function buildPostItems(){
    return posts.map(post=>{
      const meta=compMeta(post.comp),words=(Array.isArray(post.body)?post.body.join(' '):'').split(/\s+/).filter(Boolean).length;
      const isRanking=post.type==='ranking',isAvailability=post.type==='availability',isSimulation=post.type==='simulation';
      return {id:`post-${post.id||post.slug}`,type:'recap',badgeType:isAvailability?'availability':isRanking?'ranking':isSimulation?'simulation':null,sports:[meta.sport],comp:meta.key,compLabel:post.comp_label||meta.label,
        title:post.title||`${meta.label} model recap`,summary:post.summary||'The latest locked-pick model recap.',takeaway:isAvailability?'A sourced status check that separates confirmed news from what the current feed cannot establish.':isRanking?'A current ordering, its opening-fixture context, and the limits of the available evidence.':isSimulation?'A clearly labeled fictional scenario with fixed inputs, sensitivity cases, and no forecast claim.':'A weekly review of the calls, misses, and calibration lessons.',
        updated:`${post.date||''}T12:00:00Z`,dataUpdated:`${post.date||''}T12:00:00Z`,sortTime:timestamp(`${post.date||''}T12:00:00Z`),minutes:Math.max(3,Math.ceil(words/180)),
        url:`posts/${encodeURIComponent(post.slug||post.id||'')}.html`,resultLabel:isAvailability?'Availability desk':isRanking?'Ranked list':isSimulation?'Simulation':'Weekly recap'};
    });
  }

  function featuredItem(list){
    const previews=list.filter(item=>item.type==='preview').sort((a,b)=>a.sortTime-b.sortTime);
    if(previews.length){const firstKick=previews[0].sortTime;return previews.filter(item=>item.sortTime<=firstKick+3*86400000).sort((a,b)=>b.watchability-a.watchability)[0]}
    return list.find(item=>item.type==='recap')||list[0];
  }

  function renderFeatured(list){
    const host=byId('featuredStory'),item=featuredItem(list);if(!host)return;
    if(!item){host.innerHTML='<div><small>NO MATCHING FEATURE</small><h3>Try a broader search or another filter.</h3><p>The full archive remains available below.</p></div><a class="featuredAction" href="index.html">Open dashboard &rarr;</a>';return}
    const status=statusMeta(item),links=contextLinks(item).slice(0,3).map(([label,url])=>`<a href="${escapeHTML(url)}">${escapeHTML(label)}</a>`).join('');
    const headline=item.type==='preview'&&item.pick?`The case for ${item.pick}: ${item.home} vs ${item.away}`:item.title;
    host.className=`featured featured${item.type[0].toUpperCase()+item.type.slice(1)}`;
    host.innerHTML=`<div><div class="featuredLabel">${typeBadge(item.badgeType||item.type)}<span class="storyStatus ${status.className}">${escapeHTML(status.label)}</span></div><h3>${escapeHTML(headline)}</h3><p>${escapeHTML(item.takeaway||item.summary)}</p><div class="featuredMeta"><span>${escapeHTML(item.compLabel)}</span><span>${escapeHTML(formattedDate(item.updated,true))}</span><span>${escapeHTML(item.minutes)} min read</span><span>${escapeHTML(timeAgo(item.dataUpdated||item.updated))}</span></div><nav class="featuredLinks" aria-label="Featured story actions">${links}</nav></div><a class="featuredAction" href="${escapeHTML(item.url)}">Read analysis &rarr;</a>`;
  }

  function replayMotion(element,className='contentMotion'){
    if(!element)return;element.classList.remove(className);void element.offsetWidth;element.classList.add(className);
  }

  function renderLatest(animate=false){
    const list=filteredItems(),grid=byId('latestGrid'),empty=byId('contentEmpty'),count=byId('contentCount');
    if(grid)grid.innerHTML=list.map(storyCard).join('');
    if(empty)empty.hidden=!!list.length;
    if(count)count.textContent=list.length?`${list.length} ${list.length===1?'story':'stories'} shown`:'No matching stories';
    renderFeatured(list);
    if(animate){replayMotion(grid);replayMotion(byId('featuredStory'),'featuredSwap')}
  }

  function filteredDatasets(){return activeSport==='all'?datasets:datasets.filter(dataset=>compMeta(dataset.compKey).sport===activeSport)}

  function allFilteredMatches(){return filteredDatasets().flatMap(dataset=>(dataset.matches||[]).map(match=>({match,dataset,meta:compMeta(dataset.compKey)})))}

  function briefCard(label,title,body,link,labelLink='Open analysis'){
    return `<article class="briefCard"><span>${escapeHTML(label)}</span><h3>${escapeHTML(title)}</h3><p>${escapeHTML(body)}</p>${link?`<a href="${escapeHTML(link)}">${escapeHTML(labelLink)} &rarr;</a>`:''}</article>`;
  }

  function renderBrief(){
    const host=byId('briefGrid');if(!host)return;
    const rows=allFilteredMatches(),now=Date.now();
    const active=rows.filter(row=>row.match.status==='UPCOMING'&&row.match.prediction).sort((a,b)=>Number(b.match.prediction?.confidence||0)-Number(a.match.prediction?.confidence||0));
    const signal=active[0],matchOfDay=[...active].sort((a,b)=>Number(b.match.watchability||0)-Number(a.match.watchability||0))[0];
    const finished=rows.filter(row=>row.match.status==='FINISHED'&&row.match.prediction&&winnerSide(row.match)&&hasVerifiedModelCall(row.dataset,row.match)).sort((a,b)=>timestamp(b.match.kickoff)-timestamp(a.match.kickoff));
    const surprise=[...finished].filter(row=>winnerSide(row.match)!==row.match.prediction.pick).sort((a,b)=>Number(b.match.prediction.confidence||0)-Number(a.match.prediction.confidence||0))[0];
    const week=finished.filter(row=>timestamp(row.match.kickoff)>=now-7*86400000),weekHits=week.filter(row=>winnerSide(row.match)===row.match.prediction.pick).length;
    const noticed=active.slice(0,3).map(row=>`${row.match.prediction.pick_name}: ${strongestFactor(row.match)}`).join(' · ');
    const cards=[
      signal?briefCard("Today's signal",`${signal.match.prediction.pick_name} ${signal.match.prediction.confidence}%`,`${signal.match.home?.name} vs ${signal.match.away?.name} carries the strongest current model probability.`,dashboardUrl(signal.meta.key,'edge',signal.match.id)):
        briefCard("Today's signal",'Waiting for a current prediction','The next signal appears when an upcoming matchup receives a model read.',dashboardUrl('','edge')),
      matchOfDay?briefCard('Match of the day',`${matchOfDay.match.home?.name} vs ${matchOfDay.match.away?.name}`,matchTakeaway(matchOfDay.match),dashboardUrl(matchOfDay.meta.key,'matches',matchOfDay.match.id),'View matchup'):
        briefCard('Match of the day','No upcoming matchup yet','The highest-watchability pregame matchup will appear here.'),
      briefCard('Three things the model noticed',noticed||'No fresh factor notes yet',noticed?'The strongest signals across the current slate, without pretending any one factor is decisive.':'Factor notes appear with the next current predictions.',dashboardUrl('','edge'),'See every model read'),
      surprise?briefCard('Biggest surprise',`${winnerName(surprise.match)} changed the story`,matchTakeaway(surprise.match,true),dashboardUrl(surprise.meta.key,'matches',surprise.match.id),'Review the miss'):
        briefCard('Biggest surprise','No recent model miss in this view','That is not a claim of perfection—only that no graded miss is available for this filter.'),
      briefCard('Weekend scorecard',week.length?`${weekHits}–${week.length-weekHits} over the last 7 days`:'No graded games in the last 7 days',week.length?`${Math.round(100*weekHits/week.length)}% of locked predictions were correct in this filtered view.`:'The weekly record will populate automatically as results are graded.',dashboardUrl('','score'),'Open scorecard')
    ];
    host.innerHTML=cards.join('');
  }

  function movementHighlight(rows){
    let history={};try{history=JSON.parse(safeGet('matchday.modelHistory','{}'))||{}}catch(error){}
    let best=null;
    rows.forEach(row=>{
      const points=history[row.match.id];if(!Array.isArray(points)||points.length<2)return;
      const first=Number(points[0]?.p),last=Number(points[points.length-1]?.p);if(!Number.isFinite(first)||!Number.isFinite(last))return;
      const delta=Math.round(last-first);if(!best||Math.abs(delta)>Math.abs(best.delta))best={...row,delta,first,last};
    });
    return best;
  }

  function accountabilityCard(label,title,body,tone='neutral',link=''){
    return `<article class="accountabilityCard ${tone}"><span>${escapeHTML(label)}</span><h3>${escapeHTML(title)}</h3><p>${escapeHTML(body)}</p>${link?`<a href="${escapeHTML(link)}">Inspect evidence &rarr;</a>`:''}</article>`;
  }

  function renderAccountability(){
    const host=byId('accountabilityGrid');if(!host)return;
    const rows=allFilteredMatches(),now=Date.now();
    const finished=rows.filter(row=>row.match.status==='FINISHED'&&row.match.prediction&&winnerSide(row.match)&&hasVerifiedModelCall(row.dataset,row.match));
    const hits=finished.filter(row=>winnerSide(row.match)===row.match.prediction.pick).sort((a,b)=>Number(b.match.prediction.confidence||0)-Number(a.match.prediction.confidence||0));
    const misses=finished.filter(row=>winnerSide(row.match)!==row.match.prediction.pick).sort((a,b)=>Number(b.match.prediction.confidence||0)-Number(a.match.prediction.confidence||0));
    const right=hits[0],miss=misses[0],movement=movementHighlight(rows),week=finished.filter(row=>timestamp(row.match.kickoff)>=now-7*86400000),weekHits=week.filter(row=>winnerSide(row.match)===row.match.prediction.pick).length;
    const scorecards=filteredDatasets().map(dataset=>dataset.scorecard||{}),graded=scorecards.reduce((sum,card)=>sum+Number(card.graded||0),0),modelHits=scorecards.reduce((sum,card)=>sum+Number(card.model_hits||0),0);
    const recordN=week.length,recordHits=weekHits,recordTitle=recordN?`${recordHits}–${recordN-recordHits} this week`:graded?`${modelHits}–${graded-modelHits} published record`:'No graded record yet';
    const cards=[
      right?accountabilityCard('What the model got right',`${right.match.prediction.pick_name} at ${right.match.prediction.confidence}%`,matchTakeaway(right.match,true),'good',dashboardUrl(right.meta.key,'matches',right.match.id)):
        accountabilityCard('What the model got right','Waiting for a graded hit','Correct calls appear here only after the result is final.'),
      miss?accountabilityCard('What it missed',`${miss.match.prediction.pick_name} did not land`,matchTakeaway(miss.match,true),'bad',dashboardUrl(miss.meta.key,'matches',miss.match.id)):
        accountabilityCard('What it missed','No graded miss available','Misses are never hidden; the next one will appear automatically.'),
      movement?accountabilityCard('Biggest probability movement',`${movement.delta>0?'+':''}${movement.delta} points on ${movement.match.prediction.pick_name}`,`The saved probability moved from ${movement.first}% to ${movement.last}% across refreshes.`,'move',dashboardUrl(movement.meta.key,'edge',movement.match.id)):
        accountabilityCard('Biggest probability movement','Not enough snapshots yet','Movement is reported only after the same matchup has been observed more than once.'),
      accountabilityCard('Weekly prediction record',recordTitle,recordN?`${Math.round(100*recordHits/recordN)}% correct across ${recordN} graded games in the last seven days.`:graded?`${Math.round(100*modelHits/graded)}% correct across the available scorecards.`:'The record begins when locked picks are graded.','record',dashboardUrl('','score')),
      miss?accountabilityCard('Lesson from an incorrect pick',`Re-check ${strongestFactor(miss.match)}`,`The ${miss.match.prediction.confidence}% lean left ${100-Number(miss.match.prediction.confidence||0)}% for other outcomes. The miss is evidence to recalibrate, not rewrite the pick.`,'lesson',dashboardUrl(miss.meta.key,'edge',miss.match.id)):
        accountabilityCard('Lesson from an incorrect pick','Calibration needs final results','This section will explain the strongest signal behind each meaningful miss.')
    ];
    host.innerHTML=cards.join('');
    const scorecardLink=document.querySelector('.accountabilityActions a');
    if(scorecardLink)scorecardLink.href=dashboardUrl('','score');
  }

  function renderFreshness(){
    const host=byId('freshnessLine');if(!host)return;
    const filtered=filteredDatasets().filter(dataset=>dataset.updated).sort((a,b)=>timestamp(b.updated)-timestamp(a.updated));
    if(!filtered.length){host.textContent='No current data files are available for this filter; evergreen explainers remain accessible.';return}
    const newest=filtered[0],oldest=filtered[filtered.length-1],oldStatus=dataStatus(oldest.updated);
    host.innerHTML=`<span class="freshDot ${oldStatus.className}"></span><b>${filtered.length} data ${filtered.length===1?'source':'sources'} loaded</b><span>Newest ${escapeHTML(timeAgo(newest.updated))}</span><span>Oldest ${escapeHTML(timeAgo(oldest.updated))}</span><span>${escapeHTML(oldStatus.label)}</span>`;
  }

  function renderGuides(){
    document.querySelectorAll('.guideCard').forEach(card=>{
      const sports=(card.dataset.sports||'all').split(/\s+/);
      card.hidden=activeSport!=='all'&&!sports.includes('all')&&!sports.includes(activeSport);
    });
  }

  function renderAll(animate=false){renderLatest(animate);renderBrief();renderAccountability();renderFreshness();renderGuides();if(animate){replayMotion(byId('briefGrid'));replayMotion(byId('accountabilityGrid'))}}

  function setSport(filter,persist=true){
    activeSport=validSport(filter);
    if(persist)safeSet('matchday.content.sport',activeSport);
    document.querySelectorAll('[data-sport-filter]').forEach(button=>{const active=button.dataset.sportFilter===activeSport;button.classList.toggle('isActive',active);button.setAttribute('aria-pressed',String(active))});
    renderAll(persist);
  }

  function setType(filter){
    activeType=['all','preview','recap','learn'].includes(filter)?filter:'all';
    document.querySelectorAll('[data-type-filter]').forEach(button=>{const active=button.dataset.typeFilter===activeType;button.classList.toggle('isActive',active);button.setAttribute('aria-pressed',String(active))});
    renderLatest(true);
  }

  async function fetchJSON(url){
    const response=await fetch(`${url}${url.includes('?')?'&':'?'}_=${Date.now()}`,{cache:'no-store'});if(!response.ok)throw new Error(`${url}: ${response.status}`);return response.json();
  }

  async function loadContentData(){
    const [postResult,feedResult]=await Promise.allSettled([fetchJSON('posts.json'),fetchJSON('content-feed.json')]);
    posts=postResult.status==='fulfilled'&&Array.isArray(postResult.value)?postResult.value.filter(post=>{
      const key=String(post?.comp||'').toLowerCase();return key==='all'||COMP_BY_KEY[key];
    }):[];
    const feed=feedResult.status==='fulfilled'&&feedResult.value&&Array.isArray(feedResult.value.datasets)?feedResult.value.datasets:[];
    datasets=feed.filter(dataset=>COMP_BY_KEY[String(dataset?.compKey||'').toLowerCase()]);
    storyItems=[...buildPreviewItems(),...buildMatchRecaps(),...buildPostItems(),...GUIDE_ITEMS];
    renderAll();
  }

  const params=new URLSearchParams(location.search),requestedSport=validSport(params.get('sport')||safeGet('matchday.content.sport','all'));
  document.querySelectorAll('[data-sport-filter]').forEach(button=>button.addEventListener('click',()=>setSport(button.dataset.sportFilter)));
  document.querySelectorAll('[data-type-filter]').forEach(button=>button.addEventListener('click',()=>setType(button.dataset.typeFilter)));
  let searchTimer;const search=byId('contentSearch');if(search)search.addEventListener('input',()=>{searchQuery=search.value;clearTimeout(searchTimer);searchTimer=setTimeout(()=>renderLatest(true),90)});
  document.addEventListener('keydown',event=>{
    if(event.key==='/'&&!/input|textarea/i.test(document.activeElement?.tagName||'')){event.preventDefault();search?.focus()}
    if(event.key==='Escape'&&document.activeElement===search&&search.value){search.value='';searchQuery='';renderLatest(true)}
  });
  storyItems=[...GUIDE_ITEMS];
  setSport(requestedSport,false);
  loadContentData();
})();
