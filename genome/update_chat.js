// [БЛОК ЧАТ · UI] Боковое окно справа: разговор с моделью по API + живой журнал сбора данных.
//
// Почему сбоку, а не вкладкой: карточки и геном человек смотрит одновременно с разговором —
// вкладка заставляла бы прыгать туда-сюда. Окно приклеено к правому краю, страница сжимается
// под него (padding-right у .stage), так что карточки не уезжают под панель.
//
// Одно окно на две задачи по просьбе: чат с ассистентом и тот самый журнал исследования
// с индикацией и ссылками — старые плавающие панели #researchPane/#researchDock переезжают
// внутрь этого окна, а не висят поверх контента.
const fs = require("fs");
const файл = "gs.html";
let t = fs.readFileSync(файл, "utf8");
if (t.includes("id=\"sideDock\"") || t.includes("__ЧАТ_ПАНЕЛЬ")) { console.log("чат уже вшит"); process.exit(0); }
if (!t.includes("</head>") || !t.includes("</body>")) { console.error("нет якоря"); process.exit(1); }

const CSS = `
<style id="chatDockCSS">
#sideDock .dhint,#sideDock .dmsg,#sideDock .dstep,#sideDock .dtool,#sideDock .drow{position:static}
/* Отдельное окно, а не приклеенная к краю плита: скруглённое, с тенью, его можно
   таскать за шапку и тянуть за любой край. Двойной щелчок по шапке возвращает его
   к правому краю — на случай, если уехало куда-то не туда. */
#sideDock{--dpad:14px;--dlist:268px;position:fixed;top:72px;right:16px;width:440px;height:calc(100vh - 104px);
  min-width:330px;min-height:260px;z-index:120;display:flex;flex-direction:column;
  background:linear-gradient(180deg,#191622,#131019);border:0;
  border-radius:16px;box-shadow:0 30px 80px #000e,0 2px 30px #0009;overflow:hidden;
  color:var(--text,#ece6ee);font:13.5px/1.6 var(--fb,system-ui),sans-serif;
  transition:opacity .16s ease,transform .16s ease}
body.dockOff #sideDock{opacity:0;transform:translateX(18px) scale(.99);pointer-events:none}
#sideDock .dgrip{position:absolute;z-index:6}
#sideDock .dgrip[data-e=w]{left:0;top:10px;bottom:10px;width:8px;cursor:ew-resize}
#sideDock .dgrip[data-e=e]{right:0;top:10px;bottom:10px;width:8px;cursor:ew-resize}
#sideDock .dgrip[data-e=n]{top:0;left:10px;right:10px;height:7px;cursor:ns-resize}
#sideDock .dgrip[data-e=s]{bottom:0;left:10px;right:10px;height:7px;cursor:ns-resize}
#sideDock .dgrip[data-e=nw]{left:0;top:0;width:14px;height:14px;cursor:nwse-resize}
#sideDock .dgrip[data-e=ne]{right:0;top:0;width:14px;height:14px;cursor:nesw-resize}
#sideDock .dgrip[data-e=sw]{left:0;bottom:0;width:14px;height:14px;cursor:nesw-resize}
#sideDock .dgrip[data-e=se]{right:0;bottom:0;width:16px;height:16px;cursor:nwse-resize}
/* Сверху ничего нет и ничего не перекрывает: лента начинается с первой строки.
   Всё управление внизу, окно тащится за пустое место нижней строки. */
body.dockDrag{user-select:none;cursor:grabbing}
#sideDock .dxbtn{background:none;border:0;color:var(--dim,#57505f);border-radius:7px;cursor:pointer;
  padding:4px 8px;font:10.5px var(--fm,monospace);letter-spacing:.1em;text-transform:uppercase;transition:.15s}
#sideDock .dxbtn:hover{color:var(--text,#ece6ee);background:rgba(233,226,236,.07)}
/* Полоса хода работы: пока ничего не происходит — её нет вовсе. Постоянная серая
   черта под шапкой ничего не сообщала и только делила окно лишней линией. */
#dockBar{height:0;background:none;overflow:hidden;transition:height .15s}
#dockBar i{display:block;height:100%;width:40%;background:linear-gradient(90deg,#cfae70,#6bbeb4)}
body.dockBusy #dockBar{height:2px}
body.dockBusy #dockBar i{animation:dockRun 1.6s linear infinite}
@keyframes dockRun{0%{margin-left:-40%}100%{margin-left:100%}}
#sideDock *{text-transform:none}
#sideDock .dpane{flex:1 1 auto;min-height:0;overflow:auto;padding:18px var(--dpad) 6px;display:none;overflow-wrap:anywhere}
#sideDock .dpane.don{display:block}
#sideDock .pane.on{display:block}
/* Реплика человека — коробка, ответ ассистента — просто текст: видно, где чья мысль,
   и длинный ответ не превращается в стену в рамке. */
#chatFlow .dmsg{margin:0 0 14px;white-space:pre-wrap}
/* Облачко без рамки и по ширине текста: рамка вокруг каждой реплики дробит ленту
   на клетки, а растянутый на всю ширину пузырь перестаёт читаться как реплика. */
#chatFlow .dmsg.me{max-width:85%;width:fit-content;margin-left:auto;padding:9px 13px;
  border-radius:14px;border:0;background:rgba(233,226,236,.09)}
#chatFlow .dmsg.ai{padding:1px 2px 2px}
#chatFlow .dmsg.err{width:fit-content;max-width:92%;padding:8px 12px;border-radius:12px;border:0;
  background:rgba(213,42,66,.14);color:#f0a8b2;font:12.5px/1.5 var(--fb,system-ui)}
#chatFlow .dstep{font:11px/1.5 var(--fm,monospace);color:var(--dim,#57505f);border-left:2px solid #35303c;
  padding:2px 0 2px 9px;margin:0 0 5px}
#chatFlow .dtool{font:11px/1.5 var(--fm,monospace);border-left:2px solid #6bbeb4;padding:4px 0 4px 9px;
  margin:0 0 9px;color:#9aa6a3}
#chatFlow .dtool>summary{cursor:pointer;list-style:none;color:#9aa6a3}
#chatFlow .dtool>summary::-webkit-details-marker{display:none}
#chatFlow .dtool>summary::before{content:"▸ ";color:#4f6b67}
#chatFlow .dtool[open]>summary::before{content:"▾ "}
#chatFlow .dtool b{color:#8fd3c8;font-weight:600}
#chatFlow .dtool pre{margin:4px 0 0;max-height:150px;overflow:auto;color:#8b8494;white-space:pre-wrap}
#chatFlow .dtool a{display:block;color:#9cbed1;text-decoration:none;margin-top:2px}
#chatFlow .dtool a:hover{text-decoration:underline}
/* Картинка в ленте — маленькой карточкой: развёрнутый скрин занимал пол-окна и
   выталкивал переписку. По щелчку открывается во весь экран. */
#chatFlow img.dshot{display:block;width:160px;height:110px;object-fit:cover;object-position:top;
  border-radius:10px;margin:6px 0 2px auto;cursor:zoom-in;transition:.15s}
#chatFlow img.dshot:hover{filter:brightness(1.12)}
#dockLightbox{position:fixed;inset:0;z-index:200;background:rgba(6,5,9,.94);display:flex;
  align-items:center;justify-content:center;padding:28px;cursor:zoom-out}
#dockLightbox img{max-width:100%;max-height:100%;border-radius:10px;box-shadow:0 30px 80px #000}
#chatFlow .dhint{color:var(--dim,#57505f);font:12.5px/1.6 var(--fb,system-ui);padding:8px 2px 2px}
#chatFlow .dseed{display:grid;grid-template-columns:repeat(auto-fit,minmax(168px,1fr));gap:7px;padding:2px 0 4px}
#chatFlow .dseed button{background:rgba(233,226,236,.045);border:0;border-radius:11px;
  color:var(--muted,#8f8699);cursor:pointer;padding:10px 12px;min-height:48px;
  font:11.5px/1.35 var(--fb,system-ui);text-align:left;transition:.15s}
#chatFlow .dseed button:hover{color:var(--text,#ece6ee);background:rgba(233,226,236,.085)}
/* Строка ввода — одна коробка, как в нормальном мессенджере: поле, слева скрепка,
   справа отправка. Подсказки про Enter и перетаскивание больше не занимают место
   постоянно — они появляются только пока поле пустое и в фокусе. */
/* Строка ввода — одна аккуратная полоса: скрепка слева, поле посередине, отправка справа.
   Подсказки про Enter убраны совсем: они занимали вторую строку и ничего не объясняли. */
#sideDock footer{padding:6px var(--dpad) 12px;position:relative}
/* Кем отвечать — видно и меняется прямо здесь, не уходя во вкладку API. */
/* Служебная строка под вводом: слева — что можно сделать, справа — кто отвечает.
   Всё текстом, без рамок и кнопок-коробок: это подпись, а не панель управления. */
#sideDock .dunder{display:flex;align-items:center;gap:10px;padding:9px 6px 0;min-height:18px}
#sideDock .dfill{flex:1;align-self:stretch;cursor:grab}
#sideDock .dfill:active{cursor:grabbing}
#sideDock .dlink{background:none;border:0;cursor:pointer;padding:2px 0;color:var(--dim,#57505f);
  font:11px var(--fb,system-ui);transition:color .15s}
#sideDock .dlink:hover{color:var(--text,#ece6ee)}
#sideDock .dmodel{font:10.5px var(--fm,monospace);letter-spacing:.06em;color:var(--muted,#8f8699);
  max-width:190px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
/* Список моделей: тот же приём, что и у выбора модели в чате — всплывает над кнопкой,
   показывает, чем отвечаем сейчас, и даёт выбрать другую, не уходя в настройки. */
/* Список бесед и история персонажа — внутри того же окна, выдвижной колонкой поверх
   ленты. Разговоры копятся, и без такого списка вчерашний разбор карточки найти негде. */
/* Список — часть раскладки, а не слой поверх: при открытии лента и строка ввода
   сдвигаются вправо. Полупрозрачная панель поверх текста читалась как брак. */
#chatList{position:absolute;left:0;top:0;bottom:0;width:var(--dlist,268px);z-index:7;overflow:auto;
  background:#191622;border-right:1px solid rgba(233,226,236,.07);padding:12px 10px 16px}
#sideDock.withList .dpane,#sideDock.withList footer{margin-left:var(--dlist,268px)}
#sideDock.withList #chatBeседы{color:var(--text,#ece6ee)}
@media(max-width:620px){#sideDock.withList .dpane,#sideDock.withList footer{margin-left:0}
  #chatList{width:100%}}
#chatList h5{margin:14px 8px 6px;font:9.5px var(--fm,monospace);letter-spacing:.18em;
  text-transform:uppercase;color:var(--dim,#57505f)}
#chatList h5:first-child{margin-top:2px}
#chatList .row{display:flex;align-items:center;gap:6px;border-radius:9px;padding:7px 9px;cursor:pointer;
  color:var(--muted,#8f8699);font:12px/1.35 var(--fb,system-ui)}
#chatList .row:hover{background:rgba(233,226,236,.06);color:var(--text,#ece6ee)}
#chatList .row.cur{background:rgba(233,226,236,.09);color:var(--text,#ece6ee)}
#chatList .row i{flex:1;font-style:normal;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
#chatList .row em{font-style:normal;color:var(--dim,#57505f);font-size:10px}
#chatList .row u{text-decoration:none;font:9.5px var(--fm,monospace);color:var(--dim,#57505f)}
#chatList .row b{opacity:0;color:#e08a96;font-weight:400}
#chatList .row:hover b{opacity:1}
#chatList .new{width:100%;text-align:left;background:rgba(233,226,236,.06);border:0;border-radius:9px;
  cursor:pointer;color:var(--text,#ece6ee);padding:9px 10px;font:12px var(--fb,system-ui)}
#chatList .new:hover{background:rgba(233,226,236,.1)}
#chatList .ev{padding:7px 9px;border-left:2px solid #35303c;margin:0 0 7px 8px;
  font:11px/1.45 var(--fm,monospace);color:var(--muted,#8f8699)}
#chatList .ev b{color:var(--gold,#cfae70);font-weight:500}
#chatList .ev q{display:block;color:var(--dim,#57505f);margin-top:3px;font-style:italic}
#modelMenu{position:absolute;right:var(--dpad);bottom:34px;z-index:8;min-width:230px;max-height:320px;
  overflow:auto;background:#221e2d;border-radius:12px;box-shadow:0 20px 50px #000d;padding:6px}
#modelMenu .mgrp{font:9.5px var(--fm,monospace);letter-spacing:.16em;text-transform:uppercase;
  color:var(--dim,#57505f);padding:8px 10px 4px}
#modelMenu button{display:flex;width:100%;align-items:center;gap:8px;background:none;border:0;cursor:pointer;
  color:var(--text,#ece6ee);text-align:left;padding:7px 10px;border-radius:8px;font:12px var(--fb,system-ui)}
#modelMenu button:hover{background:rgba(233,226,236,.07)}
#modelMenu button i{flex:1;font-style:normal;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
#modelMenu button s{text-decoration:none;color:var(--gold,#cfae70);font:12px var(--fm,monospace)}
/* Не «пилюля» с золотой обводкой, а спокойная коробка: мягкое скругление, нейтральный
   край, чуть светлее фона. Акцент тут не нужен — он забирает внимание у переписки. */
#sideDock .dbox{background:rgba(233,226,236,.075);border:0;border-radius:16px;
  padding:5px 7px;transition:background .15s}
#sideDock .dbox:focus-within{background:rgba(233,226,236,.1)}
#chatClips{display:flex;flex-wrap:wrap;align-items:flex-start;gap:7px}
#chatClips:not(:empty){margin:5px 5px 8px}
#chatClips span{background:rgba(233,226,236,.07);border:0;border-radius:9px;padding:4px 10px;
  font:10.5px var(--fm,monospace);color:var(--muted,#8f8699);cursor:pointer}
#chatClips span:hover{color:#ff8f9c;background:rgba(213,42,66,.14)}
/* Картинку показываем картинкой: по имени файла не видно, что именно приложил. */
#chatClips span.pic{position:relative;padding:0;width:56px;height:56px;border-radius:10px;overflow:hidden}
#chatClips span.pic img{width:100%;height:100%;object-fit:cover;display:block}
#chatClips span.pic b{position:absolute;right:3px;top:2px;font:11px var(--fb,system-ui);color:#fff;
  text-shadow:0 1px 4px #000;opacity:0;transition:.15s}
#chatClips span.pic:hover b{opacity:1}
#chatClips span.pic:hover img{opacity:.55}
/* Две раскладки одной строки ввода, как в образце:
   короткое сообщение — «+», текст и отправка в один ряд;
   как только текст переносится или появилось вложение — текст занимает всю ширину
   сверху, а кнопки уходят под него. Иначе длинный текст ползёт узкой колонкой
   справа от «+», что и раздражало. */
#sideDock .drow{display:flex;align-items:flex-end;gap:4px;flex-wrap:wrap}
#sideDock .dbox.multi #chatIn{order:-1;flex:0 0 100%;width:100%;padding:6px 6px 2px}
#sideDock .dbox.multi .drow{gap:0}
#sideDock .dbox.multi #chatSend{margin-left:auto}
#chatIn{flex:1;min-width:0;box-sizing:border-box;resize:none;min-height:32px;max-height:180px;background:none;
  border:0;color:var(--text,#ece6ee);padding:7px 4px;font:13.5px/1.5 var(--fb,system-ui);
  outline:none;display:block;overflow-y:auto}
#chatIn::placeholder{color:var(--dim,#57505f)}
/* Кнопки плоские: ни заливки, ни круга. Отправка оживает, только когда есть что отправить. */
#chatClip,#chatSend{width:32px;height:32px;flex:0 0 32px;border:0;background:none;border-radius:8px;
  cursor:pointer;padding:0;display:flex;align-items:center;justify-content:center;
  color:var(--muted,#8f8699);transition:.15s}
#chatClip{font:300 21px/1 var(--fb,system-ui)}
#chatClip:hover,#chatSend:not(:disabled):hover{color:var(--text,#ece6ee);background:rgba(233,226,236,.08)}
#chatSend{position:relative}
#chatSend::after{content:"";width:8px;height:8px;border-top:1.7px solid currentColor;border-right:1.7px solid currentColor;
  transform:rotate(-45deg);margin-top:2px}
#chatSend.stop::after{width:9px;height:9px;border:0;border-radius:2px;background:currentColor;
  transform:none;margin-top:0}
#chatSend.stop{color:#e08a96}
#chatSend:disabled{opacity:.35;cursor:default}
#sideDock.ddrop{outline:2px dashed var(--gold,#cfae70);outline-offset:-8px}
#dockTab{position:fixed;right:0;top:50%;transform:translateY(-50%);z-index:119;writing-mode:vertical-rl;
  background:#0d0b12;border:1px solid var(--hair2,rgba(233,226,236,.22));border-right:0;border-radius:9px 0 0 9px;
  color:var(--gold,#cfae70);cursor:pointer;padding:14px 6px;font:600 11px var(--fm,monospace);letter-spacing:.14em;display:none}
body.dockOff #dockTab{display:block}
body.dockRight:not(.dockOff) .stage{padding-right:var(--dockW,456px)}
#sideDock #researchPane,#sideDock #researchDock{position:static!important;width:auto!important;max-width:none!important;
  max-height:none!important;inset:auto!important;box-shadow:none!important;border:0!important;background:none!important;
  padding:0!important;backdrop-filter:none!important;transform:none!important}
@media(max-width:900px){#sideDock{left:8px!important;right:8px!important;top:8px!important;
  width:auto!important;height:calc(100vh - 16px)!important}
  body.dockRight:not(.dockOff) .stage{padding-right:0}}
</style>`;
t = t.replace("</head>", CSS + "\n</head>");

