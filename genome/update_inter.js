// update_inter.js — блок «Социальная механика» (13 генов) в геном: шаблон студии, описания, дорисовка, genes.json, оси эталонов.
// ---- учебный блок: почему отдельный блок ----
// Прежние блоки описывали, ЧТО человек чувствует и ценит. Но «нет» и «простите, часов при себе нет» могут сказать
// два человека с одинаковыми чувствами — разница в том, как устроен сам разговор: бережёт ли он лицо собеседника,
// следует ли ритуалам, возвращает ли открытость, чинит ли неловкость. Это проверенные теории общения, у каждого гена
// в описании — откуда он. Ноль = обычный воспитанный человек своей среды.
const fs = require("fs"), path = require("path");
const ROOT = __dirname, P = path.join(ROOT, "genome-studio.html");
const B = JSON.parse(fs.readFileSync(path.join(ROOT, "pipeline", "inter_block.json"), "utf8"));
let h = fs.readFileSync(P, "utf8");
// 1) блок в шаблон — перед «Природой существа»
if (h.includes('{"id":"inter","name"')) console.log("блок уже в шаблоне");
else {
  const genes = B.genes.map(g => JSON.stringify([g.id, g.name, 0, 0, g.ch, [], g.neg, g.pos])).join(",");
  const rec = '{"id":"inter","name":' + JSON.stringify(B.name) + ',"purpose":' + JSON.stringify(B.purpose) + ',"compiles":' + JSON.stringify(B.compiles) +
    ',"interacts":' + JSON.stringify(B.interacts) + ',"extremes":' + JSON.stringify(B.extremes) + ',"genes":[' + genes + ']},';
  const A = '{"id":"beast","name":"Природа существа"';
  if (!h.includes(A)) throw "нет якоря beast";
  h = h.replace(A, rec + A);
}
// 2) описания генов — в объект DESC (разбор литерала скобками, затем JSON)
function patchObj(name, fn) {
  const k = h.indexOf("const " + name + "={"); const st = k < 0 ? h.indexOf(name + "={") : k; if (st < 0) throw "нет " + name;
  const o = h.indexOf("{", st); let d = 0, i = o, inStr = false, esc = false;
  for (; i < h.length; i++) { const c = h[i]; if (inStr) { if (esc) esc = false; else if (c === "\\") esc = true; else if (c === '"') inStr = false; continue }
    if (c === '"') inStr = true; else if (c === "{") d++; else if (c === "}") { d--; if (d === 0) break } }
  const obj = JSON.parse(h.slice(o, i + 1)); fn(obj); h = h.slice(0, o) + JSON.stringify(obj) + h.slice(i + 1);
}
patchObj("DESC", o => { for (const g of B.genes) o[g.id] = g.desc });
// 3) дорисовка: новые гены предсказываются из старых, пока их не сняли по корпусу
const PRIOR = {
  "inter.face_other": [["soc.diplomacy", .6], ["mor.wellbeing", .4], ["sp.rudeness", -.5], ["dark.callous", -.4], ["perc.emotion", .3]],
  "inter.preferred": [["soc.compliance", .5], ["soc.please_need", .4], ["mot.autonomy", -.4], ["soc.directness", -.2]],
  "inter.convention": [["soc.formality", .6], ["sp.formality", .5], ["mor.law", .3], ["will.discipline", .3]],
  "inter.power_dist": [["perc.status", .6], ["soc.formality", .4], ["dark.authoritarian", .3]],
  "inter.reciprocity": [["bond.reciprocity", .5], ["mor.justice", .3], ["dark.vengeful", .3]],
  "inter.warmth_match": [["soc.mirror", .5], ["soc.caring", .3], ["bond.liking_speed", .3]],
  "inter.dominance_resp": [["soc.dominance", .6], ["def.attack", .4], ["soc.compliance", -.4]],
  "inter.repair": [["mor.own_fault", .6], ["self.admit_error", .5], ["def.blame_shift", -.5], ["def.denial", -.4]],
  "inter.cooperative": [["soc.hide_intent", -.5], ["sp.directness", .3], ["dark.deceit", -.4], ["ag.explain_self", .3]],
  "inter.contagion": [["perc.emotion", .5], ["soc.mirror", .4], ["mod.extero.bias", .3]],
  "inter.expect_viol": [["soc.formality", .4], ["need.certainty.weight", .4], ["perc.threat", .3], ["cog.uncertainty", -.3]],
  "inter.disclosure_pace": [["soc.self_disclose", .7], ["bond.trust_speed", .4]],
  "inter.tact": [["perc.emotion", .5], ["soc.diplomacy", .4], ["cog.metacog", .3], ["perc.status", .2]],
};
patchObj("CORR", o => { for (const [t, src] of Object.entries(PRIOR)) for (const [s, w] of src) { (o[s] || (o[s] = [])); if (!o[s].some(e => e[0] === t)) o[s].push([t, w]) } });
fs.writeFileSync(P, h);
// 4) pipeline/genes.json и correlations.json — для конвейера (persona.py, следователь, эталоны)
const GJ = path.join(ROOT, "pipeline", "genes.json"); const G = JSON.parse(fs.readFileSync(GJ, "utf8"));
if (!G.some(b => b.block === "inter")) { const k = G.findIndex(b => b.block === "beast");
  G.splice(k < 0 ? G.length : k, 0, { block: "inter", name: B.name, genes: B.genes.map(g => ({ id: g.id, name: g.name, desc: g.desc, ch: g.ch, neg: g.neg, pos: g.pos })) });
  fs.writeFileSync(GJ, JSON.stringify(G, null, 1)) }
const CJ = path.join(ROOT, "pipeline", "correlations.json"); const C = JSON.parse(fs.readFileSync(CJ, "utf8"));
for (const [t, src] of Object.entries(PRIOR)) for (const [s, w] of src) { C[s] = C[s] || []; if (!C[s].some(e => e[0] === t)) C[s].push([t, w]) }
fs.writeFileSync(CJ, JSON.stringify(C, null, 1));
fs.writeFileSync(path.join(ROOT, "ver.js"), 'window.__BUILD="' + new Date().toISOString() + '-inter";');
console.log("ok: блок «" + B.name + "» · генов " + B.genes.length + " · всего в genes.json " + G.reduce((a, b) => a + b.genes.length, 0));
