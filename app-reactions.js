/* Personal editorial stays separate from generated model research. */
window.renderReactions=function(){
  const host=document.getElementById('view-reactions');
  if(!host)return;
  const posts=window.MATCHDAY_REACTIONS||[];
  const dateLabel=value=>new Date(value+'T12:00:00').toLocaleDateString(undefined,{month:'long',day:'numeric',year:'numeric'});
  host.innerHTML=`<section class="reactionsPage"><header class="viewIntro reactionIntro"><div><h1 class="vhead">Matchday Reactions</h1><p>Personal reflections on the week in college sports: the wins, the misses, and the model behind the picks.</p></div><span>Weekly · Mondays</span></header>${posts.length?`<div class="reactionArchiveHead"><h2>Weekly reactions</h2><span>${posts.length} ${posts.length===1?'article':'articles'}</span></div><div class="reactionList">${posts.map((p,i)=>`<article class="reactionCard"><div class="reactionKicker">${i===0?'LATEST REACTION':'FROM THE ARCHIVE'} · <time datetime="${esc(p.date)}">${esc(dateLabel(p.date))}</time></div><h3><a href="reactions/${esc(p.slug)}.html">${esc(p.title)}</a></h3><p>${esc(p.summary)}</p><a class="reactionRead" href="reactions/${esc(p.slug)}.html" aria-label="Read reaction: ${esc(p.title)}">Read reaction <span aria-hidden="true">↗</span></a></article>`).join('')}</div>`:'<section class="reactionEmpty"><span class="reactionKicker">FIRST EDITION COMING SOON</span><h2>See you after the weekend.</h2><p>The first reaction will appear here once published: what the model got right, what hurt, and what comes next.</p></section>'}</section>`;
};
