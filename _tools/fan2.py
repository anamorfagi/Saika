# -*- coding: utf-8 -*-
"""Веер строим руками по кадрам: маска из conic-gradient не анимируется."""
import io, sys
p = sys.argv[1]
s = io.open(p, encoding='utf-8').read()

# ── CSS: снять маску, оставить чистый холст под JS-клип ───────────────────
i = s.index("/* ═══ РАСКРЫТИЕ ВЕЕРОМ (27.08.2026")
j = s.index("/* ВДАВЛИВАНИЕ ПОД ПАЛЬЦЕМ", i)
css = """/* ═══ РАСКРЫТИЕ ВЕЕРОМ (27.08.2026, владелец, объяснено много раз) ═══
   «Есть передние блоки. При нажатии её правая грань как бы вдоль всех
   панелей по кругу развернулась и на полный экран, как веером, раскрыла
   свою внутреннюю страницу.»

   Движение — не вырастание из точки и не выход из глубины. Сектор
   остаётся клином и РАСТЁТ ПО УГЛУ: правая грань (радиальная линия, что
   отделяет его от соседа) стоит, левая едет по кругу мимо всех остальных
   секторов, пока клин не замкнётся на 360° и не закроет экран. Страница
   проявляется внутри клина.

   Сам клин рисует JS (zpFan ниже) через clip-path: polygon. Первая версия
   делала это конической маской с анимацией угла — и она НЕ РАБОТАЛА:
   произвольное свойство без @property браузер анимирует ступенькой, клин
   полкадра стоял ниткой, потом прыгал на весь экран. Снаружи это и
   выглядело как «кривое открытие». Полигон честно пересчитывается каждый
   кадр и врать не умеет. */
body.zpanel #zpanel{opacity:1;transform:none;pointer-events:auto;
  animation:none}
body.zpclosing #zpanel{opacity:1;pointer-events:none}

"""
s = s[:i] + css + s[j:]

# ── openPanel: угол сектора вместо CSS-переменных ─────────────────────────
a2 = """  try {
    const SP = (typeof SPAN === 'number' ? SPAN : 60);
    zpEl.style.setProperty('--za', ((z.a - SP / 2) + 90).toFixed(1) + 'deg');
    zpEl.style.setProperty('--zcx', CX.toFixed(1) + 'px');
    zpEl.style.setProperty('--zcy', CY.toFixed(1) + 'px');
  } catch(e){}
  zpEl.classList.remove('zp-done');
"""
b2 = ""
assert s.count(a2) == 1, 'old vars'
s = s.replace(a2, b2)

a3 = """  document.body.classList.remove('zpclosing');
  requestAnimationFrame(() => requestAnimationFrame(() => {
    if (zpOpen !== z.id) return;
    document.body.classList.add('zpanel');
    clearTimeout(zpDoneT);
    zpDoneT = setTimeout(() => {
      if (zpOpen === z.id) zpEl.classList.add('zp-done');
    }, 640);
  }));"""
b3 = """  document.body.classList.remove('zpclosing');
  /* СНАЧАЛА СОБРАЛИ, ПОТОМ ПОЕХАЛИ. Сборка содержимого — сотни узлов и
     иногда тяжёлый iframe; включи анимацию в том же кадре — и первые
     200 мс уходят в вёрстку, а веер начинается рывком с середины. */
  requestAnimationFrame(() => requestAnimationFrame(() => {
    if (zpOpen !== z.id) return;
    document.body.classList.add('zpanel');
    zpFan(z.a, +1);
  }));"""
assert s.count(a3) == 1, 'raf block'
s = s.replace(a3, b3)

# ── closePanel: складываем веер назад ─────────────────────────────────────
a4 = """  clearTimeout(zpDoneT);
  zpEl.classList.remove('zp-done');
  document.body.classList.add('zpclosing');
  setTimeout(() => {
    document.body.classList.remove('zpanel', 'zpclosing');
  }, 300);"""
b4 = """  document.body.classList.add('zpclosing');
  const _a = (zpLastA == null ? -90 : zpLastA);
  zpFan(_a, -1, () => {
    document.body.classList.remove('zpanel', 'zpclosing');
    zpEl.style.clipPath = '';
  });"""
assert s.count(a4) == 1, 'close block'
s = s.replace(a4, b4)

# ── сама функция веера ────────────────────────────────────────────────────
a5 = """/* ── открыть / закрыть ── */
function openPanel(z, cx, cy, keepStep){"""
b5 = """/* ВЕЕР: клин от правой грани сектора разворачивается на полный круг.
   dir=+1 раскрытие, dir=-1 складывание. Углы — те же, что у секторов в
   разметке: ноль вправо, растут вниз (глаза -90 = вверх). Правая грань —
   это a - SPAN/2: именно с неё начинается ход по часовой стрелке. */
let zpFanRAF = 0, zpLastA = null;
function zpFan(aDeg, dir, done){
  cancelAnimationFrame(zpFanRAF);
  zpLastA = aDeg;
  const SP = (typeof SPAN === 'number' ? SPAN : 60);
  const a0 = (aDeg - SP / 2) * Math.PI / 180;
  const R = Math.hypot(W, H) * 1.2;      // с запасом за углы экрана
  const T = dir > 0 ? 560 : 280;
  const N = 26;                          // хватает, чтобы дуга не гранилась
  const t0 = performance.now();
  const step = (now) => {
    let t = Math.min(1, (now - t0) / T);
    // раскрытие тормозит к концу, складывание — разгоняется
    const e = dir > 0 ? 1 - Math.pow(1 - t, 3) : Math.pow(1 - t, 2);
    const sweep = e * Math.PI * 2;
    if (sweep >= Math.PI * 2 - 1e-3){
      zpEl.style.clipPath = 'none';
    } else {
      const pts = [CX.toFixed(1) + 'px ' + CY.toFixed(1) + 'px'];
      for (let i = 0; i <= N; i++){
        const a = a0 + sweep * i / N;
        pts.push((CX + Math.cos(a) * R).toFixed(1) + 'px ' +
                 (CY + Math.sin(a) * R).toFixed(1) + 'px');
      }
      zpEl.style.clipPath = 'polygon(' + pts.join(',') + ')';
    }
    if (t < 1){ zpFanRAF = requestAnimationFrame(step); }
    else if (done) done();
  };
  zpFanRAF = requestAnimationFrame(step);
}

/* ── открыть / закрыть ── */
function openPanel(z, cx, cy, keepStep){"""
assert s.count(a5) == 1, 'anchor openPanel'
s = s.replace(a5, b5)

io.open(p, 'w', encoding='utf-8').write(s)
print('ok')
