// update_cards.js — вкладка «Персонажи»: без пояснительных строк, карточки одного размера (6 на экран: 3×2),
// поиск по имени и сортировка (имя · дата добавления · тип-жанр) справа от видов; жанр выводится из источника (хентай, аниме, кино…).
// Запуск: node update_cards.js (после update_store/update_newcard, до update_live). Правит gs.html.
const fs=require("fs");let t=fs.readFileSync("gs.html","utf8");
function rep(a,b){if(!t.includes(a)){console.error("не найдено:",a.slice(0,80));process.exit(1)}t=t.replace(a,b)}

// [1] дата экспорта — в meta, чтобы сортировать по дате добавления
rep(`return {id,genome,meta,n}}`,`meta.exported=meta.exported||obj.exported||"";return {id,genome,meta,n}}`);

// [2] жанр по источнику + фильтр/сортировка
rep(`function renderChars(){\n  const el=document.getElementById("chars");`,`// жанр персонажа — по строке источника и виду; используется как «тип» в сортировке и как метка на карточке
function genreOf(c){const s=String(c.src||"").toLowerCase();if((c.kind||"персонаж")==="человек")return "люди";if((c.kind||"персонаж")==="ии")return "ии";
  if(/хентай|hentai|ova 18|эро/.test(s))return "хентай";if(/персона без модели|синтез|архетип/.test(String(c.method||"").toLowerCase()))return "синтез";
  if(/ранобэ|манга|аниме|anime|manga/.test(s))return "аниме";if(/фильм|сериал|disney|мульт|кино/.test(s))return "кино";if(/игра|game/.test(s))return "игры";return "прочее"}
const GENRE_ORD=["хентай","аниме","кино","игры","люди","ии","синтез","прочее"];
function renderChars(){
  const el=document.getElementById("chars");const KQ=(ST.kq||"").trim().toLowerCase(),KS=ST.ksort||"name";`);
// шапка: виды слева, поиск и сортировка справа; пояснительный абзац убран
rep(`</div></div><p class="lead">Снятые профили — папка share/ рядом с программой.\${location.protocol==="file:"&&!window.__SHARE?" <b>Открыто с диска и список share/_list.js не найден — запусти AnamorfGenom.exe или «загрузить файл».</b>":""} Клик по аватару — картинка. Каждый персонаж — отдельный геном на той же схеме из \${N} генов. Кнопки видов: клик — только этот вид, Ctrl+клик — добавить.</p><div class="cards">\`+
  CHARS.filter(c=>ksel.has(c.kind||"персонаж")).map(c=>{`,
`</div><div class="ktools"><div class="sortp"><span class="t">сортировка</span>\${[["name","имя"],["date","дата"],["type","тип"]].map(([k,l])=>\`<button class="sb \${KS===k?'on':''}" data-sort="\${k}">\${l}</button>\`).join("")}</div><label class="search"><svg viewBox="0 0 24 24" width="15" height="15" aria-hidden="true"><circle cx="11" cy="11" r="7" fill="none" stroke="currentColor" stroke-width="1.8"/><path d="M16.5 16.5 21 21" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg><input id="kq" class="kq" placeholder="поиск: имя, титул, произведение, жанр…" value="\${(ST.kq||"").replace(/"/g,"&quot;")}" autocomplete="off" spellcheck="false"><button class="kx" id="kx" title="очистить" \${KQ?"":"hidden"}>×</button></label></div></div>\${location.protocol==="file:"&&!window.__SHARE?'<p class="lead"><b>Открыто с диска и список share/_list.js не найден — запусти AnamorfGenom.exe или «загрузить файл».</b></p>':""}<div class="cards">\`+
  CHARS.filter(c=>ksel.has(c.kind||"персонаж")).filter(c=>!KQ||(c.name+" "+(c.alias||"")+" "+(c.src||"")+" "+genreOf(c)).toLowerCase().includes(KQ))
  .sort((a,b)=>KS==="date"?String(b.exported||"").localeCompare(String(a.exported||""))||a.name.localeCompare(b.name,"ru"):KS==="type"?(GENRE_ORD.indexOf(genreOf(a))-GENRE_ORD.indexOf(genreOf(b)))||a.name.localeCompare(b.name,"ru"):a.name.localeCompare(b.name,"ru")).map(c=>{`);
// метка жанра и дата в карточке; описание и строки — в фиксированных слотах
rep(`<div><h3>\${c.name}<em>«\${c.alias}»</em></h3><div class="src"><i class="cdot"></i><b class="clab">\${gtx(co.label,maleOf(c.id))}</b> · вред \${co.harm.toFixed(2)}</div><div class="src">\${c.src}</div><div class="src">\${c.method}</div><p>\${c.desc}</p>
    \${ageCard(c.id)}`,
`<div><h3>\${c.name}<em>«\${c.alias}»</em></h3><div class="src"><i class="cdot"></i><b class="clab">\${gtx(co.label,maleOf(c.id))}</b> · вред \${co.harm.toFixed(2)} · <span class="gtag">\${genreOf(c)}</span>\${c.exported?\` · <span title="добавлен">\${String(c.exported).slice(0,10)}</span>\`:""}</div><div class="src one" title="\${String(c.src).replace(/"/g,"&quot;")}">\${c.src}</div><div class="src one" title="\${String(c.method).replace(/"/g,"&quot;")}">\${c.method}</div><p class="cdesc" title="\${String(c.desc).replace(/"/g,"&quot;")}">\${c.desc}</p>
    <div class="agew">\${ageCard(c.id)}</div>`);
