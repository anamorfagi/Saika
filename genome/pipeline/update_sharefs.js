// Персонажи из папки share/ рядом с exe: при запуске через AnamorfGenom.exe (http://localhost) страница подхватывает все share/*.genome.json,
// а «файл персонажа ↓» дополнительно кладёт файл в share/. Так снятые персонажи не теряются между браузерами и переносятся папкой.
const fs=require("fs");let t=fs.readFileSync("gs.html","utf8");
function rep(a,b){if(!t.includes(a)){console.error("NOT FOUND:",a.slice(0,80));process.exit(1)}t=t.replace(a,b)}
rep(`function loadAva(id){try{return localStorage.getItem(avaKey(id))}catch(e){return null}}`,`var AVAFS={};   // id → файл в ava/ рядом с exe (подхватывается с локального сервера)
function loadAva(id){try{const l=localStorage.getItem(avaKey(id));if(l)return l}catch(e){}return AVAFS[id]?"/ava/"+encodeURIComponent(AVAFS[id]):null}`);
rep(`bindShare(document.getElementById("chars"));`,`bindShare(document.getElementById("chars"));
// [share/] подхват при старте — только с локального сервера (exe); файловый и claude.ai варианты этого не умеют
(async()=>{if(!/^http/.test(location.protocol)||!/localhost|127\\.0\\.0\\.1/.test(location.hostname))return;
  try{const ra=await fetch("/api/avas");if(ra.ok){for(const f of await ra.json()){AVAFS[f.replace(/\.[^.]+$/,"")]=f}if(Object.keys(AVAFS).length)renderChars()}}catch(e){}
  try{const r=await fetch("/api/chars");if(!r.ok)return;const files=await r.json();let added=0;
    for(const f of files){const o=await (await fetch("/share/"+encodeURIComponent(f))).json();const id=String(o.id||"").toLowerCase().replace(/[^a-z0-9_]/g,"");if(!id||GENOMES[id])continue;importChar(o);added++}
    if(added){console.log("share/: добавлено персонажей",added);location.reload()}}catch(e){console.warn("share/",e.message)}})();`);
// при экспорте — ещё и в share/, если есть локальный сервер
rep(`    b.textContent=[saved,copied?"в буфере":""].filter(Boolean).join(" · ")`,`    if(/^http/.test(location.protocol)&&/localhost|127\\.0\\.0\\.1/.test(location.hostname)){try{const r=await fetch("/api/chars",{method:"POST",body:txt});if(r.ok)saved=(saved?saved+" · ":"")+"в share/"}catch(e){}}
    b.textContent=[saved,copied?"в буфере":""].filter(Boolean).join(" · ")`);
fs.writeFileSync("gs.html",t);console.log("sharefs ok");
