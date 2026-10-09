/* ═══ ДОСКА — редактор в духе Miro ═══
   Полотно в клетку, на нём: стикеры, текст, фигуры, рамки, картинки, код,
   карточки цепочки слуха, связи со стрелками и подписями, свободный карандаш.
   Всё хранится на сервере слуха в data/boards/<id>.json — доску одинаково
   видят вкладка и тот, кто читает файл.

   ═══ БЛОК 1: состояние ═══
   B      — текущая доска: {id, name, view:{px,py,z}, items:[], links:[], groups:[]}
   SEL    — выделенные id (элементов и связей)
   TOOL   — активный инструмент: v выбор, h рука, n стикер, t текст, s фигура,
            l связь, f рамка, p карандаш, c карточка
   UNDO/REDO — снимки {items,links,groups} до каждого изменения

   ═══ БЛОК 2: координаты ═══
   Сцена 1920×1080 масштабируется в окно (K = innerHeight/1080), доска внутри
   борда сдвинута на view.px/py и умножена на view.z. Экран → доска:
   ((clientX − left)/K − px)/z.

   Мышь:  тянуть пустое — сдвиг (или рамка выделения при инструменте «выбор»
          с Shift), колесо — зум к курсору, двойной щелчок по пустому — стикер,
          двойной по элементу — правка текста, тянуть от кружка на краю — связь.
   Клавиши: V H N T S L F P C — инструменты, Esc — выбор/снять выделение,
          Del — удалить, Ctrl+Z/Y — отмена/возврат, Ctrl+C/V/D — копия/вставка/
          дубль, Ctrl+G / Ctrl+Shift+G — группа, Ctrl+A — всё, стрелки — сдвиг
          на 1 (Shift — 10), Ctrl+] / Ctrl+[ — выше/ниже, Ctrl+L — замок, 0 — вид, 1 — вписать.
*/
(function(){
'use strict';
const $ = id => document.getElementById(id);
const flow = $('flow'), port = $('port'), layer = $('cards'), wires = $('wires'), groupsBox = $('groups');
const lasso = $('lasso'), guides = $('guides'), selbox = $('selbox'), props = $('props'), ctx = $('ctxmenu');
const K = () => innerHeight / 1080;
/* любое перетаскивание идёт через track(): если мышь ушла из окна, окно потеряло фокус
   или кнопка уже отпущена (скриншотер перехватил mouseup) — цикл завершается сам */
function track(move, up){
  const m = ev => { if (ev.buttons === 0){ end(ev); return; } move(ev); };   // любая кнопка: левая тянет, средняя — сдвиг доски
  const end = ev => { removeEventListener('mousemove', m); removeEventListener('mouseup', end); removeEventListener('blur', end); document.removeEventListener('mouseleave', end); up(ev || {}); };
  addEventListener('mousemove', m); addEventListener('mouseup', end); addEventListener('blur', end); document.addEventListener('mouseleave', end);
}
let B = null, SEL = new Set(), TOOL = 'v', UNDO = [], REDO = [], CLIP = null, NODES = new Map();
let SNAP = true, saveT = 0, BOARDS = [];
const NOTE_COLORS = {yellow: '#f5e07a', orange: '#f7b26a', pink: '#f4a3c4', violet: '#c7a6f2', blue: '#9dc4f5',
                     cyan: '#8fe0e8', green: '#a7e39a', gray: '#d3d3d3'};
const FILLS = ['none', '#3a3f4b', '#4a3b5c', '#2f4f4f', '#5c3b3b', '#3b4f5c', '#5c5a3b', '#eef2ff', '#f0fdf4', '#fef3c7', '#fde2e2', '#e0f2fe'];
const STROKES = ['#c9c9c9', '#5fbf7a', '#2d9bf0', '#da0063', '#ff8c00', '#8b5cf6', '#e5e5e5', '#8a8a8a'];
const SHAPES = {rect: 'Прямоугольник', round: 'Скруглённый', ellipse: 'Эллипс', diamond: 'Ромб', hex: 'Шестиугольник',
                para: 'Параллелограмм', tri: 'Треугольник', pill: 'Капсула'};

/* ═══ БЛОК 3: исходная доска — цепочка слуха ═══ */
const TECH = [
  ['src', 20, 100, 1, 'Источники', 'Звук каждой программы отдельным каналом — WASAPI process loopback через именованный канал Windows.', 'Discord, браузер и игра приходят порознь. Ничего не надо разделять потом — оно и не смешивалось.'],
  ['mic', 20, 300, 1, 'Микрофон', 'Свой канал с устройства ввода, 16 кГц моно.', 'Твой голос — отдельный поток, его нельзя перепутать с собеседником.'],
  ['ring', 310, 200, 1, 'Кольцо', 'Все каналы сводятся к моно 16 кГц и живут в кольцевом буфере последних секунд.', 'Уши работают в одном формате, а к только что прозвучавшему можно вернуться назад.'],
  ['vad', 600, 200, 1, 'Рефлекс', 'Silero VAD на каждом канале, 0,8–1,9 мс на такт.', 'Дешёвый сторож: тяжёлые модели просыпаются только там, где действительно говорят.'],
  ['words', 890, 60, 1, 'Слова · сейчас', 'faster-whisper turbo: черновик раз в секунду, окончательный текст по концу речи.', 'Даёт текст уже сегодня, но ждёт, пока фраза закончится.'],
  ['stream', 890, 230, 0, 'Слова · потоком', 'Nemotron ASR Streaming 0.6B, 40 языков, задержка 80–560 мс.', 'Текст должен появляться во время речи, а не после неё. Это и есть реальный слух.'],
  ['who', 890, 400, 0, 'Кто говорит', 'Streaming Sortformer v2 плюс отпечаток голоса ReDimNet2-B6.', 'В одном канале сидит несколько человек. Метка «кто сказал» важнее метки «откуда пришло».'],
  ['snd', 600, 400, 0, 'Звуки', 'CED-Tiny / PretrainedSED, кадр 40 мс — шаги, стук, лай, уведомление.', 'Слух — это не только речь. Половина смысла сцены в том, что не произносят.'],
  ['mus', 600, 570, 0, 'Музыка', 'BeatNet — доли и темп, CLAP — смысл, NMFP — отпечаток трека.', 'Понимать, что играет, в каком темпе и настроении — отдельный слой восприятия.'],
  ['scene', 1180, 230, 1, 'Сцена', 'Одна шина событий: речь, слова, кто, звуки, уровни. Подписчики — вкладка и журнал.', 'Всё сходится в одном месте, поэтому новый слой добавляется без переделки остальных.'],
  ['jrn', 1470, 130, 1, 'Журнал', 'Файл на день, поиск по словам в любом порядке, подгрузка ленты вверх.', 'Текст переживает перезапуск. Сказанное неделю назад нужно уметь найти.'],
  ['feed', 1470, 310, 1, 'Лента', 'Эта вкладка: строки по источникам, дни, склейка, поиск.', 'Показывает правду о том, что слышно прямо сейчас, без приукрашивания.'],
  ['mem', 1470, 490, 0, 'Память', 'Долгая память сцены: свёртки дня, кто говорил, о чём, что звучало.', 'Чтобы к услышанному можно было вернуться через неделю и получить смысл, а не простыню строк.']
];
const LINKS = [['src', 'ring'], ['mic', 'ring'], ['ring', 'vad'], ['ring', 'snd'], ['snd', 'mus'], ['vad', 'words'], ['vad', 'stream'],
               ['vad', 'who'], ['words', 'scene'], ['stream', 'scene'], ['who', 'scene'], ['snd', 'scene'], ['mus', 'scene'],
               ['scene', 'jrn'], ['scene', 'feed'], ['jrn', 'mem']];
function fresh(){
  return {id: 'main', name: 'Слух · цепочка', view: {px: 30, py: 20, z: 1},
    items: TECH.map(([id, x, y, ok, t, d, w], i) => ({id, type: 'card', x, y, w: 240, h: 0, z: i + 1, t, d, why: w, ok})),
    links: LINKS.map((l, i) => ({id: 'l' + i, a: l[0], b: l[1], arrow: 'end', style: 'curve'})), groups: []};
}
/* старая доска из браузера (карточки + группы) переезжает без потерь */
function migrate(raw){
  const b = fresh();
  if (raw.cards){
    b.items = Object.values(raw.cards).map((c, i) => ({id: c.id, type: 'card', x: c.x, y: c.y, w: 240, h: 0, z: i + 1, t: c.t, d: c.d, why: c.w, ok: c.ok ? 1 : 0}));
    b.links = (raw.links || []).map(l => ({id: l.id, a: l.a, b: l.b, ap: l.ap, bp: l.bp, arrow: 'end', style: 'curve'}));
    b.groups = (raw.groups || []).map(g => ({id: g.id, ids: g.ids, t: g.t}));
  } else if (raw.pos){
    for (const it of b.items) if (raw.pos[it.id]){ it.x = raw.pos[it.id][0]; it.y = raw.pos[it.id][1]; }
  }
  if (raw.px != null) b.view = {px: raw.px, py: raw.py, z: raw.z || 1};
  return b;
}

/* ═══ БЛОК 4: хранение — сервер, запас в браузере ═══ */
function nid(p){ return p + Math.random().toString(36).slice(2, 8); }
function item(id){ return B.items.find(i => i.id === id); }
function link(id){ return B.links.find(l => l.id === id); }
function dirty(){
  clearTimeout(saveT);
  saveT = setTimeout(async () => {
    try { localStorage.setItem('hear.board.' + B.id, JSON.stringify(B)); } catch (e){}
    try { await fetch('/api/board/' + encodeURIComponent(B.id), {method: 'PUT', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(B)}); }
    catch (e){}
  }, 400);
}
async function loadBoard(id){
  let b = null;
  try { const r = await fetch('/api/board/' + encodeURIComponent(id)); if (r.ok) b = await r.json(); } catch (e){}
  if (!b){ try { b = JSON.parse(localStorage.getItem('hear.board.' + id) || 'null'); } catch (e){} }
  if (!b && id === 'main'){
    let old = null; try { old = JSON.parse(localStorage.getItem('hear.flow') || 'null'); } catch (e){}
    b = old ? migrate(old) : fresh();
  }
  if (!b) b = {id, name: id, view: {px: 30, py: 20, z: 1}, items: [], links: [], groups: []};
  b.view = b.view || {px: 30, py: 20, z: 1}; b.items = b.items || []; b.links = b.links || []; b.groups = b.groups || [];
  B = b; SEL.clear(); UNDO = []; REDO = [];
  try { localStorage.setItem('hear.board', id); } catch (e){}
  NODES.clear(); layer.innerHTML = '';
  render(); view(); $('bname').textContent = B.name;
  dirty();
}
async function listBoards(){
  try { BOARDS = (await (await fetch('/api/boards')).json()).boards || []; } catch (e){ BOARDS = []; }
  if (!BOARDS.some(b => b.id === B.id)) BOARDS.unshift({id: B.id, name: B.name});
  return BOARDS;
}

/* ═══ БЛОК 5: отмена и возврат ═══ */
function snap(){ return JSON.stringify({items: B.items, links: B.links, groups: B.groups}); }
function hist(){ UNDO.push(snap()); if (UNDO.length > 80) UNDO.shift(); REDO = []; }
function restore(s){ const o = JSON.parse(s); B.items = o.items; B.links = o.links; B.groups = o.groups; SEL.clear(); render(); dirty(); }
function undo(){ if (!UNDO.length) return; REDO.push(snap()); restore(UNDO.pop()); }
function redo(){ if (!REDO.length) return; UNDO.push(snap()); restore(REDO.pop()); }

/* ═══ БЛОК 6: вид ═══ */
function view(){
  const r = flow.style, v = B.view;
  r.setProperty('--px', v.px + 'px'); r.setProperty('--py', v.py + 'px'); r.setProperty('--z', v.z);
  $('zoomv').textContent = Math.round(v.z * 100) + '%';
  selUI();
}
function toBoard(cx, cy){
  const r = flow.getBoundingClientRect(), k = K();
  return [((cx - r.left) / k - B.view.px) / B.view.z, ((cy - r.top) / k - B.view.py) / B.view.z];
}
function zoomAt(cx, cy, z){
  const r = flow.getBoundingClientRect(), k = K();
  const mx = (cx - r.left) / k, my = (cy - r.top) / k, z0 = B.view.z;
  z = Math.min(3, Math.max(0.15, z));
  B.view.px = mx - (mx - B.view.px) * (z / z0); B.view.py = my - (my - B.view.py) * (z / z0); B.view.z = Math.round(z * 1000) / 1000;
  view(); dirty();
}
function fit(){
  const bs = B.items.map(bbox).filter(Boolean);
  if (!bs.length){ B.view = {px: 30, py: 20, z: 1}; view(); return; }
  const x0 = Math.min(...bs.map(b => b.x)) - 40, y0 = Math.min(...bs.map(b => b.y)) - 40;
  const x1 = Math.max(...bs.map(b => b.x + b.w)) + 40, y1 = Math.max(...bs.map(b => b.y + b.h)) + 40;
  const r = flow.getBoundingClientRect(), k = K(), W = r.width / k, H = r.height / k;
  const z = Math.min(3, Math.max(0.15, Math.min(W / (x1 - x0), H / (y1 - y0))));
  B.view = {px: (W - (x1 - x0) * z) / 2 - x0 * z, py: (H - (y1 - y0) * z) / 2 - y0 * z, z: Math.round(z * 1000) / 1000};
  view(); dirty();
}

/* ═══ БЛОК 7: элементы — отрисовка по типу ═══ */
function bbox(it){
  const n = NODES.get(it.id);
  const h = it.h || (n ? n.offsetHeight : 60);
  return {x: it.x, y: it.y, w: it.w || (n ? n.offsetWidth : 100), h};
}
function shapePath(kind, w, h){
  const r = Math.min(w, h);
  switch (kind){
    case 'ellipse': return 'M ' + (w / 2) + ' 0 A ' + (w / 2) + ' ' + (h / 2) + ' 0 1 1 ' + (w / 2) + ' ' + h + ' A ' + (w / 2) + ' ' + (h / 2) + ' 0 1 1 ' + (w / 2) + ' 0 Z';
    case 'diamond': return 'M ' + (w / 2) + ' 0 L ' + w + ' ' + (h / 2) + ' L ' + (w / 2) + ' ' + h + ' L 0 ' + (h / 2) + ' Z';
    case 'hex': { const d = Math.min(w * 0.25, h / 2); return 'M ' + d + ' 0 L ' + (w - d) + ' 0 L ' + w + ' ' + (h / 2) + ' L ' + (w - d) + ' ' + h + ' L ' + d + ' ' + h + ' L 0 ' + (h / 2) + ' Z'; }
    case 'para': { const d = Math.min(w * 0.22, h); return 'M ' + d + ' 0 L ' + w + ' 0 L ' + (w - d) + ' ' + h + ' L 0 ' + h + ' Z'; }
    case 'tri': return 'M ' + (w / 2) + ' 0 L ' + w + ' ' + h + ' L 0 ' + h + ' Z';
    case 'pill': { const q = h / 2; return 'M ' + q + ' 0 L ' + (w - q) + ' 0 A ' + q + ' ' + q + ' 0 0 1 ' + (w - q) + ' ' + h + ' L ' + q + ' ' + h + ' A ' + q + ' ' + q + ' 0 0 1 ' + q + ' 0 Z'; }
    case 'round': { const q = Math.min(14, r / 2); return 'M ' + q + ' 0 L ' + (w - q) + ' 0 Q ' + w + ' 0 ' + w + ' ' + q + ' L ' + w + ' ' + (h - q) + ' Q ' + w + ' ' + h + ' ' + (w - q) + ' ' + h + ' L ' + q + ' ' + h + ' Q 0 ' + h + ' 0 ' + (h - q) + ' L 0 ' + q + ' Q 0 0 ' + q + ' 0 Z'; }
    default: return 'M 0 0 L ' + w + ' 0 L ' + w + ' ' + h + ' L 0 ' + h + ' Z';
  }
}
function esc(s){ return String(s == null ? '' : s).replace(/[&<>"]/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c])); }
function draw(it){
  let n = NODES.get(it.id);
  if (!n){
    n = document.createElement('div'); n.dataset.id = it.id; NODES.set(it.id, n); layer.appendChild(n);
    n.innerHTML = ['t', 'r', 'b', 'l'].map(p => '<i class="pin ' + p + '" data-p="' + p + '"></i>').join('');
  }
  n.className = 'el ' + it.type + (SEL.has(it.id) ? ' sel' : '') + (it.locked ? ' locked' : '');
  n.style.left = it.x + 'px'; n.style.top = it.y + 'px'; n.style.zIndex = it.type === 'frame' ? 0 : (it.z || 1);
  n.style.width = it.w ? it.w + 'px' : ''; n.style.height = (it.h && it.type !== 'card' && it.type !== 'text') ? it.h + 'px' : '';
  n.style.minHeight = (it.h && (it.type === 'card' || it.type === 'text')) ? it.h + 'px' : '';
  let body = n.querySelector('.body');
  if (!body){ body = document.createElement('div'); body.className = 'body'; n.insertBefore(body, n.firstChild); }
  if (n.dataset.sig === sig(it)) return n;
  n.dataset.sig = sig(it);
  switch (it.type){
    case 'card':
      body.innerHTML = '<h4><s title="двойной щелчок — переключить"></s><span class="t"></span><em></em></h4><p class="d"></p><p class="why"></p>';
      body.querySelector('.t').textContent = it.t || ''; body.querySelector('em').textContent = it.ok ? 'работает' : 'следующий этап';
      body.querySelector('.d').textContent = it.d || ''; body.querySelector('.why').textContent = it.why || '';
      body.querySelector('.d').classList.toggle('none', !it.d); body.querySelector('.why').classList.toggle('none', !it.why);
      n.classList.toggle('ok', !!it.ok); break;
    case 'note':
      body.innerHTML = '<div class="txt"></div>'; body.querySelector('.txt').textContent = it.text || '';
      n.style.background = NOTE_COLORS[it.color] || NOTE_COLORS.yellow; fitNote(n, it); break;
    case 'text':
      body.innerHTML = '<div class="txt"></div>'; body.querySelector('.txt').textContent = it.text || '';
      body.style.fontSize = (it.size || 18) + 'px'; body.style.textAlign = it.align || 'left'; body.style.fontWeight = it.bold ? 600 : 400;
      body.style.color = it.color || ''; break;
    case 'shape':
      body.innerHTML = '<svg viewBox="0 0 ' + (it.w || 160) + ' ' + (it.h || 100) + '" preserveAspectRatio="none"><path vector-effect="non-scaling-stroke"/></svg><div class="txt"></div>';
      { const p = body.querySelector('path'); p.setAttribute('d', shapePath(it.kind, it.w || 160, it.h || 100));
        p.style.fill = it.fill && it.fill !== 'none' ? it.fill : 'transparent'; p.style.stroke = it.stroke || '#c9c9c9';
        p.style.strokeWidth = (it.sw || 1.6); p.style.strokeDasharray = it.dash ? '6 5' : ''; }
      body.querySelector('.txt').textContent = it.text || ''; body.querySelector('.txt').style.color = it.tc || ''; break;
    case 'frame':
      body.innerHTML = '<b class="ttl"></b>'; body.querySelector('.ttl').textContent = it.t || 'Рамка';
      n.style.background = it.fill && it.fill !== 'none' ? it.fill : ''; break;
    case 'image':
      body.innerHTML = '<img draggable="false">'; body.querySelector('img').src = it.src || ''; break;
    case 'code':
      body.innerHTML = '<div class="cap"></div><pre class="txt"></pre>'; body.querySelector('.cap').textContent = it.t || 'код';
      body.querySelector('pre').textContent = it.text || ''; break;
    case 'pen': {
      const pts = it.points || [];
      const d = pts.map((p, i) => (i ? 'L ' : 'M ') + (p[0] - it.x) + ' ' + (p[1] - it.y)).join(' ');
      body.innerHTML = '<svg viewBox="0 0 ' + (it.w || 1) + ' ' + (it.h || 1) + '" preserveAspectRatio="none"><path vector-effect="non-scaling-stroke" fill="none" stroke-linecap="round" stroke-linejoin="round"/></svg>';
      const p = body.querySelector('path'); p.setAttribute('d', d); p.style.stroke = it.color || '#5fbf7a'; p.style.strokeWidth = it.sw || 2.5; break;
    }
  }
  return n;
}
function sig(it){ const o = Object.assign({}, it); delete o.x; delete o.y; delete o.z; return JSON.stringify(o) + '|' + (SEL.has(it.id) ? 1 : 0); }
function fitNote(n, it){
  const t = n.querySelector('.txt'); if (!t) return;
  let s = it.size || 28; t.style.fontSize = s + 'px';
  requestAnimationFrame(() => {
    while (s > 11 && (t.scrollHeight > n.clientHeight - 24 || t.scrollWidth > n.clientWidth - 24)){ s -= 1; t.style.fontSize = s + 'px'; }
  });
}
function render(){
  const ids = new Set(B.items.map(i => i.id));
  for (const [id, n] of NODES) if (!ids.has(id)){ n.remove(); NODES.delete(id); }
  for (const it of B.items) draw(it);
  wire(); groupsDraw(); selUI();
}

/* ═══ БЛОК 8: связи — стрелки, стиль, подпись ═══ */
function pinAt(g, s){
  return s === 'l' ? [g.x, g.y + g.h / 2] : s === 'r' ? [g.x + g.w, g.y + g.h / 2] : s === 't' ? [g.x + g.w / 2, g.y] : [g.x + g.w / 2, g.y + g.h];
}
function sides(A, Bx){
  const dx = (Bx.x + Bx.w / 2) - (A.x + A.w / 2), dy = (Bx.y + Bx.h / 2) - (A.y + A.h / 2);
  if (Math.abs(dx) >= Math.abs(dy)) return dx >= 0 ? ['r', 'l'] : ['l', 'r'];
  return dy >= 0 ? ['b', 't'] : ['t', 'b'];
}
function route(p1, s1, p2, s2, style){
  if (style === 'straight') return {d: 'M ' + p1[0] + ' ' + p1[1] + ' L ' + p2[0] + ' ' + p2[1], m: [(p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2]};
  if (style === 'elbow'){
    const h = s1 === 'l' || s1 === 'r';
    const mx = (p1[0] + p2[0]) / 2, my = (p1[1] + p2[1]) / 2;
    const d = h ? 'M ' + p1[0] + ' ' + p1[1] + ' L ' + mx + ' ' + p1[1] + ' L ' + mx + ' ' + p2[1] + ' L ' + p2[0] + ' ' + p2[1]
                : 'M ' + p1[0] + ' ' + p1[1] + ' L ' + p1[0] + ' ' + my + ' L ' + p2[0] + ' ' + my + ' L ' + p2[0] + ' ' + p2[1];
    return {d, m: [mx, my]};
  }
  const k = 0.45 * Math.max(60, Math.hypot(p2[0] - p1[0], p2[1] - p1[1]));
  const off = (p, s) => s === 'r' ? [p[0] + k, p[1]] : s === 'l' ? [p[0] - k, p[1]] : s === 'b' ? [p[0], p[1] + k] : [p[0], p[1] - k];
  const c1 = off(p1, s1), c2 = off(p2, s2);
  const m = [0.125 * p1[0] + 0.375 * c1[0] + 0.375 * c2[0] + 0.125 * p2[0], 0.125 * p1[1] + 0.375 * c1[1] + 0.375 * c2[1] + 0.125 * p2[1]];
  return {d: 'M ' + p1[0] + ' ' + p1[1] + ' C ' + c1[0] + ' ' + c1[1] + ', ' + c2[0] + ' ' + c2[1] + ', ' + p2[0] + ' ' + p2[1], m};
}
function wire(extra){
  const out = ['<defs><marker id="mE" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="context-stroke"/></marker></defs>'];
  for (const l of B.links){
    const A = item(l.a), Bi = item(l.b); if (!A || !Bi) continue;
    const ga = bbox(A), gb = bbox(Bi);
    const [s1, s2] = (l.ap && l.bp) ? [l.ap, l.bp] : sides(ga, gb);
    const r = route(pinAt(ga, s1), s1, pinAt(gb, s2), s2, l.style || 'curve');
    const hot = A.type === 'card' && Bi.type === 'card' && A.ok && Bi.ok;
    const col = l.color || (hot ? 'var(--glow)' : 'var(--wire)');
    const mk = (l.arrow === 'end' || l.arrow === 'both') ? ' marker-end="url(#mE)"' : '';
    const ms = (l.arrow === 'start' || l.arrow === 'both') ? ' marker-start="url(#mE)"' : '';
    out.push('<path class="hit" data-l="' + l.id + '" d="' + r.d + '"/>');
    out.push('<path class="ln' + (SEL.has(l.id) ? ' sel' : '') + '" data-l="' + l.id + '" d="' + r.d + '" style="stroke:' + col + ';stroke-width:' + (l.sw || (hot ? 2 : 1.6)) + (l.dash ? ';stroke-dasharray:6 5' : '') + '"' + mk + ms + '/>');
    if (l.label){
      const w = l.label.length * 6.6 + 14;
      out.push('<g class="lbl" data-l="' + l.id + '"><rect x="' + (r.m[0] - w / 2) + '" y="' + (r.m[1] - 10) + '" width="' + w + '" height="20" rx="6"/><text x="' + r.m[0] + '" y="' + (r.m[1] + 4) + '" text-anchor="middle">' + esc(l.label) + '</text></g>');
    }
  }
  if (extra) out.push('<path class="temp" d="' + extra + '"/>');
  wires.innerHTML = out.join('');
}

/* ═══ БЛОК 9: группы, выделение, рамка-выделение, направляющие ═══ */
function groupOf(id){ return B.groups.find(g => g.ids.includes(id)); }
function groupsDraw(){
  groupsBox.innerHTML = '';
  for (const g of B.groups){
    const bs = g.ids.map(item).filter(Boolean).map(bbox); if (bs.length < 2) continue;
    const x = Math.min(...bs.map(b => b.x)), y = Math.min(...bs.map(b => b.y));
    const r = Math.max(...bs.map(b => b.x + b.w)), bm = Math.max(...bs.map(b => b.y + b.h));
    const d = document.createElement('div'); d.className = 'grp'; d.dataset.g = g.id;
    d.style.cssText = 'left:' + (x - 14) + 'px;top:' + (y - 22) + 'px;width:' + (r - x + 28) + 'px;height:' + (bm - y + 36) + 'px';
    d.innerHTML = '<b contenteditable="true" spellcheck="false"></b>'; d.querySelector('b').textContent = g.t || 'группа';
    d.querySelector('b').addEventListener('blur', e => { g.t = e.target.textContent.trim() || 'группа'; dirty(); });
    groupsBox.appendChild(d);
  }
}
function select(ids, add){
  if (!add) SEL.clear();
  for (const i of ids) SEL.add(i);
  for (const [id, n] of NODES) n.classList.toggle('sel', SEL.has(id));
  wire(); selUI();
}
function selItems(){ return [...SEL].map(item).filter(Boolean); }
function selBBox(){
  const bs = selItems().map(bbox); if (!bs.length) return null;
  return {x: Math.min(...bs.map(b => b.x)), y: Math.min(...bs.map(b => b.y)),
          x2: Math.max(...bs.map(b => b.x + b.w)), y2: Math.max(...bs.map(b => b.y + b.h))};
}
/* рамка выделения с ручками и панель свойств над ней */
function selUI(){
  const bb = selBBox(), one = selItems().length === 1 ? selItems()[0] : null;
  if (!bb){ selbox.style.display = 'none'; propsDraw(null); return; }
  selbox.style.display = 'block';
  selbox.style.cssText = 'display:block;left:' + (bb.x - 2) + 'px;top:' + (bb.y - 2) + 'px;width:' + (bb.x2 - bb.x + 4) + 'px;height:' + (bb.y2 - bb.y + 4) + 'px';
  selbox.classList.toggle('one', !!one && !one.locked && one.type !== 'pen');
  propsDraw(one || (SEL.size ? 'many' : null), bb);
}
function movers(id){
  let ids = SEL.has(id) ? [...SEL] : [id];
  const grow = () => { const n = ids.length; for (const i of [...ids]){ const g = groupOf(i); if (g) ids.push(...g.ids); } ids = [...new Set(ids)]; return ids.length > n; };
  while (grow());
  /* рамка везёт то, что внутри неё */
  for (const i of [...ids]){ const f = item(i); if (f && f.type === 'frame') ids.push(...inside(f).map(x => x.id)); }
  return [...new Set(ids)].filter(i => item(i) && !item(i).locked);
}
function inside(f){
  const fb = bbox(f);
  return B.items.filter(it => it.id !== f.id && it.type !== 'frame' && (() => { const b = bbox(it); const cx = b.x + b.w / 2, cy = b.y + b.h / 2; return cx > fb.x && cx < fb.x + fb.w && cy > fb.y && cy < fb.y + fb.h; })());
}
/* умные направляющие: края и центры соседей, прилипание в 6 px экрана */
function guide(ids, bb){
  const th = 6 / B.view.z, others = B.items.filter(i => !ids.includes(i.id)).map(bbox);
  let dx = 0, dy = 0, lines = [];
  const xs = [bb.x, (bb.x + bb.x2) / 2, bb.x2], ys = [bb.y, (bb.y + bb.y2) / 2, bb.y2];
  let bx = null, by = null;
  for (const o of others){
    for (const ox of [o.x, o.x + o.w / 2, o.x + o.w]) for (const x of xs){ const d = ox - x; if (Math.abs(d) < th && (bx === null || Math.abs(d) < Math.abs(bx.d))) bx = {d, v: ox}; }
    for (const oy of [o.y, o.y + o.h / 2, o.y + o.h]) for (const y of ys){ const d = oy - y; if (Math.abs(d) < th && (by === null || Math.abs(d) < Math.abs(by.d))) by = {d, v: oy}; }
  }
  if (bx){ dx = bx.d; lines.push('<line x1="' + bx.v + '" y1="-99999" x2="' + bx.v + '" y2="99999"/>'); }
  if (by){ dy = by.d; lines.push('<line x1="-99999" y1="' + by.v + '" x2="99999" y2="' + by.v + '"/>'); }
  guides.innerHTML = lines.join('');
  return [dx, dy];
}

/* ═══ БЛОК 10: инструменты и мышь ═══ */
function setTool(t){
  TOOL = t;
  for (const b of document.querySelectorAll('#btools [data-t]')) b.classList.toggle('on', b.dataset.t === t);
  flow.dataset.tool = t;
  $('shapes').classList.toggle('open', t === 's');   // у фигуры сразу видна палитра форм
}
let shapeKind = 'round', noteColor = 'yellow', penColor = '#5fbf7a';
function add(it, quiet){
  hist(); it.id = it.id || nid(it.type[0]); it.z = Math.max(0, ...B.items.map(i => i.z || 0)) + 1;
  B.items.push(it); draw(it); if (!quiet){ select([it.id], false); } dirty(); return it;
}
function newAt(type, x, y){
  if (type === 'note') return add({type, x: x - 80, y: y - 80, w: 160, h: 160, text: '', color: noteColor});
  if (type === 'text') return add({type, x: x - 100, y: y - 12, w: 200, h: 0, text: '', size: 18});
  if (type === 'shape') return add({type, x: x - 80, y: y - 50, w: 160, h: 100, kind: shapeKind, fill: 'none', stroke: '#c9c9c9', text: ''});
  if (type === 'frame') return add({type, x: x - 200, y: y - 140, w: 400, h: 280, t: 'Рамка', fill: 'none'});
  if (type === 'card') return add({type, x: x - 120, y: y - 40, w: 240, h: 0, t: 'Новый блок', d: 'что это', why: 'почему это нужно', ok: 0});
  if (type === 'code') return add({type, x: x - 160, y: y - 60, w: 320, h: 120, t: 'код', text: ''});
  return null;
}
layer.addEventListener('mousedown', e => {
  if (e.button === 2) return;
  if (e.button === 1){ e.preventDefault(); pan(e); return; }        // нажатое колёсико — сдвиг доски даже над элементом
  const pin = e.target.closest('.pin'), n = e.target.closest('.el'); if (!n) return;
  const it = item(n.dataset.id); if (!it) return;
  if ('ntsfckp'.includes(TOOL) && !pin) return;          // инструмент создания: клик по занятому месту тоже создаёт
  e.stopPropagation(); if (!n.classList.contains('edit')) e.preventDefault();
  if (TOOL === 'h'){ pan(e); return; }
  if (pin || TOOL === 'l'){ startLink(it.id, pin ? pin.dataset.p : null, e); return; }
  if (n.classList.contains('edit')) return;
  if (TOOL !== 'v'){ setTool('v'); }
  if (!SEL.has(it.id)) select([it.id], e.ctrlKey || e.shiftKey || e.metaKey);
  else if (e.ctrlKey || e.metaKey){ SEL.delete(it.id); select([...SEL], false); return; }
  if (it.locked) return;
  if (e.altKey){ duplicate(); }
  const ids = movers(it.id), start = ids.map(i => ({it: item(i), x: item(i).x, y: item(i).y}));
  const k = K() * B.view.z, s = {x: e.clientX, y: e.clientY};
  let moved = false, pushed = false;
  const move = ev => {
    if (!moved){ moved = true; }
    if (!pushed){ pushed = true; hist(); }
    let ddx = (ev.clientX - s.x) / k, ddy = (ev.clientY - s.y) / k;
    for (const st of start){ st.it.x = st.x + ddx; st.it.y = st.y + ddy; }
    const bb = selBBox() || {x: start[0].it.x, y: start[0].it.y, x2: start[0].it.x + bbox(start[0].it).w, y2: start[0].it.y + bbox(start[0].it).h};
    let [gx, gy] = ev.altKey ? [0, 0] : guide(ids, bb);
    if (SNAP && !gx && !gy && !ev.altKey){ const g = 13; const rx = Math.round(bb.x / g) * g - bb.x, ry = Math.round(bb.y / g) * g - bb.y; if (Math.abs(rx) < 5 / B.view.z) gx = rx; if (Math.abs(ry) < 5 / B.view.z) gy = ry; }
    for (const st of start){ st.it.x = Math.round(st.it.x + gx); st.it.y = Math.round(st.it.y + gy); const nn = NODES.get(st.it.id); nn.style.left = st.it.x + 'px'; nn.style.top = st.it.y + 'px'; }
    wire(); groupsDraw(); selUI();
  };
  const up = () => { guides.innerHTML = ''; if (moved) dirty();  };
  track(move, up);
});
/* ручки изменения размера */
selbox.addEventListener('mousedown', e => {
  const h = e.target.closest('.hd'); if (!h) return;
  e.stopPropagation(); e.preventDefault();
  const it = selItems()[0]; if (!it) return;
  hist();
  const b0 = bbox(it), k = K() * B.view.z, s = {x: e.clientX, y: e.clientY}, d = h.dataset.h, keep = it.type === 'image' && !e.shiftKey;
  const move = ev => {
    let dx = (ev.clientX - s.x) / k, dy = (ev.clientY - s.y) / k;
    let x = b0.x, y = b0.y, w = b0.w, hh = b0.h;
    if (d.includes('e')) w = b0.w + dx; if (d.includes('s')) hh = b0.h + dy;
    if (d.includes('w')){ w = b0.w - dx; x = b0.x + dx; } if (d.includes('n')){ hh = b0.h - dy; y = b0.y + dy; }
    if (keep){ const r = b0.w / b0.h; if (d.includes('e') || d.includes('w')) hh = w / r; else w = hh * r; }
    w = Math.max(40, w); hh = Math.max(24, hh);
    it.x = Math.round(x); it.y = Math.round(y); it.w = Math.round(w); it.h = Math.round(hh);
    if (it.type === 'pen'){ const sx = it.w / b0.w, sy = it.h / b0.h; it.points = it.points.map(p => [it.x + (p[0] - b0.x) * sx, it.y + (p[1] - b0.y) * sy]); }
    const n = NODES.get(it.id); n.dataset.sig = ''; draw(it); if (it.type === 'note') fitNote(n, it);
    wire(); groupsDraw(); selUI();
  };
  const up = () => { dirty();  };
  track(move, up);
});
/* пустое место: сдвиг, рамка выделения, создание, карандаш */
function pan(e){
  const k = K(), s = {x: e.clientX, y: e.clientY, px: B.view.px, py: B.view.py};
  let moved = false; flow.classList.add('drag');
  const move = ev => { moved = true; B.view.px = s.px + (ev.clientX - s.x) / k; B.view.py = s.py + (ev.clientY - s.y) / k; view(); };
  const up = () => { flow.classList.remove('drag'); if (moved) dirty(); else if (TOOL === 'v') select([], false);  };
  track(move, up);
}
flow.addEventListener('mousedown', e => {
  if (e.button === 2) return;
  const making = 'ntsfckp'.includes(TOOL) && !e.target.closest('.pin');
  if ((!making && e.target.closest('.el')) || e.target.closest('.grp b') || e.target.closest('#btools') || e.target.closest('#props') || e.target.closest('#bhead') || e.target.closest('#bzoom') || e.target.closest('path[data-l]') || e.target.closest('.lbl') || e.target.closest('#selbox')) return;
  ctx.style.display = 'none';
  if (!e.target.isContentEditable) e.preventDefault();   // иначе тянется синее выделение текста
  if (e.button === 1){ pan(e); return; }                   // нажатое колёсико — сдвиг доски при любом инструменте
  const [bx, by] = toBoard(e.clientX, e.clientY);
  if (TOOL === 'p'){ pen(e); return; }
  if (['n', 't', 's', 'f', 'c', 'k'].includes(TOOL)){
    e.preventDefault();                                   // иначе браузер после mousedown заберёт фокус у нового элемента
    const it = newAt({n: 'note', t: 'text', s: 'shape', f: 'frame', c: 'card', k: 'code'}[TOOL], bx, by);
    setTool('v'); if (it) edit(NODES.get(it.id), true); return;
  }
  if (TOOL === 'v' && (e.shiftKey || e.ctrlKey || e.metaKey)){ marquee(e); return; }
  if (TOOL === 'v' && e.button === 1){ pan(e); return; }
  if (TOOL === 'v'){ marquee(e, true); return; }
  pan(e);
});
function marquee(e, orPan){
  const r = flow.getBoundingClientRect(), k = K(), s = {x: (e.clientX - r.left) / k, y: (e.clientY - r.top) / k, cx: e.clientX, cy: e.clientY, px: B.view.px, py: B.view.py};
  let mode = null, add = e.shiftKey || e.ctrlKey || e.metaKey;
  const move = ev => {
    if (!mode){ if (Math.hypot(ev.clientX - s.cx, ev.clientY - s.cy) < 4) return; mode = (orPan && ev.buttons === 1 && !add && (ev.altKey || false)) ? 'pan' : 'box'; if (orPan && !add && !mode) mode = 'box'; }
    if (mode === 'pan'){ B.view.px = s.px + (ev.clientX - s.cx) / k; B.view.py = s.py + (ev.clientY - s.cy) / k; view(); return; }
    const x = (ev.clientX - r.left) / k, y = (ev.clientY - r.top) / k;
    lasso.style.cssText = 'display:block;left:' + Math.min(s.x, x) + 'px;top:' + Math.min(s.y, y) + 'px;width:' + Math.abs(x - s.x) + 'px;height:' + Math.abs(y - s.y) + 'px';
  };
  const up = ev => {
    if (mode === 'box'){
      const lb = lasso.getBoundingClientRect(), hit = [];
      for (const [id, n] of NODES){ const cb = n.getBoundingClientRect(); if (item(id).type !== 'frame' && cb.right > lb.left && cb.left < lb.right && cb.bottom > lb.top && cb.top < lb.bottom) hit.push(id); }
      lasso.style.display = 'none'; select(hit, add);
    } else if (!mode){ if (!add) select([], false); }
    else dirty();
  };
  track(move, up);
}
/* прокрутка — зум к курсору; Shift + прокрутка — сдвиг вбок; перемещение — нажатым колёсиком или рукой */
flow.addEventListener('wheel', e => {
  e.preventDefault();
  if (e.shiftKey){ B.view.px -= e.deltaY / K(); view(); dirty(); return; }
  zoomAt(e.clientX, e.clientY, B.view.z * (e.deltaY < 0 ? 1.12 : 1 / 1.12));
}, {passive: false});
flow.addEventListener('dblclick', e => {
  if (e.target.closest('.el') || e.target.closest('.grp b') || e.target.closest('#btools') || e.target.closest('#props') || e.target.closest('#bhead') || e.target.closest('#bzoom') || e.target.closest('path[data-l]') || e.target.closest('.lbl')) return;
  const [bx, by] = toBoard(e.clientX, e.clientY);
  const it = newAt('note', bx, by); edit(NODES.get(it.id), true);
});
/* карандаш */
function pen(e){
  hist();
  const pts = [toBoard(e.clientX, e.clientY)];
  const it = {id: nid('p'), type: 'pen', x: pts[0][0], y: pts[0][1], w: 1, h: 1, points: pts, color: penColor, sw: 2.5, z: Math.max(0, ...B.items.map(i => i.z || 0)) + 1};
  B.items.push(it);
  const move = ev => {
    const p = toBoard(ev.clientX, ev.clientY); const l = pts[pts.length - 1]; if (Math.hypot(p[0] - l[0], p[1] - l[1]) < 2 / B.view.z) return;
    pts.push(p);
    const xs = pts.map(q => q[0]), ys = pts.map(q => q[1]);
    it.x = Math.min(...xs); it.y = Math.min(...ys); it.w = Math.max(1, Math.max(...xs) - it.x); it.h = Math.max(1, Math.max(...ys) - it.y);
    const n = NODES.get(it.id); if (n) n.dataset.sig = ''; draw(it);
  };
  const up = () => {  if (pts.length < 2){ B.items = B.items.filter(i => i !== it); NODES.get(it.id)?.remove(); NODES.delete(it.id); } else dirty(); };
  track(move, up);
}
/* связь: тянем от пина или от элемента при инструменте «связь» */
function startLink(id, side, e){
  const A = bbox(item(id));
  const move = ev => {
    const p = toBoard(ev.clientX, ev.clientY);
    const s1 = side || sides(A, {x: p[0], y: p[1], w: 0, h: 0})[0];
    wire(route(pinAt(A, s1), s1, p, s1 === 'r' ? 'l' : s1 === 'l' ? 'r' : s1 === 'b' ? 't' : 'b', 'curve').d);
  };
  const up = ev => {
    if (ev.clientX == null){ wire(); return; }             // окно потеряло фокус — связь не создаём
    const t = document.elementFromPoint(ev.clientX, ev.clientY), n = t && t.closest ? t.closest('.el') : null;
    if (n && n.dataset.id !== id){
      const b = n.dataset.id, pin2 = t.closest('.pin');
      if (!B.links.some(l => (l.a === id && l.b === b) || (l.a === b && l.b === id))){
        hist(); const l = {id: nid('l'), a: id, b, ap: side || null, bp: pin2 ? pin2.dataset.p : null, arrow: 'end', style: 'curve'};
        B.links.push(l); dirty(); select([l.id], false);
      }
    }
    wire();
  };
  track(move, up);
}
wires.addEventListener('mousedown', e => {
  const p = e.target.closest('path[data-l]') || e.target.closest('.lbl'); if (!p) return;
  e.stopPropagation(); select([p.dataset.l], e.ctrlKey || e.shiftKey);
});
wires.addEventListener('dblclick', e => {
  const p = e.target.closest('[data-l]'); if (!p) return;
  e.stopPropagation(); const l = link(p.dataset.l); if (!l) return;
  const v = prompt('Подпись связи', l.label || ''); if (v === null) return;
  hist(); l.label = v.trim(); dirty(); wire();
});

/* ═══ БЛОК 11: правка текста ═══ */
function fields(n){ return [...n.querySelectorAll('.t, .d, .why, .txt, .ttl, .cap')]; }
function edit(n, on){
  const it = item(n.dataset.id); if (!it) return;
  if (on && it.locked) return;
  n.classList.toggle('edit', on);
  for (const f of fields(n)){ f.contentEditable = on ? 'true' : 'false'; if (on) f.classList.remove('none'); }
  if (on){
    hist();
    const f = it.type === 'card' ? n.querySelector('.t') : (it.type === 'frame' ? n.querySelector('.ttl') : (it.type === 'code' ? n.querySelector('pre') : n.querySelector('.txt')));
    if (f){ f.focus(); const rg = document.createRange(); rg.selectNodeContents(f); const sl = getSelection(); sl.removeAllRanges(); sl.addRange(rg); }
    return;
  }
  const g = q => (n.querySelector(q) || {}).textContent || '';
  if (it.type === 'card'){ it.t = g('.t').trim(); it.d = g('.d').trim(); it.why = g('.why').trim(); }
  else if (it.type === 'frame') it.t = g('.ttl').trim() || 'Рамка';
  else if (it.type === 'code'){ it.t = g('.cap').trim() || 'код'; it.text = g('pre'); }
  else it.text = g('.txt');
  if (it.type === 'text') it.h = 0;
  n.dataset.sig = ''; draw(it); if (it.type === 'note') fitNote(n, it);
  dirty(); wire(); groupsDraw(); selUI();
}
layer.addEventListener('dblclick', e => {
  const n = e.target.closest('.el'); if (!n) return;
  e.stopPropagation(); const it = item(n.dataset.id);
  if (e.target.closest('h4 s') && it.type === 'card'){ hist(); it.ok = it.ok ? 0 : 1; n.dataset.sig = ''; draw(it); wire(); dirty(); return; }
  if (it.type === 'image' || it.type === 'pen') return;
  edit(n, true);
});
layer.addEventListener('focusout', e => { const n = e.target.closest && e.target.closest('.el.edit'); if (n && !n.contains(e.relatedTarget)) edit(n, false); });
layer.addEventListener('keydown', e => { if (e.key === 'Escape' && e.target.isContentEditable) e.target.blur(); if (e.key === 'Enter' && !e.shiftKey && e.target.closest('.t, .ttl, .cap')){ e.preventDefault(); e.target.blur(); } });
layer.addEventListener('paste', e => {
  if (!e.target.isContentEditable) return;
  e.preventDefault(); document.execCommand('insertText', false, (e.clipboardData || window.clipboardData).getData('text/plain'));
});

/* ═══ БЛОК 12: действия — удалить, дубль, группа, порядок, замок ═══ */
function drop(){
  if (!SEL.size) return; hist();
  for (const id of SEL){
    if (item(id)){ B.items = B.items.filter(i => i.id !== id); B.links = B.links.filter(l => l.a !== id && l.b !== id); B.groups.forEach(g => g.ids = g.ids.filter(i => i !== id)); }
    else B.links = B.links.filter(l => l.id !== id);
  }
  B.groups = B.groups.filter(g => g.ids.length > 1); SEL.clear(); render(); dirty();
}
function copy(){ const its = selItems().filter(i => !i.locked); if (!its.length) return; CLIP = JSON.stringify({items: its, links: B.links.filter(l => SEL.has(l.a) && SEL.has(l.b))}); }
function paste(at){
  if (!CLIP) return; const o = JSON.parse(CLIP); hist();
  const map = {}, bb = {x: Math.min(...o.items.map(i => i.x)), y: Math.min(...o.items.map(i => i.y))};
  const dx = at ? at[0] - bb.x : 24, dy = at ? at[1] - bb.y : 24, zmax = Math.max(0, ...B.items.map(i => i.z || 0));
  o.items.forEach((it, i) => { const c = Object.assign({}, it); c.id = nid(c.type[0]); map[it.id] = c.id; c.x += dx; c.y += dy; c.z = zmax + i + 1; c.locked = false;
    if (c.points) c.points = c.points.map(p => [p[0] + dx, p[1] + dy]); B.items.push(c); });
  for (const l of o.links) B.links.push(Object.assign({}, l, {id: nid('l'), a: map[l.a], b: map[l.b]}));
  render(); select(Object.values(map), false); dirty();
}
function duplicate(){ copy(); paste(); }
function group(){ const ids = selItems().map(i => i.id); if (ids.length < 2) return; hist(); B.groups = B.groups.filter(g => !g.ids.some(i => ids.includes(i))); B.groups.push({id: nid('g'), ids, t: 'группа'}); groupsDraw(); dirty(); }
function ungroup(){ const ids = selItems().map(i => i.id); hist(); B.groups = B.groups.filter(g => !g.ids.some(i => ids.includes(i))); groupsDraw(); dirty(); }
function order(up){ const its = selItems(); if (!its.length) return; hist(); const ext = up ? Math.max(0, ...B.items.map(i => i.z || 0)) : Math.min(0, ...B.items.map(i => i.z || 0)); its.forEach((it, i) => it.z = up ? ext + i + 1 : ext - its.length + i); render(); dirty(); }
function lock(){ const its = selItems(); if (!its.length) return; hist(); const v = !its.every(i => i.locked); its.forEach(i => i.locked = v); render(); dirty(); }
function nudge(dx, dy){ const its = selItems().filter(i => !i.locked); if (!its.length) return; hist(); for (const it of its){ it.x += dx; it.y += dy; if (it.points) it.points = it.points.map(p => [p[0] + dx, p[1] + dy]); const n = NODES.get(it.id); n.style.left = it.x + 'px'; n.style.top = it.y + 'px'; } wire(); groupsDraw(); selUI(); dirty(); }
function setProp(k, v){
  hist();
  for (const id of SEL){ const it = item(id) || link(id); if (!it) continue; it[k] = v; const n = NODES.get(id); if (n){ n.dataset.sig = ''; draw(it); if (it.type === 'note') fitNote(n, it); } }
  wire(); dirty(); selUI();
}

/* ═══ БЛОК 13: панель свойств над выделением, контекстное меню ═══ */
function propsDraw(what, bb){
  if (!what && !SEL.size){ props.style.display = 'none'; return; }
  const one = what && what !== 'many' ? what : null, l = SEL.size === 1 ? link([...SEL][0]) : null;
  const items = [];
  const sw = (k, vals, cur, named) => vals.map(v => '<i class="sw' + (cur === v ? ' on' : '') + '" data-k="' + k + '" data-v="' + v + '" style="--c:' + (named ? NOTE_COLORS[v] : (v === 'none' ? 'transparent' : v)) + '" title="' + v + '"></i>').join('');
  if (l){
    items.push('<span class="grp1"><b data-a="arrow" data-v="none" class="' + ((l.arrow || 'end') === 'none' ? 'on' : '') + '" title="без стрелок">—</b><b data-a="arrow" data-v="end" class="' + ((l.arrow || 'end') === 'end' ? 'on' : '') + '" title="стрелка в конце">→</b><b data-a="arrow" data-v="both" class="' + (l.arrow === 'both' ? 'on' : '') + '" title="обе">↔</b></span>');
    items.push('<span class="grp1"><b data-a="style" data-v="curve" class="' + ((l.style || 'curve') === 'curve' ? 'on' : '') + '" title="дуга">∿</b><b data-a="style" data-v="straight" class="' + (l.style === 'straight' ? 'on' : '') + '" title="прямая">╱</b><b data-a="style" data-v="elbow" class="' + (l.style === 'elbow' ? 'on' : '') + '" title="уголком">⌐</b></span>');
    items.push('<span class="grp1"><b data-a="dash" data-v="' + (l.dash ? 0 : 1) + '" class="' + (l.dash ? 'on' : '') + '" title="пунктир">┄</b><b data-a="label" title="подпись">Aa</b></span>');
    items.push('<span class="grp1 cols">' + sw('color', STROKES, l.color || '') + '</span>');
  } else if (one){
    if (one.type === 'note') items.push('<span class="grp1 cols">' + sw('color', Object.keys(NOTE_COLORS), one.color || 'yellow', true) + '</span>');
    if (one.type === 'shape'){
      items.push('<span class="grp1">' + Object.keys(SHAPES).map(k => '<b data-a="kind" data-v="' + k + '" class="' + (one.kind === k ? 'on' : '') + '" title="' + SHAPES[k] + '"><svg viewBox="0 0 24 16"><path d="' + shapePath(k, 22, 14) + '" transform="translate(1,1)" fill="none" stroke="currentColor" stroke-width="1.5"/></svg></b>').join('') + '</span>');
      items.push('<span class="grp1 cols" title="заливка">' + sw('fill', FILLS, one.fill || 'none') + '</span>');
      items.push('<span class="grp1 cols" title="обводка">' + sw('stroke', STROKES, one.stroke || '#c9c9c9') + '</span>');
      items.push('<span class="grp1"><b data-a="dash" data-v="' + (one.dash ? 0 : 1) + '" class="' + (one.dash ? 'on' : '') + '" title="пунктир">┄</b></span>');
    }
    if (one.type === 'text') items.push('<span class="grp1"><b data-a="size" data-v="-" title="меньше">A−</b><b class="v">' + (one.size || 18) + '</b><b data-a="size" data-v="+" title="больше">A+</b><b data-a="bold" data-v="' + (one.bold ? 0 : 1) + '" class="' + (one.bold ? 'on' : '') + '" title="жирный">B</b><b data-a="align" data-v="left" class="' + ((one.align || 'left') === 'left' ? 'on' : '') + '">≡</b><b data-a="align" data-v="center" class="' + (one.align === 'center' ? 'on' : '') + '">☰</b></span><span class="grp1 cols">' + sw('color', STROKES, one.color || '') + '</span>');
    if (one.type === 'pen') items.push('<span class="grp1 cols">' + sw('color', STROKES, one.color || '') + '</span>');
    if (one.type === 'frame') items.push('<span class="grp1 cols">' + sw('fill', FILLS, one.fill || 'none') + '</span>');
    if (one.type === 'card') items.push('<span class="grp1"><b data-a="ok" data-v="' + (one.ok ? 0 : 1) + '" class="' + (one.ok ? 'on' : '') + '">' + (one.ok ? 'работает' : 'следующий этап') + '</b></span>');
  }
  if (what === 'many' || one) items.push('<span class="grp1"><b data-a="front" title="выше (Ctrl+])">⇡</b><b data-a="back" title="ниже (Ctrl+[)">⇣</b><b data-a="dup" title="дубль (Ctrl+D)">⧉</b><b data-a="lock" class="' + (selItems().every(i => i.locked) ? 'on' : '') + '" title="замок (Ctrl+L)">🔒</b>' + (SEL.size > 1 ? '<b data-a="group" title="группа (Ctrl+G)">▣</b>' : '') + '<b data-a="del" title="удалить (Del)">✕</b></span>');
  else items.push('<span class="grp1"><b data-a="del" title="удалить (Del)">✕</b></span>');
  props.innerHTML = items.join('');
  props.style.display = 'flex';
  /* над выделением, в экранных координатах борда */
  let x, y;
  if (bb){ x = (bb.x + bb.x2) / 2 * B.view.z + B.view.px; y = bb.y * B.view.z + B.view.py - 46; }
  else { const el = wires.querySelector('path.ln.sel'); const r = el ? el.getBoundingClientRect() : null, fr = flow.getBoundingClientRect();
    x = r ? ((r.left + r.right) / 2 - fr.left) / K() : 200; y = r ? (r.top - fr.top) / K() - 46 : 60; }
  const fw = flow.getBoundingClientRect().width / K();
  props.style.left = Math.max(60, Math.min(fw - 60, x)) + 'px'; props.style.top = Math.max(56, y) + 'px';
}
props.addEventListener('mousedown', e => e.stopPropagation());
props.addEventListener('click', e => {
  const sw = e.target.closest('.sw'); if (sw){ setProp(sw.dataset.k, sw.dataset.v); return; }
  const b = e.target.closest('[data-a]'); if (!b) return;
  const a = b.dataset.a, v = b.dataset.v;
  if (a === 'arrow' || a === 'style' || a === 'kind' || a === 'align') setProp(a, v);
  else if (a === 'dash' || a === 'bold' || a === 'ok') setProp(a, +v);
  else if (a === 'size'){ const it = selItems()[0]; setProp('size', Math.max(10, Math.min(96, (it.size || 18) + (v === '+' ? 2 : -2)))); }
  else if (a === 'label'){ const l = link([...SEL][0]); const t = prompt('Подпись связи', l.label || ''); if (t !== null){ hist(); l.label = t.trim(); dirty(); wire(); } }
  else if (a === 'front') order(true); else if (a === 'back') order(false);
  else if (a === 'dup') duplicate(); else if (a === 'lock') lock(); else if (a === 'group') group(); else if (a === 'del') drop();
});
/* контекстное меню */
flow.addEventListener('contextmenu', e => {
  e.preventDefault();
  const n = e.target.closest('.el'), p = e.target.closest('[data-l]');
  if (n && !SEL.has(n.dataset.id)) select([n.dataset.id], false);
  else if (p && !SEL.has(p.dataset.l)) select([p.dataset.l], false);
  else if (!n && !p) select([], false);                   // правый клик по пустому — меню пустого места
  const has = SEL.size > 0, rows = [];
  if (has){ rows.push(['copy', 'Копировать', 'Ctrl+C'], ['dup', 'Дублировать', 'Ctrl+D'], ['front', 'На передний план', 'Ctrl+]'], ['back', 'На задний план', 'Ctrl+['], ['lock', 'Замок', 'Ctrl+L']);
    if (SEL.size > 1) rows.push(['group', 'Сгруппировать', 'Ctrl+G']); if (selItems().some(i => groupOf(i.id))) rows.push(['ungroup', 'Разгруппировать', 'Ctrl+Shift+G']);
    rows.push(['del', 'Удалить', 'Del']); }
  else { rows.push(['paste', 'Вставить сюда', 'Ctrl+V'], ['note', 'Стикер', 'N'], ['text', 'Текст', 'T'], ['shape', 'Фигура', 'S'], ['frame', 'Рамка', 'F'], ['card', 'Карточка', 'C'], ['code', 'Код', 'K'], ['fit', 'Вписать всё', '1'], ['reset', 'Вернуть вид', '0']); }
  ctx.innerHTML = rows.map(r => '<b data-a="' + r[0] + '"><span>' + r[1] + '</span><em>' + r[2] + '</em></b>').join('');
  const fr = flow.getBoundingClientRect(), k = K();
  ctx.style.cssText = 'display:block;left:' + ((e.clientX - fr.left) / k) + 'px;top:' + ((e.clientY - fr.top) / k) + 'px';
  ctx.dataset.bx = toBoard(e.clientX, e.clientY).join(',');
});
ctx.addEventListener('mousedown', e => e.stopPropagation());
ctx.addEventListener('click', e => {
  const b = e.target.closest('[data-a]'); if (!b) return; const a = b.dataset.a, at = ctx.dataset.bx.split(',').map(Number);
  ctx.style.display = 'none';
  if (a === 'copy') copy(); else if (a === 'dup') duplicate(); else if (a === 'front') order(true); else if (a === 'back') order(false);
  else if (a === 'lock') lock(); else if (a === 'group') group(); else if (a === 'ungroup') ungroup(); else if (a === 'del') drop();
  else if (a === 'paste') paste(at); else if (a === 'fit') fit(); else if (a === 'reset'){ B.view = {px: 30, py: 20, z: 1}; view(); dirty(); }
  else { const it = newAt(a, at[0], at[1]); if (it) edit(NODES.get(it.id), true); }
});
addEventListener('mousedown', e => { if (!ctx.contains(e.target)) ctx.style.display = 'none'; if (!$('shapes').contains(e.target) && !e.target.closest('[data-t="s"]')) $('shapes').classList.remove('open'); if (!$('blist').contains(e.target) && !e.target.closest('#bname')) $('blist').classList.remove('open'); });

/* ═══ БЛОК 14: панель инструментов, доски, картинки, клавиши ═══ */
$('btools').addEventListener('click', e => {
  const b = e.target.closest('[data-t]'); if (!b) return;
  const t = b.dataset.t;
  if (t === 's' && TOOL === 's'){ $('shapes').classList.toggle('open'); return; }
  if (t === 'i'){ $('bpick').click(); return; }
  if (t === 'undo'){ undo(); return; } if (t === 'redo'){ redo(); return; }
  if (t === 'snap'){ SNAP = !SNAP; b.classList.toggle('on', SNAP); return; }
  setTool(t);
});
$('shapes').addEventListener('click', e => { const b = e.target.closest('[data-k]'); if (!b) return; shapeKind = b.dataset.k; for (const x of $('shapes').querySelectorAll('b')) x.classList.toggle('on', x === b); $('shapes').classList.remove('open'); });
$('bzoom').addEventListener('click', e => {
  const b = e.target.closest('[data-z]'); if (!b) return; const r = flow.getBoundingClientRect();
  if (b.dataset.z === '+') zoomAt(r.left + r.width / 2, r.top + r.height / 2, B.view.z * 1.25);
  else if (b.dataset.z === '-') zoomAt(r.left + r.width / 2, r.top + r.height / 2, B.view.z / 1.25);
  else if (b.dataset.z === 'fit') fit(); else { B.view = {px: 30, py: 20, z: 1}; view(); dirty(); }
});
/* картинки: кнопка, перетаскивание файла на доску, Ctrl+V */
function addImage(file, at){
  if (!file || !file.type.startsWith('image/') || file.size > 3 * 1024 * 1024) return;
  const rd = new FileReader();
  rd.onload = () => { const im = new Image(); im.onload = () => { const w = Math.min(420, im.width), h = w * im.height / im.width;
    const p = at || toBoard(innerWidth / 2, innerHeight / 2); add({type: 'image', x: p[0] - w / 2, y: p[1] - h / 2, w: Math.round(w), h: Math.round(h), src: rd.result}); }; im.src = rd.result; };
  rd.readAsDataURL(file);
}
$('bpick').addEventListener('change', () => { for (const f of $('bpick').files) addImage(f); $('bpick').value = ''; });
flow.addEventListener('dragstart', e => e.preventDefault());       // никакого нативного перетаска текста и картинок с доски
flow.addEventListener('dragover', e => { e.preventDefault(); e.stopPropagation(); });
flow.addEventListener('drop', e => { e.preventDefault(); e.stopPropagation(); const at = toBoard(e.clientX, e.clientY); for (const f of e.dataTransfer.files) addImage(f, at); });
addEventListener('paste', e => {
  if (!document.body.classList.contains('flow') || (document.activeElement && document.activeElement.isContentEditable)) return;
  const files = [...(e.clipboardData.files || [])].filter(f => f.type.startsWith('image/'));
  if (files.length){ e.preventDefault(); files.forEach(f => addImage(f)); return; }
  const t = e.clipboardData.getData('text/plain');
  if (t && !CLIP){ e.preventDefault(); const p = toBoard(innerWidth / 2, innerHeight / 2); add({type: 'note', x: p[0] - 80, y: p[1] - 80, w: 160, h: 160, text: t.slice(0, 400), color: noteColor}); }
  else if (CLIP){ e.preventDefault(); paste(); }
});
/* доски */
$('bname').addEventListener('click', async e => {
  e.stopPropagation();
  const box = $('blist'); if (box.classList.toggle('open')){
    await listBoards();
    box.innerHTML = BOARDS.map(b => '<b data-b="' + esc(b.id) + '" class="' + (b.id === B.id ? 'on' : '') + '"><span>' + esc(b.name) + '</span><em data-x="' + esc(b.id) + '" title="удалить">✕</em></b>').join('')
      + '<b data-new="1"><span>+ новая доска</span></b><b data-ren="1"><span>переименовать текущую</span></b>';
  }
});
$('blist').addEventListener('click', async e => {
  const x = e.target.closest('[data-x]');
  if (x){ e.stopPropagation(); const id = x.dataset.x; if (id === B.id || !confirm('Удалить доску «' + id + '»?')) return;
    try { await fetch('/api/board/' + encodeURIComponent(id), {method: 'DELETE'}); } catch (err){} localStorage.removeItem('hear.board.' + id); $('bname').click(); $('bname').click(); return; }
  const b = e.target.closest('[data-b]'); if (b){ $('blist').classList.remove('open'); if (b.dataset.b !== B.id) await loadBoard(b.dataset.b); return; }
  if (e.target.closest('[data-new]')){ $('blist').classList.remove('open'); const name = prompt('Название доски', 'Доска ' + (BOARDS.length + 1)); if (!name) return;
    const id = 'b' + Date.now().toString(36); B = {id, name, view: {px: 30, py: 20, z: 1}, items: [], links: [], groups: []}; SEL.clear(); UNDO = []; REDO = []; NODES.clear(); layer.innerHTML = '';
    render(); view(); $('bname').textContent = name; try { localStorage.setItem('hear.board', id); } catch (err){} dirty(); return; }
  if (e.target.closest('[data-ren]')){ $('blist').classList.remove('open'); const name = prompt('Название доски', B.name); if (!name) return; B.name = name; $('bname').textContent = name; dirty(); }
});
/* клавиши */
addEventListener('keydown', e => {
  if (!document.body.classList.contains('flow')) return;
  const a = document.activeElement;
  if (a && (a.isContentEditable || a.tagName === 'INPUT' || a.tagName === 'TEXTAREA')) return;
  const c = e.ctrlKey || e.metaKey, k = e.key.toLowerCase();
  if (c && k === 'z'){ e.preventDefault(); e.shiftKey ? redo() : undo(); }
  else if (c && k === 'y'){ e.preventDefault(); redo(); }
  else if (c && k === 'c'){ e.preventDefault(); copy(); }
  else if (c && k === 'v'){ /* вставка — через событие paste */ }
  else if (c && k === 'd'){ e.preventDefault(); duplicate(); }
  else if (c && k === 'a'){ e.preventDefault(); select(B.items.map(i => i.id), false); }
  else if (c && k === 'g'){ e.preventDefault(); e.shiftKey ? ungroup() : group(); }
  else if (c && k === 'l'){ e.preventDefault(); lock(); }
  else if (c && e.key === ']'){ e.preventDefault(); order(true); }
  else if (c && e.key === '['){ e.preventDefault(); order(false); }
  else if (e.key === 'Delete' || e.key === 'Backspace'){ e.preventDefault(); drop(); }
  else if (e.key === 'Escape'){ if (TOOL !== 'v') setTool('v'); else select([], false); ctx.style.display = 'none'; }
  else if (e.key.startsWith('Arrow')){ e.preventDefault(); const s = e.shiftKey ? 10 : 1; nudge(e.key === 'ArrowLeft' ? -s : e.key === 'ArrowRight' ? s : 0, e.key === 'ArrowUp' ? -s : e.key === 'ArrowDown' ? s : 0); }
  else if (!c && 'vhntslfpck'.includes(k) && e.key.length === 1){ setTool(k); }
  else if (e.key === '0'){ B.view = {px: 30, py: 20, z: 1}; view(); dirty(); }
  else if (e.key === '1'){ fit(); }
  else if (e.key === '=' || e.key === '+'){ const r = flow.getBoundingClientRect(); zoomAt(r.left + r.width / 2, r.top + r.height / 2, B.view.z * 1.2); }
  else if (e.key === '-'){ const r = flow.getBoundingClientRect(); zoomAt(r.left + r.width / 2, r.top + r.height / 2, B.view.z / 1.2); }
});
/* пробел зажат — временно рука */
let spaceTool = null;
addEventListener('keydown', e => { if (e.key === ' ' && document.body.classList.contains('flow') && !(document.activeElement && document.activeElement.isContentEditable) && spaceTool === null){ e.preventDefault(); spaceTool = TOOL; setTool('h'); } });
addEventListener('keyup', e => { if (e.key === ' ' && spaceTool !== null){ setTool(spaceTool); spaceTool = null; } });

/* ═══ БЛОК 15: вход — открытие с Λ ═══ */
let opened = false;
window.drawFlow = async function(){
  if (!opened){ opened = true; setTool('v'); $('shapes').innerHTML = Object.keys(SHAPES).map(k => '<b data-k="' + k + '" class="' + (k === shapeKind ? 'on' : '') + '" title="' + SHAPES[k] + '"><svg viewBox="0 0 28 20"><path d="' + shapePath(k, 26, 18) + '" transform="translate(1,1)" fill="none" stroke="currentColor" stroke-width="1.5"/></svg></b>').join('');
    let id = 'main'; try { id = localStorage.getItem('hear.board') || 'main'; } catch (e){}
    await loadBoard(id);
  } else { view(); wire(); }
};
})();
