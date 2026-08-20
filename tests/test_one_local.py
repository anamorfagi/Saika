"""ОДИН ЛОКАЛЬНЫЙ ДВИЖОК НА ВИДЕОКАРТУ.

Живой лог 20.08.2026, 09:03 — за тридцать девять секунд:
  09:03:13  locallm: запускаю воркер T-lite-it-2.1 (8B, 32k)
  09:03:18  ЗАЩИТА: VRAM 96% — выгружаю всё
  09:03:33  временно выключила ОЗВУЧКУ
  09:03:52  выгрузила локальные МОЗГИ
  09:04:11  ответ через 59 секунд
Разговор в этот момент шёл на llamacpp/gemma — она уже держала видеокарту.

Владелец, в третий раз про то же: «у нас есть своя ллм на c++, нафиг он
стартует ещё одну с лм студио такую же; я вот тебе уже об этом говорил, но
ты не правил — мне приходилось вырубать лм студио».
"""


def run():
    rows = []
    from anamorf.llm import one_local as ol
    from anamorf.config import CFG

    real = ol._alive
    was = CFG.get("llm.two_local_ok", False)
    try:
        # 1. Все четыре движка считаются держателями памяти, а не два:
        #    прошлая правка закрыла только llamacpp/locallm.
        rows.append(("сторожим все локальные движки",
                     set(ol.BACKENDS) == {"llamacpp", "locallm",
                                          "lmstudio", "ollama"},
                     " + ".join(ol.BACKENDS)))

        CFG.set("llm.two_local_ok", False)

        # 2. Видеокарту держит llamacpp — второй движок не поднимаем.
        ol._alive = lambda n: n == "llamacpp"
        for who in ("locallm", "lmstudio", "ollama"):
            no = ol.refuse(who)
            rows.append((f"{who} не лезет к занятой видеокарте",
                         bool(no) and "llamacpp" in no.get("error", ""),
                         (no.get("error", "")[:60] if no
                          else "пустил — а не должен был")))

        # 3. САМ СЕБЯ движок не блокирует: llamacpp, который уже жив,
        #    обязан прогреваться и отвечать как обычно.
        rows.append(("сам себе не мешает", ol.refuse("llamacpp") == {},
                     "llamacpp жив -> llamacpp пускаем"))

        # 4. Видеокарта свободна — пускаем всех.
        ol._alive = lambda n: False
        rows.append(("свободна — пускаем",
                     all(ol.refuse(n) == {} for n in ol.BACKENDS),
                     "ни один движок не держит память"))

        # 5. Человек попросил прямо — запрет снимается. Бережём железо,
        #    а не запрещаем им пользоваться.
        ol._alive = lambda n: n == "llamacpp"
        forced = ol.refuse("lmstudio", force=True)
        CFG.set("llm.two_local_ok", True)
        by_cfg = ol.refuse("lmstudio")
        rows.append(("прямая просьба сильнее запрета",
                     forced == {} and by_cfg == {},
                     "force=True и llm.two_local_ok пропускают"))
    finally:
        ol._alive = real
        CFG.set("llm.two_local_ok", was)
    return rows
