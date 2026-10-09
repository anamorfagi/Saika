/* Live source research. Separate from author seed creation and observation replay. */
(() => {
  'use strict';
  const API = 'http://127.0.0.1:8770', STORE = 'gs_research_job';
  const esc = x => String(x ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const safeURL = value => { try { const u = new URL(value); return /^https?:$/.test(u.protocol) ? u.href : ''; } catch { return ''; } };
  let busy = false, polling = false, cursor = 0, job = null, history = [], latest = null;
  try { job = JSON.parse(localStorage.getItem(STORE) || 'null'); } catch {}
  const style = document.createElement('style');
  style.textContent = `#researchDock{position:fixed;right:18px;bottom:18px;left:auto;width:min(760px,calc(50vw - 20px));min-width:420px;z-index:90;background:rgba(15,13,19,.97);border:1px solid #66563b;border-radius:12px;box-shadow:0 12px 40px #0009;padding:14px;color:#dad3c5;font:12px/1.5 var(--fm,monospace)}#researchDock header{display:flex;align-items:center;gap:10px}#researchDock h3{flex:1;margin:0;font-size:14px;color:var(--gold,#cfae70)}#researchDock button{background:none;color:#cfae70;border:1px solid #514839;border-radius:5px;cursor:pointer;padding:3px 8px}#researchDock .researchProgress{display:grid;grid-template-columns:repeat(5,1fr);gap:4px;margin:9px 0 5px}#researchDock .researchProgress i{height:5px;background:#342f33;border-radius:3px}#researchDock .researchProgress i.done{background:#cfae70}#researchDock .researchProgress i.active{background:#71bfb7;animation:researchWalk 1.1s ease-in-out infinite}@keyframes researchWalk{50%{opacity:.35}}#researchDock .researchPhase{font-size:11px;color:#c7b78d;min-height:17px}#researchDock .researchLog{max-height:240px;overflow:auto;margin:10px 0;overflow-wrap:anywhere}#researchDock .researchEvent{border-left:2px solid #66563b;padding:4px 8px;margin:5px 0}#researchDock .researchEvent[data-stage=evidence]{border-color:#6bbeb4}#researchDock .researchEvent[data-stage=error],#researchDock .researchEvent[data-stage=source_error]{border-color:#d97474}#researchDock a{color:#9cbed1}#researchDock blockquote{margin:4px 0;color:#ddd}#researchDock .researchStatus{color:#a3a0b0}#researchDock .researchTotals{margin-top:8px;padding-top:8px;border-top:1px solid rgba(233,226,236,.14);color:#c7b78d;line-height:1.6}#researchDock .researchTotals:empty{display:none}#researchDock .researchTotals button{margin-left:6px}#researchDock[data-folded=true] .researchDetails{display:none}.body.researchMode{overflow:auto;padding-right:10px}.researchWork{padding:28px 4px 12px}.researchWork h2{margin:8px 0;font-size:28px}.researchQuery{color:#bcb4a8;margin:0 0 18px}.researchWorkProgress{display:grid;grid-template-columns:repeat(5,1fr);gap:5px}.researchWorkProgress i{height:6px;background:#302d32;border-radius:4px}.researchWorkProgress i.done{background:#cfae70}.researchWorkProgress i.active{background:#70bdb4;animation:researchWalk 1.1s ease-in-out infinite}.researchStages{display:grid;grid-template-columns:repeat(5,1fr);font:10px var(--fm,monospace);color:#7e7883;margin:5px 0 20px}.researchMetrics{display:grid;grid-template-columns:auto 1fr auto 1fr;gap:5px 10px;padding:12px;border:1px solid #443c32;background:#151318;border-radius:8px;margin-bottom:17px}.researchMetrics b{font:600 20px var(--fm,monospace);color:#d7b66f}.researchMetrics span{font:10px/1.25 var(--fm,monospace);color:#938c84}.researchWorkHead{font:600 12px var(--fm,monospace);color:#d7b66f;margin-bottom:8px}.researchWorkHead small{float:right;color:#77717c;font-weight:400}.researchWorkLog{border-top:1px solid #38323a}.researchWorkEvent{padding:9px 10px;border-left:2px solid #635645;border-bottom:1px solid #2a272d}.researchWorkEvent.evidence{border-left-color:#70bdb4}.researchWorkEvent.error,.researchWorkEvent.source_error{border-left-color:#d97474}.researchWorkAt{font:10px var(--fm,monospace);color:#8c8390;margin-bottom:2px}.researchWorkEvent a{display:inline-block;margin-top:3px;color:#9cbed1}.researchWorkEvent button{margin-top:5px}.researchEmpty{color:#8c8390}@media(max-width:1000px){#researchDock{right:12px;bottom:48px;width:calc(100vw - 24px);min-width:0}}body.researchPulse #body{box-shadow:inset 3px 0 #6bbeb4}
#researchPane{position:fixed;top:64px;right:16px;width:min(620px,42vw);max-height:calc(100vh - 88px);
  overflow:auto;z-index:95;background:rgba(13,11,18,.97);border:1px solid rgba(233,226,236,.16);
  border-radius:12px;box-shadow:0 18px 60px #000a;padding:4px 18px 16px;color:#dad3c5;
  font:12px/1.5 var(--fm,monospace);backdrop-filter:blur(3px)}
#researchPane .researchWork{padding:14px 0 4px}
#researchPane h2{margin:6px 0 2px;font-size:24px}
#researchPane .researchFold{position:sticky;top:0;display:flex;justify-content:flex-end;gap:8px;
  padding:8px 0 4px;background:linear-gradient(rgba(13,11,18,.99),rgba(13,11,18,.86));z-index:2}
#researchPane .researchFold button{background:none;color:#cfae70;border:1px solid rgba(233,226,236,.18);
  border-radius:6px;cursor:pointer;padding:4px 10px;font:11px var(--fm,monospace)}
#researchPane .researchFold button:hover{border-color:#cfae70}
#researchPane[data-min=true] .researchWork{display:none}
#researchPane[data-min=true]{width:260px}
@media(max-width:1200px){#researchPane{width:min(520px,52vw)}}
/* Окно живого поиска ведёт себя как окно Windows: за шапку тянут, за края тянут размер. */
#researchPane .researchFold{cursor:move;user-select:none}
#researchPane .researchTitle{flex:1;font:10px var(--fm,monospace);color:#8c8390;font-weight:400;
  letter-spacing:.08em;text-transform:uppercase;align-self:center}
#researchPane .researchFold button{cursor:pointer}
#researchPane .researchGrip{position:absolute;z-index:3}
#researchPane .researchGrip[data-edge=n]{top:-3px;left:10px;right:10px;height:7px;cursor:ns-resize}
#researchPane .researchGrip[data-edge=s]{bottom:-3px;left:10px;right:10px;height:7px;cursor:ns-resize}
#researchPane .researchGrip[data-edge=w]{left:-3px;top:10px;bottom:10px;width:7px;cursor:ew-resize}
#researchPane .researchGrip[data-edge=e]{right:-3px;top:10px;bottom:10px;width:7px;cursor:ew-resize}
#researchPane .researchGrip[data-edge=nw]{top:-4px;left:-4px;width:14px;height:14px;cursor:nwse-resize}
#researchPane .researchGrip[data-edge=ne]{top:-4px;right:-4px;width:14px;height:14px;cursor:nesw-resize}
#researchPane .researchGrip[data-edge=sw]{bottom:-4px;left:-4px;width:14px;height:14px;cursor:nesw-resize}
#researchPane .researchGrip[data-edge=se]{bottom:-4px;right:-4px;width:14px;height:14px;cursor:nwse-resize}
#researchPane .researchGrip[data-edge=se]::after{content:'';position:absolute;right:3px;bottom:3px;
  width:8px;height:8px;border-right:2px solid rgba(207,174,112,.55);border-bottom:2px solid rgba(207,174,112,.55)}
body.researchDragging{user-select:none;cursor:move}
body.researchSizing{user-select:none}`;
  document.head.appendChild(style);

  async function request(path, body) {
    const r = await fetch(API + path, {method: body === undefined ? 'GET' : 'POST',
      headers: body === undefined ? {} : {'Content-Type':'application/json'},
      body: body === undefined ? undefined : JSON.stringify(body), signal: AbortSignal.timeout(12000)});
    const data = await r.json();
    if (!r.ok || data.error) throw new Error(data.error || 'HTTP ' + r.status);
    return data;
  }

  function dock() {
    let el = document.getElementById('researchDock');
    if (el) return el;
    el = document.createElement('aside'); el.id = 'researchDock';
    el.innerHTML = `<header><h3>Сбор данных</h3><button data-action="fold" title="Свернуть журнал">−</button><button data-action="cancel">Стоп</button><button data-action="close" title="Закрыть панель">×</button></header><div class="researchDetails"><div class="researchProgress" aria-label="ход исследования"><i></i><i></i><i></i><i></i><i></i></div><div class="researchPhase"></div><div class="researchStatus"></div><label><input type="checkbox" data-follow checked> Следовать за новыми уликами</label><div class="researchLog" aria-live="polite"></div><div class="researchCounts"></div><div class="researchTotals"></div></div>`;
    document.body.appendChild(el);
    // Панель висела на экране после конца работы и не закрывалась вовсе.
    el.querySelector('[data-action=close]').onclick = () => {el.style.display = 'none';};
    el.querySelector('[data-action=fold]').onclick = () => {el.dataset.folded = el.dataset.folded === 'true' ? 'false' : 'true';};
    el.querySelector('[data-action=cancel]').onclick = async () => {
      if (!job) return;
      try {await request('/jobs/' + job.id + '/cancel', {}); status('Останавливаю после текущего сетевого запроса…');}
      catch (e) {status(e.message);}
    };
    return el;
  }

  // Окно живого поиска. Раньше оно писалось прямо в правую колонку (#body) и исчезало от
  // любого клика по гену или прокрутки колесом: студия перерисовывала карточку поверх.
  // Теперь это самостоятельная панель поверх страницы — её ничто не затирает. 2026-09-18.
  // Геометрия окна живого поиска: положение и размер переживают перезапуск студии.
  const ГЕОМ = 'anamorf.research.geom';

  function запомнитьГеом(el) {
    try {
      const r = el.getBoundingClientRect();
      localStorage.setItem(ГЕОМ, JSON.stringify({x: r.left, y: r.top, w: r.width, h: r.height}));
    } catch (e) {/* приватный режим — просто не запоминаем */}
  }

  function вернутьГеом(el) {
    let g = null;
    try {g = JSON.parse(localStorage.getItem(ГЕОМ) || 'null');} catch (e) {g = null;}
    if (!g || !isFinite(g.w) || g.w < 260) return;
    // Окно могло остаться за краем, если монитор сменился: возвращаем в видимую часть.
    const w = Math.min(Math.max(g.w, 320), innerWidth - 20);
    const h = Math.min(Math.max(g.h, 180), innerHeight - 20);
    const x = Math.min(Math.max(g.x, 0), innerWidth - w);
    const y = Math.min(Math.max(g.y, 0), innerHeight - h);
    Object.assign(el.style, {left: x + 'px', top: y + 'px', right: 'auto',
                             width: w + 'px', height: h + 'px', maxHeight: 'none'});
  }

  function сделатьОкном(el) {
    // Панель перерисовывается через innerHTML, и ручки вместе с ней стираются.
    // Поэтому проверяем не флаг на элементе, а то, есть ли ручки прямо сейчас.
    const первый = el.dataset.window !== 'true';
    if (el.querySelector('.researchGrip')) return;
    el.dataset.window = 'true';
    for (const край of ['n', 's', 'w', 'e', 'nw', 'ne', 'sw', 'se']) {
      const g = document.createElement('div');
      g.className = 'researchGrip'; g.dataset.edge = край;
      el.appendChild(g);
      g.addEventListener('pointerdown', ev => тянуть(ev, el, край));
    }
    if (первый) {
      // Слушатель на самой панели переживает перерисовку содержимого, вешаем один раз.
      el.addEventListener('pointerdown', ev => {
        const шапка = ev.target.closest('.researchFold');
        if (!шапка || ev.target.closest('button')) return;
        двигать(ev, el);
      });
      вернутьГеом(el);
    }
  }

  function зафиксировать(el) {
    // Пока окно держится на right/maxHeight, менять его размер нечем: переводим в left/top/px.
    const r = el.getBoundingClientRect();
    Object.assign(el.style, {left: r.left + 'px', top: r.top + 'px', right: 'auto',
                             width: r.width + 'px', height: r.height + 'px', maxHeight: 'none'});
    return r;
  }

  function двигать(ev, el) {
    ev.preventDefault();
    const r = зафиксировать(el);
    const dx = ev.clientX - r.left, dy = ev.clientY - r.top;
    document.body.classList.add('researchDragging');
    const шаг = e => {
      el.style.left = Math.min(Math.max(e.clientX - dx, -r.width + 80), innerWidth - 80) + 'px';
      el.style.top = Math.min(Math.max(e.clientY - dy, 0), innerHeight - 40) + 'px';
    };
    const стоп = () => {
      removeEventListener('pointermove', шаг); removeEventListener('pointerup', стоп);
      document.body.classList.remove('researchDragging'); запомнитьГеом(el);
    };
    addEventListener('pointermove', шаг); addEventListener('pointerup', стоп);
  }

  function тянуть(ev, el, край) {
    ev.preventDefault(); ev.stopPropagation();
    const r = зафиксировать(el);
    const x0 = ev.clientX, y0 = ev.clientY;
    document.body.classList.add('researchSizing');
    const шаг = e => {
      const dx = e.clientX - x0, dy = e.clientY - y0;
      let {left: x, top: y, width: w, height: h} = {left: r.left, top: r.top, width: r.width, height: r.height};
      if (край.includes('e')) w = r.width + dx;
      if (край.includes('s')) h = r.height + dy;
      if (край.includes('w')) {w = r.width - dx; x = r.left + dx;}
      if (край.includes('n')) {h = r.height - dy; y = r.top + dy;}
      if (w < 320) {if (край.includes('w')) x = r.left + r.width - 320; w = 320;}
      if (h < 180) {if (край.includes('n')) y = r.top + r.height - 180; h = 180;}
      Object.assign(el.style, {left: x + 'px', top: y + 'px', width: w + 'px', height: h + 'px'});
    };
    const стоп = () => {
      removeEventListener('pointermove', шаг); removeEventListener('pointerup', стоп);
      document.body.classList.remove('researchSizing'); запомнитьГеом(el);
    };
    addEventListener('pointermove', шаг); addEventListener('pointerup', стоп);
  }

  function pane() {
    let el = document.getElementById('researchPane');
    if (el) {сделатьОкном(el); return el;}
    el = document.createElement('div');
    el.id = 'researchPane';
    document.body.appendChild(el);
    сделатьОкном(el);
    return el;
  }
  function researchPanel(s) {
    const body = pane();
    if (CUR !== job?.id) return;
    dock().style.display = 'none';
    const phase = {queued:'Ожидание запуска',identify:'Устанавливаю объект',disambiguate:'Снимаю неоднозначность',sources:'Читаю источники',analyze:'Извлекаю улики и гены',done:'Сбор завершён',insufficient:'Недостаточно подтверждённых данных',error:'Сбор остановлен',cancelled:'Сбор остановлен',interrupted:'Работник остановлен'}[s.state] || s.state;
    const step = {queued:0,identify:1,disambiguate:1,sources:2,analyze:3,done:5,insufficient:4,error:1,cancelled:1,interrupted:1}[s.state] ?? 0;
    const active = !s.done;
    const rows = history.slice(-28).reverse().map(e => {
      const url = safeURL(e.url), label = url ? esc(new URL(url).hostname) : '';
      return `<article class="researchWorkEvent ${esc(e.stage)}"><div class="researchWorkAt">${esc(e.at?.slice(11,19) || '')} · ${esc(e.stage)}</div><div>${esc(e.message)}</div>${url?`<a href="${esc(url)}" target="_blank" rel="noopener noreferrer">${label} ↗</a>`:''}${e.quote?`<blockquote>${esc(e.quote)}</blockquote>`:''}${e.gene?`<button data-research-gene="${esc(e.gene)}">${esc(byId[e.gene]?.name||e.gene)} · ${Number(e.value).toFixed(2)} · ${Number(e.confidence).toFixed(2)}</button>`:''}</article>`;
    }).join('') || '<p class="researchEmpty">Жду первое фактическое событие работника…</p>';
    body.innerHTML = `<section class="researchWork"><div class="eyebrow">живое исследование · ${active?'выполняется':'остановлено'}</div><h2>${esc(phase)}</h2><p class="researchQuery">${esc(s.card?.meta?.research?.query || job.query || '')}</p><div class="researchWorkProgress">${[0,1,2,3,4].map(i=>`<i class="${i<step?'done':(i===step&&active?'active':'')}"></i>`).join('')}</div><div class="researchStages"><span>объект</span><span>поиск</span><span>чтение</span><span>улики</span><span>карточка</span></div><div class="researchMetrics"><b>${s.sources.length}</b><span>источников<br>прочитано</span><b>${s.evidence_count}</b><span>улик<br>принято</span><b>${s.card?.genes_captured||0}/360</b><span>генов<br>снято</span><b>${s.quality?.rejected||0}</b><span>строк<br>отклонено</span></div><div class="researchWorkHead">Журнал фактических операций <small>${history.length} событий</small></div><div class="researchWorkLog">${rows}</div></section>`;
    сделатьОкном(body);
    // кнопки поверх содержимого: свернуть в полоску или убрать совсем, не останавливая поиск
    const свёрнуто = body.dataset.min === 'true';
    body.insertAdjacentHTML('afterbegin',
      '<div class="researchFold"><b class="researchTitle">живое исследование · тянуть за шапку</b>' +
      '<button data-min>' + (свёрнуто ? 'развернуть' : 'свернуть') +
      '</button><button data-hide>закрыть окно</button></div>');
    body.querySelector('[data-min]').onclick = () => {
      body.dataset.min = свёрнуто ? 'false' : 'true'; researchPanel(s); };
    body.querySelector('[data-hide]').onclick = () => {
      body.remove(); dock().style.display = ''; };
    body.querySelectorAll('[data-research-gene]').forEach(b=>b.onclick=()=>{const g=byId[b.dataset.researchGene];if(g)select(g.i)});
  }

  function status(text) {dock().querySelector('.researchStatus').textContent = text;}
  function progress(s) {
    const step = {queued:0,identify:1,disambiguate:1,sources:2,analyze:3,done:5,error:1,cancelled:1,interrupted:1}[s.state] ?? 0;
    const bars = [...dock().querySelectorAll('.researchProgress i')];
    bars.forEach((bar, i) => bar.className = i < step ? 'done' : (i === step && !s.done ? 'active' : ''));
    const phase = {queued:'ожидание запуска',identify:'устанавливаю объект',disambiguate:'снимаю неоднозначность',sources:'читаю источники',analyze:'извлекаю улики и гены',done:'анализ завершён',error:'анализ не начался',cancelled:'остановлено',interrupted:'работник остановлен'}[s.state] || s.state;
    dock().querySelector('.researchPhase').textContent = phase + (s.state === 'analyze' ? ` · ${s.sources.length} источников` : '');
  }
  function put(e) {
    const log = dock().querySelector('.researchLog'), row = document.createElement('div');
    row.className = 'researchEvent'; row.dataset.stage = e.stage;
    const url = safeURL(e.url);
    row.innerHTML = `<div>${esc(e.message)}</div>${url ? `<a href="${esc(url)}" target="_blank" rel="noopener noreferrer">${esc(new URL(url).hostname)} ↗</a>` : ''}${e.quote ? `<blockquote>${esc(e.quote)}</blockquote>` : ''}${e.gene ? `<button data-gene="${esc(e.gene)}">${esc(byId[e.gene]?.name || e.gene)} · ${Number(e.value).toFixed(2)} · уверенность ${Number(e.confidence).toFixed(2)}</button>` : ''}`;
    row.querySelector('[data-gene]')?.addEventListener('click', () => { const g = byId[e.gene]; if (g) select(g.i); });
    log.appendChild(row); log.scrollTop = log.scrollHeight;
    // Keep browser DOM bounded; complete history lives in chars/<job>/events.jsonl.
    while (log.children.length > 300) log.firstChild.remove();
  }

  function updateCard(card) {
    const parsed = charFromFile(card);
    GENOMES[parsed.id] = parsed.genome; CHARS_META[parsed.id] = parsed.meta;
    const listed = CHARS.find(c => c.id === parsed.id);
    if (listed) Object.assign(listed, parsed.meta);
    const lc = JSON.parse(localStorage.getItem('gs_chars') || '{}');
    lc[parsed.id] = {genome:parsed.genome, meta:parsed.meta};
    localStorage.setItem('gs_chars', JSON.stringify(lc));
    if (CUR !== parsed.id) return;
    Object.assign(CHAR, parsed.meta);
    document.title = CHAR.name + ' — геном';
    // The existing brand renderer uses escaped strings from imported metadata.
    document.querySelector('.brand h1').innerHTML = `${CHAR.name} <em>«${CHAR.alias}»</em>`;
    for (const g of all) {
      const value = card.genome[g.id];
      if (!value || EDITS[g.id]) continue;
      [g.v,g.c,g.ev] = value;
      const stored = BLOCKS[g.bi].genes.find(x => x[0] === g.id);
      if (stored) {stored[2] = g.v; stored[3] = g.c; stored[5] = g.ev;}
    }
    applyContour(); refreshStats();
    if (sel >= 0) renderBody(all[sel], true);
    renderResearchCompiler(); renderTrace(); renderVoice(); renderArch(); renderChars();
  }

  async function tick() {
    if (!job || polling) return;
    polling = true;
    try {
      const s = await request('/jobs/' + job.id + '?after=' + cursor);
      latest = s;
      if (s.events.length || cursor === 0 || s.done) updateCard(s.card);
      for (const e of s.events) { history.push(e); put(e); }
      cursor = s.next;
      researchPanel(s);
      const last = s.events.filter(e => e.stage === 'evidence').at(-1);
      if (last && CUR === job.id) {
        document.body.classList.add('researchPulse');
        setTimeout(() => document.body.classList.remove('researchPulse'), 900);
        if (dock().querySelector('[data-follow]').checked && byId[last.gene]) { select(byId[last.gene].i); researchPanel(s); }
      }
      const names = {queued:'Ожидание',identify:'Определение персонажа',disambiguate:'Уточняю объект',sources:'Чтение источников',analyze:'Анализ реплик и поведения',done:'Поиск завершён',insufficient:'Недостаточно данных для карточки',error:'Исследование не началось',cancelled:'Остановлено',interrupted:'Работник был остановлен'};
      status(names[s.state] || s.state);
      progress(s);
      dock().querySelector('.researchCounts').textContent = `${s.sources.length} прочитанных источников · ${s.evidence_count} улик · ${s.card.genes_captured}/${s.card.genes_total} генов`;
      if (s.quality) dock().querySelector('.researchCounts').textContent += ` · проверок модели: ${s.quality.batches}; отклонено: ${s.quality.rejected}; пустых: ${s.quality.empty}`;
      dock().querySelector('[data-action=cancel]').hidden = s.done;
      const итоги = dock().querySelector('.researchTotals');
      if (s.done && итоги) {
        const первое = s.events?.[0]?.at || history[0]?.at, последнее = s.events?.at(-1)?.at || history.at(-1)?.at;
        let длилось = '';
        if (первое && последнее) {
          const сек = Math.max(0, Math.round((new Date(последнее) - new Date(первое)) / 1000));
          длилось = сек >= 60 ? `${Math.floor(сек / 60)} мин ${сек % 60} с` : `${сек} с`;
        }
        const принято = s.quality?.accepted ?? s.evidence_count;
        итоги.innerHTML = `<b>Итог.</b> ${names[s.state] || s.state}.` +
          (длилось ? ` Заняло ${длилось}.` : '') +
          ` Источников ${s.sources.length}, улик принято ${принято}` +
          (s.quality ? `, отклонено ${s.quality.rejected}, пустых ответов ${s.quality.empty}` : '') +
          `, генов снято ${s.card.genes_captured} из ${s.card.genes_total}.` +
          ` <button data-action="close2">закрыть</button>` +
          (плохо(s) ? ` <button data-action="retry">попробовать иначе</button>` : '');
        итоги.querySelector('[data-action=close2]').onclick = () => {dock().style.display = 'none';};
        const кн = итоги.querySelector('[data-action=retry]');
        if (кн) кн.onclick = () => переделать(s);
      }
      job.done = s.done; localStorage.setItem(STORE, JSON.stringify(job));
      if (!s.done) setTimeout(tick, 800);
    } catch (e) { status('Нет связи с работником: ' + e.message); if (!job.done) setTimeout(tick, 4000); }
    finally {polling = false;}
  }

  // Неудачей считаем всё, из чего карточки не вышло: ошибка, нехватка данных,
  // обрыв работника, ноль улик.
  function плохо(s) {
    if (!s || !s.done) return false;
    if (['error', 'insufficient', 'cancelled', 'interrupted'].includes(s.state)) return true;
    return !s.evidence_count;
  }

  // Переделка идёт в ТУ ЖЕ карточку: движок читает прошлый прогон, разбирает,
  // что не сработало, и заходит иначе. Новый персонаж не заводится.
  async function переделать(s) {
    if (busy) return;
    busy = true;
    status('Переделываю: разбираю прошлый заход…');
    try {
      const запрос = s.card?.meta?.research?.query || job?.query || '';
      const свежее = await request('/jobs', {
        query: запрос,
        origin: s.card?.meta?.research?.origin || '',
        retry: s.id || job?.id,
        cfg: apiCfg()});
      job = {id: свежее.id, query: запрос, done: false};
      localStorage.setItem(STORE, JSON.stringify(job));
      const t = dock().querySelector('.researchTotals');
      if (t) t.innerHTML = '';
      cursor = 0; history = [];
      tick();
    } catch (e) {
      status('Переделка не запустилась: ' + e.message);
    } finally {busy = false;}
  }

  async function start() {
    if (busy) return;
    const query = document.getElementById('ncN')?.value.trim();
    if (!query) {document.getElementById('ncN')?.focus(); return;}
    busy = true; dock(); status('Подключаю поиск…');
    try {
      const health = await request('/health');
      if (health.service !== 'genome-research') throw new Error('На порту другой сервис');
      const s = await request('/jobs', {query,origin:document.getElementById('ncFrom')?.value.trim() || '',cfg:apiCfg()});
      importChar(s.card);
      if (NC.ava) localStorage.setItem(avaKey(s.id), NC.ava);
      job = {id:s.id, query, done:false}; localStorage.setItem(STORE,JSON.stringify(job));
      saveState({char:s.id,page:'genome'});
      // Existing studio uses hash navigation to rebuild immutable genome references.
      location.hash = '#' + s.id;
    } catch (e) {status('Сбор не запущен: ' + e.message); put({stage:'error',message:e.message});}
    finally {busy = false;}
  }

  function bindQuery() {
    const button = document.getElementById('ncGo'), input = document.getElementById('ncN');
    if (!button || button.dataset.researchBound) return;
    button.dataset.researchBound = 'true'; button.textContent = 'собрать данные →';
    input.placeholder = 'Кого исследовать? Имя, произведение или описание';
    const summary = button.closest('.card')?.querySelector('p');
    if (summary) summary.textContent = 'Опиши, кого ищем. Геном установит имя и произведение, найдёт источники и покажет, как из реплик и поступков появляются улики на спирали.';
    const label = document.getElementById('ncSrc');
    const oldInput = input.oninput;
    input.oninput = function(e) {if(oldInput)oldInput.call(this,e);if(label)label.textContent='запрос на исследование · имя определяется по источникам';};
    if(label)label.textContent='запрос на исследование · имя определяется по источникам';
    // Keep the previously existing author-seed panel reachable as a separate action.
    const author = document.createElement('button'); author.className='open'; author.textContent='авторский замысел';
    author.onclick = button.onclick; button.after(author);
    button.onclick = start;
  }
  const originalBind = bindNewChar;
  bindNewChar = function(el) {originalBind(el); bindQuery();};
  bindQuery();
  async function discoverActiveJob() {
    // A local service launch (for example when file:// automation is unavailable)
    // still becomes visible in the studio without requiring a manual refresh.
    try {
      const active = await request('/jobs/latest');
      if (!active.id || (job && job.id === active.id)) return;
      // Завершённую чужую работу не подхватываем: она перетрёт открытую карточку.
      if (active.active === false && active.done) return;
      importChar(active.card);
      job = {id:active.id, query:active.card.meta?.research?.query || '', done:false};
      localStorage.setItem(STORE, JSON.stringify(job));
      saveState({char:active.id,page:'genome'});
      if (CUR !== active.id) location.hash = '#' + active.id;
      else {dock(); tick();}
    } catch (_) { /* worker is optional until the user starts research */ }
  }
  if (job && job.id === CUR) {dock();tick();}
  else discoverActiveJob();

  // Исследование могло быть запущено не из студии — скриптом, агентом или после
  // перезапуска работника. Раньше студия узнавала о нём только при загрузке
  // страницы, и запущенный сбор просто не отображался. Теперь она спрашивает
  // работника каждые четыре секунды, пока ничего не ведёт.
  setInterval(() => {
    if (polling) return;
    if (job && !job.done) return;
    discoverActiveJob();
  }, 4000);
})();
