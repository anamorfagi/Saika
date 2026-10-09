// update_avaread.js — карточка показывает лицо, вшитое в файл персонажа.
// Было: loadAva смотрела только в браузер и в папку ava/. Удалил файлы с диска и почистил
// браузер — и персонаж, загруженный обратно из своего же файла, оставался без лица, хотя
// картинка лежит прямо в нём полем avatar. Теперь порядок такой: свежее из браузера →
// вшитое в файл персонажа → файл в ava/. Ни один источник не отменяет остальные.
// Запуск: node update_avaread.js (после update_avahard). Правит gs.html.
const fs=require("fs");let t=fs.readFileSync("gs.html","utf8");
function rep(a,b){if(!t.includes(a)){console.error("не найдено:",a.slice(0,90));process.exit(1)}t=t.replace(a,b)}

// [1] лицо из файла персонажа держим под рукой: id → data:image/…
rep(`function loadAva(id){try{const l=localStorage.getItem(avaKey(id));if(l)return l}catch(e){}return AVAFS[id]?"ava/"+encodeURIComponent(AVAFS[id]):"ava/"+id+".png"}`,
`// Лица, вшитые в файлы персонажей. Наполняется при чтении share/ и при загрузке файла.
var AVAIN={};
function rememberAva(id,data){if(id&&typeof data==="string"&&data.startsWith("data:image/"))AVAIN[String(id).toLowerCase()]=data}
function loadAva(id,card){
  try{const l=localStorage.getItem(avaKey(id));if(l)return l}catch(e){}
  const вшито=(card&&typeof card.avatar==="string"&&card.avatar.startsWith("data:image/")&&card.avatar)||AVAIN[String(id).toLowerCase()];
  if(вшито)return вшито;
  return AVAFS[id]?"ava/"+encodeURIComponent(AVAFS[id]):"ava/"+id+".png"}`);

// [2] карточка отдаёт саму себя — чтобы лицо бралось из её файла
rep(`const av=loadAva(c.id)`,`const av=loadAva(c.id,c)`);

// [3] запоминаем лицо, когда персонаж приходит из share/ или из файла
rep(`function charFromFile(obj){if(!obj||obj.format!=="saika-genome/1"||!obj.genome||!obj.meta)throw new Error("это не файл персонажа Anamorf Genom (ждём format: saika-genome/1)");`,
`function charFromFile(obj){if(!obj||obj.format!=="saika-genome/1"||!obj.genome||!obj.meta)throw new Error("это не файл персонажа Anamorf Genom (ждём format: saika-genome/1)");
  rememberAva(obj.id,obj.avatar);`);
rep(`for(const o of (window.__SHARE||[])){try{const r=charFromFile(o)`,
`for(const o of (window.__SHARE||[])){try{rememberAva(o.id,o.avatar);const r=charFromFile(o)`);
fs.writeFileSync("gs.html",t);console.log("карточка читает вшитое лицо ok");
