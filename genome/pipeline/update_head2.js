// update_head2.js — плотность карточки гена: название всегда в одну строку (шрифт сам ужимается под длинные имена),
// поэтому исчезает дыра над заголовком и текст не скачет; правила и улики идут плотнее.
// Запуск: node update_head2.js (после update_head). Правит gs.html.
const fs=require("fs");let t=fs.readFileSync("gs.html","utf8");
function rep(a,b){if(!t.includes(a)){console.error("не найдено:",a.slice(0,90));process.exit(1)}t=t.replace(a,b)}

// [1] заголовок — одна строка фиксированной высоты
rep(`.body h2{min-height:96px;display:flex;align-items:flex-end}`,`.body h2{height:52px;display:flex;align-items:flex-end;white-space:nowrap;overflow:hidden}`);
rep(`.body .id{font:11px var(--fm);color:var(--dim);margin-bottom:34px}`,`.body .id{font:11px var(--fm);color:var(--dim);margin-bottom:14px}`);
rep(`.gdesc{font:15px/1.5 var(--fd);color:var(--text);margin:-22px 0 26px;`,`.gdesc{font:15px/1.5 var(--fd);color:var(--text);margin:0 0 18px;`);
// подгонка кегля под ширину: длинные имена ужимаются, короткие остаются крупными
rep(`  const sl=document.getElementById("gslider");`,`  {const h=document.querySelector(".body h2");if(h){h.style.fontSize="";let fz=34;h.style.fontSize=fz+"px";
    while(h.scrollWidth>h.clientWidth&&fz>19){fz-=1;h.style.fontSize=fz+"px"}}}
  const sl=document.getElementById("gslider");`);
// [2] правила и улики — плотнее
rep(`.q{display:grid;grid-template-columns:64px 1fr;gap:16px;padding:12px 0}`,`.q{display:grid;grid-template-columns:52px 1fr;gap:12px;padding:4px 0}`);
rep(`.q p{margin:0;font:400 16px/1.5 var(--fd);color:var(--text)}`,`.q p{margin:0;font:400 14px/1.45 var(--fd);color:var(--text)}`);
rep(`.q b{font:500 10px var(--fm);letter-spacing:.12em;text-transform:uppercase;padding-top:5px}`,`.q b{font:500 10px var(--fm);letter-spacing:.12em;text-transform:uppercase;padding-top:3px}`);
rep(`.ev{margin-top:44px}`,`.ev{margin-top:24px}`);
fs.writeFileSync("gs.html",t);console.log("head2 ok");
