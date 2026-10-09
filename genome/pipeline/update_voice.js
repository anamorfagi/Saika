// Вкладка «Голос»: V-компилятор голоса — геном → параметры речи → промпт для Voice Design (ElevenLabs-подобный)
const fs=require("fs");
let t=fs.readFileSync("gs.html","utf8");
function rep(a,b){if(!t.includes(a)){console.error("NOT FOUND:",a.slice(0,80));process.exit(1)}t=t.replace(a,b)}

// ---- [1] навигация и страница ----
rep(`<button role="tab" aria-selected="false" data-p="comp">Компилятор</button>`,
    `<button role="tab" aria-selected="false" data-p="comp">Компилятор</button>
      <button role="tab" aria-selected="false" data-p="voice">Голос</button>`);
rep(`<section class="page doc" id="p-arch" hidden>`,
    `<section class="page doc" id="p-voice" hidden><div class="inner" id="voice" style="grid-template-rows:auto auto 1fr"></div></section>
    <section class="page doc" id="p-arch" hidden>`);
rep(`#p-comp .inner{grid-template-rows:auto auto 1fr;overflow:hidden}`,
`#p-comp .inner{grid-template-rows:auto auto 1fr;overflow:hidden}
#p-voice .inner{overflow:hidden}
#p-voice .inner>div{position:relative;min-width:0;min-height:0}
.vp{display:grid;gap:3px}
.vp div{display:grid;grid-template-columns:150px 44px 1fr 1fr;gap:12px;font:10.5px var(--fm);align-items:center;color:var(--muted)}
.vp div.h{color:var(--dim);letter-spacing:.1em;text-transform:uppercase;font-size:9.5px}
.vp div span:nth-child(3){height:2px;background:var(--hair2);position:relative}
.vp div span:nth-child(3) i{position:absolute;left:0;top:-1px;bottom:-1px;background:var(--gold)}
.vp div.def{color:var(--dim)}.vp div.def span:nth-child(3) i{background:var(--hair2)}
.vp div span:last-child{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--dim)}
.vpre{font:12px/1.6 var(--fb);color:#d3cbd8;white-space:pre-wrap;margin:0}
.vpre b{color:var(--gold);font-weight:500}
.emb{display:grid;grid-template-columns:repeat(4,auto);gap:22px;justify-content:start;margin:0 0 14px}
.emb div{display:flex;flex-direction:column;gap:3px}.emb b{font:500 18px/1 var(--fd)}.emb span{font:9.5px var(--fm);letter-spacing:.12em;text-transform:uppercase;color:var(--dim)}`);

// ---- [2] слой Embodiment: тембр, возраст, пол — не гены (спека §0), задаются на персонажа ----
rep(` snailkick:{name:"Снейл Кик",alias:"Макс",`,
` snailkick:{voice:{mode:"clone",gender:"мужской",age:"30+",lang:"русский",timbre:"— снимается с аудио «Мюслей», не проектируется"},name:"Снейл Кик",alias:"Макс",`);
rep(` elsa:{name:"Эльза Гранхирт",`,
` elsa:{voice:{mode:"design",gender:"женский",age:"около 25",lang:"русский, безупречная дикция",timbre:"низкий-средний, бархатный, с придыханием; улыбка слышна в голосе даже в угрозе"},name:"Эльза Гранхирт",`);
rep(` kaguya:{name:"Кагуя Синомия",`,
` kaguya:{voice:{mode:"design",gender:"женский",age:"17",lang:"русский, литературный",timbre:"средне-высокий, чистый, собранный; в срыве — на октаву выше и быстрее"},name:"Кагуя Синомия",`);

