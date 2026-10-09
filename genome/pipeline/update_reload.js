// Самообновление должно ПЕРЕЧИТЫВАТЬ страницу, а не брать её из кеша.
//
// Было: опрос ver.js замечает новую сборку и зовёт location.reload(). Но для
// file:// Chrome отдаёт html из кеша — на экране остаётся старая студия, и
// приходится жать Ctrl+F5. Именно поэтому правки «не видны», хотя файл на диске
// уже новый.
//
// Стало: переход по тому же адресу с меткой сборки в запросе. Адрес другой —
// значит кеш не при чём, файл читается заново. Якорь персонажа сохраняется.
const fs=require("fs");
let t=fs.readFileSync("gs.html","utf8");
if(t.includes("ПЕРЕЧИТАТЬ_БЕЗ_КЕША")){console.log("уже вшито");process.exit(0)}
function rep(a,b){if(!t.includes(a)){console.error("нет якоря:",a.slice(0,80));process.exit(1)}t=t.split(a).join(b)}

rep('else if(window.__BUILD&&window.__BUILD!==__BUILD0){try{saveState&&saveState({})}catch(e){}location.reload()}',
    'else if(window.__BUILD&&window.__BUILD!==__BUILD0){try{saveState&&saveState({})}catch(e){}'+
    '/* ПЕРЕЧИТАТЬ_БЕЗ_КЕША */'+
    'var б=location.pathname+"?b="+encodeURIComponent(window.__BUILD)+location.hash;'+
    'location.replace(б)}');

fs.writeFileSync("gs.html",t);
console.log("перечитывание ok");
