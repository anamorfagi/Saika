// Apply only bounded integration changes; parse every inline script before saving.
const fs=require('fs'),path=require('path'),vm=require('vm');
const root=path.resolve(__dirname,'..');
const file=path.join(root,'genome-studio.html');let html=fs.readFileSync(file,'utf8').replace(/\r\n/g,'\n');
function replace(a,b){if(!html.includes(a))throw Error('Missing anchor: '+a.slice(0,100));html=html.replace(a,b);}
replace('<script src="share/_list.js?v=20260918025000"></script>', '<script src="share/_list.js?v=20260918025000"></script>\n<script src="pipeline/personality.js?v=20261004"></script>');
replace('function sayOf(si,a){const s=SCEN[si];', `function sceneFor(s){return typeof GenomePersonality!=="undefined"?GenomePersonality.scene(CHAR,s):s}
function sayOf(si,a){if(a.contextual&&a.example)return '<span class="nosay">проектная реплика · не канон</span><br>'+GenomePersonality.escape(a.example);const s=SCEN[si];`);
replace('const close=second&&Math.abs(top.score-second.score)<.04;', 'const close=second&&Math.abs(top.score-second.score)<.04;\n  if(s.authored)return `<b>${name}</b> → <b>${top.a.n.toLowerCase()}</b> (${top.score.toFixed(2)} · склонность, не вероятность)${close?" · выбор близкий":""} · из генов: ${why}<br>${GenomePersonality.escape(s.reason)}`;');
replace('function want(act){let s=0,w=0;', 'function want(act){if(act.contextual)return GenomePersonality.desire(act,byId)??0;let s=0,w=0;');
replace('const scenes=SCEN.filter(s=>!s.adult||(adult&&!isAI_));', 'const scenes=SCEN.filter(s=>!s.adult||(adult&&!isAI_)).map(sceneFor);');
replace('scenes.map(s=>{const si=SCEN.indexOf(s);', 'scenes.map(s=>{const si=SCEN.findIndex(base=>base.id===s.id);');
replace('function compilePrompt(){\n', 'function compilePrompt(){\n  if(typeof GenomePersonality!=="undefined"&&GenomePersonality.enabled(CHAR)){compilePrompt.thr=0;return GenomePersonality.compile(CHAR,all,SCEN,perm)}\n');
replace('document.getElementById("prompt").textContent=(CHAR&&CHAR.prompt&&CHAR.prompt.length>200)?CHAR.prompt:cp.text;', 'document.getElementById("prompt").textContent=(typeof GenomePersonality!=="undefined"&&GenomePersonality.enabled(CHAR))?cp.text:((CHAR&&CHAR.prompt&&CHAR.prompt.length>200)?CHAR.prompt:cp.text);');
replace('"trace","trace_by"', '"trace","trace_by","trace_provenance","behavior","analysis"');
const original='const who=[CHAR.name,CHAR.alias,...(CHAR.identity||[]).slice(0,2)].filter(Boolean).join(" · ").slice(0,600);';
const decision=`if(typeof GenomePersonality!=="undefined"&&GenomePersonality.enabled(CHAR)){
    const prior=(st.intent||{})[CUR]||null;
    const recent=hist().slice(st.cut[CUR]||0).filter(m=>m.role==="user"||m.role==="it").slice(-8).map(m=>(m.role==="user"?"Собеседник: ":"Ты: ")+m.text).join("\\n");
    const sys=comp.text+"\\nСлужебный шаг выбора. Верни только JSON: {observation,goal,status,move,disclosure,tone}. Каждое поле — короткая строка. observation — доступный факт без выдуманных чувств. goal — текущая цель; удержи предыдущую, пока она не достигнута или не потеряла смысл. status: active/fulfilled/abandoned/blocked/replaced. move — конкретный речевой поступок, disclosure — что раскрыть или оставить при себе, tone — подача. Не пиши готовую реплику и художественные мысли.";
    try{const r=await callModel(sys,"Предыдущий выбор: "+JSON.stringify(prior)+"\\nСостояние:\\n"+stateBrief(f)+"\\nРазговор:\\n"+recent+"\\nПоследняя реплика: "+msg,3000);
      const d=GenomePersonality.parseDecision(r.text);if(!d)return "";f.decision=d;
      return "Цель: "+d.goal+" · ход: "+d.move+" · "+d.tone;
    }catch(e){return ""}
  }
  `+original;
// Embedded probe and its editable source share exactly the same integration.
replace(original,decision);
const oldInner='const inner=f&&f.inner?';
const newInner='const inner=f&&f.decision?"\\n\\n## Выбор на этот ход (служебное; не произносить)\\n"+JSON.stringify(f.decision):f&&f.inner?';
replace(oldInner,newInner);
const commit='hist().push({role:"it",t:Date.now(),inner:f.inner||"",text:p.text||"(пусто)",';
replace(commit,'if(f.decision&&p.text){st.intent=st.intent||{};st.intent[CUR]=f.decision}\n    '+commit);
// Normal sends already appended msg to history. Do not duplicate it in the actor input.
replace('return H.map(m=>(m.role==="user"?"Собеседник: ":"Ты: ")+m.text).join("\\n")+`\\nСобеседник: ${msg}',
    'if(typeof GenomePersonality!=="undefined"&&GenomePersonality.enabled(CHAR)&&H.length&&H[H.length-1].role==="user"&&H[H.length-1].text===msg)H.pop();\n  return H.map(m=>(m.role==="user"?"Собеседник: ":"Ты: ")+m.text).join("\\n")+`\\nСобеседник: ${msg}');
let probe=fs.readFileSync(path.join(root,'pipeline/probe/probe.js'),'utf8').replace(/\r\n/g,'\n');
for(const [a,b] of [[original,decision],[oldInner,newInner],[commit,'if(f.decision&&p.text){st.intent=st.intent||{};st.intent[CUR]=f.decision}\n    '+commit]]){
  if(!probe.includes(a))throw Error('Probe anchor missing');probe=probe.replace(a,b);
}
probe=probe.replace('return H.map(m=>(m.role==="user"?"Собеседник: ":"Ты: ")+m.text).join("\\n")+`\\nСобеседник: ${msg}',
    'if(typeof GenomePersonality!=="undefined"&&GenomePersonality.enabled(CHAR)&&H.length&&H[H.length-1].role==="user"&&H[H.length-1].text===msg)H.pop();\n  return H.map(m=>(m.role==="user"?"Собеседник: ":"Ты: ")+m.text).join("\\n")+`\\nСобеседник: ${msg}');
new vm.Script(probe);
for(const match of html.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script>/gi))new vm.Script(match[1]);
fs.writeFileSync(file,html);fs.writeFileSync(path.join(root,'pipeline/probe/probe.js'),probe);
console.log('Personality integration parsed and saved');
