# -*- mode: python ; coding: utf-8 -*-
"""Сборка ANAMORF.exe — только лаунчера, не всего проекта.

    pyinstaller launcher/ANAMORF.spec --distpath build --workpath build/_pyi

Замораживается ровно один файл на две сотни строк, из зависимостей — одна
библиотека окна. Ни torch, ни comtypes, ни pywinauto сюда не попадают: они
живут обычными файлами в runtime\\, и PyInstaller про них ничего не знает.

Так сделано не из лени. Проекты такого размера с CUDA и COM в onefile
собираются днями, ломаются от каждого обновления зависимости и стабильно
ловят ложные срабатывания антивирусов из-за самораспаковки. Полтора
мегабайта чистого Python ломаться нечему.

────────────────────────────────────────────────────────────────────────
ПОЧЕМУ НЕ ONEFILE

Onefile при каждом запуске распаковывает себя в %TEMP%\\_MEIxxxxx, а при
выходе пытается эту папку удалить. Удалить её он может только если ни один
процесс не держит оттуда ни одного файла. А держат: WebView2 поднимает
свои процессы браузера и подгружает DLL, и живут они на доли секунды
дольше, чем наш питон. Отсюда «Failed to remove temporary directory» —
безобидное по сути, но человек видит жёлтый треугольник при каждом
закрытии программы и делает единственный разумный вывод: сломалось.

Обойти это изнутри нельзя: удаление делает не наш код, а бутлоадер, уже
после того как интерпретатор мёртв. Поэтому убран сам механизм. Onedir
ничего никуда не распаковывает — он просто лежит на диске распакованным.
Побочно: старт становится быстрее (нет распаковки 18 МБ на каждый запуск)
и антивирусы перестают нервничать, потому что самораспаковки больше нет.

contents_directory прячет требуху в _launcher\\, чтобы рядом с ANAMORF.exe
в корне билда не выросла свалка из сорока DLL. Требует PyInstaller 6+.
────────────────────────────────────────────────────────────────────────

console=False — окно консоли человеку не нужно. Всё, что лаунчер хочет
сказать, он пишет в data\\logs\\launcher.log.
"""

import os
from PyInstaller.utils.hooks import collect_all

ICON = os.path.join(SPECPATH, 'ANAMORF.ico')   # SPECPATH даёт PyInstaller

# ── проверка, которой раньше не было и зря ────────────────────────────
# hiddenimports — это ПОЖЕЛАНИЕ. Если модуля нет в питоне, которым
# собирают, PyInstaller пишет строчку в warn-*.txt и спокойно продолжает.
# Ровно так и вышло: pywebview не был установлен, exe собрался без окна,
# лаунчер молча падал в браузерную вкладку, а выглядело это как «билд
# запускается и сразу умирает». Пусть лучше сборка честно откажется.
try:
    import webview                                   # noqa: F401
except Exception as _e:
    raise SystemExit(
        "\n  pywebview не установлен в этом питоне — окна у сборки не будет.\n"
        "  Поставь и собери заново:\n"
        "      pip install pywebview pythonnet\n"
        f"  ({type(_e).__name__}: {_e})\n")

# Окно тащит за собой .NET-обвязку и свои данные; collect_all забирает
# всё разом, иначе backend edgechromium не находит половину себя.
WV_DATAS, WV_BINS, WV_HIDDEN = collect_all('webview')

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=WV_BINS,
    datas=WV_DATAS,
    hiddenimports=['webview'] + WV_HIDDEN,
    hookspath=[],
    excludes=['torch', 'numpy', 'PIL', 'cv2', 'transformers', 'tkinter'],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,          # ← onedir: двоичное уходит в COLLECT
    name='ANAMORF',
    console=False,
    icon=ICON,
    upx=False,               # UPX = почти гарантированный ложный вирус
    disable_windowed_traceback=False,
    contents_directory='_launcher',
    version=None,
)

coll = COLLECT(
    exe, a.binaries, a.datas,
    strip=False, upx=False,
    # Имя папки нарочно не «ANAMORF»: это НЕ приложение, а полуфабрикат
    # лаунчера. Папка с таким же именем, как у продукта, но без app\ и
    # runtime\ — ловушка: exe в ней запускается и честно ругается, что
    # установка повреждена. Подчёркивание в начале ставит её рядом с
    # _pyi и говорит «сюда не ходи».
    name='_launcher_build',
)
