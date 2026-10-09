// Карточка «Новый персонаж» — только суть: картинка, имя (пишется прямо в заголовке), «начать анализ →».
// Провайдер/модель/ключ уехали на отдельную вкладку API (вернулась в навигацию). Сам анализ — панель под карточками:
// пол · вид · тип корпуса · корпус (найти в сети через exe или вставить) · снять. Итог: файл в share/ (через exe) + карточка.
const fs=require("fs");let t=fs.readFileSync("gs.html","utf8");
function rep(a,b){if(!t.includes(a)){console.error("NOT FOUND:",a.slice(0,90));process.exit(1)}t=t.replace(a,b)}
function cut(a,b,keepB){const i=t.indexOf(a),j=t.indexOf(b,i);if(i<0||j<0){console.error("CUT NOT FOUND:",a.slice(0,60),b.slice(0,40));process.exit(1)}t=t.slice(0,i)+(keepB?"":"")+t.slice(keepB?j:j+b.length)}
// [1] вкладка API в навигации
rep(`<button role="tab" aria-selected="false" data-p="chars">Персонажи</button>`,`<button role="tab" aria-selected="false" data-p="chars">Персонажи</button>
      <button role="tab" aria-selected="false" data-p="api">API</button>`);
// [2] на странице API — только модель; захват по корпусу убран (он в карточке)
cut(`  <h2 style="margin-top:28px">Снять персонажа по корпусу</h2>`,`<div class="log" id="cpL" hidden></div>`);
cut(`  document.getElementById("cpRun").onclick=async()=>{`,`log("ошибка: "+e.message)}};\n`);
// [3] карточка
const i0=t.indexOf('`<div class="card new">');const i1=t.indexOf("</div></div></div>`;",i0);if(i0<0||i1<0){console.error("нет карточки");process.exit(1)}
t=t.slice(0,i0)+`\`<div class="card new"><div class="ava" id="ncAva" data-letter="" title="Картинка персонажа"><input type="file" accept="image/*" hidden></div><div class="nc"><h3><input id="ncN" class="ncname" placeholder="Новый персонаж" autocomplete="off" spellcheck="false"></h3><div class="src" id="ncSrc">имя · картинка · анализ</div>
<p>Впиши имя прямо в заголовок, поставь картинку и запусти анализ: корпус найдётся в сети (через AnamorfGenom.exe) или вставь свой; следователь снимет улики, свод соберёт геном, файл лягет в share/.</p>
<div><button class="open" id="ncGo">начать анализ →</button><button class="open shr" id="ncImp">загрузить файл</button><input id="ncFile" type="file" accept=".json,application/json" hidden><span id="ncR" class="src" style="margin-left:14px"></span></div></div></div>\`+
  \`</div><div class="ncpanel" id="ncPanel" hidden><h2>Анализ · <span id="ncPName">—</span></h2>
  <div class="row"><span>пол</span><select id="ncG"><option value="женский">женский</option><option value="мужской">мужской</option></select><span>вид</span><select id="ncKind"><option value="персонаж">персонаж</option><option value="человек">человек</option><option value="ии">ИИ-компаньон</option></select><span>корпус</span><select id="ncK"><option value="w">вики · потолок 0.7</option><option value="k">пересказ сцен · 0.7</option><option value="n">первоисточник · 0.8</option><option value="t">транскрипт речи · 0.8</option></select></div>
  <div class="row"><span>источник</span><button class="open" id="ncFind">найти в сети →</button><span id="ncFR" class="src"></span></div>
  <textarea id="ncT" placeholder="Корпус: вики, главы, сводки серий, транскрипт. Абзацы — пустой строкой. Или нажми «найти в сети»."></textarea>
  <div class="row"><span>модель</span><span id="ncModel" class="mono"></span><button class="open" data-goapi>API →</button></div>
  <div class="row act"><button class="open pri" id="ncRun">снять персонажа</button><span id="ncRR" class="src"></span></div>
  <div class="ncprog"><i id="ncPr"></i></div><div class="nclog" id="ncL" hidden></div></div>\`;`+t.slice(i1+"</div></div></div>`;".length);
