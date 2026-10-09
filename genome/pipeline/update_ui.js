// v1.1d: описания генов, шкала −1 · 0 · +1, цельная линия блока слева, режим обзора по средней кнопке
const fs=require("fs");
let t=fs.readFileSync("gs.html","utf8");
function rep(a,b){if(!t.includes(a)){console.error("NOT FOUND:",a.slice(0,90));process.exit(1)}t=t.replace(a,b)}
const D1=JSON.parse(fs.readFileSync("desc1.json","utf8")),D2=JSON.parse(fs.readFileSync("desc2.json","utf8")),D3=JSON.parse(fs.readFileSync("desc3.json","utf8"));
const DESC=Object.assign({},D1,D2);

// ---- [1] описания генов: словарь + шаблоны для семейств ----
rep(`const SRC={w:"вики"`,`// Описание гена: что он значит и как виден в поведении. Семейства (need/mod/dyn/emo) — из шаблонов
const DESC=${JSON.stringify(DESC)};
const DFAM=${JSON.stringify(D3)};
function geneDesc(id){
  if(DESC[id])return DESC[id];
  let m;
  if(m=id.match(/^need\\.(\\w+)\\.(weight|target|sens)$/)){const n=DFAM.needs[m[1]];return n?\`Потребность: \${n}. \${DFAM.needp[m[2]]}\`:""}
  if(m=id.match(/^mod\\.(\\w+)\\.(bias|gain)$/)){const o=DFAM.mods[m[1]];return o?o[m[2]]:""}
  if(m=id.match(/^dyn\\.(\\w+)\\.(threshold|peak|decay|dwell)$/)){const c=DFAM.chans[m[1]];return c?\`Канал: \${c}. \${DFAM.dynp[m[2]]}\`:""}
  if(m=id.match(/^emo\\.(\\w+)\\.hide$/)){const e=DFAM.emos[m[1]];return e?DFAM.emot.replace("{E}",e):""}
  return ""}
const SRC={w:"вики"`);

// панель гена: описание под id; полюса −1 · 0 · +1; markdown из описания блока убрать
rep(`<h2>\${G.name}</h2><div class="id">\${G.id}</div>
  <div class="poles"><div class="\${G.v<0?'on':'off'}"><span>−1</span>\${G.neg}</div><div class="\${G.v>0?'on':'off'}"><span>+1</span>\${G.pos}</div></div>`,
`<h2>\${G.name}</h2><div class="id">\${G.id}</div>
  <p class="gdesc">\${geneDesc(G.id)||"<span class=unc>Описание не написано.</span>"}</p>
  <div class="poles"><div class="\${G.v<0?'on':'off'}"><span>−1</span>\${G.neg}</div><div class="mid \${Math.abs(G.v)<.15?'on':'off'}"><span>0</span>как у всех</div><div class="\${G.v>0?'on':'off'}"><span>+1</span>\${G.pos}</div></div>`);
rep(`.poles{display:grid;grid-template-columns:1fr 1fr;gap:18px;margin-top:12px}`,
`.poles{display:grid;grid-template-columns:1fr auto 1fr;gap:18px;margin-top:12px}
.poles div:last-child{text-align:right}.poles div.mid{text-align:center;color:var(--dim)}.poles div.mid.on{color:var(--text)}
.gdesc{font:15px/1.5 var(--fd);color:var(--text);margin:-22px 0 26px;max-width:62ch}`);
rep(`<p class="bdesc"><span class="short">\${G.b.purpose.split(/(?<=\\.)\\s/)[0]}</span><span class="full" hidden>\${G.b.purpose}`,
    `<p class="bdesc"><span class="short">\${G.b.purpose.replace(/\\*+/g,"").split(/(?<=\\.)\\s/)[0]}</span><span class="full" hidden>\${G.b.purpose.replace(/\\*+/g,"")}`);

// ---- [2] цельная линия блока слева: фиксированный x, вся высота; текущий блок — яркий отрезок на ней ----
rep(`const cam={y:0,rot:0,zoom:1};`,`let overview=false; // режим обзора: средняя кнопка — вся спираль ровно, без затенений, быстрее крутится
const BX=300; // x цельной линии блоков — не зависит от масштаба
const cam={y:0,rot:0,zoom:1};`);
// затенения: в обзоре — нет
rep(`const dimS=(curB<0||inBlock(it.ay+cam.y,curB))?1:.12;`,`const dimS=(overview||curB<0||inBlock(it.ay+cam.y,curB))?1:.12;`);
rep(`const dimS=it.bi===curB?1:.18;`,`const dimS=(overview||it.bi===curB)?1:.18;`);
rep(`dimB=G.bi===curB?1:.1,a=(.18+depth*.45)`,`dimB=(overview||G.bi===curB)?1:.1,a=(.18+depth*.45)`);
rep(`const dimB=G.bi===curB?1:.1;
      if(isSel||isHov)`,`const dimB=(overview||G.bi===curB)?1:.1;
      if(isSel||isHov)`);
// линия: рисуется один раз перед items; подписи блоков — на фиксированном x
rep(`  items.sort((a,b)=>a.z-b.z);const curB=sel>=0?all[sel].bi:-1;`,
`  items.sort((a,b)=>a.z-b.z);const curB=sel>=0?all[sel].bi:-1;
  // цельная линия блоков: фиксированный x, от подсказки до панели управления; не зависит от масштаба
  const LY0=96,LY1=H-70;ctx.strokeStyle="rgba(233,226,236,.14)";ctx.lineWidth=1;ctx.beginPath();ctx.moveTo(BX,LY0);ctx.lineTo(BX,LY1);ctx.stroke();`);
