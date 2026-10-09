// [ШАГ 5] Вставка персонажей из pipeline/chars/*/ в артефакт (gs.html): геном + карточка.
// Запуск из /home/claude:  node pipeline/build_char.js [id …]   (без аргументов — все папки chars/, у которых есть genome.json)
// Для существующего персонажа (kaguya) — только досъёмка: гены, у которых в артефакте c=0, берутся из genome.json; остальное не трогается.
const fs=require("fs"),path=require("path");
const ROOT=path.join(__dirname,"chars");let t=fs.readFileSync("gs.html","utf8");
const ids=process.argv.slice(2).length?process.argv.slice(2):fs.readdirSync(ROOT).filter(d=>fs.existsSync(path.join(ROOT,d,"char.json")));
const i0=t.indexOf("const GENOMES=");let lit=t.slice(i0+"const GENOMES=".length,t.indexOf("\nconst CHARS_META=",i0));lit=lit.slice(0,lit.indexOf("};")+1);
const G=eval("("+lit+")");
const m0=t.indexOf("const CHARS_META={");const m1=t.indexOf("\n};",m0);let metaLit=t.slice(m0+"const CHARS_META=".length,m1+3);
const log=[];
for(const id of ids){
  const dir=path.join(ROOT,id);const meta=JSON.parse(fs.readFileSync(path.join(dir,"char.json"),"utf8"));
  const gen=fs.existsSync(path.join(dir,"genome.json"))?JSON.parse(fs.readFileSync(path.join(dir,"genome.json"),"utf8")):{};
  if(G[id]&&meta.trace){metaLit=metaLit.replace(new RegExp("(\\n\\s*"+id+":\\{)"),"$1trace:"+JSON.stringify(meta.trace)+",");log.push(`${id}: реплики трассы`)}
  if(!Object.keys(gen).length){continue}
  const tmpl=G.kaguya;let n=0,added=0;
  if(G[id]){ // досъёмка
    G[id]=G[id].map(b=>Object.assign({},b,{genes:b.genes.map(g=>{const s=gen[g[0]];if(!s||g[3]>0)return g;added++;return [g[0],g[1],s[0],s[1],g[4],s[2].concat(s[3]==="spor"?[["!","спорный: улики расходятся"]]:[]),g[6],g[7]]})}));
    log.push(`${id}: досъёмка +${added} генов`);
  }else{
    G[id]=tmpl.map(b=>Object.assign({},b,{genes:b.genes.map(g=>{const s=gen[g[0]];if(!s||!s[1])return [g[0],g[1],0,0,g[4],[],g[6],g[7]];n++;return [g[0],g[1],s[0],s[1],g[4],s[2].concat(s[3]==="spor"?[["!","спорный: улики расходятся"]]:[]),g[6],g[7]]})}));
    const voice=Object.assign({mode:"design",gender:meta.gender||"женский",age:"",lang:"русский",timbre:""},meta.voice||{});voice.gender=meta.gender||voice.gender;
    const M={voice,name:meta.name,alias:meta.alias||"",src:meta.src||"",method:meta.method||"автоматический захват · следователь → свод",desc:meta.desc||"",
      identity:meta.identity||[],samples:meta.samples||[],never:meta.never||[],masks:meta.masks||[],tensions:meta.tensions||[]};
    for(const k of ["ageStated","ageVoice","ageText","photo"])if(meta[k])M[k]=meta[k];
    // вставка перед закрывающей скобкой CHARS_META
    metaLit=metaLit.replace(/\n};$/,`,\n ${id}:${JSON.stringify(M)}\n};`);
    log.push(`${id}: новый персонаж, снято ${n}/345`);
  }
}
t=t.slice(0,i0)+"const GENOMES="+JSON.stringify(G)+";"+t.slice(i0+"const GENOMES=".length+lit.length+1);
const m0b=t.indexOf("const CHARS_META={");const m1b=t.indexOf("\n};",m0b);
t=t.slice(0,m0b)+"const CHARS_META="+metaLit+t.slice(m1b+3);
fs.writeFileSync("gs.html",t);console.log(log.join("\n"));
