c.width=2160;c.height=3840;ctx.scale(2,2);$('png').textContent='Download PNG · 2160 × 3840';

const modes = {prediction:'Score prediction', rankings:'Top 25 Power Ratings', ballot:'Top 25 Ballot', matchups:'Top 5 matchups', upset:'Upset Watch'};

let mode='matchups';

const seeds=["notreDame", "miami", "ohioState", "indiana", "georgia", "alabama", "lsu", "oleMiss", "utah", "texas", "wakeForest", "oregon", "texasTech", "tennessee", "iowa", "usc", "arizona", "missouri", "houston", "louisville", "texasAM", "northwestern", "byu", "nebraska", "ucla"];

const ratingValues={"notreDame": "40.49", "miami": "40.37", "ohioState": "39.84", "indiana": "38.44", "georgia": "38.13", "alabama": "36.75", "lsu": "36.44", "oleMiss": "35.46", "utah": "35.36", "texas": "35.03", "wakeForest": "33.24", "oregon": "32.64", "texasTech": "31.72", "tennessee": "31.35", "iowa": "30.89", "usc": "29.62", "arizona": "29.39", "missouri": "29.23", "houston": "29.16", "louisville": "28.34", "texasAM": "28.14", "northwestern": "28.07", "byu": "28.02", "nebraska": "27.95", "ucla": "27.65"};
let rankings=seeds.map(team=>({team,name:LOGOS[team].name.toUpperCase(),detail:ratingValues[team],src:LOGOS[team].src}));

const ballotSeeds=["utah", "miami", "georgia", "indiana", "ucla", "kentucky", "byu", "texasTech", "tennessee", "alabama", "ohioState", "texas", "notreDame", "wakeForest", "houston", "oleMiss", "lsu", "usc", "missouri", "arizona", "iowa", "northwestern", "oregon", "boiseState", "newMexico"];
let ballot=ballotSeeds.map(team=>({team,name:LOGOS[team].name.toUpperCase(),detail:"",src:LOGOS[team].src}));
function isRanking(){return mode==='rankings'||mode==='ballot'}
function rankingList(){return mode==='ballot'?ballot:rankings}

let matchups=[['texas','georgia'],['ohioState','oregon'],['alabama','tennessee'],['iowa','michigan'],['lsu','oleMiss']].map(([a,b])=>({left:{team:a,name:LOGOS[a].name.toUpperCase(),src:LOGOS[a].src},right:{team:b,name:LOGOS[b].name.toUpperCase(),src:LOGOS[b].src},detail:''}));

let upsets=[['texas','oleMiss'],['byu','ucf'],['texasTech','cincinnati']].map(([a,b])=>({left:{team:a,name:LOGOS[a].name.toUpperCase(),src:LOGOS[a].src},right:{team:b,name:LOGOS[b].name.toUpperCase(),src:LOGOS[b].src},detail:''}));
let upsetFooter='WHICH FAVORITE GOES DOWN?';
function matchupList(){return mode==='upset'?upsets:matchups}

let ballotEdition='NOV 1, 2026',ballotFooter='AGREE OR DISAGREE?';
let edition='NOV 1, 2026', footer='WHO MAKES YOUR LIST?';

const aside=document.querySelector('aside'), intro=aside.querySelector('p');

aside.querySelector('h1').textContent='Matchday Studio';intro.textContent='Pick a format. Make it yours.';

aside.querySelector('small').textContent='Teams and order are sample content.';

const picker=document.createElement('div');picker.innerHTML='<label for="format">Graphic format</label><select id="format"><option value="prediction">Score prediction</option><option value="rankings">Top 25 Power Ratings</option><option value="ballot">Top 25 Ballot</option><option value="matchups" selected>Top 5 matchups</option><option value="upset">Upset Watch</option></select>';

intro.after(picker);

const originalControls=document.createElement('div');originalControls.id='predictionControls';

let start=$('leftTeam').previousElementSibling.previousElementSibling;

while(start && start!==$('share')){const next=start.nextElementSibling;originalControls.append(start);start=next;}

aside.insertBefore(originalControls,$('share'));

