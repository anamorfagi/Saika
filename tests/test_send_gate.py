"""ОТПРАВКА — ТОЛЬКО ПО ПОДТВЕРЖДЕНИЮ.

Живой случай 20.08.2026: в окне чата с ИИ-соавтором она напечатала ссылку
и нажала Enter — сообщение ушло живому человеку. Владелец: «по поводу
отправки сообщения — как ей удалось в целом отправить тебе. Отправка
любого диалога ввода должна быть через подтверждение отправить.
Единственная механика, где не нужны подтверждения, — когда явно просят
открыть ту или иную инфу в браузере».

До этой правки запрет жил только в докстринге press(): «это правило
протокола, не кода». Правило, которое знает только модель, — пожелание.
"""
import re
import time


def run():
    rows = []
    from anamorf import send_gate as sg
    from anamorf.config import CFG

    real = sg._target
    was = CFG.get("hands.confirm_send", True)
    try:
        CFG.set("hands.confirm_send", True)

        def look(proc, hwnd=11, title="окно"):
            sg._target = lambda: {"proc": proc, "hwnd": hwnd, "title": title}

        def clean():
            sg.PEND.update(on=False)
            sg.TYPED.update(hwnd=0, proc="", text="", ts=0.0)
            sg.WEB.update(until=0.0)

        # 1. Печатали в чат -> Enter придерживаем и спрашиваем.
        clean(); look("claude", 11, "Claude")
        sg.note_typed("https://пример", {"hwnd": 11, "proc": "claude.exe"})
        ask = sg.check("enter")
        rows.append(("в чат сама не отправляет",
                     bool(ask) and "ОТПРАВЛЯТЬ?" in ask, ask[:70]))

        # 2. Мессенджер — даже если мы туда не печатали (текст мог набрать
        #    человек, а нас попросили «нажми ввод»).
        clean(); look("telegram", 22, "Telegram")
        rows.append(("мессенджер тоже под правилом",
                     bool(sg.check("enter")), "telegram + enter"))

        # 3. ИСКЛЮЧЕНИЕ ВЛАДЕЛЬЦА: открытый цикл работы с браузером.
        clean(); look("chrome", 33, "Google Chrome")
        sg.allow_web("ютуб музыка")
        rows.append(("в браузере по просьбе — без вопросов",
                     sg.check("enter") == "", "web_open открыл цикл"))

        # 4. …но тот же браузер БЕЗ просьбы — снова под правилом: там
        #    может быть открыт веб-мессенджер.
        clean(); look("chrome", 33, "Google Chrome")
        sg.note_typed("привет", {"hwnd": 33, "proc": "chrome.exe"})
        rows.append(("браузер без просьбы — спрашиваем",
                     bool(sg.check("enter")), "цикл не открыт"))

        # 5. Блокнот — не отправка: Enter там просто перевод строки.
        clean(); look("notepad", 44, "Безымянный")
        rows.append(("в блокноте не мешаем", sg.check("enter") == "",
                     "notepad + enter"))

        # 6. Другие клавиши правило не трогает.
        clean(); look("telegram", 22)
        rows.append(("ctrl+s правилом не задет",
                     sg.check("ctrl+s") == "", "сохранение — не отправка"))

        # 7. Несказанное «да» согласием не считается.
        clean(); look("claude", 11)
        sg.note_typed("текст", {"hwnd": 11, "proc": "claude.exe"})
        sg.check("enter")
        alive = bool(sg.pending())
        sg.PEND["ts"] = time.time() - sg._life() - 1
        rows.append(("молчание не считается согласием",
                     alive and not sg.pending(),
                     "предложение протухает само"))

        # 8. Отмена — это отмена, а не «ну ладно».
        clean(); look("claude", 11)
        sg.note_typed("текст", {"hwnd": 11, "proc": "claude.exe"})
        sg.check("enter")
        msg = sg.cancel("человек передумал")
        rows.append(("отказ снимает предложение",
                     not sg.pending() and "Не отправляю" in msg, msg[:50]))

        # 9. ГЛАВНОЕ ПРО СЛОВА: «не отправляй» подходит под оба выражения,
        #    и при ничьей побеждает отказ — отправленное не отзывается.
        yes = re.compile(r"\b(?:отправ(?:ляй|ь|ляйте|им)|шли|пошли|посылай|"
                         r"жми\s+(?:ввод|энтер|enter)|да[,\s]+отправ\w*|"
                         r"подтвержда\w+)\b", re.I)
        no = re.compile(r"\b(?:не\s+(?:отправ\w*|надо|нужно|шли|посылай)|"
                        r"отмен\w+|стой|стоп|погод\w*|подожд\w*|сотри|"
                        r"убери|не\s+вздумай)\b", re.I)

        def decide(t):                      # тот же порядок, что в main.py
            if no.search(t):
                return "нет"
            return "да" if yes.search(t) else "—"
        table = {"отправляй": "да", "да, отправь": "да", "шли": "да",
                 "жми ввод": "да", "подтверждаю": "да",
                 "не отправляй": "нет", "не надо": "нет", "отмена": "нет",
                 "стой": "нет", "сотри": "нет",
                 "ага": "—", "угу": "—", "ну ладно": "—"}
        bad = [t for t, want in table.items() if decide(t) != want]
        rows.append(("«не отправляй» — это НЕТ", not bad,
                     f"{len(table)} фраз" if not bad else f"спорят: {bad}"))
    finally:
        sg._target = real
        sg.PEND.update(on=False)
        CFG.set("hands.confirm_send", was)
    return rows
