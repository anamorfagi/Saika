// Пол персонажа — три состояния, а не два.
// Было: male() = «пол равен мужскому». Пусто → ложь → система считала персонажа
// женщиной и присуждала Джарвису «Одзёсаму» и «Гордую аристократку».
// Стало: мужской / женский / не задан. При «не задан» типажи с полом не
// показываются вовсе — лучше меньше, чем наугад.
const fs=require("fs");
let t=fs.readFileSync("gs.html","utf8");
function rep(a,b){if(!t.includes(a)){console.error("нет якоря:",a.slice(0,70));process.exit(1)}t=t.split(a).join(b)}

rep(`const SEX=male()?"m":"f";const ranked=SIGS.map((s,i)=>({s,i,m:sigMatch(s)})).filter(r=>!r.s.sex||r.s.sex===SEX)`,
`const SEX=полПерсонажа();const ranked=SIGS.map((s,i)=>({s,i,m:sigMatch(s)})).filter(r=>!r.s.sex||(SEX&&r.s.sex===SEX))`);

// сам определитель + подпись в шапке раздела
rep(`function renderArch(){`,
`// "m" | "f" | "" — пусто значит «неизвестно», и это не то же самое, что «женский».
function полПерсонажа(){
  const g=String((CHAR&&CHAR.voice&&CHAR.voice.gender)||"").toLowerCase();
  if(/муж|male|^m$/.test(g))return "m";
  if(/жен|female|^f$/.test(g))return "f";
  return "";
}
function renderArch(){`);

rep(`<p class="lead">\${ranked.length} применимых архетипов`,
`<p class="lead">\${SEX?"":"<b style=\\"color:#cfae70\\">Пол не задан — типажи с мужским и женским признаком скрыты, чтобы не присуждать наугад. Задай пол на вкладке «Голос».</b><br>"}\${ranked.length} применимых архетипов`);

fs.writeFileSync("gs.html",t);
console.log("пол ok · архетипов с полом:",(t.match(/sex:"[fm]"/g)||[]).length);
