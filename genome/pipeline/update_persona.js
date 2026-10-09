// Персона без модели прямо в студии: панель «Анализ» получает внешность (теги по картинке через exe → tagger.py, либо руками),
// описание, 7 главных ползунков; вместе с архетипами всё сводится кодом (те же таблицы, что у pipeline/persona.py) и дорисовывается
// по корреляциям. Таблицы вшиваются при сборке из pipeline/*.json — один источник правды для python и браузера.
const fs=require("fs");let t=fs.readFileSync("gs.html","utf8");
function rep(a,b){if(!t.includes(a)){console.error("NOT FOUND:",a.slice(0,90));process.exit(1)}t=t.replace(a,b)}
const J=n=>{const d=JSON.parse(fs.readFileSync("pipeline/"+n,"utf8"));delete d._;return JSON.stringify(d)};
// [1] таблицы
rep(`var TEMPLATE=`,`var TAG2G=${J("tags2genes.json")},DESC_LEX=${J("desc_lex.json")},CORR=${J("correlations.json")};
var MAINS=[["тепло","soc.caring"],["напор","soc.dominance"],["общительность","soc.sociable"],["игривость","soc.playful"],["дисциплина","will.discipline"],["тревожность","dyn.fear.threshold"],["любопытство","ag.curiosity"]];
var TEMPLATE=`);
// [2] разметка панели: внешность · описание · главные · одна кнопка «собрать персону»
rep(`<button class="open" id="ncMix">собрать из архетипов →</button></div>`,`</div>
  <div class="row"><span>внешность</span><button class="open" id="ncTagBtn">теги по картинке →</button><span id="ncTagR" class="src"></span></div>
  <input id="ncTags" class="ncline" placeholder="теги внешности через запятую: smirk, goggles, oversized clothes… (или снять по картинке через exe)">
  <div class="row"><span>описание</span></div><textarea id="ncDesc" class="short" placeholder="Кто это, в две строки, прилагательными: игривая, любопытная, дерзкая, не любит правил, верна своим…"></textarea>
  <div class="row"><span>главные</span><span class="src">сдвинь только те, что знаешь; остальное вычислится</span></div>
  <div class="mains">\${MAINS.map(([l,g])=>\`<label><span>\${l}</span><input type="range" min="-1" max="1" step="0.1" value="0" data-g="\${g}"><b>—</b></label>\`).join("")}</div>
  <div class="row act"><button class="open pri" id="ncMix">собрать персону →</button><span id="ncPR" class="src"></span></div>`);