const panel=document.createElement('div');panel.id='collectionControls';aside.insertBefore(panel,$('share'));

const oldRender=render,oldSnapshot=snapshot,oldLoad=$('loadFile').onchange;

function field(label,value,change,max=40){const wrap=document.createElement('label');wrap.textContent=label;const input=document.createElement('input');input.value=value;input.maxLength=max;input.oninput=()=>{change(input.value);render()};wrap.append(input);return wrap}

function teamFields(item,host){const label=document.createElement('label');label.textContent='Team';const sel=document.createElement('select');for(const [key,v] of Object.entries(LOGOS))sel.add(new Option(v.name,key));sel.value=item.team;sel.onchange=()=>{item.team=sel.value;item.name=LOGOS[sel.value].name.toUpperCase();item.src=LOGOS[sel.value].src;delete item.color;host.querySelector('input:not([type])').value=item.name;const colorInput=host.querySelector('input[type=color]');if(colorInput)colorInput.value=teamColor(item);const card=host.closest('details');if(card){const index=Array.from(panel.querySelectorAll('details')).indexOf(card);const entry=(isRanking()?rankingList():matchupList())[index];card.querySelector('summary').textContent=String(index+1).padStart(2,'0')+'  '+(isRanking()?entry.name:entry.left.name+' / '+entry.right.name)}render()};label.append(sel);host.append(label,field('Display name',item.name,v=>item.name=v,24));const up=document.createElement('input');up.type='file';up.accept='image/*';up.setAttribute('aria-label','Upload custom team logo');up.onchange=async()=>{const f=up.files[0];if(!f)return;if(f.size>10000000){$('status').textContent='Choose a logo smaller than 10 MB.';return}try{const s=await new Promise((resolve,reject)=>{const r=new FileReader();r.onload=()=>resolve(r.result);r.onerror=reject;r.readAsDataURL(f)});await img(s);item.src=s;item.team='';render()}catch{$('status').textContent='Could not open that logo.'}};host.append(up);if(mode==='matchups'||mode==='upset'){const label=document.createElement('label');label.textContent='Team side color';const input=document.createElement('input');input.type='color';input.value=teamColor(item);input.style.height='46px';input.oninput=()=>{item.color=input.value;render()};label.append(input);const reset=document.createElement('button');reset.type='button';reset.textContent='Use team color';reset.onclick=()=>{delete item.color;input.value=teamColor(item);render()};host.append(label,reset)}}

function buildControls(){originalControls.hidden=mode!=='prediction';panel.hidden=mode==='prediction';panel.replaceChildren();if(mode==='prediction')return;

panel.append(field('Edition / week (optional)',mode==='ballot'?ballotEdition:edition,v=>{if(mode==='ballot')ballotEdition=v;else edition=v},38),field('Bottom caption',mode==='upset'?upsetFooter:mode==='ballot'?ballotFooter:footer,v=>{if(mode==='upset')upsetFooter=v;else if(mode==='ballot')ballotFooter=v;else footer=v},44));

const hint=document.createElement('p');hint.className='editHint';hint.textContent=mode==='ballot'?'Your personal Top 25. Choose teams and use the arrows to rank them.':mode==='rankings'?'Open a rank to edit its team, logo and power rating. Use arrows to reorder.':'Edit the teams, names, logos and side colors. Use arrows to reorder.';panel.append(hint);

const list=isRanking()?rankingList():matchupList();

list.forEach((item,i)=>{const d=document.createElement('details'),summary=document.createElement('summary');summary.textContent=String(i+1).padStart(2,'0')+'  '+(isRanking()?item.name:item.left.name+' / '+item.right.name);d.append(summary);const controls=document.createElement('div');controls.className='row';for(const [name,delta] of [['↑ Move up',-1],['↓ Move down',1]]){const b=document.createElement('button');b.textContent=name;b.disabled=i+delta<0||i+delta>=list.length;b.onclick=()=>{[list[i],list[i+delta]]=[list[i+delta],list[i]];buildControls();render()};controls.append(b)}d.append(controls);if(isRanking()){teamFields(item,d);if(mode==='rankings')d.append(field('Power rating',item.detail,v=>item.detail=v,10))}else{const l=document.createElement('div');l.innerHTML=mode==='upset'?'<h3>Favorite on alert</h3>':'<h3>Left team</h3>';teamFields(item.left,l);const r=document.createElement('div');r.innerHTML=mode==='upset'?'<h3>Upset challenger</h3>':'<h3>Right team</h3>';teamFields(item.right,r);d.append(l,r,field('Kickoff time (optional, include time zone)',item.detail,v=>item.detail=v,36))}panel.append(d)});

}

