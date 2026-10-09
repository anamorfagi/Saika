// Выгрузка архетипов из сборки в pipeline/sigs.json — чтобы persona.py собирал персону из тех же типов, что и студия
const fs=require("fs");const t=fs.readFileSync(process.argv[2]||"gs.html","utf8");
const i=t.indexOf("\nconst SIGS=[");let d=0,j=t.indexOf("[",i);for(let k=j;k<t.length;k++){const ch=t[k];if(ch==="[")d++;else if(ch==="]"){d--;if(!d){j=k;break}}else if(ch==='"'){k++;while(t[k]!=='"'){if(t[k]==="\\")k++;k++}}}
const SIGS=eval(t.slice(t.indexOf("[",i),j+1));
// вставки SIGS.push(...) из update_nat — тоже
const m=t.match(/SIGS\.push\(([\s\S]*?)\n\);/);if(m){const extra=eval("["+m[1]+"]");SIGS.push(...extra)}
fs.writeFileSync("pipeline/sigs.json",JSON.stringify(SIGS.map(s=>({n:s.n,nm:s.nm||null,fam:s.fam,sex:s.sex||null,d:s.d,c:s.c})),null,1));console.log("sigs.json:",SIGS.length);
