// Anamorf Genom — запускатель: поднимает локальный сервер рядом с exe и открывает браузер.
// Так страница живёт на http://localhost — запросы к моделям и файлы работают надёжнее, чем с диска.
const http=require("http"),fs=require("fs"),path=require("path"),{exec}=require("child_process");
// Где корень проекта. Из exe — папка рядом с exe. Запущен как обычный скрипт
// (node pipeline/launcher.js) — корнем была бы сама pipeline\, и страница не находилась:
// «Нет такого: /genome-studio.html». Поэтому в режиме скрипта поднимаемся на уровень выше,
// если страница лежит там. 2026-09-18.
const ROOT=(()=>{
  const script=process.execPath.endsWith("node")||process.execPath.endsWith("node.exe");
  if(!script)return path.dirname(process.execPath);
  const here=path.dirname(__filename), up=path.dirname(here);
  const has=d=>fs.existsSync(path.join(d,"genome-studio.html"))||fs.existsSync(path.join(d,"app","genome-studio.html"));
  return has(here)?here:(has(up)?up:here);
})();
const MIME={".html":"text/html; charset=utf-8",".json":"application/json; charset=utf-8",".js":"text/javascript; charset=utf-8",".css":"text/css; charset=utf-8",".png":"image/png",".jpg":"image/jpeg",".svg":"image/svg+xml",".md":"text/plain; charset=utf-8",".txt":"text/plain; charset=utf-8"};
const PORT=+process.env.PORT||8765;
// журнал рядом с exe и удержание окна при ошибке — чтобы сбой было видно, а не «мигнуло и исчезло»
const LOG=path.join(ROOT,"anamorf-genom.log");const log=s=>{try{fs.appendFileSync(LOG,new Date().toISOString()+" "+s+"\n")}catch(e){}console.log(s)};
const hold=()=>{console.log("\nНажми Enter, чтобы закрыть.");try{process.stdin.resume();process.stdin.on("data",()=>process.exit(1))}catch(e){setTimeout(()=>process.exit(1),30000)}};
process.on("uncaughtException",e=>{log("ОШИБКА: "+(e&&e.stack||e));hold()});
log("старт · node "+process.version+" · "+process.platform+" · exe="+process.execPath+" · папка="+ROOT);
if(!fs.existsSync(path.join(ROOT,"genome-studio.html"))&&!fs.existsSync(path.join(ROOT,"app","genome-studio.html"))){log("рядом с exe нет app/genome-studio.html — положи exe в папку AnamorfGenom");hold()}
const SHARE=path.join(ROOT,"share"),AVA=path.join(ROOT,"ava");const SCOUTS={};   // разведки: id → журнал
const APP=fs.existsSync(path.join(ROOT,"app","genome-studio.html"))?path.join(ROOT,"app"):ROOT;   // страница лежит в app/, корень — только exe
// share/index.js — список персонажей для страницы (без аватаров); пересобирается при старте, после сохранения и удаления
function shareList(){try{fs.mkdirSync(SHARE,{recursive:true})}catch(e){}const L=[];for(const f of fs.readdirSync(SHARE).filter(f=>f.endsWith(".genome.json")).sort()){try{const o=JSON.parse(fs.readFileSync(path.join(SHARE,f),"utf8"));if(o.format!=="saika-genome/1")continue;
    // Аватар из СПИСКА вырезаем (2026-09-18, вторая попытка). Первый заход оставил его
    // внутри — список распух с 719 КБ до 1.1 МБ, браузер упёрся в предел хранилища и
    // молча выбросил тяжёлых персонажей: на странице осталось 4 из 11. Лицо берётся из
    // ava/<id>.jpg, а внутри файла персонажа остаётся для переноса на другую машину.
    delete o.avatar;L.push(o)}catch(e){log("share/"+f+": "+e.message)}}return L}
// share/_list.js — служебный список для открытия html с диска; exe пишет его при старте, после сохранения и удаления (и отдаёт из памяти по /share/_list.js)
function genIndex(){try{const L=shareList();fs.writeFileSync(path.join(SHARE,"_list.js"),"// служебный список персонажей для открытия html с диска — генерируется автоматически\nwindow.__SHARE="+JSON.stringify(L)+";\n");log("share/_list.js: "+L.length+" персонажей")}catch(e){log("share/_list.js: "+e.message)}}
try{const old=path.join(SHARE,"index.js");if(fs.existsSync(old)){fs.unlinkSync(old);log("убран устаревший share/index.js")}}catch(e){}
genIndex();
// удаление: файл и аватар переезжают в _trash (не стираются), чтобы ошибочное удаление можно было вернуть
function trash(id){const ts=new Date().toISOString().replace(/[-:T]/g,"").slice(0,14);const moved=[];const T1=path.join(SHARE,"_trash"),T2=path.join(AVA,"_trash");
  const f=path.join(SHARE,id+".genome.json");if(fs.existsSync(f)){fs.mkdirSync(T1,{recursive:true});fs.renameSync(f,path.join(T1,id+"."+ts+".genome.json"));moved.push("share/_trash/"+id+"."+ts+".genome.json")}
  if(fs.existsSync(AVA))for(const a of fs.readdirSync(AVA)){if(a.replace(/\.[^.]+$/,"")===id&&fs.statSync(path.join(AVA,a)).isFile()){fs.mkdirSync(T2,{recursive:true});fs.renameSync(path.join(AVA,a),path.join(T2,ts+"."+a));moved.push("ava/_trash/"+ts+"."+a)}}
  genIndex();return moved}
// аватар из файла персонажа (data:URL) → ava/<id>.<расширение>, чтобы картинка жила файлом рядом с exe
function saveAva(id,dataUrl){const m=/^data:image\/(png|jpe?g|webp|gif);base64,(.+)$/i.exec(dataUrl||"");if(!m)return null;fs.mkdirSync(AVA,{recursive:true});const ext=m[1].toLowerCase().replace("jpeg","jpg");const f=id+"."+ext;fs.writeFileSync(path.join(AVA,f),Buffer.from(m[2],"base64"));return f}

