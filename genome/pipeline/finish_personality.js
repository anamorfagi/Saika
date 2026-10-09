const fs=require('fs'),path=require('path'),vm=require('vm');
const root=path.resolve(__dirname,'..');const file=path.join(root,'genome-studio.html');
let h=fs.readFileSync(file,'utf8').replace(/\r\n/g,'\n');
function change(a,b){if(!h.includes(a))throw Error('Missing '+a.slice(0,100));h=h.replace(a,b);}
change("return '<span class=\"nosay\">проектная реплика · не канон</span><br>'+GenomePersonality.escape(a.example)",
       "return '<span class=\"say-label\">пример ответа · авторский, не цитата</span><span class=\"say-text\">'+GenomePersonality.escape(a.example)+'</span>'");
change('const scenes=SCEN.filter(s=>!s.adult||(adult&&!isAI_)).map(sceneFor);',
       'const scenes=(typeof GenomePersonality!=="undefined"?GenomePersonality.scenes(CHAR,SCEN):SCEN).filter(s=>!s.adult||(adult&&!isAI_));');
change('return `<div class="sc tile"><div class="grp">${s.grp}',
       'return `<div class="sc tile${s.authored?\' authored\':\'\'}"><div class="grp">${s.grp}');
change('(${top.score.toFixed(2)} · склонность, не вероятность)', '(${top.score.toFixed(2)})');
change('const местный=/^https?:/.test(location.protocol)&&/localhost|127\\.0\\.0\\.1/.test(location.hostname);',
       'if(typeof GenomePersonality!=="undefined"&&GenomePersonality.enabled(CHAR)){стат.textContent=" — собран из текущих генов и условий сцен";renderResearchCompiler();return}\n  const местный=/^https?:/.test(location.protocol)&&/localhost|127\\.0\\.0\\.1/.test(location.hostname);');
// Keep the editor's display and probe in the same opt-in compiler path.
let probe=fs.readFileSync(path.join(root,'pipeline/probe/probe.js'),'utf8').replace(/\r\n/g,'\n');
const edits=[
  ['function forget(){st.mem[CUR]=[];', 'function forget(){if(st.intent)delete st.intent[CUR];st.mem[CUR]=[];'],
  ['const S=(CHAR.samples||[]).filter(s=>s&&typeof s==="object"&&s.ctx&&s.t);',
   'const S=(CHAR.samples||[]).filter(s=>s&&typeof s==="object"&&s.ctx&&s.t&&(!(typeof GenomePersonality!=="undefined"&&GenomePersonality.enabled(CHAR))||s.provenance==="canon"));'],
  ['st.hist[CUR]=[];st.emo[CUR]={a:{},turn:0};save();showChat();',
   'st.hist[CUR]=[];st.cut[CUR]=0;if(st.intent)delete st.intent[CUR];st.emo[CUR]={a:{},turn:0};save();showChat();'],
];
for(const [a,b] of edits){if(!h.includes(a)||!probe.includes(a))throw Error('Probe integration anchor missing');h=h.replace(a,b);probe=probe.replace(a,b);}
// Updating the card starts a new generation context but keeps the old conversation visible.
const a='function rebuild(){\n  try{comp=compilePrompt()}';
const b=`function rebuild(){
  if(typeof GenomePersonality!=="undefined"&&GenomePersonality.enabled(CHAR)){
    st.profileRevision=st.profileRevision||{};const revision=CHAR.behavior.revision||"1";
    if(st.profileRevision[CUR]!==revision){
      st.cut[CUR]=(st.hist[CUR]||[]).length;if(st.intent)delete st.intent[CUR];
      st.profileRevision[CUR]=revision;save();
    }
  }
  try{comp=compilePrompt()}`;
if(!h.includes(a)||!probe.includes(a))throw Error('Rebuild anchor missing');h=h.replace(a,b);probe=probe.replace(a,b);
for(const m of h.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script>/gi))new vm.Script(m[1]);new vm.Script(probe);
fs.writeFileSync(file,h);fs.writeFileSync(path.join(root,'pipeline/probe/probe.js'),probe);
console.log('Scene layout and context integrations parsed and saved');
