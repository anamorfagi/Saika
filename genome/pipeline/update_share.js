// Формат обмена персонажами: один файл <id>.genome.json — карточка + геном с уликами. Его можно скинуть в чат, а студия загрузит целиком.
// Экспорт — на каждой карточке («файл персонажа»: скачать / скопировать); импорт — в карточке «Новый персонаж» (файл или вставить текст).
// Тот же формат пишет pipeline/export_char.py и читает build_char.js — то, что снято у людей в браузере, можно вшить в сборку.
const fs=require("fs");
let t=fs.readFileSync("gs.html","utf8");
function rep(a,b){if(!t.includes(a)){console.error("NOT FOUND:",a.slice(0,80));process.exit(1)}t=t.replace(a,b)}
// кнопки на карточке
rep("<button class=\"open\" data-open=\"${c.id}\">${cur?\"открыт · к спирали →\":\"открыть геном →\"}</button>","<button class=\"open\" data-open=\"${c.id}\">${cur?\"открыт · к спирали →\":\"открыть геном →\"}</button><button class=\"open shr\" data-share=\"${c.id}\">файл персонажа ↓</button>");
// импорт в карточке нового персонажа
// кнопка «загрузить файл» и input уже в разметке карточки (update_newchar.js)
rep(`bindNewChar(el);`,`bindNewChar(el);bindShare(el);`);
rep(`// ---------- страницы ----------`,`// ---------- файл персонажа: экспорт / импорт ----------
const GENOME_FORMAT="saika-genome/1";
function exportChar(id){const ed=(loadState().edits||{})[id]||{};const genome={};let n=0;
  GENOMES[id].forEach(b=>b.genes.forEach(g=>{const e=ed[g[0]];const v=e?e.v:g[2],c=e?e.c:g[3];if(!c)return;n++;genome[g[0]]=[+v.toFixed(2),+c.toFixed(2),(g[5]||[]).concat(e?[["v","правка вручную в студии"]]:[])]}));
  const m=CHARS_META[id];const meta={};for(const k of ["name","alias","src","method","desc","identity","samples","never","masks","tensions","voice","trace","ageStated","ageVoice","ageText"])if(m[k]!=null)meta[k]=m[k];
  let ava=null;try{ava=localStorage.getItem(avaKey(id))}catch(e){}
  return {format:GENOME_FORMAT,id,exported:new Date().toISOString().slice(0,16),studio:"Genome Studio",genes_total:N,genes_captured:n,meta,genome,avatar:ava&&ava.length<400000?ava:undefined}}
function importChar(obj){if(!obj||obj.format!==GENOME_FORMAT||!obj.genome||!obj.meta)throw new Error("это не файл персонажа Genome Studio (ждём format: "+GENOME_FORMAT+")");
  const id=String(obj.id||obj.meta.name||"imported").toLowerCase().replace(/[^a-z0-9_]/g,"")||"imported";const tmpl=GENOMES.elsa;let n=0;
  const genome=tmpl.map(b=>Object.assign({},b,{genes:b.genes.map(g=>{const s=obj.genome[g[0]];if(!s||!s[1])return [g[0],g[1],0,0,g[4],[],g[6],g[7]];n++;return [g[0],g[1],+s[0],+s[1],g[4],s[2]||[],g[6],g[7]]})}));
  const meta=Object.assign({voice:{mode:"design",gender:"женский",age:"",lang:"русский",timbre:""},alias:"",src:"",method:"загружен из файла",desc:"",identity:[],samples:[],never:[],masks:[],tensions:[]},obj.meta);
  const LC=JSON.parse(localStorage.getItem("gs_chars")||"{}");LC[id]={genome,meta};localStorage.setItem("gs_chars",JSON.stringify(LC));
  if(obj.avatar){try{localStorage.setItem(avaKey(id),obj.avatar)}catch(e){}}
  return {id,n}}
function bindShare(el){
  el.querySelectorAll("[data-share]").forEach(b=>b.onclick=async()=>{const id=b.dataset.share;const obj=exportChar(id);const txt=JSON.stringify(obj);const fn=id+".genome.json";
    let copied=false;try{await navigator.clipboard.writeText(txt);copied=true}catch(e){}
    // сохранение файла: на claude.ai — через downloads-возможность страницы (viewer спросит подтверждение); локально — обычная ссылка
    let saved="";try{const dl=(window.claude&&window.claude.use)?await window.claude.use("downloads"):null;
      if(dl){try{await dl.save({filename:fn,data:txt});saved="сохранён"}catch(e){saved=e&&e.code==="declined"?"отменено":"не сохранён ("+(e&&e.code||"?")+")"}}
      else{const a=document.createElement("a");a.href=URL.createObjectURL(new Blob([txt],{type:"application/json"}));a.download=fn;a.click();setTimeout(()=>URL.revokeObjectURL(a.href),2000);saved="скачан"}}catch(e){}
    b.textContent=[saved,copied?"в буфере":""].filter(Boolean).join(" · ")+" · "+fn+" · "+obj.genes_captured+" генов · "+Math.round(txt.length/1024)+" КБ";setTimeout(()=>{b.textContent="файл персонажа ↓"},5000)});
  const imp=el.querySelector("#ncImp"),file=el.querySelector("#ncFile");if(!imp)return;
  const accept=txt=>{const r=el.querySelector("#ncR");try{const {id,n}=importChar(JSON.parse(txt));r.textContent="загружен "+id+" · "+n+" генов — открываю";saveState({page:"genome"});setTimeout(()=>{location.hash="#"+id;if(("#"+id)===location.hash)location.reload()},600)}catch(e){r.textContent="✗ "+e.message}};
  imp.onclick=async()=>{let txt="";try{txt=await navigator.clipboard.readText()}catch(e){}
    if(txt.trim().startsWith("{")&&txt.includes(GENOME_FORMAT)){accept(txt);return}   // в буфере уже файл — берём его
    file.value="";file.click()};
  file.onchange=()=>{const f=file.files[0];if(!f)return;const rd=new FileReader();rd.onload=()=>accept(rd.result);rd.readAsText(f,"utf-8")};
  // перетащить файл на карточку
  const card=el.querySelector(".card.new");if(card){card.ondragover=e=>{e.preventDefault();card.style.outline="1px dashed var(--gold,#c9a35b)"};card.ondragleave=()=>card.style.outline="";card.ondrop=e=>{e.preventDefault();card.style.outline="";const f=e.dataTransfer.files[0];if(!f)return;const rd=new FileReader();rd.onload=()=>accept(rd.result);rd.readAsText(f,"utf-8")}}}
bindShare(document.getElementById("chars"));
// ---------- страницы ----------`);
rep(`.card.new .ncprog{`,`.card .open.shr{margin-left:14px}
.card.new .ncprog{`);
fs.writeFileSync("gs.html",t);console.log("share ok");
