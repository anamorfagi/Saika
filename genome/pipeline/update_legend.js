// update_legend.js — карточка гена: строка под кубиками больше не дублирует то, что написано ниже (только позиция в блоке,
// имя и значения — при наведении на кубик); легенда граней уезжает в самый низ карточки и получает своё описание.
// Запуск: node update_legend.js (после update_facets2). Правит gs.html.
const fs=require("fs");let t=fs.readFileSync("gs.html","utf8");
function rep(a,b){if(!t.includes(a)){console.error("не найдено:",a.slice(0,80));process.exit(1)}t=t.replace(a,b)}

// [1] вырезать легенду граней из-под кубиков
const L0=t.indexOf(`\${["к другим","чувства","ум","близость"].map(gr=>`);
if(L0<0){console.error("нет легенды граней");process.exit(1)}
const L1=t.indexOf(`).join("")}`,t.indexOf(`</div>\``,L0))+`).join("")}`.length;
const LEG=t.slice(L0,L1);
t=t.slice(0,L0)+t.slice(L1);

// [2] строка под кубиками — только позиция; всё остальное появляется при наведении
rep(`<div class="binhover" id="binhover"><b>\${G.name}</b> · \${G.c?(G.v>0?"+":"")+G.v.toFixed(2)+" снято":"не снято"}\${G.pc?" · предполагается "+(G.pv>0?"+":"")+G.pv.toFixed(2):""} · <span>\${G.b.genes.indexOf(G.b.genes.find(g=>g[0]===G.id))+1} из \${G.b.genes.length} в блоке «\${G.b.name}»</span></div>`,
`<div class="binhover" id="binhover"><span>\${G.b.genes.indexOf(G.b.genes.find(g=>g[0]===G.id))+1} из \${G.b.genes.length} в блоке «\${G.b.name}» · наведи на кубик — увидишь соседний ген</span></div>`);

// [3] грани — постоянная подвал-панель справа: одна и та же на каждом гене, текст под кубиками не пляшет
rep(`<div class="pn"><button id="prev">← предыдущий</button><button id="next">следующий →</button></div>`,
`<div class="pn"><button id="prev">← предыдущий</button><button id="next">следующий →</button></div>
        <div class="facetsfoot" id="facetsFoot"></div>`);
rep(`renderChars();\n`,`renderChars();
// подвал с гранями рисуется один раз на персонажа: состав и род не зависят от выбранного гена
{const ff=document.getElementById("facetsFoot");if(ff)ff.innerHTML='<div class="facetcap">Грани характера: цвет кубика — грань, в которую попал ген; из них собирается контур персонажа в шапке. Наведи на название — что она значит.</div>'+["к другим","чувства","ум","близость"].map(gr=>'<div class="binname legend3"><em>'+gr+'</em>'+FACETS.filter(f=>f.grp===gr).map(f=>'<span title="'+f.t+'"><i class="sw" style="background:rgb('+f.rgb+')"></i>'+gt(f.n)+'</span>').join("")+'</div>').join("")}
`);
// [4] стили
rep(`.binhover{margin-top:8px;`,`.facetcap{font:11px/1.5 var(--fm);color:var(--dim);margin:0 0 6px}
.facetsfoot{padding:10px 56px 12px 44px;background:var(--bg)}
.binhover{margin-top:8px;`);
fs.writeFileSync("gs.html",t);console.log("legend ok");
