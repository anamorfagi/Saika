// Вкладка «API»: каталог провайдеров (pipeline/providers.json), ключ/модель/проверка, и следователь прямо в браузере —
// корпус в поле → фрагменты × группы генов → запросы к модели по investigator.md → свод формулой §9 → новый персонаж в студии.
// Ограничение хостинга claude.ai: страница не может ходить наружу (CSP) — вкладка это честно показывает; локально/из Сайки работает.
const fs=require("fs");
let t=fs.readFileSync("gs.html","utf8");
function rep(a,b){if(!t.includes(a)){console.error("NOT FOUND:",a.slice(0,80));process.exit(1)}t=t.replace(a,b)}
const PROV=JSON.parse(fs.readFileSync("pipeline/providers.json","utf8")).providers;
const TEMPLATE=fs.readFileSync("pipeline/investigator.md","utf8");
// [1] кнопка и страница
// вкладка API в навигации пока скрыта (решение владельца 15.09); настройки модели живут в карточке «Новый персонаж»
rep(`<section class="page doc" id="p-arch" hidden>`,`<section class="page doc" id="p-api" hidden><div class="inner" id="api"></div></section>
    <section class="page doc" id="p-arch" hidden>`);
rep(`["genome","trace","comp","voice","arch","chars"].forEach`,`["genome","trace","comp","voice","arch","chars","api"].forEach`);
// [2] персонажи, снятые в браузере, живут в localStorage и подмешиваются до сборки CHARS
{const m0=t.indexOf("const CHARS_META={");const m1=t.indexOf("\n};",m0)+3;t=t.slice(0,m1)+`\ntry{const LC=JSON.parse(localStorage.getItem("gs_chars")||"{}");for(const [id,c] of Object.entries(LC)){GENOMES[id]=c.genome;CHARS_META[id]=c.meta}}catch(e){}`+t.slice(m1)}
// [3] стили
rep(`.card .kv.agek{`,`.api{max-width:1100px}.api .row{display:grid;grid-template-columns:150px 1fr;gap:10px 16px;align-items:center;margin:6px 0}.api .row>span:first-child{font:10.5px var(--fm);color:var(--muted);letter-spacing:.06em;text-transform:uppercase}
.api input,.api select,.api textarea{background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.12);color:var(--text);font:13px var(--fb);padding:7px 10px;border-radius:6px;width:100%;box-sizing:border-box}.api textarea{min-height:160px;font:12px var(--fm);line-height:1.5}
.api .btns{display:flex;gap:10px;margin:14px 0}.api button.b{font:500 12px var(--fb);padding:8px 16px;border-radius:999px;border:1px solid rgba(255,255,255,.18);color:var(--text);background:none;min-width:140px}.api button.b.pri{background:var(--gold,#c9a35b);color:#111;border-color:transparent}
.api .badges{display:flex;gap:8px;flex-wrap:wrap}.api .bd{font:10.5px var(--fm);padding:3px 8px;border-radius:4px;border:1px solid rgba(255,255,255,.14);color:var(--muted)}.api .bd.ok{color:#7c6}.api .bd.no{color:#e66}
.api .log{font:11.5px var(--fm);color:var(--muted);white-space:pre-wrap;background:rgba(255,255,255,.03);border-radius:6px;padding:10px 12px;margin-top:10px;max-height:260px;overflow:auto;line-height:1.6}.api .log b{color:var(--text)}
.api .prog{height:4px;background:rgba(255,255,255,.08);border-radius:2px;overflow:hidden;margin:8px 0}.api .prog i{display:block;height:100%;background:var(--gold,#c9a35b);width:0;transition:width .3s}
.card .kv.agek{`);
// [4] логика
rep(`// ---------- страницы ----------`,`// ---------- API: провайдеры и следователь в браузере ----------
var PROVIDERS=${JSON.stringify(PROV)};
var INVESTIGATOR=${JSON.stringify(TEMPLATE)};
var CAPK={w:.7,k:.7,n:.8,t:.8,a:.7,f:.3};
function apiCfg(){try{return Object.assign({provider:"gigachat",base:"",model:"",key:""},JSON.parse(localStorage.getItem("gs_api")||"{}"))}catch(e){return {provider:"gigachat",base:"",model:"",key:""}}}
function apiSave(c){try{localStorage.setItem("gs_api",JSON.stringify(c))}catch(e){}}
// один вызов модели: OpenAI-совместимый /chat/completions; Anthropic — /messages; GigaChat из браузера не ходит (OAuth + CORS) — только через python или прокси Сайки
async function llmChat(cfg,system,user,maxTokens){const p=PROVIDERS.find(x=>x.id===cfg.provider)||PROVIDERS.at(-1);const base=(cfg.base||p.base).replace(/\\/$/,"");const model=cfg.model||p.models[0]||"";
  if(p.auth==="gigachat")throw new Error("GigaChat требует OAuth и не пускает браузер (CORS): запускай pipeline/investigate.py --provider gigachat или прокси Сайки");
  const h={"Content-Type":"application/json"};if(p.auth==="bearer"&&cfg.key)h.Authorization=(p.id==="yandex"?"Api-Key ":"Bearer ")+cfg.key;if(p.auth==="x-api-key"){h["x-api-key"]=cfg.key;h["anthropic-version"]="2023-06-01";h["anthropic-dangerous-direct-browser-access"]="true"}
  const t0=performance.now();let r;
  if(p.auth==="x-api-key")r=await fetch(base+"/messages",{method:"POST",headers:h,body:JSON.stringify({model,max_tokens:maxTokens||2500,temperature:.1,system,messages:[{role:"user",content:user}]})});
  else r=await fetch(base+"/chat/completions",{method:"POST",headers:h,body:JSON.stringify({model,temperature:.1,max_tokens:maxTokens||2500,messages:[{role:"system",content:system},{role:"user",content:user}]})});
  if(!r.ok)throw new Error("HTTP "+r.status+": "+(await r.text()).slice(0,200));const d=await r.json();const ms=Math.round(performance.now()-t0);
  const text=Array.isArray(d.content)?d.content.map(x=>x.text||"").join(""):d.choices[0].message.content;const u=d.usage||{};
  return {text,ms,tok:(u.prompt_tokens||u.input_tokens||0)+(u.completion_tokens||u.output_tokens||0)}}
// корпус → фрагменты по абзацам
function apiChunks(text,size){const out=[];let buf="";for(const p of text.split(/\\n\\s*\\n/)){if(buf.length+p.length>size&&buf){out.push(buf.trim());buf=""}buf+=p+"\\n\\n"}if(buf.trim())out.push(buf.trim());return out}
function apiGeneList(blocks){return blocks.map(b=>"### "+b.name+" ("+b.id+")\\n"+b.genes.map(g=>g[0]+" · "+g[1]+" · −1 = "+(g[6]||"")+" · +1 = "+(g[7]||"")).join("\\n")).join("\\n")}
function apiParse(s){const m=s.match(/\\[[\\s\\S]*\\]/);if(!m)return [];try{return JSON.parse(m[0])}catch(e){try{return JSON.parse(m[0].replace(/,\\s*([\\]}])/g,"$1"))}catch(e2){return []}}}
function apiMerge(v,c,vn,cn){if(!c)return [vn,cn,false];return [(v*c+vn*cn)/(c+cn),Math.min(1,c+cn*(1-c)),Math.abs(vn-v)>.6&&c>.5]}
// следователь: корпус → улики → геном → персонаж
async function apiCapture(cfg,{id,name,gender,kind,text,groups},log,prog){const tmpl=GENOMES.elsa;const valid=new Set(tmpl.flatMap(b=>b.genes.map(g=>g[0])));
  const ch=apiChunks(text,7000);const per=Math.ceil(tmpl.length/groups);const gg=[];for(let i=0;i<tmpl.length;i+=per)gg.push(tmpl.slice(i,i+per));
  const total=ch.length*gg.length;let done=0,nev=0,tok=0,ms=0;const G={};log("фрагментов "+ch.length+" × групп "+gg.length+" = "+total+" запросов");
  for(let ci=0;ci<ch.length;ci++)for(let gi=0;gi<gg.length;gi++){const prompt=INVESTIGATOR.replace("{NAME}",name).replace("{CAP}",String(CAPK[kind])).replace("{GENES}",apiGeneList(gg[gi])).replace("{SRC}","фрагмент "+(ci+1)).replace("{TEXT}",ch[ci]);
    let ev=[];try{const r=await llmChat(cfg,"Ты следователь генома. Отвечай только JSON-массивом.",prompt,3000);ev=apiParse(r.text);tok+=r.tok;ms+=r.ms}catch(e){log("сбой "+(ci+1)+"/"+(gi+1)+": "+e.message)}
    for(const e of ev){if(!e||!valid.has(e.g))continue;const v=Math.max(-1,Math.min(1,+e.v||0)),c=Math.max(.1,Math.min(CAPK[kind],+e.c||.3));const cur=G[e.g]||[0,0,[],false];const q=String(e.q||"").slice(0,220);if(cur[2].some(x=>x[1].startsWith(q)))continue;const [v2,c2,sp]=apiMerge(cur[0],cur[1],v,c);G[e.g]=[v2,c2,cur[2].concat([[kind,q+" — фрагмент "+(ci+1)]]),cur[3]||sp];nev++}
    done++;prog(done/total);log("фрагмент "+(ci+1)+"/"+ch.length+" · группа "+(gi+1)+"/"+gg.length+" · улик "+ev.length+" · "+Math.round(ms/1000)+" с · токенов "+tok)}
  let n=0;const genome=tmpl.map(b=>Object.assign({},b,{genes:b.genes.map(g=>{const s=G[g[0]];if(!s)return [g[0],g[1],0,0,g[4],[],g[6],g[7]];n++;return [g[0],g[1],+s[0].toFixed(2),+s[1].toFixed(2),g[4],s[2].concat(s[3]?[["!","спорный: улики расходятся"]]:[]),g[6],g[7]]})}));
  const meta={voice:{mode:"design",gender,age:"",lang:"русский",timbre:""},name,alias:"",src:"корпус из вкладки API · "+text.length+" символов",method:"автоматический захват в браузере · "+cfg.provider+"/"+(cfg.model||"")+" · "+total+" запросов · "+nev+" улик",desc:"",identity:[],samples:[],never:[],masks:[],tensions:[]};
  try{const LC=JSON.parse(localStorage.getItem("gs_chars")||"{}");LC[id]={genome,meta};localStorage.setItem("gs_chars",JSON.stringify(LC))}catch(e){log("не удалось сохранить в браузере: "+e.message)}
  log("<b>готово: снято "+n+"/345, улик "+nev+", токенов "+tok+", "+Math.round(ms/1000)+" с</b> — открой #"+id);return {n,nev}}
function renderApi(){const el=document.getElementById("api");const cfg=apiCfg();const p=PROVIDERS.find(x=>x.id===cfg.provider)||PROVIDERS[0];const hosted=/claude\\.ai$/.test(location.hostname)||/anthropic|claudeusercontent/.test(location.hostname);
  el.innerHTML=\`<div class="api"><h2>API · модель для следователя</h2><p class="lead">Один клиент на всех: любой OpenAI-совместимый провайдер, платный или бесплатный, плюс GigaChat и Anthropic. Тот же каталог читает <code>pipeline/llm.py</code>. Ключ хранится только в этом браузере.\${hosted?" <b>Со страницы на claude.ai наружу ходить нельзя (политика хостинга) — проверка и захват работают, когда файл открыт локально или из Сайки.</b>":""}</p>
  <div class="row"><span>провайдер</span><select id="apP">\${PROVIDERS.map(x=>\`<option value="\${x.id}" \${x.id===cfg.provider?"selected":""}>\${x.name} — \${x.free?"есть бесплатный тир":"платно"} · РФ: \${x.ru}</option>\`).join("")}</select></div>
  <div class="row"><span></span><div class="badges"><span class="bd \${p.free?"ok":""}">\${p.free?"бесплатный тир":"платно"}</span><span class="bd \${p.ru==="ok"?"ok":p.ru==="vpn"?"":"no"}">из РФ: \${p.ru==="ok"?"работает":p.ru==="vpn"?"нужен VPN":"закрыт"}</span><span class="bd \${p.cors?"ok":"no"}">\${p.cors?"можно из браузера":"только через python/прокси"}</span>\${p.key_url?\`<a class="bd" href="\${p.key_url}" target="_blank">где взять ключ ↗</a>\`:""}\${p.note?\`<span class="bd">\${p.note}</span>\`:""}</div></div>
  <div class="row"><span>адрес API</span><input id="apB" value="\${cfg.base||p.base}" placeholder="\${p.base||"https://…/v1"}"></div>
  <div class="row"><span>модель</span><input id="apM" list="apML" value="\${cfg.model||p.models[0]||""}"><datalist id="apML">\${p.models.map(m=>\`<option value="\${m}">\`).join("")}</datalist></div>
  <div class="row"><span>ключ</span><input id="apK" type="password" value="\${cfg.key||""}" placeholder="\${p.auth==="none"?"не нужен":"API key"}"></div>
  <div class="btns"><button class="b" id="apT">проверить</button><span id="apR" style="font:12px var(--fm);color:var(--muted);align-self:center"></span></div>
  <h2 style="margin-top:28px">Снять персонажа по корпусу</h2><p class="lead">Тот же следователь, что в <code>pipeline/investigate.py</code>: корпус режется на фрагменты по ~7000 символов, гены — на группы, каждая пара — один запрос; улики сводятся формулой слияния (§9). Персонаж появится во вкладке «Персонажи» и сохранится в этом браузере.</p>
  <div class="row"><span>id (латиницей)</span><input id="cpI" placeholder="baymax"></div><div class="row"><span>имя</span><input id="cpN" placeholder="Беймакс"></div>
  <div class="row"><span>пол</span><select id="cpG"><option value="женский">женский</option><option value="мужской">мужской</option></select></div>
  <div class="row"><span>тип корпуса</span><select id="cpK"><option value="w">вики / описание (потолок 0.7)</option><option value="k">пересказ сцен (0.7)</option><option value="n">текст первоисточника (0.8)</option><option value="t">транскрипт живой речи (0.8)</option></select></div>
  <div class="row"><span>групп генов</span><input id="cpQ" type="number" min="1" max="6" value="2"></div>
  <div class="row" style="align-items:start"><span>корпус</span><textarea id="cpT" placeholder="Вставь текст: вики, главы, сводки серий, транскрипты. Абзацы — пустой строкой."></textarea></div>
  <div class="btns"><button class="b pri" id="cpRun">снять</button></div><div class="prog"><i id="cpP"></i></div><div class="log" id="cpL" hidden></div></div>\`;
  const save=()=>apiSave({provider:document.getElementById("apP").value,base:document.getElementById("apB").value.trim(),model:document.getElementById("apM").value.trim(),key:document.getElementById("apK").value.trim()});
  document.getElementById("apP").onchange=()=>{apiSave({provider:document.getElementById("apP").value,base:"",model:"",key:apiCfg().provider===document.getElementById("apP").value?apiCfg().key:""});renderApi()};
  ["apB","apM","apK"].forEach(i=>document.getElementById(i).onchange=save);
  document.getElementById("apT").onclick=async()=>{save();const r=document.getElementById("apR");r.textContent="…";try{const x=await llmChat(apiCfg(),"Отвечай одним словом.","Скажи: работает",8);r.textContent="✓ «"+x.text.trim().slice(0,30)+"» за "+x.ms+" мс"}catch(e){r.textContent="✗ "+(e.message==="Failed to fetch"?"запрос не ушёл (CSP хостинга, CORS или сеть)":e.message)}};
  document.getElementById("cpRun").onclick=async()=>{save();const id=document.getElementById("cpI").value.trim().toLowerCase().replace(/[^a-z0-9_]/g,"");const name=document.getElementById("cpN").value.trim();const text=document.getElementById("cpT").value;const L=document.getElementById("cpL");L.hidden=false;L.innerHTML="";
    const log=s=>{L.innerHTML+=s+"\\n";L.scrollTop=L.scrollHeight};const prog=f=>document.getElementById("cpP").style.width=Math.round(f*100)+"%";
    if(!id||!name||text.length<500){log("нужны id, имя и корпус хотя бы на 500 символов");return}
    if(GENOMES[id]&&!confirm("Персонаж "+id+" уже есть — перезаписать?"))return;
    try{await apiCapture(apiCfg(),{id,name,gender:document.getElementById("cpG").value,kind:document.getElementById("cpK").value,text,groups:+document.getElementById("cpQ").value||2},log,prog)}catch(e){log("ошибка: "+e.message)}};
}
renderApi();
// ---------- страницы ----------`);
fs.writeFileSync("gs.html",t);console.log("api ok",PROV.length);
