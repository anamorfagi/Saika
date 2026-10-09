// Спираль: (1) центр правее — визуально посреди между линией блоков и панелью гена;
// (2) масштаб больше не подстраивается под длину блока при каждом переходе (раньше «плавал»): два фиксированных режима —
//     ближний ZNEAR (чуть ближе прежнего) и обзор ZFAR по средней кнопке (вся спираль, без затенений);
//     ctrl+колесо — плавно от ближнего до дальнего, с затенением соседних блоков. Выбранный масштаб запоминается.
const fs=require("fs");let t=fs.readFileSync("gs.html","utf8");
function rep(a,b,all){if(!t.includes(a)){console.error("NOT FOUND:",a.slice(0,90));process.exit(1)}t=all?t.split(a).join(b):t.replace(a,b)}
rep(`const CXF=0.6; // центр спирали — правее середины, слева место для полосы блока`,`const CXF=0.66; // центр спирали — визуально посреди между линией блоков слева и панелью гена справа`);
rep(`const cam={y:0,rot:0,zoom:1};const tgt={y:0,rot:0,zoom:1};`,`const ZNEAR=3.0,ZFAR=.42;   // ближний режим и обзор; между ними — ctrl+колесо
const cam={y:0,rot:0,zoom:ZNEAR};const tgt={y:0,rot:0,zoom:ZNEAR};`);
// переход между генами/блоками масштаб не трогает
rep(`  const spanB=blockEnd[G.bi]-blockStart[G.bi]+STEP*2;if(!overview)tgt.zoom=Math.min(2.6,Math.max(.8,(.7*H*DIST/spanB)/760));\n`,`\n`);
// обзор: дальний; выход из обзора — к сохранённому ближнему масштабу (не пересчёт по блоку)
rep(`  if(on){tgt.zoom=.42}else if(sel>=0){const G=all[sel];const spanB=blockEnd[G.bi]-blockStart[G.bi]+STEP*2;tgt.zoom=Math.min(2.6,Math.max(.8,(.7*H*DIST/spanB)/760))}}`,`  if(on){tgt.zoom=ZFAR}else{tgt.zoom=Math.min(ZNEAR,Math.max(ZFAR,(loadState().zoom||ZNEAR)))}}`);
// ctrl+колесо — в пределах [ZFAR, ZNEAR], с затенением (режим обзора при этом выключается)
rep(`if(e.ctrlKey){tgt.zoom=Math.min(2.6,Math.max(.35,tgt.zoom*(e.deltaY<0?1.08:.93)));saveState({zoom:tgt.zoom});return}`,`if(e.ctrlKey){if(overview)setOverview(false);tgt.zoom=Math.min(ZNEAR,Math.max(ZFAR,tgt.zoom*(e.deltaY<0?1.08:.93)));saveState({zoom:tgt.zoom});return}`);
rep(`document.getElementById("zin").onclick=()=>{tgt.zoom=Math.min(2.6,tgt.zoom*1.25);saveState({zoom:tgt.zoom})};`,`document.getElementById("zin").onclick=()=>{if(overview)setOverview(false);tgt.zoom=Math.min(ZNEAR,tgt.zoom*1.25);saveState({zoom:tgt.zoom})};`);
rep(`document.getElementById("zout").onclick=()=>{tgt.zoom=Math.max(.55,tgt.zoom/1.25);saveState({zoom:tgt.zoom})};`,`document.getElementById("zout").onclick=()=>{if(overview)setOverview(false);tgt.zoom=Math.max(ZFAR,tgt.zoom/1.25);saveState({zoom:tgt.zoom})};
{const s=loadState();if(s.zoomv!==3){saveState({zoomv:3,zoom:ZNEAR})}else{const z=s.zoom;if(z&&z>=ZFAR&&z<=ZNEAR){tgt.zoom=z;cam.zoom=z}}}   // запомненный масштаб; при смене ближнего режима (zoomv) — сброс на новый ближний`);
fs.writeFileSync("gs.html",t);console.log("zoom ok");
