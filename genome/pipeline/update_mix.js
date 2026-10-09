// Быстрый путь без нейронки: в панели «Анализ» — до трёх архетипов → геном (пересечения усредняются) → персонаж.
// Дальше всё уже считается кодом: компилятор пишет системный промпт из генома, вкладка «Голос» — параметры манеры.
const fs=require("fs");let t=fs.readFileSync("gs.html","utf8");
function rep(a,b){if(!t.includes(a)){console.error("NOT FOUND:",a.slice(0,90));process.exit(1)}t=t.replace(a,b)}
rep(`  <div class="row"><span>источник</span><button class="open" id="ncFind">найти в сети →</button><span id="ncFR" class="src"></span></div>`,
`  <div class="row"><span>без нейронки</span><select id="ncA1"></select><select id="ncA2"></select><select id="ncA3"></select><button class="open" id="ncMix">собрать из архетипов →</button></div>
  <div class="row"><span>источник</span><button class="open" id="ncFind">найти в сети →</button><span id="ncFR" class="src"></span></div>`);
// заполнение списков и сборка
rep(`    P.querySelector("[data-goapi]").onclick=()=>document.querySelector('.nav button[data-p="api"]').click();`,
`    P.querySelector("[data-goapi]").onclick=()=>document.querySelector('.nav button[data-p="api"]').click();
    const fillA=()=>{const sex=P.querySelector("#ncG").value==="мужской"?"m":"f";const opts='<option value="">— архетип —</option>'+Object.keys(FAM).map(f=>SIGS.map((s,i)=>({s,i})).filter(x=>x.s.fam===f&&(!x.s.sex||x.s.sex===sex)).map(x=>'<option value="'+x.i+'">'+(sex==="m"&&x.s.nm?x.s.nm:x.s.n)+' · '+FAM[f]+'</option>').join("")).join("");
      ["#ncA1","#ncA2","#ncA3"].forEach(q=>{const s=P.querySelector(q);const v=s.value;s.innerHTML=opts;s.value=v;s.dispatchEvent(new Event("ddsync"))})};
    fillA();P.querySelector("#ncG").addEventListener("change",fillA);
    P.querySelector("#ncMix").onclick=()=>{const picked=["#ncA1","#ncA2","#ncA3"].map(q=>P.querySelector(q).value).filter(Boolean).map(i=>SIGS[+i]);const r=P.querySelector("#ncRR");
      if(!picked.length){r.textContent="выбери хотя бы один архетип";return}if(!NC.name){r.textContent="сначала имя в карточке";return}
      makeMixChar(picked,NC.name,P.querySelector("#ncG").value,P.querySelector("#ncKind").value,NC.ava)};`);
// сборка из нескольких архетипов — обобщение makeArchChar
rep(`// ---------- карточка «Новый персонаж»`,`// несколько архетипов → один геном: середины диапазонов, пересечения усредняются; c 0.6 (меньше, чем у чистого эталона 0.7)
function makeMixChar(sigs,name,gender,kind,ava){const id=translit(name).slice(0,28);const acc={};const sex=gender==="мужской"?"m":"f";const nm=s=>sex==="m"&&s.nm?s.nm:s.n;
  for(const s of sigs)for(const [g,lo,hi] of s.c){const v=Math.max(-1,Math.min(1,(lo+hi)/2));(acc[g]=acc[g]||[]).push([v,nm(s),lo,hi])}
  const genome={};for(const g in acc){const L=acc[g];const v=L.reduce((a,x)=>a+x[0],0)/L.length;genome[g]=[+v.toFixed(2),0.6,L.map(x=>["k","архетип «"+x[1]+"»: диапазон "+x[2]+"…"+x[3]])]}
  const obj={format:GENOME_FORMAT,id,exported:new Date().toISOString().slice(0,16),studio:"Anamorf Genom",genes_total:N,genes_captured:Object.keys(genome).length,
    meta:{kind:kind||"персонаж",name,alias:sigs.map(nm).join(" · "),src:"архетипы: "+sigs.map(s=>nm(s)+" ("+FAM[s.fam]+")").join(", "),method:"синтез без модели: "+sigs.length+" архетип(а), середины диапазонов, c 0.6",desc:sigs.map(s=>gt(s.d)).join(" "),identity:[],samples:[],never:[],masks:[],tensions:[],voice:{mode:"design",gender,age:"",lang:"русский",timbre:""}},genome,avatar:ava&&ava.length<400000?ava:undefined};
  try{importChar(obj)}catch(e){alert(e.message);return}
  const go=()=>{NC={ava:null,name:"",text:""};saveState({page:"genome"});location.hash="#"+id;location.reload()};
  if(isLocal()){fetch("/api/chars",{method:"POST",body:JSON.stringify(obj,null,2)}).then(r=>{if(r.ok){try{const LC=JSON.parse(localStorage.getItem("gs_chars")||"{}");delete LC[id];localStorage.setItem("gs_chars",JSON.stringify(LC))}catch(e){}}}).finally(go)}else go()}
// ---------- карточка «Новый персонаж»`);
fs.writeFileSync("gs.html",t);console.log("mix ok");
