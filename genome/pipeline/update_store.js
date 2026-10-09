// Хранилище персонажей = папка share/. В HTML персонажей больше нет: при загрузке страница читает share/index.js
// (работает и с диска, и с локального сервера), плюс персонажи, загруженные файлом в этом браузере (localStorage gs_chars).
// Карточку можно удалить: с exe — файл уезжает в share/_trash, с диска (file://) — карточка скрывается (файл удалить нельзя из браузера).
const fs=require("fs");let t=fs.readFileSync("gs.html","utf8");
function rep(a,b){if(!t.includes(a)){console.error("NOT FOUND:",a.slice(0,90));process.exit(1)}t=t.replace(a,b)}
// [1] вшитые GENOMES / CHARS_META → пустые + TEMPLATE (обнулённый геном, чтобы собирать персонажей из файлов)
const i0=t.indexOf("\nconst GENOMES=");const i1=t.indexOf("\ntry{const LC=JSON.parse(localStorage.getItem(\"gs_chars\")",i0);if(i0<0||i1<0){console.error("нет блока персонажей");process.exit(1)}
const lit=t.slice(t.indexOf("=",i0)+1,t.indexOf("\n// ---------- персонажи: метаданные",i0));const G=eval("("+lit.trim().replace(/;$/,"")+")");
const first=G[Object.keys(G)[0]];const TEMPLATE=first.map(b=>Object.assign({},b,{genes:b.genes.map(g=>[g[0],g[1],0,0,g[4],[],g[6],g[7]])}));
t=t.slice(0,i0)+`
var TEMPLATE=${JSON.stringify(TEMPLATE)};   // схема генома без значений: из неё собирается любой персонаж из файла
const GENOMES={},CHARS_META={};
// персонаж из файла saika-genome/1 → {id, genome, meta, n}
function charFromFile(obj){if(!obj||obj.format!=="saika-genome/1"||!obj.genome||!obj.meta)throw new Error("это не файл персонажа Anamorf Genom (ждём format: saika-genome/1)");
  const id=String(obj.id||obj.meta.name||"imported").toLowerCase().replace(/[^a-z0-9_]/g,"")||"imported";let n=0;
  const genome=TEMPLATE.map(b=>Object.assign({},b,{genes:b.genes.map(g=>{const s=obj.genome[g[0]];if(!s||!s[1])return [g[0],g[1],0,0,g[4],[],g[6],g[7]];n++;return [g[0],g[1],+s[0],+s[1],g[4],s[2]||[],g[6],g[7]]})}));
  const meta=Object.assign({kind:"персонаж",voice:{mode:"design",gender:"женский",age:"",lang:"русский",timbre:""},alias:"",src:"",method:"загружен из файла",desc:"",identity:[],samples:[],never:[],masks:[],tensions:[]},obj.meta);
  return {id,genome,meta,n}}
// [share/] персонажи из папки — через share/index.js (window.__SHARE); скрытые в этом браузере — пропускаем
var HIDDEN={};try{HIDDEN=JSON.parse(localStorage.getItem("gs_hidden")||"{}")}catch(e){}
var MISSING={};try{MISSING=location.protocol==="file:"?JSON.parse(localStorage.getItem("gs_missing")||"{}"):{}}catch(e){}
for(const o of (window.__SHARE||[])){try{const r=charFromFile(o);if(HIDDEN[r.id]||MISSING[r.id])continue;GENOMES[r.id]=r.genome;CHARS_META[r.id]=r.meta;CHARS_META[r.id].__src="share"}catch(e){console.warn("share/",e.message)}}`+t.slice(i1);
// [2] загруженные файлом в этом браузере — поверх share
rep(`for(const [id,c] of Object.entries(LC)){GENOMES[id]=c.genome;CHARS_META[id]=c.meta}`,`for(const [id,c] of Object.entries(LC)){if(HIDDEN[id])continue;GENOMES[id]=c.genome;CHARS_META[id]=c.meta;CHARS_META[id].__src="local"}`);
// [3] текущий персонаж: из hash/состояния, иначе первый; если никого нет — пустая заготовка и сразу вкладка «Персонажи»
rep(`const CUR=wantChar in GENOMES?wantChar:"elsa";`,`const CUR=wantChar in GENOMES?wantChar:(Object.keys(GENOMES)[0]||"__empty");
if(CUR==="__empty"){GENOMES.__empty=JSON.parse(JSON.stringify(TEMPLATE));CHARS_META.__empty={kind:"персонаж",name:"Нет персонажей",alias:"загрузи файл или сними нового",src:"",method:"",desc:"",identity:[],samples:[],never:[],masks:[],tensions:[],voice:{mode:"design",gender:"женский",age:"",lang:"русский",timbre:""}};ST.page="chars"}`);
rep(`const CHARS=Object.keys(GENOMES).map(id=>Object.assign({id},CHARS_META[id]));`,`const CHARS=Object.keys(GENOMES).filter(id=>id!=="__empty").map(id=>Object.assign({id},CHARS_META[id]));
// [file://] index.js — кэш; браузер папку не видит, поэтому проверяем каждый файл тегом <script>: загрузился — есть, ошибка — файл убран → карточка снимается
if(location.protocol==="file:"){window.addEventListener("error",e=>{if(e.filename&&/\\.genome\\.json/.test(e.filename))e.preventDefault()},true);
  const miss=(()=>{try{return JSON.parse(localStorage.getItem("gs_missing")||"{}")}catch(e){return {}}})();
  (window.__SHARE||[]).map(o=>({id:String(o.id||"").toLowerCase().replace(/[^a-z0-9_]/g,"")})).filter(c=>c.id&&!HIDDEN[c.id]).forEach(c=>{const s=document.createElement("script");s.src="share/"+c.id+".genome.json?t="+Date.now();
    s.onload=()=>{s.remove();if(miss[c.id]){delete miss[c.id];localStorage.setItem("gs_missing",JSON.stringify(miss));console.log("share/"+c.id+".genome.json вернулся");location.reload()}};
    s.onerror=()=>{s.remove();if(miss[c.id])return;miss[c.id]=Date.now();try{localStorage.setItem("gs_missing",JSON.stringify(miss))}catch(e){}
      delete GENOMES[c.id];delete CHARS_META[c.id];const i=CHARS.findIndex(x=>x.id===c.id);if(i>=0)CHARS.splice(i,1);console.log("share/"+c.id+".genome.json убран — карточка снята");
      if(CUR===c.id){saveState({char:null});location.hash="";location.reload()}else if(typeof renderChars==="function")renderChars()};
    document.head.appendChild(s)})}`);
