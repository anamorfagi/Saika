// update_avakeep.js — загруженное лицо больше не теряется.
// Было: в браузер сохранялись только {genome, meta}, а картинка шла лишь в экспортный
// объект. Страница открыта файлом, лаунчера нет — и лицо жило до перезагрузки, после
// чего исчезало навсегда. Теперь оно кладётся рядом в то же хранилище, а когда лаунчер
// поднят — уезжает на диск и вшивается в файл персонажа (update_avapush).
// Запуск: node update_avakeep.js (перед update_avapush). Правит gs.html.
const fs=require("fs");let t=fs.readFileSync("gs.html","utf8");
let n=0;
// оба места, где персонаж кладётся в браузер, теперь сохраняют и лицо
t=t.split(`LC[id]={genome,meta};`).join(`LC[id]={genome,meta,ava:(typeof ava!=="undefined"&&ava)||(LC[id]&&LC[id].ava)||undefined};`);
n=(t.match(/LC\[id\]=\{genome,meta,ava:/g)||[]).length;
if(!n){console.error("не найдено ни одного места сохранения персонажа");process.exit(1)}
fs.writeFileSync("gs.html",t);console.log("лицо сохраняется в браузере · мест:",n);
