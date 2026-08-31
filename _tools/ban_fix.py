# -*- coding: utf-8 -*-
"""Ноль в рейтинге = выключено человеком. Автопуск обязан это уважать."""
import io, sys
p = sys.argv[1]
s = io.open(p, encoding='utf-8').read()

a = """          if cfg_pick[1] and cfg_pick in cands:
              cands.remove(cfg_pick)
              cands.insert(0, cfg_pick)
              log.info("Автопуск: начинаю с выбранной человеком %s/%s — "
                       "рейтинг подождёт", *cfg_pick)"""
b = """          # НОЛЬ — ЭТО НЕ НИЗКИЙ РЕЙТИНГ, ЭТО «ВЫКЛЮЧЕНО РУКАМИ»
          # (27.08.2026, владелец: «какого хуя постоянно врублена или
          # переключается ллм на те, что даже в рейтинге в нулину
          # выключены»). В системе жили два взаимоисключающих правила:
          # автопуск ставил первой «выбранную человеком» модель, а отбор
          # при ответе выкидывал модели с оценкой 0 как запрещённые. Если
          # это одна и та же модель — а именно так и было, — она грелась,
          # занимала карту и не звалась ни разу: «ни одна LLM не ответила»
          # при полностью рабочем мозге.
          # Ноль ставит человек, руками, в той же таблице. Значит ноль
          # старше записи llm.model: это его более позднее решение.
          try:
              _ban = {ratings.norm_name(n)
                      for n, v in (ratings.manual_scores() or {}).items()
                      if not v}
              def _is_ban(nm):
                  nn = ratings.norm_name(nm)
                  return nn in _ban or any(
                      x and nn and (x in nn or nn in x)
                      and min(len(x), len(nn)) >= 6 for x in _ban)
              _drop = [c for c in cands if _is_ban(c[1])]
              if _drop:
                  cands = [c for c in cands if not _is_ban(c[1])]
                  log.info("Автопуск: пропускаю выключенные нулём: %s",
                           ", ".join(m for _b, m in _drop)[:160])
              if cfg_pick[1] and _is_ban(cfg_pick[1]):
                  log.warning("Автопуск: в настройках записана «%s», но у неё "
                              "оценка 0 — это «выключено руками». Беру "
                              "лучшую разрешённую, а настройку исправляю.",
                              cfg_pick[1])
                  cfg_pick = ("", "")
                  if cands:
                      CFG.set("llm.backend", cands[0][0])
                      CFG.set("llm.model", cands[0][1])
          except Exception as _eban:
              log.debug("фильтр нулевых оценок в автопуске: %s", _eban)
          if cfg_pick[1] and cfg_pick in cands:
              cands.remove(cfg_pick)
              cands.insert(0, cfg_pick)
              log.info("Автопуск: начинаю с выбранной человеком %s/%s — "
                       "рейтинг подождёт", *cfg_pick)"""
assert s.count(a) == 1, 'cfg_pick block'
io.open(p, 'w', encoding='utf-8').write(s.replace(a, b))
print('ok')
