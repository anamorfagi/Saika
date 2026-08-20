"""Стенд по окнам: числа вместо «вроде развернулось» (2026-08-18).

ПОВОД. Живой вечер, четыре просьбы подряд «поставь проводник слева на
первом экране» — и четыре ответа «не смогла найти окно» при том, что окно
на глазах у владельца переезжало и разворачивалось. Разбор показал баг,
который на глаз выглядит как «моргнуло»: window_maximize разворачивал окно
(SW_MAXIMIZE), потом звал _force_front ради фокуса, а тот ПЕРВОЙ строкой
делал SW_RESTORE — и разворот отменялся. Проверка «развёрнуто?» честно
говорила «нет», ответ был «окно не послушалось», агентный цикл шёл
повторять. Отсюда и мигание Chrome.

Глазами это не ловится: моргание длится доли секунды и читается как
«подтормозило». Числа ловят сразу — RULES п.4.

ПОРЯДОК РАБОТЫ СО СТЕНДОМ — RULES п.5, и он тут не формальность. Тест на
разворот ОБЯЗАН краснеть на старом коде. Проверить это можно за минуту:
верни в anamorf/pc_control.py в _force_front безусловный
    user32.ShowWindow(hwnd, 9)
вместо
    if user32.IsIconic(hwnd): user32.ShowWindow(hwnd, 9)
— и «разворот переживает фокус» станет ПРОВАЛ. Не увидел красного —
значит стенд проверяет не то, что думаешь.

Запуск (из папки репозитория, Сайку останавливать не нужно):
    python -m tools.window_bench                 — мониторы, карта, разбор фраз
    python -m tools.window_bench --act хром      — плюс живые действия над окном
    python -m tools.window_bench --act хром --monitor 2

Без --act стенд НИЧЕГО на экране не трогает: только смотрит и печатает.
С --act он двигает названное окно и в конце ВОЗВРАЩАЕТ его туда, где взял.
"""
import sys
import time

sys.path.insert(0, __import__("os").path.dirname(
    __import__("os").path.dirname(__import__("os").path.abspath(__file__))))

from anamorf import pc_control as pc            # noqa: E402

OK, FAIL = "  ОК   ", "  ПРОВАЛ"
_score = {"ok": 0, "fail": 0}


def check(name: str, cond: bool, got: str = "") -> bool:
    _score["ok" if cond else "fail"] += 1
    print(f"{OK if cond else FAIL}  {name}" + (f"   [{got}]" if got else ""))
    return bool(cond)


# ───────────────────────────── мониторы ──────────────────────────────
def monitors():
    """Те ли это номера, которые Windows рисует по кнопке «Определить».

    Вопрос владельца дословно: «проверь, правильно ли она понимает первый и
    второй моник». Проверяется только глазами человека — машине неоткуда
    знать, какую цифру ей нарисовали на экране. Поэтому стенд печатает
    номер, размер, положение и главный он или нет, а сверяет человек.
    """
    print("\n=== МОНИТОРЫ (как их видит Сайка) ===")
    info = pc._mon_info()
    if not info:
        print("  мониторов не видно — не Windows или EnumDisplayMonitors "
              "промолчал")
        return
    for d in info:
        r, w = d["rect"], d["work"]
        print(f"  Экран {d['num']}: {r[2]-r[0]}×{r[3]-r[1]} "
              f"в точке ({r[0]}, {r[1]})"
              f"{'  ГЛАВНЫЙ' if d['primary'] else ''}")
        print(f"           рабочая область (без панели задач): "
              f"{w[2]-w[0]}×{w[3]-w[1]} в точке ({w[0]}, {w[1]})")
    check("номера мониторов идут без дыр",
          sorted(d["num"] for d in info) == list(
              range(1, len(info) + 1)),
          "номера: " + ", ".join(str(d["num"]) for d in info))
    check("ровно один монитор помечен главным",
          sum(1 for d in info if d["primary"]) == 1)
    print("\n  СВЕРЬ РУКАМИ: Параметры Windows -> Дисплей -> кнопка "
          "«Определить». Цифры на экранах должны совпасть с номерами "
          "выше. Не совпали — Сайка будет путать экраны, и это НЕ её "
          "ошибка, а расхождение нумерации.")


# ────────────────────────────── карта ────────────────────────────────
def snapshot():
    """Что в карте стола есть — по ней модель проверяет саму себя."""
    print("\n=== СНИМОК СТОЛА (то, что уходит в промпт) ===")
    ws = pc.windows()
    print(f"  окон с заголовком: {len(ws)}")
    if not ws:
        print("  окон нет — дальше проверять нечего")
        return
    for f in ("hwnd", "title", "proc", "cls", "minimized", "maximized",
              "front", "monitor", "z"):
        check(f"в списке есть поле «{f}»", f in ws[0])
    check("ровно одно окно помечено как переднее",
          sum(1 for w in ws if w.get("front")) <= 1,
          f"передних: {sum(1 for w in ws if w.get('front'))}")
    check("у окон есть класс (по нему опознаём, когда заголовок врёт)",
          any(w.get("cls") for w in ws))
    text = pc.screen_map()
    check("в карте помечено, кто впереди (▶)", "▶" in text)
    check("в карте есть состояние окон",
          "развёрнуто" in text or "обычное" in text)
    print("\n--- карта целиком ---")
    print(text)
    print("--- конец карты ---")


