(function(){
  'use strict';
  const file=(location.pathname.split('/').pop()||'').toLowerCase();
  const map={
    'tactics-soccer.html':{sport:'soccer',comp:'ucl'},
    'tactics-football.html':{sport:'nfl',comp:'nfl'},
    'tactics-basketball.html':{sport:'basketball',comp:'nba'},
    'tactics-baseball.html':{sport:'baseball',comp:'mlb'},
    'tactics-hockey.html':{sport:'hockey',comp:'nhl'}
  };
  const context=map[file];if(!context)return;
  const style=document.createElement('style');
  style.textContent='.articleLoop{display:grid!important;grid-template-columns:repeat(2,minmax(0,1fr));gap:9px!important;margin:26px 0!important}.articleLoop a{padding:11px 12px!important;border:1px solid var(--line)!important;border-radius:10px!important;background:var(--panel)!important;color:var(--link)!important;font:700 .7rem/1.25 "JetBrains Mono",monospace!important;text-decoration:none!important}.articleLoop a:hover,.articleLoop a:focus-visible{border-color:var(--signal)!important;color:var(--signal)!important}.articleLoopLabel{grid-column:1/-1;color:var(--signal);font:800 .6rem/1 "JetBrains Mono",monospace;letter-spacing:.09em;text-transform:uppercase}@media(max-width:560px){.articleLoop{grid-template-columns:1fr}}';
  document.head.appendChild(style);
  const nav=document.createElement('nav');nav.className='articleLoop';nav.setAttribute('aria-label','Continue exploring');
  const query=value=>encodeURIComponent(value);
  nav.innerHTML=`<span class="articleLoopLabel">Continue with Matchday</span><a href="index.html?sport=${query(context.comp)}&view=matches">View matchup</a><a href="index.html?sport=${query(context.comp)}&view=edge">See model prediction</a><a href="index.html?sport=${query(context.comp)}&view=score">Open scorecard</a><a href="content.html?sport=${query(context.sport)}#latest">Explore similar games</a>`;
  const foot=document.querySelector('.foot'),wrap=document.querySelector('.wrap')||document.body;
  if(foot)foot.before(nav);else wrap.appendChild(nav);
})();
