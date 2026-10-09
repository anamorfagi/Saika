// v1.1g: пятое семейство «стиль привязанности», отпечаток — лучший из каждого семейства, условие содержания у «добрых» типажей, чистая вёрстка превращений и низа списка
const fs=require("fs");
let t=fs.readFileSync("gs.html","utf8");
function rep(a,b){if(!t.includes(a)){console.error("NOT FOUND:",a.slice(0,80));process.exit(1)}t=t.replace(a,b)}

// ---- [1] темперамент: классическая четвёрка по осям Айзенка (активация × устойчивость) на модуляторах и динамике каналов ----
const TEMP=`
 // ---- стиль привязанности: Боулби — Эйнсворт — Бартоломью; как персонаж ведёт себя в близости, при разлуке, игноре, ревности ----
 {n:"Надёжный",fam:"привяз",d:"Близость не пугает и разлука не ломает: доверяет по опыту, говорит о чувствах прямо, прощает, не требует постоянных подтверждений; конфликт — повод поговорить, не катастрофа.",
  c:[["bond.depth",.2,1],["bond.reject_fear",-1,0],["bond.separation",-1,.1],["bond.confirm_need",-1,.2],["bond.forgive",.2,1],["soc.self_disclose",.1,1],["def.withdraw",-1,.1],["ct.feel_speech_gap",-1,.2],["bond.trust_speed",-.2,.6]]},
 {n:"Тревожный",fam:"привяз",d:"Озабоченный тип: боится отвержения и замены, чувствует любое отдаление, ждёт подтверждений, разлука невыносима; идеализирует партнёра, себя ценит через него.",
  c:[["bond.reject_fear",.4,1],["bond.confirm_need",.4,1],["bond.distance_sens",.4,1],["bond.ignore_sens",.4,1],["bond.separation",.3,1],["bond.replace_fear",.3,1],["bond.idealize",.2,1],["self.worth",-1,.1]]},
 {n:"Избегающий",fam:"привяз",d:"Отстранённый тип: дистанция как норма, личного не раскрывает, при сближении отступает, нежность прячет, автономия важнее близости; разлуку переносит легко — слишком легко.",
  c:[["bond.depth",-1,0],["soc.self_disclose",-1,-.3],["def.withdraw",.3,1],["mot.closeness",-1,0],["bond.confirm_need",-1,-.2],["bond.separation",-1,-.2],["emo.tender.hide",.3,1],["mot.autonomy",.3,1]]},
 {n:"Тревожно-избегающий",fam:"привяз",d:"Дезорганизованный тип: хочет близости и боится её одновременно — тянется и отталкивает, доверяет медленно, под стрессом откатывается; конфликт «хочу/боюсь» не выдерживает.",
  c:[["bond.reject_fear",.4,1],["bond.depth",.3,1],["def.withdraw",.3,1],["def.attack",.2,1],["soc.self_disclose",-1,-.2],["bond.trust_speed",-1,-.3],["ct.conflict_tol",-1,0],["dev.regress",.2,1]]},
 {n:"Опекающий",fam:"привяз",d:"Навязчивая забота по Боулби: близость через нужность — опекает, защищает, вмешивается сама; ценит себя настолько, насколько полезна; отказ от помощи ранит сильнее ссоры.",
  c:[["soc.caring",.5,1],["mot.protect",.4,1],["need.nurturing.weight",.4,1],["bond.depth",.3,1],["mot.useful",.3,1],["self.worth",-1,.2],["ag.init_unasked",.2,1],["soc.boundaries",-1,.2]]},
 {n:"Непривязанный",fam:"привяз",d:"Привязанности как таковой нет: близость не ищет, разлуку не замечает, потребность в людях низкая — не «надёжный», а вне шкалы. Стиль применим только когда связь вообще есть.",
  c:[["bond.depth",-1,-.3],["mot.closeness",-1,0],["bond.separation",-1,-.3],["need.affiliation.weight",-1,-.3],["bond.confirm_need",-1,0],["mem.sig_closeness",-1,0]]},
`;
rep(`const SIGS=[`,`const SIGS=[${TEMP}`);
rep(`const FAM={"дере":"аниме-типаж","роль":"социальная роль","тёмный":"тёмный тип","ум":"склад ума"};`,
    `const FAM={"дере":"аниме-типаж","роль":"социальная роль","тёмный":"тёмный тип","ум":"склад ума","привяз":"стиль привязанности"};`);
