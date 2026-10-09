// Экспорт всех вшитых в сборку персонажей в share/<id>.genome.json (формат saika-genome/1) + сборка share/index.js.
// Запуск: node pipeline/export_all.js <папка_сборки>   (в ней ava/<id>.jpg|png и share/)
// Идея: единственный источник правды — папка share/. HTML персонажей не содержит; index.js — производный список без аватаров.
const fs=require("fs"),path=require("path");
const OUT=process.argv[2]||"dist/AnamorfGenom";const SHARE=path.join(OUT,"share"),AVA=path.join(OUT,"ava");
const t=fs.readFileSync("gs.html","utf8");
function lit(name){const i=t.indexOf("\nconst "+name+"=");if(i<0)return null;const s=t.indexOf("=",i)+1;let d=0,j=s;for(;j<t.length;j++){const ch=t[j];if(ch==="{")d++;else if(ch==="}"){d--;if(d===0)break}else if(ch==='"'){j++;while(t[j]!=='"'){if(t[j]==="\\")j++;j++}}}return eval("("+t.slice(s,j+1)+")")}
const G=lit("GENOMES"),M=lit("CHARS_META");if(!G||!M){console.error("в gs.html нет вшитых персонажей — нечего экспортировать");process.exit(0)}
fs.mkdirSync(SHARE,{recursive:true});
const KEYS=["kind","name","alias","src","method","desc","identity","samples","never","masks","tensions","voice","trace","trace_by","child","ageStated","ageVoice","ageText"];
let total=0;for(const id of Object.keys(G)){const genome={};let n=0;G[id].forEach(b=>b.genes.forEach(g=>{if(!g[3])return;n++;genome[g[0]]=[+g[2].toFixed(2),+g[3].toFixed(2),g[5]||[]];total++}));
  const meta={};for(const k of KEYS)if(M[id]&&M[id][k]!=null)meta[k]=M[id][k];
  let avatar;for(const ext of ["jpg","png"]){const f=path.join(AVA,id+"."+ext);if(fs.existsSync(f)){avatar="data:image/"+(ext==="jpg"?"jpeg":"png")+";base64,"+fs.readFileSync(f).toString("base64");break}}
  const N=G[id].reduce((s,b)=>s+b.genes.length,0);
  fs.writeFileSync(path.join(SHARE,id+".genome.json"),JSON.stringify({format:"saika-genome/1",id,exported:new Date().toISOString().slice(0,16),studio:"Anamorf Genom",genes_total:N,genes_captured:n,meta,genome,avatar},null,2));
  console.log("share/"+id+".genome.json",n+"/"+N,avatar?"ава":"без авы")}
// share/_list.js — служебный список для открытия с диска (браузер не читает папку и не грузит .json с file://); exe держит его в актуальном виде
fs.writeFileSync(path.join(SHARE,"_list.js"),"// служебный список персонажей для открытия html с диска — генерируется автоматически\nwindow.__SHARE="+JSON.stringify(fs.readdirSync(SHARE).filter(f=>f.endsWith(".genome.json")).sort().map(f=>{const o=JSON.parse(fs.readFileSync(path.join(SHARE,f),"utf8"));return o}))+";\n");
console.log("share/_list.js обновлён");
