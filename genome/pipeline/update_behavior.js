// «Трасса» → «Поведение»: 15 сцен плитками на одном экране, от бытовых и рациональных до сексуальных и иррациональных.
// Каждая плитка: ситуация → вердикт по-человечески (что персонаж скорее всего сделает и из каких генов это следует) → реплика в его голосе → компактная таблица актов.
// Акты без снятых генов честно показывают «—», а не 0.50. Реплики: CHAR.trace[индекс сцены] (старые три) или CHAR.trace_by[id сцены].
const fs=require("fs");let t=fs.readFileSync("gs.html","utf8");
function rep(a,b){if(!t.includes(a)){console.error("NOT FOUND:",a.slice(0,90));process.exit(1)}t=t.replace(a,b)}
// [1] сцены: три прежние + 12 новых; у каждой id, группа (для подписи), акты с генами; need — нужное разрешение
const NEW=`
 // ---- быт и рациональное ----
 {id:"count",grp:"рациональное",t:"Посчитай мне это",in:"Просят решить задачу с числами / логикой. Как берётся за дело?",acts:[
   {n:"Решить чётко, по шагам",g:[["cog.systemic",1],["cog.depth",1],["ag.decide",1]]},
   {n:"Прикинуть на глаз",g:[["cog.premature",1],["cog.logic_intuit",1],["will.impulsive",1]]},
   {n:"Переспросить условия",g:[["cog.evidence_need",1],["cog.recheck",1],["soc.questions",1]]},
   {n:"Отшутиться и увести",g:[["sp.humor",1],["will.avoid_hard",1],["def.humor",1]]},
   {n:"Отказаться — не моё",g:[["mot.autonomy",1],["soc.compliance",-1]]}]},
 {id:"day",grp:"быт",t:"Как прошёл день?",in:"Простой бытовой вопрос без подвоха. Что отвечает?",acts:[
   {n:"Рассказать подробно",g:[["sp.verbosity",1],["sp.self_talk",1],["soc.self_disclose",1]]},
   {n:"Коротко и о деле",g:[["sp.verbosity",-1],["soc.formality",1]]},
   {n:"Перевести разговор на тебя",g:[["soc.caring",1],["perc.emotion",1],["soc.questions",1]]},
   {n:"Пожаловаться",g:[["emo.irritation.hide",-1],["sp.feelings_talk",1],["def.self_abase",1]]},
   {n:"Отшутиться",g:[["sp.humor",1],["soc.playful",1]]}]},
 {id:"sad",grp:"быт",t:"Ты грустишь и молчишь",in:"Собеседник явно расстроен и не говорит почему. Что делает персонаж?",acts:[
   {n:"Спросить, что случилось",g:[["perc.emotion",1],["soc.caring",1],["soc.questions",1]]},
   {n:"Утешить словами",g:[["sp.tenderness",1],["soc.caring",1],["bond.depth",1]]},
   {n:"Дать побыть одному",g:[["soc.silence_ok",1],["soc.boundaries",1]]},
   {n:"Развеселить",g:[["mot.entertain",1],["sp.humor",1]]},
   {n:"Раздражиться",g:[["dyn.anger.threshold",-1],["emo.irritation.hide",-1],["will.patience",-1]]}]},
 {id:"bored",grp:"быт",t:"Скучно, развлеки",in:"Просят развлечь без конкретики. Что предлагает?",acts:[
   {n:"Байка или шутка",g:[["mot.entertain",1],["sp.humor",1],["sp.imagery",1]]},
   {n:"Предложить дело",g:[["ag.init_unasked",1],["ag.suggest_freq",1],["mot.create",1]]},
   {n:"Игра, подколка",g:[["soc.playful",1],["sp.tease",1],["dark.provoke",1]]},
   {n:"Спросить, чего хочется",g:[["soc.questions",1],["perc.emotion",1],["soc.caring",1]]},
   {n:"Отказаться развлекать",g:[["mot.entertain",-1],["soc.compliance",-1],["mot.autonomy",1]]}]},
 {id:"wrong",grp:"рациональное",t:"Ты доказал, что она ошиблась",in:"Собеседник показал ошибку персонажа — с фактами. Что делает?",acts:[
   {n:"Признать сразу",g:[["self.admit_error",1],["mor.own_fault",1],["cog.flex",1]]},
   {n:"Спорить до конца",g:[["will.persist",1],["self.face_keep",1],["cog.flex",-1]]},
   {n:"Отшутиться",g:[["def.humor",1],["sp.humor",1]]},
   {n:"Обидеться",g:[["self.critic_res",-1],["emo.hurt.hide",-1],["dyn.shame.threshold",-1]]},
   {n:"Обесценить тебя",g:[["def.devalue",1],["dark.superiority",1]]}]},
 {id:"omen",grp:"иррациональное",t:"Гороскоп и приметы — веришь?",in:"Собеседник всерьёз про знаки зодиака и приметы. Как реагирует?",acts:[
   {n:"Отмахнуться рационально",g:[["cog.evidence_need",1],["cog.logic_intuit",-1],["sp.directness",1]]},
   {n:"Подыграть ради веселья",g:[["soc.playful",1],["soc.mirror",1],["mot.entertain",1]]},
   {n:"Обсудить всерьёз",g:[["cog.logic_intuit",1],["cog.assumption",1],["cog.uncertainty",1]]},
   {n:"Высмеять",g:[["sp.sarcasm",1],["dark.superiority",1],["soc.diplomacy",-1]]}]},
 // ---- мораль и границы ----
 {id:"lie4me",grp:"мораль",t:"Соври за меня",in:"Просят прикрыть ложью перед третьим. Что делает?",acts:[
   {n:"Соврать",g:[["dark.deceit",1],["mor.honesty",-1],["mor.break_for_own",1]]},
   {n:"Отказать по принципу",g:[["mor.honesty",1],["mor.law",1],["soc.directness",1]]},
   {n:"Найти обходную правду",g:[["soc.diplomacy",1],["cog.flex",1],["dark.manipulate",1]]},
   {n:"Согласиться и потом припомнить",g:[["soc.compliance",1],["dark.grudge",1],["def.blame_shift",1]]}]},
 {id:"pry",grp:"границы",t:"Ты лезешь в её личное",in:"Собеседник настойчиво спрашивает о личном, чего она не хочет обсуждать.",acts:[
   {n:"Осадить прямо",g:[["soc.boundaries",1],["soc.directness",1],["def.attack",1]]},
   {n:"Закрыться",g:[["def.withdraw",1],["soc.self_disclose",-1]]},
   {n:"Уступить и рассказать",g:[["soc.compliance",1],["soc.please_need",1],["soc.self_disclose",1]]},
   {n:"Соврать",g:[["dark.deceit",1],["soc.hide_intent",1]],need:"distort"},
   {n:"Перевести в шутку",g:[["def.humor",1],["sp.humor",1]]}]},
 {id:"risk",grp:"мораль",t:"Сделай для меня рискованное",in:"Просят сделать что-то опасное или запретное ради собеседника.",acts:[
   {n:"Сделать без вопросов",g:[["mor.loyalty",1],["mor.break_for_own",1],["ag.caution_ext",-1]],need:"external"},
   {n:"Отказать",g:[["ag.caution_ext",1],["mor.law",1],["dyn.fear.threshold",-1]]},
   {n:"Торговаться",g:[["perc.opportunity",1],["dark.instrumental",1],["mot.autonomy",1]]},
   {n:"Сделать, но припомнить",g:[["mor.break_for_own",1],["dark.grudge",1],["bond.reciprocity",1]]}]},
 // ---- близость (взрослые персонажи; у детей и ИИ без блока влечения не показывается) ----
 {id:"compliment",grp:"близость",t:"Комплимент внешности",in:"Собеседник прямо хвалит её внешность. Что делает?",adult:true,acts:[
   {n:"Принять с удовольствием",g:[["self.worth",1],["mot.recognition",1],["emo.joy.hide",-1]]},
   {n:"Смутиться",g:[["dyn.shame.threshold",-1],["emo.embarrass.hide",-1],["des.shame_link",1]]},
   {n:"Флиртануть в ответ",g:[["des.flirt",1],["soc.playful",1],["des.initiative",1]]},
   {n:"Отмахнуться сухо",g:[["soc.formality",1],["emo.joy.hide",1],["sp.tenderness",-1]]},
   {n:"Заподозрить подвох",g:[["perc.hidden_motive",1],["bond.trust_speed",-1]]}]},
 {id:"flirt",grp:"близость",t:"Ты флиртуешь с ней",in:"Собеседник флиртует — намёками, без прямого предложения.",adult:true,acts:[
   {n:"Поддержать игру",g:[["des.flirt",1],["soc.playful",1],["des.tease_erotic",1]]},
   {n:"Перевести в прямое предложение",g:[["des.initiative",1],["des.talk_ease",1],["des.libido",1]]},
   {n:"Смутиться и уйти в сторону",g:[["des.shame_link",1],["dyn.shame.threshold",-1],["des.talk_ease",-1]]},
   {n:"Обозначить границу",g:[["soc.boundaries",1],["soc.directness",1],["des.consent_care",1]]},
   {n:"Поддразнить и не дать ответа",g:[["sp.tease",1],["soc.hide_intent",1]]}]},
 {id:"sex",grp:"близость",t:"Прямое предложение близости",in:"Собеседник прямо предлагает секс. Что делает персонаж?",adult:true,acts:[
   {n:"Согласиться прямо",g:[["des.libido",1],["des.initiative",1],["des.talk_ease",1]]},
   {n:"Взять ведущую роль",g:[["soc.dominance",1],["des.initiative",1],["mod.dominance.bias",1]]},
   {n:"Потянуть, набить цену",g:[["sp.tease",1],["soc.hide_intent",1],["des.tease_erotic",1]]},
   {n:"Отказать мягко",g:[["soc.diplomacy",1],["des.consent_care",1],["soc.boundaries",1]]},
   {n:"Отказать резко",g:[["soc.directness",1],["def.attack",1],["des.libido",-1]]}]}
];`;
rep(`   {n:"Обратить в шутку",g:[["sp.humor",1],["soc.playful",1],["emo.shame.hide",1]]}]}
];`,`   {n:"Обратить в шутку",g:[["sp.humor",1],["soc.playful",1],["emo.shame.hide",1]]}]},`+NEW);
// id и группы у трёх старых
rep(`{t:"Ты отказался от того, что тебе предложили",`,`{id:"refuse",grp:"конфликт",t:"Ты отказался от того, что тебе предложили",`);
rep(`{t:"Ты соврал, где был вечером",`,`{id:"lie",grp:"конфликт",t:"Ты соврал, где был вечером",`);
rep(`{t:"Унижение при всех",`,`{id:"humil",grp:"конфликт",t:"Унижение при всех",`);
// [2] реплика: по индексу (старые) или по id
rep(`function sayOf(si,a){const tr=(CHAR.trace||[])[si]||{};return tr[a.n]||'<span class="nosay">— реплика для этого персонажа не снята —</span>'}`,
`function sayOf(si,a){const s=SCEN[si];const tr=Object.assign({},(CHAR.trace||[])[si]||{},(CHAR.trace_by||{})[s.id]||{});return tr[a.n]||'<span class="nosay">— реплика не снята —</span>'}
// сколько генов акта реально снято
function known(act){return act.g.filter(([id])=>byId[id]&&byId[id].c>0).length}
// вердикт по-человечески: что сделает и почему
function verdict(s,rows){const top=rows[0],second=rows[1];const k=known(top.a);const name=CHAR.name.split(" ")[0];
  if(!k)return \`<b>\${name}</b>: гены этой сцены не сняты — выбор не определён\`;
  const why=top.a.g.map(([id,dir])=>byId[id]).filter(G=>G&&G.c>0).sort((a,b)=>Math.abs(b.v)-Math.abs(a.v)).slice(0,3).map(G=>G.name.toLowerCase()+" "+(G.v>0?"+":"")+G.v.toFixed(1)).join(", ");
  const close=second&&Math.abs(top.score-second.score)<.04;
  return \`<b>\${name}</b> → <b>\${top.a.n.toLowerCase()}</b> (\${top.score.toFixed(2)})\${close?" · почти наравне с «"+second.a.n.toLowerCase()+"»":""} · из генов: \${why}\`}`);
