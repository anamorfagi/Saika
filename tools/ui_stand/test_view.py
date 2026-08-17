"""Стенд вида аватара: переживает ли вид изменение размера окна.

    python -m tools.ui_stand.test_view          (нужен playwright)

ПОВОД (2026-08-17). Владелец: «шифт+колесико — передвижение вдоль окна
ломается при масштабировании окна, а остальное нет».

Причина оказалась в saikaFit(): там стояло присваивание ЦЕЛОГО объекта
`view = {x:0, y:0, z:0, zoom: view.zoom || 1}`, а функция висит на resize
окна на столе. Присваивание молча выбрасывало все поля, которых нет в
скобках: сдвиг (ox/oy/oz), облёт (az/el), поворот (rx/ry/rz).

И «ломается» — точное слово, а не «сбрасывается». После подмены объекта
`view.ox` не просто ноль, его НЕТ, и следующий сдвиг считает
`undefined - число` = NaN. Смещение умирает насовсем, до сброса вида.
Облёт при этом выживает, потому что каждый раз пересевается от
`view.az || 0` — отсюда и «остальное не ломается».

ПОЧЕМУ ЭТО НУЖНО ПРОВЕРЯТЬ МАШИНОЙ, А НЕ ГЛАЗОМ. Из пяти сброшенных полей
глазом заметно ровно одно. Облёт сбрасывается в 0 — это вид спереди, он от
нормального неотличим. Поворот модели трогают редко. Зум уцелевает явно.
Поэтому смотрим ЧИСЛА в window.saikaView() до и после resize.

ВАЖНО: баг живёт только в ОКНЕ НА СТОЛЕ (?desk=1) — в панели браузера
resize не зовёт saikaFit вообще. Стенд без ?desk=1 показывал зелёное на
заведомо сломанной версии; это отдельный урок про то, как легко получить
бесполезный тест.
"""
import sys
import threading

URL = "http://127.0.0.1:8899/avatar?desk=1"
OK, BAD = "  ✓", "  ✗"
KEEP = ["ox", "oy", "oz", "x", "y", "z", "az", "el", "rx", "zoom"]


def _view(page):
    return page.evaluate("() => JSON.parse(JSON.stringify(window.saikaView()||{}))")


def _pan(page, x0, y0, x1, y1):
    """Сдвиг вида: Shift + зажатое колесо + движение мышью."""
    page.mouse.move(x0, y0)
    page.mouse.down(button="middle")
    page.keyboard.down("Shift")
    page.mouse.move(x1, y1, steps=8)
    page.keyboard.up("Shift")
    page.mouse.up(button="middle")
    page.wait_for_timeout(120)


def run():
    from playwright.sync_api import sync_playwright
    fails = 0
    with sync_playwright() as pw:
        br = pw.chromium.launch(args=["--use-gl=swiftshader",
                                      "--enable-unsafe-swiftshader"])
        page = br.new_page(viewport={"width": 900, "height": 700})
        errs = []
        page.on("pageerror", lambda e: errs.append(str(e)))
        page.goto(URL, wait_until="load")
        page.wait_for_function(
            "() => window.saikaView && window.saikaView().zoom != null",
            timeout=90000)
        page.wait_for_timeout(800)

        if errs:
            print(f"{BAD} ошибки на странице: {errs[:3]}")
            fails += 1
        else:
            print(f"{OK} страница загрузилась, модель на месте")

        page.evaluate("() => window.saikaView({ox:0, oy:0, oz:0})")
        _pan(page, 450, 350, 600, 300)
        v = _view(page)
        moved = any(abs(v.get(k) or 0) > 1e-6 for k in ("ox", "oy", "oz"))
        print(f"{OK if moved else BAD} сдвиг работает: "
              f"ox={v.get('ox')!r} oy={v.get('oy')!r}")
        fails += not moved

        # ставим облёт и поворот — тоже должны пережить
        page.evaluate("() => window.saikaView({az:30, el:12, rx:5})")
        before = _view(page)

        page.set_viewport_size({"width": 520, "height": 900})   # <- вот здесь ломалось
        page.wait_for_timeout(400)
        after = _view(page)

        print("\n   поле    до resize -> после")
        lost = []
        for k in KEEP:
            a, b = before.get(k), after.get(k)
            same = (a or 0) == (b or 0)
            if not same:
                lost.append(k)
            print(f"   {'  ' if same else '✗ '}{k:5} {a!r:>22} -> {b!r}")
        print()
        if lost:
            print(f"{BAD} вид сброшен по полям: {', '.join(lost)}")
            fails += 1
        else:
            print(f"{OK} вид пережил изменение размера окна целиком")

        ox0 = after.get("ox") or 0
        _pan(page, 260, 450, 360, 450)
        ox1 = _view(page).get("ox") or 0
        works = abs(ox1 - ox0) > 1e-6
        print(f"{OK if works else BAD} сдвиг жив ПОСЛЕ resize "
              f"(ox {ox0:.4f} -> {ox1:.4f})")
        fails += not works
        br.close()
    return fails


if __name__ == "__main__":
    from tools.ui_stand.stub_server import serve
    srv = serve(8899)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        n = run()
    except ImportError:
        print("нужен playwright:  pip install playwright && playwright install chromium")
        sys.exit(2)
    finally:
        srv.shutdown()
    print("\nПРОВАЛОВ:", n)
    sys.exit(1 if n else 0)