// [4] обработчики: старый bindNewChar → новый
const b0=t.indexOf("function bindNewChar(el){");const b1=t.indexOf("\nbindNewChar(document.getElementById(\"chars\"));",b0);if(b0<0||b1<0){console.error("нет bindNewChar");process.exit(1)}
t=t.slice(0,b0)+`var NC;   // черновик новой карточки живёт между перерисовками (инициализация ленивая: renderChars вызывается раньше этой строки)
function translit(s){const m={а:"a",б:"b",в:"v",г:"g",д:"d",е:"e",ё:"e",ж:"zh",з:"z",и:"i",й:"y",к:"k",л:"l",м:"m",н:"n",о:"o",п:"p",р:"r",с:"s",т:"t",у:"u",ф:"f",х:"h",ц:"c",ч:"ch",ш:"sh",щ:"sch",ъ:"",ы:"y",ь:"",э:"e",ю:"yu",я:"ya"};return s.toLowerCase().split("").map(c=>m[c]!=null?m[c]:c).join("").replace(/[^a-z0-9_]+/g,"_").replace(/^_+|_+$/g,"").slice(0,24)}
function isLocal(){return /^http/.test(location.protocol)&&/localhost|127\\.0\\.0\\.1/.test(location.hostname)}
function bindNewChar(el){NC=NC||{ava:null,name:"",text:""};const N=el.querySelector("#ncN");if(!N)return;const A=el.querySelector("#ncAva"),S=el.querySelector("#ncSrc"),panel=document.getElementById("ncPanel");
  const drawAva=()=>{A.innerHTML=(NC.ava?\`<img src="\${NC.ava}" alt="">\`:"")+'<input type="file" accept="image/*" hidden>';A.classList.toggle("noava",!NC.ava);A.dataset.letter=NC.name?NC.name[0].toUpperCase():"+";
    const inp=A.querySelector("input");A.onclick=()=>inp.click();inp.onchange=()=>{const f=inp.files[0];if(!f)return;const r=new FileReader();r.onload=()=>{NC.ava=r.result;drawAva()};r.readAsDataURL(f)}};
  const sync=()=>{NC.name=N.value.trim();const id=translit(NC.name);S.textContent=NC.name?"id · "+id+(GENOMES[id]?" · уже есть — перезапишется":""):"имя · картинка · анализ";A.dataset.letter=NC.name?NC.name[0].toUpperCase():"+";const pn=document.getElementById("ncPName");if(pn)pn.textContent=NC.name||"—"};
  N.value=NC.name;N.oninput=sync;sync();drawAva();
  el.querySelector("#ncGo").onclick=()=>{sync();if(!NC.name){N.focus();N.placeholder="сначала имя";return}panel.hidden=false;panel.scrollIntoView({behavior:"smooth",block:"start"});const T=document.getElementById("ncT");T.value=NC.text;
    const cfg=apiCfg();const p=(typeof PROVIDERS!=="undefined"?PROVIDERS:[]).find(x=>x.id===cfg.provider);document.getElementById("ncModel").textContent=(p?p.name:cfg.provider)+" · "+(cfg.model||(p&&p.models[0])||"")+(cfg.key?"":" · ключа нет")};
  const P=panel;if(P&&!P.dataset.bound){P.dataset.bound="1";const T=P.querySelector("#ncT");T.oninput=()=>NC.text=T.value;
    P.querySelector("[data-goapi]").onclick=()=>document.querySelector('.nav button[data-p="api"]').click();
    P.querySelector("#ncFind").onclick=async()=>{const r=P.querySelector("#ncFR");if(!isLocal()){r.textContent="поиск в сети работает через AnamorfGenom.exe; с диска — вставь корпус";return}r.textContent="ищу…";
      try{const x=await (await fetch("/api/corpus?q="+encodeURIComponent(NC.name))).json();if(!x.ok)throw new Error(x.error||"ничего");T.value=NC.text=x.text;r.textContent=x.sources.map(s=>s.title+" ("+s.lang+", "+Math.round(s.len/1000)+"k)").join(" · ")}catch(e){r.textContent="✗ "+e.message}};
    P.querySelector("#ncRun").onclick=async()=>{const id=translit(NC.name),name=NC.name,text=T.value;const L=P.querySelector("#ncL");L.hidden=false;L.innerHTML="";const log=s=>{L.innerHTML+=s+"\\n";L.scrollTop=L.scrollHeight};const prog=f=>P.querySelector("#ncPr").style.width=Math.round(f*100)+"%";
      if(!id||text.length<500){log("нужны имя и корпус хотя бы на 500 символов");return}
      try{const cfg=apiCfg();await apiCapture(cfg,{id,name,gender:P.querySelector("#ncG").value,kind:P.querySelector("#ncK").value,text,groups:2},log,prog);
        if(NC.ava){try{localStorage.setItem(avaKey(id),NC.ava)}catch(e){}}
        // файл в share/ — через exe; иначе остаётся в браузере
        if(isLocal()){try{const LC=JSON.parse(localStorage.getItem("gs_chars")||"{}");const c=LC[id];const genome={};let n=0;c.genome.forEach(b=>b.genes.forEach(g=>{if(!g[3])return;n++;genome[g[0]]=[g[2],g[3],g[5]||[]]}));
          const obj={format:GENOME_FORMAT,id,exported:new Date().toISOString().slice(0,16),studio:"Anamorf Genom",genes_total:N,genes_captured:n,meta:c.meta,genome,avatar:NC.ava&&NC.ava.length<400000?NC.ava:undefined};
          const r=await fetch("/api/chars",{method:"POST",body:JSON.stringify(obj,null,2)});if(r.ok){log("файл: share/"+id+".genome.json");delete LC[id];localStorage.setItem("gs_chars",JSON.stringify(LC))}}catch(e){log("в share/ не записалось: "+e.message)}}
        NC={ava:null,name:"",text:""};log("готово — открываю");saveState({page:"genome"});setTimeout(()=>{location.hash="#"+id;location.reload()},800)}catch(e){log("ошибка: "+e.message)}}}}`+t.slice(b1);
