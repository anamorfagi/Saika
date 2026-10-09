// update_priors.js — предполагаемая нить, часть 2: априорные ожидания для КАЖДОГО гена из того, кто персонаж —
//  роль/род занятий (по титулу, источнику, описанию), возраст, вид, текст карточки через стемы DESC_LEX,
//  плюс второй проход корреляций (от уже предположенных генов, с половинным весом) и «индекс ума» → блоки мышления/памяти/внимания.
// Запуск: node update_priors.js (после update_dna, до update_cards). Правит gs.html.
const fs=require("fs");let t=fs.readFileSync("gs.html","utf8");
function rep(a,b){if(!t.includes(a)){console.error("не найдено:",a.slice(0,80));process.exit(1)}t=t.replace(a,b)}

rep(`const DNA={pred:0,agree:0,check:0,playing:false};`,`const DNA={pred:0,agree:0,check:0,playing:false};
// ---------- априори: кто она → чего ждать от генов, которых улики не коснулись ----------
// Роль узнаётся по тексту карточки (титул, источник, описание, identity). Формат: [регэксп, подпись, [[ген, ожидаемое v], …]]. Вес каждой строки — 0.35·c
const ROLE_PRIORS=[
 [/исследоват|учён|научн|лаборатор|физик|химик|биолог|инженер|проект.*андроид/i,"роль: исследователь",[["cog.depth",.5],["cog.evidence_need",.5],["cog.recheck",.4],["cog.systemic",.4],["cog.logic_intuit",-.4],["cog.metacog",.3],["cog.uncertainty",.2],["att.goal_hold",.5],["att.return",.3],["att.unfinished",.3],["will.persist",.5],["will.delay_reward",.3],["mot.learn",.5],["mot.explore",.4],["mot.create",.4],["mot.avoid_error",.3],["need.competence.weight",.5],["need.competence.sens",.3],["perc.detail",.4],["perc.contradict",.3],["mem.detail_cause",.4],["mem.link_similar",.3],["mem.consolidate",.2],["dev.reframe_prob",.3],["dev.authority_inf",-.2],["self.competence",.3],["mor.result",.2]]],
 [/ассистент|секретар|помощни|референт|администратор/i,"роль: ассистентка",[["mor.law",.4],["will.discipline",.4],["mot.order",.4],["need.order.weight",.3],["mot.useful",.5],["soc.compliance",.3],["soc.formality",.3],["att.unfinished",.3],["att.return",.3],["mem.sig_promise",.3],["mem.detail_words",.2],["dev.authority_inf",.4],["soc.please_need",.2],["mot.avoid_error",.3],["perc.detail",.3],["mor.promise",.3]]],
 [/убий|наёмн|наемн|боец|охотни|воин|киллер|мечник|ассасин/i,"роль: боец",[["perc.threat",.6],["will.against_emo",.4],["dark.callous",.3],["will.aggr_control",.2],["mor.wellbeing",-.3],["self.competence",.4],["will.impulsive",-.2],["dev.shock_sens",-.3],["att.goal_hold",.4],["perc.opportunity",.3],["will.frustration",.3],["def.numb",.2]]],
 [/правител|принцесс|королев|императ|аристократ|наследниц|вице-президент|президент|госпожа|леди|барышн/i,"роль: правительница",[["soc.dominance",.5],["soc.formality",.5],["perc.status",.5],["self.face_keep",.5],["need.recognition.weight",.3],["mot.control",.4],["dark.authoritarian",.3],["self.special_need",.3],["dev.authority_inf",-.2],["soc.self_disclose",-.3],["will.discipline",.3]]],
 [/медик|врач|сидел|лекар|санитар|компаньон по здрав|целител/i,"роль: медик",[["soc.caring",.6],["mot.protect",.5],["mot.useful",.5],["mor.wellbeing",.6],["perc.emotion",.4],["will.patience",.5],["need.nurturing.weight",.5],["dark.callous",-.5],["soc.questions",.3],["mem.detail_cause",.3]]],
 [/студент|школьни|ученица|ученик|старшеклас|лицеист|студсовет/i,"роль: учащаяся",[["dev.plasticity",.4],["dev.authority_inf",.3],["dev.close_inf",.4],["mot.learn",.3],["self.compare",.3],["need.recognition.weight",.2],["mem.sig_praise",.2],["mem.sig_critic",.2],["dev.habit_form",.2]]],
 [/идол|актрис|актёр|блогер|ютуб|youtube|стример|певиц|артист|канал/i,"роль: публичная",[["mot.attention",.5],["mot.entertain",.5],["soc.sociable",.4],["soc.initiative",.4],["self.ext_depend",.3],["sp.drama",.3],["perc.status",.2],["need.recognition.weight",.4],["soc.mirror",.2]]],
 [/служан|горничн|официант|прислуг|мэйд|maid/i,"роль: прислуга",[["mot.useful",.5],["soc.compliance",.4],["soc.formality",.4],["will.discipline",.3],["mor.law",.3],["self.worth",-.2],["def.please",.3],["perc.absence",.3],["mem.sig_promise",.2]]],
 [/учител|наставни|препод|тренер|сэнсэй|сенсей/i,"роль: наставница",[["mot.protect",.3],["soc.caring",.4],["will.patience",.4],["mot.learn",.3],["soc.dominance",.2],["dev.authority_inf",-.2],["soc.questions",.3],["mor.strict_others",.2],["cog.metacog",.2]]],
 [/солдат|военн|рыцар|офицер|гвард|стражн|полиц/i,"роль: служба",[["will.discipline",.5],["mor.law",.4],["dev.authority_inf",.4],["will.against_emo",.4],["perc.threat",.4],["mor.loyalty",.4],["mot.order",.3],["will.aggr_control",.3]]],
 [/изобретат|техник|хакер|механик|конструктор|программист|гоггл/i,"роль: изобретательница",[["mot.create",.5],["mot.explore",.5],["cog.associative",.3],["cog.systemic",.4],["mor.law",-.2],["mot.novelty",.3],["need.autonomy.weight",.3],["att.breadth",.3],["will.avoid_hard",-.3],["dev.reframe_prob",.3]]],
 [/дух|демон|бессмерт|бог|богин|проклят|нежить|вампир|ками/i,"роль: нечеловек",[["dev.plasticity",-.4],["dev.identity_res",.5],["mem.recall_recent",-.4],["dark.superiority",.3],["perc.status",.2],["dev.early_weight",.4],["self.integrity",.3]]],
 [/андроид|робот|ии|искусств.*интеллект|компаньон/i,"роль: машина",[["dev.plasticity",-.3],["dev.identity_res",.4],["self.integrity",.4],["att.switch",.3],["will.impulsive",-.3],["mem.detail_words",.4],["cog.recheck",.3],["dev.regress",-.3]]],
];
// возраст → пластичность и саморегуляция (взрослый vs подросток)
const AGE_PRIORS={adult:["возраст: взрослая",[["dev.plasticity",-.2],["dev.early_weight",.2],["will.impulsive",-.2],["cog.metacog",.2],["dev.identity_res",.3],["dev.habit_break",-.2],["mem.recall_recent",-.1]]],
  teen:["возраст: подросток",[["dev.plasticity",.3],["dev.close_inf",.3],["self.compare",.3],["will.impulsive",.2],["dev.identity_res",-.2],["att.novelty_pri",.2],["dev.habit_form",.2],["self.ideal_gap",.2]]]};
function ageBand(){const c=CHAR;const s=String((c.ageStated||"")+" "+((c.voice&&c.voice.age)||"")).toLowerCase();const m=s.match(/(\\d{2})/);
  if(c.kind==="ребёнок"||c.child)return "teen";if(m){const a=+m[1];return a<=19?"teen":"adult"}if(/взросл|около [2-9]\\d|\\b(2|3|4|5)\\d\\+?/.test(s))return "adult";if(/подрост|школь|лет 1\\d|1\\d лет/.test(s))return "teen";return null}
// текст карточки через стемы DESC_LEX: «не»/«без» перед словом меняет знак
function textPriors(push){if(typeof DESC_LEX==="undefined")return;const c=CHAR;const txt=[c.desc,...(c.identity||[]),...(c.never||[]),...((c.masks||[]).map(m=>m[1]))].filter(Boolean).join(" · ").toLowerCase();if(!txt)return;
  for(const stem in DESC_LEX){if(stem==="_")continue;let i=txt.indexOf(stem);if(i<0)continue;const before=txt.slice(Math.max(0,i-8),i);const neg=/(^|\\s)(не|без|ни)\\s*$/.test(before)?-1:1;
    for(const [g,v] of DESC_LEX[stem])push(g,Math.max(-1,Math.min(1,v*neg)),.22,"описание: «"+stem+"»"+(neg<0?" (отрицание)":""))}}
function priorsInto(push){const c=CHAR;const hay=[c.alias,c.src,c.desc,c.name,...(c.identity||[]),c.method].filter(Boolean).join(" · ");
  ROLE_PRIORS.forEach(([rx,lab,L])=>{if(lab==="роль: машина"){if(!(typeof isAI==="function"&&isAI()))return}else if(!rx.test(hay))return;L.forEach(([g,v])=>push(g,v,.35,lab))});
  const ab=ageBand();if(ab)AGE_PRIORS[ab][1].forEach(([g,v])=>push(g,v,.3,AGE_PRIORS[ab][0]));
  if(typeof isAI==="function"&&isAI())[["dev.plasticity",-.3],["self.integrity",.4],["will.impulsive",-.3]].forEach(([g,v])=>push(g,v,.3,"вид: ИИ"));
  textPriors(push)}`);

