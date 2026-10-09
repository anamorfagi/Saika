// Панель «Анализ»: строка «материалы» — путь к папке на диске → exe запускает ingest.py (видео/аудио/субтитры/тексты/фото → корпус),
// журнал и подстановка корпуса — как у разведки.
const fs=require("fs");let t=fs.readFileSync("gs.html","utf8");
function rep(a,b){if(!t.includes(a)){console.error("NOT FOUND:",a.slice(0,90));process.exit(1)}t=t.replace(a,b)}
rep(`  <div class="nclog scout" id="ncSL" hidden></div>`,`  <div class="row"><span>материалы</span><input id="ncFolder" class="ncline" style="flex:1;min-width:260px;margin:0" placeholder="папка на диске: C:\\\\AI\\\\Saika\\\\genome\\\\Analiz\\\\automate — видео (субтитры дорожкой или вшитые → OCR), аудио, srt, txt, фото"><button class="open" id="ncIngest">разобрать папку →</button></div>
  <div class="nclog scout" id="ncSL" hidden></div>`);
rep(`    P.querySelector("#ncFind").onclick=async()=>{`,`    P.querySelector("#ncIngest").onclick=async()=>{const r=P.querySelector("#ncFR"),L=P.querySelector("#ncSL");const folder=P.querySelector("#ncFolder").value.trim();if(!isLocal()){r.textContent="разбор папки работает через AnamorfGenom.exe";return}if(!NC.name){r.textContent="сначала имя в карточке";return}if(!folder){r.textContent="укажи папку";return}
      const id=translit(NC.name).slice(0,28);L.hidden=false;L.innerHTML="";r.textContent="разбираю…";const put=j=>{const s=j.stage;L.innerHTML+=(s==="done"?"<b>":s==="error"?"<b style='color:#e0605a'>":"<i>"+s+"</i> ")+j.msg+(s==="done"||s==="error"?"</b>":"")+"\\n";L.scrollTop=L.scrollHeight;if(typeof j.progress==="number")P.querySelector("#ncPr").style.width=Math.round(j.progress*100)+"%"};
      try{const x=await (await fetch("/api/ingest",{method:"POST",body:JSON.stringify({folder,id})})).json();if(x.error)throw new Error(x.error);
        let from=0;const tick=async()=>{const s=await (await fetch("/api/scout/"+x.id+"?from="+from)).json();s.lines.forEach(put);from=s.next;if(!s.done)return setTimeout(tick,1500);
          if(s.result&&s.result.ok){const c=await (await fetch("/api/scout/"+x.id+"/corpus")).text();T.value=NC.text=c;r.textContent="корпус подставлен: "+Math.round(c.length/1000)+"k символов · chars/"+x.id;(s.result.notes||[]).forEach(n=>put({stage:"note",msg:n}))}else r.textContent=(s.result&&s.result.msg)||"разбор остановился"};tick()}catch(e){r.textContent="✗ "+e.message}};
    P.querySelector("#ncFind").onclick=async()=>{`);
fs.writeFileSync("gs.html",t);console.log("ingest ok");