// обработчики поиска/сортировки
rep(`  bindNewChar(el);bindShare(el);ddAll(el);`,`  bindNewChar(el);bindShare(el);ddAll(el);
  {const q=el.querySelector("#kq");let tm;q.oninput=()=>{ST.kq=q.value;saveState({kq:ST.kq});clearTimeout(tm);tm=setTimeout(()=>{const pos=q.selectionStart;renderChars();const q2=document.getElementById("kq");q2.focus();q2.setSelectionRange(pos,pos)},160)};
   el.querySelectorAll(".sb").forEach(b=>b.onclick=()=>{ST.ksort=b.dataset.sort;saveState({ksort:ST.ksort});renderChars()});
   const x=el.querySelector("#kx");if(x)x.onclick=()=>{ST.kq="";saveState({kq:""});renderChars();document.getElementById("kq").focus()}}`);

// [3] стили: сетка 3 колонки, одинаковые карточки, инструменты справа
rep(`.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(460px,1fr));gap:28px 40px;align-content:start}`,
`.cards{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:22px 36px;align-content:start;align-items:stretch}
@media (max-width:1500px){.cards{grid-template-columns:repeat(2,minmax(0,1fr))}}
.card>div:last-child{min-width:0;display:flex;flex-direction:column}.card>div:last-child>.open{margin-top:auto}
.card h3{white-space:nowrap;overflow:hidden;text-overflow:ellipsis;height:26px}
.card .src.one{white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin-bottom:6px;height:12px}
.card p.cdesc{height:76px;overflow:hidden;display:-webkit-box;-webkit-line-clamp:4;-webkit-box-orient:vertical;margin-bottom:6px}
.card .agew{height:16px;overflow:hidden}.card .agew .kv.agek{margin-top:0;flex-wrap:nowrap;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;display:block}.card .agew .kv.agek span{margin-right:12px}
.card .gtag{color:var(--gold);letter-spacing:.08em}
.card .btns{display:flex;gap:0;margin-top:10px;white-space:nowrap}.card .btns .open{margin-top:0}
.khead{justify-content:space-between;align-items:center}.ktools{display:flex;align-items:center;gap:22px}
.sortp{display:flex;align-items:center;gap:4px;padding:3px;border:1px solid rgba(233,226,236,.12);border-radius:999px;background:rgba(233,226,236,.03)}.sortp .t{font:9.5px var(--fm);letter-spacing:.12em;text-transform:uppercase;color:var(--dim);padding:0 10px 0 12px}
.sortp .sb{width:64px;height:28px;border:0;border-radius:999px;background:none;color:var(--muted);font:11.5px var(--fm);cursor:pointer}.sortp .sb.on{background:rgba(207,174,112,.16);color:var(--gold)}.sortp .sb:hover{color:var(--text)}
.search{display:flex;align-items:center;gap:10px;width:360px;height:36px;padding:0 12px 0 14px;border:1px solid rgba(233,226,236,.14);border-radius:999px;background:rgba(233,226,236,.035);color:var(--dim);box-sizing:border-box}.search:focus-within{border-color:rgba(207,174,112,.55);color:var(--gold)}
.search .kq{flex:1;min-width:0;height:100%;background:none;border:0;outline:none;color:var(--text);font:12.5px var(--fm);padding:0}.search .kq::placeholder{color:var(--dim)}
.search .kx{border:0;background:none;color:var(--dim);font:16px/1 var(--fb);cursor:pointer;padding:0 2px}.search .kx:hover{color:var(--text)}`);
// кнопки карточки — в один ряд внизу
rep(`<button class="open" data-open="\${c.id}">\${cur?"открыт · к спирали →":"открыть геном →"}</button><button class="open shr" data-share="\${c.id}">файл персонажа ↓</button><button class="open del" data-del="\${c.id}">удалить</button>\${editsCount(c.id)?\`<button class="rst" data-reset="\${c.id}">сбросить правки · \${editsCount(c.id)}</button>\`:""}</div></div>\`}).join("")+`,
`<div class="btns"><button class="open" data-open="\${c.id}">\${cur?"открыт · к спирали →":"открыть геном →"}</button><button class="open shr" data-share="\${c.id}">файл персонажа ↓</button><button class="open del" data-del="\${c.id}">удалить</button>\${editsCount(c.id)?\`<button class="rst" data-reset="\${c.id}">сбросить правки · \${editsCount(c.id)}</button>\`:""}</div></div></div>\`}).join("")+`);
fs.writeFileSync("gs.html",t);console.log("cards ok");
