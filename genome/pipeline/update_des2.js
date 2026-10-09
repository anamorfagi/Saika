// update_des2.js — расширение блока «Влечение и близость» под типажи эротических произведений (взрослые персонажи):
//  +3 гена: des.arousal_override (влечение перебивает рассудок), des.taboo_effect (запрет тормозит ↔ заводит), des.yield_pressure (стойкость под давлением)
//  +7 сигнатур семейства «аниме-типаж» с флагом adult (скрыты у детей и ИИ), описания генов, стемы описания, корреляции.
// Запуск: node update_des2.js — ДО update_store (TEMPLATE копирует блоки) и до sigs_dump.
const fs=require("fs");let t=fs.readFileSync("gs.html","utf8");
function rep(a,b,all){if(!t.includes(a)){console.error("не найдено:",a.slice(0,80));process.exit(1)}t=all?t.split(a).join(b):t.replace(a,b)}

// [1] гены — во все копии структуры блоков (определение + TEMPLATE, если уже есть)
const NEW=`,["des.arousal_override","Влечение против рассудка",0,0,"P,E",[],"голова остаётся ясной","желание выключает логику и правила"],["des.taboo_effect","Действие запрета",0,0,"P,E",[],"запрет тормозит","запрет заводит"],["des.yield_pressure","Стойкость под давлением",0,0,"P,A",[],"сопротивление держится","уступает с каждой попыткой"]`;
rep(`["des.shame_link","Стыд вокруг влечения",0,0,"P,E",[],"влечение не стыдит","стыд сильнее желания"]`,`["des.shame_link","Стыд вокруг влечения",0,0,"P,E",[],"влечение не стыдит","стыд сильнее желания"]`+NEW,true);
// [2] описания
rep(`"des.shame_link":"Стыд вокруг влечения. Высокое — стыд сильнее желания; низкое — влечение не стыдит."`,
`"des.shame_link":"Стыд вокруг влечения. Высокое — стыд сильнее желания; низкое — влечение не стыдит.",
"des.arousal_override":"Что делает возбуждение с мышлением. Высокое — при возбуждении отключаются логика, правила и осторожность («поскользнулась» — и уже согласна); низкое — голова ясная в любом состоянии. Отдельно от силы влечения (des.libido): сильное влечение при низком override — человек хочет, но решает головой.",
"des.taboo_effect":"Как действует запрет (место, статус, чужой партнёр, риск быть увиденной). Высокое — запрет заводит, чем нельзя — тем сильнее; низкое — запрет тормозит и гасит желание. Это ключ к сценам «на работе», «при всех», «чужая жена».",
"des.yield_pressure":"Стойкость отказа под повторным давлением. Высокое — «нет» слабеет с каждой попыткой, уступает после N-й; низкое — отказ держится. Отдельно от общей уступчивости (soc.compliance): касается только напора в близости."`);
// [3] сигнатуры взрослых типажей — после «Ара-ара онэ-сан»
rep(`{n:"Гяру",fam:"дере",sex:"f",`,`{n:"Чистый лист",nm:"Чистый лист",fam:"дере",adult:true,d:"Намёк не читается как намёк, а собственное возбуждение проходит по статье «наверное, температура». Отказ держится ровно до третьей попытки, а наутро история переписывается во что-то приемлемое: «ну я же не против». Это не глупость — просто в этой сфере опыта ноль и ориентиров тоже.",
  c:[["des.naivety",.5,1],["des.yield_pressure",.5,1],["soc.compliance",.3,1],["ct.self_deceive",.3,1],["def.denial",.3,1],["dyn.shame.decay",.3,1],["cog.evidence_need",-1,-.2],["des.arousal_override",.3,1]]},
 {n:"Запретный плод",nm:"Запретный плод",fam:"дере",adult:true,d:"Тормоз и педаль перепутаны местами: чем нельзя — на работе, при людях, с чужим партнёром — тем интереснее. Инициатива своя, о желании говорит прямо, регламент идёт как декорация: «дверь закрою — и ладно». Убери запрет — и азарт гаснет вместе с ним.",
  c:[["des.taboo_effect",.5,1],["des.libido",.4,1],["des.initiative",.3,1],["des.talk_ease",.3,1],["mor.law",-1,0],["mot.novelty",.2,1],["des.shame_link",-1,.1]]},
 {n:"Двойное дно",nm:"Двойное дно",fam:"дере",adult:true,d:"Снаружи дистанция, этикет и полный контроль. Внутри желание, намертво сцепленное со стыдом, и низкий порог, за которым голова выключается — срыв выглядит как другой человек в том же теле. Наутро включается объяснение «это ничего не значит», и маска встаёт на место.",
  c:[["soc.formality",.4,1],["soc.dominance",.2,1],["des.shame_link",.4,1],["des.arousal_override",.5,1],["dark.guilt_after",.3,1],["emo.desire.hide",.4,1],["def.rationalize",.3,1]]},
 {n:"Ненасытная",nm:"Ненасытный",fam:"дере",adult:true,d:"Влечение ровное, сильное и без тени стыда: близость тут часть быта, а не событие. Ведёт сама, просит прямо, после встаёт и возвращается к делам — «здорово, как всегда, ладно, мне пора». Привязанность при этом может быть почти нулевой, одно другому не мешает.",
  c:[["des.libido",.6,1],["des.initiative",.5,1],["des.talk_ease",.5,1],["des.shame_link",-1,-.2],["des.love_vs_desire",-1,0],["soc.dominance",.3,1],["des.arousal_override",.2,1]]},
 {n:"Тихое согласие",nm:"Тихое согласие",fam:"дере",adult:true,d:"Отказ звучит тихо и без опоры: «не надо… я не хочу», через минуту — «ну ладно». Стыд идёт впереди желания, прикосновений не ищет, но и границу не держит, а после случившегося связь не рвёт — наоборот, цепляется сильнее. Обида выговаривается позже и обычно не тому.",
  c:[["des.shame_link",.5,1],["des.talk_ease",-1,-.3],["des.yield_pressure",.4,1],["soc.compliance",.3,1],["mot.keep_relation",.3,1],["des.initiative",-1,0],["dyn.shame.threshold",-1,0]]},
 {n:"Чидзё",fam:"дере",sex:"f",adult:true,d:"Жанровый типаж: старшая и опытная, для которой чужое смущение — главное развлечение. Границы младших считывает отлично и переступает намеренно, вкус узкий и свой: «ну что застыл, я же ещё ничего не сделала». Инициатива всегда на её стороне, отступать не планирует.",
  c:[["des.tease_erotic",.5,1],["des.initiative",.5,1],["dark.provoke",.4,1],["soc.boundaries",-1,-.2],["des.quirk",.4,1],["soc.dominance",.4,1],["des.taboo_effect",.3,1]]},
 {n:"Нэторарэ",nm:"Нэторарэ",fam:"дере",adult:true,d:"Жанровый термин про то, как привязанность к одному уживается с уступкой другому. Сопротивление тает под повторным напором, дальше включается ремонт истории: «это ничего не значило», «он сам всё придумал». Вина настоящая и даже мучает, но поведения не меняет — связь держится с обоими.",
  c:[["des.yield_pressure",.5,1],["ct.self_deceive",.4,1],["def.rationalize",.4,1],["mot.keep_relation",.4,1],["mor.loyalty",-1,.2],["dark.guilt_after",.2,1],["des.taboo_effect",.2,1]]},
 {n:"Гяру",fam:"дере",sex:"f",`);
