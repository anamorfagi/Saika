// Карточки-заглушки от сорвавшихся исследований.
// Студия заводит персонажа в момент ЗАПУСКА поиска — чтобы спираль наполнялась
// на глазах. Если прогон падал, черновик оставался жить: «Карен · Исследование
// источников · снято 1/360». За ночь их накопилось с десяток.
// Здесь: такие черновики не показываются и вычищаются из памяти браузера.
const fs=require("fs");
let t=fs.readFileSync("gs.html","utf8");
function rep(a,b){if(!t.includes(a)){console.error("нет якоря:",a.slice(0,70));process.exit(1)}t=t.split(a).join(b)}

rep(`try{const LC=JSON.parse(localStorage.getItem("gs_chars")||"{}");for(const [id,c] of Object.entries(LC)){if(HIDDEN[id])continue;GENOMES[id]=c.genome;CHARS_META[id]=c.meta;CHARS_META[id].__src="local"}}catch(e){}`,
`// Черновик исследования: заведён при запуске, но ничего не собрал. Это не персонаж.
function черновик(id,c){
  if(!/^research_/.test(String(id)))return false;
  const m=(c&&c.meta)||{};
  const снято=(c.genome||[]).reduce((n,b)=>n+(b.genes||[]).filter(g=>g[3]>0).length,0);
  if(снято>2)return false;
  const улик=((m.evidence)||[]).length;
  if(улик>0)return false;
  return /Исследование источников|Сбор данных|Поиск персонажа/.test(String(m.alias||"")+" "+String(m.name||""));
}
try{const LC=JSON.parse(localStorage.getItem("gs_chars")||"{}");let убрано=0;
  for(const [id,c] of Object.entries(LC)){
    if(черновик(id,c)){delete LC[id];убрано++;continue}
    if(HIDDEN[id])continue;GENOMES[id]=c.genome;CHARS_META[id]=c.meta;CHARS_META[id].__src="local"}
  if(убрано){localStorage.setItem("gs_chars",JSON.stringify(LC));
    console.info("убрано черновиков исследования: "+убрано)}
}catch(e){}`);

fs.writeFileSync("gs.html",t);
console.log("черновики ok");