// All built-in teams are covered. Sources and review date: docs/team-colors.json.
const teamColors={
  "abileneChristian": "#592d82",
  "airForce": "#003594",
  "akron": "#041e42",
  "alabama": "#9e1b32",
  "alabamaAM": "#790000",
  "alabamaState": "#e9a900",
  "albany": "#3d2777",
  "alcornState": "#4b0058",
  "appalachianState": "#ffcd00",
  "arizona": "#cc0033",
  "arizonaState": "#8c1d40",
  "arkansas": "#a32136",
  "arkansasPineBluff": "#e0aa0f",
  "arkansasState": "#cc092f",
  "army": "#d3bc8d",
  "auburn": "#002b5c",
  "austinPeay": "#8e0b0b",
  "ballState": "#ba0c2f",
  "baylor": "#154734",
  "bethuneCookman": "#7b1831",
  "boiseState": "#0033a0",
  "boston": "#8c2232",
  "bowlingGreen": "#fd5000",
  "brown": "#411e09",
  "bryant": "#9f8343",
  "bucknell": "#000060",
  "buffalo": "#005bbb",
  "butler": "#0d1361",
  "byu": "#0047ba",
  "california": "#041e42",
  "calPoly": "#1e4d2b",
  "campbell": "#ea7125",
  "centralArkansas": "#582c83",
  "centralConnecticut": "#1b49a2",
  "centralMichigan": "#4c0027",
  "charlestonSouthern": "#2e3192",
  "charlotte": "#005035",
  "chattanooga": "#00386b",
  "cincinnati": "#e00122",
  "citadel": "#7badd3",
  "clemson": "#f56600",
  "coastalCarolina": "#006f71",
  "colgate": "#821019",
  "colorado": "#cfb87c",
  "coloradoState": "#004c23",
  "columbia": "#7ba4db",
  "connecticut": "#0c2340",
  "cornell": "#b31b1b",
  "dartmouth": "#005730",
  "davidson": "#e51837",
  "dayton": "#004b8d",
  "delaware": "#00539f",
  "delawareState": "#009cdb",
  "drake": "#005596",
  "duke": "#00539b",
  "duquesne": "#002d62",
  "eastCarolina": "#582c83",
  "easternIllinois": "#003594",
  "easternKentucky": "#660819",
  "easternMichigan": "#006938",
  "easternWashington": "#a10022",
  "eastTennessee": "#002d61",
  "elon": "#020303",
  "florida": "#0021a5",
  "floridaAM": "#f89728",
  "floridaAtlantic": "#003366",
  "floridaIntl": "#091f3f",
  "floridaState": "#782f40",
  "fordham": "#830032",
  "fresnoState": "#b1102b",
  "furman": "#582c83",
  "gardnerWebb": "#c12535",
  "georgetown": "#110e42",
  "georgia": "#ba0c2f",
  "georgiaSouthern": "#041e42",
  "georgiaState": "#0039a6",
  "georgiaTech": "#b3a369",
  "gramblingState": "#ffd10a",
  "hampton": "#0067ac",
  "harvard": "#990000",
  "hawaii": "#005737",
  "holyCross": "#582c83",
  "houston": "#c8102e",
  "houstonBaptist": "#00539c",
  "howard": "#003a63",
  "idaho": "#8c6e4a",
  "idahoState": "#ef8c00",
  "illinois": "#ff5f05",
  "illinoisState": "#ce1126",
  "incarnateWord": "#cb333b",
  "indiana": "#970310",
  "indianaState": "#00669a",
  "iowa": "#fcd116",
  "iowaState": "#ae192d",
  "jacksonState": "#123297",
  "jacksonville": "#00523e",
  "jacksonvilleState": "#cc0000",
  "jamesMadison": "#450084",
  "kansas": "#0051ba",
  "kansasState": "#512888",
  "kennesawState": "#fdbb30",
  "kentState": "#002664",
  "kentucky": "#0033a0",
  "lafayette": "#790000",
  "lamar": "#dc0032",
  "lehigh": "#6c2b2a",
  "liberty": "#0a254e",
  "louisianaLafayette": "#ce181e",
  "louisianaMonroe": "#840029",
  "LouisianaTech": "#003087",
  "louisville": "#c9001f",
  "lsu": "#461d76",
  "maine": "#127dbe",
  "marist": "#e53730",
  "marshall": "#00b140",
  "maryland": "#ce1126",
  "massachusetts": "#881c1c",
  "mcNeeseState": "#00529c",
  "memphis": "#004991",
  "mercer": "#ff7f29",
  "miami": "#035131",
  "miamiOH": "#c41230",
  "michigan": "#00274c",
  "michiganState": "#173f35",
  "middleTennessee": "#036eb7",
  "minnesota": "#5e0a2f",
  "mississippiState": "#5d1725",
  "mississippiValleyState": "#005328",
  "missouri": "#f1b82d",
  "missouriState": "#5e0009",
  "monmouth": "#051844",
  "montana": "#751d4a",
  "montanaState": "#00205c",
  "moreheadState": "#094fa3",
  "morganState": "#014786",
  "murrayState": "#002148",
  "navy": "#00225b",
  "ncState": "#cc0000",
  "nebraska": "#e31937",
  "nevada": "#041e42",
  "newHampshire": "#004990",
  "newMexico": "#ba0c2f",
  "newMexicoState": "#7e141b",
  "nichollsState": "#c41230",
  "norfolkState": "#0c8968",
  "northCarolina": "#7bafd4",
  "northCarolinaAT": "#0505aa",
  "northCarolinaCentral": "#880023",
  "northDakota": "#00a26b",
  "northDakotaState": "#01402a",
  "northernArizona": "#003976",
  "northernColorado": "#13558d",
  "northernIllinois": "#c8102e",
  "northernIowa": "#473282",
  "northTexas": "#068f33",
  "northwestern": "#492f92",
  "northwesternState": "#492f91",
  "notreDame": "#062340",
  "ohio": "#154734",
  "ohioState": "#ba0c2f",
  "oklahoma": "#841617",
  "OklahomaState": "#fe5c00",
  "oldDominion": "#003768",
  "oleMiss": "#13294b",
  "oregon": "#00934b",
  "oregonState": "#dc4405",
  "penn": "#082a74",
  "pennState": "#001e44",
  "pittsburgh": "#003594",
  "portlandState": "#00311e",
  "prairieView": "#582c83",
  "presbyterianCollege": "#194896",
  "princeton": "#ff6000",
  "purdue": "#ceb888",
  "rhodeIsland": "#091f3f",
  "rice": "#00205b",
  "richmond": "#9e0712",
  "robertMorris": "#00214d",
  "rutgers": "#ce0e2d",
  "sacramentoState": "#00573c",
  "sacredHeart": "#a40012",
  "samford": "#005485",
  "samHoustonState": "#f56423",
  "sanDiego": "#2f99d4",
  "sanDiegoState": "#a6192e",
  "sanJoseState": "#0038a8",
  "savannahState": "#280298",
  "smu": "#a80000",
  "southAlabama": "#00205b",
  "southCarolina": "#73000a",
  "southCarolinaState": "#7d1315",
  "southDakota": "#cd1241",
  "southDakotaState": "#0033a0",
  "southeasternLouisiana": "#215732",
  "southeastMissouriState": "#c8102e",
  "southern": "#004b97",
  "southernIllinois": "#85283d",
  "southernMississippi": "#ffc72c",
  "southernUtah": "#c72026",
  "southFlorida": "#006747",
  "stanford": "#8c1515",
  "stephenFAustin": "#393996",
  "stetson": "#0a5640",
  "stFrancisPA": "#a20012",
  "stonyBrook": "#990000",
  "syracuse": "#f76900",
  "TCU": "#4d1979",
  "temple": "#a41e35",
  "tennessee": "#ff8200",
  "tennesseeMartin": "#ff6700",
  "tennesseeState": "#171796",
  "tennesseeTech": "#5a4099",
  "texas": "#bf5700",
  "texasAM": "#500000",
  "texasSanAntonio": "#0c2340",
  "texasSouthern": "#860038",
  "texasState": "#501214",
  "texasTech": "#da291c",
  "toledo": "#0b2240",
  "towson": "#ffc229",
  "troy": "#862633",
  "tulane": "#006747",
  "tulsa": "#003595",
  "uab": "#1a5632",
  "ucDavis": "#002855",
  "ucf": "#b4a169",
  "ucla": "#2774ae",
  "unlv": "#cf0a2c",
  "usc": "#9d2235",
  "utah": "#be0000",
  "utahState": "#0f2439",
  "utep": "#ff8200",
  "valparaiso": "#794500",
  "vanderbilt": "#cfae70",
  "villanova": "#00205b",
  "virginia": "#232d4b",
  "virginiaTech": "#6a2c3e",
  "vmi": "#ae122a",
  "wagner": "#00483a",
  "wakeForest": "#ceb888",
  "washington": "#33006f",
  "washingtonState": "#a60f2d",
  "weberState": "#18005a",
  "westernCarolina": "#492f91",
  "westernIllinois": "#4e1e8a",
  "westernKentucky": "#e13a3e",
  "westernMichigan": "#532e1f",
  "westVirginia": "#eaaa00",
  "williamMary": "#115740",
  "wisconsin": "#a00000",
  "wofford": "#533b23",
  "wyoming": "#492f24",
  "yale": "#004a81",
  "youngstownState": "#e51936"
};
const normalizedTeamColors=new Map(Object.entries(teamColors).map(([key,color])=>[key.toLowerCase().replace(/[^a-z0-9]/g,''),color]));
function teamColor(item){if(/^#[0-9a-f]{6}$/i.test(item.color||''))return item.color;const key=String(item.team||'').toLowerCase().replace(/[^a-z0-9]/g,'');return normalizedTeamColors.get(key)||'#30343b'}
function teamPanel(item,x,y,w,h){ctx.fillStyle=teamColor(item);ctx.fillRect(x,y,w,h);const g=ctx.createLinearGradient(x,y,x,y+h);g.addColorStop(0,'rgba(0,0,0,.25)');g.addColorStop(.55,'rgba(0,0,0,.52)');g.addColorStop(1,'rgba(0,0,0,.77)');ctx.fillStyle=g;ctx.fillRect(x,y,w,h)}
function line(x,y,w,color='#29323c'){ctx.fillStyle=color;ctx.fillRect(x,y,w,2)}

function bodyText(t,x,y,size,max,color='#f3f6ef',align='left'){ctx.fillStyle=color;ctx.textAlign=align;ctx.textBaseline='middle';ctx.font=`700 ${size}px Arial`;while(ctx.measureText(t).width>max&&size>16){size--;ctx.font=`700 ${size}px Arial`}ctx.fillText(t,x,y)}

function header(title,brand){ctx.fillStyle='#070a0f';ctx.fillRect(0,0,1080,1920);ctx.save();ctx.beginPath();ctx.arc(155,292,85,0,Math.PI*2);ctx.clip();ctx.drawImage(brand,70,207,170,170);ctx.restore();text('MATCHDAY',280,259,62,710,'#f3f6ef','left');text('TERMINAL',280,332,62,710,'#f3f6ef','left');text(title,60,420,title==='TOP 25 POWER RATINGS'?68:92,960,'#defa10','left');bodyText((mode==='ballot'?ballotEdition:edition).toUpperCase(),62,468,24,950,'#c8ced5');line(60,483,960);}

render=async function(){if(mode==='prediction')return oldRender();if(!ready)return;const rev=++revision;$('png').disabled=true;$('share').disabled=true;try{const items=isRanking()?rankingList():matchupList().flatMap(m=>[m.left,m.right]);const [brand,images]=await Promise.all([img(BRAND),Promise.all(items.map(t=>img(t.src)))]);if(rev!==revision)return;header(mode==='ballot'?'MY TOP 25 BALLOT':mode==='rankings'?'TOP 25 POWER RATINGS':mode==='upset'?'UPSET WATCH':'TOP 5 MATCHUPS',brand);

if(isRanking()){rankingList().forEach((r,i)=>{const col=i%5,row=Math.floor(i/5),x=60+col*194,y=520+row*198;ctx.fillStyle=i===0?'#192019':'#10161d';ctx.fillRect(x,y,180,184);text(String(i+1).padStart(2,'0'),x+25,y+26,27,43,'#ffffff');contain(images[i],x+22,y+43,136,112);if(mode==='rankings'&&r.detail.trim())bodyText(r.detail,x+90,y+166,29,155,'#f3f6ef','center')});}

else if(mode==='upset'){upsets.forEach((m,i)=>{const y=510+i*328;
teamPanel(m.left,60,y,480,310);teamPanel(m.right,540,y,480,310);
text(String(i+1).padStart(2,'0'),108,y+36,42,75,'#ffffff');
bodyText('ON ALERT',320,y+36,23,280,'#ffffff','center');bodyText('CHALLENGER',790,y+36,23,360,'#ffffff','center');
for(const [item,im,x] of [[m.left,images[i*2],200],[m.right,images[i*2+1],670]]){ctx.save();if(item.team!=='iowa'){ctx.shadowColor='#ffffff';ctx.shadowBlur=0;for(const [dx,dy] of [[-2,0],[2,0],[0,-2],[0,2]]){ctx.shadowOffsetX=dx;ctx.shadowOffsetY=dy;contain(im,x,y+65,240,145)}}ctx.restore();contain(im,x,y+65,240,145)}
ctx.fillStyle='#070a0f';ctx.beginPath();ctx.arc(540,y+140,43,0,Math.PI*2);ctx.fill();bodyText('VS',540,y+140,34,72,'#ffffff','center');
bodyText(m.left.name.toUpperCase(),320,y+244,36,400,'#ffffff','center');bodyText(m.right.name.toUpperCase(),790,y+244,36,400,'#ffffff','center');
if(m.detail)bodyText(m.detail.toUpperCase(),540,y+286,24,850,'#ffffff','center');
});}
else{matchups.forEach((m,i)=>{const y=505+i*218;
teamPanel(m.left,60,y,480,204);teamPanel(m.right,540,y,480,204);
text(String(i+1).padStart(2,'0'),112,y+43,52,85,'#ffffff','center');
ctx.save();ctx.shadowColor='#ffffff';ctx.shadowBlur=0;for(const [dx,dy] of [[-3,0],[3,0],[0,-3],[0,3],[-2,-2],[2,-2],[-2,2],[2,2]]){ctx.shadowOffsetX=dx;ctx.shadowOffsetY=dy;if(m.left.team!=='iowa')contain(images[i*2],201,y+8,238,122);if(m.right.team!=='iowa')contain(images[i*2+1],671,y+8,238,122)}ctx.restore();contain(images[i*2],201,y+8,238,122);contain(images[i*2+1],671,y+8,238,122);
bodyText(m.left.name.toUpperCase(),320,y+151,36,335,'#ffffff','center');bodyText(m.right.name.toUpperCase(),790,y+151,36,335,'#ffffff','center');
ctx.fillStyle='#070a0f';ctx.beginPath();ctx.moveTo(540,y+52);ctx.lineTo(591,y+103);ctx.lineTo(540,y+154);ctx.lineTo(489,y+103);ctx.closePath();ctx.fill();
bodyText('VS',540,y+103,37,80,'#ffffff','center');if(m.detail){ctx.fillStyle='rgba(0,0,0,.55)';ctx.fillRect(60,y+175,960,29);bodyText(m.detail.toUpperCase(),540,y+190,23,830,'#ffffff','center')}
});}


line(60,mode==='matchups'?1630:1540,960);text((mode==='upset'?upsetFooter:mode==='ballot'?ballotFooter:footer).toUpperCase(),540,mode==='matchups'?1685:1614,43,950,'#defa10');scheduleExport(rev);}catch(e){$('status').textContent=e.message}};

$('format').onchange=()=>{mode=$('format').value;buildControls();render()};

$('png').onclick=()=>{if(exportBlob)download(exportBlob,'Matchday-'+mode+'.png')};

$('share').onclick=async()=>{if(!exportBlob)return;const file=new File([exportBlob],'Matchday-'+mode+'.png',{type:'image/png'});try{if(navigator.canShare?.({files:[file]}))await navigator.share({files:[file],title:'Matchday '+modes[mode]});else download(exportBlob,file.name)}catch(e){if(e.name!=='AbortError')$('status').textContent='Use Download PNG to save this graphic.'}};

$('save').textContent='Save edition';$('load').textContent='Load edition';

$('save').onclick=()=>download(new Blob([JSON.stringify(mode==='prediction'?oldSnapshot():{version:2,mode,edition,footer,rankings,ballot,matchups,upsets,upsetFooter,ballotEdition,ballotFooter})],{type:'application/json'}),'Matchday-'+mode+'.json');

$('loadFile').onchange=async e=>{const f=e.target.files[0];if(!f)return;try{const d=JSON.parse(await f.text());if(d.version===1){mode='prediction';$('format').value=mode;buildControls();await oldLoad(e);return}if(d.version!==2||!['rankings','ballot','matchups','upset'].includes(d.mode)||d.rankings?.length!==25||d.matchups?.length!==5)throw Error();if(d.ballot!==undefined&&(!Array.isArray(d.ballot)||d.ballot.length!==25))throw Error();if(d.mode==='ballot'&&!d.ballot)throw Error();if(d.upsets!==undefined&&(!Array.isArray(d.upsets)||d.upsets.length!==3||d.upsets.some(m=>!m||typeof m.detail!=='string')))throw Error();if(d.mode==='upset'&&!d.upsets)throw Error();const all=[...(d.upsets||[]).flatMap(m=>[m.left,m.right]),...(d.ballot||[]),...d.rankings,...d.matchups.flatMap(m=>[m.left,m.right])];if(all.some(x=>!x||typeof x.name!=='string'||typeof x.src!=='string'||!x.src.startsWith('data:image/')))throw Error();if(typeof d.edition!=='string'||typeof d.footer!=='string'||d.rankings.some(x=>typeof x.detail!=='string')||d.matchups.some(x=>typeof x.detail!=='string'))throw Error();await Promise.all(all.map(t=>img(t.src)));rankings=d.rankings;ballot=d.ballot||rankings.map(r=>({...r,detail:''}));matchups=d.matchups;if(d.upsets)upsets=d.upsets;if(typeof d.upsetFooter==='string')upsetFooter=d.upsetFooter.slice(0,44);edition=d.edition.slice(0,38);footer=d.footer.slice(0,44);ballotEdition=typeof d.ballotEdition==='string'?d.ballotEdition.slice(0,38):d.edition.slice(0,38);ballotFooter=typeof d.ballotFooter==='string'?d.ballotFooter.slice(0,44):d.footer.slice(0,44);mode=d.mode;$('format').value=mode;buildControls();render()}catch{$('status').textContent='Could not load this edition. Choose a saved Matchday JSON file.'}e.target.value=''};

const drawGraphic=render;
let drawTimer=null, exportTimer=null, encoding=false;
function scheduleExport(rev){
 clearTimeout(exportTimer);
 exportTimer=setTimeout(function encodeLatest(){
  if(rev!==revision)return;
  if(encoding){exportTimer=setTimeout(encodeLatest,100);return}
  encoding=true;
  c.toBlob(b=>{encoding=false;if(rev!==revision)return;exportBlob=b;$('png').disabled=!b;$('share').disabled=!b;$('status').textContent=b?'Ready to save.':'Could not prepare image. Try editing again.'},'image/png');
 },600);
}
render=function(){
 clearTimeout(drawTimer);clearTimeout(exportTimer);++revision;exportBlob=null;
 $('png').disabled=true;$('share').disabled=true;
 $('status').textContent='Updating preview…';
 drawTimer=setTimeout(()=>{drawTimer=null;drawGraphic()},120);
};
buildControls();render();

