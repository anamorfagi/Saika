// Блок «Природа существа» (16 генов) и вид «существо».
// Беззубик не говорит: весь прежний геном описывает то, чего у него нет —
// формулировки, подтекст, самоописание. Зато есть своё: стая, территория,
// охота, прикосновение, привязка к человеку. Блок включается для вида
// «существо» и на остальных персонажей не влияет — гены остаются нулевыми.
const fs=require("fs");
let t=fs.readFileSync("gs.html","utf8");
const БЛОК=JSON.parse(fs.readFileSync("/home/claude/work/beast_block.json","utf8"));

function rep(a,b){if(!t.includes(a)){console.error("нет якоря: "+a.slice(0,60));process.exit(1)}t=t.split(a).join(b)}

// 1) гены в TEMPLATE — перед блоком «Природа агента», чтобы природа шла рядом с природой
if(t.includes('"id":"beast"')){console.log("beast уже вшит");}
else{
  const гены=БЛОК.genes.map(g=>JSON.stringify([g.id,g.name,0,0,g.ch,[],g.neg,g.pos])).join(",");
  const запись='{"id":"beast","name":'+JSON.stringify(БЛОК.name)+
    ',"purpose":'+JSON.stringify(БЛОК.purpose)+
    ',"compiles":'+JSON.stringify(БЛОК.compiles)+
    ',"interacts":'+JSON.stringify(БЛОК.interacts)+
    ',"extremes":'+JSON.stringify(БЛОК.extremes)+
    ',"genes":['+гены+']},';
  const якорь='{"id":"nat","name":"Природа агента"';
  if(!t.includes(якорь)){console.error("не нашёл блок nat");process.exit(1)}
  t=t.replace(якорь,запись+якорь);
}

// 2) вид «существо» в списке видов
rep('const KINDS=[["персонаж","Персонажи"],["человек","Люди"],["ии","ИИ-компаньоны"]]',
    'const KINDS=[["персонаж","Персонажи"],["человек","Люди"],["ии","ИИ-компаньоны"],["существо","Существа"]]');

// 3) блок «Природа существа» показывается только существам, «Природа агента» — только ИИ.
// Иначе у каждого персонажа в спирали висят 16 пустых генов про территорию и охоту.
if(!t.includes("ВИДОВЫЕ_БЛОКИ")){
  rep("const BLOCKS=GENOMES[CUR];const CHAR=CHARS_META[CUR];",
      "const ВИДОВЫЕ_БЛОКИ={beast:\"существо\",nat:\"ии\"};"+
      "const CHAR=CHARS_META[CUR];"+
      "const BLOCKS=(GENOMES[CUR]||[]).filter(b=>{const нужен=ВИДОВЫЕ_БЛОКИ[b.id];"+
      "if(!нужен)return true;if((CHAR&&CHAR.kind)===нужен)return true;"+
      "return (b.genes||[]).some(g=>g[3]>0)});");
}

fs.writeFileSync("gs.html",t);
console.log("beast ok · блоков в шаблоне:",(t.match(/"purpose":/g)||[]).length);
