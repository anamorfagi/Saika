// v1.1b: правила R1–R16 в панели гена, превращения эмоций на трассе, третий персонаж — Снейл Кик (живой человек, не снят)
const fs=require("fs");
let t=fs.readFileSync("gs.html","utf8");
function rep(a,b){if(!t.includes(a)){console.error("NOT FOUND:",a.slice(0,80));process.exit(1)}t=t.replace(a,b)}

// ---- [1] третий персонаж: пустой геном на той же схеме ----
const i0=t.indexOf("const GENOMES=");let lit=t.slice(i0+"const GENOMES=".length,t.indexOf("\nconst CHARS_META=",i0));lit=lit.slice(0,lit.indexOf("};")+1);
const G=eval("("+lit+")");
G.snailkick=G.kaguya.map(b=>Object.assign({},b,{genes:b.genes.map(g=>[g[0],g[1],0,0,g[4],[],g[6],g[7]])}));
t=t.slice(0,i0)+"const GENOMES="+JSON.stringify(G)+";"+t.slice(i0+"const GENOMES=".length+lit.length+1);

rep(` kaguya:{name:"Кагуя Синомия",`,
` snailkick:{name:"Снейл Кик",alias:"Макс",src:"YouTube-канал · монологи («Мюсли» и подобные), аудио тех же роликов, фото",
  desc:"Первый живой человек в системе. Захват не начат: корпус ещё не загружен. Три канала улик снимаются раздельно и не смешиваются: текст транскрибов (потолок уверенности 0.8), просодия из аудио (0.7), фото (0.3 — только гипотеза). Расхождение каналов — не ошибка, а маска: emo.*.hide.",
  method:"живой человек · 3 канала улик · захват не начат",
  identity:[],samples:[],never:[],masks:[],tensions:[]},
 kaguya:{name:"Кагуя Синомия",`);
rep(`const SRC={w:"вики",k:"канон",v:"вывод",n:"ранобэ"};`,`const SRC={w:"вики",k:"канон",v:"вывод",n:"ранобэ",t:"текст",a:"просодия",f:"фото"};`);
rep(`.q b.w{color:var(--gold)}`,`.q b.t{color:var(--gold)}.q b.a{color:var(--cold)}.q b.f{color:var(--dim)}.q b.w{color:var(--gold)}`);

// ---- [2] правила взаимодействия генов ----
rep(`const SRC={`,`// Правила взаимодействия генов (ядро движка, спека §4). f — активность правила 0…1 по текущему геному; g — гены-участники
const RULES=[
 {id:"R1",g:["emo.*.hide","ct.feel_speech_gap"],t:"скрытые эмоции ⇒ растёт разрыв речи и чувств"},
 {id:"R2",g:["will.impulsive","cog.depth"],t:"импульсивность ⇒ глубина анализа −0.3 в момент действия"},
 {id:"R3",g:["bond.reject_fear","def.attack"],t:"страх отвержения ∧ нападение ⇒ «отталкивает первой»"},
 {id:"R4",g:["dark.*","dark.awareness","def.rationalize"],t:"тёмная черта без осознанности ⇒ рационализация усиливается"},
 {id:"R5",g:["dark.*","dark.guilt_after","ct.regret","emo.guilt.hide"],t:"тёмная черта ∧ вина после ⇒ сожаление всплывает после эпизода"},
 {id:"R6",g:["self.ext_depend","mem.sig_praise","mem.sig_critic"],t:"зависимость от оценки ⇒ похвала и критика весят ×1.5"},
 {id:"R7",g:["soc.please_need","mot.autonomy","ct.conflict_tol"],t:"хочет нравиться ∧ автономия ⇒ внутренний конфликт"},
 {id:"R8",g:["bond.possess","perc.absence","bond.distance_sens"],t:"собственничество ⇒ чувствительность к отсутствию и дистанции ×1.5"},
 {id:"R9",g:["mor.honesty","dark.deceit"],t:"честность ≥ 0.6 ⇒ лживость не выше −0.2"},
 {id:"R10",g:["def.numb","dyn.*.peak"],t:"онемение ⇒ все пики ×0.5 снаружи, ×1.0 внутри (копится)"},
 {id:"R11",g:["dev.regress"],t:"регресс ∧ стресс ⇒ текущие значения откатываются к baseline"},
 {id:"R12",g:["ct.mask_split","soc.*","sp.*"],t:"разделение масок ⇒ контекстная чувствительность социальности и речи ×2"},
 {id:"R13",conv:["fear","anger"],g:["dyn.fear.*","def.attack","mod.dominance.bias","dyn.anger.*"],t:"страх → гнев: нападение ∧ доминантность к приближению",f:b=>Math.max(0,b("def.attack")-.3)/.7*Math.max(0,b("mod.dominance.bias"))},
 {id:"R14",conv:["shame","anger"],g:["dyn.shame.*","self.humiliation","def.attack","dyn.anger.*"],t:"стыд → агрессия на источник: чувствительность к унижению ∧ нападение",f:b=>Math.max(0,b("self.humiliation")-.4)/.6*Math.max(0,b("def.attack")-.3)/.7},
 {id:"R15",conv:["sadness","numb"],g:["dyn.sadness.*","def.numb","def.withdraw","emo.*.hide"],t:"печаль → холодность: онемение или замыкание гасят печаль, всё hide временно +0.5",f:b=>Math.max(Math.max(0,b("def.numb")-.3)/.7,Math.max(0,b("def.withdraw")-.4)/.6)},
 {id:"R16",conv:["tender","control"],g:["dyn.tender.*","bond.possess","def.control","dyn.fear.*"],t:"привязанность → контроль: собственничество ∧ контроль ⇒ страх потери → акт «Проверить» (симуляция)",f:b=>Math.max(0,b("bond.possess")-.4)/.6*Math.max(0,b("def.control")-.3)/.7}
];
function ruleMatch(pat,id){if(pat===id)return true;if(!pat.includes("*"))return false;const re=new RegExp("^"+pat.replace(/\\./g,"\\\\.").replace(/\\*/g,"[^.]+")+"$");return re.test(id)}
function rulesOf(id){return RULES.filter(r=>r.g.some(p=>ruleMatch(p,id)))}
const SRC={`);

