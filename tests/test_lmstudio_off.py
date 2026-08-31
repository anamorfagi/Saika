"""LM STUDIO НЕ ДЕРЖИТ ВТОРУЮ МОДЕЛЬ (2026-08-23).

Владелец: «найди, из-за чего наша модель на C++ запускалась вместе с
моделью из ЛМ с похожим названием, и убери этот баг».

Механика бага: LM Studio поднимает модель в память по ЛЮБОМУ запросу к
себе, даже по «покажи список». Сайка опрашивала его регулярно — и на
карте в 16 ГБ жили ДВЕ копии похожей модели: её собственный llama-server
и невидимый двойник в LM Studio. Выключатель существовал с 22.08, но по
умолчанию был ВКЛЮЧЁН, а строчка «выключить» ждала правки конфига руками.
"""


def run():
    rows = []
    from anamorf.config import CFG
    from anamorf.llm import manager as m

    was_use = CFG.get("llm.use_lmstudio", None)
    was_bk = CFG.get("llm.backend", "")
    try:
        # 1) наш backend=llamacpp, явного выбора нет -> LM Studio не трогаем
        CFG.set("llm.backend", "llamacpp")
        try:
            CFG.set("llm.use_lmstudio", None)
        except Exception:
            pass
        rows.append(("при своих мозгах (llamacpp) LM Studio не опрашивается",
                     m._down("lmstudio") is True, ""))

        # 2) кто работает через LM Studio — у того всё живо
        CFG.set("llm.backend", "lmstudio")
        m._DOWN.pop("lmstudio", None)
        rows.append(("при backend=lmstudio опросы разрешены",
                     m._down("lmstudio") is False, ""))

        # 3) явный выбор человека главнее умолчаний
        CFG.set("llm.backend", "llamacpp")
        CFG.set("llm.use_lmstudio", True)
        m._DOWN.pop("lmstudio", None)
        rows.append(("явное use_lmstudio=true уважается",
                     m._down("lmstudio") is False, ""))
        CFG.set("llm.use_lmstudio", False)
        rows.append(("явное use_lmstudio=false уважается",
                     m._down("lmstudio") is True, ""))
    finally:
        CFG.set("llm.backend", was_bk)
        CFG.set("llm.use_lmstudio", was_use)
    return rows
