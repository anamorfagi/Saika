// update_fit.js — карточка гена целиком помещается между шапкой и гранями: тексты уплотнены, а нижний край
// средней зоны растворяется, чтобы обрезанная строка не лезла под подвал с гранями.
// Запуск: node update_fit.js (после update_zones). Правит gs.html.
const fs=require("fs");let t=fs.readFileSync("gs.html","utf8");
function rep(a,b){if(!t.includes(a)){console.error("не найдено:",a.slice(0,90));process.exit(1)}t=t.replace(a,b)}

// [1] верхняя зона плотнее: описание блока и гена — тот же текст, меньше воздуха
rep(`.bdesc{height:98px;overflow:hidden}`,`.bdesc{height:auto;font-size:12.5px;line-height:1.45}`);
rep(`.gdesc{font:15px/1.5 var(--fd);color:var(--text);margin:0 0 18px;max-width:none;height:96px`,
    `.gdesc{font:14.5px/1.5 var(--fd);color:var(--text);margin:0 0 10px;max-width:none;height:auto`);
rep(`.ghead{position:sticky;top:0;z-index:3;background:var(--bg);margin:0 -56px 0 -44px;padding:34px 56px 14px 44px}`,
    `.ghead{position:sticky;top:0;z-index:3;background:var(--bg);margin:0 -56px 0 -44px;padding:24px 56px 8px 44px}`);
rep(`.body h2{height:52px;display:flex;align-items:flex-end;`,`.body h2{margin:10px 0 2px;display:block;`);
// [2] средняя зона: меньше отступов у правил и улик, мягкий нижний край
rep(`.ev{margin-top:24px}`,`.ev{margin-top:16px}`);
rep(`.q{display:grid;grid-template-columns:52px 1fr;gap:12px;padding:4px 0}`,`.q{display:grid;grid-template-columns:78px 1fr;gap:10px;padding:2px 0}.q b{white-space:nowrap;overflow:hidden}`);
rep(`.body{padding:0 56px 40px 44px;`,`.body{padding:0 56px 18px 44px;-webkit-mask-image:linear-gradient(to bottom,#000 calc(100% - 22px),transparent 100%);mask-image:linear-gradient(to bottom,#000 calc(100% - 22px),transparent 100%);`);
rep(`.strip{margin-top:14px}`,`.strip{margin-top:6px}`);
fs.writeFileSync("gs.html",t);console.log("fit ok");
