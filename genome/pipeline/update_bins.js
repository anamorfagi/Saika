// update_bins.js — столбики блока в карточке гена: убраны вертикальные нечитаемые подписи; имя гена под столбиками — одной строкой
// при наведении/выборе; легенда граней (к другим · чувства · близость) — ровная сетка с одинаковыми колонками.
// Запуск: node update_bins.js (после update_dna). Правит gs.html.
const fs=require("fs");let t=fs.readFileSync("gs.html","utf8");
function rep(a,b){if(!t.includes(a)){console.error("не найдено:",a.slice(0,80));process.exit(1)}t=t.replace(a,b)}
// [1] вместо вертикальных подписей — строка с именем гена под столбиками (текущий; при наведении — наведённый)
rep(`  <div class="binnames">\${G.b.genes.map(g=>byId[g[0]]).map(X=>\`<span class="\${X.i===G.i?'cur':''}">\${X.name}</span>\`).join("")}</div>
  <div class="binname">гены блока «\${G.b.name}» по порядку · высота — сила · <b>\${G.b.genes.indexOf(G.b.genes.find(g=>g[0]===G.id))+1}</b> из \${G.b.genes.length}</div>`,
`  <div class="binhover" id="binhover"><b>\${G.name}</b> · \${G.c?(G.v>0?"+":"")+G.v.toFixed(2)+" снято":"не снято"}\${G.pc?" · предполагается "+(G.pv>0?"+":"")+G.pv.toFixed(2):""} · <span>\${G.b.genes.indexOf(G.b.genes.find(g=>g[0]===G.id))+1} из \${G.b.genes.length} в блоке «\${G.b.name}»</span></div>`);
// наведение на столбик — имя в строке; уход — обратно текущий
rep(`  const sl=document.getElementById("gslider");`,`  {const hv=document.getElementById("binhover");const base=hv?hv.innerHTML:"";document.querySelectorAll(".bins button").forEach(b=>{b.onmouseenter=()=>{const X=all[+b.dataset.i];if(!hv||!X)return;hv.innerHTML=\`<b>\${X.name}</b> · \${X.c?(X.v>0?"+":"")+X.v.toFixed(2)+" снято":"не снято"}\${X.pc?" · предполагается "+(X.pv>0?"+":"")+X.pv.toFixed(2):""} · <span>\${X.b.genes.findIndex(g=>g[0]===X.id)+1} из \${X.b.genes.length}</span>\`};b.onmouseleave=()=>{if(hv)hv.innerHTML=base}})}
  const sl=document.getElementById("gslider");`);
// [2] стили: столбики выше, строка имени, легенда сеткой
rep(`.binnames{display:flex;gap:6px;margin-top:5px}`,`.binhover{margin-top:8px;font:10.5px var(--fm);color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;min-height:14px}.binhover b{color:var(--text);font-weight:500}.binhover span{color:var(--dim)}
.binname.legend3{display:grid;grid-template-columns:64px repeat(7,minmax(0,1fr));gap:4px 8px;align-items:center;white-space:nowrap;margin-top:4px}.binname.legend3 em{grid-column:1}.binname.legend3 span:nth-child(9){grid-column:2}
.binname.legend3:first-of-type{margin-top:10px}
.bins{height:auto;min-height:22px;margin-top:16px}.tonel{margin-top:8px}.bins button{transition:opacity .2s,height .3s,box-shadow .15s}.bins button:hover{opacity:.85}
.binnames{display:none}`);
fs.writeFileSync("gs.html",t);console.log("bins ok");
