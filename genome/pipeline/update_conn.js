// update_conn.js — вкладка API превращается в «стыки»: каталог из providers.json разложен по группам,
// одна кнопка проверяет все стыки с этой машины настоящими запросами, одно поле принимает ключ и само
// определяет провайдера и модель. Ключи копятся по провайдерам, а не затирают друг друга.
// Запуск: node update_conn.js (последним, после update_research). Правит gs.html.
const fs=require("fs");let t=fs.readFileSync("gs.html","utf8");
function rep(a,b){if(!t.includes(a)){console.error("не найдено:",a.slice(0,90));process.exit(1)}t=t.replace(a,b)}

// [1] каталог стыков — тот же файл, что читает python
const cat=JSON.parse(fs.readFileSync("pipeline/providers.json","utf8")).providers;
const m=/(?:const|var|let)\s+PROVIDERS\s*=\s*\[[\s\S]*?\];/.exec(t);
if(!m){console.error("не найден PROVIDERS");process.exit(1)}
t=t.replace(m[0],m[0].slice(0,m[0].indexOf("PROVIDERS"))+"PROVIDERS="+JSON.stringify(cat)+";");

// [2] стили стыков
rep("<style>",`<style>
.cbar{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin:16px 0 6px}
.cbar button{background:var(--gold);color:#17141a;border:0;border-radius:6px;padding:9px 16px;font:600 12px var(--fm);cursor:pointer}
.cbar button.ghost{background:none;color:var(--gold);border:1px solid rgba(233,226,236,.14)}
.cbar button:disabled{opacity:.5;cursor:default}
.cnote{font:11px/1.6 var(--fm);color:var(--dim);margin:6px 0 0}
.cpaste{display:grid;grid-template-columns:1fr auto;gap:10px;margin:14px 0 4px}
.cpaste input{background:var(--bg2);border:1px solid rgba(233,226,236,.14);border-radius:6px;padding:10px 12px;color:var(--text);font:12px var(--fm)}
.cgrp{margin:26px 0 6px;font:600 11px var(--fm);letter-spacing:.14em;text-transform:uppercase;color:var(--gold)}
.cgrp small{display:block;margin-top:3px;font:400 11px var(--fm);letter-spacing:0;text-transform:none;color:var(--dim)}
.crow{display:grid;grid-template-columns:14px 1fr 150px 1.4fr 96px;gap:12px;align-items:baseline;padding:8px 0;border-bottom:1px solid rgba(233,226,236,.14);cursor:pointer}
.crow:hover{background:var(--bg2)}
.crow.sel{box-shadow:inset 3px 0 var(--gold)}
.crow b{font:500 13px var(--fd);color:var(--text)}
.crow b i{font-style:normal;color:var(--gold);font-size:11px;margin-left:7px}
.crow .vd{font:11px var(--fm)}
.crow .dt{font:11px/1.45 var(--fm);color:var(--dim);overflow-wrap:anywhere}
.crow a.kl{font:11px var(--fm);color:var(--gold);text-align:right;white-space:nowrap}
.dot{width:9px;height:9px;border-radius:50%;background:#3a3640;display:inline-block}
.dot.ok{background:#63c08a}.dot.open{background:#cfae70}.dot.warn{background:#c9a13f}
.dot.geo,.dot.block{background:#c05f5f}
.vd.ok{color:#63c08a}.vd.open{color:#cfae70}.vd.warn{color:#c9a13f}.vd.geo,.vd.block{color:#c05f5f}`);

