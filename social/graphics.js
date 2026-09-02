const W = 1600, H = 900;
const C = { bg: "#070a0f", panel: "#121821", panel2: "#172030", line: "#2b3543", text: "#e7edf4", muted: "#7e8a9a", signal: "#3ad17a", blue: "#4cc2ff", warn: "#ffb02e", loss: "#ff5d6c" };
const data = window.MATCHDAY_SOCIAL;

function setup(canvas) { canvas.width=W; canvas.height=H; const x=canvas.getContext("2d"); x.textBaseline="middle"; return x; }
function rect(x,a,b,c,d,r=0,fill=C.panel,stroke=null){x.beginPath();x.roundRect(a,b,c,d,r);x.fillStyle=fill;x.fill();if(stroke){x.strokeStyle=stroke;x.lineWidth=1;x.stroke();}}
function text(x,s,a,b,size=28,color=C.text,weight=600,align="left",family="Arial"){x.font=`${weight} ${size}px ${family}`;x.fillStyle=color;x.textAlign=align;x.fillText(s,a,b);}
function brand(x,title,subtitle){
  rect(x,28,28,1544,844,18,C.panel,"#283240");
  x.beginPath();x.arc(78,82,25,0,Math.PI*2);x.strokeStyle="#d7ff22";x.lineWidth=4;x.stroke();text(x,"M",78,83,24,C.text,900,"center");
  text(x,"COLLEGE MATCHDAY",124,72,20,C.signal,800);text(x,subtitle,124,101,16,C.muted,500);
  text(x,data.season,1536,76,18,C.muted,800,"right","monospace");text(x,title,56,162,55,C.text,900);
}
function initials(name){return name.split(/\s+/).filter(w=>!/[&]/.test(w)).slice(0,2).map(w=>w[0]).join("").toUpperCase();}
function logo(x,name,cx,cy,r=20){x.beginPath();x.arc(cx,cy,r,0,Math.PI*2);x.fillStyle="#253246";x.fill();text(x,initials(name),cx,cy+1,Math.max(10,r*.55),C.text,800,"center");}
function footer(x,label){x.strokeStyle="#26303d";x.beginPath();x.moveTo(56,807);x.lineTo(1544,807);x.stroke();text(x,label,56,837,15,C.muted,700,"left","monospace");text(x,`${data.published}  ·  @CollegeMatchday`,1544,837,15,C.muted,700,"right","monospace");}
function top25(canvas){const x=setup(canvas);brand(x,"MODEL TOP 25","Football · weekly ratings");text(x,"OPPONENT-ADJUSTED SCORING MARGIN",430,162,16,C.muted,800,"left","monospace");
  data.top25.forEach((row,i)=>{const col=i<13?0:1, j=col?i-13:i, ox=56+col*764, oy=222+j*42;if(i<4)rect(x,ox-10,oy-18,735,36,9,"#172132");text(x,String(i+1),ox+2,oy,18,i<4?C.signal:C.muted,800,"left","monospace");logo(x,row[0],ox+66,oy,14);text(x,row[0],ox+94,oy,21,C.text,500);text(x,`+${row[1].toFixed(1)}`,ox+720,oy,19,i<4?C.text:C.muted,800,"right","monospace");});footer(x,"Model ratings · logos load from social/logos when supplied");}
function upset(canvas){const x=setup(canvas);brand(x,"UPSET WATCH","One game · model vs market");text(x,data.upset.eyebrow,56,220,17,C.warn,900,"left","monospace");
  rect(x,56,254,1488,405,16,"#0d131c","#323d4c");text(x,data.upset.underdog,160,348,58,C.text,900);text(x,"MODEL PICK",160,405,17,C.signal,900,"left","monospace");text(x,"VS",800,392,21,C.muted,800,"center","monospace");text(x,data.upset.favorite,1440,348,58,C.muted,900,"right");
  logo(x,data.upset.underdog,105,350,34);logo(x,data.upset.favorite,1495,350,34);
  rect(x,145,472,350,126,12,"#142118","#295b3c");text(x,"MATCHDAY MODEL",173,501,15,C.muted,800,"left","monospace");text(x,`${data.upset.modelPct.toFixed(1)}%`,173,550,42,C.signal,900);rect(x,625,472,350,126,12,C.panel,"#303b4a");text(x,"MARKET",653,501,15,C.muted,800,"left","monospace");text(x,`${data.upset.marketPct.toFixed(1)}%`,653,550,42,C.text,900);rect(x,1105,472,300,126,12,"#241c10","#69501d");text(x,"UNDERDOG PRICE",1133,501,15,C.muted,800,"left","monospace");text(x,data.upset.line,1133,550,42,C.warn,900);
  text(x,`${data.upset.kickoff}  ·  ${data.upset.network}`,56,706,19,C.text,800,"left","monospace");text(x,data.upset.note,56,753,21,C.muted,500);footer(x,"Live model read · confirm the final locked pick before posting");}
function slate(canvas){const x=setup(canvas);brand(x,"TOP 5 SLATE","Weekend watchlist · editorial");text(x,"PURE WATCHABILITY · RIVALRY · STAKES · ATMOSPHERE",56,218,17,C.blue,900,"left","monospace");
  data.slate.forEach((g,i)=>{const y=270+i*101;rect(x,56,y-38,1488,82,12,i===0?"#162234":C.panel,"#2b3543");text(x,String(g.rank),86,y+2,34,i===0?C.signal:C.muted,900,"center","monospace");text(x,g.away,140,y-10,28,C.text,900);text(x,"AT",420,y-10,17,C.muted,800,"center","monospace");text(x,g.home,470,y-10,28,C.text,900);text(x,g.hook,470,y+22,16,C.blue,700);text(x,g.time,1508,y,20,C.muted,800,"right","monospace");});footer(x,"Fan slate · editorial ranking, separate from model picks");}

const renderers={top25,upset,slate};document.querySelectorAll("canvas[data-graphic]").forEach(c=>renderers[c.dataset.graphic](c));
document.querySelectorAll("button[data-download]").forEach(b=>b.onclick=()=>{const c=document.querySelector(`canvas[data-graphic='${b.dataset.download}']`);const a=document.createElement("a");a.download=`matchday-${b.dataset.download}-${data.published}.png`;a.href=c.toDataURL("image/png");a.click();});
