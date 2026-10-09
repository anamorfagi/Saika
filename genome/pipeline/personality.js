/* Contextual personality layer. Opt-in per card; legacy cards keep their compiler. */
(function(root){
  'use strict';
  const enabled=c=>!!(c&&c.behavior&&c.behavior.version===1);
  const escape=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  function scene(card,base){
    const r=enabled(card)&&card.behavior.scenes&&card.behavior.scenes[base.id];
    if(!r||!Array.isArray(r.acts)||!r.acts.length)return base;
    return Object.assign({},base,{in:r.context,reason:r.reason,authored:true,
      acts:r.acts.map(a=>Object.assign({},a,{contextual:true}))});
  }
  function scenes(card,base){
    const out=base.map(s=>scene(card,s));
    if(enabled(card))for(const [id,s] of Object.entries(card.behavior.scenes||{})){
      if(!out.some(b=>b.id===id))out.push(scene(card,{id,t:s.title||id,grp:s.group||'образ',adult:!!s.adult}));
    }
    return out;
  }
  function desire(act,genes){
    let sum=0,weight=0;
    for(const [id,dir,k=1] of act.g||[]){const g=genes[id];
      if(!g||!(g.c>0))continue;
      const w=g.c*Math.abs(k);sum+=g.v*dir*w;weight+=w;
    }
    return weight?Math.max(0,Math.min(1,(1+sum/weight)/2)):null;
  }
  function compile(card,genes,baseScenes,permissions){
    const b=card.behavior,by=Object.fromEntries(genes.map(g=>[g.id,g]));
    const lines=['# '+card.name+' («'+card.alias+'»)',
      'Играй персонажа от первого лица. Ответ рождается из текущей ситуации и цели. Карточка — основания выбора, а не текст для пересказа. Сила черты не задаёт частоту её упоминания. Уверенность обозначает качество улик; неизвестное не равно среднему.'];
    const section=(name,rows)=>{if(rows&&rows.length)lines.push('\n## '+name,...rows.map(s=>'- '+s));};
    section('Идентичность и мир',card.identity);
    section('Приоритеты и конфликт мотивов',b.priorities);
    section('Выбор поступка',b.decision);
    section('Контекстные режимы',b.modes.map(m=>m.when+' → '+m.goal+'. '+m.style+' Выход: '+m.exit));
    section('Речь',b.speech);
    const captured=genes.filter(g=>g.c>0&&!/^(beast|nat)\./.test(g.id));
    const core=[];
    const groups=new Map();for(const g of captured){const id=g.id.split('.')[0];if(!groups.has(id))groups.set(id,[]);groups.get(id).push(g);}
    for(const [id,gs] of groups){
      // Each block contributes; attention, agency and memory are not lost through P-only ranking.
      const selected=gs.sort((a,z)=>Math.abs(z.v)*z.c-Math.abs(a.v)*a.c).slice(0,3);
      core.push(...selected);
      section('Основания · '+(b.blocks[id]||id),selected.map(g=>g.name+': '+(g.v>=0?g.pos:g.neg)+
        ' [склонность '+g.v.toFixed(2)+', уверенность '+g.c.toFixed(2)+']; применяется по релевантному поводу, не к каждому собеседнику.'));
    }
    section('Неизвестное и неприменимое',b.unknown);
    const demonstrations=[];
    for(const base of scenes(card,baseScenes)){if(base.adult&&(card.child||card.kind==='ребёнок'||card.kind==='ии'))continue;
      const s=scene(card,base);if(!s.authored)continue;
      const rows=s.acts.map(a=>({a,v:desire(a,by)})).filter(r=>r.v!==null&&(!r.a.need||permissions[r.a.need])).sort((a,z)=>z.v-a.v);
      if(!rows.length)continue;
      demonstrations.push(s.in+' → вероятнее '+rows[0].a.n+'. Основание: '+s.reason+
        ' Другие возможные ходы: '+rows.slice(1).map(r=>r.a.n).join('; ')+'.');
    }
    section('Условные сцены — прогноз, не обязательный сценарий',demonstrations);
    section('Противоречия', (card.tensions||[]).filter(([a,oa,va,z,oz,vz])=>by[a]&&by[a].c&&by[z]&&by[z].c&&
      (oa==='>='?by[a].v>=va:by[a].v<=va)&&(oz==='>='?by[z].v>=vz:by[z].v<=vz)).map(r=>r[6]));
    section('Границы образа',card.never);
    section('Границы исполнения',['Сценические намерения не дают доступа к устройству или личным данным. Не изображай уже выполненные реальные действия. Не приписывай собеседнику страх, возбуждение, мысли или движения без доступного свидетельства.']);
    // Only verified short primary-source samples. Authored demonstrations stay in the behavior UI.
    section('Короткие образцы из первоисточника',(card.samples||[]).filter(s=>s.provenance==='canon').map(s=>s.ctx+': «'+(s.translation||s.t)+'» ('+s.src+'; '+(s.translation?'рабочий перевод':'оригинал')+'). Не повторять механически.'));
    return {text:lines.join('\n'),core};
  }
  function parseDecision(raw){
    const t=String(raw||'').trim().replace(/^```(?:json)?\s*/i,'').replace(/\s*```$/,'');
    try{const o=JSON.parse(t);if(!o||typeof o!=='object'||Array.isArray(o))return null;
      const out={};for(const k of ['observation','goal','status','move','disclosure','tone']){
        if(typeof o[k]!=='string'||!o[k].trim())return null;out[k]=o[k].trim().slice(0,240);
      }
      if(!['active','fulfilled','abandoned','blocked','replaced'].includes(out.status))return null;
      return out;
    }catch(e){return null;}
  }
  const api={enabled,scene,scenes,desire,compile,parseDecision,escape};
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
  root.GenomePersonality=api;
})(typeof globalThis!=='undefined'?globalThis:this);