// [3] хранилище ключей по провайдерам + проверка всех стыков + распознавание ключа
rep("function renderApi(){",`
// ключи копятся по провайдеру: завёл пять — все пять остались, переключение не стирает
function keyBag(){try{return JSON.parse(localStorage.getItem("gs_api_keys")||"{}")}catch(e){return {}}}
function keyPut(id,k){try{const b=keyBag();if(k)b[id]=k;else delete b[id];localStorage.setItem("gs_api_keys",JSON.stringify(b))}catch(e){}}
var PROBE={};
async function probeAll(only){
  const box=document.getElementById("cRes"),btn=document.getElementById("cGo");
  if(!box)return;if(btn)btn.disabled=true;
  box.textContent="проверяю "+(only?only:"все сети")+" — настоящими запросами, до 20 секунд…";
  try{
    const r=await fetch("/api/probe"+(only?"?id="+encodeURIComponent(only):""));
    const d=await r.json();if(d.error)throw new Error(d.error);
    d.forEach(x=>PROBE[x.id]=x);
    const live=d.filter(x=>x.level==="ok"||x.level==="open");
    const keyed=d.filter(x=>x.code==="ok_key");
    const todo=live.filter(x=>x.free&&!x.has_key);
    box.innerHTML="Проверено "+d.length+" стыков с этой машины. Открыто: <b>"+live.length+"</b>. Отвечает с ключом: <b>"+keyed.length+"</b>. Закрыто: "+d.filter(x=>x.level==="geo"||x.level==="block").length+"."+
      (todo.length?"<br>Открыты, бесплатный тир, ключа нет — с них и начинай: <b>"+todo.map(x=>x.name).join(", ")+"</b>":"");
    renderApi();
  }catch(e){
    box.innerHTML="Проверку запускает лаунчер Сайки (он поднимает <code>pipeline/probe.py</code>). Если студия открыта файлом, браузер так не умеет — тогда в консоли: <code>python pipeline/probe.py</code>";
  }finally{if(btn)btn.disabled=false}
}
// вставил ключ — стык определяется сам: перебираются подходящие провайдеры, берётся тот, кто ключ принял
async function keyFind(){
  const inp=document.getElementById("cKey"),box=document.getElementById("cRes");
  const key=(inp.value||"").trim();if(!key)return;
  box.textContent="ищу, чей это ключ…";
  try{
    const r=await fetch("/api/keyfind",{method:"POST",body:JSON.stringify({key})});
    const d=await r.json();if(d.error)throw new Error(d.error);
    if(!d.provider){box.innerHTML="Ключ никто не принял. Перебрал: "+(d.tried||[]).map(x=>x.id+" ("+x.status+")").join(", ")+". Если провайдер не отдаёт список моделей — выбери его в списке и вставь ключ в его строку.";return}
    keyPut(d.provider,key);
    const model=(d.models||[]).find(x=>/deepseek|gpt-5|gpt-4|claude|glm|qwen|gemini/i.test(x))||(d.models||[])[0]||"";
    apiSave({provider:d.provider,base:"",model,key});
    inp.value="";
    box.innerHTML="Это <b>"+d.name+"</b>. Ключ сохранён, моделей доступно "+(d.models||[]).length+", выбрана <code>"+(model||"—")+"</code>. Следователь уже будет думать ей.";
    probeAll(d.provider);
  }catch(e){
    // Студия открыта файлом — лаунчера нет, значит перебирать провайдеров некому.
    // Но ключ всё равно надо сохранить: им пользуется python-воркер, а не браузер.
    // Провайдера узнаём по виду ключа, а если вид незнакомый — кладём в выбранный.
    const hint=[["sk-aitunnel","aitunnel"],["sk-or-v1","openrouter"],["sk-ant","anthropic"],
                ["sk-proj","openai"],["sk-svcacct","openai"],["gsk_","groq"],["xai-","xai"],
                ["csk-","cerebras"],["fw_","fireworks"],["pplx-","perplexity"]];
    const guess=(hint.find(([pre])=>key.startsWith(pre))||[])[1]||apiCfg().provider;
    const pr=PROVIDERS.find(x=>x.id===guess)||PROVIDERS[0];
    keyPut(pr.id,key);apiSave({provider:pr.id,base:"",model:pr.models[0]||"",key});
    inp.value="";renderApi();
    box.innerHTML="Лаунчер не отвечает, поэтому список моделей не спросил. Ключ сохранён для <b>"+pr.name+
      "</b>, модель по умолчанию <code>"+(pr.models[0]||"—")+"</code>. Если провайдер другой — выбери его в списке ниже, ключ подставится сам.";
  }
}
function renderApi(){`);

