// update_dna.js — «вторая нить ДНК»: у каждого гена две полосы — снятая (улики) и предполагаемая (корреляции + архетипы).
//  · predict(): для всех 360 генов считает pv/pc/pfrom; неснятые получают предположение, снятые — проверку «сходится ли»
//  · спираль: пунктирная дорисовка перекладины до предполагаемого значения; серые гены — тусклая предполагаемая бусина
//  · столбики блока: вторая (контурная) полоса у каждого гена; карточка гена — строка «предполагается»
//  · ▶ сборка: проигрывание захвата — гены заполняются улика за уликой, потом неснятые перескакивают на предположение
// Запуск: node update_dna.js (после update_des2, до update_live). Правит gs.html.
const fs=require("fs");let t=fs.readFileSync("gs.html","utf8");
function rep(a,b){if(!t.includes(a)){console.error("не найдено:",a.slice(0,80));process.exit(1)}t=t.replace(a,b)}

// [1] расчёт предположений — после sigMatch (нужны архетипы) и до первого renderArch()
rep(`renderArch();\n`,`renderArch();
// ---------- ДНК: предполагаемая нить ----------
// Источники: (а) корреляции CORR — снятые гены тянут за собой связанные; (б) архетипы с совпадением ≥ 60 % — центр диапазона параметра.
// Уверенность предположения ≤ 0.45 и всегда ниже снятой — предположение никогда не выдаётся за факт.
function predict(){const adultOK=!(CHAR.kind==="ребёнок"||CHAR.child||(typeof isAI==="function"&&isAI()));const SEX=male()?"m":"f";
  const acc={};const push=(id,v,w,why)=>{(acc[id]=acc[id]||[]).push([v,w,why])};
  if(typeof CORR!=="undefined")for(const src in CORR){const S=byId[src];if(!S||!S.c||Math.abs(S.v)<.15)continue;for(const [dst,w] of CORR[src]){if(!byId[dst])continue;push(dst,Math.max(-1,Math.min(1,w*S.v)),Math.abs(w)*S.c*.5,S.name.toLowerCase()+" "+(S.v>0?"+":"")+S.v.toFixed(1))}}
  const top=SIGS.map(s=>({s,m:sigMatch(s)})).filter(r=>(!r.s.sex||r.s.sex===SEX)&&(!r.s.adult||adultOK)&&r.m.known>=3&&r.m.score>=.6).sort((a,b)=>b.m.score-a.m.score).slice(0,4);
  top.forEach(r=>r.s.c.forEach(([id,lo,hi])=>{if(!byId[id])return;push(id,(lo+hi)/2,(r.m.score-.5)*.6,"«"+(male()&&r.s.nm?r.s.nm:r.s.n)+"» "+Math.round(r.m.score*100)+"%")}));
  all.forEach(G=>{const a=acc[G.id];if(!a){G.pv=0;G.pc=0;G.pfrom=[];return}let s=0,w=0;a.forEach(([v,k])=>{s+=v*k;w+=k});G.pv=w?+(s/w).toFixed(2):0;G.pc=+Math.min(.45,w/(1+w)).toFixed(2);G.pfrom=a.sort((x,y)=>y[1]-x[1]).slice(0,4).map(x=>x[2])});
  DNA.pred=all.filter(G=>!G.c&&G.pc>0).length;DNA.agree=all.filter(G=>G.c&&G.pc>0&&Math.abs(G.v-G.pv)<=.35).length;DNA.check=all.filter(G=>G.c&&G.pc>0).length;
  const el=document.getElementById("sPred");if(el){el.textContent=DNA.pred;const cf=document.getElementById("sAgree");if(cf)cf.textContent=DNA.check?Math.round(DNA.agree/DNA.check*100)+"%":"—"}}
const DNA={pred:0,agree:0,check:0,playing:false};
predict();
`);

// [2] заголовок: две цифры — «предположено» и «сходится» (проверка предположений на снятых генах)
rep(`<div><b id="sConf">—</b><span>уверенность</span></div></div>`,`<div><b id="sConf">—</b><span>уверенность</span></div><div><b id="sPred">—</b><span>предположено</span></div><div><b id="sAgree" title="доля снятых генов, где предположение по другим генам попало в ±0.35 от снятого значения">—</b><span>сходится</span></div></div>`);

