# -*- coding: utf-8 -*-
"""Атлас сначала разворачивается из центра ВО ВЕСЬ экран, потом уступает
место колонке с описанием."""
import io, sys
p = sys.argv[1]
s = io.open(p, encoding='utf-8').read()

a = """@keyframes zi-stage{
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
b = """/* ПЕРВЫЙ ТАКТ — ВО ВЕСЬ ЭКРАН (27.08.2026, владелец: «сделай, чтобы окно
   акустической системы разворачивалось из центра во весь экран»). Раньше
   сцена проявлялась уже в своём конечном размере — просто сдвинутая к
   середине; это читалось как «съехала», а не «развернулась». Теперь она
   сначала занимает ВСЮ ширину страницы, а колонка описания имеет нулевую
   ширину. Вторым тактом сетка едет к 2fr / 1fr: сцена отдаёт место, и в
   освободившееся справа заезжает текст. */
@keyframes zi-stage{
  from{opacity:0; transform:scale(.70)}
  to  {opacity:1; transform:scale(1)}}
@keyframes zi-side{
  from{opacity:0; transform:translateX(54px)}
  to  {opacity:1; transform:translateX(0)}}
@keyframes zi-plain{from{opacity:0}to{opacity:1}}
#zpanel.zpi #zp-body{opacity:1}
#zpanel.zpi .zi-stage{transform-origin:50% 50%;
  animation:zi-stage .44s cubic-bezier(.22,.8,.28,1) both}
#zpanel.zpi .zi-side {animation:zi-side .42s cubic-bezier(.25,.8,.3,1) .60s both}
#zpanel.zpi .zi-plain{animation:zi-plain .34s var(--zease) .18s both}
#zpanel.zpi .zi-grid{transition:grid-template-columns .50s cubic-bezier(.3,.8,.25,1)}
#zpanel.zpi.zi-full .zi-grid{grid-template-columns:1fr 0fr}
#zpanel.zpi .zi-side{min-width:0;overflow:hidden}"""
assert s.count(a) == 1, 'css block'
s = s.replace(a, b)

a2 = """  if (stage && side){
    try {
      const pr = b.getBoundingClientRect(), sr = stage.getBoundingClientRect();
      const dx = (pr.left + pr.width / 2) - (sr.left + sr.width / 2);
      stage.style.setProperty('--zidx', dx.toFixed(1) + 'px');
    } catch(e){}
    stage.classList.add('zi-stage');
    side.classList.add('zi-side');
  } else {"""
b2 = """  if (stage && side){
    const grid = stage.parentNode;
    if (grid) grid.classList.add('zi-grid');
    stage.classList.add('zi-stage');
    side.classList.add('zi-side');
    zpEl.classList.add('zi-full');
    clearTimeout(zpFullT);
    zpFullT = setTimeout(() => zpEl.classList.remove('zi-full'), 520);
  } else {"""
assert s.count(a2) == 1, 'zpInner'
s = s.replace(a2, b2)

a3 = """  b.querySelectorAll('.zi-stage,.zi-side,.zi-plain').forEach(
    n => n.classList.remove('zi-stage', 'zi-side', 'zi-plain'));"""
b3 = """  b.querySelectorAll('.zi-stage,.zi-side,.zi-plain,.zi-grid').forEach(
    n => n.classList.remove('zi-stage', 'zi-side', 'zi-plain', 'zi-grid'));"""
assert s.count(a3) == 1, 'reset'
s = s.replace(a3, b3)

a4 = "let zpFanRAF = 0, zpLastA = null;"
b4 = "let zpFanRAF = 0, zpLastA = null, zpFullT = 0;"
assert s.count(a4) == 1, 'vars'
s = s.replace(a4, b4)

a5 = """  zpEl.classList.remove('zpi', 'zp-hold');"""
b5 = """  clearTimeout(zpFullT);
  zpEl.classList.remove('zpi', 'zp-hold', 'zi-full');"""
assert s.count(a5) == 1, 'close reset'
s = s.replace(a5, b5)

io.open(p, 'w', encoding='utf-8').write(s)
print('ok')
