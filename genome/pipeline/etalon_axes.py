# -*- coding: utf-8 -*-
"""
etalon_axes.py — полный геном эталона из 14 осей личности.

Зачем: эталон архетипа должен иметь ВСЕ гены, а не 12 ядерных + дорисовку.
Руками 348 генов × 20 образов — 7000 чисел и неизбежный разнобой. Поэтому:
  образ = 14 чисел по осям (как в факторных моделях личности: Big Five/HEXACO + аффект + стиль)
  ген   = взвешенная сумма осей (таблица LOAD ниже, знак по смыслу полюсов гена)
  ядро образа (12–13 генов) перекрывает расчёт — это то, что тип делает узнаваемым.

---- учебный блок: оси ----
W тепло/забота       D напор/доминантность   A энергия/возбуждение   V оптимизм/фон настроения
X общительность      O открытость/воображение C собранность/порядок   N ранимость/тревожность
H честность-смирение (минус = тёмная сторона)  I импульсивность       R маска/сдержанность выражения
S чувственность/романтика   K глубина ума/рассудочность   P игривость/юмор
"""
AXES = "WDAVXOCNHIRSKP"

# ген: оси с весами. Строка «perc.emotion W.5 N.3 K.2» = 0.5·W + 0.3·N + 0.2·K
LOAD_TXT = """
perc.emotion W.5 N.3 K.2|perc.words K.4 C.2|perc.tone N.3 W.3|perc.face_body W.3 N.2 X.2|perc.status D.5 H-.3
perc.contradict K.5 R.2 P.2|perc.threat N.6 V-.3|perc.opportunity D.3 H-.3 O.3|perc.novelty O.6 A.3|perc.detail C.5 K.3
perc.absence N.5 S.2 W.2|perc.hidden_motive K.4 H-.4 N.2 V-.2
cog.depth K.8 I-.3|cog.uncertainty O.4 N-.5|cog.evidence_need K.5 C.2|cog.assumption I.3 O.3 K-.3|cog.recheck C.6 N.3 I-.3
cog.logic_intuit K-.5 O.3 S.2|cog.associative O.6 P.3 C-.2|cog.systemic K.6 C.2|cog.hold_contra K.4 O.3 N-.3|cog.flex O.5 K.2 C-.2
cog.premature I.5 K-.4|cog.metacog K.6 R.1
att.goal_hold C.7 I-.3|att.switch I.4 A.3 C-.3|att.breadth X.2 A.3 K.2|att.return C.5 W.1|att.novelty_pri O.4 I.4 C-.3
att.emotion_pri N.5 I.3 R-.3|att.unfinished C.5 N.3|att.rumination N.7 K.2 V-.3
mem.sig_self N.5 W.1|mem.sig_praise N.3 X.2 D.1|mem.sig_critic N.7 V-.2|mem.sig_promise H.5 C.4|mem.sig_conflict N.4 H-.2
mem.sig_closeness W.5 S.3|mem.sig_reject N.7|mem.sig_joint W.5 X.3|mem.detail_words K.4 C.3|mem.detail_cause K.6
mem.link_similar K.4 N.2|mem.consolidate N.3 I.3 K-.2|mem.single_event N.5 I.2|mem.recall_bias V.7 N-.4|mem.recall_recent R.2 N.2 A-.3
mem.reinterpret O.5 K.3 N-.2
need.affiliation.weight X.5 W.4|need.affiliation.target X.5|need.affiliation.sens N.5 X.2
need.competence.weight C.5 K.3|need.competence.target C.4 D.3|need.competence.sens N.4 C.2
need.certainty.weight N.5 C.3 O-.3|need.certainty.target C.4 N.3|need.certainty.sens N.6
need.autonomy.weight D.5 R.2|need.autonomy.target D.4 R.2|need.autonomy.sens D.3 N.3
need.recognition.weight X.3 D.3 H-.4|need.recognition.target H-.4 X.2|need.recognition.sens N.5 H-.2
need.novelty.weight O.6 A.3|need.novelty.target O.5 A.3|need.novelty.sens O.3 A.3
need.nurturing.weight W.8|need.nurturing.target W.6|need.nurturing.sens W.5 N.2
need.order.weight C.7|need.order.target C.6|need.order.sens C.4 N.3
need.superiority.weight D.5 H-.6|need.superiority.target D.4 H-.5|need.superiority.sens H-.4 N.3
need.intimacy.weight S.8|need.intimacy.target S.7|need.intimacy.sens S.5 N.2
mod.arousal.bias A.8|mod.arousal.gain A.3 N.5 R-.2|mod.valence.bias V.8 N-.3|mod.valence.gain N.5 R-.3 A.2
mod.dominance.bias D.7 N-.2|mod.dominance.gain D.4 I.4|mod.resolution.bias K.6 I-.4|mod.resolution.gain N.4 I.3 K-.3
mod.focus.bias C.4 N.3|mod.focus.gain N.5|mod.extero.bias X.5 R-.4 W.2|mod.extero.gain N.4 R.3
dyn.fear.threshold N-.7 D.3|dyn.fear.peak N.5 R-.3|dyn.fear.decay N-.5 V.3|dyn.fear.dwell N.6
dyn.anger.threshold I-.5 A-.3 W.2|dyn.anger.peak I.5 A.4 R-.4|dyn.anger.decay W.3 V.3 H.2|dyn.anger.dwell H-.3 N.4 V-.2
dyn.sadness.threshold N-.6 V.4|dyn.sadness.peak N.5 R-.3|dyn.sadness.decay V.5 N-.4|dyn.sadness.dwell N.6 V-.3
dyn.shame.threshold N-.5 D.3 H-.2|dyn.shame.peak N.5 H.2|dyn.shame.decay N-.4 D.3|dyn.shame.dwell N.6
dyn.joy.threshold V-.6 A-.3|dyn.joy.peak A.5 V.3 R-.4|dyn.joy.decay V-.4 N.2|dyn.joy.dwell V.5
dyn.interest.threshold O-.6 A-.2|dyn.interest.peak O.4 A.4|dyn.interest.decay O-.4 I.3|dyn.interest.dwell O.4 K.3
dyn.tender.threshold W-.6|dyn.tender.peak W.5 S.3 R-.2|dyn.tender.decay W-.4|dyn.tender.dwell W.5 S.2
dyn.envy.threshold H.5 V.3 N-.3|dyn.envy.peak N.4 H-.4|dyn.envy.decay H.3 V.3|dyn.envy.dwell N.4 H-.4
dyn.disgust.threshold O.3 C-.3 W.2|dyn.disgust.peak C.3 K.2 A.2|dyn.disgust.decay O.3|dyn.disgust.dwell C.2 N.2
dyn.surprise.threshold K.3 R.4 O-.3|dyn.surprise.peak A.5 R-.4|dyn.surprise.decay A.3|dyn.surprise.dwell O.2
dyn.desire.threshold S-.6 R.2|dyn.desire.peak S.6 A.3|dyn.desire.decay S-.4|dyn.desire.dwell S.5 N.1
emo.joy.hide R.8 X-.2|emo.tender_awe.hide R.7|emo.interest.hide R.6 K.1|emo.thrill.hide R.6 C.2|emo.tender.hide R.8 W-.1
emo.gratitude.hide R.6 D.2|emo.relief.hide R.6|emo.pride.hide R.4 H.3|emo.surprise.hide R.7|emo.anxiety.hide R.6 D.3
emo.fear.hide R.6 D.4|emo.irritation.hide R.5 C.3 W.1|emo.anger.hide R.5 C.4 H.1|emo.contempt.hide R.4 H.3 W.2|emo.disgust.hide R.5 C.3
emo.sadness.hide R.7 D.2|emo.longing.hide R.7|emo.hurt.hide R.6 D.3|emo.guilt.hide R.5 H-.3|emo.shame.hide R.5 D.3
emo.embarrass.hide R.6 D.2|emo.envy.hide R.5 C.2|emo.jealousy.hide R.5 C.2|emo.boredom.hide R.4 C.4 W.2|emo.arousal.hide R.6 C.3 S-.2
emo.desire.hide R.6 C.3 S-.2|emo.flutter.hide R.6
mot.contact X.7 W.2|mot.closeness W.5 S.3 R-.3|mot.useful W.6 C.2|mot.attention X.4 H-.4 N.2|mot.recognition H-.4 X.2 N.2
mot.autonomy D.5 R.3|mot.control D.5 C.3 N.3|mot.protect W.5 D.4|mot.learn O.5 K.5|mot.explore O.7 A.3|mot.order C.8
mot.novelty O.6 A.3 C-.3|mot.entertain P.7 X.4|mot.compete D.5 H-.3 A.3|mot.superior D.4 H-.6|mot.create O.7
mot.avoid_error C.6 N.4 I-.2|mot.keep_relation W.6 N.2
bond.liking_speed X.4 W.4 R-.3|bond.trust_speed W.3 K-.2 N-.2 R-.4 H.2|bond.depth W.5 S.3 N.2|bond.reciprocity N.4 H-.2
bond.distance_sens N.6 W.3|bond.ignore_sens N.7|bond.replace_fear N.6|bond.reject_fear N.8 D-.3|bond.idealize S.3 N.3 K-.3
bond.devalue H-.4 N.3 W-.3|bond.possess N.4 D.3 H-.3 S.2|bond.confirm_need N.6 R-.2|bond.separation N.6 W.3 R-.2|bond.forgive W.6 H.3 N-.2
soc.initiative X.7 D.3 N-.2|soc.sociable X.8|soc.dominance D.9|soc.compliance D-.6 W.3|soc.directness D.4 R-.3 H.3 I.2
soc.diplomacy W.4 C.3 I-.3|soc.formality C.5 R.4 P-.3 X-.2|soc.playful P.8 A.2|soc.caring W.8|soc.mirror W.3 R.2 H-.2 D-.3
soc.please_need N.4 D-.4 W.2|soc.boundaries W.4 C.3 H.3|soc.self_disclose R-.7 X.3|soc.hide_intent R.5 H-.5|soc.questions O.4 W.3 K.2
soc.silence_ok R.4 X-.4 N-.3
mor.wellbeing W.7 H.4|mor.justice H.5 W.3 D.2|mor.freedom O.5 D.3 C-.3|mor.loyalty W.4 H.4 C.2|mor.honesty H.9|mor.law C.6 O-.3 H.2
mor.result D.4 H-.3 K.2|mor.promise H.6 C.4|mor.break_for_own W.4 H-.3 S.2|mor.small_harm H-.5 K.3 D.2|mor.own_fault H.5 N.2 K.2
mor.strict_self C.5 N.4|mor.strict_others C.4 D.4 W-.3|mor.revisable O.5 K.3
dark.egocentric H-.7 W-.4|dark.narcissism H-.6 X.2 N.2|dark.superiority H-.6 D.3|dark.instrumental H-.7 W-.4|dark.exploit H-.7 K.2
dark.deceit H-.9|dark.manipulate H-.8 K.2|dark.provoke P.3 H-.5 A.2|dark.envy H-.5 N.4|dark.vengeful H-.5 N.3 W-.3
dark.grudge H-.3 N.4 W-.3|dark.authoritarian D.6 H-.4 W-.2|dark.humiliate H-.6 W-.5|dark.callous W-.7 H-.4|dark.sadism H-.6 W-.6
dark.chaos H-.4 C-.4 I.3|dark.awareness K.5|dark.guilt_after W.4 H.4 N.3|dark.target_scope H-.5 N.2|dark.stop_ability C.5 I-.4 H.2
def.denial R.4 N.3 K-.3|def.rationalize K.3 H-.3 N.2|def.project N.4 H-.3 K-.3|def.devalue H-.3 R.3 N.2|def.idealize N.3 S.3 K-.3
def.humor P.8|def.sarcasm P.3 H-.3 R.3 W-.3|def.withdraw R.5 X-.5 N.3|def.attack D.4 I.5 N.3 W-.2|def.control D.4 C.4 N.4
def.please D-.5 N.4 W.3|def.self_abase N.6 D-.5|def.blame_shift H-.6 D.3|def.numb R.6 N-.2 W-.3
self.worth N-.6 D.4 V.3|self.ext_depend N.5 D-.3|self.critic_res N-.7 D.3|self.special_need H-.4 O.3 X.2|self.admit_error H.5 N-.2 K.2
self.compare N.5 H-.3|self.humiliation N.6 D.2|self.self_critic N.5 C.4|self.competence D.4 N-.4 C.3|self.face_keep R.4 D.3 H-.2
self.integrity H.5 R-.3 C.2|self.ideal_gap N.6 O.2
will.impulsive I.9|will.patience C.4 I-.5 W.2|will.persist C.6 D.3|will.discipline C.9|will.delay_reward C.5 I-.5|will.stop C.5 I-.4
will.frustration N-.6 C.3|will.recover V.5 N-.5|will.against_emo C.5 D.3 N-.2|will.avoid_hard D.4 N-.4 C.3|will.aggr_control C.5 I-.5 W.2
will.ask_help W.3 R-.4 D-.3 N.2
ag.init_unasked X.4 D.3 W.2|ag.suggest_freq X.4 D.3 P.2|ag.own_goals D.5 O.3|ag.horizon C.5 K.4 I-.3|ag.curiosity O.8
ag.finish_need C.7|ag.decide D.7 N-.3|ag.ask_permission D-.5 W.3 C.2|ag.caution_ext C.4 N.4 I-.4|ag.interrupt_ok N-.5 W.2
ag.replan O.5 N-.3|ag.respect_no W.5 H.4 D-.2|ag.remind C.5 W.3|ag.explain_self K.5 W.3 R-.2
sp.verbosity X.5 R-.4 A.2|sp.emotional A.5 R-.6|sp.formality C.5 R.3 P-.3|sp.directness D.4 R-.3 I.3 H.2|sp.imagery O.6 S.2
sp.humor P.8|sp.sarcasm P.3 H-.4 W-.3 K.2|sp.rudeness W-.5 C-.3 I.3|sp.tenderness W.7 S.2|sp.drama A.4 X.3 R-.4
sp.pace A.7 I.3|sp.name_use W.4 X.3|sp.self_talk X.4 H-.2 R-.3|sp.feelings_talk R-.7 W.2|sp.tease P.6 S.2 D.2|sp.voice_stability N-.7 C.2
ct.conflict_tol K.3 N-.3 O.2|ct.mask_split R.5 H-.3|ct.value_act_gap H-.6|ct.feel_speech_gap R.7|ct.self_deceive K-.4 H-.3 N.2
ct.motive_aware K.6|ct.suppress_want R.6 C.3|ct.regret N.6 C.2
dev.plasticity O.5 N.2 C-.2|dev.early_weight N.4 O-.2|dev.repeat_sens N.3 O.2|dev.shock_sens N.6|dev.authority_inf D-.5 C.3
dev.close_inf W.5 D-.3|dev.identity_res D.4 C.3 N-.3|dev.habit_form C.4|dev.habit_break I.4 C-.4|dev.reframe_prob O.5 K.3
dev.regress N.6|dev.trauma_recover N-.5 V.5
des.romantic_drive S.7 W.3|des.libido S.8 A.2|des.flirt S.5 P.4 X.3 R-.3|des.initiative S.4 D.4 X.2|des.touch_open S.5 W.3 R-.4
des.talk_ease S.3 R-.5 N-.3 D.2|des.naivety K-.5 S-.4 H.2|des.love_vs_desire W.4 S.2 H.2|des.idealize_partner S.3 N.3 K-.3
des.consent_care W.6 H.4|des.exclusivity N.4 S.3 W.2|des.tease_erotic S.6 P.4|des.quirk O.3 S.3|des.shame_link N.5 C.3 S-.2
des.arousal_override S.4 I.5 C-.3|des.taboo_effect O.3 S.3 H-.2|des.yield_pressure D-.6 N.3
"""
def _parse():
    L = {}
    for chunk in LOAD_TXT.replace("\n", "|").split("|"):
        p = chunk.split()
        if not p: continue
        L[p[0]] = [(t[0], float(t[1:])) for t in p[1:]]
    return L
LOAD = _parse()

def full_genome(axes, scale=0.95):
    """axes: {'W':.7,...} → {ген: значение} для всех генов из LOAD (неназванные оси = 0)."""
    out = {}
    for g, ws in LOAD.items():
        v = sum(w * axes.get(a, 0.0) for a, w in ws) * scale
        out[g] = round(max(-1.0, min(1.0, v)), 2)
    return out