// ---------- сеть для страницы: модели и корпус ----------
const https=require("https");
function reqJSON(url,{method="GET",headers={},body,insecure}={}){return new Promise((ok,bad)=>{const u=new URL(url);const r=https.request({hostname:u.hostname,port:u.port||443,path:u.pathname+u.search,method,headers,rejectUnauthorized:!insecure},res=>{let d="";res.on("data",c=>d+=c);res.on("end",()=>ok({status:res.statusCode,text:d}))});r.on("error",bad);if(body)r.write(body);r.end()})}
// GigaChat: OAuth по ключу (Basic), токен живёт ~30 мин; сертификат Минцифры не в доверенных node → insecure только для *.sberbank.ru
const GC={tok:null,exp:0};
async function gigaToken(key){if(GC.tok&&Date.now()<GC.exp-60000)return GC.tok;const r=await reqJSON("https://ngw.devices.sberbank.ru:9443/api/v2/oauth",{method:"POST",headers:{"Content-Type":"application/x-www-form-urlencoded",Accept:"application/json",RqUID:require("crypto").randomUUID(),Authorization:"Basic "+key},body:"scope=GIGACHAT_API_PERS",insecure:true});
  if(r.status!==200)throw new Error("GigaChat OAuth "+r.status+": "+r.text.slice(0,120));const d=JSON.parse(r.text);GC.tok=d.access_token;GC.exp=+d.expires_at||Date.now()+1700000;return GC.tok}
// один вызов модели: {provider,auth,base,model,key,system,user,max_tokens} → {text,tok}

// ключ провайдера из api_keys.json (корень или pipeline/), если страница прислала только имя провайдера
function serverKey(q){if(q.key)return q;for(const ф of [path.join(ROOT,"api_keys.json"),path.join(ROOT,"pipeline","api_keys.json")]){
  try{if(!fs.existsSync(ф))continue;const д=JSON.parse(fs.readFileSync(ф,"utf8"));for(const ветка of [д,д.keys||{}]){const з=ветка&&ветка[q.provider];if(!з)continue;
    q.key=typeof з==="string"?з:з.key;if(!q.base&&typeof з==="object"&&з.base)q.base=з.base;if(!q.auth)q.auth="bearer";return q}}catch(e){}}return q}
async function llm(q){const msgs=[{role:"system",content:q.system},{role:"user",content:q.user}];const h={"Content-Type":"application/json"};let url,body,insecure=false;
  if(q.auth==="gigachat"){h.Authorization="Bearer "+await gigaToken(q.key);url="https://gigachat.devices.sberbank.ru/api/v1/chat/completions";body={model:q.model||"GigaChat-2-Pro",temperature:.1,max_tokens:q.max_tokens,messages:msgs};insecure=true}
  else if(q.auth==="x-api-key"){h["x-api-key"]=q.key;h["anthropic-version"]="2023-06-01";url=q.base+"/messages";body={model:q.model,max_tokens:q.max_tokens,temperature:.1,system:q.system,messages:[{role:"user",content:q.user}]}}
  else{if(q.auth==="bearer"&&q.key)h.Authorization=(q.provider==="yandex"?"Api-Key ":"Bearer ")+q.key;url=q.base+"/chat/completions";body={model:q.model,temperature:.1,max_tokens:q.max_tokens,messages:msgs};if(q.reasoning)body.reasoning_effort=q.reasoning}   // "none" — без скрытых рассуждений (быстрее в разы)
  const r=await reqJSON(url,{method:"POST",headers:h,body:JSON.stringify(body),insecure});if(r.status<200||r.status>=300)throw new Error("HTTP "+r.status+": "+r.text.slice(0,200));const d=JSON.parse(r.text);
  const text=Array.isArray(d.content)?d.content.map(x=>x.text||"").join(""):d.choices[0].message.content;const u=d.usage||{};return {text,tok:(u.prompt_tokens||u.input_tokens||0)+(u.completion_tokens||u.output_tokens||0)}}
// корпус из сети: Википедия ru + en (поиск → полный текст статьи), плюс fandom через поиск не трогаем — только открытые API
async function corpus(q){const out=[];for(const lang of ["ru","en"]){try{const s=await reqJSON(`https://${lang}.wikipedia.org/w/api.php?action=query&list=search&srsearch=${encodeURIComponent(q)}&srlimit=3&format=json`,{headers:{"User-Agent":"AnamorfGenom/1.0"}});const hits=(JSON.parse(s.text).query||{}).search||[];
    for(const hgt of hits.slice(0,2)){const e=await reqJSON(`https://${lang}.wikipedia.org/w/api.php?action=query&prop=extracts&explaintext=1&titles=${encodeURIComponent(hgt.title)}&format=json`,{headers:{"User-Agent":"AnamorfGenom/1.0"}});const pages=(JSON.parse(e.text).query||{}).pages||{};for(const k in pages){const tx=pages[k].extract||"";if(tx.length>800)out.push({title:hgt.title,lang,len:tx.length,text:tx})}}}catch(e){log("corpus "+lang+": "+e.message)}}
  return out}
