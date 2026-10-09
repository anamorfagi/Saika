// update_launcher_fb.js — маршрут /api/feedback: отзывы «верю / не верю» из модуля «Ассистент» пишутся строками в feedback/probe.jsonl.
// Это датасет: какая реплика, какой ответ, какие гены и чувства, и как ответил бы настоящий — по нему потом правятся гены и правила.
const fs = require("fs"), path = require("path");
const P = path.join(__dirname, "pipeline", "launcher.js");
let t = fs.readFileSync(P, "utf8");
if (t.includes('"/api/feedback"')) { console.log("уже стоит"); process.exit(0); }
const A = 'if(p==="/api/llm"&&req.method==="POST"){';
if (!t.includes(A)) throw "якорь /api/llm не найден";
const R = `if(p==="/api/feedback"&&req.method==="POST"){let body="";req.on("data",d=>body+=d);req.on("end",()=>{try{JSON.parse(body);const d=path.join(ROOT,"feedback");fs.mkdirSync(d,{recursive:true});
    fs.appendFileSync(path.join(d,"probe.jsonl"),body.replace(/\\n/g," ")+"\\n");res.writeHead(200,{"Content-Type":"application/json"});res.end('{"ok":true}')}catch(e){res.writeHead(400);res.end(e.message)}});return}
  `;
t = t.replace(A, R + A);
fs.writeFileSync(P, t); console.log("ok: /api/feedback");
