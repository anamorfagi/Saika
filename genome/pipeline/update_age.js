// Слой возрастных норм: наклон гена в единицах шкалы на декаду (0.2·SD/декаду), опорный возраст 30; оценка возраста по геному, голосу и тексту
const fs=require("fs");
let t=fs.readFileSync("gs.html","utf8");
function rep(a,b){if(!t.includes(a)){console.error("NOT FOUND:",a.slice(0,80));process.exit(1)}t=t.replace(a,b)}
// [ген]: [наклон/декаду, диапазон действия [от, до] лет, описание тренда, источник, надёжность]
const AGE={
 "will.discipline":[.03,[18,60],"дисциплина растёт всю взрослую жизнь","Roberts, Walton & Viechtbauer 2006; Soto et al. 2011",0],
 "mot.order":[.03,[18,60],"порядок растёт","Roberts 2006; Soto 2011",0],
 "will.impulsive":[-.06,[15,40],"импульсивность падает до ~40","Steinberg et al. 2008; Roberts 2006",0],
 "mot.novelty":[-.06,[15,45],"поиск новизны падает после подросткового пика","Steinberg 2008 (sensation seeking)",0],
 "mot.explore":[-.04,[15,50],"тяга к неизвестному снижается","Steinberg 2008",0],
 "mot.avoid_error":[.04,[18,50],"избегание ошибок растёт (риск падает)","Byrnes 1999; Steinberg 2008",0],
 "soc.dominance":[.05,[20,40],"социальная доминантность растёт 20→40","Roberts 2006",0],
 "self.competence":[.04,[20,50],"ощущение компетентности растёт","Roberts 2006 (social dominance)",0],
 "dyn.fear.threshold":[.03,[20,60],"эмоциональная устойчивость растёт","Roberts 2006; Soto 2011",0],
 "mod.arousal.gain":[-.03,[20,60],"реактивность на напряжение падает","Roberts 2006 (emotional stability)",0],
 "dyn.anger.peak":[-.03,[20,60],"вспышки слабеют","Soto 2011 (neuroticism: anger facet)",0],
 "def.attack":[-.04,[18,55],"физическая агрессия падает; половая разница 0.66 → 0.25 после 30","Archer 2004",1],
 "soc.caring":[.02,[20,65],"доброжелательность растёт, сильнее после 50","Roberts 2006; Soto 2011",0],
 "mor.wellbeing":[.02,[20,65],"то же","Soto 2011 (altruism)",0],
 "soc.diplomacy":[.02,[20,65],"уступчивость растёт","Soto 2011 (compliance)",0],
 "des.libido":[-.04,[30,70],"влечение снижается после 30","Frankenbach 2022 (возраст как модератор слабый); клинические нормы",0],
 "sp.imagery":[-.02,[50,80],"образность/эстетика снижается после 55","Roberts 2006 (openness)",0],
 "att.rumination":[-.02,[20,60],"руминация слабеет","Johnson & Whisman 2013 (возраст)",0],
 "mem.recall_recent":[.03,[30,80],"давнее помнится ярче новому (пик воспоминаний 15–25 лет)","reminiscence bump: Rubin 1998",0]
};
rep(`const SRC={w:"вики"`,`// Возрастные нормы: наклон на декаду относительно 30 лет; действует в окне [от, до]
const AGE=${JSON.stringify(AGE)};
function ageLine(G){const a=AGE[G.id];if(!a)return "";const [s,[lo,hi],txt,src,ok]=a;return \`<div class="normline"><b>возраст:</b> \${s>0?"+":"−"}\${Math.abs(s).toFixed(2)} за декаду, \${lo}–\${hi} лет — \${txt} <span>\${src}\${ok?"":" · по памяти, проверить"}</span></div>\`}
// оценка возраста по геному: каждый ген с наклоном даёт «подразумеваемый возраст», вес = уверенность × |наклон|; разброс честно широкий
function ageFromGenome(id){const ed=(loadState().edits||{})[id]||{};const m={};GENOMES[id].flatMap(b=>b.genes).forEach(g=>{const e=ed[g[0]];m[g[0]]={v:e?e.v:g[2],c:e?e.c:g[3]}});
  // индекс зрелости: взвешенная сумма (значение − норма пола)·знак тренда; |idx| < 0.3 — возраст по геному не определяется (тренды ≤ 0.06/декаду тонут в индивидуальном разбросе σ ≈ 0.3)
  const ml=maleOf(id);let sw=0,si=0,n=0;for(const [gid,[s]] of Object.entries(AGE)){const x=m[gid];if(!x||!x.c)continue;const norm=NORM[gid]?(ml?NORM[gid][0]:-NORM[gid][0]):0;const w=x.c*Math.abs(s);sw+=w;si+=w*(x.v-norm)*Math.sign(s);n++}
  if(!n)return null;const idx=si/sw;return {idx,n,band:idx>=.3?"профиль старше типичного (40+)":idx<=-.3?"профиль моложе типичного (до 25)":"не определяется"}}
function ageCard(id){const g=ageFromGenome(id);const c=CHARS_META[id];const parts=[];
  if(g)parts.push(\`по геному: <b>\${g.band}</b> — индекс зрелости \${g.idx>0?"+":""}\${g.idx.toFixed(2)} по \${g.n} генам\`);
  if(c.ageVoice)parts.push(\`по голосу <b>\${c.ageVoice}</b>\`);if(c.ageText)parts.push(\`по речи <b>\${c.ageText}</b>\`);
  if(c.ageStated)parts.push(\`корпус · сеть: <b>\${c.ageStated}</b>\`);else if(c.voice&&c.voice.age)parts.push(\`канон: <b>\${c.voice.age}</b>\`);
  return parts.length?\`<div class="kv agek"><span>возраст:</span>\${parts.map(p=>\`<span>\${p}</span>\`).join("")}</div>\`:""}
const SRC={w:"вики"`);
rep(`\${normLine(G)}
  <div class="lv">`,`\${normLine(G)}\${ageLine(G)}
  <div class="lv">`);
// карточка персонажа: строка возраста под статистикой
rep(`<div class="kv"><span>снято <b>\${st.cap}</b> / \${N}</span>`,`\${ageCard(c.id)}<div class="kv"><span>снято <b>\${st.cap}</b> / \${N}</span>`);
rep(`.card .kv{`,`.card .kv.agek{margin-top:10px;flex-wrap:wrap;white-space:normal}
.card .kv{`);
// Максим: голос и речь — оценки из просодии и лексики корпуса; возраст, названный в тексте
rep(`voice:{mode:"clone",gender:"мужской",age:"32",`,`ageStated:"32 (запись ноябрь 2023) · <a href='https://wikireality.ru/wiki/Snailkick' target='_blank'>18.11.1991</a> → 34",ageVoice:"25–50",ageText:"30–39 (age_lex, слабо 0.16)",voice:{mode:"clone",gender:"мужской",age:"32",`);
fs.writeFileSync("gs.html",t);console.log("age ok",Object.keys(AGE).length);
