// update_axis.js — карточка гена: полюса, семисегментная шкала и ползунок показывали одно и то же значение тремя разными способами.
// Теперь одна ось: подписи полюсов сверху, дорожка с 7 отметками уровней, на ней — ползунок (снятое) и пунктирная метка (предполагаемое).
// Запуск: node update_axis.js (после update_bins). Правит gs.html.
const fs=require("fs");let t=fs.readFileSync("gs.html","utf8");
function rep(a,b){if(!t.includes(a)){console.error("не найдено:",a.slice(0,80));process.exit(1)}t=t.replace(a,b)}
// [1] полюса + шкала → одна ось с ползунком внутри
rep(`  <div class="poles"><div class="\${G.v<0?'on':'off'}"><span>−1</span>\${gt(G.neg)}</div><div class="mid \${Math.abs(G.v)<.15?'on':'off'}"><span>0</span>как у всех</div><div class="\${G.v>0?'on':'off'}"><span>+1</span>\${gt(G.pos)}</div></div>
  <div class="scale">\${[0,1,2,3,4,5,6].map(k=>\`<i class="\${k===L?'on':''}" style="\${k===L?'background:rgb('+toneRGB(G)+')':''}"></i>\`).join("")}</div>`,
`  <div class="axis"><div class="poles"><div class="\${G.v<0?'on':'off'}"><span>−1</span>\${gt(G.neg)}</div><div class="mid \${Math.abs(G.v)<.15?'on':'off'}"><span>0</span>как у всех</div><div class="\${G.v>0?'on':'off'}"><span>+1</span>\${gt(G.pos)}</div></div>
  <div class="track"><div class="scale">\${[0,1,2,3,4,5,6].map(k=>\`<i class="\${k===L?'on':''}" style="\${k===L?'background:rgb('+toneRGB(G)+')':''}" title="\${LEVELS[k]}"></i>\`).join("")}</div>
    \${G.pc?\`<i class="pmark" style="left:\${((G.pv+1)*50).toFixed(1)}%;border-color:rgb(\${toneRGB({v:G.pv,id:G.id,c:1})})" title="предполагается \${G.pv>0?"+":""}\${G.pv.toFixed(2)}"></i>\`:""}
    <input type="range" class="gslider" id="gslider" min="-1" max="1" step="0.05" value="\${G.v}" aria-label="значение гена"></div></div>`);
// старый ползунок внизу — убрать
rep(`  <input type="range" class="gslider" id="gslider" min="-1" max="1" step="0.05" value="\${G.v}" aria-label="значение гена">
`,``);
// при перетаскивании — подсвечивать сегмент уровня на той же оси
rep(`sl.oninput=()=>{G.v=+sl.value;commit();`,`sl.oninput=()=>{G.v=+sl.value;commit();{const L2=lvl(G.v);document.querySelectorAll(".axis .scale i").forEach((el,k)=>{el.classList.toggle("on",k===L2);el.style.background=k===L2?"rgb("+toneRGB(G)+")":""});document.querySelectorAll(".axis .poles>div").forEach((d,k)=>{const on=k===0?G.v<0:k===1?Math.abs(G.v)<.15:G.v>0;d.classList.toggle("on",on);d.classList.toggle("off",!on)})}`);
// [2] стили
rep(`.scale{display:grid;grid-template-columns:repeat(7,1fr);gap:4px}`,`.axis{margin-top:14px}.axis .poles{margin-top:0}
.axis .track{position:relative;height:28px;margin-top:8px}
.axis .scale{position:absolute;left:0;right:0;top:12px;display:grid;grid-template-columns:repeat(7,1fr);gap:4px;pointer-events:none}
.axis .gslider{position:absolute;left:0;right:0;top:4px;margin:0;height:18px;width:100%}
.axis .gslider::-webkit-slider-runnable-track{background:none;height:2px}
.axis .pmark{position:absolute;top:6px;width:0;height:14px;border-left:2px dashed;opacity:.8;transform:translateX(-1px);pointer-events:none}
.scale{display:grid;grid-template-columns:repeat(7,1fr);gap:4px}`);
fs.writeFileSync("gs.html",t);console.log("axis ok");
