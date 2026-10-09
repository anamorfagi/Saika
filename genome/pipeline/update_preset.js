// update_preset.js — «Лепка»: быстрый конструктор персонажа из готовых типажей.
// Наверху вкладки «Архетипы» появляется панель: выбираешь типажи чипами (или берёшь
// готовый пресет из нескольких), сразу видишь, сколько генов задастся и где типажи
// спорят друг с другом, вписываешь имя — и персонаж готов. Считается всё вживую,
// на настоящих диапазонах, а не «примерно».
// Запуск: node update_preset.js (после update_keys). Правит gs.html.
const fs=require("fs");let t=fs.readFileSync("gs.html","utf8");
function rep(a,b){if(!t.includes(a)){console.error("не найдено:",a.slice(0,90));process.exit(1)}t=t.replace(a,b)}

// [1] стили панели
rep(`.dot{width:9px;height:9px;border-radius:50%;`,
`.lepka{border:1px solid rgba(233,226,236,.14);border-radius:10px;padding:16px 18px;margin:0 0 22px;background:var(--bg2)}
.lepka h3{margin:0 0 4px;font:600 13px var(--fm);letter-spacing:.1em;text-transform:uppercase;color:var(--gold)}
.lepka .sub{font:11px/1.5 var(--fm);color:var(--dim);margin:0 0 12px}
.lepka .fam{font:10px var(--fm);letter-spacing:.12em;text-transform:uppercase;color:var(--dim);margin:10px 0 5px}
.chip{display:inline-block;border:1px solid rgba(233,226,236,.14);border-radius:14px;padding:4px 11px;margin:0 5px 5px 0;
  font:11px var(--fm);color:var(--text);cursor:pointer;user-select:none}
.chip:hover{border-color:var(--gold)}
.chip.on{background:var(--gold);color:#17141a;border-color:var(--gold)}
.lepka .ready{display:grid;grid-template-columns:repeat(4,auto);gap:6px 20px;margin:14px 0 4px;align-items:baseline}
.lepka .ready b{font:600 19px var(--fm);color:var(--gold)}
.lepka .ready span{font:10px/1.25 var(--fm);color:var(--dim)}
.lepka .war{font:11px/1.5 var(--fm);color:#c9a13f;margin:8px 0 0}
.lepka .mk{display:grid;grid-template-columns:1fr 130px 130px auto;gap:8px;margin-top:14px}
.lepka .mk input,.lepka .mk select{background:var(--bg);border:1px solid rgba(233,226,236,.14);border-radius:6px;padding:8px 10px;color:var(--text);font:12px var(--fm)}
.lepka .mk button{background:var(--gold);color:#17141a;border:0;border-radius:6px;padding:9px 18px;font:600 12px var(--fm);cursor:pointer}
.lepka .mk button:disabled{opacity:.4;cursor:default}
.preset{display:inline-block;border:1px dashed rgba(233,226,236,.14);border-radius:8px;padding:6px 12px;margin:0 6px 6px 0;
  font:11px var(--fm);color:var(--gold);cursor:pointer}
.preset:hover{border-color:var(--gold);border-style:solid}
.dot{width:9px;height:9px;border-radius:50%;`);

