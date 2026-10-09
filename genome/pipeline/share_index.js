// share/index.js: список персонажей из share/*.genome.json без аватаров (аватары берутся из ava/<id>.jpg|png).
// Используется сборкой (build.sh) и запускателем (exe) — при старте, после сохранения и после удаления.
const fs=require("fs"),path=require("path");
function build(SHARE){try{fs.mkdirSync(SHARE,{recursive:true})}catch(e){}
  const L=[];for(const f of fs.readdirSync(SHARE).filter(f=>f.endsWith(".genome.json")).sort()){try{const o=JSON.parse(fs.readFileSync(path.join(SHARE,f),"utf8"));if(o.format!=="saika-genome/1")continue;delete o.avatar;L.push(o)}catch(e){console.warn("share/"+f+": "+e.message)}}
  fs.writeFileSync(path.join(SHARE,"index.js"),"// генерируется автоматически из share/*.genome.json — не править\nwindow.__SHARE="+JSON.stringify(L)+";\n");return L.length}
module.exports={build};if(require.main===module)console.log("index.js:",build(process.argv[2]||"share"),"персонажей");
