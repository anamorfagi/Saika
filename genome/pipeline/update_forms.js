// Стилизованные поля карточки «Новый персонаж»: свои выпадающие списки вместо системных (белые/синие не из проги),
// шрифты проекта (JetBrains Mono для данных, Manrope для кнопок), одинаковые размеры у элементов одного назначения.
const fs=require("fs");
let t=fs.readFileSync("gs.html","utf8");
function rep(a,b){if(!t.includes(a)){console.error("NOT FOUND:",a.slice(0,80));process.exit(1)}t=t.replace(a,b)}
// [1] стили
rep(`.card.new .nc{display:flex;flex-direction:column;gap:8px}`,`.card.new .nc{display:flex;flex-direction:column;gap:8px}
.card.new .ncrow.model{grid-template-columns:1.7fr 1.1fr 1fr auto}.card.new .ncrow>*{min-width:0}.card.new .nc{min-width:0}.card.new .dd{min-width:0}
.card.new{grid-column:1/-1}.card.new .nc{display:grid!important;grid-template-columns:480px 1fr;grid-template-rows:auto auto 1fr auto auto;gap:10px 24px;align-items:start}.card.new .nc h3,.card.new .nc>.src,.card.new .ncprog,.card.new .nclog{grid-column:1/-1}
.card.new .ncl{display:flex;flex-direction:column;gap:10px}.card.new .nc textarea{grid-column:2;grid-row:3;height:100%!important;min-height:260px}.card.new .nc .ncrow{grid-template-columns:1fr 1fr}.card.new .nc .ncrow.one{grid-template-columns:1fr}.card.new .nc .ncrow.act{display:grid!important;grid-template-columns:1fr 1fr 1fr}.card.new .ncrow.act button{min-width:0!important;width:100%}
.card.new input,.card.new textarea{font:12.5px var(--fm)!important;letter-spacing:.01em;background:rgba(233,226,236,.035)!important;border:1px solid rgba(233,226,236,.11)!important;border-radius:4px!important;color:var(--text);padding:8px 12px!important;height:38px}
.card.new textarea{height:auto}.card.new input::placeholder,.card.new textarea::placeholder{color:var(--dim)}.card.new input:focus,.card.new textarea:focus{outline:none;border-color:rgba(207,174,112,.55)!important}
.card.new button{font:500 13px var(--fb)!important;height:38px;min-width:150px!important;border-radius:4px!important;padding:0 14px!important}
/* свой выпадающий список */
.dd{position:relative;height:38px}.dd>select{display:none}
.dd .ddb{height:38px;width:100%;box-sizing:border-box;display:flex;align-items:center;justify-content:space-between;gap:8px;padding:0 12px;font:12.5px var(--fm);color:var(--text);background:rgba(233,226,236,.035);border:1px solid rgba(233,226,236,.11);border-radius:4px;cursor:pointer;white-space:nowrap;overflow:hidden}
.dd .ddb span{overflow:hidden;text-overflow:ellipsis}.dd .ddb i{flex:none;width:7px;height:7px;border-right:1px solid var(--muted);border-bottom:1px solid var(--muted);transform:rotate(45deg) translateY(-2px)}
.dd.on .ddb{border-color:rgba(207,174,112,.55)}.dd .ddl{position:fixed;z-index:400;min-width:300px;background:var(--bg2);border:1px solid rgba(233,226,236,.14);border-radius:4px;box-shadow:0 14px 40px rgba(0,0,0,.6);max-height:260px;overflow:auto;padding:4px;display:none}
.dd.on .ddl{display:block}.dd .ddl div{font:12.5px var(--fm);color:var(--muted);padding:9px 12px;border-radius:3px;cursor:pointer;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.dd .ddl div:hover{background:rgba(233,226,236,.06);color:var(--text)}.dd .ddl div.cur{color:var(--gold)}
.dd .ddl div small{color:var(--dim);margin-left:8px}`);
// [2] превращение select → dd; работает с уже заполненным списком (провайдеры заполняются в bindNewChar)
rep(`// ---------- файл персонажа: экспорт / импорт ----------`,`// ---------- свои выпадающие списки ----------
function ddWrap(sel){if(!sel||sel.parentElement.classList.contains("dd"))return;const w=document.createElement("div");w.className="dd";sel.parentNode.insertBefore(w,sel);w.appendChild(sel);
  const b=document.createElement("div");b.className="ddb";b.innerHTML="<span></span><i></i>";const l=document.createElement("div");l.className="ddl";w.appendChild(b);w.appendChild(l);
  const label=o=>{const m=o.textContent.split(" · ");return m.length>1?m[0]+"<small>· "+m.slice(1).join(" · ")+"</small>":o.textContent};
  const sync=()=>{const o=sel.options[sel.selectedIndex];b.querySelector("span").innerHTML=o?label(o):"";l.innerHTML=[...sel.options].map((o,i)=>\`<div data-i="\${i}" class="\${i===sel.selectedIndex?'cur':''}">\${label(o)}</div>\`).join("");
    l.querySelectorAll("div").forEach(d=>d.onclick=e=>{e.stopPropagation();sel.selectedIndex=+d.dataset.i;w.classList.remove("on");sync();sel.dispatchEvent(new Event("change"))})};
  b.onclick=e=>{e.stopPropagation();document.querySelectorAll(".dd.on").forEach(x=>x!==w&&x.classList.remove("on"));w.classList.toggle("on");
    if(w.classList.contains("on")){const r=b.getBoundingClientRect();const width=Math.max(r.width,300);l.style.width=width+"px";l.style.left=Math.min(r.left,window.innerWidth-width-12)+"px";
      const need=Math.min(l.scrollHeight,260)+8;const below=window.innerHeight-r.bottom;                     // снизу не влезает — открываем вверх
      if(below<need&&r.top>need){l.style.top="";l.style.bottom=(window.innerHeight-r.top+4)+"px"}else{l.style.bottom="";l.style.top=(r.bottom+4)+"px"}}};
  sel.addEventListener("ddsync",sync);sync();w._sync=sync}
document.addEventListener("click",()=>document.querySelectorAll(".dd.on").forEach(x=>x.classList.remove("on")));
function ddAll(root){(root||document).querySelectorAll(".card.new select").forEach(s=>{ddWrap(s);s.dispatchEvent(new Event("ddsync"))})}
// ---------- файл персонажа: экспорт / импорт ----------`);
// после заполнения списка провайдеров — обернуть/обновить
rep(`  const M=el.querySelector("#ncM"),K=el.querySelector("#ncKey");`,`  ddAll(el);
  const M=el.querySelector("#ncM"),K=el.querySelector("#ncKey");`);
rep(`bindShare(document.getElementById("chars"));`,`bindShare(document.getElementById("chars"));ddAll(document.getElementById("chars"));`);
// при перерисовке карточек — тоже
rep(`bindNewChar(el);bindShare(el);`,`bindNewChar(el);bindShare(el);ddAll(el);`);
fs.writeFileSync("gs.html",t);console.log("forms ok");