// вид персонажа для apiCapture — из панели (id ncKind сохранён)
// [5] стили: без рамок-квадратов — подчёркивания; карточка как остальные
rep(`.card.new .ava{border:1px dashed var(--hair2);background:none;color:var(--dim);font-size:28px;cursor:default}`,`.card.new .ava{cursor:pointer}.card.new .ava.noava::before{content:attr(data-letter);color:var(--dim)}
.card.new h3 .ncname{font:inherit!important;color:inherit;background:none!important;border:0!important;border-bottom:1px solid transparent!important;padding:0!important;height:auto;width:100%;outline:none;border-radius:0!important;letter-spacing:inherit}.card.new h3 .ncname::placeholder{color:var(--dim);opacity:1}.card.new h3 .ncname:focus{border-bottom-color:rgba(207,174,112,.45)!important}
.card.new button.open{background:none!important;border:0!important;height:auto!important;min-width:0!important;padding:0!important;border-radius:0!important;font:500 12px var(--fb)!important;color:var(--gold);letter-spacing:.04em;margin-top:10px}.card.new button.open.shr{margin-left:14px}
.ncpanel{margin-top:36px;padding-top:24px;border-top:1px solid var(--hair);max-width:960px}.ncpanel h2{font:500 30px/1.05 var(--fd);margin:0 0 16px}.ncpanel h2 span{color:var(--gold)}
.ncpanel .row{display:flex;align-items:center;gap:14px;margin:10px 0;flex-wrap:wrap}.ncpanel .row>span:first-child,.ncpanel .row>span:nth-child(3),.ncpanel .row>span:nth-child(5){font:10px var(--fm);letter-spacing:.1em;text-transform:uppercase;color:var(--dim);min-width:52px}.ncpanel .mono{font:12.5px var(--fm);color:var(--text)}
.ncpanel .dd{height:34px;min-width:200px}.ncpanel .dd .ddb{background:none!important;border:0!important;border-bottom:1px solid rgba(233,226,236,.18)!important;border-radius:0!important;padding-left:0!important}.ncpanel .dd.on .ddb{border-bottom-color:rgba(207,174,112,.55)!important}
.ncpanel textarea{width:100%;box-sizing:border-box;min-height:180px;background:none;border:0;border-bottom:1px solid rgba(233,226,236,.18);color:var(--text);font:12.5px/1.55 var(--fm);padding:8px 0;resize:vertical;outline:none}.ncpanel textarea:focus{border-bottom-color:rgba(207,174,112,.55)}.ncpanel textarea::placeholder{color:var(--dim)}
.ncpanel .open{margin-top:0;font:500 12px var(--fb);color:var(--gold);letter-spacing:.04em;background:none;border:0;cursor:pointer;padding:0}.ncpanel .open.pri{color:#111;background:var(--gold);padding:9px 18px;border-radius:3px}
.ncpanel .ncprog{height:2px;background:rgba(255,255,255,.08);margin-top:14px;overflow:hidden}.ncpanel .ncprog i{display:block;height:100%;width:0;background:var(--gold);transition:width .3s}.ncpanel .nclog{font:11.5px/1.5 var(--fm);color:var(--muted);white-space:pre-wrap;max-height:220px;overflow:auto;margin-top:10px}.ncpanel .nclog b{color:var(--text)}`);
// свои списки — и в панели
rep(`querySelectorAll(".card.new select")`,`querySelectorAll(".card.new select,.ncpanel select,.api select")`);
// вкладка API: свои списки после каждой отрисовки, поля — подчёркивания, кнопка — как везде
rep(`  document.getElementById("apP").onchange=()=>{`,`  if(typeof ddAll==="function")ddAll(el);
  document.getElementById("apP").onchange=()=>{`);
