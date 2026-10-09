// update_voice2.js — голос, часть 2: режимы (шёпот, крик, интим, смех, печаль, пение, звуки),
// живые правила «контекст → крутилки» по каналам dyn.*, адаптеры под 5 движков TTS, экспорт профиля.
// Запуск: node update_voice2.js (после update_voice / update_comp2). Правит gs.html на месте.
const fs=require("fs");let t=fs.readFileSync("gs.html","utf8");
function rep(a,b){if(!t.includes(a)){console.error("не найдено:",a.slice(0,70));process.exit(1)}t=t.replace(a,b)}

// [1] рендер: старый renderVoice остаётся, поверх — режимы/правила/движки
rep(`renderVoice();\n\n// ---------- архетипы: библиотека независимых типов`,`
// ---------- голос, часть 2: режимы · живые правила · движки ----------
// Крутилки 0…1: speed скорость, energy громкость/напор, stab устойчивость, style выразительность, breath придыхание, pitch высота (0.5 = базовая), pause паузы
const gv=id=>{const g=byId[id];return g&&g.c?g.v:0};const gk=id=>{const g=byId[id];return g&&g.c?1:0}; // значение снятого гена / снят ли
const clamp=x=>Math.max(0,Math.min(1,x));
// Базовые крутилки — из 12 параметров манеры (P) старого компилятора
function voiceBase(P){return {speed:P[0].v,energy:P[5].v,stab:P[3].v,style:(P[2].v+P[10].v)/2,breath:P[9].v,pitch:.5,pause:P[1].v}}
// Режимы: каждый — функция от базы и генов. gate = насколько режим вообще свойствен персонажу (0…1), note — почему
const VOICE_MODES=[
 {id:"normal",n:"Обычная речь",f:(b)=>({k:b,gate:1,note:"база из 12 параметров манеры"})},
 {id:"whisper",n:"Шёпот",f:(b)=>{const hide=clamp((gv("emo.desire.hide")+gv("emo.tender.hide"))/2+.5);const g=clamp(.5+gv("soc.silence_ok")*.3+gv("des.talk_ease")*.2);
   return {k:{speed:clamp(b.speed*.85),energy:.12,stab:clamp(b.stab+.15),style:clamp(b.style*.6),breath:clamp(.75+b.breath*.25),pitch:.45,pause:clamp(b.pause+.15)},gate:g,note:gk("soc.silence_ok")?"паузы держит — шёпот естественен":"склонность к шёпоту не снята"}}},
 {id:"anger",n:"Гнев",f:(b)=>{const hide=gv("emo.anger.hide"),peak=gv("dyn.anger.peak");const cold=hide>.3;
   return cold?{k:{speed:clamp(b.speed*.9),energy:clamp(b.energy*.7),stab:clamp(b.stab+.25),style:clamp(b.style*.7),breath:.2,pitch:.42,pause:clamp(b.pause+.2)},gate:clamp(.5+peak*.5),note:"гнев скрывает (emo.anger.hide "+hide.toFixed(1)+") — холодный, тише и ниже, паузы"}
   :{k:{speed:clamp(b.speed*1.15),energy:clamp(.7+peak*.3),stab:clamp(b.stab-.3),style:clamp(b.style+.3),breath:.15,pitch:.62,pause:clamp(b.pause-.2)},gate:clamp(.5+peak*.5),note:"гнев наружу — громче, быстрее, выше, устойчивость падает"}}},
 {id:"intim",n:"Интим",f:(b)=>{const sh=gv("des.shame_link"),ease=gv("des.talk_ease"),lib=gv("des.libido");
   return sh>.3?{k:{speed:clamp(b.speed*.75),energy:.25,stab:clamp(b.stab-.35),style:clamp(b.style*.8),breath:clamp(.6+lib*.3),pitch:.55,pause:clamp(b.pause+.35)},gate:clamp(.4+lib*.4),note:"стыд сильнее желания (des.shame_link "+sh.toFixed(1)+") — обрывки фраз, паузы, голос срывается"}
   :{k:{speed:clamp(b.speed*.85),energy:clamp(.3+gv("soc.dominance")*.3),stab:clamp(b.stab),style:clamp(b.style),breath:clamp(.5+lib*.4),pitch:.47,pause:clamp(b.pause+.1)},gate:clamp(.4+lib*.4+ease*.2),note:"о теле говорит прямо — ниже, с придыханием, команды"}}},
 {id:"play",n:"Смех / игра",f:(b)=>{const pl=gv("soc.playful"),sar=gv("sp.sarcasm");
   return {k:{speed:clamp(b.speed*1.05),energy:clamp(b.energy+.1),stab:clamp(b.stab-.1),style:clamp(b.style+.25),breath:.3,pitch:.56,pause:b.pause},gate:clamp(.3+pl*.5+gv("def.humor")*.2),note:sar>.3?"смех колкий — усмешка, хмык (sp.sarcasm)":pl>.3?"смех открытый — хихикает, смеётся в голос":"игривость не снята"}}},
 {id:"sad",n:"Печаль",f:(b)=>{const hide=gv("emo.sadness.hide");
   return {k:{speed:clamp(b.speed*.85),energy:.3,stab:hide>.3?clamp(b.stab+.2):clamp(b.stab-.3),style:clamp(b.style*.7),breath:.45,pitch:.42,pause:clamp(b.pause+.25)},gate:clamp(.5+gv("dyn.sadness.peak")*.5),note:hide>.3?"печаль скрывает — ровно и тихо, только медленнее":"печаль слышна — голос дрожит, паузы"}}},
 {id:"sing",n:"Пение",f:(b)=>{const g=clamp(.2+gv("mot.entertain")*.4+gv("sp.drama")*.2+gv("soc.playful")*.2-gv("dyn.shame.threshold")*-.2);
   return {k:{speed:.5,energy:clamp(.4+g*.4),stab:.35,style:.9,breath:.4,pitch:.5,pause:.5},gate:g,note:g>.6?"поёт в голос, не стесняется":g>.4?"напевает под нос, при чужих — замолкает":"петь не будет — отшутится"}}},
 {id:"sounds",n:"Звуки без слов",f:(b)=>{const em=gv("sp.emotional"),hideAll=["emo.arousal.hide","emo.desire.hide","emo.irritation.hide","emo.joy.hide","emo.sadness.hide"].map(gv).reduce((a,x)=>a+x,0)/5;
   return {k:{speed:.5,energy:clamp(.3+em*.3),stab:.3,style:.8,breath:clamp(.5+b.breath*.4),pitch:.5,pause:.6},gate:clamp(.5+em*.3-hideAll*.4),note:"вздохи, выдохи, смешки, стоны — частота из sp.emotional, минус то, что персонаж прячет (emo.*.hide)"}}},
];
// Живые правила: канал dyn.* → что делает с голосом при срабатывании. Сила = peak × (1 − hide); порог/затухание — из генов канала
const LIVE_CH=[
 ["anger","гнев","emo.anger.hide",{energy:+.4,speed:+.2,stab:-.35,pitch:+.12}],
 ["fear","страх","emo.fear.hide",{speed:+.2,stab:-.4,pitch:+.15,energy:-.1}],
 ["sadness","печаль","emo.sadness.hide",{speed:-.2,energy:-.3,pitch:-.1,pause:+.25}],
 ["shame","стыд","emo.shame.hide",{energy:-.35,pause:+.3,stab:-.25,speed:-.1}],
 ["joy","радость","emo.joy.hide",{style:+.3,pitch:+.08,speed:+.1,energy:+.15}],
 ["interest","интерес","emo.interest.hide",{speed:+.15,style:+.15,pause:-.1}],
 ["tender","нежность","emo.tender.hide",{breath:+.3,energy:-.25,speed:-.15,pitch:-.03}],
 ["desire","влечение","emo.desire.hide",{breath:+.4,speed:-.2,energy:-.15,pitch:-.05}],
 ["disgust","отвращение","emo.disgust.hide",{style:+.2,speed:-.1,pitch:-.05,energy:-.1}],
 ["surprise","удивление","emo.surprise.hide",{pitch:+.2,pause:+.2,stab:-.2}],
 ["envy","зависть","emo.envy.hide",{style:+.1,energy:-.1,pitch:-.03}],
];
function liveRules(){return LIVE_CH.map(([ch,n,hid,eff])=>{const th=gv("dyn."+ch+".threshold"),pk=gv("dyn."+ch+".peak"),dc=gv("dyn."+ch+".decay"),dw=gv("dyn."+ch+".dwell"),hide=gk(hid)?clamp((gv(hid)+1)/2):0;
  const known=gk("dyn."+ch+".threshold")+gk("dyn."+ch+".peak")+gk("dyn."+ch+".decay")+gk(hid);
  // trig: от какого повода (0 — вспыхивает от любого, 1 — нужен серьёзный); force: сила в голосе; decay_s: секунды до возврата
  const trig=(th+1)/2,force=clamp(((pk+1)/2)*(1-hide*.85)),decay_s=Math.round(8*Math.pow(40,(1-dc)/2)),dwell=(dw+1)/2;
  return {ch,n,trig,force,decay_s,dwell,hide,known,eff}})}
// Движки: как крутилки и режимы превращаются в настройки конкретного TTS. Значения проверены по документации движков (09.2026)
const VOICE_ENGINES={
 eleven_v3:{n:"ElevenLabs v3 (облако)",ru:true,tags:{whisper:"[whispers]",anger:"[angry] [shouts]",intim:"[softly] [breathy]",play:"[laughs] / [chuckles] / [giggles]",sad:"[sad] [sighs]",sing:"[sings] / [humming]",sounds:"[sighs] [gasps] [exhales] [moans]",normal:""},
   map:(k)=>({stability:+(.15+k.stab*.7).toFixed(2),similarity_boost:.8,style:+(k.style*.85).toFixed(2),speed:+(.8+(k.speed-.5)*.6).toFixed(2)}),
   how:"теги в квадратных скобках прямо в тексте реплики; stability: ~0.3 «творческий», 0.5 «естественный», 0.9 «жёсткий». Пение и звуки — единственный движок, где [sings] работает без отдельной модели",lat:"~300 мс поток",lic:"платно, API"},
 fish_s1:{n:"OpenAudio S1 / Fish Speech (локально)",ru:true,tags:{whisper:"(whispering)",anger:"(angry) (shouting)",intim:"(soft tone) (panting)",play:"(laughing) / (chuckling) / (giggling)",sad:"(sad) (sighing) (sobbing)",sing:"— пения нет",sounds:"(sighing) (panting) (groaning) (gasping)",normal:""},
   map:(k)=>({temperature:+(.5+k.style*.4).toFixed(2),top_p:+(.6+k.stab*.3).toFixed(2),repetition_penalty:1.1,speed_hint:k.speed>.6?"(in a hurry tone)":k.speed<.4?"(slowly)":""}),
   how:"49 маркеров эмоций + маркеры тона и звуков в круглых скобках перед фразой; русский в списке 13 языков; 0.5B mini на 4–6 ГБ VRAM",lat:"~200 мс",lic:"CC-BY-NC-SA (некоммерч.)"},
 qwen3_tts:{n:"Qwen3-TTS VoiceDesign 1.7B (локально)",ru:true,tags:{whisper:"инструкция: «шёпотом, едва слышно»",anger:"«резко, зло, громко»",intim:"«тихо, низко, с придыханием»",play:"«со смешком, игриво»",sad:"«тихо, медленно, устало»",sing:"— пения нет (напевно, протяжно — лишь имитация)",sounds:"— только через текст («*вздох*» не гарантирован)",normal:""},
   map:(k)=>({instruct:qwenInstruct(k)}),
   how:"управление — текстовой инструкцией на естественном языке (тон, скорость, эмоция, характер голоса); тегов нет; русский среди 10 языков; поток от 97 мс, Apache-2.0",lat:"97 мс",lic:"Apache-2.0"},
 indextts2:{n:"IndexTTS2 (локально)",ru:false,tags:{whisper:"instruct «whispering» (тега нет)",anger:"emo_vector[angry]",intim:"emo_vector[calm]+instruct",play:"emo_vector[happy]",sad:"emo_vector[sad/melancholic]",sing:"— нет",sounds:"— нет",normal:"emo_vector[calm]"},
   map:(k)=>({emo_alpha:+(.4+k.style*.9).toFixed(2),duration_ratio:+(1.25-k.speed*.5).toFixed(2),emo_vector:"[happy, angry, sad, afraid, disgusted, melancholic, surprised, calm] — задаётся правилом канала"}),
   how:"8-мерный вектор эмоции + emo_alpha 0…1.4, точная длительность (duration), эмоция и тембр разделены (эмоцию можно взять с другого голоса). Русский официально не заявлен (zh/en)",lat:"не поток",lic:"открытая, некоммерч."},
 chatterbox:{n:"Chatterbox Multilingual v3 (локально)",ru:true,tags:{whisper:"— нет (только через exaggeration↓)",anger:"exaggeration↑",intim:"exaggeration↓ cfg↓",play:"[laugh] [chuckle] (Turbo, англ.)",sad:"exaggeration↓",sing:"— нет",sounds:"[cough] [laugh] (Turbo)",normal:""},
   map:(k)=>({exaggeration:+(.25+k.style*.7).toFixed(2),cfg_weight:+(.55-k.style*.3).toFixed(2),temperature:+(.6+(1-k.stab)*.3).toFixed(2)}),
   how:"две ручки: exaggeration (драма, 0.5 база, ≥0.7 — театр) и cfg_weight (0.3 для драмы, выше — точнее к референсу); русский в 23 языках; паралингвистика только в Turbo/Nano (англ.)",lat:"<200 мс Turbo",lic:"MIT"},
};
function qwenInstruct(k){const w=[];w.push(k.speed>.65?"быстро":k.speed<.35?"медленно, с растяжкой":"в среднем темпе");w.push(k.energy>.65?"громко, напористо":k.energy<.3?"тихо, почти шёпотом":"негромко");
  if(k.breath>.6)w.push("с придыханием");if(k.style>.65)w.push("очень выразительно, с широкими интонациями");else if(k.style<.35)w.push("ровно, сдержанно");
  if(k.stab<.35)w.push("голос дрожит, срывается");if(k.pause>.65)w.push("с долгими паузами");if(k.pitch>.58)w.push("выше обычного");if(k.pitch<.44)w.push("ниже обычного");return "Говори "+w.join(", ")+"."}
// Профиль голоса целиком — то, что уходит в TTS-подключение Сайки
function voiceProfile(P){const b=voiceBase(P);const eng=(typeof ST!=="undefined"&&ST.veng)||"eleven_v3";const E=VOICE_ENGINES[eng];
  const modes={};VOICE_MODES.forEach(m=>{const r=m.f(b);modes[m.id]={name:m.n,gate:+r.gate.toFixed(2),knobs:Object.fromEntries(Object.entries(r.k).map(([a,v])=>[a,+v.toFixed(2)])),tag:E.tags[m.id]||"",tags:Object.fromEntries(Object.entries(VOICE_ENGINES).map(([e,X])=>[e,X.tags[m.id]||""])),engine:E.map(r.k),note:r.note}});
  const live=liveRules().map(r=>({channel:r.ch,name:r.n,trigger:+r.trig.toFixed(2),force:+r.force.toFixed(2),decay_s:r.decay_s,dwell:+r.dwell.toFixed(2),hide:+r.hide.toFixed(2),known:r.known,effect:r.eff}));
  return {format:"saika-voice/1",char:CUR,name:CHAR.name,engine:eng,engine_name:E.n,russian:E.ru,embodiment:CHAR.voice||{},base:Object.fromEntries(Object.entries(b).map(([a,v])=>[a,+v.toFixed(2)])),modes,live,
   rule:"крутилки = base + Σ force_канала × effect_канала (канал активен, если повод ≥ trigger; гаснет за decay_s; при dwell > .6 возвращается сам). Режим (whisper/anger/…) выбирается контекстом реплики и накладывается поверх, если gate ≥ .4"}}
const KN=[["speed","скорость"],["energy","энергия"],["stab","устойч."],["style","выразит."],["breath","придых."],["pitch","высота"],["pause","паузы"]];
function renderVoice2(P){const el=document.getElementById("voice");const prof=voiceProfile(P);const E=VOICE_ENGINES[prof.engine];
  const box=document.createElement("div");box.className="vm";
  box.innerHTML=\`<div class="vmh"><div class="eyebrow">режимы голоса · из генома</div><div class="vmeng"><span class="eyebrow">движок</span><select id="vEng">\${Object.entries(VOICE_ENGINES).map(([k,e])=>\`<option value="\${k}" \${k===prof.engine?"selected":""}>\${e.n}\${e.ru?"":" · без русского"}</option>\`).join("")}</select></div></div>
  <div class="vmg"><div class="h"><span>режим</span>\${KN.map(k=>\`<span>\${k[1]}</span>\`).join("")}<span>свойствен</span><span>метка движка</span><span>почему так</span></div>
  \${Object.values(prof.modes).map(m=>\`<div class="\${m.gate<.4?'dim':''}"><span class="n">\${m.name}</span>\${KN.map(([k])=>\`<span class="b"><u><i style="width:\${Math.round(m.knobs[k]*100)}%"></i></u><em>\${m.knobs[k].toFixed(2)}</em></span>\`).join("")}<span class="g">\${m.gate.toFixed(2)}</span><span class="tg">\${m.tag||"—"}</span><span class="nt">\${m.note}</span></div>\`).join("")}</div>
  <div class="vmh" style="margin-top:22px"><div class="eyebrow">живые правила · контекст → крутилки · из каналов dyn.*</div><div class="eyebrow" style="letter-spacing:0;text-transform:none;color:var(--dim)">сила = пик × (1 − скрывает); серые — гены канала не сняты</div></div>
  <div class="vl"><div class="h"><span>канал</span><span>порог</span><span>сила в голосе</span><span>гаснет</span><span>возвращается</span><span>скрывает</span><span>эффект на голос</span></div>
  \${prof.live.map(r=>\`<div class="\${r.known?'':'dim'}"><span class="n">\${r.name}</span><span class="b"><u><i style="width:\${Math.round(r.trigger*100)}%"></i></u><em>\${r.trigger.toFixed(2)}</em></span><span class="b"><u><i style="width:\${Math.round(r.force*100)}%"></i></u><em>\${r.force.toFixed(2)}</em></span><span>\${r.known?r.decay_s+" с":"—"}</span><span>\${r.known?(r.dwell>.6?"сам":"нет"):"—"}</span><span>\${r.hide.toFixed(2)}</span><span class="nt">\${Object.entries(r.effect).map(([k,v])=>KN.find(x=>x[0]===k)[1]+(v>0?" +":" −")+Math.abs(v).toFixed(2)).join(" · ")}</span></div>\`).join("")}</div>
  <div class="vmf"><div class="nt"><b>\${E.n}</b> · \${E.how} · задержка \${E.lat} · \${E.lic}</div><button class="gold" id="vDl">профиль голоса → JSON</button></div>\`;
  el.appendChild(box);
  const sel=box.querySelector("#vEng");sel.onchange=()=>{ST.veng=sel.value;saveState({veng:sel.value});renderVoice()};if(typeof ddWrap==="function")ddWrap(sel);
  box.querySelector("#vDl").onclick=()=>{const a=document.createElement("a");a.href="data:application/json;charset=utf-8,"+encodeURIComponent(JSON.stringify(prof,null,1));a.download="voice_"+(CUR||"char")+".json";a.click()};
  // в промпт справа — режимы и настройки движка
  const pre=el.querySelector(".vpre");if(pre){const L=[];L.push("## Режимы ("+E.n+")");Object.values(prof.modes).forEach(m=>{if(m.gate<.4)return;L.push("- "+m.name.toLowerCase()+": "+Object.entries(m.engine).map(([k,v])=>k+" "+(typeof v==="string"?"«"+v+"»":v)).join(" · ")+(m.tag?" · "+m.tag:""))});
    L.push("## Живые правила");prof.live.filter(r=>r.known).sort((a,b)=>b.force-a.force).slice(0,5).forEach(r=>L.push("- "+r.name+": порог "+r.trigger.toFixed(2)+", сила "+r.force.toFixed(2)+", гаснет за "+r.decay_s+" с → "+Object.entries(r.effect).map(([k,v])=>k+(v>0?"+":"")+v).join(" ")));
    pre.innerHTML+="\\n"+L.join("\\n").replace(/^(#+ .*)$/gm,"<b>$1</b>");const cnt=el.querySelector(".eyebrow span");if(cnt)cnt.textContent=(pre.textContent.split("\\n").length)+" строк"}
}
const renderVoice0=renderVoice;renderVoice=function(){renderVoice0();const P=VOICE_PARAMS.map(p=>Object.assign({n:p[0]},voiceParam(p)));renderVoice2(P)};
renderVoice();

// ---------- архетипы: библиотека независимых типов`);

