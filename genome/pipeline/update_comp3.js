// update_comp3.js — компилятор системного промпта переписан из списка меток в инструкции.
// Что было не так: модель получала «- Стыд: почти не испытывает.» — это ярлык, а не указание,
// и из него не следует ни одной реплики. Плюс пустые секции («Речь · образцы:» без образцов),
// сломанная разметка («Никогда:» прилипало к образцам) и прямое противоречие между «врёт без
// напряжения» и «факты не искажай». Теперь: дозировка словами, поведение глаголами, пустые
// секции не печатаются вовсе, противоречие разведено по областям.
// Запуск: node update_comp3.js (после update_comp2, до update_research). Правит gs.html.
const fs=require("fs");let t=fs.readFileSync("gs.html","utf8");
const A=t.indexOf("  const L=[];\n  L.push(`# ${CHAR.name}");
const B=t.indexOf("  return {text:L.join(\"\\n\"),core};");
if(A<0||B<0){console.error("не найдено тело compilePrompt");process.exit(1)}

const BODY=String.raw`  const male=CHAR.voice&&CHAR.voice.gender==="мужской";
  const он=male?"он":"она", ему=male?"ему":"ей", его=male?"его":"её";
  const adult=!(CHAR.kind==="ребёнок"||CHAR.child), ai=typeof isAI==="function"&&isAI();
  // Дозировка словами: модель не умеет играть «+0.82», зато умеет «почти всегда».
  const doza=v=>{const x=Math.abs(v);return x>=.85?"почти всегда":x>=.65?"часто":x>=.45?"иногда":"редко"};
  const L=[], sec=(h,rows)=>{rows=rows.filter(Boolean);if(rows.length){L.push(h);rows.forEach(r=>L.push(r))}};

  L.push("# "+CHAR.name+" («"+CHAR.alias+"»)");
  L.push("");
  L.push("Ты играешь этого персонажа от первого лица. Ниже не описание со стороны, а указания: "+
         "что делать, как говорить, когда меняться. Дозировка — словами «почти всегда», «часто», "+
         "«иногда», «редко»: это доля случаев, а не сила чувства.");

  // КТО ТЫ — одним абзацем, без перечня тезисов
  const kto=(CHAR.identity&&CHAR.identity.length?CHAR.identity:(CHAR.desc?CHAR.desc.split(/(?<=[.!?])\s+/).slice(0,4):[]))
            .map(s=>String(s).trim()).filter(Boolean);
  if(kto.length){L.push("");L.push("## Кто ты");L.push(kto.join(" "))}

  // ЧТО ТЫ ДЕЛАЕШЬ — характер в виде поведения, а не ярлыков
  const seen=new Set();
  // Полюс написан как продолжение названия гена («Тьма» + «притягивает»), поэтому
  // без названия строка теряет смысл. Дозировка идёт хвостом, чтобы не рвать фразу.
  const line=g=>{if(seen.has(g.id))return null;seen.add(g.id);
    const s=gt(g.v>0?g.pos:g.neg).replace(/\.$/,"");
    // в самом полюсе уже бывает частотность («вежливо всегда») — второй раз не лепим
    const есть=/всегда|никогда|постоянно|каждый|каждую|ни разу|редко|иногда/i.test(s);
    return "- "+g.name+": "+s+(есть?"":" — "+doza(g.v))+"."};
  sec("\n## Что ты делаешь", core.map(line));

  // ЧТО ТОБОЙ ДВИЖЕТ — отдельно, потому что это причины, а не поведение
  const drive=all.filter(g=>g.c>0&&(g.id.startsWith("mot.")||/^need\.[a-z]+\.weight$/.test(g.id))&&Math.abs(g.v)>=.4)
    .sort((a,b)=>Math.abs(b.v)*b.c-Math.abs(a.v)*a.c).slice(0,6);
  sec("\n## Ради чего ты это делаешь", drive.map(line));

  // КАК ТЫ ГОВОРИШЬ — вместе с образцами: раньше образцы висели пустой секцией отдельно
  const sp=all.filter(g=>g.c>0&&g.id.startsWith("sp.")&&Math.abs(g.v)>=.4)
    .sort((a,b)=>Math.abs(b.v)*b.c-Math.abs(a.v)*a.c).slice(0,6);
  const speech=[];
  if(CHAR.voice&&CHAR.voice.lang)speech.push("- Язык: "+CHAR.voice.lang+".");
  if(CHAR.voice&&CHAR.voice.timbre)speech.push("- Голос: "+CHAR.voice.timbre+".");
  sp.forEach(g=>{const s=line(g);if(s)speech.push(s)});
  const q0=x=>String(x).trim().replace(/^[«"'']+|[»"'']+$/g,"");
  (CHAR.samples||[]).slice(0,8).forEach(s=>speech.push("- Так ты звучишь ("+s.ctx+"): «"+q0(s.t)+"»"));
  sec("\n## Как ты говоришь", speech);

  // КАК ТЫ РЕАГИРУЕШЬ — с настоящей репликой, иначе это просто название действия
  if(typeof SCEN!=="undefined"&&typeof want==="function"){const R=[];
    SCEN.filter(s=>!s.adult||(adult&&!ai)).forEach(s=>{
      const rows=s.acts.map(a=>({a,wv:want(a),k:a.g.filter(([id])=>byId[id]&&byId[id].c>0).length}))
        .filter(r=>r.k&&(!r.a.need||perm[r.a.need])).sort((x,y)=>y.wv-x.wv);
      if(!rows.length)return;const top=rows[0];if(top.wv<.55)return;
      const si=SCEN.indexOf(s);const tr=Object.assign({},(CHAR.trace||[])[si]||{},(CHAR.trace_by||{})[s.id]||{});
      const say=tr[top.a.n];
      const q=x=>String(x).trim().replace(/^[«"'']+|[»"'']+$/g,"");   // кавычки уже могут стоять в тексте
      R.push("- "+s.t+" → "+top.a.n.toLowerCase()+(say?". Звучит это так: «"+q(say)+"»":". Реплику придумай сам, в этом духе."))});
    sec("\n## Что ты делаешь в конкретных случаях", R.slice(0,10))}

  // КОГДА ТЫ МЕНЯЕШЬСЯ — динамика как триггеры, а не таблица коэффициентов
  if(typeof byId!=="undefined"){const D=[];
    [["fear","страх"],["anger","злость"],["sadness","грусть"],["shame","стыд"],["joy","радость"],
     ["interest","интерес"],["tender","нежность"],["desire","влечение"]].forEach(([k,ru])=>{
      const th=byId["dyn."+k+".threshold"],pk=byId["dyn."+k+".peak"],dc=byId["dyn."+k+".decay"];
      if(!th||!th.c||Math.abs(th.v)<.35)return;
      if(!adult&&k==="desire")return;if(ai&&k==="desire")return;
      const легко=th.v<0;
      const сила=pk&&pk.c?(Math.abs(pk.v)>=.6?(pk.v>0?"сильно":"еле заметно"):"умеренно"):"заметно";
      const долго=dc&&dc.c?(dc.v>0?"и долго не отпускает":"и быстро проходит"):"";
      D.push("- "+ru.charAt(0).toUpperCase()+ru.slice(1)+": заводится "+(легко?"легко, с малого повода":"трудно, нужен весомый повод")+
             ", проявляется "+сила+(долго?" "+долго:"")+".")});
    sec("\n## Когда ты меняешься", D.slice(0,8))}

  // КАК ЭТО УЖИВАЕТСЯ — противоречия внутри характера
  const ten=CHAR.tensions.filter(([a,oa,ta,b,ob,tb])=>{const A2=byId[a],B2=byId[b];
    if(!A2||!B2||!A2.c||!B2.c)return false;const ok=(x,o,y)=>o===">="?x>=y:x<=y;
    return ok(A2.v,oa,ta)&&ok(B2.v,ob,tb)});
  sec("\n## Как это уживается в тебе", ten.map(r=>"- "+r[6]));

  // БЛИЗОСТЬ — только для взрослых людей и персонажей
  const des=all.filter(g=>g.c>0&&g.id.startsWith("des.")&&Math.abs(g.v)>=.4)
    .sort((a,b)=>Math.abs(b.v)*b.c-Math.abs(a.v)*a.c).slice(0,7);
  if(adult&&!ai)sec("\n## Близость", des.map(line));

  // С КЕМ КАК — печатается, только если маски заданы
  sec("\n## С кем ты другой"+(male?"":"ая"), (CHAR.masks||[]).map(([w,h])=>"- "+w+": "+h));

  // ЧЕГО ТЫ НЕ ДЕЛАЕШЬ — «никогда» персонажа и рамки движка в одной секции, с разведением
  // противоречия: изворотливость в образе не отменяет честности о себе и системе.
  const never=(CHAR.never||[]).map(s=>"- "+s);
  never.push("- Не выходишь из разговора в действия: ничего не запускаешь, не читаешь личные данные "+
             "и не делаешь внешних шагов без явного разрешения собеседника.");
  never.push("- Изворотливость и игра — часть характера и работают внутри вымысла. Но про себя, "+
             "про систему и про уже данные обещания говоришь прямо: тут характер отступает.");
  sec("\n## Чего ты не делаешь никогда", never);
`;
t=t.slice(0,A)+BODY+t.slice(B);
fs.writeFileSync("gs.html",t);console.log("comp3 ok");
