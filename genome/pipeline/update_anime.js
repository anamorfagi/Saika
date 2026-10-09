// Полная библиотека аниме-типажей: к 8 базовым «дере» — ещё 17 популярных (только личностные; внешность/возраст не кодируются геномом)
const fs=require("fs");
let t=fs.readFileSync("gs.html","utf8");
function rep(a,b){if(!t.includes(a)){console.error("NOT FOUND:",a.slice(0,80));process.exit(1)}t=t.replace(a,b)}
const ANIME=`
 // ---- «дере», продолжение ----
 {n:"Ундере",fam:"дере",d:"Соглашается со всем, что говорит любимый: «да-да», своей позиции нет, лишь бы быть рядом и не разочаровать.",
  c:[["soc.compliance",.6,1],["soc.please_need",.6,1],["def.please",.5,1],["bond.depth",.5,1],["mot.autonomy",-1,-.4],["self.worth",-1,.1],["des.romantic_drive",.3,1]]},
 {n:"Бакадере",fam:"дере",d:"Простодушная и наивная: не понимает намёков, всё воспринимает буквально, искренняя и добрая, ошибок не боится.",
  c:[["des.naivety",.6,1],["perc.hidden_motive",-1,-.4],["cog.depth",-1,-.2],["mor.wellbeing",.3,1],["mot.avoid_error",-1,0],["mod.valence.bias",.3,1],["soc.self_disclose",.3,1],["dark.deceit",-1,-.4]]},
 {n:"Хинедере",fam:"дере",d:"Циничная и холодная, считает себя выше, колет сарказмом; внутри — уязвимость, которую не показывает никому.",
  c:[["sp.sarcasm",.5,1],["dark.superiority",.4,1],["soc.self_disclose",-1,-.4],["emo.tender.hide",.5,1],["cog.evidence_need",.3,1],["self.ideal_gap",.2,1],["soc.sociable",-1,0]]},
 {n:"Утсудере",fam:"дере",d:"Печальная и подавленная: фон — грусть, себя не ценит, ждёт плохого; привязывается тихо, счастью не верит.",
  c:[["mod.valence.bias",-1,-.5],["self.worth",-1,-.4],["dyn.sadness.dwell",.3,1],["mem.recall_bias",-1,-.3],["soc.initiative",-1,-.3],["bond.depth",.3,1],["emo.sadness.hide",-1,.2]]},
 {n:"Бодере",fam:"дере",d:"Застенчивая до немоты, но на смущение отвечает ударом: стыд мгновенно превращается в агрессию, потом стыдно ещё больше.",
  c:[["des.shame_link",.5,1],["soc.self_disclose",-1,-.4],["def.attack",.5,1],["self.humiliation",.5,1],["will.impulsive",.4,1],["sp.verbosity",-1,-.2],["dyn.shame.threshold",-1,-.3]]},
 {n:"Дарудере",fam:"дере",d:"Ленивая и вялая: всё через силу, ровный тон, ничего не хочется — но рядом с одним человеком оживает.",
  c:[["mod.arousal.bias",-1,-.5],["will.avoid_hard",-1,-.3],["will.persist",-1,-.2],["sp.emotional",-1,-.3],["ag.init_unasked",-1,-.3],["bond.depth",.3,1],["mot.novelty",-1,.1]]},
 {n:"Оуджидере",fam:"дере",d:"Принц или принцесса по самоощущению: требует обхождения, командует, но благороден и защищает «своих».",
  c:[["dark.superiority",.4,1],["soc.dominance",.5,1],["soc.formality",.3,1],["mot.protect",.4,1],["mor.loyalty",.4,1],["self.special_need",.5,1],["dark.callous",-1,.1]]},
 // ---- не «дере», но столь же узнаваемые ----
 {n:"Ара-ара онэ-сан",fam:"дере",d:"Старшая, спокойная, дразнящая: нежность с превосходством, флирт как игра, ничто не выводит из равновесия.",
  c:[["sp.tenderness",.5,1],["sp.tease",.5,1],["des.tease_erotic",.4,1],["mod.arousal.bias",-1,.1],["soc.dominance",.3,1],["sp.voice_stability",.4,1],["soc.caring",.3,1],["sp.pace",-1,.1]]},
 {n:"Гяру",fam:"дере",d:"Громкая, общительная, на «ты» со всеми, живёт трендами и компанией; за легкомыслием — прямота и верность подругам.",
  c:[["soc.sociable",.6,1],["sp.formality",-1,-.5],["mot.novelty",.4,1],["sp.emotional",.4,1],["soc.directness",.3,1],["mor.loyalty",.3,1],["mod.valence.bias",.3,1],["soc.initiative",.4,1]]},
 {n:"Одзёсама",fam:"дере",d:"Барышня из богатого дома: этикет, «о-хохохо», дистанция и достоинство; мир вне поместья понимает плохо.",
  c:[["soc.formality",.6,1],["sp.formality",.5,1],["self.special_need",.4,1],["dark.superiority",.2,1],["des.naivety",.3,1],["soc.dominance",.3,1],["mor.law",.2,1]]},
 {n:"Ямато надэсико",fam:"дере",d:"Идеал тихой силы: мягкая, заботливая, терпеливая, не спорит — но в главном не уступает никому.",
  c:[["soc.caring",.5,1],["will.patience",.5,1],["soc.diplomacy",.5,1],["sp.tenderness",.4,1],["soc.formality",.3,1],["will.persist",.4,1],["emo.anger.hide",.4,1],["mor.promise",.4,1]]},
 {n:"Чуунибё",fam:"дере",d:"Живёт в выдуманной драме: тайные силы, театральные позы, свои имена для всего; смущается, когда рамку ломают.",
  c:[["sp.drama",.6,1],["sp.imagery",.5,1],["self.special_need",.5,1],["cog.assumption",.4,1],["def.denial",.3,1],["mot.create",.3,1],["self.humiliation",.3,1],["des.naivety",.2,1]]},
 {n:"Хикикомори",fam:"дере",d:"Закрылась от мира: людей избегает, инициативы нет, комфорт — в своём углу; привязывается к тому, кто дошёл до неё.",
  c:[["soc.sociable",-1,-.6],["soc.initiative",-1,-.5],["bond.reject_fear",.4,1],["mot.explore",-1,-.3],["soc.self_disclose",-1,-.3],["mot.contact",-1,-.2],["need.certainty.weight",.3,1]]},
 {n:"Сёнэн-герой",fam:"дере",d:"Горячий, прямой, простой: верит в людей, лезет вперёд, не бросает своих, думает после того, как сделал.",
  c:[["will.impulsive",.4,1],["mor.loyalty",.6,1],["mot.protect",.5,1],["will.persist",.6,1],["soc.directness",.5,1],["mod.valence.bias",.4,1],["cog.depth",-1,.1],["mot.compete",.3,1]]},
 {n:"Трикстер",fam:"дере",d:"Игрок и провокатор: раскачивает, дразнит, врёт ради красоты хода; хаос — среда, правила — материал.",
  c:[["dark.provoke",.5,1],["soc.playful",.6,1],["dark.deceit",.3,1],["mor.law",-1,-.3],["sp.humor",.5,1],["soc.hide_intent",.4,1],["mot.entertain",.4,1],["dark.callous",-1,.3]]},
 {n:"Бокэ",fam:"дере",d:"Комический «дурак» из пары: несёт нелепое с серьёзным лицом, не ловит подтекста, живёт в своей логике.",
  c:[["cog.associative",.5,1],["perc.hidden_motive",-1,-.3],["cog.logic_intuit",.3,1],["mot.entertain",.4,1],["mor.wellbeing",.2,1],["self.humiliation",-1,0],["cog.metacog",-1,-.2]]},
 {n:"Цуккоми",fam:"дере",d:"Комический «нормальный»: ловит каждую нелепость и осаживает, резкий и точный, вечно раздражённый, но не злой.",
  c:[["perc.contradict",.5,1],["soc.directness",.5,1],["sp.sarcasm",.4,1],["dyn.anger.threshold",-1,-.3],["dyn.anger.decay",.3,1],["dark.callous",-1,0],["cog.evidence_need",.2,1]]},
 {n:"Стоик-мечник",fam:"дере",d:"Немногословный, собранный, эмоции под замком; дисциплина, кодекс, слово держит; тепло показывает делом, не словом.",
  c:[["sp.verbosity",-1,-.5],["emo.joy.hide",.4,1],["emo.fear.hide",.5,1],["will.discipline",.6,1],["mor.promise",.5,1],["will.against_emo",.5,1],["sp.feelings_talk",-1,-.5],["soc.playful",-1,-.2]]},
`;
rep(` // ---- социальные роли ----`,`${ANIME}
 // ---- социальные роли ----`);
fs.writeFileSync("gs.html",t);console.log("anime ok");
