# -*- coding: utf-8 -*-
"""Имена — обратно в визуал; убрать список сбоку и вложенные полосы прокрутки."""
import io, re, sys
p = sys.argv[1]
s = io.open(p, encoding='utf-8').read()

# 1. убрать блок «Кто говорит» из правой колонки
a = """      live.innerHTML =
        '<div class="el-head"><span class="el-kick">Кто говорит</span>' +
        '<span class="el-note" id="el-vcount"></span></div>' +
        '<div class="el-voices" id="el-voices"></div>' +
        '<div class="el-head"><span class="el-kick">Что она слышит</span>' +
        '<span class="el-note" id="el-lcount"></span></div>' +
        '<div class="el-lines" id="el-lines"></div>';"""
b = """      // СПИСКА ГОЛОСОВ ЗДЕСЬ НЕТ (27.08.2026, владелец: «у нас имена
      // писались прямо в визуале, нахуя ты крутилку в крутилке делаешь»).
      // Плашки голосов рисует сама карта, поверх сцены — там же, где их
      // цвета. Справа остаётся только то, чего в визуале нет: реплики.
      live.innerHTML =
        '<div class="el-head"><span class="el-kick">Что она слышит</span>' +
        '<span class="el-note" id="el-lcount"></span></div>' +
        '<div class="el-lines" id="el-lines"></div>';"""
assert s.count(a) == 1, 'live html'
s = s.replace(a, b)

# 2. реестр голосов — внутрь карты, а не в колонку
a2 = """      const pullVoices = () => fetch('/api/voiceprint').then(r => r.json())
        .then(j => {
          const sp = (j && j.speakers) || {};
          const box = document.getElementById('el-voices');
          if(!box) return;
          const names = Object.keys(sp);
          names.sort((a, b) => (sp[b].heard || 0) - (sp[a].heard || 0));
          names.forEach(n => { VCOL[n] = sp[n].color || '#8b93a7'; });
          const cnt = document.getElementById('el-vcount');
          if(cnt) cnt.textContent = names.length ? names.length + ' в реестре'
                                                 : 'реестр пуст';
          box.innerHTML = names.length ? names.map(n => {
            const v = sp[n];
            const nm = v.guess && v.guess_conf >= 0.6 ? v.guess : n;
            const hz = v.pitch_lo && v.pitch_hi
              ? v.pitch_lo + '–' + v.pitch_hi + ' Гц' : '';
            return '<div class="el-v"><i style="background:' +
              (v.color || '#8b93a7') + '"></i><b>' + esc(nm) + '</b>' +
              (nm !== n ? '<span class="el-alias">' + esc(n) + '</span>' : '') +
              '<span class="el-hz">' + hz + '</span>' +
              '<span class="el-n">' + (v.heard || 0) + '</span></div>';
          }).join('') : '<div class="el-empty">Пока никого не завела — ' +
            'голоса появятся сами, как только услышит устойчивую речь.</div>';
        }).catch(() => {});"""
b2 = """      const pullVoices = () => fetch('/api/voiceprint').then(r => r.json())
        .then(j => {
          const sp = (j && j.speakers) || {};
          const names = Object.keys(sp);
          names.sort((a, b) => (sp[b].heard || 0) - (sp[a].heard || 0));
          names.forEach(n => { VCOL[n] = sp[n].color || '#8b93a7'; });
          const list = names.map(n => {
            const v = sp[n];
            return {
              name: (v.guess && v.guess_conf >= 0.6) ? v.guess : n,
              color: v.color || '#8b93a7',
              heard: v.heard || 0,
              hz: (v.pitch_lo && v.pitch_hi)
                ? v.pitch_lo + '–' + v.pitch_hi + ' Гц' : ''
            };
          });
          try { fr.contentWindow.postMessage({saikaVoices: list}, '*'); }
          catch(e){}
        }).catch(() => {});"""
assert s.count(a2) == 1, 'pullVoices'
s = s.replace(a2, b2)

# 3. правая колонка: одна полоса прокрутки на всю колонку, у ленты своей нет
a3 = """#zp-body .el-lines{display:flex;flex-direction:column;gap:4px;
  max-height:38vh;overflow:auto;scrollbar-width:thin}"""
b3 = """#zp-body .el-lines{display:flex;flex-direction:column;gap:4px}"""
assert s.count(a3) == 1, 'lines css'
s = s.replace(a3, b3)

a4 = """#zp-body .el-voices{display:flex;flex-direction:column;gap:2px;
  max-height:190px;overflow:auto;scrollbar-width:thin}
"""
assert s.count(a4) == 1, 'voices css'
s = s.replace(a4, "")

io.open(p, 'w', encoding='utf-8').write(s)
print('ok')
