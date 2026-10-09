// Кнопка «сохранить все в папку»: карточки из памяти вкладки — файлами на диск.
//
// Исследование, запущенное скриптом или при закрытой вкладке, раньше оставалось
// жить только в localStorage: открыть персонажа «в исходном месте» было нечего.
// Движок теперь пишет карточку сам, но те, что уже застряли в браузере, надо
// вытащить. Кнопка отправляет каждую в лаунчер и убирает из памяти вкладки —
// ровно так же, как это делает сохранение одного персонажа.
const fs=require("fs");
let t=fs.readFileSync("gs.html","utf8");
if(t.includes("data-tofile")){console.log("уже вшито");process.exit(0)}
function rep(a,b){if(!t.includes(a)){console.error("нет якоря:",a.slice(0,70));process.exit(1)}t=t.split(a).join(b)}

rep('el.innerHTML=`<div class="khead"><div class="kinds">',
    'el.innerHTML=`<div class="khead"><button class="tofile" data-tofile hidden>сохранить все в папку</button><div class="kinds">');

// обработчик + показ кнопки только когда есть что сохранять и лаунчер доступен
rep('el.querySelectorAll(".kchip").forEach(',
`(function(){
    const кн=el.querySelector("[data-tofile]");if(!кн)return;
    let местные={};try{местные=JSON.parse(localStorage.getItem("gs_chars")||"{}")}catch(e){}
    const сколько=Object.keys(местные).length;
    const доступно=typeof isLocal==="function"?isLocal():/^https?:/.test(location.protocol);
    if(!сколько||!доступно)return;
    кн.hidden=false;кн.textContent="сохранить все в папку · "+сколько;
    кн.onclick=async()=>{
      кн.disabled=true;let ушло=0,мимо=0;
      for(const [id,c] of Object.entries(местные)){
        try{
          const карта={format:GENOME_FORMAT,id,exported:new Date().toISOString().slice(0,16),
            studio:"Anamorf Genom",genes_total:N,
            genes_captured:(c.genome||[]).reduce((n,b)=>n+(b.genes||[]).filter(g=>g[3]>0).length,0),
            meta:c.meta,genome:Object.fromEntries((c.genome||[]).flatMap(b=>(b.genes||[])
              .filter(g=>g[3]>0).map(g=>[g[0],[g[2],g[3],g[5]||[]]])))};
          let лицо=null;try{лицо=localStorage.getItem(avaKey(id))}catch(e){}
          if(лицо)карта.avatar=лицо;
          const r=await fetch("/api/chars",{method:"POST",body:JSON.stringify(карта,null,2)});
          if(r.ok){ушло++;delete местные[id]}else{мимо++}
        }catch(e){мимо++}
        кн.textContent="сохраняю… "+ушло+"/"+сколько;
      }
      try{localStorage.setItem("gs_chars",JSON.stringify(местные))}catch(e){}
      кн.textContent="сохранено "+ушло+(мимо?" · не вышло "+мимо:"");
      if(ушло)setTimeout(()=>location.reload(),900);
    };
  })();
  el.querySelectorAll(".kchip").forEach(`);

// вид кнопки — как у прочих действий в шапке
rep('.khead{display:flex;align-items:baseline;gap:34px;flex-wrap:wrap;grid-column:1/-1}',
    '.khead{display:flex;align-items:baseline;gap:34px;flex-wrap:wrap;grid-column:1/-1}'+
    '.khead .tofile{order:9;margin-left:auto;background:none;color:var(--gold,#cfae70);'+
    'border:1px solid rgba(233,226,236,.18);border-radius:5px;cursor:pointer;padding:4px 10px;'+
    'font:11px var(--fm,monospace)}.khead .tofile:hover{border-color:var(--gold,#cfae70)}'+
    '.khead .tofile:disabled{opacity:.6;cursor:default}');

fs.writeFileSync("gs.html",t);
console.log("кнопка в папку ok");
