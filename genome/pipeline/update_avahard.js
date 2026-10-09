// update_avahard.js — загруженная картинка ложится в карточку намертво.
// Было: на диск она уходила, только если страница открыта через лаунчер (isLocal());
// открыл файлом — картинка оставалась в браузере и при первом же переезде терялась.
// Стало: отправка всегда идёт на 127.0.0.1:8765 (лаунчер разрешает любой источник),
// лаунчер кладёт файл в ava/<id>.jpg И вшивает его в share/<id>.genome.json. Если
// лаунчера в этот момент нет — картинка встаёт в очередь и уходит сама, как только он
// появится: повтор каждые 15 секунд, плюс общий перенос при запуске страницы.
// Запуск: node update_avahard.js (после update_avapush). Правит gs.html.
const fs=require("fs");let t=fs.readFileSync("gs.html","utf8");
function rep(a,b){if(!t.includes(a)){console.error("не найдено:",a.slice(0,90));process.exit(1)}t=t.replace(a,b)}

// [1] сама отправка: адрес абсолютный, ответ честный, при неудаче — очередь
rep(`function shrinkAva(src){`,
`// Очередь несохранённого: пережидает выключенный лаунчер, живёт в этом же браузере.
function avaQueue(){try{return JSON.parse(localStorage.getItem("gs_ava_queue")||"{}")}catch(e){return {}}}
function avaQueueSet(q){try{localStorage.setItem("gs_ava_queue",JSON.stringify(q))}catch(e){}}
// Отдать картинку лаунчеру. Возвращает true, только если он подтвердил запись файла.
async function avaToDisk(id,data){
  try{
    const r=await fetch("http://127.0.0.1:8765/api/avas/"+encodeURIComponent(id),{method:"POST",body:data});
    if(!r.ok)return false;
    const d=await r.json();
    AVAFS[id]=id+".jpg";
    return {file:d.file||id+".jpg",embedded:!!d.embedded};
  }catch(e){return false}
}
// Раз в 15 с пытаемся дослать то, что не ушло. Тихо: в журнал, без дёрганья карточек.
setInterval(async()=>{
  const q=avaQueue();const ids=Object.keys(q);if(!ids.length)return;
  let ушло=0;
  for(const id of ids){const ok=await avaToDisk(id,q[id]);if(ok){delete q[id];ушло++}}
  if(ушло){avaQueueSet(q);console.log("лица дослали на диск: "+ушло+", осталось в очереди "+Object.keys(q).length);
    if(typeof renderChars==="function"&&document.querySelector(".ava[data-id]"))renderChars()}
},15000);
function shrinkAva(src){`);

// [2] обработчик загрузки: пробуем диск всегда, а не только под лаунчером
rep(`    let where="";try{localStorage.setItem(avaKey(id),small);where="в этом браузере"}catch(e){where=""}
    if(isLocal()){try{const rs=await fetch("/api/avas/"+encodeURIComponent(id),{method:"POST",body:small});if(rs.ok){AVAFS[id]=id+".jpg";where="ava/"+id+".jpg"}}catch(e){}}
    if(!where){if(lab)lab.textContent="не сохранилось: слишком большая";return}
    renderChars();const c=document.querySelector('.ava[data-id="'+id+'"] span');if(c)c.textContent="сохранено · "+where};r.readAsDataURL(f)}});`,
`    let вБраузере=false;try{localStorage.setItem(avaKey(id),small);вБраузере=true}catch(e){}
    if(lab)lab.textContent="сохраняю…";
    const наДиске=await avaToDisk(id,small);
    if(!наДиске){const q=avaQueue();q[id]=small;avaQueueSet(q)}
    if(!вБраузере&&!наДиске){if(lab)lab.textContent="не сохранилось: слишком большая";return}
    renderChars();
    const c=document.querySelector('.ava[data-id="'+id+'"] span');
    if(c)c.textContent=наДиске?(наДиске.embedded?"в карточке навсегда · "+наДиске.file:"на диске · "+наДиске.file)
                              :"пока в браузере · уйдёт в карточку, когда поднимется студия";
  };r.readAsDataURL(f)}});`);
fs.writeFileSync("gs.html",t);console.log("картинка ложится намертво ok");
