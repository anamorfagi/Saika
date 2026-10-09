// update_normmeta.js — файл персонажа с identity/samples/never строкой (а не списком) ронял страницу:
// компилятор делал CHAR.identity.map(...) → TypeError → вкладки переставали переключаться (Рикка).
// Лечим на входе: строка → [строка], строка-JSON-массив → массив, массив одиночных букв → склеиваем.
const fs=require("fs"),P=__dirname+"/genome-studio.html";let h=fs.readFileSync(P,"utf8");
const A='meta.exported=meta.exported||obj.exported||"";return {id,genome,meta,n}}';
const B='for(const k of ["identity","samples","never","masks","tensions"]){let v=meta[k];if(Array.isArray(v)&&v.length>3&&v.every(x=>typeof x==="string"&&x.length<=1))v=v.join("");if(typeof v==="string"){const t=v.trim();try{v=t.startsWith("[")?JSON.parse(t):(t?[t]:[])}catch(e){v=[t]}}meta[k]=Array.isArray(v)?v:[]}\n  '+A;
if(h.includes(B)){console.log("уже стоит")}else{if(!h.includes(A))throw "якорь не найден";h=h.replace(A,B);fs.writeFileSync(P,h);console.log("ok: нормализация meta в charFromFile")}
fs.writeFileSync(__dirname+"/ver.js",'window.__BUILD="'+new Date().toISOString()+'";');