// [3] стили
rep(`.ncpanel .ncprog{`,`.ncpanel .ncline{width:100%;box-sizing:border-box;background:none;border:0;border-bottom:1px solid rgba(233,226,236,.18);color:var(--text);font:12.5px var(--fm);padding:8px 0;outline:none;margin:4px 0}.ncpanel .ncline:focus{border-bottom-color:rgba(207,174,112,.55)}.ncpanel .ncline::placeholder{color:var(--dim)}
.ncpanel textarea.short{min-height:64px}
.ncpanel .mains{display:grid;grid-template-columns:repeat(auto-fill,minmax(290px,1fr));gap:8px 36px;margin:6px 0 14px}.ncpanel .mains label{display:grid;grid-template-columns:110px 1fr 40px;align-items:center;gap:10px;font:10px var(--fm);letter-spacing:.08em;text-transform:uppercase;color:var(--dim)}.ncpanel .mains b{font:11px var(--fm);color:var(--text);text-align:right}.ncpanel .mains label.set span{color:var(--text)}
.ncpanel .mains input[type=range]{-webkit-appearance:none;appearance:none;height:14px;background:none;margin:0}.ncpanel .mains input[type=range]::-webkit-slider-runnable-track{height:1px;background:rgba(233,226,236,.25)}.ncpanel .mains input[type=range]::-webkit-slider-thumb{-webkit-appearance:none;width:10px;height:10px;border-radius:999px;background:var(--gold);margin-top:-4.5px}
.ncpanel .ncprog{`);
// [4] логика: сборка персоны кодом (зеркало persona.py)
rep(`// несколько архетипов → один геном:`,`// ---------- персона без модели: теги + описание + главные + архетипы → геном → дорисовка ----------
// same=true — улики одного источника (одно фото, одно описание): значение усредняется, уверенность = max, а не сумма
function pMerge(G,gid,v,c,ev,same){if(!TEMPLATE_IDS.has(gid))return;v=Math.max(-1,Math.min(1,+v));if(!G[gid]){G[gid]=[v,c,[ev]];return}const [v0,c0,evs]=G[gid];G[gid]=[+((v0*c0+v*c)/(c0+c)).toFixed(3),+(same?Math.max(c0,c):Math.min(1,c0+c*(1-c0))).toFixed(3),evs.concat([ev])]}
var INTENS={"очень":1.3,"крайне":1.4,"жутко":1.3,"слишком":1.3,"немного":.5,"слегка":.5,"чуть":.5,"чуточку":.4,"иногда":.5,"порой":.5};
var TEMPLATE_IDS=new Set(TEMPLATE.flatMap(b=>b.genes.map(g=>g[0])));
function pTags(G,tags){let hit=0;for(const [tag,p] of Object.entries(tags)){const r=TAG2G[tag.toLowerCase().replace(/_/g," ").trim()];if(!r)continue;hit++;for(const [g,v,c] of r)pMerge(G,g,v,Math.min(.3,c*p),["f","внешность: "+tag+" ("+(+p).toFixed(2)+")"],true)}return hit}
function pDesc(G,text){let low=text.toLowerCase();const hit=[];for(const ph in DESC_LEX){if(ph.includes(" ")&&low.includes(ph)){for(const [g,v] of DESC_LEX[ph])pMerge(G,g,v,.4,["k","описание: «"+ph+"»"],true);hit.push(ph);low=low.split(ph).join(" ")}}
  const words=low.match(/[а-яё]+/g)||[];words.forEach((w,i)=>{for(const stem in DESC_LEX){if(stem.includes(" ")||!w.startsWith(stem))continue;const prev=words.slice(Math.max(0,i-2),i);const neg=prev.some(x=>x==="не"||x==="без"||x==="ни");const k=(prev.map(x=>INTENS[x]).find(x=>x))||1;for(const [g,v] of DESC_LEX[stem])pMerge(G,g,(neg?-v:v)*k,.4,["k","описание: «"+((neg||k!==1)?prev.slice(-1).concat([w]).join(" "):w)+"»"],true);hit.push((neg?"не ":"")+w);break}});return hit}
function pFill(G){const acc={};for(const src in CORR){if(!G[src]||Math.abs(G[src][0])<.15)continue;const [vs,cs]=G[src];for(const [dst,w] of CORR[src]){if(G[dst])continue;(acc[dst]=acc[dst]||[]).push([w*vs*cs,Math.abs(w)*cs,src,vs,w,cs])}}
  let n=0;for(const dst in acc){const L=acc[dst];const num=L.reduce((a,x)=>a+x[0],0),den=Math.max(.5,L.reduce((a,x)=>a+x[1],0));const v=Math.max(-1,Math.min(1,num/den*Math.min(1,den/.3)));if(Math.abs(v)<.1)continue;n++;const cm=L.reduce((a,x)=>a+x[5],0)/L.length;
    G[dst]=[+v.toFixed(3),+Math.min(.3,.25*cm/.6).toFixed(3),[["d","дорисовка: "+L.sort((a,b)=>Math.abs(b[0])-Math.abs(a[0])).slice(0,4).map(x=>(byId[x[2]]?byId[x[2]].name:x[2])+" "+(x[3]>0?"+":"")+x[3].toFixed(1)+" × "+(x[4]>0?"+":"")+x[4].toFixed(1)).join("; ")]]]}return n}
function buildPersona({name,gender,kind,tags,desc,main,sigs,ava}){const G={};const log=[];const sex=gender==="мужской"?"m":"f";const nm=s=>sex==="m"&&s.nm?s.nm:s.n;
  for(const [g,v] of Object.entries(main||{})){const vv=g==="dyn.fear.threshold"?-v:v;pMerge(G,g,vv,.7,["k","главная характеристика "+(v>0?"+":"")+v])}if(main&&Object.keys(main).length)log.push("главные: "+Object.keys(main).length);
  if(desc&&desc.trim()){const h=pDesc(G,desc);log.push("описание: "+h.length+" слов → "+Object.keys(G).length+" генов")}
  if(tags&&Object.keys(tags).length){const h=pTags(G,tags);log.push("внешность: "+h+" тегов → "+Object.keys(G).length+" генов")}
  for(const s of sigs||[])for(const [g,lo,hi] of s.c){if(G[g]&&G[g][1]>=.4)continue;pMerge(G,g,(lo+hi)/2,.5,["k","архетип «"+nm(s)+"»: диапазон "+lo+"…"+hi])}if(sigs&&sigs.length)log.push("архетипы: "+sigs.map(nm).join(", ")+" (только незаданное)");
  const before=Object.keys(G).length;const filled=pFill(G);log.push("задано "+before+", дорисовано "+filled+" → "+Object.keys(G).length+" генов");
  const id=translit(name).slice(0,28);const parts=[tags&&Object.keys(tags).length?"внешность":"",desc&&desc.trim()?"описание":"",main&&Object.keys(main).length?"главные":"",sigs&&sigs.length?"архетипы: "+sigs.map(nm).join(", "):""].filter(Boolean);
  const obj={format:GENOME_FORMAT,id,exported:new Date().toISOString().slice(0,16),studio:"Anamorf Genom",genes_total:N,genes_captured:Object.keys(G).length,
    meta:{kind:kind||"персонаж",name,alias:(sigs||[]).map(nm).join(" · ")||"персона без модели",src:parts.join(" · "),method:"персона без модели: "+before+" генов задано, "+filled+" дорисовано по корреляциям (c 0.25)",desc:desc||"",identity:[],samples:[],never:[],masks:[],tensions:[],voice:{mode:"design",gender,age:"",lang:"русский",timbre:""}},genome:G,avatar:ava&&ava.length<400000?ava:undefined};
  return {obj,log}}
// несколько архетипов → один геном:`);
// [5] кнопки: теги по картинке (exe) и сборка персоны
rep(`    P.querySelector("#ncMix").onclick=()=>{const picked=`,`    P.querySelector("#ncTagBtn").onclick=async()=>{const r=P.querySelector("#ncTagR");if(!NC.ava){r.textContent="сначала картинка в карточке";return}if(!isLocal()){r.textContent="теги по картинке считает exe (tagger.py); с диска — впиши теги руками";return}r.textContent="считаю… (первый раз скачивается модель ~330 МБ)";
      try{const x=await (await fetch("/api/tags",{method:"POST",body:JSON.stringify({image:NC.ava})})).json();if(x.error)throw new Error(x.error);const L=Object.entries(x.tags||{}).filter(([k])=>TAG2G[k]);P.querySelector("#ncTags").value=L.map(([k,p])=>k+":"+p).join(", ");NC.tags=Object.fromEntries(L);r.textContent=Object.keys(x.tags||{}).length+" тегов, из них знакомых "+L.length}catch(e){r.textContent="✗ "+e.message}};
    P.querySelectorAll(".mains input").forEach(s=>{s.oninput=()=>{const l=s.parentElement;l.classList.add("set");l.querySelector("b").textContent=(+s.value>0?"+":"")+(+s.value).toFixed(1)}});
    P.querySelector("#ncMix").onclick=()=>{const picked=`);
