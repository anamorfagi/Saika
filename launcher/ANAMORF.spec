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

console=False — окно консоли человеку не нужно. Всё, что лаунчер хочет
сказать, он пишет в data\\logs\\launcher.log.
"""

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=['webview'],
    hookspath=[],
    excludes=['torch', 'numpy', 'PIL', 'cv2', 'transformers', 'tkinter'],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [],
    name='ANAMORF',
    console=False,
    icon=None,               # положить сюда путь к .ico, когда будет
    upx=False,               # UPX = почти гарантированный ложный вирус
    disable_windowed_traceback=False,
    version=None,
)