rep(`function famColor(f){return f==="дере"?"#c9a86e":f==="роль"?"#7aa6c2":f==="ум"?"#a78bd8":"#d52a42"}`,
    `function famColor(f){return f==="дере"?"#c9a86e":f==="роль"?"#7aa6c2":f==="ум"?"#a78bd8":f==="привяз"?"#5fbfb0":"#d52a42"}`);

// ---- [2] отпечаток: лучший тип из каждого семейства, по убыванию; клик — открыть ----
rep(`const top=ranked.slice(0,5);const sum=top.reduce((a,r)=>a+r.m.score,0)||1;`,
    `const top=Object.keys(FAM).map(f=>ranked.find(r=>r.s.fam===f)).filter(Boolean).sort((a,b)=>b.m.score-a.m.score);const sum=top.reduce((a,r)=>a+r.m.score,0)||1;`);
rep(`<div class="fp"><span class="t">Отпечаток</span><div class="fpbar">\${top.map(r=>\`<i style="flex:\${r.m.score/sum};background:\${famColor(r.s.fam)}" title="\${r.s.n} \${Math.round(r.m.score*100)}%"><b>\${r.s.n}</b> \${Math.round(r.m.score*100)}%</i>\`).join("")}</div></div>`,
    `<div class="fp"><span class="t">Отпечаток</span><div class="fpbar">\${top.map(r=>\`<i data-fp="\${r.i}" style="flex:\${r.m.score/sum};background:\${famColor(r.s.fam)}" title="\${FAM[r.s.fam]}: \${r.s.n} \${Math.round(r.m.score*100)}%"><b>\${r.s.n}</b> \${Math.round(r.m.score*100)}%</i>\`).join("")}</div></div>`);
rep(`.fpbar i{display:flex;`,`.fpbar i{cursor:pointer;display:flex;`);
// обработчик клика по сегменту — рядом с обработчиком строк списка
rep(`document.querySelectorAll(".rk").forEach(b=>b.onclick=`,`document.querySelectorAll(".fpbar i").forEach(b=>b.onclick=()=>{archSel=+b.dataset.fp;saveState({arch:archSel});renderArch()});
  document.querySelectorAll(".rk").forEach(b=>b.onclick=`);

// ---- [3] «добрые» типажи: форма без содержания не проходит ----
rep(`["will.persist",.4,1],["emo.anger.hide",.4,1],["mor.promise",.4,1]]},`,`["will.persist",.4,1],["emo.anger.hide",.4,1],["mor.promise",.4,1],["mor.wellbeing",.3,1],["dark.callous",-1,0]]},`);

// ---- [4] превращения на трассе: своя сетка без пустых колонок ----
rep(`<div class="acts"><div class="h"><span>правило</span><span></span><span></span><span>доля</span><span></span></div>\${RULES.filter(r=>r.conv)`,
    `<div class="acts conv"><div class="h"><span>правило</span><span>доля</span><span></span></div>\${RULES.filter(r=>r.conv)`);
rep(`<span>\${r.id} · \${CHN[r.conv[0]]} → \${CHN[r.conv[1]]}</span><span></span><span></span><span>\${v.toFixed(2)}</span>`,
    `<span>\${r.id} · \${CHN[r.conv[0]]} → \${CHN[r.conv[1]]}</span><span>\${v.toFixed(2)}</span>`);
rep(`.acts div.veto{color:var(--blood2)}`,`.acts div.veto{color:var(--blood2)}
.acts.conv div{grid-template-columns:260px 60px 220px}
.acts.conv div span:last-child{height:2px;background:var(--hair2);position:relative}
.rank{padding-bottom:40px;mask-image:linear-gradient(#000 calc(100% - 48px),transparent);-webkit-mask-image:linear-gradient(#000 calc(100% - 48px),transparent)}`);

fs.writeFileSync("gs.html",t);console.log("fam5 ok");