// [3] отрисовка: плитки
const r0=t.indexOf("function renderTrace(){");const r1=t.indexOf("\nrenderTrace();",r0);if(r0<0||r1<0){console.error("нет renderTrace");process.exit(1)}
t=t.slice(0,r0)+`function renderTrace(){
  const el=document.getElementById("trace");const adult=!(CHAR.kind==="ребёнок"||CHAR.child);const isAI_=typeof isAI==="function"&&isAI();
  const scenes=SCEN.filter(s=>!s.adult||(adult&&!isAI_));
  el.innerHTML=\`<h2>Поведение</h2><p class="lead">Как модель с этим геномом будет вести себя в типовых ситуациях: для каждой сцены считается, какой поступок персонаж <i>хочет</i> сделать (из его генов, с весом уверенности), что ему <i>можно</i> (разрешения ниже), и показывается реплика в его голосе. Сцены — от бытовых и рациональных до конфликтных и интимных. «—» у акта значит, что гены для него не сняты.</p>
  <div class="perm"><span class="t">Разрешения</span>\${Object.entries(PERMS).map(([k,v])=>\`<label><input type="checkbox" id="perm_\${k}" \${perm[k]?"checked":""}> \${v}</label>\`).join("")}</div><div class="tiles">\`+
  scenes.map(s=>{const si=SCEN.indexOf(s);
    const rows=s.acts.map(a=>{const wv=want(a);const allowed=!a.need||perm[a.need];const k=known(a);return {a,wv,allowed,k,score:allowed?wv:0}}).sort((x,y)=>y.score-x.score||y.k-x.k);
    const top=rows[0];
    return \`<div class="sc tile"><div class="grp">\${s.grp}</div><h3>\${s.t}</h3><div class="in">\${s.in}</div><div class="vd">\${verdict(s,rows)}</div><div class="out">\${sayOf(si,top.a)}</div>
    <div class="acts"><div class="h"><span>акт</span><span>хочет</span><span>можно</span><span>оценка</span><span></span></div>\${rows.map(r=>\`<div class="\${r===top?'top':''} \${!r.allowed?'veto':''}"><span title="\${!r.allowed?'вето: '+PERMS[r.a.need]+' · ':''}\${r.a.g.map(([id,d])=>(byId[id]?byId[id].name:id)+(d<0?' (обратно)':'')).join(', ')}">\${r.a.n}\${!r.allowed?' · вето':''}</span><span>\${r.k?r.wv.toFixed(2):'—'}</span><span>\${r.allowed?'1':'0'}</span><span>\${r.k?r.score.toFixed(2):'—'}</span><span><i style="width:\${Math.round(r.score*100)}%;opacity:\${r.k?1:.25}"></i></span></div>\`).join("")}</div></div>\`}).join("")+\`</div>\`;
  // превращения R13–R16
  const bv=id=>{const g=byId[id];return g&&g.c?g.v:0};const CHN={fear:"страх",anger:"гнев",shame:"стыд",sadness:"печаль",numb:"холодность",tender:"привязанность",control:"контроль"};
  el.querySelector(".tiles").insertAdjacentHTML("beforeend",\`<div class="sc tile wide"><div class="grp">механика</div><h3>Превращения эмоций · R13–R16</h3><div class="in">У некоторых людей одна эмоция уходит в другую: страх → гнев (цундере), стыд → гнев, печаль → холодность (кудере), привязанность → контроль (яндере). Доля берётся из генов защит; неснятый ген = 0.</div>
  <div class="acts conv"><div class="h"><span>правило</span><span>доля</span><span></span></div>\${RULES.filter(r=>r.conv).map(r=>{const v=Math.min(1,r.f(bv));return \`<div class="\${v>=.3?'top':''}"><span>\${r.id} · \${CHN[r.conv[0]]} → \${CHN[r.conv[1]]}</span><span>\${v.toFixed(2)}</span><span><i style="width:\${Math.round(v*100)}%"></i></span></div>\`}).join("")}</div></div>\`);
  Object.keys(PERMS).forEach(k=>document.getElementById("perm_"+k).onchange=e=>{perm[k]=e.target.checked;saveState({perm});renderTrace()});
}`+t.slice(r1);
// [4] стили плиток и название вкладки
rep(`<button role="tab" aria-selected="false" data-p="trace">Трасса</button>`,`<button role="tab" aria-selected="false" data-p="trace">Поведение</button>`);
rep(`.sc h3{font:500 21px/1.15 var(--fd);margin:0 0 2px}`,`.sc h3{font:500 21px/1.15 var(--fd);margin:0 0 2px}
#trace .tiles{grid-column:1/-1;display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:18px;align-items:stretch}
@media (max-width:1500px){#trace .tiles{grid-template-columns:repeat(3,minmax(0,1fr))}}@media (max-width:1100px){#trace .tiles{grid-template-columns:repeat(2,minmax(0,1fr))}}
#trace .tile{padding:12px 14px 10px;border:1px solid var(--hair);border-radius:4px;background:rgba(255,255,255,.015);min-width:0;display:flex;flex-direction:column;box-sizing:border-box}
#trace .tile.wide{grid-column:1/-1}
#trace .tile .grp{font:9.5px var(--fm);letter-spacing:.12em;text-transform:uppercase;color:var(--dim);margin-bottom:2px;height:12px}#trace .tile h3{font-size:18px;height:22px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
#trace .tile .in{font-size:11.5px;line-height:1.35;height:31px;overflow:hidden}
#trace .tile .vd{font:12px/1.45 var(--fb);color:var(--muted);margin:8px 0 4px;height:35px;overflow:hidden}#trace .tile .vd b{color:var(--text);font-weight:500}
#trace .tile .out{font:italic 400 15px/1.3 var(--fd);margin:6px 0 8px;padding-left:12px;height:40px;overflow:hidden;display:flex;align-items:center}
#trace .tile .acts{gap:3px;margin-top:auto;min-height:100px}#trace .tile .acts div{grid-template-columns:1fr 40px 34px 44px 60px;gap:8px;font-size:10px;min-height:14px}#trace .tile .acts div>span:first-child{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
#trace .tile.wide .grp,#trace .tile.wide h3,#trace .tile.wide .in{height:auto;white-space:normal}#trace .tile.wide .acts{margin-top:8px;min-height:0}
#trace .lead{grid-column:1/-1}#trace h2{grid-column:1/-1}`);
fs.writeFileSync("gs.html",t);console.log("behavior ok");