rep(`.api .row{display:grid;grid-template-columns:150px 1fr;`,`.api input,.api textarea{background:none!important;border:0!important;border-bottom:1px solid rgba(233,226,236,.18)!important;border-radius:0!important;font:12.5px var(--fm)!important;padding:8px 0!important;outline:none}.api input:focus{border-bottom-color:rgba(207,174,112,.55)!important}
.api .dd{height:34px}.api .dd .ddb{background:none!important;border:0!important;border-bottom:1px solid rgba(233,226,236,.18)!important;border-radius:0!important;padding-left:0!important}.api .dd.on .ddb{border-bottom-color:rgba(207,174,112,.55)!important}
.api button.b{font:500 12px var(--fb)!important;color:var(--gold)!important;background:none!important;border:0!important;padding:0!important;min-width:0!important;letter-spacing:.04em;border-radius:0!important}.api .btns{margin:18px 0}
.api .row{display:grid;grid-template-columns:150px 1fr;`);
// [6] llmChat: с локального сервера — через прокси exe (снимает CORS и даёт GigaChat)
rep(`async function llmChat(cfg,system,user,maxTokens){const p=PROVIDERS.find(x=>x.id===cfg.provider)||PROVIDERS.at(-1);const base=(cfg.base||p.base).replace(/\\/$/,"");const model=cfg.model||p.models[0]||"";`,
`async function llmChat(cfg,system,user,maxTokens){const p=PROVIDERS.find(x=>x.id===cfg.provider)||PROVIDERS.at(-1);const base=(cfg.base||p.base).replace(/\\/$/,"");const model=cfg.model||p.models[0]||"";
  if(isLocal()){const t0=performance.now();const r=await fetch("/api/llm",{method:"POST",body:JSON.stringify({provider:p.id,auth:p.auth,base,model,key:cfg.key,system,user,max_tokens:maxTokens||2500})});const d=await r.json();if(!r.ok||d.error)throw new Error(d.error||("HTTP "+r.status));return {text:d.text,ms:Math.round(performance.now()-t0),tok:d.tok||0}}`);
fs.writeFileSync("gs.html",t);console.log("newcard ok");
