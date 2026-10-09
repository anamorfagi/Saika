// update_facets2.js — грани черт (легенда под кубиками):
//  · имена склоняются по полу персонажа (для мужского — «дружелюбный», раньше легенда всегда была в женском роде);
//  · +14 граней, чтобы каждый ген блоков мышления/внимания/памяти/динамики/морали/развития имел свою грань (было 172 гена без грани);
//  · новая группа «ум»; · предполагаемая нить: гены одной грани тянут друг друга (снят один — соседи по грани получают предположение).
// Запуск: node update_facets2.js (после update_strip, до update_priors). Правит gs.html.
const fs=require("fs");let t=fs.readFileSync("gs.html","utf8");
function rep(a,b){if(!t.includes(a)){console.error("не найдено:",a.slice(0,80));process.exit(1)}t=t.replace(a,b)}

// [1] новые грани — в конец FACETS (первая грань гена по порядку остаётся главной, новые ловят «серые» гены)
rep(`  g:[["des.shame_link",1],["des.talk_ease",-1],["des.naivety",1],["emo.embarrass.hide",-1],["emo.arousal.hide",1],["emo.desire.hide",1],["des.touch_open",-1],["des.initiative",-1],["des.flirt",-1],["emo.shame.hide",-1]]},
];`,`  g:[["des.shame_link",1],["des.talk_ease",-1],["des.naivety",1],["emo.embarrass.hide",-1],["emo.arousal.hide",1],["emo.desire.hide",1],["des.touch_open",-1],["des.initiative",-1],["des.flirt",-1],["emo.shame.hide",-1]]},
 // ум
 {id:"curious",grp:"ум",n:"любопытная",rgb:"120,200,230",t:"открытость опыту: тянется к новому, учится, создаёт, легко меняет рамку",
  g:[["mot.learn",1],["mot.create",1],["perc.novelty",1],["att.novelty_pri",1],["need.novelty.weight",1],["need.novelty.target",1],["need.novelty.sens",1],["cog.associative",1],["cog.flex",1],["dev.reframe_prob",1],["mor.revisable",1],["dyn.interest.threshold",-1],["dyn.interest.peak",1],["ag.own_goals",1],["ag.suggest_freq",1],["sp.imagery",1]]},
 {id:"pedant",grp:"ум",n:"педантичная",rgb:"150,170,200",t:"добросовестность: порядок, доводит до конца, помнит дословно, держит слово и правила",
  g:[["mot.order",1],["need.order.weight",1],["need.order.target",1],["need.order.sens",1],["att.unfinished",1],["att.goal_hold",1],["att.return",1],["mem.detail_words",1],["mem.detail_cause",1],["will.persist",1],["ag.finish_need",1],["ag.replan",-1],["mor.promise",1],["mor.law",1],["sp.formality",1],["def.control",1],["mem.sig_promise",1],["ag.remind",1]]},
 {id:"scatter",grp:"ум",n:"рассеянная",rgb:"190,180,150",t:"низкая добросовестность: теряет нить, забывает, откладывает трудное, живёт последним днём",
  g:[["att.goal_hold",-1],["att.return",-1],["att.breadth",1],["mem.consolidate",-1],["mem.detail_words",-1],["mem.recall_recent",1],["will.avoid_hard",1],["ag.finish_need",-1],["cog.assumption",1],["dev.habit_form",-1],["mem.sig_promise",-1],["ag.horizon",-1],["mod.focus.gain",-1],["mod.focus.bias",-1]]},
 {id:"gullible",grp:"ум",n:"доверчивая",rgb:"230,200,150",t:"верит на слово, не видит скрытых мотивов, легко ведётся на давление и авторитет, оправдывает",
  g:[["perc.hidden_motive",-1],["def.idealize",1],["def.denial",1],["ct.self_deceive",1],["dev.authority_inf",1],["dev.close_inf",1],["des.yield_pressure",1],["des.arousal_override",1],["def.rationalize",1],["mem.reinterpret",1],["ct.regret",-1]]},
 {id:"insight",grp:"ум",n:"проницательная",rgb:"110,190,190",t:"читает людей: эмоции, интонацию, тело, статус, скрытые мотивы; связывает случаи, видит свои тёмные черты",
  g:[["perc.emotion",1],["perc.words",1],["perc.tone",1],["perc.face_body",1],["perc.status",1],["perc.hidden_motive",1],["soc.mirror",1],["mem.link_similar",1],["mem.reinterpret",1],["dark.awareness",1],["ag.explain_self",1],["mod.extero.bias",1],["mod.extero.gain",1]]},
 {id:"plastic",grp:"ум",n:"пластичная",rgb:"170,210,170",t:"характер переписывается опытом: быстро учится на повторах и ударах, меняется под близких",
  g:[["dev.plasticity",1],["dev.repeat_sens",1],["dev.shock_sens",1],["dev.close_inf",1],["dev.habit_form",1],["dev.habit_break",1],["dev.identity_res",-1],["dev.regress",-1],["dev.early_weight",-1]]},
 {id:"rigid",grp:"ум",n:"литая",rgb:"130,130,160",t:"характер литой: держит ядро, детство определяет всё, под стрессом откатывается в старое",
  g:[["dev.plasticity",-1],["dev.identity_res",1],["dev.early_weight",1],["dev.regress",1],["dev.habit_break",-1],["dev.repeat_sens",-1],["self.integrity",1],["dev.reframe_prob",-1]]},
 // чувства — добавка
 {id:"temper",grp:"чувства",n:"вспыльчивая",rgb:"230,90,70",t:"гнев с низким порогом и сильным пиком, слабый контроль агрессии, режет прямо",
  g:[["dyn.anger.threshold",-1],["dyn.anger.peak",1],["dyn.anger.dwell",1],["will.aggr_control",-1],["soc.directness",1],["sp.directness",1],["dyn.disgust.threshold",-1],["dyn.disgust.peak",1],["mod.dominance.gain",1]]},
 {id:"gloomy",grp:"чувства",n:"унылая",rgb:"110,120,160",t:"печаль и стыд легко включаются и долго держатся, радость — редко и слабо, вспоминается плохое",
  g:[["dyn.sadness.threshold",-1],["dyn.sadness.peak",1],["dyn.sadness.dwell",1],["dyn.sadness.decay",-1],["dyn.shame.dwell",1],["dyn.shame.decay",-1],["mem.recall_bias",-1],["self.ideal_gap",1],["dyn.joy.threshold",1],["dyn.joy.peak",-1],["dyn.joy.decay",1],["mod.valence.gain",-1]]},
 {id:"fearful",grp:"чувства",n:"пугливая",rgb:"160,140,220",t:"страх и стыд от малого повода, сильные и застревающие; удивление и внешний мир бьют по нервам",
  g:[["dyn.fear.threshold",-1],["dyn.fear.peak",1],["dyn.fear.dwell",1],["dyn.fear.decay",-1],["dyn.shame.threshold",-1],["dyn.shame.peak",1],["dyn.surprise.threshold",-1],["dyn.surprise.peak",1],["dyn.surprise.dwell",1],["dyn.surprise.decay",-1],["mod.extero.gain",1],["mod.resolution.gain",-1]]},
 {id:"ambit",grp:"чувства",n:"честолюбивая",rgb:"220,170,90",t:"хочет признания и компетентности, ставит дальние цели, результат важнее процесса, зависть к чужому успеху",
  g:[["mot.recognition",1],["mot.attention",1],["need.recognition.weight",1],["need.recognition.target",1],["need.recognition.sens",1],["need.competence.weight",1],["need.competence.target",1],["need.competence.sens",1],["self.competence",1],["mor.result",1],["ag.horizon",1],["ag.own_goals",1],["dyn.envy.threshold",-1],["dyn.envy.peak",1],["need.superiority.target",1],["need.superiority.sens",1]]},
 {id:"warm",grp:"чувства",n:"отзывчивая",rgb:"240,160,120",t:"нежность и интерес к людям включаются легко; ценит верность и справедливость, помнит хорошее",
  g:[["dyn.tender.threshold",-1],["dyn.tender.peak",1],["dyn.tender.dwell",1],["dyn.tender.decay",-1],["dyn.interest.dwell",1],["dyn.interest.decay",-1],["mem.sig_joint",1],["mem.sig_praise",1],["mem.sig_self",1],["mem.sig_closeness",1],["mor.loyalty",1],["mor.justice",1],["need.affiliation.target",1],["need.nurturing.target",1],["need.nurturing.sens",1],["dyn.joy.dwell",1]]},
 // к другим — добавка
 {id:"principled",grp:"к другим",n:"принципиальная",rgb:"200,200,120",t:"живёт по правилам и слову: справедливость, верность, закон; строга к себе и другим, слово и дело не расходятся",
  g:[["mor.justice",1],["mor.law",1],["mor.loyalty",1],["mor.promise",1],["mor.strict_self",1],["mor.strict_others",1],["ct.value_act_gap",-1],["mor.result",-1],["mor.freedom",-1],["self.integrity",1],["mem.sig_conflict",1],["mem.sig_critic",1],["ag.explain_self",1]]},
 {id:"jester",grp:"к другим",n:"шутливая",rgb:"240,210,90",t:"защищается и общается юмором: шутка, сарказм, образ; любит быть в центре",
  g:[["def.humor",1],["def.sarcasm",1],["sp.imagery",1],["sp.self_talk",1],["mot.attention",1],["need.autonomy.target",-1],["mem.sig_reject",-1],["dyn.joy.threshold",-1],["dyn.joy.peak",1]]},
 // близость — добавка
 {id:"jealous",grp:"близость",n:"ревнивая",rgb:"200,90,140",t:"зависть и ревность с низким порогом и долгим застреванием, собственничество, страх замены",
  g:[["dyn.envy.threshold",-1],["dyn.envy.peak",1],["dyn.envy.dwell",1],["dyn.envy.decay",-1],["bond.possess",1],["bond.replace_fear",1],["emo.jealousy.hide",-1],["des.exclusivity",1],["mem.sig_reject",1],["need.affiliation.target",1]]},
 {id:"pliant",grp:"близость",n:"податливая",rgb:"220,130,170",t:"в близости уступает давлению, желание выключает рассудок, запрет заводит; влечение включается легко",
  g:[["des.yield_pressure",1],["des.arousal_override",1],["des.taboo_effect",1],["dyn.desire.threshold",-1],["dyn.desire.peak",1],["dyn.desire.dwell",1],["dyn.desire.decay",-1],["need.autonomy.sens",-1],["need.autonomy.target",-1],["need.certainty.weight",-1],["need.certainty.target",-1]]},
];`);
// [2] мужские формы
rep(`"стыдливая":"стыдливый"`,`"стыдливая":"стыдливый","рассудительная":"рассудительный","любопытная":"любопытный","педантичная":"педантичный","рассеянная":"рассеянный","доверчивая":"доверчивый","проницательная":"проницательный","пластичная":"пластичный","литая":"литой","вспыльчивая":"вспыльчивый","унылая":"унылый","пугливая":"пугливый","честолюбивая":"честолюбивый","отзывчивая":"отзывчивый","принципиальная":"принципиальный","шутливая":"шутливый","ревнивая":"ревнивый","податливая":"податливый"`);
// [3] легенда: четыре группы, имена по полу, строки пореже
rep(`\${["к другим","чувства","близость"].map(gr=>\`<div class="binname legend3"><em>\${gr}</em>\${FACETS.filter(f=>f.grp===gr).map(f=>\`<span title="\${f.t}"><i class="sw" style="background:rgb(\${f.rgb})"></i>\${f.n}</span>\`).join("")}</div>\`).join("")}`,
`\${["к другим","чувства","ум","близость"].map(gr=>\`<div class="binname legend3"><em>\${gr}</em>\${FACETS.filter(f=>f.grp===gr).map(f=>\`<span title="\${f.t}"><i class="sw" style="background:rgb(\${f.rgb})"></i>\${gt(f.n)}</span>\`).join("")}</div>\`).join("")}`);
rep(`.binname.legend3{display:grid;grid-template-columns:64px repeat(7,minmax(0,1fr));gap:4px 8px;align-items:center;white-space:nowrap;margin-top:4px}.binname.legend3 em{grid-column:1}.binname.legend3 span:nth-child(9){grid-column:2}`,
`.binname.legend3{display:grid;grid-template-columns:64px repeat(7,minmax(0,1fr));gap:7px 8px;align-items:center;white-space:nowrap;margin-top:7px}.binname.legend3 em{grid-column:1}.binname.legend3 span{letter-spacing:0;overflow:hidden}.binname.legend3 span:nth-child(9),.binname.legend3 span:nth-child(16){grid-column:2}`);
// [4] предполагаемая нить: соседи по грани. Снятый ген с |v|≥.2 в грани f говорит «грань активна/неактивна» → остальные гены грани получают предположение
rep(`  const top=SIGS.map(s=>({s,m:sigMatch(s)}))`,`  // грани: если ген грани снят, соседи по грани тянутся в ту же сторону (вес ниже корреляций: 0.3·c, полюс мягче: 0.6·|v|)
  all.forEach(S=>{if(!S.c||Math.abs(S.v)<.2)return;for(const [f,d] of (FMAP[S.id]||[])){const act=S.v*d;for(const [id,dx] of f.g){if(id===S.id||!byId[id])continue;push(id,Math.max(-1,Math.min(1,act*dx*.6)),.3*S.c,"грань «"+f.n+"» ← "+S.name.toLowerCase())}}});
  const top=SIGS.map(s=>({s,m:sigMatch(s)}))`);
fs.writeFileSync("gs.html",t);console.log("facets2 ok");
