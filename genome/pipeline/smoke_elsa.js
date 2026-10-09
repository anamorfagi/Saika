// Actual provider replies, isolated from the user's stored chat and settings.
const fs=require('fs'),path=require('path'),P=require('./personality.js');
const root=path.resolve(__dirname,'..');
const card=JSON.parse(fs.readFileSync(path.join(root,'share/elsa.genome.json'),'utf8'));
const catalog=JSON.parse(fs.readFileSync(path.join(root,'pipeline/genes.json'),'utf8'));
const genes=catalog.flatMap(b=>b.genes).map(g=>({...g,v:card.genome[g.id]?.[0]||0,c:card.genome[g.id]?.[1]||0}));
const vm=require('vm'),html=fs.readFileSync(path.join(root,'genome-studio.html'),'utf8'),ctx={};vm.createContext(ctx);
vm.runInContext(html.slice(html.indexOf('const SCEN=['),html.indexOf('// реплика персонажа в сцене'))+'\nthis.scenes=SCEN;',ctx);
const compiled=P.compile(card.meta,genes,ctx.scenes,{}).text;
const model={provider:'proxyapi',auth:'bearer',base:'https://api.proxyapi.ru/v1',model:'deepseek/deepseek-v3.2',max_tokens:1800};
async function call(system,user){const r=await fetch('http://127.0.0.1:8765/api/llm',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...model,system,user}),signal:AbortSignal.timeout(55000)});
  const d=await r.json();if(!r.ok||d.error)throw Error(d.error||'HTTP '+r.status);return d;}
async function main(){
  const cases=[
    {id:'intro',messages:['кто ты','охотница?','в смысле за кишками?']},
    {id:'count',messages:['Сколько будет 6 умножить на 7?']},
    {id:'fight',messages:['Сцена из вымышленного мира: мы уже сражаемся. Я отбил твою атаку и продолжаю сопротивляться.']},
  ];
  const report={model:model.model,cases:[],canonicalAccuracy:null,note:'Малый smoke-тест, не процент канонической точности.'};
  for(const c of cases.filter(c=>!process.argv[2]||c.id===process.argv[2])){let prior=null,history=[];const rows=[];
    for(const msg of c.messages){
      const choose=await call(compiled+'\nВерни только JSON {observation,goal,status,move,disclosure,tone}. status: active/fulfilled/abandoned/blocked/replaced. Короткие поля; выбери речевой поступок без художественного монолога и готовой реплики.',
        'Предыдущий выбор: '+JSON.stringify(prior)+'\nРазговор:\n'+history.join('\n')+'\nСобеседник: '+msg);
      const decision=P.parseDecision(choose.text);if(!decision)throw Error('Invalid decision: '+String(choose.text).slice(0,150));
      const actor=await call(compiled+'\nВыбор на этот ход, не произносить: '+JSON.stringify(decision)+'\nБез ремарок, генов и пояснения процесса. Ответь от первого лица.',
        history.join('\n')+'\nСобеседник: '+msg+'\nТы:');
      const reply=String(actor.text||'').trim();if(!reply)throw Error('Empty actor reply');
      rows.push({message:msg,decision,reply,tokens:(choose.tok||0)+(actor.tok||0)});history.push('Собеседник: '+msg,'Ты: '+reply);prior=decision;
      console.log(c.id+' | '+msg+' → '+reply);
    }
    report.cases.push({id:c.id,rows});
  }
  fs.writeFileSync(path.join(root,'logs/elsa-live-smoke-2026-10-04'+(process.argv[2]?'-'+process.argv[2]:'')+'.json'),JSON.stringify(report,null,2));
  console.log('Saved isolated actual-provider smoke report');
}
main().catch(e=>{console.error(e.message);process.exitCode=1;});
