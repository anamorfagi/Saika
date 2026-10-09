// Панель гена: (1) ползунок — при перетаскивании панель не перестраивается (раньше oninput пересобирал весь блок,
//   и <input> исчезал из-под курсора — двигалось по шагу за клик); полная перерисовка — только при отпускании (change);
// (2) подписи генов под столбиками блока — вертикально, чтобы 12 «Внимание к…» не резались в «Внимание …».
const fs=require("fs");let t=fs.readFileSync("gs.html","utf8");
function rep(a,b){if(!t.includes(a)){console.error("NOT FOUND:",a.slice(0,90));process.exit(1)}t=t.replace(a,b)}
rep(`const sl=document.getElementById("gslider");sl.oninput=()=>{G.v=+sl.value;if(G.c===0){G.c=.5;if(!G.ev.length)G.ev.push(["v","Выставлено вручную в интерфейсе."])};G.edited=true;const s=loadState();s.edits=s.edits||{};s.edits[CUR]=s.edits[CUR]||{};s.edits[CUR][G.id]={v:G.v,c:G.c};saveState({edits:s.edits});applyContour();renderBody(G,true);renderChars()};`,
`const sl=document.getElementById("gslider");
  const commit=()=>{if(G.c===0){G.c=.5;if(!G.ev.length)G.ev.push(["v","Выставлено вручную в интерфейсе."])};G.edited=true;const s=loadState();s.edits=s.edits||{};s.edits[CUR]=s.edits[CUR]||{};s.edits[CUR][G.id]={v:G.v,c:G.c};saveState({edits:s.edits})};
  // во время перетаскивания — только значение, цвет и столбик текущего гена; без перестройки панели
  sl.oninput=()=>{G.v=+sl.value;commit();sl.style.setProperty("--p",((G.v+1)*50)+"%");sl.style.setProperty("--c","rgb("+toneRGB(G)+")");
    const bar=document.querySelector(".bins button.cur");if(bar){bar.style.height=Math.round(6+Math.abs(G.v)*50)+"px";bar.style.background="rgb("+toneRGB(G)+")";bar.classList.remove("none")}
    const vv=document.querySelector(".gval");if(vv)vv.textContent=(G.v>0?"+":"")+G.v.toFixed(2)};
  sl.onchange=()=>{applyContour();renderBody(G,true);renderChars()};`);
rep(`.binnames span{flex:1;min-width:0;font:9px var(--fm);color:var(--dim);text-align:center;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}`,
`.binnames{height:124px;align-items:flex-start}.binnames span{flex:1;min-width:0;font:9px var(--fm);color:var(--dim);writing-mode:vertical-rl;transform:rotate(180deg);text-align:right;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;height:124px;letter-spacing:.03em}`);
fs.writeFileSync("gs.html",t);console.log("slider ok");
