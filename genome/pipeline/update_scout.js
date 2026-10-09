// Разведчик в студии: в карточке — имя и «откуда», в панели — «найти всё в сети →» с живым журналом ступеней (scout.py через exe).
// По завершении корпус подставляется в поле, пометка «ребёнок» переносится в вид/ограничения. Гейт «публичная персона» — в scout.py.
const fs=require("fs");let t=fs.readFileSync("gs.html","utf8");
function rep(a,b){if(!t.includes(a)){console.error("NOT FOUND:",a.slice(0,90));process.exit(1)}t=t.replace(a,b)}
// карточка: поле «откуда» под именем
rep(`<h3><input id="ncN" class="ncname" placeholder="Новый персонаж" autocomplete="off" spellcheck="false"></h3><div class="src" id="ncSrc">имя · картинка · анализ</div>`,
`<h3><input id="ncN" class="ncname" placeholder="Новый персонаж" autocomplete="off" spellcheck="false"></h3><input id="ncFrom" class="ncfrom" placeholder="откуда: произведение · канал · профессия" autocomplete="off" spellcheck="false"><div class="src" id="ncSrc">имя · откуда · картинка · анализ</div>`);
rep(`.card.new h3 .ncname::placeholder{`,`.card.new .ncfrom{font:12px var(--fm)!important;color:var(--muted);background:none!important;border:0!important;border-bottom:1px solid transparent!important;padding:0!important;height:auto;width:100%;outline:none;border-radius:0!important;margin:2px 0 6px;letter-spacing:.02em}.card.new .ncfrom::placeholder{color:var(--dim);opacity:1}.card.new .ncfrom:focus{border-bottom-color:rgba(207,174,112,.45)!important}
.card.new h3 .ncname::placeholder{`);
// панель: разведка вместо «найти в сети»
rep(`  <div class="row"><span>источник</span><button class="open" id="ncFind">найти в сети →</button><span id="ncFR" class="src"></span></div>`,
`  <div class="row"><span>разведка</span><button class="open" id="ncFind">найти всё в сети →</button><span id="ncFR" class="hint2">Википедия · фэндом-вики · интервью и подкасты (yt-dlp) · субтитры или whisper · просодия · фото → папка chars/&lt;id&gt;</span></div>
  <div class="nclog scout" id="ncSL" hidden></div>`);
rep(`.ncpanel .ncprog{`,`.ncpanel .hint2{font:11px var(--fm);color:var(--dim)}.ncpanel .nclog.scout{max-height:200px;margin:0 0 10px}.ncpanel .nclog.scout b{color:var(--gold)}.ncpanel .nclog.scout i{color:var(--dim);font-style:normal}
.ncpanel .ncprog{`);
// логика: NC.origin, запуск и опрос журнала
rep(`  N.value=NC.name;N.oninput=sync;sync();drawAva();`,`  N.value=NC.name;N.oninput=sync;sync();drawAva();const F=el.querySelector("#ncFrom");F.value=NC.origin||"";F.oninput=()=>NC.origin=F.value.trim();`);
const a=t.indexOf(`    P.querySelector("#ncFind").onclick=async()=>{`);const b=t.indexOf(`};\n`,t.indexOf(`r.textContent="✗ "+e.message}}`,a))+3;if(a<0||b<3){console.error("нет ncFind");process.exit(1)}
t=t.slice(0,a)+`    P.querySelector("#ncFind").onclick=async()=>{const r=P.querySelector("#ncFR"),L=P.querySelector("#ncSL");if(!isLocal()){r.textContent="разведка работает через AnamorfGenom.exe (python + yt-dlp); с диска — вставь корпус руками";return}if(!NC.name){r.textContent="сначала имя в карточке";return}
      const id=translit(NC.name).slice(0,28);L.hidden=false;L.innerHTML="";r.textContent="запускаю…";const put=j=>{const s=j.stage;L.innerHTML+=(s==="done"?"<b>":s==="stop"||s==="error"?"<b style='color:#e0605a'>":"<i>"+s+"</i> ")+j.msg+(s==="done"||s==="stop"||s==="error"?"</b>":"")+"\\n";L.scrollTop=L.scrollHeight;if(typeof j.progress==="number")P.querySelector("#ncPr").style.width=Math.round(j.progress*100)+"%"};
      try{const x=await (await fetch("/api/scout",{method:"POST",body:JSON.stringify({name:NC.name,origin:NC.origin||"",kind:P.querySelector("#ncKind").value,id})})).json();if(x.error)throw new Error(x.error);
        let from=0;const tick=async()=>{const s=await (await fetch("/api/scout/"+x.id+"?from="+from)).json();s.lines.forEach(put);from=s.next;r.textContent=s.done?"":"идёт… "+(s.lines.at(-1)?.stage||"");
          if(!s.done)return setTimeout(tick,1500);
          if(s.result&&s.result.ok){const c=await (await fetch("/api/scout/"+x.id+"/corpus")).text();T.value=NC.text=c;r.textContent="корпус подставлен: "+Math.round(c.length/1000)+"k символов · папка chars/"+x.id;if(s.result.child){r.textContent+=" · персонаж-ребёнок: блок влечения не снимается";P.querySelector("#ncKind").value=P.querySelector("#ncKind").value}(s.result.notes||[]).forEach(n=>put({stage:"note",msg:n}))}
          else r.textContent=(s.result&&s.result.msg)||"разведка остановилась"};tick()}catch(e){r.textContent="✗ "+e.message}};
`+t.slice(b);
fs.writeFileSync("gs.html",t);console.log("scout ok");
