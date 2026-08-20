"""ЧЁРНЫЙ ЯЩИК: что делали в момент нативного обвала (2026-08-14).

ПОВОД. Процесс падает с -1073741819 (access violation). Такой обвал
питон НЕ ЛОВИТ: ни try, ни finally, ни except, ни logging — интерпретатор
умирает внутри чужой C-библиотеки. В логе остаётся последняя строчка,
которую успел сбросить на диск логгер, а она почти всегда не про то: у
владельца это раз за разом «Черновик распознавания: Vosk поднят», и по
ней видно только, что смерть случилась ГДЕ-ТО ПОСЛЕ.

Три перезапуска подряд я чинил по этой строчке разные вещи — гонку
загрузок, CUDA-графы — и каждый раз крах переезжал на новое место.
Хватит. Ставим метки на живые участки: перед опасным делом пишем на диск
«я тут», после — «вышел». Файл пережил обвал — значит умерли ровно там.

ЧЕМ ЭТО ОТЛИЧАЕТСЯ ОТ ЛОГА. Лог буферизуется и теряет хвост при
мгновенной смерти. Здесь один короткий файл, открытый-записанный-закрытый
на каждой метке, плюс flush. Дорого? Микросекунды, и только на участках,
которые мы сами назвали опасными.
"""
from __future__ import annotations

import os
import time

from anamorf.config import ROOT

PATH = ROOT / "data" / "last_stage.txt"
_ON = os.environ.get("SAIKA_STAGE", "1") != "0"


def mark(name: str):
    """Мы ВОШЛИ в опасный участок."""
    if not _ON:
        return
    try:
        PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(PATH, "w", encoding="utf-8") as f:
            f.write(f"{name}\t{time.strftime('%H:%M:%S')}\t{os.getpid()}")
            f.flush()
            os.fsync(f.fileno())
    except Exception:
        pass


def clear():
    """Вышли живыми."""
    if not _ON:
        return
    try:
        PATH.unlink(missing_ok=True)
    except Exception:
        pass


class step:
    """with stage.step("слух: vosk"): ..."""

    def __init__(self, name):
        self.name = name

    def __enter__(self):
        mark(self.name)
        return self

    def __exit__(self, *a):
        clear()
        return False


def crashed_at() -> str:
    """Где умер прошлый запуск. Пусто — вышел нормально."""
    try:
        if not PATH.exists():
            return ""
        txt = PATH.read_text(encoding="utf-8").strip()
        PATH.unlink(missing_ok=True)
        return txt
    except Exception:
        return ""
