// Часть 2 блока «Природа агента»: для ИИ отключить половые/возрастные нормы, для людей подписать nat.* как «не применимо». Идёт после update_age.
const fs=require("fs");
let t=fs.readFileSync("gs.html","utf8");
function rep(a,b){if(!t.includes(a)){console.error("NOT FOUND:",a.slice(0,80));process.exit(1)}t=t.replace(a,b)}
// [3] для не-ИИ блок подписан «не применимо»; для ИИ не показываем половые и возрастные нормы
rep(`function normLine(G){const n=NORM[G.id];if(!n)return "";`,`function isAI(){return (CHAR.kind||"")==="ии"}
function normLine(G){if(isAI())return "";const n=NORM[G.id];if(!n)return "";`);
rep(`function ageLine(G){const a=AGE[G.id];if(!a)return "";`,`function ageLine(G){if(isAI())return "";const a=AGE[G.id];if(!a)return "";`);
rep(`function ageFromGenome(id){`,`function ageFromGenome(id){if((CHARS_META[id]||{}).kind==="ии")return null;`);
rep(`\${normLine(G)}\${ageLine(G)}`,`\${G.id.startsWith("nat.")&&!isAI()?'<div class="normline"><b>не применимо:</b> ген природы агента — у людей остаётся серым, снимается только у ИИ-компаньонов и роботов</div>':""}\${normLine(G)}\${ageLine(G)}`);
fs.writeFileSync("gs.html",t);console.log("nat2 ok");
