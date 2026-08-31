// Public Matchday CFB record. Each row was locked before kickoff and settled
// from the same final scores used by the current-season standings below.
const MATCHDAY_CFB_SNAPSHOT={
  updated:'2026-08-31T00:41:38Z',
  news:[
    {headline:'College football Week 0: recaps, highlights, scores and more',published:'2026-08-30T03:20:00Z',source:'NCAA.com',feed:'College Football',link:'https://www.ncaa.com/live-updates/football/fbs/college-football-week-0-recaps-highlights-scores-and-more',competition:'NCAAF'},
    {headline:"Texas judge puts SEC's new eligibility rule on hold",published:'2026-08-27T20:46:14Z',source:'AP News',feed:'College Football',link:'https://apnews.com/article/7ab1b532d7e1b8309316d113493ae7de',competition:'NCAAF'},
    {headline:'SEC joins Big Ten in banning pros from returning to college, including basketball players',published:'2026-08-25T16:30:55Z',source:'AP News',feed:'College Sports',link:'https://apnews.com/article/f2a4b95071d634c22ffba31a56224085',competition:'NCAAF'}
  ],
  scorecard:{graded:8,model_hits:6,pending:0,picks:[
    {home:'TCU Horned Frogs',away:'North Carolina Tar Heels',pick_name:'TCU Horned Frogs',result:'MISS',model_hit:false},
    {home:'USC Trojans',away:'San José State Spartans',pick_name:'USC Trojans',result:'HIT',model_hit:true},
    {home:'Virginia Cavaliers',away:'NC State Wolfpack',pick_name:'Virginia Cavaliers',result:'HIT',model_hit:true},
    {home:'North Dakota State Bison',away:'Jacksonville State Gamecocks',pick_name:'North Dakota State Bison',result:'HIT',model_hit:true},
    {home:'Eastern Michigan Eagles',away:'Sacramento State Hornets',pick_name:'Eastern Michigan Eagles',result:'HIT',model_hit:true},
    {home:'Stanford Cardinal',away:"Hawai'i Rainbow Warriors",pick_name:'Stanford Cardinal',result:'HIT',model_hit:true},
    {home:'Florida State Seminoles',away:'New Mexico State Aggies',pick_name:'Florida State Seminoles',result:'HIT',model_hit:true},
    {home:'UNLV Rebels',away:'Memphis Tigers',pick_name:'UNLV Rebels',result:'MISS',model_hit:false}
  ]},
  bracket:[
    {round:'CFP First Round (Matchday projection)',matches:[
      {home:'Georgia Bulldogs',away:'BYU Cougars',home_slot:'5',away_slot:'12',status:'PROJECTED',score:{}},
      {home:'Miami Hurricanes',away:'Texas A&M Aggies',home_slot:'6',away_slot:'11',status:'PROJECTED',score:{}},
      {home:'Ole Miss Rebels',away:'Alabama Crimson Tide',home_slot:'7',away_slot:'10',status:'PROJECTED',score:{}},
      {home:'Texas Longhorns',away:'Texas Tech Red Raiders',home_slot:'8',away_slot:'9',status:'PROJECTED',score:{}}
    ]},
    {round:'CFP Quarter-finals (Matchday projection)',matches:[
      {home:'Indiana Hoosiers',away:'First-round winner',home_slot:'1',away_slot:'path',status:'PROJECTED',score:{}},
      {home:'Ohio State Buckeyes',away:'First-round winner',home_slot:'2',away_slot:'path',status:'PROJECTED',score:{}},
      {home:'Notre Dame Fighting Irish',away:'First-round winner',home_slot:'3',away_slot:'path',status:'PROJECTED',score:{}},
      {home:'Oregon Ducks',away:'First-round winner',home_slot:'4',away_slot:'path',status:'PROJECTED',score:{}}
    ]}
  ],
  records:[
    ['North Carolina Tar Heels','UNC',1,0,15,10],['USC Trojans','USC',1,0,42,26],['Virginia Cavaliers','UVA',1,0,34,8],
    ['North Dakota State Bison','NDSU',1,0,33,7],['Eastern Michigan Eagles','EMU',1,0,28,17],['Stanford Cardinal','STAN',1,0,37,27],
    ['Florida State Seminoles','FSU',1,0,34,17],['Memphis Tigers','MEM',1,0,27,21],['TCU Horned Frogs','TCU',0,1,10,15],
    ['San José State Spartans','SJSU',0,1,26,42],['NC State Wolfpack','NCSU',0,1,8,34],['Jacksonville State Gamecocks','JVST',0,1,7,33],
    ['Sacramento State Hornets','SAC',0,1,17,28],["Hawai'i Rainbow Warriors",'HAW',0,1,27,37],['New Mexico State Aggies','NMSU',0,1,17,34],['UNLV Rebels','UNLV',0,1,21,27]
  ].map((r,i)=>({name:r[0],code:r[1],pos:i+1,pld:1,w:r[2],d:0,l:r[3],gf:r[4],ga:r[5],gd:r[4]-r[5],pts:r[2],form:r[2]?'W':'L',record:`${r[2]}-${r[3]}`}))
};

const MATCHDAY_NCAAM_SNAPSHOT={
  updated:'2026-08-30',
  rankings:[
    ['Michigan Wolverines',40.06,37,3],['Duke Blue Devils',39.84,35,3],['Arizona Wildcats',37.54,36,3],['Illinois Fighting Illini',34.83,28,9],
    ['Florida Gators',34.76,27,8],['Houston Cougars',34.73,30,7],['Iowa State Cyclones',34.07,29,8],['Gonzaga Bulldogs',32.94,31,4],
    ['Purdue Boilermakers',31.97,30,9],['UConn Huskies',30.96,34,6],['Michigan State Spartans',29.8,27,8],['Vanderbilt Commodores',29.05,27,9],
    ['Tennessee Volunteers',28.84,25,12],['Saint Louis Billikens',28.72,29,6],['Virginia Cavaliers',28.47,30,6],['Louisville Cardinals',28.42,24,11],
    ['Nebraska Cornhuskers',28.25,28,7],['Alabama Crimson Tide',27.99,25,10],["St. John's Red Storm",27.78,30,7],['Arkansas Razorbacks',27.66,28,9],
    ["Saint Mary's Gaels",27.42,27,6],['Utah State Aggies',26.7,29,7],['Texas Tech Red Raiders',26.49,23,11],['Iowa Hawkeyes',25.7,24,13],['Kansas Jayhawks',25.37,24,11]
  ].map((r,i)=>({rank:i+1,name:r[0],model_score:r[1],record:`${r[2]}-${r[3]}`,bid:'At-large'}))
};