// [4] сама вкладка
const OLD_START='function renderApi(){const el=document.getElementById("api");';
const i0=t.indexOf(OLD_START);
if(i0<0){console.error("не найдено начало renderApi");process.exit(1)}
const i1=t.indexOf("\nrenderApi();",i0);
if(i1<0){console.error("не найден конец renderApi");process.exit(1)}
const BODY=`function renderApi(){const el=document.getElementById("api");const cfg=apiCfg();const bag=keyBag();
  const p=PROVIDERS.find(x=>x.id===cfg.provider)||PROVIDERS[0];
  const hosted=/claude\\.ai$/.test(location.hostname)||/anthropic|claudeusercontent/.test(location.hostname);
  const GRP=[["ru_agg","Через посредника, оплата рублями","Работают из России без VPN, карта российская. Один ключ — сразу GPT, Claude, Gemini и DeepSeek."],
             ["direct","Напрямую у разработчика","Дешевле, но оплата зарубежной картой, а часть сетей может не пустить из России — покажет проверка."],
             ["local","На своём компьютере","Бесплатно и никуда не уходит. Годится, пока модель справляется со строгим форматом ответа."]];
  const mark=x=>{const pr=PROBE[x.id];if(!pr)return {lvl:"",vd:x.ru==="ok"?"не проверен":x.ru==="vpn"?"не проверен · вероятно нужен VPN":x.ru==="block"?"не проверен · заявлен закрытым":"не проверен",dt:x.note||""};
    return {lvl:pr.level,vd:pr.verdict+(pr.http_ms?" · "+pr.http_ms+" мс":""),dt:pr.detail||""}};
  el.innerHTML=\`<div class="api"><h2>Модели и ключи</h2>
  <p class="lead">Здесь выбирается, какая нейросеть работает за студию: разбирает источники, снимает улики, пишет портрет персонажа. Проверка идёт настоящими запросами с этого компьютера — видно, что реально открывается, а не что обещают сайты.\${hosted?" <b>Со страницы на claude.ai наружу ходить нельзя — проверка работает из лаунчера или из локального файла.</b>":""}</p>
  <div class="cbar"><button id="cGo">проверить все</button><button class="ghost" id="cOpen">открыть сайты за ключами</button></div>
  <div class="cpaste"><input id="cKey" type="password" placeholder="вставь сюда любой ключ — провайдер и модель определятся сами"><button id="cFind">разобрать ключ</button></div>
  <div class="cgrp">Чем работаем сейчас<small>Эта сеть и эта модель будут разбирать источники. Кликни строку ниже — подставится она.</small></div>
  <div class="row"><span>провайдер</span><select id="apP">\${PROVIDERS.map(x=>\`<option value="\${x.id}" \${x.id===cfg.provider?"selected":""}>\${x.name}</option>\`).join("")}</select></div>
  <div class="row"><span>адрес API</span><input id="apB" value="\${cfg.base||p.base}" placeholder="\${p.base||"https://…/v1"}"></div>
  <div class="row"><span>модель</span><input id="apM" list="apML" value="\${cfg.model||p.models[0]||""}"><datalist id="apML">\${(p.models||[]).map(x=>\`<option value="\${x}">\`).join("")}</datalist></div>
  <div class="row"><span>ключ</span><input id="apK" type="password" value="\${cfg.key||bag[p.id]||""}" placeholder="\${p.auth==="none"?"не нужен":"API key"}"></div>
  <div class="btns"><button class="b" id="apT">проверить эту сеть</button><span id="apR" style="font:12px var(--fm);color:var(--muted);align-self:center"></span></div>

  <p class="cnote" id="cRes">Порядок: проверить → взять ключ там, где зелено и бесплатно → вписать его в строке этой сети. Больше ничего вбивать не надо.</p>
  \${GRP.map(([g,title,sub])=>{const rows=PROVIDERS.filter(x=>(x.grp||"direct")===g&&x.id!=="custom");if(!rows.length)return "";
    return '<div class="cgrp">'+title+'<small>'+sub+'</small></div>'+rows.map(x=>{const s=mark(x);const has=bag[x.id]||(cfg.provider===x.id&&cfg.key);
      return '<div class="crow'+(x.id===cfg.provider?' sel':'')+'" data-pick="'+x.id+'"><span class="dot '+s.lvl+'"></span>'+
        '<b>'+x.name+(has?'<i>ключ есть</i>':'')+(x.free?'<i>бесплатный тир</i>':'')+'</b>'+
        '<span class="vd '+s.lvl+'">'+s.vd+'</span>'+
        '<span class="dt" title="'+String(s.dt||x.note||x.base).replace(/"/g,"&quot;")+'">'+(s.dt||x.note||x.base)+'</span>'+
        (x.key_url?'<a class="kl" href="'+x.key_url+'" target="_blank" rel="noopener">взять ключ ↗</a>':'<span></span>')+'</div>'}).join("")}).join("")}
</div>\`;
  const save=()=>{const id=document.getElementById("apP").value,k=document.getElementById("apK").value.trim();keyPut(id,k);
    apiSave({provider:id,base:document.getElementById("apB").value.trim(),model:document.getElementById("apM").value.trim(),key:k})};
  if(typeof ddAll==="function")ddAll(el);
  document.getElementById("cGo").onclick=()=>probeAll("");
  document.getElementById("cFind").onclick=keyFind;
  document.getElementById("cKey").onkeydown=e=>{if(e.key==="Enter")keyFind()};
  // очередь: сначала то, что открыто и бесплатно, потом остальное открытое. Закрытые не открываются вовсе
  document.getElementById("cOpen").onclick=()=>{
    const live=PROVIDERS.filter(x=>x.key_url&&!keyBag()[x.id]&&(!PROBE[x.id]||["ok","open","warn"].includes(PROBE[x.id].level)));
    const q=live.sort((a,b)=>(b.free?1:0)-(a.free?1:0)||((a.grp==="ru_agg")?-1:1));
    if(!q.length){document.getElementById("cRes").textContent="Ключи уже есть везде, где стык открыт.";return}
    q.slice(0,6).forEach((x,i)=>setTimeout(()=>window.open(x.key_url,"_blank","noopener"),i*400));
    document.getElementById("cRes").innerHTML="Открыл "+Math.min(6,q.length)+" вкладок: "+q.slice(0,6).map(x=>x.name).join(", ")+". Регистрируешься сам, ключ — сюда в поле, остальное подхватится."};
  el.querySelectorAll("[data-pick]").forEach(r=>r.onclick=e=>{if(e.target.tagName==="A")return;
    const id=r.dataset.pick;apiSave({provider:id,base:"",model:"",key:keyBag()[id]||""});renderApi()});
  document.getElementById("apP").onchange=()=>{const id=document.getElementById("apP").value;apiSave({provider:id,base:"",model:"",key:keyBag()[id]||""});renderApi()};
  ["apB","apM","apK"].forEach(i=>document.getElementById(i).onchange=save);
  document.getElementById("apT").onclick=async()=>{save();const r=document.getElementById("apR");r.textContent="…";
    try{const x=await llmChat(apiCfg(),"Отвечай одним словом.","Скажи: работает",8);r.textContent="✓ «"+x.text.trim().slice(0,30)+"» за "+x.ms+" мс"}
    catch(e){r.textContent="✗ "+(e.message==="Failed to fetch"?"браузер не пустил (CORS) — воркеру следователя это не мешает":e.message)}};
}`;
t=t.slice(0,i0)+BODY+t.slice(i1);
fs.writeFileSync("gs.html",t);console.log("стыки ok · провайдеров "+cat.length);
