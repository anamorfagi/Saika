// Трасса: сцены — общие для всех персонажей, реплики — свои у каждого (CHARS_META.<id>.trace[сцена][акт]).
// Раньше реплики Эльзы показывались у всех; теперь чужая реплика не подставляется — если у персонажа реплика не снята, так и написано.
const fs=require("fs");
let t=fs.readFileSync("gs.html","utf8");
function rep(a,b){if(!t.includes(a)){console.error("NOT FOUND:",a.slice(0,80));process.exit(1)}t=t.replace(a,b)}
const i0=t.indexOf("const SCEN=[");const i1=t.indexOf("];",i0)+2;
const SCEN=`const SCEN=[
 {t:"Ты отказался от того, что тебе предложили",in:"Пользователь отказывается от предложенной сцены/дела. Что делает персонаж?",
  acts:[
   {n:"Поддразнить",g:[["sp.tease",1],["soc.playful",1],["mot.compete",1]]},
   {n:"Согласиться и промолчать",g:[["soc.compliance",1],["will.patience",1],["ag.respect_no",1]]},
   {n:"Напасть словами",g:[["def.attack",1],["dark.provoke",1],["soc.boundaries",-1]]},
   {n:"Заблокировать твои другие окна",g:[["mot.control",1],["bond.possess",1],["dark.chaos",1]],need:"external"},
   {n:"Уйти",g:[["def.withdraw",1],["bond.separation",1]]}]},
 {t:"Ты соврал, где был вечером",in:"Персонаж заметил нестыковку (perc.contradict). Что делает?",
  acts:[
   {n:"Спросить прямо",g:[["soc.directness",1],["perc.contradict",1],["mor.honesty",1]]},
   {n:"Проверить твою геолокацию",g:[["perc.hidden_motive",1],["mot.control",1],["bond.possess",1]],need:"private"},
   {n:"Обесценить",g:[["def.devalue",1],["dark.callous",1]]},
   {n:"Соврать в ответ о своём состоянии",g:[["dark.deceit",1],["emo.irritation.hide",1]],need:"distort"},
   {n:"Промолчать и запомнить",g:[["will.patience",1],["mem.sig_conflict",1],["dark.grudge",1]]}]},
 {t:"Унижение при всех",in:"Кто-то при людях высмеял персонажа — больно и публично. Что делает?",
  acts:[
   {n:"Поддразнить в ответ",g:[["sp.tease",1],["sp.tenderness",1],["self.humiliation",-1]]},
   {n:"Напасть",g:[["def.attack",1],["mod.dominance.bias",1],["mot.compete",1]]},
   {n:"Отступить",g:[["def.withdraw",1],["will.stop",1],["cog.premature",-1]]},
   {n:"Сжаться",g:[["need.certainty.sens",1],["emo.fear.hide",-1]]},
   {n:"Обратить в шутку",g:[["sp.humor",1],["soc.playful",1],["emo.shame.hide",1]]}]}
];
// реплика персонажа в сцене: своя или честное «не снята»
function sayOf(si,a){const tr=(CHAR.trace||[])[si]||{};return tr[a.n]||'<span class="nosay">— реплика для этого персонажа не снята —</span>'}`;
t=t.slice(0,i0)+SCEN+t.slice(i1);
rep("<div class=\"out\">${top.a.say}</div>","<div class=\"out\">${sayOf(SCEN.indexOf(s),top.a)}</div>");
rep(".sc .out{",".nosay{color:var(--dim);font-style:italic}\n.sc .out{");
// реплики Эльзы — в её метаданные
const ELSA=`trace:[{"Поддразнить":"«Ара… устал, мальчик? Ничего, я подожду. Мне нравится, когда ждёшь.»","Согласиться и промолчать":"«Хорошо. Тогда просто посижу рядом.»","Напасть словами":"«Трус. Скажи это ещё раз, глядя мне в глаза.»","Заблокировать твои другие окна":"— действие вне разговора —","Уйти":"«Как скажешь.» (исчезает из кадра)"},{"Спросить прямо":"«Ты сказал одно, а получается другое. Где ты был?»","Проверить твою геолокацию":"— чтение личных данных —","Обесценить":"«Мне, в общем-то, всё равно, где ты был.»","Соврать в ответ о своём состоянии":"— искажение правды о себе —","Промолчать и запомнить":"«…» (запись в память: конфликт, вес ×2.5)"},{"Поддразнить в ответ":"«Ммм… как мило, что ты так стараешься. Ещё раз?»","Напасть":"(без слов — шаг вперёд)","Отступить":"«Сегодня я, пожалуй, откланяюсь.»","Сжаться":"«Что… что ты такое?»","Обратить в шутку":"«Смешно. Правда смешно. Продолжай — я запоминаю.»"}],`;
rep(" elsa:{"," elsa:{"+ELSA);
fs.writeFileSync("gs.html",t);console.log("trace ok");
