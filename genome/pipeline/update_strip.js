// update_strip.js — карточка гена: ОДНА полоса. Горизонтальная ось (0 — «как у всех»), гены блока — столбики вверх (+) или вниз (−) от оси,
// текущий выделен и тянется мышью вверх/вниз (это и есть регулятор); пунктирный контур — предполагаемое. Отдельная шкала −1…+1 и ползунок убраны.
// Запуск: node update_strip.js (после update_axis). Правит gs.html.
const fs=require("fs");let t=fs.readFileSync("gs.html","utf8");
function rep(a,b){if(!t.includes(a)){console.error("не найдено:",a.slice(0,80));process.exit(1)}t=t.replace(a,b)}

// [1] убрать ось с полюсами/сегментами/ползунком; оставить скрытый input — на нём держится логика правок (commit/оninput/onchange)
const a0=t.indexOf(`  <div class="axis"><div class="poles">`),a1=t.indexOf(`aria-label="значение гена"></div></div>`,a0);
if(a0<0||a1<0){console.error("нет блока axis");process.exit(1)}
t=t.slice(0,a0)+`  <input type="range" class="gslider" id="gslider" min="-1" max="1" step="0.05" value="\${G.v}" aria-label="значение гена" hidden>`+t.slice(a1+`aria-label="значение гена"></div></div>`.length);
// [2] столбики → полоса с осью посередине; полюса подписаны у оси справа сверху/снизу
const b0=t.indexOf(`  <div class="bins">\${G.b.genes.map(g=>byId[g[0]]).map(X=>`),b1=t.indexOf(`</div>`,t.indexOf(`</button>\`).join("")}`,b0))+6;
if(b0<0){console.error("нет bins");process.exit(1)}
t=t.slice(0,b0)+`  <div class="strip"><div class="plab top"><b>+1</b> \${gt(G.pos)}</div>
  <div class="bins">\${G.b.genes.map(g=>byId[g[0]]).map(X=>{const h=v=>Math.round(Math.abs(v)*50);const col=X.c?toneRGB(X):"140,132,150";const pcol=toneRGB({v:X.pv,id:X.id,c:1});
    return \`<button data-i="\${X.i}" class="\${X.c===0?'none':'f'} \${X.i===G.i?'cur':''}" title="\${X.name}: снято \${X.c?(X.v>0?'+':'')+X.v:'—'} · предполагается \${X.pc?(X.pv>0?'+':'')+X.pv:'—'}" aria-label="\${X.name}">
      \${X.pc?\`<i class="pr \${X.pv>=0?'up':'dn'}" style="height:\${h(X.pv)}%;border-color:rgb(\${pcol})"></i>\`:""}
      <i class="m \${X.v>=0?'up':'dn'}" style="height:\${X.c?h(X.v):0}%;background:rgb(\${col})"></i></button>\`}).join("")}</div></div>`+t.slice(b1);
// подпись «снято/предполагается» под полосой оставляем как была (binname dna)
// [3] перетаскивание текущего столбика = регулятор; значения идут через скрытый gslider, чтобы работали commit и перерисовка
rep(`  const sl=document.getElementById("gslider");`,`  {const sl0=document.getElementById("gslider");const bins=document.querySelector(".strip .bins");const cur=bins&&bins.querySelector("button.cur");
    if(cur){cur.style.cursor="ns-resize";cur.onpointerdown=e=>{e.preventDefault();cur.setPointerCapture(e.pointerId);let moved=false;const y0=e.clientY,v0=G.v;
      const set=ev=>{let v=v0+(y0-ev.clientY)/60;v=Math.max(-1,Math.min(1,Math.round(v*20)/20));if(+sl0.value!==v){sl0.value=v;sl0.dispatchEvent(new Event("input"))};const m=cur.querySelector("i.m");if(m){m.className="m "+(v>=0?"up":"dn");m.style.height=Math.round(Math.abs(v)*50)+"%";m.style.background="rgb("+toneRGB(G)+")"}cur.classList.remove("none")};
      cur.onpointermove=ev=>{moved=true;set(ev)};cur.onpointerup=ev=>{cur.onpointermove=null;cur.onpointerup=null;if(moved){sl0.dispatchEvent(new Event("change"))}};};
      cur.onclick=e=>{e.stopPropagation()}}}
  const sl=document.getElementById("gslider");`);
