// Компилятор: адаптивный порог ядра. Раньше в промпт шли только гены |x| ≥ 0.7 — у корпусов с потолком 0.6 (OCR, вики) промпт выходил пустым.
// Теперь: сначала строгий порог 0.7; если ядро меньше 6 генов — добираем по силе |x|·c при |x| ≥ 0.4, до 14. Порог показывается в статистике.
// Плюс: описание карточки (desc) идёт в «Кто она», если нет отдельных строк identity — чтобы промпт никогда не был без «кто это».
const fs=require("fs");let t=fs.readFileSync("gs.html","utf8");
function rep(a,b){if(!t.includes(a)){console.error("NOT FOUND:",a.slice(0,90));process.exit(1)}t=t.replace(a,b)}
rep(`  const core=all.filter(g=>g.c>0&&g.ch.split(",").includes("P")&&Math.abs(g.v)>=.7)
    .sort((a,b)=>Math.abs(b.v)*b.c-Math.abs(a.v)*a.c).slice(0,14);`,
`  const P=all.filter(g=>g.c>0&&g.ch.split(",").includes("P")).sort((a,b)=>Math.abs(b.v)*b.c-Math.abs(a.v)*a.c);
  let thr=.7,core=P.filter(g=>Math.abs(g.v)>=thr).slice(0,14);
  if(core.length<6){thr=.4;core=P.filter(g=>Math.abs(g.v)>=thr).slice(0,14)}   // тонкий корпус (потолок 0.6): добираем ядро по силе
  compilePrompt.thr=thr;`);
rep(`L.push(\`## Кто \${(CHAR.voice&&CHAR.voice.gender==="мужской")?"он":"она"}\`);CHAR.identity.forEach(s=>L.push(\`- \${s}\`));`,
`L.push(\`## Кто \${(CHAR.voice&&CHAR.voice.gender==="мужской")?"он":"она"}\`);(CHAR.identity&&CHAR.identity.length?CHAR.identity:(CHAR.desc?CHAR.desc.split(/(?<=[.!?])\\s+/).slice(0,4):[])).forEach(s=>L.push(\`- \${s}\`));`);
rep("ядро ${cp.core.length} генов из ${all.filter(g=>g.c>0&&g.ch.split(\",\").includes(\"P\")).length} с каналом P`;","ядро ${cp.core.length} генов из ${all.filter(g=>g.c>0&&g.ch.split(\",\").includes(\"P\")).length} с каналом P · порог |x| ≥ ${compilePrompt.thr}`;");
// гены с уровнем ниже 0.7 — формулировать мягче: «скорее …», чтобы промпт не врал о силе
rep("core.forEach(g=>L.push(`- ${g.name}: ${gt(g.v>0?g.pos:g.neg)}.`));","core.forEach(g=>L.push(`- ${g.name}: ${Math.abs(g.v)<.6?\"скорее \":\"\"}${gt(g.v>0?g.pos:g.neg)}.`));");
fs.writeFileSync("gs.html",t);console.log("comp ok");
