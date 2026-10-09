// Оценка сигнатур: условия весят по строгости, ключевой ген на противоположном полюсе режет тип.
// Было: все условия равны → Беймакс попадал в «Учтивого хищника» на 78% при садизме −0.7 (одно «мимо» тонуло в девяти «попал»).
const fs=require("fs");
let t=fs.readFileSync("gs.html","utf8");
function rep(a,b){if(!t.includes(a)){console.error("NOT FOUND:",a.slice(0,80));process.exit(1)}t=t.replace(a,b)}
rep(`function sigMatch(sig){let got=0,w=0;const rows=sig.c.map(([id,lo,hi])=>{const G=byId[id];if(!G||G.c===0)return {id,G,lo,hi,st:"na",s:0};const s=geneScore(G.v,lo,hi);got+=s*G.c;w+=G.c;return {id,G,lo,hi,s,st:s>=.99?"ok":s>0?"near":"no"}});const known=rows.filter(r=>r.st!=="na").length,cov=known/rows.length,raw=w?got/w:0;
 // неснятые параметры — по 0.5: ни за, ни против; иначе тип с 3 снятыми из 7 обгоняет тип с 7 из 7
 return {score:raw*cov+.5*(1-cov),raw,rows,known,cov}}`,
`// строгость условия = насколько диапазон далёк от нуля: [.7,1] — 0.7 (ключевой ген), [-1,.2] — 0 (слабое «не выше»). Вес условия = 0.4 + строгость.
function sigStrict(lo,hi){return lo>0?lo:hi<0?-hi:0}
function sigMatch(sig){let got=0,w=0,veto=null;const rows=sig.c.map(([id,lo,hi])=>{const G=byId[id];const k=.4+sigStrict(lo,hi);if(!G||G.c===0)return {id,G,lo,hi,st:"na",s:0,k};const s=geneScore(G.v,lo,hi);got+=s*G.c*k;w+=G.c*k;
   // ключевой ген (строгость ≥ .6) на противоположном полюсе — тип не подходит, что бы ни говорили остальные
   if(sigStrict(lo,hi)>=.6&&s===0&&Math.sign(G.v)===-Math.sign(lo>0?lo:hi)&&Math.abs(G.v)>=.3&&!veto)veto=G.name;
   return {id,G,lo,hi,s,k,st:s>=.99?"ok":s>0?"near":"no"}});const known=rows.filter(r=>r.st!=="na").length,cov=known/rows.length,raw=w?got/w:0;
 let score=raw*cov+.5*(1-cov);if(veto)score=Math.min(score,.45);
 // тёмный тип — только при реальном вреде: форма поведения (схемы, колкости) без ставок — не тёмная сторона (правило проекта про Кагую)
 if(sig.fam==="тёмный"){const h=typeof HARM==="number"?HARM:harmLevel();score*=Math.min(1,.5+h/.4)}
 return {score,raw,rows,known,cov,veto}}`);
// в панели типа — показать вето
rep(`<p class="note">\${cur.m.rows.filter(r=>r.st==="no").length?`,`<p class="note">\${cur.m.veto?\`<b style="color:var(--red,#e05)">Противоположный полюс по ключевому гену — \${cur.m.veto.toLowerCase()}: тип отсечён (не выше 45%).</b> \`:""}\${cur.m.rows.filter(r=>r.st==="no").length?`);
fs.writeFileSync("gs.html",t);console.log("sig ok");
