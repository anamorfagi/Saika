// update_ava2.js — аватар с карточки: картинка ужимается до 600 px JPEG перед сохранением (раньше большой PNG молча не влезал
// в localStorage), при работе через exe уходит в ava/<id>.jpg (POST /api/avas/<id>), результат показывается на карточке.
// Запуск: node update_ava2.js (после update_cards). Правит gs.html и exe/launcher.js.
const fs=require("fs");let t=fs.readFileSync("gs.html","utf8");
function rep(a,b){if(!t.includes(a)){console.error("не найдено:",a.slice(0,80));process.exit(1)}t=t.replace(a,b)}
// [1] обработчик выбора файла на карточке
rep(`el.querySelectorAll(".ava[data-id]").forEach(a=>{const inp=a.querySelector("input");a.onclick=()=>inp.click();inp.onchange=()=>{const f=inp.files[0];if(!f)return;const r=new FileReader();r.onload=()=>{try{localStorage.setItem(avaKey(a.dataset.id),r.result)}catch(e){}renderChars()};r.readAsDataURL(f)}});`,
`el.querySelectorAll(".ava[data-id]").forEach(a=>{const inp=a.querySelector("input");a.onclick=()=>inp.click();inp.onchange=()=>{const f=inp.files[0];if(!f)return;const id=a.dataset.id;const lab=a.querySelector("span");if(lab)lab.textContent="сжимаю…";
  const r=new FileReader();r.onload=async()=>{const small=await shrinkAva(r.result);if(!small){if(lab)lab.textContent="не картинка";return}
    let where="";try{localStorage.setItem(avaKey(id),small);where="в этом браузере"}catch(e){where=""}
    if(isLocal()){try{const rs=await fetch("/api/avas/"+encodeURIComponent(id),{method:"POST",body:small});if(rs.ok){AVAFS[id]=id+".jpg";where="ava/"+id+".jpg"}}catch(e){}}
    if(!where){if(lab)lab.textContent="не сохранилось: слишком большая";return}
    renderChars();const c=document.querySelector('.ava[data-id="'+id+'"] span');if(c)c.textContent="сохранено · "+where};r.readAsDataURL(f)}});`);
// [2] карточка: подпись под аватаром — что можно сделать и куда ляжет
rep(`<span>\${av&&!String(av).startsWith("ava/")?"заменить":"добавить аву"}</span>`,`<span>\${av&&!String(av).startsWith("ava/")?"заменить":"добавить аву"}</span>`);
// ужатие для аватара — глобально (shrink из avasync живёт внутри своей функции)
rep(`var AVAFS={};`,`var AVAFS={};
function shrinkAva(src){return new Promise(res=>{const im=new Image();im.onload=()=>{const k=Math.min(1,600/Math.max(im.width,im.height));const c=document.createElement("canvas");c.width=Math.round(im.width*k);c.height=Math.round(im.height*k);c.getContext("2d").drawImage(im,0,0,c.width,c.height);res(c.toDataURL("image/jpeg",.88))};im.onerror=()=>res(null);im.src=src})}`);
fs.writeFileSync("gs.html",t);
// [3] launcher: POST /api/avas/<id> — data:image/jpeg;base64 → ava/<id>.jpg
const lp="exe/launcher.js";let L=fs.readFileSync(lp,"utf8");
if(!L.includes('/api/avas/')){
  const a=`  if(p==="/api/avas"){`;if(!L.includes(a)){console.error("нет маршрута /api/avas");process.exit(1)}
  L=L.replace(a,`  if(p.startsWith("/api/avas/")&&req.method==="POST"){const id=decodeURIComponent(p.slice(10)).toLowerCase().replace(/[^a-z0-9_]/g,"");let body="";req.on("data",d=>body+=d);req.on("end",()=>{try{const m=/^data:image\\/[a-z]+;base64,(.+)$/s.exec(body);if(!id||!m)throw new Error("bad");fs.mkdirSync(AVA,{recursive:true});for(const ext of ["png","webp","gif"]){try{fs.unlinkSync(path.join(AVA,id+"."+ext))}catch(e){}}fs.writeFileSync(path.join(AVA,id+".jpg"),Buffer.from(m[1],"base64"));res.writeHead(200,{"Content-Type":"application/json"});res.end(JSON.stringify({ok:true,file:id+".jpg"}))}catch(e){res.writeHead(400);res.end("bad image")}});return}
`+a);
  fs.writeFileSync(lp,L);
}
console.log("ava2 ok");