const JS = `
<script>
/* __ЧАТ_ПАНЕЛЬ — боковое окно: разговор с моделью и живой журнал сбора данных. */
(()=>{"use strict";
const $=s=>document.querySelector(s);
const esc=x=>String(x??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]||c));
const dock=document.createElement("aside");dock.id="sideDock";
dock.innerHTML=
 ['w','e','n','s','nw','ne','sw','se'].map(e=>'<div class="dgrip" data-e="'+e+'"></div>').join("")+
 '<div id="dockBar"><i></i></div>'+
 
 '<div class="dpane don" id="chatFlow"></div>'+
 '<div class="dpane" id="resFlow"></div>'+
 '<aside id="chatList" hidden></aside>'+
 '<footer><div class="dbox"><div id="chatClips"></div>'+
 '<div class="drow"><button id="chatClip" title="Прикрепить файл или картинку">+</button>'+
 '<textarea id="chatIn" rows="1" placeholder="Напиши сообщение…"></textarea>'+
 '<button id="chatSend" title="Отправить (Enter)"></button></div></div>'+
 '<div class="dunder"><button class="dlink" id="chatBeседы">Беседы</button>'+
 '<button class="dlink" id="chatWipe2">Очистить</button>'+
 '<button class="dlink" id="chatHide2">Закрыть</button>'+
 '<button class="dlink" id="chatRes2" hidden>Журнал сбора</button><span class="dfill"></span>'+
 '<button class="dlink dmodel" id="chatModel" title="Выбрать модель">модель</button>'+
 '<div id="modelMenu" hidden></div></div>'+
 '<input type="file" id="chatFile" multiple hidden></footer>';
document.body.appendChild(dock);
const tab=document.createElement("button");tab.id="dockTab";tab.textContent="АССИСТЕНТ";document.body.appendChild(tab);

/* ширина и состояние помнятся между запусками */
const П={get(k,d){try{const v=localStorage.getItem("gs_dock_"+k);return v===null?d:JSON.parse(v)}catch(e){return d}},
         set(k,v){try{localStorage.setItem("gs_dock_"+k,JSON.stringify(v))}catch(e){}}};
/* Геометрия окна живёт в одном месте: сдвиг и размер считаются в пикселях от левого
   верхнего угла, у правого края окно «пристёгнуто» — тогда страница поджимается под него. */
const ГРАНИЦЫ={w:330,h:260};
let гео=П.get("geo",null);
function применить(){
  const W=innerWidth,H=innerHeight;
  if(!гео){dock.style.cssText="";document.body.classList.add("dockRight");
    document.documentElement.style.setProperty("--dockW",(dock.offsetWidth+32)+"px");return}
  гео.w=Math.max(ГРАНИЦЫ.w,Math.min(W-24,гео.w));гео.h=Math.max(ГРАНИЦЫ.h,Math.min(H-24,гео.h));
  гео.x=Math.max(8-гео.w+120,Math.min(W-120,гео.x));гео.y=Math.max(4,Math.min(H-60,гео.y));
  Object.assign(dock.style,{left:гео.x+"px",top:гео.y+"px",right:"auto",bottom:"auto",
    width:гео.w+"px",height:гео.h+"px"});
  const уПравого=Math.abs((гео.x+гео.w)-W)<40;
  document.body.classList.toggle("dockRight",уПравого);
  document.documentElement.style.setProperty("--dockW",(гео.w+32)+"px");
  П.set("geo",гео)}
function снять(){const r=dock.getBoundingClientRect();гео={x:r.left,y:r.top,w:r.width,h:r.height}}
применить();
addEventListener("resize",применить);
/* тяга за края и углы */
dock.querySelectorAll(".dgrip").forEach(g=>g.addEventListener("mousedown",e=>{
  e.preventDefault();e.stopPropagation();if(!гео)снять();
  const край=g.dataset.e,старт={x:e.clientX,y:e.clientY},было=Object.assign({},гео);
  document.body.classList.add("dockDrag");
  const тянуть=ev=>{const dx=ev.clientX-старт.x,dy=ev.clientY-старт.y;
    if(край.includes("e"))гео.w=было.w+dx;
    if(край.includes("w")){гео.w=было.w-dx;гео.x=было.x+dx}
    if(край.includes("s"))гео.h=было.h+dy;
    if(край.includes("n")){гео.h=было.h-dy;гео.y=было.y+dy}
    применить()};
  const бросить=()=>{removeEventListener("mousemove",тянуть);removeEventListener("mouseup",бросить);
    document.body.classList.remove("dockDrag")};
  addEventListener("mousemove",тянуть);addEventListener("mouseup",бросить)}));
/* перетаскивание за шапку */
dock.querySelector(".dfill").addEventListener("mousedown",e=>{
  if(e.target.closest("button"))return;e.preventDefault();if(!гео)снять();
  const старт={x:e.clientX,y:e.clientY},было=Object.assign({},гео);
  document.body.classList.add("dockDrag");
  const везти=ev=>{гео.x=было.x+(ev.clientX-старт.x);гео.y=было.y+(ev.clientY-старт.y);применить()};
  const бросить=()=>{removeEventListener("mousemove",везти);removeEventListener("mouseup",бросить);
    document.body.classList.remove("dockDrag")};
  addEventListener("mousemove",везти);addEventListener("mouseup",бросить)});
/* двойной щелчок по шапке — вернуть к правому краю */
dock.querySelector(".dfill").addEventListener("dblclick",e=>{
  if(e.target.closest("button"))return;гео=null;П.set("geo",null);применить()});
const открыть=(да)=>{document.body.classList.toggle("dockOff",!да);П.set("open",!!да);
  if(да)setTimeout(()=>$("#chatIn").focus(),120)};
открыть(П.get("open",false));
tab.onclick=()=>открыть(true);$("#chatHide2").onclick=()=>открыть(false);
/* Escape закрывает по слоям: сперва меню моделей, потом список бесед, потом само окно —
   чтобы одним нажатием не терять всё сразу, когда открыт только список. */
/* «С» открывает окно — но только когда человек не печатает: иначе буква из текста
   в карточке или в поиске дёргала бы панель. Ловим и латинскую C, и кириллическую С. */
addEventListener("keydown",e=>{
  if(e.ctrlKey||e.metaKey||e.altKey)return;
  const ц=e.target,печатает=ц&&(ц.tagName==="INPUT"||ц.tagName==="TEXTAREA"||ц.isContentEditable);
  if(печатает)return;
  if(e.code==="KeyC"||e.key==="с"||e.key==="С"||e.key==="c"||e.key==="C"){
    if(document.body.classList.contains("dockOff")){e.preventDefault();открыть(true)}}});
addEventListener("keydown",e=>{
  if(e.key!=="Escape")return;
  const л=$("#dockLightbox");if(л){л.remove();return}
  if(document.body.classList.contains("dockOff"))return;
  const м=$("#modelMenu");if(м&&!м.hidden){м.hidden=true;return}
  const п=$("#chatList");if(п&&!п.hidden){показать_список(false);return}
  открыть(false)});
/* Двух вкладок наверху больше нет — окно открывается сразу разговором. Журнал сбора
   данных живёт за одной кнопкой в шапке, и сама кнопка появляется, только когда сбор идёт. */
const наВкладку=d=>{$("#chatFlow").classList.toggle("don",d==="chat");
  $("#resFlow").classList.toggle("don",d==="res");
  const н=$("#chatRes2");if(н)н.textContent=d==="res"?"Вернуться в чат":"Журнал сбора"};

/* журнал исследования переезжает внутрь окна, а не висит поверх карточек */
function забрать(){["researchPane","researchDock"].forEach(id=>{const el=document.getElementById(id);
  if(el&&el.parentNode!==$("#resFlow")){$("#resFlow").appendChild(el);открыть(true);
    $("#chatRes2").hidden=false;наВкладку("res");document.body.classList.add("dockBusy")}})}
new MutationObserver(забрать).observe(document.body,{childList:true});

/* Адрес студии. Бывает, что прежний лаунчер остался на своём порту (его не снять
   чужими правами), а рабочий поднялся на соседнем — и человек сидит во вкладке, где
   маршрутов чата нет. Вместо «переоткрой вкладку» находим живой порт сами. */
let БАЗА="";
async function живая_база(){
  if(БАЗА!==undefined&&БАЗА!=="")return БАЗА;
  try{const r=await fetch("/api/chat",{signal:AbortSignal.timeout(1500)});
    if(r.ok){БАЗА="";return ""}}catch(e){}
  const порт=+location.port||8765;
  for(let п=порт;п<=порт+10;п++){
    if(п===порт)continue;
    try{const r=await fetch("http://localhost:"+п+"/api/v",{signal:AbortSignal.timeout(900)});
      if(r.ok){БАЗА="http://localhost:"+п;return БАЗА}}catch(e){}}
  return ""}

/* ---- разговор ---- */
/* Затравки: с пустого окна трудно начать, а эти четыре вопроса — то, ради чего
   ассистент вообще здесь. Клик подставляет текст в поле, не отправляя: можно дописать. */
const ЗАТРАВКИ=["Что не так с этой карточкой?","Найди первоисточник реплик",
  "Собери системный промпт","Какие гены тут пустые и почему"];
/* Объявлено функцией, а не const: её зовут из показать_клипы() и перерисовать(),
   которые выполняются выше по файлу. С const это была ошибка доступа до инициализации,
   и она рвала весь остальной скрипт — вместе с тягой окна за края. */
function оживить(){const е=$("#chatSend");
  if(е&&!занят)е.disabled=!(($("#chatIn")||{}).value||"").trim()&&!вложения.length}
let отмена=null;
const поток=$("#chatFlow");let история=[],вложения=[],занят=false;
setInterval(()=>{забрать();
  const идёт=!!document.querySelector("#researchPane .researchWorkProgress i.active, #researchDock .researchProgress i.active");
  document.body.classList.toggle("dockBusy",идёт||занят)},1200);

const текущий=()=>{try{const к=(window.__CARD||window.карта||window.card||null);
  return (к&&к.id)||(к&&к.meta&&к.meta.id)||localStorage.getItem("gs_last_char")||""}catch(e){return ""}};
/* Беседы лежат ОДНИМ списком, а не по ящикам на каждого персонажа.
   Было так: ящик выбирался по открытой карточке, и стоило в разговоре кликнуть другого
   персонажа — текущая беседа подменялась чужой, а написанное будто пропадало. На деле
   оно никуда не девалось, просто лежало в ящике, которого больше не видно. Персонаж
   теперь всего лишь помечает беседу и уходит в запрос как контекст. */
const КЛЮЧ="gs_chats2", КУДА="gs_cur2";
function все_беседы(){try{const д=JSON.parse(localStorage.getItem(КЛЮЧ)||"[]");
  return Array.isArray(д)?д:[]}catch(e){return []}}
function записать_беседы(р){try{localStorage.setItem(КЛЮЧ,JSON.stringify(р.slice(0,60)))}catch(e){}}
function перенести_старое(){
  /* Переносим оба прежних хранилища, чтобы вчерашние разговоры не потерялись. */
  let р=все_беседы();if(р.length)return р;
  try{const по_домам=JSON.parse(localStorage.getItem("gs_chats")||"{}");
    for(const [дом,список] of Object.entries(по_домам||{}))
      for(const б of (список||[]))
        р.push(Object.assign({char:dom_имя(дом)},б));
  }catch(e){}
  try{for(const ключ of Object.keys(localStorage)){
    if(!ключ.startsWith("gs_chat_"))continue;
    const ст=JSON.parse(localStorage.getItem(ключ)||"[]");
    if(ст.length)р.push({id:"c"+Date.now()+Math.random().toString(36).slice(2,6),
      at:Date.now(),char:dom_имя(ключ.slice(8)),title:(ст[0].content||"").slice(0,70),msgs:ст});
  }}catch(e){}
  р.sort((a,b)=>(b.at||0)-(a.at||0));
  if(р.length)записать_беседы(р);
  return р}
function dom_имя(x){return x==="_"?"":String(x||"")}
function мои(){return перенести_старое()}
function текущая_id(){try{return localStorage.getItem(КУДА)||""}catch(e){return ""}}
function поставить_текущую(id){try{localStorage.setItem(КУДА,id||"")}catch(e){}}
function беседа(){const р=мои();return р.find(b=>b.id===текущая_id())||р[0]||null}
function открыть_беседу(id){поставить_текущую(id);const б=беседа();
  история=б?б.msgs.slice():[];перерисовать();рисовать_список()}
function новая_беседа(){const р=мои();
  const б={id:"c"+Date.now(),at:Date.now(),char:текущий()||"",title:"",msgs:[]};
  р.unshift(б);записать_беседы(р);поставить_текущую(б.id);
  история=[];перерисовать();рисовать_список()}
const сохранить=()=>{const р=мои();
  let б=р.find(x=>x.id===текущая_id());
  if(!б){б={id:"c"+Date.now(),at:Date.now(),char:текущий()||"",title:"",msgs:[]};р.unshift(б);поставить_текущую(б.id)}
  б.msgs=история.slice(-60);б.at=Date.now();
  if(текущий())б.char=текущий();
  if(!б.title){const п=история.find(m=>m.role==="user");
    б.title=((п&&п.content)||"").slice(0,70)}
  б.скартинкой=история.some(m=>(m.pics||[]).length>0);
  записать_беседы(р)};
{const б=беседа();история=б?б.msgs.slice():[];if(б)поставить_текущую(б.id)}
function низ(){поток.scrollTop=поток.scrollHeight}
function добавить(html){const d=document.createElement("div");d.innerHTML=html;while(d.firstChild)поток.appendChild(d.firstChild);низ()}
function перерисовать(){поток.innerHTML="";
  if(!история.length)добавить('<div class="dseed">'+ЗАТРАВКИ.map(з=>'<button>'+esc(з)+'</button>').join("")+'</div>');
  история.forEach(m=>добавить('<div class="dmsg '+(m.role==="user"?"me":"ai")+'">'+esc(m.content)+'</div>'+
    ((m.pics||[]).map(u=>'<img class="dshot" src="'+u+'">').join("")))); низ()}
перерисовать();setTimeout(оживить,0);
const очистить=()=>{история=[];сохранить();перерисовать();рисовать_список()};

/* --- список бесед и история персонажа --- */
function когда(t){const д=new Date(t);const с=(Date.now()-t)/1000;
  if(с<60)return "только что";
  if(с<3600)return Math.round(с/60)+" мин назад";
  if(с<86400)return Math.round(с/3600)+" ч назад";
  return д.toLocaleDateString("ru-RU",{day:"2-digit",month:"2-digit"})}

function рисовать_список(){
  const п=$("#chatList");if(!п||п.hidden)return;
  const р=мои(),тек=текущая_id();
  п.innerHTML='<button class="new" id="chatNew">+ Новая беседа</button>'+
    '<h5>Беседы</h5>'+
    (р.length?р.map(б=>'<div class="row'+(б.id===тек?" cur":"")+'" data-id="'+esc(б.id)+'">'+
      '<i>'+(б.скартинкой?"🖼 ":"")+esc(б.title||"Новая беседа")+(б.char?' <em>'+esc(б.char)+'</em>':'')+'</i><u>'+esc(когда(б.at))+'</u><b data-del="'+esc(б.id)+'">✕</b></div>').join("")
     :'<div class="ev">здесь пока пусто</div>')+
    '';
}

/* Открываем список — окну нужна ширина под две колонки, иначе переписка схлопнется. */
function показать_список(да){
  if(да){if(!гео)снять();if(гео.w<620){гео.w=Math.min(innerWidth-24,620);гео.x=Math.max(8,гео.x-(620-dock.offsetWidth));применить()}}
  const п=$("#chatList");п.hidden=!да;
  dock.classList.toggle("withList",!!да);if(да)рисовать_список()}
$("#chatBeседы").onclick=e=>{e.stopPropagation();показать_список($("#chatList").hidden)};

$("#chatList").onclick=e=>{
  e.stopPropagation();
  if(e.target.id==="chatNew")return новая_беседа();
  const уд=e.target.closest("[data-del]");
  if(уд){записать_беседы(мои().filter(b=>b.id!==уд.dataset.del));
    if(текущая_id()===уд.dataset.del){const б=беседа();поставить_текущую(б?б.id:"");история=б?б.msgs.slice():[];перерисовать()}
    return рисовать_список()}
  const р=e.target.closest(".row[data-id]");
  if(р)открыть_беседу(р.dataset.id)};
$("#chatWipe2").onclick=очистить;
$("#chatRes2").onclick=()=>наВкладку($("#resFlow").classList.contains("don")?"chat":"res");
поток.addEventListener("click",e=>{const b=e.target.closest(".dseed button");if(!b)return;
  const поле=$("#chatIn");поле.value=b.textContent+" ";поле.focus();подрасти()});
/* Смена открытого персонажа больше не трогает разговор: он просто уйдёт в следующий
   запрос как контекст, а в списке беседа получит пометку, с кем она. */
let прежний=текущий();
setInterval(()=>{const т=текущий();if(т===прежний)return;прежний=т;
  if(история.length)сохранить();
  if(!$("#chatList").hidden)рисовать_список()},1500);

/* вложения: кнопка, перетаскивание, вставка из буфера */
function ужать(url,бок){return new Promise(готово=>{
  const и=new Image();
  и.onload=()=>{const к=Math.min(1,бок/Math.max(и.width,и.height));
    const c=document.createElement("canvas");c.width=Math.round(и.width*к);c.height=Math.round(и.height*к);
    try{c.getContext("2d").drawImage(и,0,0,c.width,c.height);готово(c.toDataURL("image/jpeg",0.72))}
    catch(e){готово("")}};
  и.onerror=()=>готово("");и.src=url})}
function показать_клипы(){оживить();подрасти();
  $("#chatClips").innerHTML=вложения.map((f,i)=>/^data:image/.test(f.data)
    ?'<span class="pic" data-i="'+i+'" title="'+esc(f.name)+'"><img src="'+f.data+'" alt=""><b>✕</b></span>'
    :'<span data-i="'+i+'">'+esc(f.name)+' ✕</span>').join("")}
$("#chatClips").onclick=e=>{const s=e.target.closest("span");if(!s)return;вложения.splice(+s.dataset.i,1);показать_клипы()};
$("#chatClip").onclick=()=>$("#chatFile").click();
/* поле растёт под текст, а не прокручивается в две строки */
const подрасти=()=>{const e=$("#chatIn");if(!e)return;e.style.height="auto";
  const в=Math.min(180,e.scrollHeight);e.style.height=в+"px";e.scrollTop=e.scrollHeight;
  // Больше одной строки или есть вложение — переходим на раскладку в две полосы.
  const к=document.querySelector("#sideDock .dbox");
  if(к)к.classList.toggle("multi",в>44||вложения.length>0)};
$("#chatIn").addEventListener("input",()=>{подрасти();оживить()});
addEventListener("load",подрасти);setTimeout(подрасти,0);
$("#chatFile").onchange=e=>{взять(e.target.files);e.target.value=""};
function взять(список){[...список].slice(0,8).forEach(f=>{if(f.size>25*1024*1024)return;
  const r=new FileReader();r.onload=()=>{вложения.push({name:f.name,mime:f.type||"",data:String(r.result)});показать_клипы()};
  r.readAsDataURL(f)})}
dock.addEventListener("dragover",e=>{e.preventDefault();dock.classList.add("ddrop")});
dock.addEventListener("dragleave",()=>dock.classList.remove("ddrop"));
dock.addEventListener("drop",e=>{e.preventDefault();dock.classList.remove("ddrop");открыть(true);взять(e.dataTransfer.files)});
$("#chatIn").addEventListener("paste",e=>{const f=[...(e.clipboardData&&e.clipboardData.files||[])];if(f.length){e.preventDefault();взять(f)}});
$("#chatIn").addEventListener("keydown",e=>{if(e.key==="Enter"&&!e.shiftKey){e.preventDefault();отправить()}});
$("#chatSend").onclick=()=>{if(занят){try{отмена&&отмена.abort()}catch(e){}return}отправить()};

async function отправить(){
  if(занят)return;const поле=$("#chatIn");const текст=поле.value.trim();
  if(!текст&&!вложения.length)return;
  занят=true;document.body.classList.add("dockBusy");
  const кн=$("#chatSend");кн.disabled=false;кн.classList.add("stop");кн.title="Остановить";
  const файлы=вложения.slice();вложения=[];показать_клипы();поле.value="";подрасти();
  const снимки=файлы.filter(f=>/^data:image/.test(f.data));
  const запись={role:"user",content:текст||"(файл)"};
  история.push(запись);сохранить();
  добавить('<div class="dmsg me">'+esc(текст||"(файл)")+'</div>'+
    снимки.map(f=>'<img class="dshot" src="'+f.data+'">').join(""));
  // Миниатюры досохраняем отдельно: полноразмерный скрин в localStorage не влезает,
  // а без них в истории оставалось голое «(файл)» и найти разговор было не по чему.
  if(снимки.length)Promise.all(снимки.map(f=>ужать(f.data,320)))
    .then(м=>{запись.pics=м.filter(Boolean).slice(0,4);сохранить()});
  const тело={id:текущий(),provider:выбор.prov||undefined,model:выбор.model||undefined,
    messages:история.map((m,i)=>i===история.length-1?Object.assign({},m,{files:файлы}):m)};
  /* Ни одна строка ответа не пропадает молча. Раньше неразобранная строка тихо
     отбрасывалась — и когда сервер отдал «нет файла: /api/chat» (старый лаунчер без
     нового маршрута), в окне не появилось ВООБЩЕ ничего: ни ответа, ни ошибки.
     Отсутствие ошибки хуже ошибки: чинить нечего, потому что не видно, что сломалось. */
  let былОтвет=false;
  try{
    const база=await живая_база();
    if(база)добавить('<div class="dstep">эта вкладка от прежнего запуска — отвечает студия на '+esc(база)+'</div>');
    const r=await fetch(база+"/api/chat",{method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify(тело),signal:(отмена=new AbortController()).signal});
    if(!r.ok){const т=await r.text();былОтвет=true;
      добавить('<div class="dmsg err">Сервер ответил '+r.status+': '+esc(т.slice(0,300))+
        (r.status===404?'<br><br>Маршрут /api/chat не поднят — студия работает на старом коде.':'')+'</div>')}
    else{
      const rd=r.body.getReader();const dec=new TextDecoder();let буфер="";
      const разобрать=строка=>{if(!строка.trim())return;let e;былОтвет=true;
        try{e=JSON.parse(строка)}catch(err){добавить('<div class="dmsg err">'+esc(строка.slice(0,400))+'</div>');return}
        событие(e)};
      for(;;){const {value,done}=await rd.read();if(done)break;
        буфер+=dec.decode(value,{stream:true});const части=буфер.split(String.fromCharCode(10));буфер=части.pop();
        части.forEach(разобрать)}
      разобрать(буфер)}
  }catch(e){былОтвет=true;
    добавить(e&&e.name==="AbortError"?'<div class="dstep">остановлено</div>'
      :'<div class="dmsg err">'+esc(e.message||e)+'</div>')}
  if(!былОтвет)добавить('<div class="dmsg err">Сервер закрыл соединение, не сказав ни слова. Смотри studio.log.</div>');
  занят=false;кн.classList.remove("stop");кн.title="Отправить (Enter)";отмена=null;
  оживить();document.body.classList.remove("dockBusy");
}
function событие(e){
  if(e.t==="step")добавить('<div class="dstep">'+esc(e.text)+'</div>');
  else if(e.t==="tool")добавить('<details class="dtool"><summary><b>'+esc(e.name)+'</b> '+esc(e.arg||"")+
    (e.sec?' · '+e.sec+' с':'')+'</summary><pre>'+esc(e.out||"")+'</pre>'+
    (e.links||[]).map(u=>'<a href="'+esc(u)+'" target="_blank" rel="noopener">'+esc(u)+'</a>').join("")+'</details>');
  else if(e.t==="reply"){история.push({role:"assistant",content:e.text});сохранить();
    добавить('<div class="dmsg ai">'+esc(e.text)+'</div>')}
  else if(e.t==="тема"){
    /* Сервер понял, над кем работаем, — беседа получает его имя вместо первой фразы.
       Название «почему возраст кривой» ничего не говорит через неделю, «Рикка Таканаси» говорит. */
    const р=мои(),б=р.find(x=>x.id===текущая_id());
    if(б){б.char=e.id||б.char;if(e.name)б.title=e.name;записать_беседы(р);
      if(!$("#chatList").hidden)рисовать_список()}}
  else if(e.t==="error")добавить('<div class="dmsg err">'+esc(e.text)+'</div>');
}
/* Список стыков берём у самой студии: во вкладке «API» они уже вписаны, дублировать
   их руками в чате — верный способ разъехаться. */
const выбор={prov:П.get("prov",""),model:П.get("model","")};
let СТЫКИ=[];
function подписать(){const к=$("#chatModel");
  const коротко=имя=>{имя=String(имя||"");return имя.includes("/")?имя.split("/").pop():имя};
  к.textContent=выбор.model?коротко(выбор.model):(СТЫКИ.length?"выбрать модель":"нет ключей");
  к.title=(выбор.model?выбор.model+" · ":"")+(выбор.prov||"")+" · выбрать другую"}
function собрать_меню(){
  const м=$("#modelMenu");
  м.innerHTML=СТЫКИ.map(п=>'<div class="mgrp">'+esc(п.name||п.id)+'</div>'+
    (п.models||[]).map(мод=>'<button data-p="'+esc(п.id)+'" data-m="'+esc(мод)+'"><i>'+esc(мод)+'</i>'+
      (выбор.prov===п.id&&выбор.model===мод?'<s>✓</s>':'')+'</button>').join("")
    ||'<button data-p="'+esc(п.id)+'" data-m=""><i>по умолчанию</i></button>').join("")}
$("#chatModel").onclick=e=>{e.stopPropagation();const м=$("#modelMenu");
  if(!СТЫКИ.length)return;собрать_меню();м.hidden=!м.hidden};
$("#modelMenu").onclick=e=>{const b=e.target.closest("button");if(!b)return;
  выбор.prov=b.dataset.p;выбор.model=b.dataset.m;П.set("prov",выбор.prov);П.set("model",выбор.model);
  подписать();$("#modelMenu").hidden=true};
addEventListener("click",()=>{const м=$("#modelMenu");if(м&&!м.hidden)м.hidden=true});
живая_база().then(б=>fetch(б+"/api/keys")).then(r=>r.json()).then(d=>{
  СТЫКИ=(d&&d.providers)||[];
  // Если ничего не выбрано — берём первый вписанный стык и его первую модель, чтобы
  // не молчать и не гадать: человек сразу видит, кто отвечает.
  if(!выбор.prov&&СТЫКИ.length){выбор.prov=СТЫКИ[0].id;выбор.model=(СТЫКИ[0].models||[])[0]||"";
    П.set("prov",выбор.prov);П.set("model",выбор.model)}
  подписать();
}).catch(()=>подписать());
/* Просмотр во весь экран. Отдельным слоем поверх всего, закрывается щелчком и Escape. */
function показать_картинку(url){
  let л=$("#dockLightbox");
  if(!л){л=document.createElement("div");л.id="dockLightbox";
    л.onclick=()=>{л.remove()};document.body.appendChild(л)}
  л.innerHTML='<img src="'+url+'" alt="">';}
поток.addEventListener("click",e=>{const и=e.target.closest("img.dshot");
  if(и)показать_картинку(и.src)});

window.__ЧАТ={открыть,наВкладку};
})();
</script>`;
t = t.replace("</body>", JS + "\n</body>");
fs.writeFileSync(файл, t);
console.log("чат вшит, " + t.length);
