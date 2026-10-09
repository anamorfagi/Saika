// update_zones.js — правая панель делится на три зоны: верх (описания блока и гена, всегда на месте, не уезжает при прокрутке),
// центр (изменяемые параметры: кубики, полюса, правила, улики — прокручивается) и низ (грани характера, закреплён).
// Запуск: node update_zones.js (после update_head2). Правит gs.html.
const fs=require("fs");let t=fs.readFileSync("gs.html","utf8");
function rep(a,b){if(!t.includes(a)){console.error("не найдено:",a.slice(0,90));process.exit(1)}t=t.replace(a,b)}

// [1] верхняя зона — обёртка вокруг описаний
rep(`  <div class="eyebrow"><i style="background:\${hue(G.bi,70)}"></i>`,`  <div class="ghead"><div class="eyebrow"><i style="background:\${hue(G.bi,70)}"></i>`);
rep(`  <p class="gdesc">\${gt(geneDesc(G.id))||"<span class=unc>Описание не написано.</span>"}</p>`,
    `  <p class="gdesc">\${gt(geneDesc(G.id))||"<span class=unc>Описание не написано.</span>"}</p></div>`);
// [2] стили зон
rep(`.body{padding:44px 56px 90px 44px;`,`.body{padding:0 56px 40px 44px;`);
rep(`.facetcap{font:11px/1.5 var(--fm);color:var(--dim);margin:0 0 6px}`,
`.facetcap{font:11px/1.5 var(--fm);color:var(--dim);margin:0 0 6px}
.ghead{position:sticky;top:0;z-index:3;background:var(--bg);margin:0 -56px 0 -44px;padding:34px 56px 14px 44px}
.ghead .bdesc{margin-top:8px}`);
fs.writeFileSync("gs.html",t);console.log("zones ok");