http.createServer((req,res)=>{
  let p=decodeURIComponent(req.url.split("?")[0]);if(p==="/")p="/genome-studio.html";
  // папка share/ — персонажи, общие для всех браузеров на этой машине: список, чтение, сохранение
  if(p==="/share/_list.js"||p==="/share/index.js"){res.writeHead(200,{"Content-Type":"text/javascript","Cache-Control":"no-cache"});res.end("window.__SHARE="+JSON.stringify(shareList())+";");return}
  // теги внешности по картинке: data:URL → временный файл → python pipeline/tagger.py (WD14, модель скачивается один раз в models/)
  // разведчик: имя + откуда → python pipeline/scout.py → папка chars/<id>/ с материалами; журнал отдаётся панели по запросу
  // приёмник материалов: папка на диске → python pipeline/ingest.py → chars/<id>/corpus.txt; журнал как у разведки (/api/scout/<id>)
  if(p==="/api/ingest"&&req.method==="POST"){let body="";req.on("data",d=>body+=d);req.on("end",()=>{try{const {folder,id,lang}=JSON.parse(body);if(!folder||!fs.existsSync(folder))throw new Error("папка не найдена: "+folder);const cid=String(id||"").replace(/[^a-z0-9_]/g,"")||("p"+Date.now());
      const script=fs.existsSync(path.join(ROOT,"pipeline","ingest.py"))?path.join(ROOT,"pipeline","ingest.py"):path.join(APP,"pipeline","ingest.py");const outDir=path.join(ROOT,"chars",cid);fs.mkdirSync(outDir,{recursive:true});
      const job={id:cid,lines:[],done:false,result:null,started:Date.now()};SCOUTS[cid]=job;const py=[["py",["-3"]],["python",[]],["python3",[]]];
      const start=i=>{if(i>=py.length){job.lines.push({stage:"error",msg:"python не найден"});job.done=true;return}const [cmd,pre]=py[i];const {spawn}=require("child_process");let started=false,next=false;
        const pr=spawn(cmd,[...pre,"-u",script,folder,"--out",outDir,"--lang",lang||"rus"],{windowsHide:true});let buf="";
        pr.stdout.on("data",d=>{started=true;buf+=d.toString("utf8");let k;while((k=buf.indexOf("\n"))>=0){const line=buf.slice(0,k).trim();buf=buf.slice(k+1);if(!line)continue;try{const j=JSON.parse(line);job.lines.push(j);if(j.stage==="done"||j.stage==="error")job.result=j}catch(e){job.lines.push({stage:"log",msg:line})}}});
        pr.stderr.on("data",d=>{const s=d.toString("utf8").trim();if(s)job.lines.push({stage:"stderr",msg:s.slice(-300)})});
        pr.on("error",e=>{if(!started&&!next){next=true;start(i+1)}else if(started){job.lines.push({stage:"error",msg:e.message});job.done=true}});
        pr.on("close",code=>{if(next)return;if(!started&&code!==0&&i+1<py.length){next=true;return start(i+1)}job.done=true;log("ingest "+cid+": код "+code)})};
      start(0);res.writeHead(200,{"Content-Type":"application/json"});res.end(JSON.stringify({ok:true,id:cid}))}catch(e){res.writeHead(400);res.end(JSON.stringify({error:e.message}))}});return}
  if(p==="/api/scout"&&req.method==="POST"){let body="";req.on("data",d=>body+=d);req.on("end",()=>{try{const {name,origin,kind,id}=JSON.parse(body);if(!name)throw new Error("нет имени");const cid=String(id||"").replace(/[^a-z0-9_]/g,"")||("p"+Date.now());
      const script=fs.existsSync(path.join(ROOT,"pipeline","scout.py"))?path.join(ROOT,"pipeline","scout.py"):path.join(APP,"pipeline","scout.py");const outDir=path.join(ROOT,"chars",cid);fs.mkdirSync(outDir,{recursive:true});
      const job={id:cid,lines:[],done:false,result:null,started:Date.now()};SCOUTS[cid]=job;const py=[["py",["-3"]],["python",[]],["python3",[]]];
      const start=i=>{if(i>=py.length){job.lines.push({stage:"error",msg:"python не найден — установи Python 3 (и pip install yt-dlp faster-whisper для аудио)"});job.done=true;return}
        const [cmd,pre]=py[i];const {spawn}=require("child_process");let started=false;const pr=spawn(cmd,[...pre,"-u",script,"--name",name,"--origin",origin||"","--kind",kind||"человек","--out",outDir],{windowsHide:true});
        let buf="";pr.stdout.on("data",d=>{started=true;buf+=d.toString("utf8");let k;while((k=buf.indexOf("\n"))>=0){const line=buf.slice(0,k).trim();buf=buf.slice(k+1);if(!line)continue;try{const j=JSON.parse(line);job.lines.push(j);if(j.stage==="done"||j.stage==="stop"||j.stage==="error")job.result=j}catch(e){job.lines.push({stage:"log",msg:line})}}});
        pr.stderr.on("data",d=>{const s=d.toString("utf8").trim();if(s)job.lines.push({stage:"stderr",msg:s.slice(-300)})});
        let next=false;pr.on("error",e=>{if(!started&&!next){next=true;start(i+1)}else if(started){job.lines.push({stage:"error",msg:e.message});job.done=true}});
        pr.on("close",code=>{if(next)return;if(!started&&code!==0&&i+1<py.length){next=true;return start(i+1)}job.done=true;log("scout "+cid+": код "+code)})};
      start(0);res.writeHead(200,{"Content-Type":"application/json"});res.end(JSON.stringify({ok:true,id:cid}))}catch(e){res.writeHead(400);res.end(JSON.stringify({error:e.message}))}});return}
  if(p.startsWith("/api/scout/")&&req.method==="GET"){const parts=p.split("/");const cid=parts[3].replace(/[^a-z0-9_]/g,"");const job=SCOUTS[cid];
    if(parts[4]==="corpus"){const f=path.join(ROOT,"chars",cid,"corpus.txt");if(!fs.existsSync(f)){res.writeHead(404);res.end("нет корпуса");return}res.writeHead(200,{"Content-Type":"text/plain; charset=utf-8"});fs.createReadStream(f).pipe(res);return}
    if(!job){res.writeHead(404,{"Content-Type":"application/json"});res.end(JSON.stringify({error:"нет такой разведки"}));return}
    const from=+(new URL(req.url,"http://x").searchParams.get("from")||0);res.writeHead(200,{"Content-Type":"application/json"});res.end(JSON.stringify({lines:job.lines.slice(from),next:job.lines.length,done:job.done,result:job.result}));return}
  if(p==="/api/tags"&&req.method==="POST"){let body="";req.on("data",d=>body+=d);req.on("end",()=>{try{const {image}=JSON.parse(body);const m=/^data:image\/(png|jpe?g|webp);base64,(.+)$/i.exec(image||"");if(!m)throw new Error("нет картинки");
      const tmp=path.join(require("os").tmpdir(),"ag_tag."+m[1].replace("jpeg","jpg"));fs.writeFileSync(tmp,Buffer.from(m[2],"base64"));
      const py=[["py",["-3"]],["python",[]],["python3",[]]];const script=fs.existsSync(path.join(ROOT,"pipeline","tagger.py"))?path.join(ROOT,"pipeline","tagger.py"):path.join(APP,"pipeline","tagger.py");
      const tryRun=i=>{if(i>=py.length){res.writeHead(500,{"Content-Type":"application/json"});res.end(JSON.stringify({error:"python не найден — установи Python 3 и pip install onnxruntime pillow numpy"}));return}
        const [cmd,pre]=py[i];const {execFile}=require("child_process");execFile(cmd,[...pre,script,tmp],{maxBuffer:1e7,timeout:600000},(err,out,errout)=>{if(err&&!out){log("tagger "+cmd+": "+(errout||err.message).slice(0,200));return tryRun(i+1)}
          log("tagger: "+out.slice(0,120).replace(/\s+/g," "));res.writeHead(200,{"Content-Type":"application/json"});res.end(out||JSON.stringify({error:errout.slice(0,300)}))})};tryRun(0)}catch(e){res.writeHead(400);res.end(JSON.stringify({error:e.message}))}});return}

  // карта стыков: что реально открывается с этой машины. Числа настоящие — их считает pipeline/probe.py
  // Страница, открытая файлом (file://), — другой источник для браузера, и без этих
  // заголовков её запросы к лаунчеру отбиваются молча. Сервер слушает только 127.0.0.1,
  // снаружи к нему всё равно никто не достучится. 2026-09-18.
  res.setHeader("Access-Control-Allow-Origin","*");
  res.setHeader("Access-Control-Allow-Headers","Content-Type");
  res.setHeader("Access-Control-Allow-Methods","GET, POST, OPTIONS");
  if(req.method==="OPTIONS"){res.writeHead(204);res.end();return}

  if(p==="/api/probe"&&req.method==="GET"){
    const only=(new URL(req.url,"http://x").searchParams.get("id")||"").replace(/[^a-z0-9_,]/g,"");
    const script=fs.existsSync(path.join(ROOT,"pipeline","probe.py"))?path.join(ROOT,"pipeline","probe.py"):path.join(APP,"pipeline","probe.py");
    const py=[["py",["-3"]],["python",[]],["python3",[]]];
    const run=i=>{if(i>=py.length){res.writeHead(500,{"Content-Type":"application/json"});res.end(JSON.stringify({error:"python не найден — установи Python 3"}));return}
      const [cmd,pre]=py[i];const {execFile}=require("child_process");
      const args=[...pre,script,"--json","--timeout","10"];if(only)args.push("--id",...only.split(","));
      execFile(cmd,args,{maxBuffer:1e7,timeout:180000},(err,out,errout)=>{
        if(!out||!out.trim().startsWith("[")){log("probe "+cmd+": "+(errout||(err&&err.message)||"пусто").slice(0,200));return run(i+1)}
        res.writeHead(200,{"Content-Type":"application/json; charset=utf-8"});res.end(out)})};
    run(0);return}
  // ключи владельца: обычный текстовый файл рядом со студией, который открывается блокнотом.
  // Каноничный вид хранится в api_keys.json, текст перерисовывается из него целиком —
  // так один и тот же провайдер не задваивается, а старый ключ честно заменяется новым.
  if(p==="/api/keys"&&req.method==="POST"){let body="";req.on("data",d=>body+=d);req.on("end",()=>{
    try{
      const q=JSON.parse(body||"{}");
      const id=String(q.id||"").replace(/[^a-z0-9_]/g,"");
      const key=String(q.key||"").trim();
      if(!id||key.length<8||key.length>400)throw new Error("Нужен id стыка и ключ");
      const jsonFile=path.join(ROOT,"api_keys.json"), txtFile=path.join(ROOT,"API_KEYS.txt");
      let bag={};try{bag=JSON.parse(fs.readFileSync(jsonFile,"utf8"))}catch(e){}
      bag[id]={name:String(q.name||id),base:String(q.base||""),key,at:new Date().toISOString().slice(0,16).replace("T"," ")};
      fs.writeFileSync(jsonFile,JSON.stringify(bag,null,1));
      let s="# Ключи API — Anamorf Genom\r\n# Здесь только то, что вписано вручную в студии. Файл никуда не отправляется.\r\n\r\n";
      for(const k of Object.keys(bag).sort()){const v=bag[k];
        s+="["+v.name+"]  "+k+"\r\nадрес:   "+(v.base||"—")+"\r\nключ:    "+v.key+"\r\nдобавлен: "+v.at+"\r\n\r\n"}
      fs.writeFileSync(txtFile,s,"utf8");
      log("ключ сохранён: "+id+" → API_KEYS.txt");
      res.writeHead(200,{"Content-Type":"application/json"});res.end(JSON.stringify({ok:true,file:"API_KEYS.txt",total:Object.keys(bag).length}));
    }catch(e){res.writeHead(400,{"Content-Type":"application/json"});res.end(JSON.stringify({error:e.message}))}});return}
  // один ключ → кто его принимает. Перебираются только стыки, подходящие по виду ключа; ключ никуда не логируется
  if(p==="/api/keyfind"&&req.method==="POST"){let body="";req.on("data",d=>body+=d);req.on("end",async()=>{
    try{
      const q=JSON.parse(body||"{}");const key=String(q.key||"").trim();
      if(key.length<8||key.length>400)throw new Error("Похоже, это не ключ");
      const cat=JSON.parse(fs.readFileSync(fs.existsSync(path.join(ROOT,"pipeline","providers.json"))?path.join(ROOT,"pipeline","providers.json"):path.join(APP,"pipeline","providers.json"),"utf8")).providers;
      const hint=[["sk-aitunnel","aitunnel"],["sk-or-v1","openrouter"],["sk-ant","anthropic"],["sk-proj","openai"],["sk-svcacct","openai"],["gsk_","groq"],["xai-","xai"],["csk-","cerebras"],["nvapi-","nebius"],["fw_","fireworks"],["pplx-","perplexity"]];
      const named=(hint.find(([pre])=>key.startsWith(pre))||[])[1];
      const order=cat.filter(x=>x.id!=="custom"&&x.auth!=="none"&&x.auth!=="gigachat"&&!String(x.base).includes("{"))
                     .sort((a,b)=>(b.id===named)-(a.id===named)||(b.grp==="ru_agg")-(a.grp==="ru_agg"));
      const tried=[];
      for(const pr of (named?order.slice(0,10):order.slice(0,14))){
        const base=String(pr.base).replace(/\/$/,"");
        const h={"Content-Type":"application/json"};
        if(pr.auth==="raw")h.Authorization=key;else if(pr.auth==="x-api-key"){h["x-api-key"]=key;h["anthropic-version"]="2023-06-01"}else h.Authorization="Bearer "+key;
        try{
          const ctl=new AbortController();const to=setTimeout(()=>ctl.abort(),9000);
          const r=await fetch(base+"/models",{headers:h,signal:ctl.signal});clearTimeout(to);
          if(r.status===200){
            let models=[];try{const d=await r.json();models=(d.data||d.models||[]).map(m=>m.id||m.name).filter(Boolean)}catch(e){}
            res.writeHead(200,{"Content-Type":"application/json"});
            res.end(JSON.stringify({provider:pr.id,name:pr.name,base:pr.base,models:models.slice(0,400),tried}));return}
          tried.push({id:pr.id,status:r.status});
        }catch(e){tried.push({id:pr.id,status:String(e.message||e).slice(0,60)})}
      }
      res.writeHead(200,{"Content-Type":"application/json"});res.end(JSON.stringify({provider:"",tried}));
    }catch(e){res.writeHead(400,{"Content-Type":"application/json"});res.end(JSON.stringify({error:e.message}))}});return}
  if(p==="/api/feedback"&&req.method==="POST"){let body="";req.on("data",d=>body+=d);req.on("end",()=>{try{JSON.parse(body);const d=path.join(ROOT,"feedback");fs.mkdirSync(d,{recursive:true});
    fs.appendFileSync(path.join(d,"probe.jsonl"),body.replace(/\n/g," ")+"\n");res.writeHead(200,{"Content-Type":"application/json"});res.end('{"ok":true}')}catch(e){res.writeHead(400);res.end(e.message)}});return}
  if(p==="/api/llm"&&req.method==="POST"){let body="";req.on("data",d=>body+=d);req.on("end",async()=>{try{const q=JSON.parse(body);serverKey(q);const r=await llm(q);res.writeHead(200,{"Content-Type":"application/json"});res.end(JSON.stringify(r))}catch(e){log("llm: "+e.message);res.writeHead(502,{"Content-Type":"application/json"});res.end(JSON.stringify({error:e.message}))}});return}
  if(p==="/api/corpus"){const q=new URL(req.url,"http://x").searchParams.get("q")||"";corpus(q).then(src=>{const text=src.map(s=>"## "+s.title+" ("+s.lang+")\n\n"+s.text).join("\n\n");log("corpus «"+q+"»: "+src.length+" статей, "+text.length+" символов");res.writeHead(200,{"Content-Type":"application/json"});res.end(JSON.stringify({ok:src.length>0,error:src.length?"":"в Википедии ничего не нашлось — вставь корпус вручную",text,sources:src.map(({title,lang,len})=>({title,lang,len}))}))}).catch(e=>{res.writeHead(500);res.end(JSON.stringify({ok:false,error:e.message}))});return}
  if(p==="/api/chars"&&req.method==="GET"){try{fs.mkdirSync(SHARE,{recursive:true})}catch(e){}const L=fs.readdirSync(SHARE).filter(f=>f.endsWith(".genome.json"));res.writeHead(200,{"Content-Type":"application/json"});res.end(JSON.stringify(L));return}
  if(p.startsWith("/api/avas/")&&req.method==="POST"){const id=decodeURIComponent(p.slice(10)).toLowerCase().replace(/[^a-z0-9_]/g,"");let body="";req.on("data",d=>body+=d);req.on("end",()=>{try{const m=/^data:image\/[a-z]+;base64,(.+)$/s.exec(body);if(!id||!m)throw new Error("bad");fs.mkdirSync(AVA,{recursive:true});for(const ext of ["png","webp","gif"]){try{fs.unlinkSync(path.join(AVA,id+"."+ext))}catch(e){}}fs.writeFileSync(path.join(AVA,id+".jpg"),Buffer.from(m[1],"base64"));
      // КАРТИНКА ВШИВАЕТСЯ В ФАЙЛ ПЕРСОНАЖА (2026-09-18). Раньше она ложилась только
      // в ava/<id>.jpg, а share/<id>.genome.json оставался со старым аватаром или без
      // него: файл персонажа переносишь на другую машину — лицо теряется. Теперь
      // последняя загруженная картинка сразу становится частью персонажа.
      let вшито=false;
      try{const f=path.join(SHARE,id+".genome.json");
        if(fs.existsSync(f)){const o=JSON.parse(fs.readFileSync(f,"utf8"));
          o.avatar=body;fs.writeFileSync(f,JSON.stringify(o,null,2));genIndex();вшито=true;
          log("аватар вшит в share/"+id+".genome.json ("+Math.round(body.length/1024)+" КБ)")}
      }catch(e){log("аватар в файл персонажа не вшился: "+e.message)}
      res.writeHead(200,{"Content-Type":"application/json"});res.end(JSON.stringify({ok:true,file:id+".jpg",embedded:вшито}))}catch(e){res.writeHead(400);res.end("bad image")}});return}
  if(p==="/api/avas"){try{fs.mkdirSync(AVA,{recursive:true})}catch(e){}const L=fs.readdirSync(AVA).filter(f=>/\.(png|jpe?g|webp|gif)$/i.test(f));res.writeHead(200,{"Content-Type":"application/json"});res.end(JSON.stringify(L));return}
  if(p.startsWith("/api/chars/")&&req.method==="DELETE"){const id=p.slice(11).replace(/[^a-z0-9_]/g,"");const moved=trash(id);log("удалён "+id+" → "+moved.join(", "));res.writeHead(200,{"Content-Type":"application/json"});res.end(JSON.stringify({ok:true,moved:moved.join(", ")}));return}
  // ЧАТ. Поток, а не «подожди минуту в тишине»: stdout питона (NDJSON) льётся в ответ
  // как есть, студия читает его построчно и показывает каждый шаг агента.
  // Корректная остановка по просьбе с этой же машины. Понадобилось после того, как
  // перезапуск упёрся в права: taskkill отказал («Отказано в доступе»), и студия осталась
  // на старом коде. Процесс, который умеет завершаться сам, снимать правами не нужно.
  if(p==="/api/quit"&&req.method==="POST"){res.writeHead(200,{"Content-Type":"application/json"});
    res.end(JSON.stringify({ok:true}));log("остановка по запросу /api/quit");
    setTimeout(()=>process.exit(0),250);return}
  // Какие стыки вписаны во вкладке «API» — без самих ключей наружу. Нужно, чтобы в чате
  // можно было выбрать, кем отвечать, не уходя в настройки и не угадывая имена.
  if(p==="/api/keys"&&req.method==="GET"){let список=[];
    for(const ф of [path.join(ROOT,"api_keys.json"),path.join(ROOT,"pipeline","api_keys.json")]){
      try{if(!fs.existsSync(ф))continue;const д=JSON.parse(fs.readFileSync(ф,"utf8"));
        for(const ветка of [д,д.keys||{}])for(const [имя,зн] of Object.entries(ветка||{})){
          if(!зн||typeof зн!=="object"&&typeof зн!=="string")continue;
          const ключ=typeof зн==="string"?зн:(зн.key||"");
          if(typeof ключ!=="string"||ключ.trim().length<13)continue;
          if(список.some(x=>x.id===имя))continue;
          список.push({id:имя,name:(typeof зн==="object"&&зн.name)||имя,base:(typeof зн==="object"&&зн.base)||"",models:[]})}
      }catch(e){}}
    // К каждому стыку — его модели из каталога: выбирать модель надо из живого списка,
    // а не вписывать имя руками и гадать, есть ли такая.
    try{const кат=JSON.parse(fs.readFileSync(path.join(ROOT,"pipeline","providers.json"),"utf8"));
      for(const p of список){const к=(кат.providers||[]).find(x=>x.id===p.id);if(к&&Array.isArray(к.models))p.models=к.models}
    }catch(e){}
    res.writeHead(200,{"Content-Type":"application/json"});res.end(JSON.stringify({providers:список}));return}
  // Пинг маршрута: по нему страница понимает, что попала в живую студию, а не во вкладку
  // от прежнего запуска, где чата ещё нет.
  // ---- учебный блок: когда анализ персонажа ЗАВЕРШЁН ----
  // Не когда «процесс закончился», а когда пройдены все этапы: источники с его речью найдены, геном разобран
  // (половина генов или каждый блок хоть на треть), улики проверены после последнего разбора, все предложения
  // проверки решены владельцем, есть 5+ настоящих реплик, голос и собранный промпт. Каждый этап — с цифрой.
  // ---- учебный блок: прогресс по журналу ----
  // Движок анализа пишет события: распознавание → поиск источников → книга/манга/серии → разбор сцен (Разобрано a/b)
  // → добор пробелов → сверка противоречий → описание → готово. Этап = самое позднее из встреченных;
  // внутри разбора прогресс = разобрано/всего запросов; «осталось» = оставшиеся запросы × средняя скорость + ~2 мин на хвост.
  const ЭТАПЫ=[["распознавание",["queued","identify","identity"]],["поиск источников",["sources","search","think","candidate","fetch","source","source_error","rejected","budget"]],
    ["разбор сцен",["coverage","analyze","evidence","model_check"]],["добор пробелов",["gaps","plan"]],["сверка противоречий",["contradiction"]],["описание",["profile"]],["готово",["card","done"]]];
  function этап_анализа(ev){let n=0;const t0=ev.length?Date.parse(ev[0].at):0;
    ev.forEach(e=>{const i=ЭТАПЫ.findIndex(x=>x[1].includes(e.stage));if(i>n&&!(i===3&&e.stage==="plan"&&n<2))n=i});
    let внутри="",доля=0,осталось=null;
    if(n===1){const шаги=ev.filter(e=>e.stage==="think"||e.stage==="search").length;доля=Math.min(1,шаги/30);внутри="шагов поиска "+шаги}
    if(n===2||n===3){let всего=0,сделано=0;const ан=ev.filter(e=>e.stage==="analyze");
      ан.forEach(e=>{const m=/Разбор источника: (\d+) запрос/.exec(e.message||"");if(m)всего+=+m[1]});
      сделано=ев_разобрано(ан);if(всего){доля=Math.min(1,сделано/всего);внутри="разобрано "+сделано+" из "+всего+" запросов";
        const первые=ан.find(e=>/Разобрано/.test(e.message||"")),последние=[...ан].reverse().find(e=>/Разобрано/.test(e.message||""));
        if(первые&&последние&&сделано>1){const сек=(Date.parse(последние.at)-Date.parse(первые.at))/1000/Math.max(1,сделано-1);осталось=Math.round(((всего-сделано)*сек+120)/60)}}}
    const проц=Math.round((n+доля)/(ЭТАПЫ.length-1)*100);
    return {номер:n+1,из:ЭТАПЫ.length,имя:ЭТАПЫ[n][0],внутри,процент:Math.min(100,проц),осталось}}
  function ев_разобрано(ан){let s=0,текущий=0;ан.forEach(e=>{if(/Разбор источника/.test(e.message||"")){s+=текущий;текущий=0}const m=/Разобрано (\d+)\//.exec(e.message||"");if(m)текущий=Math.max(текущий,+m[1])});return s+текущий}
  function готовность(id){let к;try{к=JSON.parse(fs.readFileSync(path.join(SHARE,id+".genome.json"),"utf8"))}catch(e){return null}
    const m=к.meta||{},г=к.genome||{},вид=m.kind||"персонаж";let блоки=[];try{блоки=JSON.parse(fs.readFileSync(path.join(ROOT,"pipeline","genes.json"),"utf8"))}catch(e){}
    // гены, которые уже нашёл идущий анализ этого персонажа (журнал улик прогона)
    const вработе=new Set();try{const d=JSON.parse(fs.readFileSync(path.join(ROOT,"logs","research_"+id+".json"),"utf8"));
      if(!d.finished){fs.readFileSync(path.join(ROOT,"chars",String(d.job),"events.jsonl"),"utf8").split(/\r?\n/).forEach(x=>{if(x.includes('"evidence"')){try{const e=JSON.parse(x);if(e.stage==="evidence"&&e.gene&&!г[e.gene])вработе.add(e.gene)}catch(e){}}})}}catch(e){}
    let всего=0,снято=0,пустых=0,улик=0;for(const b of блоки){const ids=b.genes.map(g=>g.id);if(!ids.length)continue;const p=ids[0].split(".")[0];
      if((p==="beast"&&вид!=="существо")||(p==="nat"&&вид!=="ии"))continue;const есть=ids.filter(i=>г[i]||вработе.has(i));всего+=ids.length;снято+=есть.length;
      есть.forEach(i=>{const e=г[i]&&г[i][2];if(Array.isArray(e))улик+=e.length});if(есть.length/ids.length<.3)пустых++}
    const иссл=m.research||{},рев=(m.review||[]).slice(-1)[0],ждут=рев&&рев.предложения?рев.предложения.filter(x=>!x.решено).length:0;
    const голос=m.voice&&typeof m.voice==="object"?m.voice.timbre:m.voice;
    const этапы=[
      {э:"источники",ок:!!иссл.job||улик>0,ч:улик?улик+" улик":"нет"},
      {э:"разбор",ок:снято>=всего*.5||пустых===0,ч:снято+"/"+всего+" генов"+(вработе.size?" (в карточке "+(снято-вработе.size)+" + в работе "+вработе.size+")":"")+" · пустых блоков "+пустых},
      {э:"проверка",ок:!!рев&&String(рев.at||"")>=String(m.analyzed_at||""),ч:рев?("проверено "+(рев.проверено_генов||0)+" · правок "+(рев.правок||0)):"не было"},
      {э:"решения",ок:!!рев&&ждут===0,ч:ждут?("ждут тебя: "+ждут):"—"},
      {э:"реплики",ок:(m.samples||[]).length>=5,ч:(m.samples||[]).length+" из 5"},
      {э:"голос",ок:!!голос,ч:голос?"есть":"нет"},
      {э:"промпт",ок:!!m.prompt,ч:m.prompt?"собран":"нет"}];
    const след=этапы.find(x=>!x.ок);return {этапы,готово:этапы.filter(x=>x.ок).length,всего:этапы.length,дальше:след?след.э+" ("+след.ч+")":"анализ завершён"}}
  // ЖИВОЙ РАЗБОР: улики анализа по мере появления (для вкладки Геном). Берётся прогон из logs/research_<id>.json;
  // законченный показывается ещё 10 минут, потом панель гаснет.
  if(p.startsWith("/api/live/")){const id=p.slice(10).replace(/[^a-z0-9_]/g,"");const after=+(new URL(req.url,"http://x").searchParams.get("after")||0);
    let out={job:""};try{const d=JSON.parse(fs.readFileSync(path.join(ROOT,"logs","research_"+id+".json"),"utf8"));let жив=false;try{process.kill(d.pid,0);жив=true}catch(e){}
      const конец=d.finished?Date.parse(String(d.finished).replace(" ","T")):0;
      if(жив||!d.finished||(Date.now()-конец<10*60*1000)){const ev=fs.readFileSync(path.join(ROOT,"chars",String(d.job),"events.jsonl"),"utf8").split(/\r?\n/).filter(Boolean).map(x=>{try{return JSON.parse(x)}catch(e){return null}}).filter(Boolean);
        const ул=ev.filter(e=>e.stage==="evidence");const посл=ev[ev.length-1]||{};
        out={job:d.job,done:!!d.finished||!жив,state:d.finished?"закончен":(жив?(посл.stage||"идёт"):"прерван"),total:ул.length,from:0,
          items:ул.filter(e=>(e.seq||0)>after).slice(0,60).map(e=>({seq:e.seq,gene:e.gene,v:e.value,c:e.confidence,quote:String(e.quote||"").slice(0,300),reason:String(e.message||"").slice(0,200)}))}}}catch(e){}
    res.writeHead(200,{"Content-Type":"application/json; charset=utf-8","Cache-Control":"no-store"});res.end(JSON.stringify(out));return}
  if(p.startsWith("/api/ready/")){const id=p.slice(11).replace(/[^a-z0-9_]/g,"");res.writeHead(200,{"Content-Type":"application/json; charset=utf-8","Cache-Control":"no-store"});res.end(JSON.stringify(готовность(id)));return}
  // ФОНОВЫЕ РАБОТЫ: logs/research_<id>.json (указатель) + chars/<job>/events.jsonl (живой журнал движка)
  // МОДЕЛЬ ФОНОВЫХ АНАЛИЗОВ: {provider, model} или пусто — «как в чате»
  if(p==="/api/research_model"){const ф=path.join(ROOT,"logs","research_model.json");
    if(req.method==="POST"){let body="";req.on("data",d=>body+=d);req.on("end",()=>{try{const o=JSON.parse(body||"{}");fs.mkdirSync(path.dirname(ф),{recursive:true});
      if(o.provider)fs.writeFileSync(ф,JSON.stringify({provider:String(o.provider),model:String(o.model||"")}));else{try{fs.unlinkSync(ф)}catch(e){}}
      log("модель анализа: "+(o.provider?o.provider+" · "+(o.model||"по умолчанию"):"как в чате"));res.writeHead(200,{"Content-Type":"application/json"});res.end('{"ok":true}')}catch(e){res.writeHead(400);res.end(e.message)}});return}
    let o={};try{o=JSON.parse(fs.readFileSync(ф,"utf8"))}catch(e){}res.writeHead(200,{"Content-Type":"application/json; charset=utf-8","Cache-Control":"no-store"});res.end(JSON.stringify(o));return}
  if(p==="/api/jobs"){const out=[];try{for(const f of fs.readdirSync(path.join(ROOT,"logs")).filter(f=>/^(research|review|auto|corpus|behavior)_[a-z0-9_]+\.json$/.test(f))){
      try{const d=JSON.parse(fs.readFileSync(path.join(ROOT,"logs",f),"utf8"));const id=f.replace(/^(research|review|auto|corpus|behavior)_/,"").slice(0,-5);const вид=f.startsWith("behavior_")?"поведение":f.startsWith("review_")?"проверка":f.startsWith("auto_")?"автопилот":f.startsWith("corpus_")?"корпус":"анализ";let жив=false;try{process.kill(d.pid,0);жив=true}catch(e){}
        const ev=вид==="корпус"?path.join(ROOT,"chars",id,String(d.job),"events.jsonl"):path.join(ROOT,"chars",String(d.job),"events.jsonl");let события=[];try{события=fs.readFileSync(ev,"utf8").split(/\r?\n/).filter(Boolean).map(x=>{try{return JSON.parse(x)}catch(e){return null}}).filter(Boolean)}catch(e){}
        const ист=события.filter(e=>e.stage==="source");const реплик=ист.reduce((a,e)=>a+(+e.replicas||0),0);
        const сост=d.finished?(d.state==="done"?"готово":d.state==="insufficient"?"мало данных":d.state==="error"?"ошибка":String(d.finished).startsWith("останов")?"остановлено":"завершено"):(жив?"идёт":"прервано");
        let имя=id;try{имя=(JSON.parse(fs.readFileSync(path.join(SHARE,id+".genome.json"),"utf8")).meta||{}).name||id}catch(e){}
        const прогресс=вид==="анализ"?этап_анализа(события):(вид==="корпус"&&d.всего_глав?{номер:1,из:1,имя:"загрузка книги",внутри:"глав "+(d.глав_готово||0)+" из "+d.всего_глав+" · его эпизодов "+(d.эпизодов||0),процент:Math.round((d.глав_готово||0)/d.всего_глав*100),осталось:null}:(вид==="поведение"&&d.всего?{номер:1,из:1,имя:"реплики по сценариям",внутри:"сценариев "+(d.готово||0)+" из "+d.всего+" · реплик "+(d.реплик||0),процент:Math.round((d.готово||0)/d.всего*100),осталось:null}:null));
        out.push({id,имя,вид,прогресс,job:d.job,сост,query:d.query,model:d.model||"",provider:d.provider||"",usage:d.usage||null,rub:d.rub!=null?d.rub:null,rub_search:d.rub_search!=null?d.rub_search:null,rub_work:d.rub_work!=null?d.rub_work:null,budget:d.budget||null,started:d.started,finished:d.finished||"",событий:события.length,источников:ист.length,реплик,
          последние:события.slice(-40).map(e=>({at:e.at,stage:e.stage,message:String(e.message||"").slice(0,300)}))})}catch(e){}}}catch(e){}
    out.sort((a,b)=>String(b.started).localeCompare(String(a.started)));
    // результат упавшего в конце анализа мог быть влит (восстановлен) — тогда это не «ошибка», а «влито»
    for(const j of out){if(j.вид==="анализ"&&j.сост==="ошибка"){try{const к=JSON.parse(fs.readFileSync(path.join(SHARE,j.id+".genome.json"),"utf8"));if((к.meta||{}).research&&(к.meta.research.job===j.job)&&Object.keys(к.genome||{}).length)j.сост="влито"}catch(e){}}}
    const персонажи=[...new Set(out.map(j=>j.id))].map(id=>({id,имя:(out.find(j=>j.id===id)||{}).имя,гот:готовность(id)})).filter(x=>x.гот);
    out.forEach(j=>j.гот=(персонажи.find(x=>x.id===j.id)||{}).гот||null);
    res.writeHead(200,{"Content-Type":"application/json; charset=utf-8","Cache-Control":"no-store"});res.end(JSON.stringify(out));return}
  if(p==="/api/chat"&&req.method==="GET"){res.writeHead(200,{"Content-Type":"application/json"});
    res.end(JSON.stringify({ok:true}));return}
  if(p==="/api/chat"&&req.method==="POST"){const куски=[];let размер=0;req.on("data",d=>{размер+=d.length;if(размер<64*1024*1024)куски.push(d)});req.on("end",()=>{const body=Buffer.concat(куски).toString("utf8");res.writeHead(200,{"Content-Type":"application/x-ndjson; charset=utf-8","Cache-Control":"no-cache","X-Accel-Buffering":"no"});const кандидаты=[["py",["-3"]],["python",[]],["python3",[]]];const скрипт=path.join(ROOT,"pipeline","chat.py");const {spawn}=require("child_process");const попытка=i=>{if(i>=кандидаты.length){res.end(JSON.stringify({t:"error",text:"python не найден"})+"\n");return}const [cmd,pre]=кандидаты[i];let pr;try{pr=spawn(cmd,[...pre,"-u",скрипт],{windowsHide:true,env:Object.assign({},process.env,{PYTHONIOENCODING:"utf-8",PYTHONUTF8:"1"})})}catch(e){return попытка(i+1)}let ушёл=false,было=false;pr.on("error",()=>{if(!ушёл&&!было){ушёл=true;попытка(i+1)}});pr.stdout.on("data",d=>{было=true;res.write(d)});let err="";pr.stderr.on("data",d=>err+=d);pr.on("close",код=>{if(ушёл)return;ушёл=true;if(!было){log("chat: "+err.slice(0,300));res.write(JSON.stringify({t:"error",text:err.slice(0,300)||"чат не ответил"})+"\n")}else if(код!==0&&err)log("chat(код "+код+"): "+err.slice(0,300));res.end()});try{pr.stdin.write(body||"{}");pr.stdin.end()}catch(e){}};попытка(0);});return}
  if(p==="/api/prompt"&&req.method==="POST"){let body="";req.on("data",d=>body+=d);req.on("end",()=>{const конец=(код,текст)=>{res.writeHead(код,{"Content-Type":"application/json; charset=utf-8"});res.end(текст)};try{const o=JSON.parse(body||"{}");const id=String(o.id||"").replace(/[^a-z0-9_]/g,"");if(!id)throw new Error("не указан персонаж");const файл=path.join(SHARE,id+".genome.json");if(!fs.existsSync(файл))throw new Error("карточки нет в папке — сначала сохрани её на диск");const кандидаты=[["py",["-3"]],["python",[]],["python3",[]]];const скрипт=path.join(ROOT,"pipeline","promptsmith.py");const {execFile}=require("child_process");const попытка=i=>{if(i>=кандидаты.length){конец(500,JSON.stringify({error:"python не найден"}));return}const [cmd,pre]=кандидаты[i];execFile(cmd,[...pre,скрипт,файл],{maxBuffer:1e7,timeout:300000,env:Object.assign({},process.env,{PYTHONIOENCODING:"utf-8",PYTHONUTF8:"1"})},(err,out,errout)=>{if(err&&!out&&/ENOENT|not found/i.test(String(errout||err.message)))return попытка(i+1);if(err){log("promptsmith: "+String(errout||err.message).slice(0,300));return конец(500,JSON.stringify({error:String(errout||err.message).slice(0,300)}))}try{const карта=JSON.parse(fs.readFileSync(файл,"utf8"));const текст=((карта.meta||{}).prompt)||"";if(текст.length<200)throw new Error("промпт не записался в карточку");log("promptsmith: "+id+" · "+текст.length+" знаков");genIndex();конец(200,JSON.stringify({prompt:текст,by:(карта.meta||{}).prompt_by||""}))}catch(e){конец(500,JSON.stringify({error:e.message}))}})};попытка(0);}catch(e){конец(400,JSON.stringify({error:e.message}))}});return}
  if(p==="/api/chars"&&req.method==="POST"){let body="";req.on("data",d=>body+=d);req.on("end",()=>{try{const o=JSON.parse(body);const id=String(o.id||"").replace(/[^a-z0-9_]/g,"");if(!id||o.format!=="saika-genome/1")throw new Error("не файл персонажа");fs.mkdirSync(SHARE,{recursive:true});const av=saveAva(id,o.avatar);fs.writeFileSync(path.join(SHARE,id+".genome.json"),JSON.stringify(o,null,2));genIndex();log("сохранён share/"+id+".genome.json"+(av?" · ava/"+av:""));res.writeHead(200,{"Content-Type":"application/json"});res.end(JSON.stringify({ok:true,file:"share/"+id+".genome.json"}))}catch(e){res.writeHead(400);res.end(e.message)}});return}
  let f=path.join(APP,p);if(!fs.existsSync(f))f=path.join(ROOT,p);   // сначала app/, потом share/ ava/ pipeline/ из корня
  if(!f.startsWith(ROOT)||!fs.existsSync(f)||fs.statSync(f).isDirectory()){res.writeHead(404);res.end("нет файла: "+p);return}
  res.writeHead(200,{"Content-Type":MIME[path.extname(f)]||"application/octet-stream","Cache-Control":"no-cache"});fs.createReadStream(f).pipe(res);
}).listen(PORT,"127.0.0.1",()=>{
  const url=`http://localhost:${PORT}/genome-studio.html`;
  log("Anamorf Genom · "+url+"\nПапка: "+ROOT+"\nОкно не закрывать, пока работаешь. Ctrl+C — выход.");
  // ПРОВЕРКА МОДУЛЕЙ PYTHON при каждом старте: недостающие ставятся сами, итог — в журнал и logs/deps.log.
  // Появилось после того, как поиск в чате молча падал без модуля ddgs.
  try{const ch=require("child_process").spawn(process.platform==="win32"?"py":"python3",process.platform==="win32"?["-3",path.join(ROOT,"pipeline","deps_check.py")]:[path.join(ROOT,"pipeline","deps_check.py")],{cwd:ROOT,windowsHide:true});
    ch.stdout.on("data",d=>String(d).split(/\r?\n/).filter(Boolean).forEach(s=>log("модули python: "+s.trim())));ch.on("error",e=>log("модули python: проверка не запустилась — "+e.message))}catch(e){log("модули python: "+e.message)}
  const cmd=process.platform==="win32"?`start "" "${url}"`:process.platform==="darwin"?`open "${url}"`:`xdg-open "${url}"`;if(!process.argv.includes("--quiet"))exec(cmd);   // --quiet: перезапуск без новой вкладки
  try{fs.writeFileSync(path.join(ROOT,"ver.js"),'window.__BUILD="'+new Date().toISOString()+'-перезапуск лаунчера";')}catch(e){}   // открытая студия перечитается и покажет уведомление
}).on("error",e=>{log(e.code==="EADDRINUSE"?`Порт ${PORT} занят — уже запущено? Открой http://localhost:${PORT}`:"ОШИБКА сервера: "+e.message);hold()});
