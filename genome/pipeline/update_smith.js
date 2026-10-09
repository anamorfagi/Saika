// Кнопка «собрать промпт моделью» на вкладке «Компилятор».
//
// Шаблон умеет только пересобрать то, что лежит в данных: полюс плюс частота.
// Живой проход даёт связный текст — поведение в ситуациях, что перевешивает при
// столкновении черт, где персонаж ломается. Обе версии нужны: шаблон работает
// без сети и мгновенно, модель пишет качественно. Промпт от модели, если он есть
// в карточке, показывается первым.
const fs=require("fs");
let t=fs.readFileSync("gs.html","utf8");
if(t.includes("data-smith")){console.log("уже вшито");process.exit(0)}
function rep(a,b){if(!t.includes(a)){console.error("нет якоря:",a.slice(0,80));process.exit(1)}t=t.split(a).join(b)}

rep('<div class="eyebrow">канал 1 · системный промпт <span id="pstat"',
    '<div class="eyebrow">канал 1 · системный промпт'+
    ' <button class="smith" data-smith>собрать моделью</button>'+
    '<span id="smithstat" style="color:var(--dim);letter-spacing:0;text-transform:none"></span>'+
    ' <span id="pstat"');

// обработчик вешается там же, где строится страница компилятора
rep('function renderResearchCompiler(){',
`async function собратьПромптМоделью(){
  const кн=document.querySelector("[data-smith]"),стат=document.getElementById("smithstat");
  if(!кн)return;
  const местный=/^https?:/.test(location.protocol)&&/localhost|127\\.0\\.0\\.1/.test(location.hostname);
  if(!местный){стат.textContent=" — нужен запущенный лаунчер, из файла напрямую не выйдет";return}
  кн.disabled=true;стат.textContent=" — пишет модель, это до минуты…";
  try{
    const r=await fetch("/api/prompt",{method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify({id:CUR})});
    const d=await r.json();
    if(!r.ok||d.error)throw new Error(d.error||("HTTP "+r.status));
    CHAR.prompt=d.prompt;CHAR.prompt_by=d.by||"";
    стат.textContent=" — готово: "+(d.prompt||"").length+" знаков";
    renderResearchCompiler();
  }catch(e){стат.textContent=" — не вышло: "+e.message}
  finally{кн.disabled=false}
}
function renderResearchCompiler(){`);

// показывать промпт от модели вместо шаблонного, если он есть
rep('document.getElementById("prompt").textContent=cp.text;',
`document.getElementById("prompt").textContent=(CHAR&&CHAR.prompt&&CHAR.prompt.length>200)?CHAR.prompt:cp.text;`);

rep('#p-comp pre{', '#p-comp .smith{background:none;color:var(--gold,#cfae70);border:1px solid rgba(233,226,236,.18);'+
   'border-radius:5px;cursor:pointer;padding:3px 9px;font:10px var(--fm,monospace);letter-spacing:0;'+
   'text-transform:none;margin-left:10px}#p-comp .smith:hover{border-color:var(--gold,#cfae70)}'+
   '#p-comp .smith:disabled{opacity:.6;cursor:default}#p-comp pre{');

fs.writeFileSync("gs.html",t);
console.log("кнопка промпта ok");
