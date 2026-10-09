// Компилятор: недостающие разделы промпта — «Как говорит» (voice + гены речи), «Что ею движет» (мотивы), «Как реагирует» (вердикты вкладки «Поведение»
// как правила поведения), «Близость» (гены влечения — только у взрослых, не у ИИ без блока). Так промпт описывает реакции, а не прилагательные.
const fs=require("fs");let t=fs.readFileSync("gs.html","utf8");
function rep(a,b){if(!t.includes(a)){console.error("NOT FOUND:",a.slice(0,90));process.exit(1)}t=t.replace(a,b)}
rep(`  L.push(\`## Речь\`);
  CHAR.samples.forEach(s=>L.push(\`- \${s.ctx}: «\${s.t}»\`));`,
`  // близость: гены влечения — у взрослых людей и персонажей
  const des=all.filter(g=>g.c>0&&g.id.startsWith("des.")&&Math.abs(g.v)>=.4).sort((a,b)=>Math.abs(b.v)*b.c-Math.abs(a.v)*a.c).slice(0,7);
  if(des.length&&!(CHAR.kind==="ребёнок"||CHAR.child)&&!(typeof isAI==="function"&&isAI())){L.push(\`## Близость\`);des.forEach(g=>L.push(\`- \${g.name}: \${gt(g.v>0?g.pos:g.neg)}.\`))}
  // что движет: сильнейшие мотивы и веса потребностей
  const drive=all.filter(g=>g.c>0&&(g.id.startsWith("mot.")||/^need\\.[a-z]+\\.weight$/.test(g.id))&&Math.abs(g.v)>=.4).sort((a,b)=>Math.abs(b.v)*b.c-Math.abs(a.v)*a.c).slice(0,6);
  if(drive.length){L.push(\`## Что \${(CHAR.voice&&CHAR.voice.gender==="мужской")?"им":"ею"} движет\`);drive.forEach(g=>L.push(\`- \${g.name}: \${gt(g.v>0?g.pos:g.neg)}.\`))}
  // как реагирует: вердикты сцен «Поведения», где гены сняты
  if(typeof SCEN!=="undefined"&&typeof want==="function"){const adult=!(CHAR.kind==="ребёнок"||CHAR.child);const isAI_=typeof isAI==="function"&&isAI();const R=[];
    SCEN.filter(s=>!s.adult||(adult&&!isAI_)).forEach(s=>{const rows=s.acts.map(a=>({a,wv:want(a),k:a.g.filter(([id])=>byId[id]&&byId[id].c>0).length})).filter(r=>r.k&&(!r.a.need||perm[r.a.need])).sort((x,y)=>y.wv-x.wv);if(!rows.length)return;const top=rows[0];if(top.wv<.55)return;
      const si=SCEN.indexOf(s);const tr=Object.assign({},(CHAR.trace||[])[si]||{},(CHAR.trace_by||{})[s.id]||{});const say=tr[top.a.n];R.push(\`- \${s.t}: \${top.a.n.toLowerCase()}\${say?\` — «\${say}»\`:""}\`)});
    if(R.length){L.push(\`## Как реагирует\`);R.slice(0,10).forEach(x=>L.push(x))}}
  // как говорит: voice + гены речи
  const sp=all.filter(g=>g.c>0&&g.id.startsWith("sp.")&&Math.abs(g.v)>=.4).sort((a,b)=>Math.abs(b.v)*b.c-Math.abs(a.v)*a.c).slice(0,6);
  L.push(\`## Как говорит\`);if(CHAR.voice&&CHAR.voice.lang)L.push(\`- \${CHAR.voice.lang}\`);if(CHAR.voice&&CHAR.voice.timbre)L.push(\`- Голос: \${CHAR.voice.timbre}\`);sp.forEach(g=>L.push(\`- \${g.name}: \${gt(g.v>0?g.pos:g.neg)}.\`));
  L.push(\`## Речь · образцы\`);
  CHAR.samples.forEach(s=>L.push(\`- \${s.ctx}: «\${s.t}»\`));
`);
// из «Характера» убрать гены влечения — у них свой раздел
rep(`  let thr=.7,core=P.filter(g=>Math.abs(g.v)>=thr).slice(0,14);`,`  const adultP=!(CHAR.kind==="ребёнок"||CHAR.child)&&!(typeof isAI==="function"&&isAI());const P2=adultP?P.filter(g=>!g.id.startsWith("des.")):P;
  let thr=.7,core=P2.filter(g=>Math.abs(g.v)>=thr).slice(0,14);`);
rep(`  if(core.length<6){thr=.4;core=P.filter(g=>Math.abs(g.v)>=thr).slice(0,14)}`,`  if(core.length<6){thr=.4;core=P2.filter(g=>Math.abs(g.v)>=thr).slice(0,14)}`);
fs.writeFileSync("gs.html",t);console.log("comp2 ok");