// панель гена: «участвует в правилах»
rep(`<div class="ev"><h3>Откуда это значение</h3>`,
`\${(()=>{const R=rulesOf(G.id);return R.length?\`<div class="ev" style="margin-top:34px"><h3>Участвует в правилах</h3>\${R.map(r=>\`<div class="q"><b class="\${r.conv?'k':'v'}">\${r.id}</b><p><small style="margin-top:0;font-size:13px;color:var(--text)">\${r.t}</small></p></div>\`).join("")}</div>\`:""})()}
  <div class="ev"><h3>Откуда это значение</h3>`);

// ---- [3] трасса: превращения эмоций у текущего персонажа ----
rep(`  Object.keys(PERMS).forEach(k=>document.getElementById("perm_"+k).onchange=`,
`  // превращения R13–R16: активность по генам текущего персонажа, неснятый ген = 0
  const bv=id=>{const g=byId[id];return g&&g.c?g.v:0};const CHN={fear:"страх",anger:"гнев",shame:"стыд",sadness:"печаль",numb:"холодность",tender:"привязанность",control:"контроль"};
  el.insertAdjacentHTML("beforeend",\`<div class="sc" style="grid-column:1/-1"><h3>Превращения эмоций · R13–R16</h3><div class="in">Один канал отдаёт активность другому; доля — из генов защит. Так из одинаковых потребностей получаются разные персонажи: цундере = R14, яндере = R16, кудере = R15. Неснятый ген считается за 0.</div>
  <div class="acts"><div class="h"><span>правило</span><span></span><span></span><span>доля</span><span></span></div>\${RULES.filter(r=>r.conv).map(r=>{const v=Math.min(1,r.f(bv));return \`<div class="\${v>=.3?'top':''}"><span>\${r.id} · \${CHN[r.conv[0]]} → \${CHN[r.conv[1]]}</span><span></span><span></span><span>\${v.toFixed(2)}</span><span><i style="width:\${Math.round(v*100)}%"></i></span></div>\`}).join("")}</div></div>\`);
  Object.keys(PERMS).forEach(k=>document.getElementById("perm_"+k).onchange=`);

fs.writeFileSync("gs.html",t);
console.log("ok",Object.keys(G).map(k=>k+":"+G[k].reduce((s,b)=>s+b.genes.length,0)).join(" "));
// ---- [4] пустой геном: не выдавать 50% и «неоднозначная» за измерение ----
let t2=fs.readFileSync("gs.html","utf8");
t2=t2.replace('<span>тип <b>${st.best.n}</b> ${Math.round(st.best.sc*100)}%</span>','<span>тип <b>${st.cap?st.best.n:"—"}</b> ${st.cap?Math.round(st.best.sc*100)+"%":"не снято"}</span>');
t2=t2.replace('const label=s<=-.45?"тёмная":','const label=!gs.length?"не снято":s<=-.45?"тёмная":');
fs.writeFileSync("gs.html",t2);console.log("patch4",t2.includes('"не снято"'));
