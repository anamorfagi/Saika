// Карточка «Новый персонаж» = снять персонажа по корпусу прямо здесь (следователь в браузере из update_api.js).
// Модель для следователя настраивается тут же, компактно; отдельных вкладок API/Наблюдение в навигации нет.
// Плюс: «открыть геном» другого персонажа ведёт на спираль сразу (раньше страница перезагружалась и оставалась на карточках — второй клик).
const fs=require("fs");
let t=fs.readFileSync("gs.html","utf8");
function rep(a,b){if(!t.includes(a)){console.error("NOT FOUND:",a.slice(0,80));process.exit(1)}t=t.replace(a,b)}
rep(`else location.hash="#"+b.dataset.open});`,`else{saveState({page:"genome"});location.hash="#"+b.dataset.open}});`);
rep("`<div class=\"card new\"><div class=\"ava\">+</div><div><h3>Новый персонаж</h3><div class=\"src\">захват по корпусу</div><p>Конвейер: корпус (главы, серии, вики, переписка) → сцены → улики на каждый ген (следователь) → свод в геном (код) → компиляция → замер. Кагуя прошла его первой.</p></div></div></div>`;",
"`<div class=\"card new\"><div class=\"ava\">+</div><div class=\"nc\"><h3>Новый персонаж</h3><div class=\"src\">захват по корпусу · следователь → свод · файл персонажа</div>\n"+
"<div class=\"ncl\"><div class=\"ncrow\"><input id=\"ncI\" placeholder=\"id латиницей\"><input id=\"ncN\" placeholder=\"Имя\"></div>\n"+
"<div class=\"ncrow\"><select id=\"ncG\"><option value=\"женский\">женский</option><option value=\"мужской\">мужской</option></select><select id=\"ncK\"><option value=\"w\">вики · потолок 0.7</option><option value=\"k\">пересказ сцен · 0.7</option><option value=\"n\">первоисточник · 0.8</option><option value=\"t\">транскрипт речи · 0.8</option></select></div>\n"+
"<div class=\"ncrow one\"><select id=\"ncP\"></select></div><div class=\"ncrow\"><input id=\"ncM\" placeholder=\"модель\"><input id=\"ncKey\" type=\"password\" placeholder=\"ключ\"></div>\n"+
"<div class=\"ncrow act\"><button id=\"ncRun\" class=\"pri\">снять</button><button id=\"ncTest\">проверить</button><button id=\"ncImp\">загрузить файл</button><input id=\"ncFile\" type=\"file\" accept=\".json,application/json\" hidden></div><span id=\"ncR\" class=\"src\"></span></div>\n"+
"<textarea id=\"ncT\" placeholder=\"Корпус: вики, главы, сводки серий, транскрипт. Абзацы — пустой строкой. Режется на фрагменты ~7000 символов × 2 группы генов; улики сводятся формулой слияния.\"></textarea>\n"+
"<div class=\"ncprog\"><i id=\"ncPr\"></i></div><div class=\"nclog\" id=\"ncL\" hidden></div></div></div></div>`;");
// обработчики карточки
rep(`el.querySelectorAll("[data-open]").forEach(b=>b.onclick=()=>{`,`bindNewChar(el);
  el.querySelectorAll("[data-open]").forEach(b=>b.onclick=()=>{`);
