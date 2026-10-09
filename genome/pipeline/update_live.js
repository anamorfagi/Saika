// Живая перезагрузка: рядом с html лежит ver.js (window.__BUILD="метка сборки").
// Страница раз в 2 с подтягивает ver.js?t=… тегом <script> (работает и с file://, и с localhost),
// и если метка изменилась — перезагружается сама. Больше не нужно жать F5 после моей записи файла.
const fs=require("fs");
let t=fs.readFileSync("gs.html","utf8");
const BUILD=new Date().toISOString().replace(/[-:T]/g,"").slice(0,14);
const code=`<script>var __BUILD0=null;(function(){function chk(){var s=document.createElement("script");s.src="ver.js?t="+Date.now();s.onload=function(){s.remove();if(__BUILD0===null)__BUILD0=window.__BUILD;else if(window.__BUILD&&window.__BUILD!==__BUILD0){try{saveState&&saveState({})}catch(e){}location.reload()}};s.onerror=function(){s.remove()};document.head.appendChild(s)}chk();setInterval(chk,2000)})();</script>`;
if(!t.includes("ver.js?t=")){t=t.replace("</body>",code+"</body>")}
fs.writeFileSync("gs.html",t);
fs.writeFileSync("ver.js",`window.__BUILD="${BUILD}";`);
console.log("live ok",BUILD);
