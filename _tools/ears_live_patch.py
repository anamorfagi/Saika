# -*- coding: utf-8 -*-
"""Правая колонка панели СЛУХ: кто говорит + живой транскриб над справкой."""
import io, sys
p = sys.argv[1]
s = io.open(p, encoding='utf-8').read()

# ── 1. сборщик реплик: складываем каждое 'stt' в общий журнал ───────────
a = "  if(m.type==='stt'){\n"
b = """  if(m.type==='stt'){
    /* ЖИВОЙ ЖУРНАЛ СЛУХА (27.08.2026, владелец: «где вообще транскриб» и
       «справа должен был отображаться список спикеров»). Реплики и раньше
       приходили сюда, но оседали ТОЛЬКО в ленте разговора — в панели СЛУХ
       их не было вовсе. Складываем в общий журнал; панель, если открыта,
       рисует его у себя. */
    try{
      (window.EARS_LOG = window.EARS_LOG || []).push({
        t: Date.now(), text: String(m.text || ''), who: m.speaker || '',
        conf: (m.speaker_conf == null ? null : +m.speaker_conf),
        src: m.src || 'mic', hz: m.voice_hz || 0, music: !!m.music});
      if(window.EARS_LOG.length > 300) window.EARS_LOG.splice(0, 100);
      if(window.earsRender) window.earsRender();
    }catch(e){}
"""
assert s.count(a) == 1, 'stt hook'
s = s.replace(a, b)

# ── 2. правая колонка: живой блок над справкой ──────────────────────────
a2 = "      wrap.appendChild(side);      // документ — вторая колонка титульной сетки\n"
b2 = """      // ЖИВОЙ БЛОК НАД СПРАВКОЙ (27.08.2026, владелец). Справа теперь
      // сначала то, что происходит прямо сейчас — кто говорит и что
      // сказано, — а описание технологии уезжает под него.
      const right = document.createElement('div');
      right.className = 'ears-right';
      const live = document.createElement('div');
      live.className = 'ears-live';
      live.innerHTML =
        '<div class="el-head"><span class="el-kick">Кто говорит</span>' +
        '<span class="el-note" id="el-vcount"></span></div>' +
        '<div class="el-voices" id="el-voices"></div>' +
        '<div class="el-head"><span class="el-kick">Что она слышит</span>' +
        '<span class="el-note" id="el-lcount"></span></div>' +
        '<div class="el-lines" id="el-lines"></div>';
      right.appendChild(live);
      right.appendChild(side);
      wrap.appendChild(right);     // вторая колонка титульной сетки

      // цвет голоса берём из реестра — он же на карте узнавания
      const VCOL = {};
      const pullVoices = () => fetch('/api/voiceprint').then(r => r.json())
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
        }).catch(() => {});
      pullVoices();
      const vTimer = setInterval(pullVoices, 4000);

      window.earsRender = () => {
        const box = document.getElementById('el-lines');
        if(!box){ return; }
        const L = (window.EARS_LOG || []).slice(-40).reverse();
        const cnt = document.getElementById('el-lcount');
        if(cnt) cnt.textContent = L.length ? 'последние ' + L.length : 'тихо';
        box.innerHTML = L.length ? L.map(r => {
          const c = VCOL[r.who] || '#8b93a7';
          const tm = new Date(r.t).toTimeString().slice(0, 8);
          return '<div class="el-l"><span class="el-lt">' + tm + '</span>' +
            '<i style="background:' + c + '"></i>' +
            '<span class="el-lw">' + esc(r.who || 'неизвестный') + '</span>' +
            '<span class="el-lx">' + esc(r.text) + '</span>' +
            '<span class="el-ls">' + (r.src === 'sys' ? 'система' : 'микро') +
            '</span></div>';
        }).join('') : '<div class="el-empty">Тишина. Скажи что-нибудь или ' +
          'включи звук — реплики появятся здесь.</div>';
      };
      window.earsRender();
      adopted.push({node: null, slot: null, stop: () => {
        clearInterval(vTimer); window.earsRender = null; }});
"""
assert s.count(a2) == 1, 'right col'
s = s.replace(a2, b2)

# ── 3. стили живого блока ───────────────────────────────────────────────
a3 = "#zp-body .ears-doc{overflow:auto;"
b3 = """#zp-body .ears-right{display:flex;flex-direction:column;gap:14px;
  height:100%;min-height:0;overflow:auto;padding-right:10px;
  scrollbar-width:thin}
#zp-body .ears-right .ears-doc{overflow:visible;height:auto;padding-right:0}
#zp-body .ears-live{display:flex;flex-direction:column;gap:8px;flex:none}
#zp-body .el-head{display:flex;align-items:baseline;gap:10px;
  padding-bottom:2px;border-bottom:1px solid rgba(255,255,255,.07)}
#zp-body .el-kick{font:500 10.5px/1 inherit;letter-spacing:.26em;
  text-transform:uppercase;color:#4dd0e1}
#zp-body .el-note{font-size:11px;color:#7b8496;margin-left:auto}
#zp-body .el-voices{display:flex;flex-direction:column;gap:2px;
  max-height:190px;overflow:auto;scrollbar-width:thin}
#zp-body .el-v{display:flex;align-items:center;gap:8px;font-size:13px;
  padding:3px 2px;border-radius:8px}
#zp-body .el-v:hover{background:rgba(255,255,255,.04)}
#zp-body .el-v i{width:9px;height:9px;border-radius:50%;flex:none}
#zp-body .el-v b{font-weight:600;color:#eceef1}
#zp-body .el-alias{font-size:11px;color:#6d7688}
#zp-body .el-hz{font-size:11px;color:#7b8496;margin-left:auto;
  font-variant-numeric:tabular-nums}
#zp-body .el-n{font-size:11px;color:#5d6678;min-width:26px;text-align:right;
  font-variant-numeric:tabular-nums}
#zp-body .el-lines{display:flex;flex-direction:column;gap:4px;
  max-height:38vh;overflow:auto;scrollbar-width:thin}
#zp-body .el-l{display:grid;grid-template-columns:52px 9px 88px 1fr auto;
  align-items:baseline;gap:7px;font-size:12.5px;line-height:1.45;
  padding:3px 2px;border-radius:8px}
#zp-body .el-l:hover{background:rgba(255,255,255,.04)}
#zp-body .el-lt{color:#5d6678;font-size:11px;font-variant-numeric:tabular-nums}
#zp-body .el-l i{width:9px;height:9px;border-radius:50%;align-self:center}
#zp-body .el-lw{color:#9aa3b5;font-size:11.5px;overflow:hidden;
  text-overflow:ellipsis;white-space:nowrap}
#zp-body .el-lx{color:#dfe3ea}
#zp-body .el-ls{color:#5d6678;font-size:10.5px}
#zp-body .el-empty{font-size:12.5px;color:#6d7688;padding:6px 2px}
#zp-body .ears-doc{overflow:auto;"""
assert s.count(a3) == 1, 'css'
s = s.replace(a3, b3)

io.open(p, 'w', encoding='utf-8').write(s)
print('ok')