rep(`// ---------- страницы ----------`,`// ---------- карточка «Новый персонаж»: модель + следователь ----------
function bindNewChar(el){const P=el.querySelector("#ncP");if(!P||typeof PROVIDERS==="undefined")return;const cfg=apiCfg();
  P.innerHTML=PROVIDERS.map(x=>\`<option value="\${x.id}" \${x.id===cfg.provider?"selected":""}>\${x.name}\${x.free?" · бесплатно":""}\${x.ru==="ok"?"":x.ru==="vpn"?" · VPN":" · РФ закрыт"}\${x.cors?"":" · только python"}</option>\`).join("");
  const M=el.querySelector("#ncM"),K=el.querySelector("#ncKey");M.value=cfg.model||((PROVIDERS.find(x=>x.id===cfg.provider)||{}).models||[])[0]||"";K.value=cfg.key||"";
  const save=()=>apiSave({provider:P.value,base:"",model:M.value.trim(),key:K.value.trim()});
  P.onchange=()=>{const p=PROVIDERS.find(x=>x.id===P.value);M.value=p.models[0]||"";K.value="";save()};M.onchange=save;K.onchange=save;
  el.querySelector("#ncTest").onclick=async()=>{save();const r=el.querySelector("#ncR");r.textContent="…";try{const x=await llmChat(apiCfg(),"Отвечай одним словом.","Скажи: работает",8);r.textContent="✓ «"+x.text.trim().slice(0,30)+"» · "+x.ms+" мс"}catch(e){r.textContent="✗ "+(e.message==="Failed to fetch"?"запрос не ушёл: с claude.ai наружу нельзя (открой файл локально или из Сайки), либо CORS/сеть":e.message)}};
  el.querySelector("#ncRun").onclick=async()=>{save();const id=el.querySelector("#ncI").value.trim().toLowerCase().replace(/[^a-z0-9_]/g,""),name=el.querySelector("#ncN").value.trim(),text=el.querySelector("#ncT").value;const L=el.querySelector("#ncL");L.hidden=false;L.innerHTML="";
    const log=s=>{L.innerHTML+=s+"\\n";L.scrollTop=L.scrollHeight};const prog=f=>el.querySelector("#ncPr").style.width=Math.round(f*100)+"%";
    if(!id||!name||text.length<500){log("нужны id, имя и корпус хотя бы на 500 символов");return}
    if(GENOMES[id]){log("персонаж "+id+" уже есть — возьми другой id");return}
    try{await apiCapture(apiCfg(),{id,name,gender:el.querySelector("#ncG").value,kind:el.querySelector("#ncK").value,text,groups:2},log,prog);log("персонаж сохранён в этом браузере — открываю");saveState({page:"genome"});setTimeout(()=>{location.hash="#"+id},800)}catch(e){log("ошибка: "+e.message)}}}
bindNewChar(document.getElementById("chars"));   // карточки отрисованы раньше, чем определён каталог провайдеров — привязываем сейчас
// ---------- страницы ----------`);
rep(`.card .kv.agek{`,`.card.new .nc{display:flex;flex-direction:column;gap:8px}.card.new .ncrow{display:grid;grid-template-columns:1fr 1fr 1fr 1fr;gap:8px}.card.new .ncrow.model{grid-template-columns:1.6fr 1fr 1fr auto}.card.new .ncrow.act{display:flex;align-items:center;gap:12px}
.card.new input,.card.new select,.card.new textarea{background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.12);color:var(--text);font:12px var(--fb);padding:6px 9px;border-radius:6px;width:100%;box-sizing:border-box;min-width:0}.card.new textarea{min-height:110px;font:11.5px var(--fm);line-height:1.5;resize:vertical}
.card.new button{font:500 12px var(--fb);padding:6px 14px;min-width:110px;border-radius:999px;border:1px solid rgba(255,255,255,.18);color:var(--text);background:none;white-space:nowrap}.card.new button.pri{background:var(--gold,#c9a35b);color:#111;border-color:transparent;width:auto;justify-self:start}
.card.new .ncprog{height:3px;background:rgba(255,255,255,.08);border-radius:2px;overflow:hidden}.card.new .ncprog i{display:block;height:100%;width:0;background:var(--gold,#c9a35b);transition:width .3s}.card.new .nclog{font:11px var(--fm);color:var(--muted);white-space:pre-wrap;max-height:140px;overflow:auto;line-height:1.5}.card.new .nclog b{color:var(--text)}
.card .kv.agek{`);
fs.writeFileSync("gs.html",t);console.log("newchar ok");
