# -*- coding: utf-8 -*-
"""Схлопывание дырки и своя анимация внутреннего интерфейса."""
import io, sys
p = sys.argv[1]
s = io.open(p, encoding='utf-8').read()

# ── CSS: пусто во время веера, затем выход содержимого ────────────────────
a = """body.zpanel #zpanel{opacity:1;transform:none;pointer-events:auto;
  animation:none}
body.zpclosing #zpanel{opacity:1;pointer-events:none}"""
b = """body.zpanel #zpanel{opacity:1;transform:none;pointer-events:auto;
  animation:none}
body.zpclosing #zpanel{opacity:1;pointer-events:none}

/* ═══ ВТОРОЙ ХОД: ДЫРКА СХЛОПЫВАЕТСЯ, ВНУТРЕННОСТЬ ВЫХОДИТ ═══
   (27.08.2026, владелец). Пока клин едет по кругу, панель пустая — это
   ещё «оболочка», её содержимое не показывают на ходу. Клин замкнулся,
   кольцо вокруг ядра стянулось в точку — и только тогда начинается своя,
   отдельная анимация страницы: сцена проявляется ИЗ ЦЕНТРА, потом уезжает
   на своё место влево, и следом справа заезжает текст о технологии. */
#zpanel.zp-hold #zp-body{opacity:0}
@keyframes zi-stage{
  0%  {opacity:0; transform:translateX(var(--zidx,0px)) scale(.74)}
  30% {opacity:1; transform:translateX(var(--zidx,0px)) scale(1)}
  58% {opacity:1; transform:translateX(var(--zidx,0px)) scale(1)}
  100%{opacity:1; transform:translateX(0) scale(1)}}
@keyframes zi-side{
  from{opacity:0; transform:translateX(54px)}
  to  {opacity:1; transform:translateX(0)}}
@keyframes zi-plain{from{opacity:0}to{opacity:1}}
#zpanel.zpi #zp-body{opacity:1}
#zpanel.zpi .zi-stage{animation:zi-stage .88s cubic-bezier(.3,.75,.25,1) both}
#zpanel.zpi .zi-side {animation:zi-side .44s cubic-bezier(.25,.8,.3,1) .60s both}
#zpanel.zpi .zi-plain{animation:zi-plain .34s var(--zease) .18s both}"""
assert s.count(a) == 1, 'css anchor'
s = s.replace(a, b)

# ── zpFan: после круга стягиваем кольцо, потом зовём внутреннюю анимацию ──
a2 = """    const sweep = (SP * Math.PI / 180) + e * (Math.PI * 2 - SP * Math.PI / 180);
    if (sweep >= Math.PI * 2 - 1e-3){
      zpEl.style.clipPath = 'none';
    } else {
      const r0 = (typeof HOLE === 'number' && HOLE > 4) ? HOLE : 60;"""
b2 = """    const sweep = (SP * Math.PI / 180) + e * (Math.PI * 2 - SP * Math.PI / 180);
    if (sweep >= Math.PI * 2 - 1e-3){
      zpEl.style.clipPath = 'none';
    } else {
      const r0 = HOLE0 * (dir > 0 ? 1 : 1);"""
assert s.count(a2) == 1, 'sweep block'
s = s.replace(a2, b2)

a3 = """  const T = dir > 0 ? 560 : 280;
  const N = 26;                          // хватает, чтобы дуга не гранилась
  const t0 = performance.now();"""
b3 = """  const T = dir > 0 ? 560 : 280;
  const N = 26;                          // хватает, чтобы дуга не гранилась
  const HOLE0 = (typeof HOLE === 'number' && HOLE > 4) ? HOLE : 60;
  const t0 = performance.now();"""
assert s.count(a3) == 1, 'consts'
s = s.replace(a3, b3)

