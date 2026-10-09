// update_compact.js — карточка гена: три блока, повторявшие одно и то же значение (крупный уровень, «предполагается», плитки
// уверенность/улик/каналы), сворачиваются в две короткие строки. Освободившееся место занимает легенда граней.
// Запуск: node update_compact.js (после update_legend). Правит gs.html.
const fs=require("fs");let t=fs.readFileSync("gs.html","utf8");
function rep(a,b){if(!t.includes(a)){console.error("не найдено:",a.slice(0,90));process.exit(1)}t=t.replace(a,b)}

rep(`  <div class="lv"><b class="\${G.c===0?'unc':''}">\${G.c===0?'не снято':LEVELS[L]}</b><span>\${G.c===0?'улик нет — ген ждёт захвата по корпусу':\`\${G.v>0?"+":""}\${G.v.toFixed(2)} на шкале −1…+1, где 0 — обычный человек\`}</span></div>
  \${G.pc?\`<div class="lv pred"><b>\${G.c?(Math.abs(G.v-G.pv)<=.35?"сходится":"расходится"):"предполагается"}</b><span>\${G.pv>0?"+":""}\${G.pv.toFixed(2)} · уверенность \${G.pc.toFixed(2)} · из: \${G.pfrom.join(", ")}</span></div>\`:""}
  <div class="meta"><div><b>\${G.c.toFixed(2)}</b><span>уверенность</span></div><div><b>\${G.ev.filter(e=>e[0]!=="v").length}</b><span>улик</span></div><div><div class="ch">\${G.ch.split(",").filter(Boolean).map(c=>\`<em>\${CHAN[c]||c}</em>\`).join("")}</div><span>каналы</span></div></div>`,
`  <div class="gline">\${G.c?\`<b>\${G.v>0?"+":""}\${G.v.toFixed(2)}</b> <em>\${LEVELS[L].toLowerCase()}</em> · уверенность \${G.c.toFixed(2)} · улик \${G.ev.filter(e=>e[0]!=="v").length}\`:\`<b class="unc">не снято</b> <em>улик нет, ген ждёт захвата</em>\`} · каналы: \${G.ch.split(",").filter(Boolean).map(c=>(CHAN[c]||c)).join(", ")}</div>
  \${G.pc?\`<div class="gline pred">\${G.c?(Math.abs(G.v-G.pv)<=.35?"сходится с предположением":"расходится с предположением"):"предполагается"} <b>\${G.pv>0?"+":""}\${G.pv.toFixed(2)}</b> <em>уверенность \${G.pc.toFixed(2)}</em> · из: \${G.pfrom.join(", ")}</div>\`:""}`);
rep(`.binhover{margin-top:8px;`,`.gline{font:11px/1.6 var(--fm);color:var(--dim);margin-top:14px}.gline b{color:var(--text);font-size:13px}.gline b.unc{color:var(--muted)}.gline em{font-style:normal;color:var(--muted)}
.gline.pred{margin-top:3px;font-style:italic}
.binhover{margin-top:8px;`);
fs.writeFileSync("gs.html",t);console.log("compact ok");
