// update_tail.js — карточка гена: убраны строки-дубли под кубиками (значение, «предполагается») и нижняя навигация
// «предыдущий/следующий» (ген переключается колесом и кликом по спирали). Цифры и источник предположения переехали
// в раздел «Откуда это значение» — туда, где им место.
// Запуск: node update_tail.js (после update_compact). Правит gs.html.
const fs=require("fs");let t=fs.readFileSync("gs.html","utf8");
function rep(a,b){if(!t.includes(a)){console.error("не найдено:",a.slice(0,90));process.exit(1)}t=t.replace(a,b)}

// [1] строки-дубли под кубиками — вон
rep(`  <div class="gline">\${G.c?\`<b>\${G.v>0?"+":""}\${G.v.toFixed(2)}</b> <em>\${LEVELS[L].toLowerCase()}</em> · уверенность \${G.c.toFixed(2)} · улик \${G.ev.filter(e=>e[0]!=="v").length}\`:\`<b class="unc">не снято</b> <em>улик нет, ген ждёт захвата</em>\`} · каналы: \${G.ch.split(",").filter(Boolean).map(c=>(CHAN[c]||c)).join(", ")}</div>
  \${G.pc?\`<div class="gline pred">\${G.c?(Math.abs(G.v-G.pv)<=.35?"сходится с предположением":"расходится с предположением"):"предполагается"} <b>\${G.pv>0?"+":""}\${G.pv.toFixed(2)}</b> <em>уверенность \${G.pc.toFixed(2)}</em> · из: \${G.pfrom.join(", ")}</div>\`:""}`,``);

// [2] цифры и предположение — в раздел с уликами
rep(`  <div class="ev"><h3>Откуда это значение</h3>\${G.ev.length?`,
`  <div class="ev"><h3>Откуда это значение</h3>
  <div class="gline">\${G.c?\`<b>\${G.v>0?"+":""}\${G.v.toFixed(2)}</b> <em>\${LEVELS[L].toLowerCase()}</em> · уверенность \${G.c.toFixed(2)} · улик \${G.ev.filter(e=>e[0]!=="v").length}\`:\`<b class="unc">не снято</b>\`} · каналы: \${G.ch.split(",").filter(Boolean).map(c=>(CHAN[c]||c)).join(", ")}\${G.pc?\` · \${G.c?(Math.abs(G.v-G.pv)<=.35?"сходится с предположением":"расходится с предположением"):"предполагается"} \${G.pv>0?"+":""}\${G.pv.toFixed(2)} (\${G.pc.toFixed(2)}) из: \${G.pfrom.join(", ")}\`:""}</div>
  \${G.ev.length?`);
rep(`.gline{font:11px/1.6 var(--fm);color:var(--dim);margin-top:14px}`,`.gline{font:11px/1.6 var(--fm);color:var(--dim);margin:2px 0 12px}`);

// [3] нижняя навигация не нужна — ген листается колесом и кликом по спирали
rep(`<div class="pn"><button id="prev">← предыдущий</button><button id="next">следующий →</button></div>`,
`<div class="pn" hidden><button id="prev">← предыдущий</button><button id="next">следующий →</button></div>`);
fs.writeFileSync("gs.html",t);console.log("tail ok");