// ---- [3] компилятор голоса ----
rep(`// ---------- архетипы: библиотека независимых типов`,
`// ---------- голос: V-компилятор. Параметр = взвешенное по уверенности среднее полюсов генов; неснятые гены не участвуют ----------
// Формат: [название, [[ген, знак], ...], описание −, описание +]. Значение 0…1, 0.5 = «как у всех»
const VOICE_PARAMS=[
 ["Темп речи",[["sp.pace",1],["mod.arousal.bias",1],["will.impulsive",.5]],"медленно, с растяжкой","быстро, без пауз"],
 ["Паузы",[["soc.silence_ok",1],["sp.pace",-1],["cog.depth",.5]],"заполняет каждую паузу","держит долгие паузы"],
 ["Диапазон интонации",[["sp.emotional",1],["sp.drama",1],["mod.arousal.gain",.5]],"ровная, монотонная","широкие интонационные качели"],
 ["Устойчивость под стрессом",[["sp.voice_stability",1],["will.against_emo",1],["mod.arousal.gain",-.5]],"голос ломается, дрожит","не меняется ни при чём"],
 ["Мягкость / теплота",[["sp.tenderness",1],["soc.caring",.5],["sp.rudeness",-1]],"сухо, жёстко","ласково, обволакивающе"],
 ["Энергия / напор",[["soc.dominance",1],["mod.dominance.bias",1],["mod.arousal.bias",.5]],"тихо, уступающе","громко, ведёт"],
 ["Формальность",[["sp.formality",1],["soc.formality",1]],"сленг, «ты»","этикет, «вы», полные фразы"],
 ["Игривость / смех",[["soc.playful",1],["sp.tease",1],["def.humor",.5]],"серьёзно","смешок в голосе, дразнит"],
 ["Колкость",[["sp.sarcasm",1],["sp.rudeness",.5],["dark.provoke",.5]],"без острых углов","подколки, острые края"],
 ["Придыхание / чувственность",[["des.tease_erotic",1],["des.libido",.7],["emo.arousal.hide",-.5]],"нейтрально","с придыханием, интимно"],
 ["Театральность",[["sp.drama",1],["mot.entertain",.5]],"буднично","театрально, с растяжкой слов"],
 ["Многословность",[["sp.verbosity",1]],"короткие реплики","развёрнуто"],
];
function voiceParam(p){let s=0,w=0,used=[];for(const [id,k] of p[1]){const g=byId[id];if(!g||!g.c)continue;s+=g.v*Math.sign(k)*Math.abs(k)*g.c;w+=Math.abs(k)*g.c;used.push(g.name.toLowerCase())}
  return {v:w?(1+s/w)/2:.5,def:!w,used}}
const LVL=v=>v<.15?"почти нет":v<.35?"ниже среднего":v<.65?"обычно":v<.85?"выражено":"предельно";
function renderVoice(){
  const el=document.getElementById("voice");const V=CHAR.voice||{};
  const P=VOICE_PARAMS.map(p=>Object.assign({n:p[0],neg:p[2],pos:p[3]},voiceParam(p)));
  const cap=P.filter(p=>!p.def).length;
  // маска в голосе: чувства, которые персонаж прячет (hide ≥ .5) — голос не должен их выдавать
  const hid=all.filter(g=>g.c&&g.id.startsWith("emo.")&&g.v>=.5).map(g=>g.name.toLowerCase());
  const shown=all.filter(g=>g.c&&g.id.startsWith("emo.")&&g.v<=-.5).map(g=>g.name.toLowerCase());
  // настройки речи (ElevenLabs-подобные): stability, style, speed — из параметров
  const st=P[3].v,sty=(P[2].v+P[10].v)/2,spd=P[0].v;
  const settings={stability:+(0.25+st*.6).toFixed(2),similarity_boost:0.8,style:+(sty*.8).toFixed(2),speed:+(0.85+(spd-.5)*.5).toFixed(2)};
  // текстовый промпт Voice Design: воплощение (тембр, возраст) + геном (манера). Только выраженные параметры, только полюсом
  const strong=P.filter(p=>!p.def&&Math.abs(p.v-.5)>=.2).sort((a,b)=>Math.abs(b.v-.5)-Math.abs(a.v-.5));
  const L=[];
  L.push(\`# Голос · \${CHAR.name}\`);
  if(V.mode==="clone"){L.push(\`Режим: клонирование с аудио. Описание ниже — не для генерации, а для проверки: сходится ли снятый геном с тем, как человек звучит на самом деле.\`)}
  L.push(\`## Тембр (слой воплощения, не геном)\`);
  L.push(\`- \${V.gender||"—"}, \${V.age||"—"}; язык: \${V.lang||"—"}\`);
  L.push(\`- \${V.timbre||"—"}\`);
  L.push(\`## Манера (из генома)\`);
  if(!strong.length)L.push(\`- не снято: параметры не отличаются от «как у всех»\`);
  strong.forEach(p=>L.push(\`- \${p.n.toLowerCase()}: \${p.v>.5?p.pos:p.neg}\${p.v>.85||p.v<.15?" — предельно":""}\`));
  if(hid.length){L.push(\`## Чего голос не выдаёт\`);L.push(\`- даже когда чувствует: \${hid.join(", ")}\`)}
  if(shown.length){L.push(\`## Что слышно сразу\`);L.push(\`- \${shown.join(", ")}\`)}
  L.push(\`## Настройки речи\`);L.push(\`- stability \${settings.stability} · style \${settings.style} · speed \${settings.speed} · similarity \${settings.similarity_boost}\`);
  el.innerHTML=\`<h2>Предполагаемый голос</h2><p class="lead">Канал V, часть 1 — голос. Тембр, возраст и пол в геном не входят (слой воплощения, задаются на персонажа). Всё остальное — темп, паузы, интонация, устойчивость, теплота — вычисляется из генов с весом уверенности; неснятые гены не участвуют, параметр остаётся «как у всех» и помечен серым. Справа — то, что уходит в конструктор голоса.</p>
  <div><div class="emb"><div><b>\${V.mode==="clone"?"клон":"дизайн"}</b><span>режим</span></div><div><b>\${V.gender||"—"}</b><span>пол</span></div><div><b>\${V.age||"—"}</b><span>возраст</span></div><div><b>\${cap} / \${P.length}</b><span>параметров снято</span></div></div>
  <div class="eyebrow" style="margin-bottom:8px">параметры манеры · из генома</div>
  <div class="vp"><div class="h"><span>параметр</span><span>знач.</span><span></span><span>из генов</span></div>\${P.map(p=>\`<div class="\${p.def?'def':''}"><span title="\${p.neg} ↔ \${p.pos}">\${p.n}</span><span>\${p.v.toFixed(2)}</span><span><i style="width:\${Math.round(p.v*100)}%"></i></span><span>\${p.def?"не снято — по умолчанию":p.used.join(", ")}</span></div>\`).join("")}</div></div>
  <div><div class="colscroll"><div class="eyebrow" style="margin-bottom:8px">промпт голоса <span style="color:var(--dim);letter-spacing:0;text-transform:none">\${L.length} строк</span></div><pre class="vpre">\${L.join("\\n").replace(/^(#+ .*)$/gm,"<b>$1</b>")}</pre></div></div>\`;
}
renderVoice();

// ---------- архетипы: библиотека независимых типов`);