// [2] стили
rep(`.vp{display:grid;gap:3px}`,`.vp{display:grid;gap:3px}
.vm{grid-column:1/-1;margin-top:26px;padding-top:18px;border-top:1px solid var(--hair)}
.vmh{display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;gap:20px}.vmeng{display:flex;align-items:center;gap:12px}.vmeng .dd{width:340px}
.vmg,.vl{display:grid;gap:4px}
.vmg div{display:grid;grid-template-columns:110px repeat(7,84px) 60px 190px 1fr;gap:10px;align-items:center;font:10.5px var(--fm);color:var(--muted);min-height:18px}
.vl div{display:grid;grid-template-columns:110px 120px 120px 60px 84px 60px 1fr;gap:10px;align-items:center;font:10.5px var(--fm);color:var(--muted);min-height:18px}
.vmg div.h,.vl div.h{color:var(--dim);letter-spacing:.1em;text-transform:uppercase;font-size:9.5px}
.vmg .n,.vl .n{color:var(--text)}.vmg .dim,.vl .dim{color:var(--dim)}.vmg .dim .n,.vl .dim .n{color:var(--dim)}
.vmg .b,.vl .b{display:flex;align-items:center;gap:6px}.vmg .b u,.vl .b u{position:relative;flex:1;height:2px;background:var(--hair2);text-decoration:none}.vmg .b i,.vl .b i{position:absolute;left:0;top:0;height:2px;background:var(--gold)}.vmg .dim .b i,.vl .dim .b i{background:var(--hair2)}
.vmg .b em,.vl .b em{font-style:normal;flex:none;width:26px;text-align:right;font-size:9.5px;color:var(--muted)}.vmg .dim .b em,.vl .dim .b em{color:var(--dim)}
#voice.inner{grid-template-rows:auto auto auto auto!important;height:auto;overflow:visible}#voice.inner>div{min-height:auto}#voice .colscroll{max-height:none;overflow:visible}
.vmg .g{color:var(--text)}.vmg .tg{color:var(--gold);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.vmg .nt,.vl .nt{color:var(--dim);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.vmf{display:flex;justify-content:space-between;align-items:center;gap:20px;margin-top:18px}.vmf .nt{font:11px var(--fm);color:var(--dim);white-space:normal;max-width:1200px}
.vmf button.gold{flex:none}`);
fs.writeFileSync("gs.html",t);console.log("voice2 ok");