// [3] спираль: пунктир до предполагаемого значения; у неснятых — тусклая предполагаемая бусина
rep(`      const col=G.c===0?"140,132,150":toneRGB(G);ctx.lineWidth=(isSel||isHov?3.4:2.2)*s;ctx.strokeStyle=\`rgba(\${col},\${Math.min(1,a+.25)})\`;ctx.beginPath();ctx.moveTo(ax,ay);ctx.lineTo(cx,cy);ctx.stroke();`,
`      const col=G.c===0?"140,132,150":toneRGB(G);
      // предполагаемая нить: пунктир от остова до предполагаемого значения (тусклее, тоньше); у снятых — поверх, для сравнения
      if(G.pc>0&&(G.c===0||Math.abs(G.pv-G.v)>=.1)){const pf=.1+Math.abs(G.pv)*.8;const [px,py]=proj(it.x1+(it.x2-it.x1)*pf,it.yy,it.z1+(it.z2-it.z1)*pf);const pcol=toneRGB({v:G.pv,id:G.id,c:1});
        ctx.save();ctx.setLineDash([3*s,3*s]);ctx.lineWidth=1.8*s;ctx.strokeStyle=\`rgba(\${pcol},\${Math.min(1,(a+.3)*(.6+G.pc))})\`;ctx.beginPath();ctx.moveTo(ax,ay);ctx.lineTo(px,py);ctx.stroke();ctx.restore();
        if(G.c===0){ctx.fillStyle=\`rgba(\${pcol},\${(.4+depth*.4)*(.5+G.pc)*dimB})\`;ctx.beginPath();ctx.arc(px,py,(1.1+Math.abs(G.pv)*1.1)*s,0,7);ctx.fill()}}
      ctx.lineWidth=(isSel||isHov?3.4:2.2)*s;ctx.strokeStyle=\`rgba(\${col},\${Math.min(1,a+.25)})\`;ctx.beginPath();ctx.moveTo(ax,ay);ctx.lineTo(cx,cy);ctx.stroke();`);

// [4] столбики блока: вторая полоса (контур) — предположение
rep(`<div class="bins">\${G.b.genes.map(g=>byId[g[0]]).map(X=>\`<button data-i="\${X.i}" class="\${X.c===0?'none':'f'} \${X.i===G.i?'cur':''}" style="height:\${Math.round(6+Math.abs(X.v)*50)}px;\${X.c?'background:rgb('+toneRGB(X)+')':''}" title="\${X.name}: \${X.v>0?'+':''}\${X.v}" aria-label="\${X.name}"></button>\`).join("")}</div>`,
`<div class="bins">\${G.b.genes.map(g=>byId[g[0]]).map(X=>\`<button data-i="\${X.i}" class="\${X.c===0?'none':'f'} \${X.i===G.i?'cur':''}" style="height:\${Math.round(6+Math.abs(X.v)*50)}px;\${X.c?'background:rgb('+toneRGB(X)+')':''}" title="\${X.name}: снято \${X.c?(X.v>0?'+':'')+X.v:'—'} · предполагается \${X.pc?(X.pv>0?'+':'')+X.pv:'—'}" aria-label="\${X.name}">\${X.pc?\`<i class="pr" style="height:\${Math.round(6+Math.abs(X.pv)*50)}px;border-color:rgb(\${toneRGB({v:X.pv,id:X.id,c:1})})"></i>\`:""}</button>\`).join("")}</div>
  <div class="binname dna"><span><i class="sw f"></i>снято по уликам</span><span><i class="sw p"></i>предполагается по другим генам и архетипам</span></div>`);
// строка предположения в карточке гена — после строки уровня
rep(`  <div class="meta"><div><b>\${G.c.toFixed(2)}</b><span>уверенность</span></div>`,
`  \${G.pc?\`<div class="lv pred"><b>\${G.c?(Math.abs(G.v-G.pv)<=.35?"сходится":"расходится"):"предполагается"}</b><span>\${G.pv>0?"+":""}\${G.pv.toFixed(2)} · уверенность \${G.pc.toFixed(2)} · из: \${G.pfrom.join(", ")}</span></div>\`:""}
  <div class="meta"><div><b>\${G.c.toFixed(2)}</b><span>уверенность</span></div>`);

// [5] после ручной правки — пересчёт предположений
rep(`sl.onchange=()=>{applyContour();renderBody(G,true);renderChars()};`,`sl.onchange=()=>{applyContour();if(typeof predict==="function")predict();renderBody(G,true);renderChars()};`);