fs.writeFileSync("gs.html",t);console.log("voice ok");
// ---- [4] переключатель вкладок: добавить voice ----
let t2=fs.readFileSync("gs.html","utf8");
if(!t2.includes('["genome","trace","comp","arch","chars"]')){console.error("nav list not found");process.exit(1)}
t2=t2.replace('["genome","trace","comp","arch","chars"]','["genome","trace","comp","voice","arch","chars"]');
fs.writeFileSync("gs.html",t2);console.log("nav ok");
// ---- [5] шапка: шесть вкладок — уже кнопки, чтобы бренд и цифры не ломались ----
let t3=fs.readFileSync("gs.html","utf8");
t3=t3.replace('.nav button{font:500 12px var(--fb);letter-spacing:.04em;color:var(--muted);padding:8px 14px;border-radius:999px;min-width:118px;text-align:center}','.nav button{font:500 12px var(--fb);letter-spacing:.04em;color:var(--muted);padding:8px 10px;border-radius:999px;min-width:86px;text-align:center}');
fs.writeFileSync("gs.html",t3);console.log("bar ok",t3.includes("min-width:86px"));
let t4=fs.readFileSync("gs.html","utf8");t4=t4.replace('.stats{display:flex;gap:26px;white-space:nowrap}','.stats{display:flex;gap:18px;white-space:nowrap}');fs.writeFileSync("gs.html",t4);