rep(`      const cur=it.bi===curB;let [sx,sy,s]=proj(-R-56,it.yy,0),[,ey]=proj(-R-56,it.y1,0);if(cur)sy=Math.max(sy,96);
      ctx.textBaseline="middle";
      if(!cur){ // чужие блоки — тихая подпись слева, не ближе рельса
        sx=Math.max(310,sx);ctx.font=\`500 10px "JetBrains Mono",monospace\`;ctx.textAlign="right";ctx.fillStyle="rgba(143,134,153,.35)";ctx.fillText(it.b.name.toUpperCase().replace(" · "," "),sx,sy);
      }else{ // текущий блок — полоса слева от спирали, но не ближе рельса
        const bx=Math.max(345,W*CXF-R*s-44);ctx.strokeStyle=ACCENT;ctx.lineWidth=2;ctx.beginPath();ctx.moveTo(bx,sy);ctx.lineTo(bx,ey);ctx.stroke();
        ctx.textAlign="right";ctx.font=\`500 12px "JetBrains Mono",monospace\`;ctx.fillStyle="#ece6ee";ctx.fillText(it.b.name.toUpperCase().replace(" · "," "),bx-12,sy);
        ctx.font=\`400 10px "JetBrains Mono",monospace\`;ctx.fillStyle="rgba(143,134,153,.8)";ctx.fillText(\`\${it.b.genes.length} генов\`,bx-12,sy+16);
      }`,
`      const cur=it.bi===curB;let [,sy]=proj(0,it.yy,0),[,ey]=proj(0,it.y1,0);
      const LY0=96,LY1=H-70;const cy0=Math.max(LY0,Math.min(LY1,sy)),cy1=Math.max(LY0,Math.min(LY1,ey));if(cy1-cy0<2)continue;
      // отрезок блока на общей линии: текущий — акцент, остальные — тихие
      ctx.strokeStyle=cur?ACCENT:"rgba(233,226,236,.26)";ctx.lineWidth=cur?2:1;ctx.beginPath();ctx.moveTo(BX,cy0);ctx.lineTo(BX,cy1);ctx.stroke();
      // подпись — вертикально вдоль отрезка, слева от линии; чужие блоки — только если отрезок вмещает текст
      const label=it.b.name.toUpperCase().replace(" · "," ")+(cur?\` · \${it.b.genes.length} ГЕНОВ\`:"");
      ctx.font=cur?\`500 11px "JetBrains Mono",monospace\`:\`500 9.5px "JetBrains Mono",monospace\`;const tw=ctx.measureText(label).width;
      if(cur||tw<cy1-cy0-12){const my=(cy0+cy1)/2;ctx.save();ctx.translate(BX-9,my);ctx.rotate(-Math.PI/2);ctx.textAlign="center";ctx.textBaseline="middle";ctx.fillStyle=cur?"#ece6ee":"rgba(143,134,153,.55)";ctx.fillText(label,0,0);ctx.restore()}`);

// ---- [3] режим обзора: средняя кнопка ----
rep(`cv.addEventListener("pointerdown",e=>{dragging=true;`,
`function setOverview(on){overview=on;cv.classList.toggle("ov",on);document.querySelector(".hint").textContent=on?"обзор · средняя кнопка — вернуться · тянуть — быстрое вращение · колесо — 5 генов":"колесо — следующий ген · тянуть — вращать · клик — ген · ctrl+колесо — масштаб · средняя кнопка — обзор";
  if(on){tgt.zoom=.42}else if(sel>=0){const G=all[sel];const spanB=blockEnd[G.bi]-blockStart[G.bi]+STEP*2;tgt.zoom=Math.min(2.6,Math.max(.8,(.7*H*DIST/spanB)/760))}}
cv.addEventListener("mousedown",e=>{if(e.button===1)e.preventDefault()}); // не давать браузеру автопрокрутку
cv.addEventListener("auxclick",e=>{if(e.button===1)e.preventDefault()});
cv.addEventListener("pointerdown",e=>{if(e.button===1){e.preventDefault();setOverview(!overview);return}dragging=true;`);
rep(`tgt.rot+=dx*.008;cam.rot+=dx*.008;tgt.y-=dy*1.4/cam.zoom;`,`const rs=overview?.024:.008;tgt.rot+=dx*rs;cam.rot+=dx*rs;tgt.y-=dy*1.4/cam.zoom;`);
rep(`function step(d){selectAbs(absIdx+d)}`,`function step(d){selectAbs(absIdx+d*(overview?5:1))}`);
rep(`tgt.zoom=Math.min(2.6,Math.max(.8,(.7*H*DIST/spanB)/760));
  lastPointer=performance.now();`,`if(!overview)tgt.zoom=Math.min(2.6,Math.max(.8,(.7*H*DIST/spanB)/760));
  lastPointer=performance.now();`);
rep(`if(e.ctrlKey){tgt.zoom=Math.min(2.6,Math.max(.55,`,`if(e.ctrlKey){tgt.zoom=Math.min(2.6,Math.max(.35,`);
rep(`<div class="hint">колесо — следующий ген · тянуть — вращать · клик — ген · ctrl+колесо — масштаб</div>`,
    `<div class="hint">колесо — следующий ген · тянуть — вращать · клик — ген · ctrl+колесо — масштаб · средняя кнопка — обзор</div>`);

fs.writeFileSync("gs.html",t);
console.log("ui ok");
