// Архетипы: (1) клик по типу больше не сбрасывает прокрутку списка — позиция запоминается и восстанавливается после перерисовки;
// (2) «собрать типичный образ →» — синтетический персонаж из одного архетипа: каждый параметр типа = середина целевого диапазона (c=0.7),
//     остальные гены не сняты. Полезно как эталон: как выглядит «чистая Манипуляторша» на спирали, в компиляторе и в голосе.
const fs=require("fs");let t=fs.readFileSync("gs.html","utf8");
function rep(a,b){if(!t.includes(a)){console.error("NOT FOUND:",a.slice(0,90));process.exit(1)}t=t.replace(a,b)}
rep(`  document.getElementById("arch").innerHTML=\`<h2>Куда попадает`,`  const _rk=document.querySelector("#arch .rank"),_ad=document.querySelector("#arch .adet");const _sc=[_rk?_rk.scrollTop:0,_ad?_ad.scrollTop:0];
  document.getElementById("arch").innerHTML=\`<h2>Куда попадает`);
rep(`  document.querySelectorAll(".fpbar i").forEach(b=>b.onclick=()=>{archSel=+b.dataset.fp;saveState({arch:archSel});renderArch()});`,`  {const rk=document.querySelector("#arch .rank"),ad=document.querySelector("#arch .adet");if(rk)rk.scrollTop=_sc[0];if(ad)ad.scrollTop=_sc[1]}
  const mk=document.getElementById("archMake");if(mk)mk.onclick=()=>makeArchChar(cur.s,NMof(cur.s));
  document.querySelectorAll(".fpbar i").forEach(b=>b.onclick=()=>{archSel=+b.dataset.fp;saveState({arch:archSel});renderArch()});`);
// кнопка в панели типа — после описания
rep(`<p class="ad">\${gt(cur.s.d)}</p>
    <div class="legend2">`,`<p class="ad">\${gt(cur.s.d)}</p>
    <p><button class="open" id="archMake">собрать типичный образ →</button><span class="src" style="margin-left:12px">персонаж только из этого типа: \${cur.s.c.length} параметров в середине диапазона, остальное не снято</span></p>
    <div class="legend2">`);
rep(`// ---------- карточка «Новый персонаж»`,`// ---------- типичный образ архетипа → персонаж ----------
function makeArchChar(s,name){const id=("typ_"+translit(name)).slice(0,28);const genome={};
  for(const [g,lo,hi] of s.c){const v=Math.max(-1,Math.min(1,(lo+hi)/2));genome[g]=[+v.toFixed(2),0.7,[["k","типичный образ архетипа «"+name+"»: середина целевого диапазона "+lo+"…"+hi]]]}
  const gender=male()?"мужской":"женский";
  const obj={format:GENOME_FORMAT,id,exported:new Date().toISOString().slice(0,16),studio:"Anamorf Genom",genes_total:N,genes_captured:Object.keys(genome).length,
    meta:{kind:"персонаж",name,alias:"типичный образ · "+FAM[s.fam],src:"архетип «"+name+"» · семейство «"+FAM[s.fam]+"»",method:"синтез: "+s.c.length+" параметров типа = середина диапазона, c 0.7",desc:gt(s.d),identity:[],samples:[],never:[],masks:[],tensions:[],voice:{mode:"design",gender,age:"",lang:"русский",timbre:""}},genome};
  try{importChar(obj)}catch(e){alert(e.message);return}
  if(isLocal()){fetch("/api/chars",{method:"POST",body:JSON.stringify(obj,null,2)}).then(r=>{if(r.ok){try{const LC=JSON.parse(localStorage.getItem("gs_chars")||"{}");delete LC[id];localStorage.setItem("gs_chars",JSON.stringify(LC))}catch(e){}}}).finally(()=>{saveState({page:"genome"});location.hash="#"+id;location.reload()});return}
  saveState({page:"genome"});location.hash="#"+id;location.reload()}
// ---------- карточка «Новый персонаж»`);
// ворота «тёмный тип только при реальном вреде» — для синтетического эталона не применяются: у него нет сцен, по которым мерить вред
rep(` if(sig.fam==="тёмный"){const h=typeof HARM==="number"?HARM:harmLevel();score*=Math.min(1,.5+h/.4)}`,` if(sig.fam==="тёмный"&&!/^синтез/.test(CHAR.method||"")){const h=typeof HARM==="number"?HARM:harmLevel();score*=Math.min(1,.5+h/.4)}`);
fs.writeFileSync("gs.html",t);console.log("archtyp ok");
