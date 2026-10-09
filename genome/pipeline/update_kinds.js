// Сортировка карточек по виду: персонажи (вымышленные) · люди (живые) · ИИ-компаньоны.
// Клик по кнопке — только этот вид; Ctrl+клик — добавить/убрать вид; выбраны все — все карточки яркие. Выбор запоминается.
// Вид хранится в CHARS_META.<id>.kind ("персонаж" | "человек" | "ии"), уезжает в файл персонажа и задаётся в «Новом персонаже».
const fs=require("fs");
let t=fs.readFileSync("gs.html","utf8");
function rep(a,b){if(!t.includes(a)){console.error("NOT FOUND:",a.slice(0,80));process.exit(1)}t=t.replace(a,b)}
// [1] вид у существующих
for(const [id,k] of [["elsa","персонаж"],["kaguya","персонаж"],["kurumi","персонаж"],["snailkick","человек"],["baymax","ии"]]){
  const re=new RegExp("(\\n\\s*"+id+":\\{)");if(!re.test(t)){console.error("нет меты",id);process.exit(1)}t=t.replace(re,"$1kind:\""+k+"\",")}
// [2] кнопки видов + фильтр
rep("el.innerHTML=`<h2>Персонажи</h2><p class=\"lead\">Снятые профили. Клик по аватару — загрузить свой (хранится только в этом браузере). Каждый персонаж — отдельный геном на той же схеме из ${N} генов.</p><div class=\"cards\">`+\n  CHARS.map(c=>{",
"const KINDS=[[\"персонаж\",\"Персонажи\"],[\"человек\",\"Люди\"],[\"ии\",\"ИИ-компаньоны\"]];const ksel=new Set(ST.kinds&&ST.kinds.length?ST.kinds:KINDS.map(k=>k[0]));\n  el.innerHTML=`<div class=\"khead\"><div class=\"kinds\">${KINDS.map(([k,l])=>`<button class=\"kchip ${ksel.has(k)?'on':''}\" data-kind=\"${k}\">${l}<small>${CHARS.filter(c=>(c.kind||'персонаж')===k).length}</small></button>`).join(\"\")}</div></div><p class=\"lead\">Снятые профили. Клик по аватару — загрузить свой (хранится только в этом браузере). Каждый персонаж — отдельный геном на той же схеме из ${N} генов. Кнопки видов: клик — только этот вид, Ctrl+клик — добавить.</p><div class=\"cards\">`+\n  CHARS.filter(c=>ksel.has(c.kind||\"персонаж\")).map(c=>{");
rep(`bindNewChar(el);bindShare(el);ddAll(el);`,`bindNewChar(el);bindShare(el);ddAll(el);
  el.querySelectorAll(".kchip").forEach(b=>b.onclick=e=>{const k=b.dataset.kind;let s=new Set(ST.kinds&&ST.kinds.length?ST.kinds:KINDS.map(x=>x[0]));
    if(e.ctrlKey||e.metaKey){if(s.has(k)&&s.size>1)s.delete(k);else s.add(k)}else s=new Set([k]);
    ST.kinds=[...s];saveState({kinds:ST.kinds});renderChars()});`);
// [3] вид в форме нового персонажа: рядом с полом
rep(`<select id="ncG"><option value="женский">женский</option><option value="мужской">мужской</option></select>`,`<select id="ncG"><option value="женский">женский</option><option value="мужской">мужской</option></select><select id="ncKind"><option value="персонаж">персонаж</option><option value="человек">живой человек</option><option value="ии">ИИ-компаньон</option></select>`);
rep(`.card.new .nc .ncrow{grid-template-columns:1fr 1fr}`,`.card.new .nc .ncrow{grid-template-columns:1fr 1fr}.card.new .nc .ncrow.three{grid-template-columns:1fr 1fr 1fr}`);
rep(`<div class="ncrow"><select id="ncG">`,`<div class="ncrow three"><select id="ncG">`);
// вид → в мету при снятии и в файл
rep(`const meta={voice:{mode:"design",gender,age:"",lang:"русский",timbre:""},name,alias:"",src:"корпус из вкладки API · "+text.length+" символов",`,`const meta={kind:(document.getElementById("ncKind")||{}).value||"персонаж",voice:{mode:"design",gender,age:"",lang:"русский",timbre:""},name,alias:"",src:"корпус · "+text.length+" символов",`);
rep(`for(const k of ["name","alias","src","method","desc","identity","samples","never","masks","tensions","voice","trace","ageStated","ageVoice","ageText"])`,`for(const k of ["kind","name","alias","src","method","desc","identity","samples","never","masks","tensions","voice","trace","ageStated","ageVoice","ageText"])`);
// [4] стили: кнопки видов одного размера, в ряд с заголовком
rep(`.card .open.shr{`,`.khead{display:flex;align-items:baseline;gap:34px;flex-wrap:wrap;grid-column:1/-1}.khead h2{grid-column:auto}.kinds{display:flex;gap:34px;align-items:baseline}
.kchip{font:500 30px/1.05 var(--fd);color:var(--dim);background:none;border:0;padding:0;margin:0;cursor:pointer;display:inline-flex;align-items:baseline;gap:8px;letter-spacing:-.005em}
.kchip small{font:11px var(--fm);color:var(--dim);letter-spacing:.06em}.kchip.on{color:var(--text)}.kchip.on small{color:var(--muted)}.kchip:hover{color:var(--muted)}.kchip.on:hover{color:var(--text)}
.card .open.shr{`);
fs.writeFileSync("gs.html",t);console.log("kinds ok");
