// update_head.js — карточка гена: описание блока показывается целиком (раньше резалось до первого предложения и пряталось
// под «подробнее»), кнопка остаётся только там, где есть что раскрыть — во что блок компилируется. Внизу страницы
// добавлен отступ, чтобы последний раздел не упирался в край окна.
// Запуск: node update_head.js (после update_tail). Правит gs.html.
const fs=require("fs");let t=fs.readFileSync("gs.html","utf8");
function rep(a,b){if(!t.includes(a)){console.error("не найдено:",a.slice(0,90));process.exit(1)}t=t.replace(a,b)}

rep(`<p class="bdesc"><span class="short">\${gt(G.b.purpose.replace(/\\*+/g,"")).split(/(?<=\\.)\\s/)[0]}</span>`,
    `<p class="bdesc"><span class="short">\${gt(G.b.purpose.replace(/\\*+/g,""))}</span>`);
rep(`<button class="more" type="button">подробнее</button></p>`,
    `\${(G.b.compiles||G.b.interacts)?'<button class="more" type="button">во что идёт</button>':""}</p>`);
rep(`.bdesc{min-height:60px}`,`.bdesc{height:98px;overflow:hidden}.bdesc .short,.bdesc .full{display:block}`);
rep(`.body{padding:44px 56px 40px 44px;`,`.body{padding:44px 56px 90px 44px;`);
fs.writeFileSync("gs.html",t);console.log("head ok");
