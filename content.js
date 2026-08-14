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
  const REWIND_CARD_LIMIT=3;
  const FUN_STAT_LIMIT=4;
  const SCORE_LABELS={soccer:['goal','goals'],hockey:['goal','goals'],baseball:['run','runs'],nfl:['point','points'],ncaaf:['point','points'],basketball:['point','points']};
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

  function verifiedModelCall(dataset,match){
    const official=match?.official_pick;
    if(!official||typeof official!=='object'||!['h','a','d'].includes(official.pick))return null;
    // `official_pick` is projected from the verified pregame ledger by the
    // feed builder. A fixture-id list alone cannot prove that the current,
    // potentially recalculated prediction is the one that was locked.
    return official;
  }

  function hasVerifiedModelCall(dataset,match){
    return !!verifiedModelCall(dataset,match);
  }

  function officialPickHit(modelCall){
    if(typeof modelCall?.model_hit==='boolean')return modelCall.model_hit;
    if(typeof modelCall?.result==='boolean')return modelCall.result;
    const result=String(modelCall?.result||'').toLowerCase();
    if(['h','a','d'].includes(result)&&['h','a','d'].includes(modelCall?.pick))return result===modelCall.pick;
    if(['hit','correct','won','win','true'].includes(result))return true;
    if(['miss','incorrect','lost','loss','false'].includes(result))return false;
    return null;
  }

  function finiteNumber(value){
    if(value===null||value===''||value===undefined)return null;
    const number=Number(value);return Number.isFinite(number)?number:null;
  }

  function hasFinalScore(match){
    return match?.status==='FINISHED'&&finiteNumber(match?.score?.home)!==null&&finiteNumber(match?.score?.away)!==null&&['h','a','d'].includes(winnerSide(match));
  }

  function scoreWord(sport,value,capitalized=false){
    const forms=SCORE_LABELS[sport]||['point','points'],word=forms[Math.abs(Number(value))===1?0:1];
    return capitalized?word[0].toUpperCase()+word.slice(1):word;
  }

  function teamInitials(name){
    const words=String(name||'').replace(/[^\p{L}\p{N}'-]+/gu,' ').trim().split(/\s+/).filter(Boolean);
    const meaningful=words.filter(word=>!/^(?:afc|cf|fc|hc|sc)$/i.test(word)&&!/^\d+$/.test(word));
    const source=meaningful.length?meaningful:words;
    if(source.length===1)return source[0].replace(/[^\p{L}\p{N}]/gu,'').slice(0,3).toUpperCase()||'—';
    return source.slice(0,3).map(word=>word[0]).join('').toUpperCase()||'—';
  }

  function strongestFactor(match,modelCall=null){
    const why=modelCall?.factor_snapshot||modelCall?.why||match?.prediction?.why||{};
    const candidates=Object.entries(why).filter(([key,value])=>key!=='adv'&&Number.isFinite(Number(value)));
    candidates.sort((a,b)=>Math.abs(Number(b[1]))-Math.abs(Number(a[1])));
    const key=(candidates[0]||Object.entries(why).find(([,value])=>Number.isFinite(Number(value)))||[])[0];
    return FACTOR_LABELS[key]||'overall team profile';
  }

  function possessive(name){return /s$/i.test(String(name||''))?`${name}'`:`${name}'s`}

  function matchTakeaway(match,finished=false,modelCall=null){
    const prediction=modelCall||match?.prediction||{},pick=prediction.pick_name||'the model pick',factor=strongestFactor(match,prediction);
    if(!finished)return `${pick} has the clearest ${factor} signal, but the probability still leaves room for the other side.`;
    const hit=finished?officialPickHit(prediction):null;
    if(hit===null)return `The verified pregame pick leaned ${pick} on ${factor}; the feed does not provide a graded outcome for this call.`;
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

  function primaryLabel(item){return item.badgeType==='availability'?'Read tracker':item.badgeType==='ranking'?'Read rankings':item.badgeType==='simulation'?'Read simulation':item.badgeType==='market-audit'?'Read market audit':item.badgeType==='methodology'?'Read methodology':item.type==='preview'?'Read preview':item.type==='recap'?'Read recap':'Read explainer'}

  function typeBadge(type){
    const label=type==='availability'?'Availability':type==='ranking'?'Rankings':type==='simulation'?'Simulation':type==='market-audit'?'Market audit':type==='methodology'?'Methodology':type==='preview'?'Preview':type==='recap'?'Recap':'Learn';
    return `<span class="typeBadge type${label.replace(/\s+/g,'')}">${label}</span>`;
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
      (dataset.matches||[]).filter(match=>match.status==='FINISHED'&&winnerSide(match)&&hasVerifiedModelCall(dataset,match)).forEach(match=>{
        const official=verifiedModelCall(dataset,match),hit=officialPickHit(official);if(hit===null)return;
        candidates.push({
          id:`recap-${meta.key}-${match.id}`,type:'recap',sports:[meta.sport],comp:meta.key,compLabel:meta.label,matchId:match.id,
          home:match.home?.name,away:match.away?.name,score:`${match.score?.home??'—'}–${match.score?.away??'—'}`,
          pick:official.pick_name,confidence:official.confidence,hit,resultLabel:hit?'Model hit':'Model miss',
          title:`${match.home?.name} ${match.score?.home??'—'}–${match.score?.away??'—'} ${match.away?.name}`,
          summary:`The verified pregame pick was ${official.pick_name}${official.confidence!=null?` at ${official.confidence}%`:''}; ${winnerName(match)} produced the result.`,
          takeaway:matchTakeaway(match,true,official),updated:match.kickoff,dataUpdated:dataset.updated,sortTime:timestamp(match.kickoff),minutes:3,
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
      const isRanking=post.type==='ranking',isAvailability=post.type==='availability',isSimulation=post.type==='simulation',isMarketAudit=post.type==='market-audit',isMethodology=post.type==='methodology';
      const storyType=isRanking?'preview':(isAvailability||isSimulation||isMarketAudit||isMethodology)?'learn':'recap';
      return {id:`post-${post.id||post.slug}`,type:storyType,badgeType:isAvailability?'availability':isRanking?'ranking':isSimulation?'simulation':isMarketAudit?'market-audit':isMethodology?'methodology':null,sports:[meta.sport],comp:meta.key,compLabel:post.comp_label||meta.label,
        title:post.title||`${meta.label} model recap`,summary:post.summary||'The latest locked-pick model recap.',takeaway:isAvailability?'A sourced status check that separates confirmed news from what the current feed cannot establish.':isRanking?'A current ordering, its opening-fixture context, and the limits of the available evidence.':isSimulation?'A clearly labeled fictional scenario with fixed inputs, sensitivity cases, and no forecast claim.':isMarketAudit?'A quality-gated comparison that states plainly when current market evidence is too thin to publish.':isMethodology?'An accountability note explaining how Matchday locks, grades, and evaluates its predictions.':'A weekly review of the calls, misses, and calibration lessons.',
        updated:`${post.date||''}T12:00:00Z`,dataUpdated:`${post.date||''}T12:00:00Z`,sortTime:timestamp(`${post.date||''}T12:00:00Z`),minutes:Math.max(3,Math.ceil(words/180)),
        url:`posts/${encodeURIComponent(post.slug||post.id||'')}.html`,resultLabel:isAvailability?'Availability desk':isRanking?'Ranked list':isSimulation?'Simulation':isMarketAudit?'Market audit':isMethodology?'Methodology':'Weekly recap'};
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

  function moduleRows(){
    const query=searchQuery.trim().toLowerCase();
    let rows=allFilteredMatches().filter(({match,dataset,meta})=>{
      if(!query)return true;
      const venue=typeof match.venue==='string'?match.venue:match.venue?.name;
      const modelCall=match.status==='FINISHED'?verifiedModelCall(dataset,match):match.prediction;
      return [meta.label,match.home?.name,match.away?.name,modelCall?.pick_name,match.stage,venue].filter(Boolean).join(' ').toLowerCase().includes(query);
    });
    if(activeType==='preview')rows=rows.filter(row=>row.match.status==='UPCOMING');
    if(activeType==='recap')rows=rows.filter(row=>row.match.status==='FINISHED');
    if(activeType==='learn')rows=[];
    return rows;
  }

  function signalBar(label,detail,count,max,tone='green'){
    const width=max?Math.max(count?8:0,Math.round(100*count/max)):0;
    return `<div class="signalBar"><div class="signalBarLabel"><span>${escapeHTML(label)}</span><b>${escapeHTML(detail)}</b></div><div class="signalBarTrack" role="meter" aria-label="${escapeHTML(label)}: ${count}" aria-valuemin="0" aria-valuemax="${max}" aria-valuenow="${count}"><span class="${tone}" style="--signal-width:${width}%"></span></div></div>`;
  }

  function renderSignalLab(){
    const host=byId('signalLabGrid');if(!host)return;
    const rows=allFilteredMatches();
    const upcoming=rows.filter(row=>row.match.status==='UPCOMING'&&finiteNumber(row.match.prediction?.confidence)!==null);
    const verified=rows.filter(row=>row.match.status==='FINISHED'&&hasVerifiedModelCall(row.dataset,row.match));
    const modelRows=[...upcoming.map(row=>({row,call:row.match.prediction})),...verified.map(row=>({row,call:verifiedModelCall(row.dataset,row.match)}))];
    if(!rows.length||!modelRows.length){
      host.innerHTML=`<article class="signalViz signalVizEmpty"><div class="signalEmptyMark" aria-hidden="true"></div><h3>No signal map for this sport yet</h3><p>The charts need at least one current prediction or verified pregame call.</p></article>`;return;
    }
    const confidenceBands=[
      {label:'Open field',detail:'under 50%',min:0,max:49,tone:'blue'},
      {label:'Lean',detail:'50–64%',min:50,max:64,tone:'purple'},
      {label:'Strong',detail:'65–79%',min:65,max:79,tone:'green'},
      {label:'Rare air',detail:'80%+',min:80,max:100,tone:'gold'}
    ].map(band=>({...band,count:modelRows.filter(item=>item.call.confidence>=band.min&&item.call.confidence<=band.max).length}));
    const confidenceMax=Math.max(...confidenceBands.map(band=>band.count),1);
    const sortedConfidence=modelRows.map(item=>Math.round(Number(item.call.confidence))).sort((a,b)=>a-b);
    const median=sortedConfidence[Math.floor(sortedConfidence.length/2)];
    const factorCounts={};
    upcoming.forEach(({match})=>{const label=strongestFactor(match);factorCounts[label]=(factorCounts[label]||0)+1});
    const factors=Object.entries(factorCounts).sort((a,b)=>b[1]-a[1]).slice(0,5),factorMax=Math.max(...factors.map(([,count])=>count),1);
    const other=Math.max(0,rows.length-upcoming.length-verified.length),upcomingPct=Math.round(100*upcoming.length/rows.length),verifiedPct=Math.round(100*verified.length/rows.length);
    const scope=activeSport==='all'?'all loaded sports':SPORT_LABELS[activeSport];
    host.innerHTML=`
      <article class="signalViz confidenceViz">
        <div class="signalVizHead"><div><span>Confidence terrain</span><h3>How bold is the board?</h3></div><strong>${median}%<small>median</small></strong></div>
        <div class="signalBars">${confidenceBands.map(band=>signalBar(band.label,`${band.detail} · ${band.count}`,band.count,confidenceMax,band.tone)).join('')}</div>
        <p>${modelRows.length} model ${modelRows.length===1?'call':'calls'} across ${scope}. Confidence describes uncertainty; it is not a promise.</p>
      </article>
      <article class="signalViz driverViz">
        <div class="signalVizHead"><div><span>Factor fingerprint</span><h3>What is moving picks?</h3></div><strong>${factors.length}<small>drivers</small></strong></div>
        <div class="driverMap" role="img" aria-label="Most common strongest model factors">${factors.length?factors.map(([label,count],index)=>`<div class="driverRoute"><i aria-hidden="true">${index+1}</i><span>${escapeHTML(label)}</span><div><b style="--driver-width:${Math.max(12,Math.round(100*count/factorMax))}%"></b></div><em>${count}</em></div>`).join(''):'<p>No upcoming factor snapshots are available.</p>'}</div>
        <p>Counts the strongest available factor in each upcoming model read; related inputs can overlap.</p>
      </article>
      <article class="signalViz boardViz">
        <div class="signalVizHead"><div><span>Board coverage</span><h3>What can the model see?</h3></div></div>
        <div class="boardGraphic">
          <div class="boardDonut" role="img" aria-label="${upcoming.length} upcoming model reads, ${verified.length} verified finals, and ${other} other loaded games" style="--upcoming:${upcomingPct * 3.6}deg;--verified:${(upcomingPct+verifiedPct) * 3.6}deg"><b>${rows.length}</b><span>loaded games</span></div>
          <div class="boardLegend"><span class="upcoming"><b>${upcoming.length}</b> Upcoming reads</span><span class="verified"><b>${verified.length}</b> Verified finals</span><span class="other"><b>${other}</b> Other / unscored</span></div>
        </div>
        <p>“Other” stays visible instead of being silently treated as a prediction or graded result.</p>
      </article>`;
  }

  function moduleEmpty(title,body,kind='stats'){
    if(kind==='rewind')return `<article class="rewindCard rewindPlaceholder"><div class="rewindVisual" aria-hidden="true"><span class="rewindFinal">Awaiting final</span><div class="rewindMatchup"><div class="rewindTeam"><span class="rewindInitials">--</span><span class="rewindScore">--</span></div><span class="rewindVs">VS</span><div class="rewindTeam"><span class="rewindInitials">--</span><span class="rewindScore">--</span></div></div><div class="rewindMeter"><span></span></div></div><div class="rewindCopy"><div class="rewindHeader"><span>Game rewind</span><span>No matching final</span></div><h3>${escapeHTML(title)}</h3><p>${escapeHTML(body)}</p><div class="rewindVerdict push">Nothing is inferred from missing data</div></div></article>`;
    return `<article class="funStatCard moduleEmpty"><span class="funStatValue" aria-hidden="true">--</span><h3 class="funStatLabel">${escapeHTML(title)}</h3><p class="funStatDetail">${escapeHTML(body)}</p></article>`;
  }

  function rewindMeter(label,value){
    const amount=Math.max(0,Math.min(100,Math.round(Number(value))));
    return `<div class="rewindMetric"><span>${escapeHTML(label)}</span><b>${amount}%</b><div class="rewindMeter" role="meter" aria-label="${escapeHTML(label)}: ${amount} percent" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${amount}"><span style="--rewind-value:${amount}%"></span></div></div>`;
  }

  function rewindTextMetric(label,value){return `<div class="rewindMetric"><span>${escapeHTML(label)}</span><b>${escapeHTML(value)}</b></div>`}

  function rewindCard(row){
    const {match,dataset,meta}=row,homeScore=finiteNumber(match.score?.home),awayScore=finiteNumber(match.score?.away);
    const lockedCall=verifiedModelCall(dataset,match),modelCall=lockedCall||{},confidence=finiteNumber(modelCall.confidence),watchability=finiteNumber(match.watchability);
    const hit=officialPickHit(lockedCall);
    const pickName=modelCall.pick_name||'No verified pregame pick';
    const venue=typeof match.venue==='string'?match.venue:match.venue?.name;
    const context=[match.stage,venue,formattedDate(match.kickoff)].filter(Boolean).join(' · ');
    const resultLabel=lockedCall?'Verified result + pick':'Final result';
    const verdict=lockedCall&&hit!==null
      ?`The verified pregame pick was ${pickName}${confidence!==null?` at ${Math.round(confidence)}%`:''}. It was ${hit?'correct':'not correct'} against the official graded outcome.`
      :lockedCall?`The verified pregame pick was ${pickName}${confidence!==null?` at ${Math.round(confidence)}%`:''}, but the feed does not provide a graded outcome for this call.`
      :'No verified pregame pick is available, so this game is not scored as a model hit or miss.';
    const total=homeScore+awayScore,scoreAria=`Final score: ${match.home?.name}, ${homeScore} ${scoreWord(meta.sport,homeScore)}; ${match.away?.name}, ${awayScore} ${scoreWord(meta.sport,awayScore)}.`;
    const metrics=[rewindTextMetric(`Total ${scoreWord(meta.sport,total)}`,String(total))];
    if(confidence!==null)metrics.push(rewindMeter('Pregame confidence',confidence));
    if(watchability!==null)metrics.push(rewindMeter('Watchability',watchability));
    const titleId=`rewind-${String(meta.key)}-${String(match.id).replace(/[^a-zA-Z0-9_-]/g,'-')}`;
    const visualValue=watchability!==null?Math.max(0,Math.min(100,Math.round(watchability))):confidence!==null?Math.max(0,Math.min(100,Math.round(confidence))):0;
    return `<article class="rewindCard" data-sport="${escapeHTML(meta.sport)}" aria-labelledby="${escapeHTML(titleId)}">
      <div class="rewindVisual">
        <span class="rewindFinal">${escapeHTML(resultLabel)}</span>
        <div class="rewindMatchup" aria-label="${escapeHTML(scoreAria)}">
          <div class="rewindTeam" aria-hidden="true"><span class="rewindInitials">${escapeHTML(teamInitials(match.home?.name))}</span><span class="rewindTeamName">${escapeHTML(match.home?.name||'Home')}</span><span class="rewindScore">${homeScore}</span></div>
          <span class="rewindVs" aria-hidden="true">&ndash;</span>
          <div class="rewindTeam" aria-hidden="true"><span class="rewindInitials">${escapeHTML(teamInitials(match.away?.name))}</span><span class="rewindTeamName">${escapeHTML(match.away?.name||'Away')}</span><span class="rewindScore">${awayScore}</span></div>
        </div>
        <div class="rewindMeter" aria-hidden="true"><span style="--rewind-value:${visualValue}%"></span></div>
      </div>
      <div class="rewindCopy">
        <div class="rewindHeader"><span>${escapeHTML(meta.label)}</span><span>${escapeHTML(context||formattedDate(match.kickoff))}</span></div>
        <h3 id="${escapeHTML(titleId)}">${escapeHTML(match.home?.name||'Home')} vs ${escapeHTML(match.away?.name||'Away')}</h3>
        <p>${escapeHTML(`${winnerName(match)} produced the final result shown in the feed.`)}</p>
        <div class="rewindMetrics">${metrics.join('')}</div>
        <p class="rewindVerdict ${hit===true?'hit':hit===false?'miss':'push'}">${escapeHTML(verdict)}</p>
        <a href="${escapeHTML(dashboardUrl(meta.key,'matches',match.id))}">Open matchup &rarr;</a>
      </div>
    </article>`;
  }

  function renderGameRewind(){
    const host=byId('gameRewindGrid');if(!host)return;
    if(activeType==='preview'||activeType==='learn'){
      host.innerHTML=moduleEmpty('Game Rewind is a final-results view','Choose Recaps or All to see completed games in this section.','rewind');return;
    }
    const finals=moduleRows().filter(row=>hasFinalScore(row.match)).sort((a,b)=>timestamp(b.match.kickoff)-timestamp(a.match.kickoff));
    if(!finals.length){
      const scope=activeSport==='all'?'this view':SPORT_LABELS[activeSport];
      const reason=searchQuery.trim()?`No final score matches “${searchQuery.trim()}” in ${scope}.`:`No complete final scores are available for ${scope} yet.`;
      host.innerHTML=moduleEmpty('No game rewind available',reason,'rewind');return;
    }
    host.innerHTML=finals.slice(0,REWIND_CARD_LIMIT).map(rewindCard).join('');
  }

  function funStatCard(value,label,detail){
    return `<article class="funStatCard"><strong class="funStatValue">${escapeHTML(value)}</strong><h3 class="funStatLabel">${escapeHTML(label)}</h3><p class="funStatDetail">${escapeHTML(detail)}</p></article>`;
  }

  function renderFunStats(){
    const host=byId('funStatsGrid');if(!host)return;
    const rows=moduleRows();
    if(!rows.length){
      const reason=activeType==='learn'?'Fun Stats uses game data; choose All, Previews, or Recaps.':searchQuery.trim()?`No games match “${searchQuery.trim()}” in the current sport filter.`:'No game data is available for this filter yet.';
      host.innerHTML=moduleEmpty('No stats for this view',reason);return;
    }
    const finals=rows.filter(row=>hasFinalScore(row.match));
    const upcoming=rows.filter(row=>row.match.status==='UPCOMING'&&row.match.prediction);
    const verified=finals.filter(row=>hasVerifiedModelCall(row.dataset,row.match));
    const watchable=rows.filter(row=>finiteNumber(row.match.watchability)!==null).sort((a,b)=>finiteNumber(b.match.watchability)-finiteNumber(a.match.watchability));
    const confident=rows.map(row=>({row,modelCall:row.match.status==='FINISHED'?verifiedModelCall(row.dataset,row.match):row.match.prediction}))
      .filter(item=>finiteNumber(item.modelCall?.confidence)!==null).sort((a,b)=>finiteNumber(b.modelCall.confidence)-finiteNumber(a.modelCall.confidence));
    const cards=[];
    if(!searchQuery.trim()&&activeType!=='preview'){
      const scorecards=filteredDatasets().map(dataset=>dataset.scorecard||{}),graded=scorecards.reduce((sum,card)=>sum+(finiteNumber(card.graded)||0),0),hits=scorecards.reduce((sum,card)=>sum+(finiteNumber(card.model_hits)||0),0);
      if(graded>0)cards.push(funStatCard(`${hits}–${graded-hits}`,'Published model record',`${Math.round(100*hits/graded)}% correct across ${graded} verified, graded picks in this sport filter.`));
    }
    if(activeType==='recap')cards.push(funStatCard(String(verified.length),'Verified rewinds',`${finals.length} final ${finals.length===1?'result is':'results are'} in this filtered feed; ${verified.length} include a verified pregame pick.`));
    else if(activeType==='preview')cards.push(funStatCard(String(upcoming.length),'Upcoming model reads',`Across ${new Set(upcoming.map(row=>row.meta.key)).size} ${new Set(upcoming.map(row=>row.meta.key)).size===1?'competition':'competitions'} in this view.`));
    else cards.push(funStatCard(String(finals.length),'Final results in view',`${upcoming.length} upcoming ${upcoming.length===1?'game also has':'games also have'} a current model read.`));
    if(activeSport!=='all'&&finals.length){
      const high=[...finals].sort((a,b)=>(finiteNumber(b.match.score.home)+finiteNumber(b.match.score.away))-(finiteNumber(a.match.score.home)+finiteNumber(a.match.score.away)))[0];
      const total=finiteNumber(high.match.score.home)+finiteNumber(high.match.score.away);
      cards.push(funStatCard(`${total} ${scoreWord(high.meta.sport,total)}`,'Highest combined score',`${high.match.home?.name} ${high.match.score.home}–${high.match.score.away} ${high.match.away?.name}, among loaded finals.`));
      const close=[...finals].sort((a,b)=>Math.abs(finiteNumber(a.match.score.home)-finiteNumber(a.match.score.away))-Math.abs(finiteNumber(b.match.score.home)-finiteNumber(b.match.score.away)))[0];
      const margin=Math.abs(finiteNumber(close.match.score.home)-finiteNumber(close.match.score.away));
      cards.push(funStatCard(`${margin} ${scoreWord(close.meta.sport,margin)}`,'Closest final margin',`${close.match.home?.name} ${close.match.score.home}–${close.match.score.away} ${close.match.away?.name}, among loaded finals.`));
    }
    if(watchable[0])cards.push(funStatCard(`${Math.round(finiteNumber(watchable[0].match.watchability))}/100`,'Watchability leader',`${watchable[0].match.home?.name} vs ${watchable[0].match.away?.name}; this is Matchday’s internal matchup score.`));
    if(confident[0])cards.push(funStatCard(`${Math.round(finiteNumber(confident[0].modelCall.confidence))}%`,confident[0].row.match.status==='FINISHED'?'Highest verified confidence':'Highest current confidence',`${confident[0].modelCall.pick_name} in ${confident[0].row.match.home?.name} vs ${confident[0].row.match.away?.name}.`));
    host.innerHTML=cards.slice(0,FUN_STAT_LIMIT).join('')||moduleEmpty('No calculated stats yet','The available games do not include enough score, watchability, or confidence data for a truthful comparison.');
  }

  function renderBrief(){
    const host=byId('briefGrid');if(!host)return;
    const rows=allFilteredMatches(),now=Date.now();
    const active=rows.filter(row=>row.match.status==='UPCOMING'&&row.match.prediction).sort((a,b)=>Number(b.match.prediction?.confidence||0)-Number(a.match.prediction?.confidence||0));
    const signal=active[0],matchOfDay=[...active].sort((a,b)=>Number(b.match.watchability||0)-Number(a.match.watchability||0))[0];
    const finished=rows.filter(row=>row.match.status==='FINISHED'&&winnerSide(row.match)&&hasVerifiedModelCall(row.dataset,row.match)).map(row=>({...row,official:verifiedModelCall(row.dataset,row.match)})).sort((a,b)=>timestamp(b.match.kickoff)-timestamp(a.match.kickoff));
    const graded=finished.filter(row=>officialPickHit(row.official)!==null),surprise=[...graded].filter(row=>officialPickHit(row.official)===false).sort((a,b)=>Number(b.official.confidence||0)-Number(a.official.confidence||0))[0];
    const week=graded.filter(row=>timestamp(row.match.kickoff)>=now-7*86400000),weekHits=week.filter(row=>officialPickHit(row.official)===true).length;
    const noticed=active.slice(0,3).map(row=>`${row.match.prediction.pick_name}: ${strongestFactor(row.match)}`).join(' · ');
    const cards=[
      signal?briefCard('Strongest upcoming signal',`${signal.match.prediction.pick_name} ${signal.match.prediction.confidence}%`,`${signal.match.home?.name} vs ${signal.match.away?.name} carries the strongest current model probability.`,dashboardUrl(signal.meta.key,'edge',signal.match.id)):
        briefCard('Strongest upcoming signal','Waiting for a current prediction','The next signal appears when an upcoming matchup receives a model read.',dashboardUrl('','edge')),
      matchOfDay?briefCard('Match of the day',`${matchOfDay.match.home?.name} vs ${matchOfDay.match.away?.name}`,matchTakeaway(matchOfDay.match),dashboardUrl(matchOfDay.meta.key,'matches',matchOfDay.match.id),'View matchup'):
        briefCard('Match of the day','No upcoming matchup yet','The highest-watchability pregame matchup will appear here.'),
      briefCard('Three things the model noticed',noticed||'No fresh factor notes yet',noticed?'The strongest signals across the current slate, without pretending any one factor is decisive.':'Factor notes appear with the next current predictions.',dashboardUrl('','edge'),'See every model read'),
      surprise?briefCard('Biggest surprise',`${winnerName(surprise.match)} changed the story`,matchTakeaway(surprise.match,true,surprise.official),dashboardUrl(surprise.meta.key,'matches',surprise.match.id),'Review the miss'):
        briefCard('Biggest surprise','No recent model miss in this view','That is not a claim of perfection—only that no graded miss is available for this filter.'),
      briefCard('Seven-day scorecard',week.length?`${weekHits}–${week.length-weekHits} over the last 7 days`:'No graded games in the last 7 days',week.length?`${Math.round(100*weekHits/week.length)}% of locked predictions were correct in this filtered view.`:'The weekly record will populate automatically as results are graded.',dashboardUrl('','score'),'Open scorecard')
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
    const finished=rows.filter(row=>row.match.status==='FINISHED'&&winnerSide(row.match)&&hasVerifiedModelCall(row.dataset,row.match)).map(row=>({...row,official:verifiedModelCall(row.dataset,row.match)}));
    const gradedFinished=finished.filter(row=>officialPickHit(row.official)!==null),hits=gradedFinished.filter(row=>officialPickHit(row.official)===true).sort((a,b)=>Number(b.official.confidence||0)-Number(a.official.confidence||0));
    const misses=gradedFinished.filter(row=>officialPickHit(row.official)===false).sort((a,b)=>Number(b.official.confidence||0)-Number(a.official.confidence||0));
    const right=hits[0],miss=misses[0],movement=movementHighlight(rows.filter(row=>row.match.status==='UPCOMING')),week=gradedFinished.filter(row=>timestamp(row.match.kickoff)>=now-7*86400000),weekHits=week.filter(row=>officialPickHit(row.official)===true).length;
    const scorecards=filteredDatasets().map(dataset=>dataset.scorecard||{}),graded=scorecards.reduce((sum,card)=>sum+Number(card.graded||0),0),modelHits=scorecards.reduce((sum,card)=>sum+Number(card.model_hits||0),0);
    const recordN=week.length,recordHits=weekHits,recordTitle=recordN?`${recordHits}–${recordN-recordHits} this week`:graded?`${modelHits}–${graded-modelHits} published record`:'No graded record yet';
    const cards=[
      right?accountabilityCard('What the model got right',`${right.official.pick_name} at ${right.official.confidence}%`,matchTakeaway(right.match,true,right.official),'good',dashboardUrl(right.meta.key,'matches',right.match.id)):
        accountabilityCard('What the model got right','Waiting for a graded hit','Correct calls appear here only after the result is final.'),
      miss?accountabilityCard('What it missed',`${miss.official.pick_name} did not land`,matchTakeaway(miss.match,true,miss.official),'bad',dashboardUrl(miss.meta.key,'matches',miss.match.id)):
        accountabilityCard('What it missed','No graded miss available','Misses are never hidden; the next one will appear automatically.'),
      movement?accountabilityCard('Biggest probability movement',`${movement.delta>0?'+':''}${movement.delta} points on ${movement.match.prediction.pick_name}`,`The saved probability moved from ${movement.first}% to ${movement.last}% across refreshes.`,'move',dashboardUrl(movement.meta.key,'edge',movement.match.id)):
        accountabilityCard('Biggest probability movement','Not enough snapshots yet','Movement is reported only after the same matchup has been observed more than once.'),
      accountabilityCard('Weekly prediction record',recordTitle,recordN?`${Math.round(100*recordHits/recordN)}% correct across ${recordN} graded games in the last seven days.`:graded?`${Math.round(100*modelHits/graded)}% correct across the available scorecards.`:'The record begins when locked picks are graded.','record',dashboardUrl('','score')),
      miss?accountabilityCard('Lesson from an incorrect pick',`Re-check ${strongestFactor(miss.match,miss.official)}`,`The ${miss.official.confidence}% lean left ${100-Number(miss.official.confidence||0)}% for other outcomes. The miss is evidence to recalibrate, not rewrite the pick.`,'lesson',dashboardUrl(miss.meta.key,'edge',miss.match.id)):
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

  function renderAll(animate=false){renderLatest(animate);renderSignalLab();renderGameRewind();renderFunStats();renderBrief();renderAccountability();renderFreshness();renderGuides();if(animate){replayMotion(byId('signalLabGrid'));replayMotion(byId('gameRewindGrid'));replayMotion(byId('funStatsGrid'));replayMotion(byId('briefGrid'));replayMotion(byId('accountabilityGrid'))}}

  function setSport(filter,persist=true){
    activeSport=validSport(filter);
    if(persist)safeSet('matchday.content.sport',activeSport);
    document.querySelectorAll('[data-sport-filter]').forEach(button=>{const active=button.dataset.sportFilter===activeSport;button.classList.toggle('isActive',active);button.setAttribute('aria-pressed',String(active))});
    renderAll(persist);
  }

  function setType(filter){
    activeType=['all','preview','recap','learn'].includes(filter)?filter:'all';
    document.querySelectorAll('[data-type-filter]').forEach(button=>{const active=button.dataset.typeFilter===activeType;button.classList.toggle('isActive',active);button.setAttribute('aria-pressed',String(active))});
    renderLatest(true);renderGameRewind();renderFunStats();replayMotion(byId('gameRewindGrid'));replayMotion(byId('funStatsGrid'));
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
  let searchTimer;const search=byId('contentSearch');if(search)search.addEventListener('input',()=>{searchQuery=search.value;clearTimeout(searchTimer);searchTimer=setTimeout(()=>{renderLatest(true);renderGameRewind();renderFunStats();replayMotion(byId('gameRewindGrid'));replayMotion(byId('funStatsGrid'))},90)});
  document.addEventListener('keydown',event=>{
    if(event.key==='/'&&!/input|textarea/i.test(document.activeElement?.tagName||'')){event.preventDefault();search?.focus()}
    if(event.key==='Escape'&&document.activeElement===search&&search.value){search.value='';searchQuery='';renderLatest(true);renderGameRewind();renderFunStats()}
  });
  storyItems=[...GUIDE_ITEMS];
  setSport(requestedSport,false);
  loadContentData();
})();