// [4] шаблон вместо GENOMES.elsa
t=t.split("GENOMES.elsa").join("TEMPLATE");
// importChar — через charFromFile
rep(`  const id=String(obj.id||obj.meta.name||"imported").toLowerCase().replace(/[^a-z0-9_]/g,"")||"imported";const tmpl=TEMPLATE;let n=0;
  const genome=tmpl.map(b=>Object.assign({},b,{genes:b.genes.map(g=>{const s=obj.genome[g[0]];if(!s||!s[1])return [g[0],g[1],0,0,g[4],[],g[6],g[7]];n++;return [g[0],g[1],+s[0],+s[1],g[4],s[2]||[],g[6],g[7]]})}));
  const meta=Object.assign({voice:{mode:"design",gender:"женский",age:"",lang:"русский",timbre:""},alias:"",src:"",method:"загружен из файла",desc:"",identity:[],samples:[],never:[],masks:[],tensions:[]},obj.meta);
  const LC=`,`  const {id,genome,meta,n}=charFromFile(obj);try{const h=JSON.parse(localStorage.getItem("gs_hidden")||"{}");delete h[id];localStorage.setItem("gs_hidden",JSON.stringify(h))}catch(e){}
  const LC=`);
// [5] кнопка «удалить» на карточке — в два клика, без системных диалогов
rep(`<button class="open shr" data-share="\${c.id}">файл персонажа ↓</button>`,`<button class="open shr" data-share="\${c.id}">файл персонажа ↓</button><button class="open del" data-del="\${c.id}">удалить</button>`);
rep(`.card .ava.noava::before{`,`.card .open.del{opacity:.55;margin-left:14px}.card .open.del:hover,.card .open.del[data-arm]{opacity:1;color:#e0605a}
.card .ava.noava::before{`);
rep(`  const imp=el.querySelector("#ncImp"),file=el.querySelector("#ncFile");if(!imp)return;`,`  el.querySelectorAll("[data-del]").forEach(b=>b.onclick=async()=>{const id=b.dataset.del;
    if(!b.dataset.arm){b.dataset.arm="1";b.textContent="точно удалить?";setTimeout(()=>{delete b.dataset.arm;b.textContent="удалить"},4000);return}
    b.textContent="удаляю…";const local=/^http/.test(location.protocol)&&/localhost|127\\.0\\.0\\.1/.test(location.hostname);let moved="";
    if(local){try{const r=await fetch("/api/chars/"+encodeURIComponent(id),{method:"DELETE"});if(r.ok)moved=(await r.json()).moved||""}catch(e){}}
    try{const LC=JSON.parse(localStorage.getItem("gs_chars")||"{}");delete LC[id];localStorage.setItem("gs_chars",JSON.stringify(LC));localStorage.removeItem(avaKey(id));
      if(!local){const h=JSON.parse(localStorage.getItem("gs_hidden")||"{}");h[id]=Date.now();localStorage.setItem("gs_hidden",JSON.stringify(h))}
      const st=loadState();if(st.edits)delete st.edits[id];if(st.char===id)st.char=null;st.page="chars";localStorage.setItem(SK,JSON.stringify(st))}catch(e){}
    console.log("удалён",id,moved||(local?"":"скрыт в этом браузере; файл в share/ удалит exe"));location.hash="";location.reload()});
  const imp=el.querySelector("#ncImp"),file=el.querySelector("#ncFile");if(!imp)return;`);
// [6] старый автоимпорт share/ с сервера (писал в localStorage) — убран; список аватаров /api/avas остаётся
const a=t.indexOf(`  try{const r=await fetch("/api/chars");if(!r.ok)return;const files=await r.json();`);const b=t.indexOf(`})();`,a);if(a<0||b<0){console.error("нет блока автоимпорта");process.exit(1)}
t=t.slice(0,a)+t.slice(b);
// подводка на «Персонажах»: с диска share/ не видна
rep("Снятые профили. Клик по аватару — загрузить свой (хранится только в этом браузере).","Снятые профили — папка share/ рядом с программой.${location.protocol===\"file:\"&&!window.__SHARE?\" <b>Открыто с диска и список share/_list.js не найден — запусти AnamorfGenom.exe или «загрузить файл».</b>\":\"\"} Клик по аватару — картинка.");
// [7] подключение share/index.js до основного скрипта
rep(`<script>\nvar TEMPLATE=`,`<script src="share/_list.js"></script>\n<script>\nvar TEMPLATE=`);
fs.writeFileSync("gs.html",t);console.log("store ok · TEMPLATE",TEMPLATE.reduce((s,b)=>s+b.genes.length,0),"генов");