// [6] ▶ сборка: проигрывание захвата. Каждый шаг — реальная улика реального гена; значение растёт к снятому пропорционально доле улик,
//     уверенность — по формуле свода c'=c+c₂(1−c) с c₂ = доля; после последней улики неснятые гены перескакивают на предположение.
rep(`<div class="ctl"><button id="zin"`,`<div class="ctl"><button id="play" class="rst" title="показать, как геном собирался из улик">▶ сборка</button><button id="zin"`);
rep(`const DNA={pred:0,agree:0,check:0,playing:false};`,`const DNA={pred:0,agree:0,check:0,playing:false};
function playBuild(){if(DNA.playing)return;const steps=[];const final={};
  all.forEach(G=>{if(!G.c)return;final[G.id]={v:G.v,c:G.c};const ev=G.ev.filter(e=>e[0]!=="v");const n=Math.max(1,ev.length);ev.length?ev.forEach((e,k)=>steps.push({G,k:k+1,n,e})):steps.push({G,k:1,n:1,e:["v","вручную"]})});
  const ORD={f:0,k:1,w:2,n:3,t:4,a:5,v:6,d:7};steps.sort((x,y)=>(ORD[x.e[0]]??5)-(ORD[y.e[0]]??5)||x.G.i-y.G.i||x.k-y.k);
  if(!steps.length)return;DNA.playing=true;const btn=document.getElementById("play");btn.textContent="■ стоп";
  all.forEach(G=>{if(final[G.id]){G.v=0;G.c=0}});if(typeof LIVE!=="undefined"){LIVE.on=true;LIVE.recent={};LIVE.now=0}
  const log=document.getElementById("playlog")||(()=>{const d=document.createElement("div");d.id="playlog";document.querySelector(".stage").appendChild(d);return d})();log.hidden=false;
  let i=0;const dt=Math.max(18,Math.min(90,9000/steps.length));
  const tick=()=>{if(!DNA.playing)return;const s=steps[i];const f=final[s.G.id];const share=s.k/s.n;
    s.G.v=+(f.v*share).toFixed(2);s.G.c=+Math.min(1,s.G.c+(f.c*share)*(1-s.G.c)).toFixed(2);if(s.k===s.n){s.G.v=f.v;s.G.c=f.c}
    if(typeof LIVE!=="undefined"){LIVE.now+=1;LIVE.recent[s.G.id]=LIVE.now}
    log.innerHTML=\`<b>\${i+1} / \${steps.length}</b> · <span style="color:rgb(\${toneRGB(s.G)})">\${s.G.name}</span> \${s.G.v>0?"+":""}\${s.G.v.toFixed(2)} · c \${s.G.c.toFixed(2)} · улика \${s.k}/\${s.n} <em>\${(SRC&&SRC[s.e[0]])||s.e[0]}</em><br><span>\${String(s.e[1]).slice(0,140)}</span>\`;
    if(i%6===0||s.k===s.n){predict();if(sel>=0&&all[sel].b===s.G.b)renderBody(all[sel],true);const cap=all.filter(g=>g.c>0);sCov.textContent=cap.length+" · "+Math.round(cap.length/N*100)+"%";sConf.textContent=(cap.reduce((a,g)=>a+g.c,0)/Math.max(1,cap.length)).toFixed(2)}
    i++;if(i<steps.length){setTimeout(tick,dt)}else{finish()}};
  const finish=()=>{all.forEach(G=>{if(final[G.id]){G.v=final[G.id].v;G.c=final[G.id].c}});predict();applyContour();if(sel>=0)renderBody(all[sel],true);
    log.innerHTML=\`<b>снято \${Object.keys(final).length}</b> генов по уликам · <b>предположено \${DNA.pred}</b> по корреляциям и архетипам · сходится \${DNA.check?Math.round(DNA.agree/DNA.check*100)+"%":"—"} <span>пунктир на спирали — предполагаемая нить</span>\`;
    DNA.playing=false;btn.textContent="▶ сборка";if(typeof LIVE!=="undefined")setTimeout(()=>{LIVE.on=false;LIVE.recent={}},3000);setTimeout(()=>{log.hidden=true},9000)};
  btn.onclick=()=>{DNA.playing=false;finish()};tick()}
document.getElementById("play").onclick=()=>DNA.playing?null:playBuild();`);

// [7] стили
rep(`.vp{display:grid;gap:3px}`,`.vp{display:grid;gap:3px}
.bins button{position:relative}.bins button .pr{position:absolute;left:-1px;right:-1px;bottom:-1px;border:1px dashed;border-bottom:0;border-radius:2px 2px 0 0;pointer-events:none;opacity:.55}.bins button.none .pr{opacity:.8}
.binname.dna span{margin-right:14px}.binname.dna .sw{display:inline-block;width:9px;height:9px;vertical-align:-1px;margin-right:5px;border-radius:2px}.binname.dna .sw.f{background:var(--muted)}.binname.dna .sw.p{border:1px dashed var(--muted);box-sizing:border-box}
.lv.pred{margin-top:6px}.lv.pred b{color:var(--dim);font-style:italic}.lv.pred span{color:var(--dim)}
#play{margin-right:10px}#playlog{position:absolute;left:50%;bottom:64px;transform:translateX(-50%);max-width:640px;padding:8px 14px;background:rgba(14,10,18,.82);border:1px solid var(--hair);border-radius:4px;font:11px/1.5 var(--fm);color:var(--muted);pointer-events:none;z-index:5}#playlog b{color:var(--text)}#playlog em{color:var(--gold);font-style:normal}#playlog span{color:var(--dim)}`);
fs.writeFileSync("gs.html",t);console.log("dna ok");
