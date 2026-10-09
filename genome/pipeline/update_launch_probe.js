// update_launch_probe.js — лаунчер получает два маршрута:
//   GET  /api/probe        — прогоняет pipeline/probe.py и отдаёт честную карту доступности стыков
//   POST /api/keyfind      — по одному вставленному ключу сам находит провайдера и список его моделей
// Запуск: node update_launch_probe.js (правит exe/launcher.js и pipeline/launcher.js).
const fs=require("fs");
const ROUTE=`
  // карта стыков: что реально открывается с этой машины. Числа настоящие — их считает pipeline/probe.py
  if(p==="/api/probe"&&req.method==="GET"){
    const only=(u.searchParams.get("id")||"").replace(/[^a-z0-9_,]/g,"");
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
        const base=String(pr.base).replace(/\\/$/,"");
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
`;
for(const f of ["exe/launcher.js","pipeline/launcher.js"]){
  if(!fs.existsSync(f))continue;
  let t=fs.readFileSync(f,"utf8");
  if(t.includes('p==="/api/probe"')){console.log("уже есть:",f);continue}
  const a='  if(p==="/api/llm"&&req.method==="POST")';
  if(!t.includes(a)){console.error("не найдена точка вставки в",f);process.exit(1)}
  t=t.replace(a,ROUTE+a);
  fs.writeFileSync(f,t);console.log("маршруты добавлены:",f);
}
