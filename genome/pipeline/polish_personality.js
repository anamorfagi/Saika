const fs=require('fs'),path=require('path'),vm=require('vm');
const root=path.resolve(__dirname,'..'),file=path.join(root,'genome-studio.html');let h=fs.readFileSync(file,'utf8');
const anchor='function renderResearchCompiler(){\n';
if(!h.includes(anchor))throw Error('Compiler anchor missing');
h=h.replace(anchor,anchor+`if(typeof GenomePersonality!=="undefined"&&GenomePersonality.enabled(CHAR)){
  document.querySelector("#p-comp .lead").textContent="Контекстный компилятор: мотивы, внимание, память, выбор действия и речь. Из каждого снятого блока берутся до трёх значимых генов; условия сцен определяют, где они уместны. Неснятое не подменяется средним, сила черты не задаёт частоту реплик.";
  document.querySelector("[data-smith]").textContent="собрать из генома";
}
`);
const stat='document.getElementById("pstat").textContent=`';
const i=h.indexOf(stat),end=h.indexOf(';',i);if(i<0||end<0)throw Error('Compiler stats missing');
h=h.slice(0,end+1)+`
if(typeof GenomePersonality!=="undefined"&&GenomePersonality.enabled(CHAR))document.getElementById("pstat").textContent=cp.text.split("\\n").length+" строк · "+cp.text.length+" символов · "+cp.core.length+" генов из "+all.filter(g=>g.c>0).length+" снятых · условия и выбор по блокам";
`+h.slice(end+1);
const trace='  // превращения R13–R16';
if(!h.includes(trace))throw Error('Trace anchor missing');
h=h.replace(trace,`  if(typeof GenomePersonality!=="undefined"&&GenomePersonality.enabled(CHAR))el.querySelector(".lead").textContent="Условные сцены: ситуация → оценка вариантов из снятых генов → пример ответа. Числа — сравнительные склонности, не вероятности и не процент точности. Примеры написаны для демонстрации; они не являются каноническими цитатами или полученными ответами модели.";
`+trace);
for(const m of h.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script>/gi))new vm.Script(m[1]);fs.writeFileSync(file,h);
console.log('Compiler and behavior labels now describe the active implementation');