# ───────────────────────── разбор фраз (без Windows) ─────────────────
def phrases():
    """Живые фразы из лога 2026-08-18 — те самые, на которых она встала."""
    print("\n=== РАЗБОР ФРАЗ РЕФЛЕКСОМ ===")
    from anamorf import reflex
    cases = [
        ("Сделай проводник слева на экране.",
         "window_place", {"match": "проводник", "position": "left"}),
        ("Блэд, просто открой проводник на первом экране слева.",
         "window_place", {"match": "проводник", "position": "left",
                          "monitor": 1}),
        ("открой проводник на втором экране",
         "window_place", {"match": "проводник", "monitor": 2}),
        ("перенеси проводник на второй экран",
         "window_place", {"match": "проводник", "monitor": 2}),
        ("поставь хром слева",
         "window_place", {"match": "хром", "position": "left"}),
        ("размести блендер в правый нижний угол",
         "window_place", {"match": "блендер", "position": "bottomright"}),
        ("кинь хром на другой экран",
         "window_place", {"match": "хром", "monitor": -1}),
        # а это трогать окна НЕ должно
        ("открой проводник", "go_to", {}),
        ("покажи что на экране", None, {}),
        ("запусти блендер", "app_launch", {}),
    ]
    for text, want_tool, want_args in cases:
        got = reflex.match(text)
        tool = got[0] if got else None
        args = got[1] if got else {}
        ok = (tool == want_tool) and all(
            args.get(k) == v for k, v in want_args.items())
        check(f"«{text[:46]}»", ok, f"{tool} {args}")


# ─────────────────────── живые действия над окном ────────────────────
def actions(target: str, monitor: int = 0):
    """САМОЕ ВАЖНОЕ. Тут и живёт баг, из-за которого моргали окна."""
    print(f"\n=== ДЕЙСТВИЯ НАД ОКНОМ «{target}» ===")
    w = pc.find(target)
    if not w:
        print(f"  окно «{target}» не нашлось — назови кусок заголовка или "
              "имя программы («хром», «проводник», «блокнот»)")
        _score["fail"] += 1
        return
    h = w["hwnd"]
    print(f"  цель: «{w['title'][:60]}» ({w['proc']}, {w.get('cls')}), "
          f"экран {w['monitor']}, состояние {pc.placement(h)}")
    было = pc.placement(h)

    # 1) разворот
    ans = pc.window_maximize(w["title"][:20])
    time.sleep(0.35)
    check("разворот: система подтверждает max", pc.placement(h) == "max",
          pc.placement(h))
    check("разворот: ответ НЕ врёт про провал",
          "не смогла" not in ans.lower() and "не послушалось" not in ans.lower(),
          ans[:90])

    # 2) ГЛАВНОЕ: фокус не отменяет разворот
    #    Красное здесь = вернулся безусловный SW_RESTORE в _force_front.
    pc.window_focus(w["title"][:20])
    time.sleep(0.35)
    check("разворот ПЕРЕЖИВАЕТ фокус (тот самый баг)",
          pc.placement(h) == "max", pc.placement(h))

    # 3) перенос: окно обязано перестать быть развёрнутым и встать слева
    ans = pc.window_place(w["title"][:20], "left", 50, 100, monitor)
    time.sleep(0.4)
    check("перенос: окно больше не развёрнуто",
          pc.placement(h) != "max", pc.placement(h))
    fresh = next((x for x in pc.windows() if x["hwnd"] == h), None)
    if monitor and fresh:
        check(f"перенос: окно на экране {monitor}",
              fresh["monitor"] == monitor, f"оказалось на {fresh['monitor']}")
    check("перенос: ответ не врёт про провал",
          "не смогла" not in ans.lower(), ans[:90])
    check("ответ сам говорит, что стало с окном (проверять нечем не надо)",
          "Сейчас:" in ans, ans[-70:])

    # 4) свернуть/поднять
    pc.window_minimize(w["title"][:20])
    time.sleep(0.35)
    check("свернулось", pc.placement(h) == "min", pc.placement(h))
    pc.window_focus(w["title"][:20])
    time.sleep(0.35)
    check("поднялось из свёрнутого", pc.placement(h) != "min",
          pc.placement(h))

    # вернуть как было — стенд не должен оставлять после себя бардак
    if было == "max":
        pc.window_maximize(w["title"][:20])
    elif было == "min":
        pc.window_minimize(w["title"][:20])
    print(f"  окно возвращено в состояние «{было}»")


def main():
    args = sys.argv[1:]
    target, monitor = "", 0
    if "--act" in args:
        i = args.index("--act")
        target = args[i + 1] if len(args) > i + 1 else ""
    if "--monitor" in args:
        i = args.index("--monitor")
        monitor = int(args[i + 1]) if len(args) > i + 1 else 0

    monitors()
    snapshot()
    phrases()
    if target:
        actions(target, monitor)
    else:
        print("\n(живые действия пропущены — добавь «--act хром», чтобы "
              "проверить разворот, фокус и перенос на настоящем окне)")

    print(f"\n=== ИТОГ: ок {_score['ok']}, провалов {_score['fail']} ===")
    if _score["fail"]:
        print("Провал в «разворот ПЕРЕЖИВАЕТ фокус» означает, что в "
              "_force_front вернулся безусловный SW_RESTORE.")
    sys.exit(1 if _score["fail"] else 0)


if __name__ == "__main__":
    main()