a4 = """    if (t < 1){ zpFanRAF = requestAnimationFrame(step); }
    else if (done) done();
  };
  zpFanRAF = requestAnimationFrame(step);
}"""
b4 = """    if (t < 1){ zpFanRAF = requestAnimationFrame(step); }
    else if (dir > 0){ zpShrink(a0, HOLE0, done); }
    else if (done) done();
  };
  zpFanRAF = requestAnimationFrame(step);
}

/* КОЛЬЦО ВОКРУГ ЯДРА СТЯГИВАЕТСЯ В ТОЧКУ. Клин уже замкнулся на полный
   круг, осталась дырка — сводим её радиус к нулю и только теперь отдаём
   панель целиком. Отдельный ход, а не хвост предыдущего: у него своя
   скорость и своя роль — «оболочка встала, можно наполнять». */
function zpShrink(a0, r1, done){
  const T = 260, N = 26, t0 = performance.now();
  const R = Math.hypot(W, H) * 1.2;
  const step = (now) => {
    const t = Math.min(1, (now - t0) / T);
    const r = r1 * (1 - t * t);
    if (t >= 1 || r < 1.5){
      zpEl.style.clipPath = 'none';
      if (done) done();
      return;
    }
    const pts = [];
    for (let i = 0; i <= N; i++){
      const a = a0 - Math.PI * 2 * i / N;
      pts.push((CX + Math.cos(a) * R).toFixed(1) + 'px ' +
               (CY + Math.sin(a) * R).toFixed(1) + 'px');
    }
    for (let i = N; i >= 0; i--){
      const a = a0 - Math.PI * 2 * i / N;
      pts.push((CX + Math.cos(a) * r).toFixed(1) + 'px ' +
               (CY + Math.sin(a) * r).toFixed(1) + 'px');
    }
    zpEl.style.clipPath = 'polygon(' + pts.join(',') + ')';
    zpFanRAF = requestAnimationFrame(step);
  };
  zpFanRAF = requestAnimationFrame(step);
}

/* ВНУТРЕННЯЯ СТРАНИЦА ВЫХОДИТ САМА. Сцена проявляется из центра панели,
   стоит там мгновение и уезжает на своё место, а следом справа заезжает
   колонка с описанием. Смещение считаем в пикселях: «центр» у каждой
   панели свой, в CSS его не выразить. */
function zpInner(){
  const b = zpBody;
  if (!b) return;
  const stage = b.querySelector('.ears-stage') ||
                b.querySelector('.zp-two > .zp-col:not(.zp-side)');
  const side  = b.querySelector('.ears-right') ||
                b.querySelector('.zp-two > .zp-col.zp-side');
  b.querySelectorAll('.zi-stage,.zi-side,.zi-plain').forEach(
    n => n.classList.remove('zi-stage', 'zi-side', 'zi-plain'));
  if (stage && side){
    try {
      const pr = b.getBoundingClientRect(), sr = stage.getBoundingClientRect();
      const dx = (pr.left + pr.width / 2) - (sr.left + sr.width / 2);
      stage.style.setProperty('--zidx', dx.toFixed(1) + 'px');
    } catch(e){}
    stage.classList.add('zi-stage');
    side.classList.add('zi-side');
  } else {
    Array.prototype.forEach.call(b.children, n => n.classList.add('zi-plain'));
  }
  zpEl.classList.remove('zp-hold');
  zpEl.classList.add('zpi');
}"""
assert s.count(a4) == 1, 'fan tail'
s = s.replace(a4, b4)

# ── openPanel: держим содержимое скрытым, пускаем внутреннюю анимацию ─────
a5 = """    document.body.classList.add('zpanel');
    zpFan(z.a, +1);"""
b5 = """    document.body.classList.add('zpanel');
    zpEl.classList.remove('zpi');
    zpEl.classList.add('zp-hold');
    zpFan(z.a, +1, () => { if (zpOpen === z.id) zpInner(); });"""
assert s.count(a5) == 1, 'openPanel call'
s = s.replace(a5, b5)

a6 = """  document.body.classList.add('zpclosing');
  const _a = (zpLastA == null ? -90 : zpLastA);"""
b6 = """  document.body.classList.add('zpclosing');
  zpEl.classList.remove('zpi', 'zp-hold');
  const _a = (zpLastA == null ? -90 : zpLastA);"""
assert s.count(a6) == 1, 'closePanel'
s = s.replace(a6, b6)

io.open(p, 'w', encoding='utf-8').write(s)
print('ok')