// подключение: априори — перед архетипами; после свода — второй проход корреляций от предположенных
rep(`  const top=SIGS.map(s=>({s,m:sigMatch(s)}))`,`  priorsInto(push);
  const top=SIGS.map(s=>({s,m:sigMatch(s)}))`);
rep(`  all.forEach(G=>{const a=acc[G.id];if(!a){G.pv=0;G.pc=0;G.pfrom=[];return}let s=0,w=0;a.forEach(([v,k])=>{s+=v*k;w+=k});G.pv=w?+(s/w).toFixed(2):0;G.pc=+Math.min(.45,w/(1+w)).toFixed(2);G.pfrom=a.sort((x,y)=>y[1]-x[1]).slice(0,4).map(x=>x[2])});`,
`  const agg=()=>{all.forEach(G=>{const a=acc[G.id];if(!a){G.pv=0;G.pc=0;G.pfrom=[];return}let s=0,w=0;a.forEach(([v,k])=>{s+=v*k;w+=k});G.pv=w?+(s/w).toFixed(2):0;G.pc=+Math.min(.45,w/(1+w)).toFixed(2);G.pfrom=[...new Set(a.sort((x,y)=>y[1]-x[1]).map(x=>x[2]))].slice(0,4)})};
  agg();
  // второй проход: предположенные гены тянут соседей по корреляциям с половинным весом (не более одного шага от предположения)
  if(typeof CORR!=="undefined"){const snap=all.filter(G=>!G.c&&G.pc>=.1&&Math.abs(G.pv)>=.2).map(G=>({id:G.id,pv:G.pv,pc:G.pc,name:G.name}));
    snap.forEach(S=>{const L=CORR[S.id];if(!L)return;for(const [dst,w] of L){const D=byId[dst];if(!D||D.c||(acc[dst]&&acc[dst].length))continue;push(dst,Math.max(-1,Math.min(1,w*S.pv)),Math.abs(w)*S.pc*.5,"через "+S.name.toLowerCase()+" (предп.)")}});agg()}
  // индекс ума: среднее по снятым/предположенным генам мышления → мягкий ориентир для остальных генов мышления, памяти и внимания
  {const IQ=[["cog.depth",1],["cog.systemic",1],["cog.metacog",1],["cog.recheck",.7],["cog.evidence_need",.6],["cog.premature",-1],["mem.detail_cause",.6],["att.goal_hold",.5]];let s=0,w=0;IQ.forEach(([id,k])=>{const G=byId[id];if(!G)return;const v=G.c?G.v:(G.pc?G.pv:null);if(v===null)return;const cc=G.c||G.pc*.6;s+=v*Math.sign(k)*cc*Math.abs(k);w+=cc*Math.abs(k)});
    if(w){const iq=s/w;DNA.iq=+iq.toFixed(2);[["cog.assumption",-.5],["cog.hold_contra",.6],["cog.flex",.4],["cog.associative",.3],["mem.link_similar",.6],["mem.reinterpret",.5],["mem.consolidate",.4],["att.breadth",.4],["att.return",.5],["dev.reframe_prob",.6],["self.admit_error",.4],["perc.contradict",.5],["perc.absence",.4]].forEach(([id,k])=>{const G=byId[id];if(!G||G.c||(acc[id]&&acc[id].length))return;push(id,Math.max(-1,Math.min(1,iq*k)),.2*Math.min(1,w),"индекс ума "+(iq>0?"+":"")+iq.toFixed(2))});agg()}}`);
fs.writeFileSync("gs.html",t);console.log("priors ok");