// старый oninput трогал столбик по высоте от низа — теперь высота от оси: заменить
rep(`const bar=document.querySelector(".bins button.cur");if(bar){bar.style.height=Math.round(6+Math.abs(G.v)*50)+"px";bar.style.background="rgb("+toneRGB(G)+")";bar.classList.remove("none")}`,
`const bar=document.querySelector(".bins button.cur");if(bar){bar.classList.remove("none");const m=bar.querySelector("i.m");if(m){m.className="m "+(G.v>=0?"up":"dn");m.style.height=Math.round(Math.abs(G.v)*50)+"%";m.style.background="rgb("+toneRGB(G)+")"}}`);
// [4] стили полосы
rep(`.bins{height:auto;min-height:22px;margin-top:16px}`,`.strip{margin-top:14px}
.strip .plab{font:9.5px var(--fm);color:var(--dim);letter-spacing:.04em;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;text-align:right}.strip .plab.top{margin-bottom:6px}.strip .plab.bot{margin-top:6px}.strip .plab b{color:var(--muted);font-weight:500;margin-right:5px}.strip .plab em{font-style:normal;margin:0 8px;opacity:.5}
.strip .bins{position:relative;height:124px;min-height:0;margin:0;display:flex;gap:6px;align-items:stretch}
.strip .bins button{position:relative;flex:1;min-width:0;height:100%;background:none!important;border-radius:0;opacity:1;box-shadow:none;padding:0}.strip .bins button.cur{cursor:ns-resize}
.strip .bins button i.m{position:absolute;left:0;right:0;display:block;border-radius:2px;opacity:.45;min-height:0}.strip .bins button i.m.up{bottom:50%}.strip .bins button i.m.dn{top:50%}
.strip .bins button.cur i.m{opacity:1;box-shadow:0 0 0 1px var(--text)}.strip .bins button.none i.m{background:var(--hair2)!important;height:3px!important;opacity:.7;top:calc(50% - 1px)}
.strip .bins button i.pr{position:absolute;left:1px;right:1px;display:block;border:1px dashed;border-radius:2px;opacity:.55;pointer-events:none}.strip .bins button i.pr.up{bottom:50%;border-bottom:0}.strip .bins button i.pr.dn{top:50%;border-top:0}
.strip .bins button:hover i.m{opacity:.85}
.bins{height:auto;min-height:22px;margin-top:16px}`);
// −1 — в одну строку с легендой (легенда слева, полюс справа)
rep(`<div class="binname dna"><span><i class="sw f"></i>снято по уликам</span><span><i class="sw p"></i>предполагается по другим генам и архетипам</span></div>`,`<div class="binname dna"><span><i class="sw f"></i>снято по уликам</span><span><i class="sw p"></i>предполагается по другим генам и архетипам</span><span class="plab bot"><b>−1</b> \${gt(G.neg)}</span></div>`);
rep(`.binname.dna span{margin-right:14px}`,`.binname.dna{display:flex;align-items:center;margin-top:6px}.binname.dna span{margin-right:14px}.binname.dna .plab{margin:0 0 0 auto;font:9.5px var(--fm);color:var(--dim);letter-spacing:.04em;white-space:nowrap}.binname.dna .plab b{color:var(--muted);font-weight:500;margin-right:5px}`);
// [5] шапка карточки — фиксированной высоты (заголовок до 2 строк, описание до 3), чтобы кубики и всё ниже не скакали между генами
rep(`.gdesc{font:15px/1.5 var(--fd);color:var(--text);margin:-22px 0 26px;max-width:62ch}`,`.gdesc{font:15px/1.5 var(--fd);color:var(--text);margin:-22px 0 26px;max-width:62ch;height:68px;overflow:hidden;display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;cursor:default}.gdesc.long{cursor:pointer}.gdesc.open{height:auto;display:block;-webkit-line-clamp:none}
.body h2{min-height:96px;display:flex;align-items:flex-end}.bdesc{min-height:60px}.tonel{min-height:12px}`);
// длинное описание гена: 3 строки, клик — раскрыть (тогда сдвиг ниже — только по желанию)
rep(`  {const sl0=document.getElementById("gslider");`,`  {const gd=document.querySelector(".gdesc");if(gd&&gd.scrollHeight>gd.clientHeight+4){gd.classList.add("long");gd.title="раскрыть";gd.onclick=()=>{gd.classList.toggle("open");gd.title=gd.classList.contains("open")?"свернуть":"раскрыть"}}}
  {const sl0=document.getElementById("gslider");`);
fs.writeFileSync("gs.html",t);console.log("strip ok");
