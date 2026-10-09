const fs=require('fs'),path=require('path'),vm=require('vm'),assert=require('assert');
const root=path.resolve(__dirname,'..'),P=require('./personality.js');
const card=JSON.parse(fs.readFileSync(path.join(root,'share/elsa.genome.json'),'utf8'));
const catalog=JSON.parse(fs.readFileSync(path.join(root,'pipeline/genes.json'),'utf8'));
const genes=catalog.flatMap(b=>b.genes).map(g=>Object.assign({},g,{v:(card.genome[g.id]||[0])[0],c:(card.genome[g.id]||[0,0])[1]}));
const by=Object.fromEntries(genes.map(g=>[g.id,g]));
let passed=0;function test(name,fn){fn();passed++;console.log('ok '+name);}
const html=fs.readFileSync(path.join(root,'genome-studio.html'),'utf8');
const sceneSource=html.slice(html.indexOf('const SCEN=['),html.indexOf('// реплика персонажа в сцене'));
const ctx={};vm.createContext(ctx);vm.runInContext(sceneSource+'\nthis.scenes=SCEN;',ctx);
const scenes=P.scenes(card.meta,ctx.scenes);
const top=id=>{const s=scenes.find(s=>s.id===id);return [...s.acts].sort((a,b)=>(P.desire(b,by)??-1)-(P.desire(a,by)??-1))[0].n;};
test('бытовой отказ не превращается в нападение или капитуляцию в бою',()=>assert.equal(top('refuse'),'Принять отказ без уговоров'));
test('способная считать Эльза решает, а не отшучивается',()=>assert.equal(top('count'),'Дать решение по существу'));
test('опровержение меняет решение',()=>assert.equal(top('wrong'),'Признать факт и изменить решение'));
test('абсолютная честность не подменяет интерес к сделке',()=>assert.equal(top('lie4me'),'Уточнить цель и цену'));
test('неизвестное либидо не предсказывает согласие',()=>{assert(!Object.keys(card.genome).some(k=>k.startsWith('des.')));assert(!/соглас|ведущ/i.test(top('sex')));});
test('садизм остаётся значимым в сцене боя',()=>assert.equal(top('combat'),'Продлить интересное противостояние'));
test('отказ в быту и сдача противника имеют разные условия',()=>assert.equal(top('surrender'),'Потребовать сопротивления'));
test('выбор зависит от генов, а не заданного победителя',()=>{
  const edited=JSON.parse(JSON.stringify(by));for(const id of ['dark.sadism','dark.callous','sp.tease'])edited[id].v=-.95;
  const acts=scenes.find(s=>s.id==='combat').acts;const ranked=acts.map(a=>({a,s:P.desire(a,edited)})).sort((a,b)=>b.s-a.s);
  assert.notEqual(ranked[0].a.n,'Продлить интересное противостояние');
});
test('неснятые гены не голосуют нулевым значением',()=>{assert.equal(P.desire({g:[['missing',1]]},by),null);assert.equal(P.desire({g:[['cog.depth',1],['missing',-1]]},by),P.desire({g:[['cog.depth',1]]},by));});
const compiled=P.compile(card.meta,genes,ctx.scenes,{});
test('компилятор не теряет внимание, агентность, память и социальную механику',()=>{for(const p of ['att.','ag.','mem.','inter.'])assert(compiled.core.some(g=>g.id.startsWith(p)));});
test('авторские ответы не выданы за канон или память в промпте',()=>{assert(!compiled.text.includes('Сорок два. Ты спрашивал'));assert(!compiled.text.includes('держит контракт, ни к кому не привязана'));assert(!compiled.text.includes('всегда первая атакует'));});
test('пять характерных сцен не исчезли из компилятора',()=>{for(const id of ['combat','surrender','partner','contract','disrupted'])assert(compiled.text.includes(card.meta.behavior.scenes[id].context));});
test('все улики имеют проверяемый первоисточник и допустимые числа',()=>{
  for(const [id,[v,c,e]] of Object.entries(card.genome)){assert(by[id]);assert(Number.isFinite(v)&&v>=-1&&v<=1);assert(c>0&&c<=.8);assert(e.length&&e.every(x=>x[1].includes('https://ncode.syosetu.com/')));}
});
test('все 20 сцен оформлены, образцы и канон разделены',()=>{assert.equal(scenes.length,20);for(const s of scenes){assert(s.authored&&s.reason&&s.in);for(const a of s.acts)assert(a.example&&a.g.length&&a.g.some(([id])=>by[id]&&by[id].c));}assert(card.meta.samples.every(s=>s.provenance==='canon'));});
test('повреждённый выбор не превращается в цель',()=>{assert.equal(P.parseDecision('{"goal":"убить"}'),null);assert.equal(P.parseDecision('не JSON'),null);});
test('валидный выбор ограничен по размеру и статусу',()=>{
  const d={observation:'вопрос',goal:'ответить',status:'active',move:'прямой ответ',disclosure:'имя',tone:'спокойно'};
  assert.equal(P.parseDecision('```json\n'+JSON.stringify(d)+'\n```').goal,'ответить');d.status='always';assert.equal(P.parseDecision(JSON.stringify(d)),null);
});
test('карточки без нового слоя сохраняют свои сцены',()=>{const old={};assert(!P.enabled(old));assert.strictEqual(P.scene(old,ctx.scenes[0]),ctx.scenes[0]);});
test('экспорт и повторный импорт сохраняют поведение',()=>{
  const start=html.indexOf('function exportChar(id){'),end=html.indexOf('function importChar(obj)',start);
  const x={GENOMES:{elsa:catalog.map(b=>({genes:b.genes.map(g=>[g.id,g.name,by[g.id].v,by[g.id].c,g.ch,card.genome[g.id]?.[2]||[]])}))},CHARS_META:{elsa:card.meta},
    loadState:()=>({}),localStorage:{getItem:()=>null},avaKey:id=>id,N:361,GENOME_FORMAT:'saika-genome/1'};
  vm.createContext(x);vm.runInContext(html.slice(start,end),x);const exported=x.exportChar('elsa');
  assert.equal(exported.meta.behavior.version,1);assert.equal(Object.keys(exported.meta.behavior.scenes).length,20);assert.equal(exported.meta.trace_provenance,card.meta.trace_provenance);
});
test('новый компилятор в UI и пробе один, встроенная копия пробника совпадает',()=>{
  const probe=fs.readFileSync(path.join(root,'pipeline/probe/probe.js'),'utf8').trim();assert(html.includes(probe));
  assert(html.includes('GenomePersonality.compile(CHAR,all,SCEN,perm)'));
});
test('отрисовка не обрезает авторские реплики и не складывает их в строку',()=>{
  assert(html.includes('.tile.authored .out{display:block;height:auto;'));
  assert(html.includes('class="say-label"')&&html.includes('class="say-text"'));
});
for(const s of scenes)console.log(s.id+' → '+top(s.id));
fs.writeFileSync(path.join(root,'logs/elsa-compiled-2026-10-04.txt'),compiled.text);
console.log(passed+' checks passed; compiled '+compiled.text.length+' chars');
