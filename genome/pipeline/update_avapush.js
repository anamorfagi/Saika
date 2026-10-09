// update_avasync.js — перенос аватаров из памяти браузера на диск.
// Зачем: картинки, загруженные на странице, открытой ФАЙЛОМ, живут в хранилище этой
// страницы. Открыл ту же студию через лаунчер (localhost) — это другой источник для
// браузера, и лица исчезают. Здесь страница при запуске сама отдаёт лаунчеру всё, чего
// на диске ещё нет: картинка ложится в ava/<id> и вшивается в файл персонажа.
// Работает и с file://, и с localhost — лаунчер разрешает оба источника.
// Запуск: node update_avasync.js (последним). Правит gs.html.
const fs=require("fs");let t=fs.readFileSync("gs.html","utf8");
function rep(a,b){if(!t.includes(a)){console.error("не найдено:",a.slice(0,90));process.exit(1)}t=t.replace(a,b)}

rep(`renderChars();\n`,`renderChars();
// ---------- перенос лиц из браузера на диск ----------
// Ничего не перезаписывает вслепую: спрашивает у лаунчера список уже лежащих файлов и
// отправляет только недостающие. Итог печатается в консоль настоящими числами.
(async function переносЛиц(){
  const БАЗА="http://127.0.0.1:8765";
  let свои={};try{свои=JSON.parse(localStorage.getItem("gs_chars")||"{}")}catch(e){return}
  const лицо=o=>{const x=(o&&(o.ava||o.avatar))||"";return typeof x==="string"&&x.startsWith("data:image/")?x:null};
  const сИзображением=Object.entries(свои).filter(([id,o])=>лицо(o));
  if(!сИзображением.length)return;
  let наДиске=[];
  try{const r=await fetch(БАЗА+"/api/avas");if(!r.ok)throw 0;наДиске=await r.json()}
  catch(e){console.log("перенос лиц: лаунчер не отвечает — оставляю как есть");return}
  const есть=new Set(наДиске.map(f=>String(f).replace(/\\.[^.]+$/,"").toLowerCase()));
  let отправлено=0,ошибок=0;
  for(const [id,o] of сИзображением){
    if(есть.has(String(id).toLowerCase()))continue;
    try{
      const r=await fetch(БАЗА+"/api/avas/"+encodeURIComponent(id),{method:"POST",body:лицо(o)});
      if(!r.ok)throw new Error("HTTP "+r.status);
      const d=await r.json();отправлено++;
      console.log("лицо перенесено: "+id+(d.embedded?" (вшито в файл персонажа)":""));
    }catch(e){ошибок++;console.log("лицо не перенеслось: "+id+" — "+e.message)}
  }
  if(отправлено||ошибок)console.log("перенос лиц: отправлено "+отправлено+", ошибок "+ошибок+
    ". Обнови страницу, чтобы увидеть их в карточках.");
})();
`);
fs.writeFileSync("gs.html",t);console.log("перенос лиц ok");
