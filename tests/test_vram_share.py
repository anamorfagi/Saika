"""ОДНА ВИДЕОКАРТА НА ДВОИХ: окно разговора против клон-голоса.

Живой вечер 22.08.2026: 12.7 ГБ из 16.4 занимал llama-server, клон-голос
просил ~5 и весь вечер не поднимался — «на qwen3 не осталось
видеопамяти, её занимает моя же LLM». Виновато было правило «беру большее
из двух ключей окна»: оно тянуло 32768 из настроек ДРУГОГО движка
(locallm_gguf — это T-lite), и за чужой ключ расплачивался голос.

Проверяем ровно две вещи, и обе — про честный делёж:
  1. при тяжёлом голосе окно ужимается до потолка;
  2. при лёгком (или выключенном) голосе окно не трогаем — там делить
     нечего, и урезать разговор без причины нельзя.

Тест меняет конфиг — и обязан вернуть всё как было (см. test_triage:
прогон теста не имеет права переписать настройки машины).
"""


def run():
    rows = []
    from anamorf.config import CFG
    from anamorf.llm import llamacpp

    was_tts = CFG.get("tts.engine", "")
    was_on = CFG.get("tts.enabled", True)
    was_ctx = (CFG.get("llamacpp") or {}).get("n_ctx")
    try:
        def ctx_of(args):
            return int(args[args.index("--ctx-size") + 1])

        CFG.set("llamacpp.n_ctx", 32768)
        CFG.set("tts.enabled", True)

        CFG.set("tts.engine", "qwen3")
        a = llamacpp._args("модель.gguf", 0)
        got = ctx_of(a)
        rows.append(("тяжёлый голос — окно ужимается",
                     got <= 16384, f"окно {got}"))

        CFG.set("tts.engine", "silero")
        b = llamacpp._args("модель.gguf", 0)
        got2 = ctx_of(b)
        rows.append(("лёгкий голос — окно не трогаем",
                     got2 == 32768, f"окно {got2}"))

        CFG.set("tts.engine", "off")
        c = llamacpp._args("модель.gguf", 0)
        got3 = ctx_of(c)
        rows.append(("голоса нет — делить нечего, окно целое",
                     got3 == 32768, f"окно {got3}"))
    finally:
        CFG.set("tts.engine", was_tts)
        CFG.set("tts.enabled", was_on)
        if was_ctx is not None:
            CFG.set("llamacpp.n_ctx", was_ctx)

    return rows
