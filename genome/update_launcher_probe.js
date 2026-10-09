// update_launcher_probe.js — /api/llm берёт ключ с сервера, если страница его не прислала.
// Зачем: ключи живут в api_keys.json (их видит чат-панель), а вкладка API в браузере может быть пустой —
// тогда модуль «Ассистент» не мог бы ответить. Теперь достаточно имени провайдера.
const fs = require("fs"), path = require("path");
const P = path.join(__dirname, "pipeline", "launcher.js");
let t = fs.readFileSync(P, "utf8");
if (t.includes("function serverKey(")) { console.log("уже стоит"); process.exit(0); }
const A = 'if(p==="/api/llm"&&req.method==="POST"){let body="";req.on("data",d=>body+=d);req.on("end",async()=>{try{const q=JSON.parse(body);';
if (!t.includes(A)) throw "якорь /api/llm не найден";
t = t.replace(A, A + "serverKey(q);");
const fn = `
// ключ провайдера из api_keys.json (корень или pipeline/), если страница прислала только имя провайдера
function serverKey(q){if(q.key)return q;for(const ф of [path.join(ROOT,"api_keys.json"),path.join(ROOT,"pipeline","api_keys.json")]){
  try{if(!fs.existsSync(ф))continue;const д=JSON.parse(fs.readFileSync(ф,"utf8"));for(const ветка of [д,д.keys||{}]){const з=ветка&&ветка[q.provider];if(!з)continue;
    q.key=typeof з==="string"?з:з.key;if(!q.base&&typeof з==="object"&&з.base)q.base=з.base;if(!q.auth)q.auth="bearer";return q}}catch(e){}}return q}
`;
const k = t.indexOf("async function llm(");
t = t.slice(0, k) + fn + t.slice(k);
fs.writeFileSync(P, t); console.log("ok: serverKey в /api/llm");