// [2] готовые пресеты и отрисовка панели
rep(`function renderArch(){`,
`// Готовые наборы: каждый — типажи из РАЗНЫХ семейств, потому что склад ума, стиль
// привязанности и social role описывают человека с разных сторон и не спорят между собой.
// Имена ищутся по подстроке: если типаж переименуют, пресет не развалится молча — он
// просто соберёт меньше и честно это покажет.
const PRESETS=[
 ["Строгая наставница",      ["Наставн","Надёжн","Систем"]],
 ["Тёплая подруга",          ["Дандэрэ","Надёжн","Забот"]],
 ["Ледяная принцесса",       ["Кудэрэ","Избега","Правит"]],
 ["Взрывная задира",         ["Цундэрэ","Тревож","Импульс"]],
 ["Тихая отличница",         ["Дандэрэ","Систем","Учащ"]],
 ["Хищница",                 ["Садист","Избега","Доминан"]],
 ["Наивная и забывчивая",    ["Чистый лист","Тревож","Рассе"]],
 ["Липкая и ревнивая",       ["Яндэрэ","Тревож","Ревни"]],
];
var LEPKA=new Set();
function lepkaSigs(){return SIGS.filter((s,i)=>LEPKA.has(i))}
// сколько генов задастся и где типажи спорят: спор = диапазоны не пересекаются вовсе
function lepkaStat(){
  const acc={},war=[];const SEX=male()?"m":"f";const nm=s=>SEX==="m"&&s.nm?s.nm:s.n;
  lepkaSigs().forEach(s=>s.c.forEach(([g,lo,hi])=>{(acc[g]=acc[g]||[]).push([lo,hi,nm(s)])}));
  for(const g in acc){const L=acc[g];if(L.length<2)continue;
    for(let a=0;a<L.length;a++)for(let b=a+1;b<L.length;b++)
      if(L[a][1]<L[b][0]||L[b][1]<L[a][0]){
        war.push((byId[g]?byId[g].name:g)+": «"+L[a][2]+"» хочет "+L[a][0]+"…"+L[a][1]+", «"+L[b][2]+"» — "+L[b][0]+"…"+L[b][1]);
        a=L.length;break}}
  const both=Object.values(acc).filter(L=>L.length>1).length;
  return {genes:Object.keys(acc).length,overlap:both,war};
}
function renderLepka(){
  const box=document.getElementById("lepka");if(!box)return;
  const SEX=male()?"m":"f";const nm=s=>SEX==="m"&&s.nm?s.nm:s.n;
  const st=lepkaStat();
  const fams=Object.keys(FAM).map(f=>{
    const rows=SIGS.map((s,i)=>({s,i})).filter(r=>r.s.fam===f&&(!r.s.sex||r.s.sex===SEX));
    if(!rows.length)return "";
    return '<div class="fam">'+FAM[f]+'</div>'+rows.map(r=>
      '<span class="chip'+(LEPKA.has(r.i)?" on":"")+'" data-sig="'+r.i+'" title="'+String(r.s.d||"").replace(/"/g,"&quot;").slice(0,220)+'">'+nm(r.s)+'</span>').join("");
  }).join("");
  box.innerHTML='<h3>Лепка персонажа</h3>'+
    '<p class="sub">Выбери типажи — геном соберётся из их диапазонов. Можно взять готовый набор и доправить чипами. Наведи на типаж — что он значит.</p>'+
    PRESETS.map((p,i)=>'<span class="preset" data-preset="'+i+'">'+p[0]+'</span>').join("")+
    fams+
    '<div class="ready"><b>'+st.genes+'</b><span>генов<br>задастся</span><b>'+st.overlap+'</b><span>генов<br>подтверждены<br>двумя типажами</span>'+
    '<b>'+st.war.length+'</b><span>спорных<br>мест</span><b>'+LEPKA.size+'</b><span>типажей<br>выбрано</span></div>'+
    (st.war.length?'<p class="war">Типажи спорят — при сборке возьмётся среднее: '+st.war.slice(0,3).join(" · ")+(st.war.length>3?" и ещё "+(st.war.length-3):"")+'</p>':"")+
    '<div class="mk"><input id="lpName" placeholder="имя персонажа" value="">'+
    '<select id="lpSex"><option value="женский">женский</option><option value="мужской">мужской</option></select>'+
    '<select id="lpKind"><option>персонаж</option><option>человек</option><option>ии</option></select>'+
    '<button id="lpGo"'+(LEPKA.size?"":" disabled")+'>слепить</button></div>';
  box.querySelectorAll("[data-sig]").forEach(c=>c.onclick=()=>{
    const i=+c.dataset.sig;LEPKA.has(i)?LEPKA.delete(i):LEPKA.add(i);renderLepka()});
  box.querySelectorAll("[data-preset]").forEach(c=>c.onclick=()=>{
    LEPKA.clear();
    PRESETS[+c.dataset.preset][1].forEach(part=>{
      const hit=SIGS.findIndex(s=>(s.n+" "+(s.nm||"")).toLowerCase().includes(part.toLowerCase()));
      if(hit>=0)LEPKA.add(hit)});
    const nameEl=document.getElementById("lpName");
    renderLepka();
    const n2=document.getElementById("lpName");if(n2&&!nameEl?.value)n2.placeholder="имя персонажа · набор «"+PRESETS[+c.dataset.preset][0]+"»";
  });
  const go=document.getElementById("lpGo");
  if(go)go.onclick=()=>{
    const name=(document.getElementById("lpName").value||"").trim();
    if(!name){document.getElementById("lpName").focus();return}
    makeMixChar(lepkaSigs(),name,document.getElementById("lpSex").value,document.getElementById("lpKind").value)};
}
function renderArch(){`);

// [3] контейнер панели наверху вкладки
rep('document.getElementById("arch").innerHTML=`<h2>Куда попадает ${CHAR.name.split(" ")[0]}</h2>',
    'document.getElementById("arch").innerHTML=`<div class="lepka" id="lepka"></div><h2>Куда попадает ${CHAR.name.split(" ")[0]}</h2>');
rep(`  const mk=document.getElementById("archMake");`,`  renderLepka();
  const mk=document.getElementById("archMake");`);
fs.writeFileSync("gs.html",t);console.log("лепка ok");
