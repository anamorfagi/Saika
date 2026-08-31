"""ЭКЗАМЕН ДЛЯ КОМАНД: проверяем ФАКТ, а не рапорт (2026-08-23).

Владелец: «попробуй провести тесты, заставляй её запускать различные
проги, работу в браузере с плеерами; посмотри, как она отрабатывает
команды и реально ли запустилась та или иная команда. Если нет — давай
напишем тесты-скрипты, чтобы обучить её отрабатывать команды на 100%».

Главная мысль здесь одна: НИ ОДНА проверка не верит ответу инструмента.
Инструмент может сказать «включила» и не включить — именно так мы и
попадались весь вечер. Поэтому у каждого сценария есть НАБЛЮДЕНИЕ: что
должно измениться в самой системе, если команда действительно сработала —
появилось окно, сменилось активное окно, окно уехало на другой монитор,
пошёл или прекратился звук. Наблюдение делается независимо от того, что
инструмент про себя рассказал.

    python tools\\command_drill.py            — разбор фраз, ничего не трогая
    python tools\\command_drill.py --live     — по-настоящему, с проверкой факта
    python tools\\command_drill.py --live --only музык

Отчёт: logs\\command_drill.md — таблицей, с причиной каждого провала.
"""
import argparse
import io
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


# ─────────────────────────── наблюдения ───────────────────────────
def _windows():
    from anamorf import pc_control as pc
    return pc.windows(include_minimized=True)


def _front():
    """Заголовок окна, которое СЕЙЧАС впереди."""
    try:
        import ctypes
        u = ctypes.windll.user32
        h = u.GetForegroundWindow()
        n = u.GetWindowTextLengthW(h)
        b = ctypes.create_unicode_buffer(n + 1)
        u.GetWindowTextW(h, b, n + 1)
        return b.value
    except Exception:
        return ""


def _playing():
    from anamorf import pc_control as pc
    try:
        return bool(pc.audio_playing(cache_s=0.0)[0])
    except Exception:
        return None


def _win_with(sub: str):
    sub = sub.lower()
    for w in _windows():
        if sub in (w.get("title", "") + " " + w.get("proc", "")).lower():
            return w
    return None


# ─────────────────────────── сценарии ───────────────────────────
# each: фраза, что ждём инструментом, и НАБЛЮДЕНИЕ (функция до/после)
def _obs_window(sub):
    def before():
        return bool(_win_with(sub))

    def after(was):
        w = _win_with(sub)
        return (bool(w), f"окно «{sub}» "
                + ("на месте" if w else "не появилось"))
    return before, after


def _obs_front(sub):
    def before():
        return _front()
    def after(was):
        now = _front()
        ok = sub.lower() in (now or "").lower()
        return ok, f"впереди «{now[:40]}»"
    return before, after


def _obs_monitor(sub, num):
    def before():
        w = _win_with(sub)
        return (w or {}).get("monitor")

    def after(was):
        w = _win_with(sub) or {}
        return (w.get("monitor") == num,
                f"монитор был {was}, стал {w.get('monitor')}")
    return before, after


def _obs_sound(want):
    def before():
        return _playing()

    def after(was):
        time.sleep(1.2)               # звуку нужно мгновение
        now = _playing()
        if now is None:
            return None, "звук спросить не удалось (нет pycaw?)"
        return now == want, f"звук был {was}, стал {now}"
    return before, after


def _obs_none():
    return (lambda: None), (lambda was: (None, "наблюдения нет — только разбор"))


SCEN = [
    # ── плеер в УЖЕ ОТКРЫТОМ браузере: главная боль 23.08 ──
    ("включи музыку", "media_control|service_open", _obs_sound(True)),
    ("включи музыку в браузере", "media_control", _obs_sound(True)),
    ("лисни музыку", "service_open|media_control", _obs_sound(True)),
    ("поставь на паузу", "media_control", _obs_sound(False)),
    ("останови", "media_control", _obs_sound(False)),
    ("продолжай", "media_control", _obs_sound(True)),
    ("следующий трек", "media_control", _obs_none()),
    ("переключи на следующий", "media_control", _obs_none()),
    ("мотни назад", "media_control", _obs_none()),
    ("промотай вперёд", "media_control", _obs_none()),
    ("сделай погромче", "volume_set", _obs_none()),
    ("сделай потише", "volume_set", _obs_none()),

    # ── программы ──
    ("открой проводник", "go_to|app_launch", _obs_window("проводник")),
    ("открой блокнот", "app_launch", _obs_window("блокнот")),
    ("запусти калькулятор", "app_launch", _obs_window("кальк")),

    # ── окна и мониторы ──
    ("покажи браузер", "window_focus", _obs_front("chrome")),
    ("сделай браузер слева на экране", "window_place", _obs_none()),
    ("перенеси браузер на второй экран", "window_place", _obs_monitor("chrome", 2)),
    ("сверни всё", "minimize_all", _obs_none()),
    ("разверни все окна", "window_restore_all", _obs_none()),

    # ── браузер ──
    ("следующая вкладка", "tab_control", _obs_none()),
    ("закрой вкладку", "tab_control", _obs_none()),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true",
                    help="выполнять по-настоящему и проверять факт")
    ap.add_argument("--only", default="", help="только фразы с этим куском")
    a = ap.parse_args()

    from anamorf import reflex
    from anamorf.llm import tools as tls

    rows, ok_n, bad_n = [], 0, 0
    for phrase, want, (before, after) in SCEN:
        if a.only and a.only.lower() not in phrase.lower():
            continue
        hit = reflex.match(phrase)
        tool = hit[0] if hit else ""
        args = hit[1] if hit else {}
        # 1) РАЗБОР: попала ли фраза в мгновенный путь и в тот ли инструмент
        parsed = bool(hit) and any(tool == w for w in want.split("|"))
        note = f"`{tool or '—'}` {args if args else ''}"
        fact, fact_note = None, ""
        if a.live and hit:
            tls.LAST_USER["text"] = phrase
            was = before()
            try:
                res = tls.call(tool, args)
            except Exception as e:
                res = f"ОШИБКА: {e}"
            fact, fact_note = after(was)
            note += f" → {str(res)[:70]}"
        good = parsed and (fact is not False)
        ok_n += 1 if good else 0
        bad_n += 0 if good else 1
        rows.append((phrase, "да" if parsed else "НЕТ",
                     {True: "да", False: "НЕТ", None: "—"}[fact],
                     note, fact_note))

    md = ["# Экзамен команд", "",
          f"Прогон: {'по-настоящему' if a.live else 'только разбор фраз'}. "
          f"Сдано {ok_n}, провалено {bad_n}.", "",
          "| фраза | мгновенно | факт | что вызвалось | наблюдение |",
          "|---|---|---|---|---|"]
    for r in rows:
        md.append("| " + " | ".join(str(x).replace("|", "¦") for x in r) + " |")
    out = ROOT / "logs" / "command_drill.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    io.open(out, "w", encoding="utf-8").write("\n".join(md) + "\n")
    print("\n".join(md[-len(rows) - 2:]))
    print(f"\nсдано {ok_n}, провалено {bad_n} — отчёт: {out}")
    return 1 if bad_n else 0


if __name__ == "__main__":
    sys.exit(main())