// [4] фильтр взрослых типажей: у детей и ИИ не показываются и не считаются
rep(`ranked=SIGS.map((s,i)=>({s,i,m:sigMatch(s)})).filter(r=>!r.s.sex||r.s.sex===SEX)`,`ranked=SIGS.map((s,i)=>({s,i,m:sigMatch(s)})).filter(r=>!r.s.sex||r.s.sex===SEX).filter(r=>!r.s.adult||!(CHAR.kind==="ребёнок"||CHAR.child||(typeof isAI==="function"&&isAI())))`,true);
fs.writeFileSync("gs.html",t);
// [5] стемы описания и корреляции — в файлы конвейера (update_persona встраивает их в HTML)
const lexP="pipeline/desc_lex.json",lex=JSON.parse(fs.readFileSync(lexP,"utf8"));
Object.assign(lex,{
 "теряет голову":[["des.arousal_override",0.6]],"голову теря":[["des.arousal_override",0.6]],"забывает обо всём":[["des.arousal_override",0.5]],"не может остановиться":[["des.arousal_override",0.5],["will.stop",-0.4]],
 "хладнокров":[["des.arousal_override",-0.5],["sp.voice_stability",0.4]],
 "заводит запрет":[["des.taboo_effect",0.6]],"чем нельзя":[["des.taboo_effect",0.5]],"на работе":[["des.taboo_effect",0.3]],"при всех":[["des.taboo_effect",0.3]],"боится, что увидят":[["des.taboo_effect",-0.4],["dyn.shame.threshold",-0.3]],
 "уступа":[["des.yield_pressure",0.5],["soc.compliance",0.3]],"не может отказать":[["des.yield_pressure",0.6]],"сдаётся":[["des.yield_pressure",0.5]],"непреклонн":[["des.yield_pressure",-0.6],["will.persist",0.3]],"твёрдое нет":[["des.yield_pressure",-0.6]]
});
fs.writeFileSync(lexP,JSON.stringify(lex,null,1).replace(/\[\n\s+\[/g,"[[").replace(/\],\n\s+\[/g,"],[").replace(/\]\n\s+\]/g,"]]"),"utf8");
const corP="pipeline/correlations.json",cor=JSON.parse(fs.readFileSync(corP,"utf8"));
const add=(s,d,w)=>{cor[s]=cor[s]||[];if(!cor[s].some(x=>x[0]===d))cor[s].push([d,w])};
add("des.libido","des.arousal_override",.4);add("will.impulsive","des.arousal_override",.4);add("will.stop","des.arousal_override",-.4);add("mod.arousal.gain","des.arousal_override",.3);
add("mor.law","des.taboo_effect",-.4);add("mot.novelty","des.taboo_effect",.3);add("dark.provoke","des.taboo_effect",.3);add("dyn.shame.threshold","des.taboo_effect",.2);
add("soc.compliance","des.yield_pressure",.5);add("des.naivety","des.yield_pressure",.3);add("will.persist","des.yield_pressure",-.3);add("soc.boundaries","des.yield_pressure",-.2);add("ct.self_deceive","des.yield_pressure",.2);
add("des.arousal_override","des.yield_pressure",.3);add("des.yield_pressure","ct.self_deceive",.3);
// связи для блоков развития, внимания, памяти — чтобы предполагаемая нить доставала до генов, куда улики почти не попадают
add("mem.consolidate","dev.repeat_sens",.6);add("mem.single_event","dev.shock_sens",.7);add("dyn.fear.peak","dev.shock_sens",.3);add("bond.depth","dev.close_inf",.4);add("soc.compliance","dev.close_inf",.4);add("dev.authority_inf","dev.close_inf",.4);
add("will.discipline","dev.habit_form",.4);add("mem.consolidate","dev.habit_form",.4);add("will.recover","dev.trauma_recover",.6);add("dev.plasticity","dev.trauma_recover",.3);add("will.frustration","dev.regress",-.5);add("def.numb","dev.regress",.3);
add("dyn.shame.dwell","att.rumination",.5);add("dyn.sadness.dwell","att.rumination",.5);add("mem.sig_critic","att.rumination",.4);add("sp.emotional","att.emotion_pri",.4);add("mod.arousal.gain","att.emotion_pri",.4);add("will.against_emo","att.emotion_pri",-.5);
add("mot.novelty","att.novelty_pri",.5);add("perc.novelty","att.novelty_pri",.5);add("will.persist","att.goal_hold",.6);add("mot.order","att.unfinished",.4);add("cog.flex","att.switch",.4);
add("mem.sig_praise","self.ext_depend",.4);add("mem.sig_reject","bond.reject_fear",.5);add("bond.reject_fear","mem.sig_reject",.5);add("bond.depth","mem.sig_closeness",.5);add("mot.keep_relation","mem.sig_joint",.4);add("dark.grudge","mem.sig_conflict",.6);add("mor.promise","mem.sig_promise",.6);
add("mod.valence.bias","mem.recall_bias",.6);add("dev.reframe_prob","mem.reinterpret",.6);add("cog.depth","mem.detail_cause",.5);add("cog.systemic","mem.link_similar",.5);add("perc.words","mem.detail_words",.5);
add("perc.emotion","perc.face_body",.5);add("perc.emotion","perc.tone",.5);add("soc.hide_intent","perc.hidden_motive",.4);add("dark.manipulate","perc.hidden_motive",.4);add("perc.threat","perc.absence",.3);add("dark.exploit","perc.opportunity",.4);
add("self.worth","self.competence",.4);add("self.worth","self.ideal_gap",-.5);add("self.ext_depend","self.face_keep",.4);add("mor.own_fault","self.admit_error",.6);add("self.critic_res","mem.sig_critic",-.5);
fs.writeFileSync(corP,JSON.stringify(cor,null,1).replace(/\[\n\s+\[/g,"[[").replace(/\],\n\s+\[/g,"],[").replace(/\]\n\s+\]/g,"]]"),"utf8");
console.log("des2 ok: +3 гена, +7 типажей, лексика",Object.keys(lex).length,"корреляций",Object.values(cor).filter(Array.isArray).reduce((a,x)=>a+x.length,0));
