// Слой половых норм: сдвиг нуля по мета-анализам (0.2·d), показывается в панели гена; гены и захват не меняются
const fs=require("fs");
let t=fs.readFileSync("gs.html","utf8");
function rep(a,b){if(!t.includes(a)){console.error("NOT FOUND:",a.slice(0,80));process.exit(1)}t=t.replace(a,b)}
// [ген]: [сдвиг для мужчин, d, источник, надёжность: 1 — снято с текста, 0 — по памяти]
const NORM={
 "des.libido":[.14,"+0.69","Frankenbach et al. 2022; Lippa 2009",1],
 "des.exclusivity":[-.12,"+0.74 (социосексуальность)","Lippa 2009",1],
 "des.love_vs_desire":[-.08,"+0.74 (социосексуальность)","Lippa 2009",1],
 "des.initiative":[.08,"+0.74 (социосексуальность)","Lippa 2009",1],
 "def.attack":[.11,"+0.55…0.60 (физическая агрессия)","Archer 2004",1],
 "will.aggr_control":[-.08,"+0.55 (физическая агрессия)","Archer 2004",1],
 "dark.manipulate":[-.02,"−0.01…−0.19 (косвенная агрессия)","Archer 2004",1],
 "soc.caring":[-.09,"−0.45 (сострадание)","Weisberg, DeYoung, Hirsh 2011",1],
 "perc.emotion":[-.10,"−0.45; «люди ↔ вещи» +0.93","Weisberg 2011; Su et al. 2009",1],
 "mor.wellbeing":[-.07,"−0.45 (сострадание)","Weisberg 2011",1],
 "soc.diplomacy":[-.07,"−0.36 (вежливость)","Weisberg 2011",1],
 "sp.rudeness":[.07,"−0.36 (вежливость)","Weisberg 2011",1],
 "dyn.fear.threshold":[.08,"−0.40 (нейротизм: Withdrawal)","Weisberg 2011",1],
 "dyn.fear.peak":[-.08,"−0.40 (Withdrawal)","Weisberg 2011",1],
 "dyn.sadness.threshold":[.06,"−0.40 (Withdrawal)","Weisberg 2011",1],
 "mod.arousal.gain":[-.06,"−0.30 (Volatility)","Weisberg 2011",1],
 "soc.sociable":[-.05,"−0.23 (Enthusiasm)","Weisberg 2011",1],
 "soc.dominance":[.03,"+0.09 (Assertiveness; старые данные до +0.5)","Weisberg 2011; Feingold 1994",1],
 "mot.order":[-.04,"−0.18 (Orderliness)","Weisberg 2011",1],
 "cog.systemic":[.05,"+0.22 (Intellect)","Weisberg 2011",1],
 "sp.imagery":[-.05,"−0.27 (Openness)","Weisberg 2011",1],
 "att.rumination":[-.05,"−0.24 (59 исследований, N=14 321)","Johnson & Whisman 2013",1],
 "dyn.shame.threshold":[.06,"−0.29 стыд, −0.27 вина","Else-Quest et al. 2012",0],
 "dyn.shame.peak":[-.06,"−0.29 стыд","Else-Quest 2012",0],
 "mor.strict_self":[-.05,"−0.27 вина","Else-Quest 2012",0],
 "emo.joy.hide":[.06,"−0.28 (позитив у подростков); улыбка ≈ −0.4","Chaplin & Aldao 2013; LaFrance 2003",1],
 "emo.sadness.hide":[.04,"−0.10 (интернализирующие)","Chaplin & Aldao 2013",1],
 "emo.fear.hide":[.04,"−0.10 (интернализирующие)","Chaplin & Aldao 2013",1],
 "emo.anger.hide":[-.02,"+0.09 (экстернализирующие)","Chaplin & Aldao 2013",1],
 "bond.confirm_need":[-.04,"−0.10…−0.20 (тревожная привязанность)","Del Giudice 2011/2019",1],
 "bond.reject_fear":[-.04,"−0.10…−0.20 (тревожная привязанность)","Del Giudice 2011/2019",1],
 "mot.autonomy":[.08,"+0.30…0.50 (самодостаточность), +0.52 (дистанцирование, AAI)","Del Giudice 2019",1],
 "will.ask_help":[-.08,"+0.30…0.50 (самодостаточность)","Del Giudice 2019",1],
 "soc.self_disclose":[-.04,"−0.18","Dindia & Allen 1992",0],
 "self.worth":[.04,"+0.15…0.21 (цитирования расходятся)","Kling et al. 1999",0],
 "dark.narcissism":[.05,"+0.26 (k=355, N=470 846; entitlement +0.29)","Grijalva et al. 2015",1],
 "dark.superiority":[.04,"+0.26 (grandiose/exhibitionism всего +0.04)","Grijalva 2015",1],
 "dark.authoritarian":[.04,"+0.20 (leadership/authority, k=40)","Grijalva 2015",1],
 "dark.callous":[.10,"≈ +0.5…0.6 (психопатия)","Muris et al. 2017",0],
 "dark.deceit":[.06,"≈ +0.3 (макиавеллизм)","Muris 2017",0],
 "dark.exploit":[.06,"≈ +0.3 (макиавеллизм)","Muris 2017",0],
 "dyn.disgust.threshold":[.10,"≈ −0.5…0.6 (чувствительность к отвращению)","Tybur et al. 2011",0],
 "mot.compete":[.08,"≈ +0.3…0.5","Niederle & Vesterlund 2007",0],
 "mot.avoid_error":[-.03,"+0.13 (риск)","Byrnes et al. 1999",0],
 "will.impulsive":[.03,"+0.13 (риск)","Byrnes 1999",0]
};
rep(`const SRC={w:"вики"`,`// Половые нормы: сдвиг нуля = 0.2·d (мужчины; женщины — с обратным знаком). Только чтение и генерация с нуля; захват норму не применяет
const NORM=${JSON.stringify(NORM)};
function normLine(G){const n=NORM[G.id];if(!n)return "";const [dm,d,src,ok]=n;const sex=male()?"мужчин":"женщин";const my=male()?dm:-dm;const rel=G.c?(G.v-my):null;
  return \`<div class="normline"><b>норма пола:</b> мужчины \${dm>0?"+":"−"}\${Math.abs(dm).toFixed(2)} · женщины \${dm>0?"−":"+"}\${Math.abs(dm).toFixed(2)} <span>d = \${d} · \${src}\${ok?"":" · по памяти, проверить"}</span>\${rel!==null?\`<i>для \${sex} это \${Math.abs(rel)<.15?"как у всех":rel>0?"выше нормы своего пола":"ниже нормы своего пола"} (\${rel>0?"+":""}\${rel.toFixed(2)})</i>\`:""}</div>\`}
const SRC={w:"вики"`);
rep(`<div class="lv"><b class="\${G.c===0?'unc':''}">`,`\${normLine(G)}
  <div class="lv"><b class="\${G.c===0?'unc':''}">`);
rep(`.gdesc{`,`.normline{font:10.5px var(--fm);color:var(--muted);margin:10px 0 0;line-height:1.6}.normline b{color:var(--text);font-weight:500}.normline span{color:var(--dim)}.normline i{display:block;font-style:normal;color:var(--gold)}
.gdesc{`);
fs.writeFileSync("gs.html",t);console.log("norms ok",Object.keys(NORM).length);
