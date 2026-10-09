// update_desc2.js — заменяет ВСЕ описания: 360 генов и 22 блока. Тексты живые, со сценками и репликами
// (написаны отдельным проходом, лежат в pipeline/descriptions.json). Заодно чинит ширину колонки описания.
// Запуск: node update_desc2.js (после update_strip). Правит gs.html и pipeline/genes.json.
const fs=require("fs");let t=fs.readFileSync("gs.html","utf8");
function rep(a,b){if(!t.includes(a)){console.error("не найдено:",a.slice(0,80));process.exit(1)}t=t.replace(a,b)}
const D=JSON.parse(fs.readFileSync("pipeline/descriptions.json","utf8"));

// [1] описания генов: DESC полностью перезаписывается (geneDesc берёт DESC[id] первым, шаблоны need/mod/dyn больше не нужны)
const i0=t.indexOf("const DESC=");if(i0<0){console.error("нет DESC");process.exit(1)}
const i1=t.indexOf("\n",t.indexOf("};",i0));
t=t.slice(0,i0)+"const DESC="+JSON.stringify(D.genes)+";"+t.slice(i1);

// [2] описания блоков: purpose в структуре блоков (одна копия на все геномы)
let nb=0;
for(const [id,txt] of Object.entries(D.blocks)){
  const re=new RegExp('("id":"'+id+'","name":"[^"]*","purpose":")([^"]*)(")');
  if(re.test(t)){t=t.replace(re,(m,a,_,c)=>a+txt.replace(/"/g,'\\"')+c);nb++}
}
// [3] колонка описания — на всю ширину панели, текст не прячется
rep(`.gdesc{font:15px/1.5 var(--fd);color:var(--text);margin:-22px 0 26px;max-width:62ch;height:68px`,
    `.gdesc{font:15px/1.5 var(--fd);color:var(--text);margin:-22px 0 26px;max-width:none;height:96px`);
rep(`.bdesc{font:13px/1.5 var(--fb);color:var(--muted);margin:10px 0 0;max-width:60ch}`,
    `.bdesc{font:13px/1.5 var(--fb);color:var(--muted);margin:10px 0 0;max-width:none}`);
fs.writeFileSync("gs.html",t);

// [4] те же тексты — в конвейер, чтобы следователь и профайлер видели их же
const gp="pipeline/genes.json";const g=JSON.parse(fs.readFileSync(gp,"utf8"));let ng=0;
for(const b of g){if(D.blocks[b.block]){b.purpose=D.blocks[b.block]}for(const x of b.genes){if(D.genes[x.id]){x.desc=D.genes[x.id];ng++}}}
fs.writeFileSync(gp,JSON.stringify(g,null,0),"utf8");
console.log("desc2 ok: блоков",nb,"генов",ng);
