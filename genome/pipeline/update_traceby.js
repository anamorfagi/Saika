// Формат файла персонажа: поле meta.trace_by — реплики по id сцен вкладки «Поведение» (в дополнение к trace[0..2] для трёх первых сцен).
const fs=require("fs");let t=fs.readFileSync("gs.html","utf8");
function rep(a,b){if(!t.includes(a)){console.error("NOT FOUND:",a.slice(0,90));process.exit(1)}t=t.split(a).join(b)}
rep(`"voice","trace","ageStated","ageVoice","ageText"`,`"voice","trace","trace_by","child","ageStated","ageVoice","ageText"`);
fs.writeFileSync("gs.html",t);console.log("traceby ok");
