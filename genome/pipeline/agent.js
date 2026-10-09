// [БЛОК АГЕНТ] Руки на этой машине. Claude кладёт задание файлом в jobs/, агент его выполняет
// и кладёт рядом результат: код возврата, вывод, время. Никакой магии и ничего скрытого —
// каждое задание видно файлом до запуска, каждый результат остаётся файлом после.
//
// Запуск: node pipeline/agent.js        (или ЗАПУСТИТЬ_АГЕНТА.bat — один раз, дальше сам)
// Папки:  jobs/<имя>.job.json  → задание,  jobs/<имя>.out.json → результат,  jobs/agent.log → журнал
//
// Разрешено только то, что перечислено в TASKS. Произвольную команду агент не выполняет:
// если файл задания подменят, максимум что случится — пересборка студии.
const fs=require("fs"),path=require("path"),{execFile,spawn}=require("child_process");
const ROOT=path.resolve(__dirname,"..");
const JOBS=path.join(ROOT,"jobs");
const LOG=path.join(JOBS,"agent.log");
const PY=process.platform==="win32"?["py","-3"]:["python3"];

function log(s){const line=new Date().toISOString().slice(0,19).replace("T"," ")+"  "+s;
  try{fs.appendFileSync(LOG,line+"\n")}catch(e){}console.log(line)}

// Список заданий. Ключ — что можно попросить; значение — как это делается на самом деле.
const TASKS={
  // карта доступности всех стыков LLM
  probe:      ()=>({cmd:PY[0],args:[...PY.slice(1),path.join(ROOT,"pipeline","probe.py"),"--json","--timeout","10"],cwd:ROOT,ms:200000}),
  // пересборка студии из конвейера
  build:      ()=>({cmd:"bash",args:[path.join(ROOT,"pipeline","build.sh")],cwd:ROOT,ms:600000}),
  // пересборка exe
  exe:        ()=>({cmd:"cmd",args:["/c",path.join(ROOT,"AnamorfGenom","СОБРАТЬ_EXE.bat")],cwd:path.join(ROOT,"AnamorfGenom"),ms:900000}),
  // поднять воркера исследований
  research:   ()=>({cmd:"powershell",args:["-File",path.join(ROOT,"pipeline","start_research.ps1")],cwd:ROOT,ms:60000}),
  // проверить одну модель живым запросом
  ping:       j=>({cmd:PY[0],args:[...PY.slice(1),path.join(ROOT,"pipeline","llm.py"),"--provider",String(j.provider||"gigachat")].concat(j.model?["--model",String(j.model)]:[]),cwd:ROOT,ms:90000}),
  // любой скрипт ИЗ pipeline/ — без путей наружу, без произвольных команд
  script:     j=>{const f=String(j.file||"").replace(/[^A-Za-z0-9_.\-]/g,"");
                  if(!f||!/\.(py|js)$/.test(f))throw new Error("script: имя файла только из pipeline/, .py или .js");
                  const full=path.join(ROOT,"pipeline",f);
                  if(!fs.existsSync(full))throw new Error("script: нет файла pipeline/"+f);
                  const args=(j.args||[]).map(String).slice(0,20);
                  return f.endsWith(".py")?{cmd:PY[0],args:[...PY.slice(1),full,...args],cwd:ROOT,ms:600000}
                                          :{cmd:"node",args:[full,...args],cwd:ROOT,ms:600000}},
  // проверка связи: агент жив, вот его версия и время
  hello:      ()=>({cmd:process.execPath,args:["-e","console.log('агент жив · node '+process.version+' · '+new Date().toLocaleString('ru-RU'))"],cwd:ROOT,ms:15000}),
};

function run(name,spec){
  return new Promise(ok=>{
    const t0=Date.now();
    execFile(spec.cmd,spec.args,{cwd:spec.cwd,maxBuffer:5e7,timeout:spec.ms,windowsHide:true,shell:false},
      (err,out,errout)=>ok({task:name,cmd:spec.cmd+" "+spec.args.join(" "),code:err?(err.code??1):0,
        killed:!!(err&&err.killed),sec:+((Date.now()-t0)/1000).toFixed(1),
        stdout:String(out||"").slice(-200000),stderr:String(errout||"").slice(-40000),
        error:err?String(err.message).slice(0,300):""}));
  });
}

const busy=new Set();
async function take(file){
  const full=path.join(JOBS,file);
  const base=file.replace(/\.job\.json$/,"");
  const outFile=path.join(JOBS,base+".out.json");
  if(busy.has(base)||fs.existsSync(outFile))return;
  busy.add(base);
  let job;
  try{job=JSON.parse(fs.readFileSync(full,"utf8"))}catch(e){
    fs.writeFileSync(outFile,JSON.stringify({error:"задание не читается: "+e.message},null,1));busy.delete(base);return}
  const name=String(job.task||"");
  log("задание «"+name+"» ("+base+")");
  let res;
  try{
    if(!TASKS[name])throw new Error("такого задания нет. Доступны: "+Object.keys(TASKS).join(", "));
    res=await run(name,TASKS[name](job));
  }catch(e){res={task:name,code:-1,error:String(e.message)}}
  res.at=new Date().toISOString().slice(0,19);
  const tmp=outFile+".tmp";
  fs.writeFileSync(tmp,JSON.stringify(res,null,1));fs.renameSync(tmp,outFile);
  log("  → код "+res.code+(res.sec?", "+res.sec+" с":"")+(res.error?", "+res.error.slice(0,90):""));
  busy.delete(base);
}

fs.mkdirSync(JOBS,{recursive:true});
log("агент запущен · корень "+ROOT+" · заданий в списке "+Object.keys(TASKS).length);
fs.writeFileSync(path.join(JOBS,"_агент_жив.txt"),
  "Агент работает с "+new Date().toLocaleString("ru-RU")+"\nПапка заданий: "+JOBS+
  "\nДоступные задания: "+Object.keys(TASKS).join(", ")+
  "\nЗакрой окно агента — и ничего отсюда выполняться больше не будет.\n");
setInterval(()=>{
  let files=[];try{files=fs.readdirSync(JOBS).filter(f=>f.endsWith(".job.json"))}catch(e){return}
  files.forEach(take);
},1500);