rep(`      makeMixChar(picked,NC.name,P.querySelector("#ncG").value,P.querySelector("#ncKind").value,NC.ava)};`,`      const tags={};P.querySelector("#ncTags").value.split(",").map(s=>s.trim()).filter(Boolean).forEach(s=>{const [k,p]=s.split(":");tags[k.trim()]=p?+p:1});
      const main={};P.querySelectorAll(".mains label.set input").forEach(s=>main[s.dataset.g]=+s.value);
      const {obj,log}=buildPersona({name:NC.name,gender:P.querySelector("#ncG").value,kind:P.querySelector("#ncKind").value,tags,desc:P.querySelector("#ncDesc").value,main,sigs:picked,ava:NC.ava});
      if(!obj.genes_captured){r.textContent="нечего собирать: ни тегов, ни описания, ни ползунков, ни архетипов";return}
      r.textContent=log.join(" · ");try{importChar(obj)}catch(e){r.textContent="✗ "+e.message;return}
      const go=()=>{NC={ava:null,name:"",text:""};saveState({page:"genome"});location.hash="#"+obj.id;location.reload()};
      if(isLocal()){fetch("/api/chars",{method:"POST",body:JSON.stringify(obj,null,2)}).then(x=>{if(x.ok){try{const LC=JSON.parse(localStorage.getItem("gs_chars")||"{}");delete LC[obj.id];localStorage.setItem("gs_chars",JSON.stringify(LC))}catch(e){}}}).finally(()=>setTimeout(go,600))}else setTimeout(go,600)};`);
// архетипы больше не обязательны для кнопки
rep(`      if(!picked.length){r.textContent="выбери хотя бы один архетип";return}if(!NC.name){r.textContent="сначала имя в карточке";return}`,`      if(!NC.name){r.textContent="сначала имя в карточке";return}`);
// вид улики d — дорисовка по корреляциям; в карточке персонажа считаем задано/дорисовано отдельно
rep(`const SRC={w:"вики",k:"канон",v:"вывод",n:"ранобэ",t:"текст",a:"просодия",f:"фото"};`,`const SRC={w:"вики",k:"канон",v:"вывод",n:"ранобэ",t:"текст",a:"просодия",f:"фото",d:"дорисовка"};`);
rep("снято <b>${st.cap}</b> / ${N}","снято <b>${st.cap}</b>${(x=>x?` <small style=\"color:var(--dim)\">· дорисовано ${x}</small>`:\"\")(GENOMES[c.id].reduce((s,b)=>s+b.genes.filter(g=>g[3]&&g[5]&&g[5].length&&g[5].every(e=>e[0]===\"d\")).length,0))} / ${N}");
fs.writeFileSync("gs.html",t);console.log("persona ok");
