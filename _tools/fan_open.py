# -*- coding: utf-8 -*-
"""Раскрытие панели ВЕЕРОМ по кругу — так, как просил владелец."""
import io, sys
p = sys.argv[1]
s = io.open(p, encoding='utf-8').read()

# ── 1. CSS: убрать «выход из глубины», поставить веер ─────────────────────
a = """/* РАСКРЫТИЕ ОРГАНА (просьба владельца 2026-08-22): панель не просто
   вырастает в плоскости, а ВЫХОДИТ ИЗ ГЛУБИНЫ вперёд — сначала сцена
   вдавливается (body.zpress ниже), затем блок поднимается на зрителя и
   занимает всю площадь центрального блока. Кадр 72% — лёгкий перелёт
   вперёд: без него движение читается как «подъехало», а не «вышло». */
@keyframes zp-rise{
  0%  {opacity:0; transform:translateZ(-150px) scale(.46)}
  36% {opacity:1; transform:translateZ(-30px)  scale(.78)}
  72% {           transform:translateZ(30px)   scale(1.035)}
  100%{           transform:translateZ(0)      scale(1)}}
body.zpanel #zpanel{opacity:1;transform:none;pointer-events:auto;
  animation:zp-rise .52s var(--zease) both}"""
b = """/* ═══ РАСКРЫТИЕ ВЕЕРОМ (27.08.2026, владелец, объяснено много раз) ═══
   «Есть передние блоки. При нажатии её правая грань как бы вдоль всех
   панелей по кругу развернулась и на полный экран, как веером, раскрыла
   свою внутреннюю страницу.»

   То есть движение НЕ вырастание из точки и НЕ выход из глубины. Сектор
   остаётся сектором и РАСТЁТ ПО УГЛУ: его правая грань — та радиальная
   линия, что отделяет его от соседа по часовой стрелке, — стоит на месте,
   а левая едет по кругу мимо всех остальных секторов, пока клин не
   замкнётся на полные 360° и не закроет собой весь экран. Страница
   проявляется внутри растущего клина, а не под ним.

   Делается конической маской из центра шара: угол начала --za берём у
   самого сектора, а --zsw (сколько градусов уже развернулось) гоним от
   нуля до полного оборота. @property нужен, чтобы браузер умел
   анимировать угол внутри градиента, а не прыгал по кадрам. */
@property --zsw{syntax:'<angle>';initial-value:0deg;inherits:false}
@keyframes zp-fan{
  from{--zsw:1deg}
  to  {--zsw:360deg}}
@keyframes zp-fan-fade{from{opacity:0}to{opacity:1}}
body.zpanel #zpanel{opacity:1;transform:none;pointer-events:auto;
  --za:0deg; --zcx:50%; --zcy:50%;
  -webkit-mask-image:conic-gradient(from var(--za) at var(--zcx) var(--zcy),
    #000 0 calc(var(--zsw) - .8deg), transparent var(--zsw));
  mask-image:conic-gradient(from var(--za) at var(--zcx) var(--zcy),
    #000 0 calc(var(--zsw) - .8deg), transparent var(--zsw));
  animation:zp-fan .60s cubic-bezier(.22,.7,.24,1) both,
            zp-fan-fade .16s linear both}
/* веер отработал — маска больше не нужна: с ней каждый кадр прокрутки
   пересчитывает конический градиент во весь экран */
body.zpanel #zpanel.zp-done{-webkit-mask-image:none;mask-image:none;
  animation:none}
/* закрытие — тот же веер назад, чтобы уход читался как складывание */
body.zpclosing #zpanel{opacity:1;pointer-events:none;
  -webkit-mask-image:conic-gradient(from var(--za) at var(--zcx) var(--zcy),
    #000 0 calc(var(--zsw) - .8deg), transparent var(--zsw));
  mask-image:conic-gradient(from var(--za) at var(--zcx) var(--zcy),
    #000 0 calc(var(--zsw) - .8deg), transparent var(--zsw));
  animation:zp-fan .30s cubic-bezier(.4,0,.7,1) reverse both}"""
assert s.count(a) == 1, 'css rise'
s = s.replace(a, b)

# ── 2. openPanel: угол сектора, центр шара, кадр под анимацию ─────────────
a2 = """  zpFit();
  zpEl.style.transformOrigin = cx + 'px ' + cy + 'px';
  SFX.open();"""
b2 = """  zpFit();
  /* УГОЛ ВЕЕРА БЕРЁМ У САМОГО СЕКТОРА. В разметке сектора угол считается
     от оси X и растёт вниз-вправо (глаза -90 — вверх), а конический
     градиент отсчитывает от 12 часов по часовой. Отсюда +90. Ещё -SPAN/2 —
     это и есть та самая «правая грань»: с неё веер начинает разворот. */
  try {
    const SP = (typeof SPAN === 'number' ? SPAN : 60);
    zpEl.style.setProperty('--za', ((z.a - SP / 2) + 90).toFixed(1) + 'deg');
    zpEl.style.setProperty('--zcx', CX.toFixed(1) + 'px');
    zpEl.style.setProperty('--zcy', CY.toFixed(1) + 'px');
  } catch(e){}
  zpEl.classList.remove('zp-done');
  zpEl.style.transformOrigin = cx + 'px ' + cy + 'px';
  SFX.open();"""
assert s.count(a2) == 1, 'openPanel geom'
s = s.replace(a2, b2)

# запуск анимации отдельным кадром: иначе первые кадры съедает сборка
# содержимого панели, и веер выглядит как рывок
a3 = """  document.body.classList.add('zpanel');
  zpTick();"""
b3 = """  /* СНАЧАЛА СОБРАЛИ, ПОТОМ ПОЕХАЛИ (27.08.2026, владелец: «открывается с
     повисанием»). Сборка содержимого — это сотни узлов, стили и иногда
     тяжёлый iframe; если включить анимацию в том же кадре, браузер тратит
     первые 200 мс на вёрстку, и веер начинается рывком с середины. Ждём
     два кадра: к этому моменту раскладка посчитана и движение идёт ровно. */
  document.body.classList.remove('zpclosing');
  requestAnimationFrame(() => requestAnimationFrame(() => {
    if (zpOpen !== z.id) return;
    document.body.classList.add('zpanel');
    clearTimeout(zpDoneT);
    zpDoneT = setTimeout(() => {
      if (zpOpen === z.id) zpEl.classList.add('zp-done');
    }, 640);
  }));
  zpTick();"""
assert s.count(a3) == 1, 'openPanel raf'
s = s.replace(a3, b3)

# ── 3. closePanel: складываем веер назад ──────────────────────────────────
a4 = """  SFX.close();
  document.body.classList.remove('zpanel');"""
b4 = """  SFX.close();
  clearTimeout(zpDoneT);
  zpEl.classList.remove('zp-done');
  document.body.classList.add('zpclosing');
  setTimeout(() => {
    document.body.classList.remove('zpanel', 'zpclosing');
  }, 300);"""
assert s.count(a4) == 1, 'closePanel'
s = s.replace(a4, b4)

# ── 4. таймер «веер доехал» ───────────────────────────────────────────────
a5 = "let zpEl=null, zpBody=null, zpOpen=null, zpZone=null, zpTimer=0, zpGen=0,"
b5 = "let zpDoneT=0;\nlet zpEl=null, zpBody=null, zpOpen=null, zpZone=null, zpTimer=0, zpGen=0,"
assert s.count(a5) == 1, 'vars'
s = s.replace(a5, b5)

io.open(p, 'w', encoding='utf-8').write(s)
print('ok')
