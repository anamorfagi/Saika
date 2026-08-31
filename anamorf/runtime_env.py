"""Где мы живём: рабочая копия автора или собранное приложение.

Один модуль отвечает на три вопроса, от которых зависит половина поведения
при запуске:

    DEV        — исходники разработчика или билд у человека?
    PY         — каким интерпретатором запускать дочерние процессы?
    ensure()   — как добыть недостающий компонент?

Зачем это отдельно, а не по месту в каждом модуле.

1. В собранном приложении ``sys.executable`` — это ANAMORF.exe, а не
   python.exe. Любой subprocess по ``sys.executable`` запустит второй
   экземпляр приложения вместо воркера. Тихо, без ошибки, с двумя серверами
   на одном порту. Поэтому интерпретатор для детей спрашивают ЗДЕСЬ.

2. В собранном приложении нет pip. Совсем. Три модуля раньше звали
   ``sys.executable -m pip install`` прямо во время работы — у клиента эта
   ветка умирала молча. И даже там, где pip есть, он опасен: он тянет
   зависимости и ломает уже работающее окружение. В этом проекте так и было:
   T-one откатывал numpy до 1.x, за ним падали scipy и librosa, и ради
   этого родился fix_venv.bat с зашитыми версиями.

Поэтому у клиента недостающее приезжает НЕ через pip, а готовым запечатанным
архивом: скачали по манифесту, сверили sha256, распаковали, добавили в путь.
Ровно тем же способом, каким setup/install_llamacpp.py давно тянет
llama-server.exe с GitHub Releases. У разработчика при этом всё как было — pip.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

log = logging.getLogger("runtime")

ROOT = Path(__file__).resolve().parent.parent


# Корень данных — на уровень выше кода, когда мы внутри собранного
# приложения (app\ по соседству с runtime\). Логика повторяет
# anamorf/config.py намеренно: эти три модуля обязаны работать до того,
# как поднимется конфиг, и тянуть его ради одной строки — значит
# заводить порядок импортов там, где он не нужен.
DATA_ROOT = (ROOT.parent
             if ROOT.name == "app" and (ROOT.parent / "runtime").is_dir()
             else ROOT)

# ---------------------------------------------------------------- где мы

def _is_dev() -> bool:
    """Рабочая копия — если рядом есть .git и нас не заморозили.

    Переменная окружения важнее: ей выключают dev-режим на собственной
    машине, чтобы посмотреть, каким приложение будет у человека.
    """
    env = os.environ.get("ANAMORF_DEV") or os.environ.get("SAIKA_DEV")
    if env is not None:
        return env.strip() not in ("", "0", "false", "no")
    if getattr(sys, "frozen", False):
        return False
    return (ROOT / ".git").exists()


DEV: bool = _is_dev()
FROZEN: bool = bool(getattr(sys, "frozen", False))


# ------------------------------------------------- интерпретатор для детей

def _find_python() -> str:
    """Чем запускать дочерние процессы.

    В рабочей копии это тот же интерпретатор, что и у нас. В собранном
    приложении — python.exe из runtime\\, потому что sys.executable там
    указывает на само приложение.
    """
    if not FROZEN:
        return sys.executable
    exe = "python.exe" if os.name == "nt" else "python"
    for rel in ("runtime", "../runtime", "python"):
        p = ROOT / rel / exe
        if p.exists():
            return str(p)
    # Не нашли — честно говорим в лог. Молча подставлять sys.executable
    # нельзя: получим второй экземпляр приложения вместо воркера.
    log.error("не найден интерпретатор в runtime\\ — дочерние процессы "
              "запускаться не будут")
    return ""


PY: str = _find_python()


def can_spawn() -> bool:
    """Можно ли вообще поднимать дочерние процессы Python."""
    return bool(PY)


def spawn(args: list[str], **kw) -> subprocess.Popen | None:
    """Запустить дочерний Python. args — без интерпретатора в начале."""
    if not can_spawn():
        return None
    return subprocess.Popen([PY, *args], **kw)


# ------------------------------------------------------- добыть компонент

def _packs_manifest() -> dict:
    """Список докачиваемых блоков: id → {url, sha256, размер}.

    Файл кладётся в сборку и обновляется вместе с ней. Нет файла —
    значит, эта сборка ничего не докачивает.
    """
    for name in ("packs.json", "app/packs.json"):
        p = ROOT / name
        if p.exists():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except Exception as e:
                log.warning("packs.json не читается: %s", e)
    return {}


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _download_pack(feature_id: str) -> tuple[bool, str]:
    """Скачать и распаковать готовый блок. Без pip и без компилятора."""
    entry = _packs_manifest().get(feature_id)
    if not entry:
        return False, ("этот компонент не входит в сборку — "
                       "его можно добавить только в другой версии")

    dest = ROOT / "runtime" / "packs" / feature_id
    if dest.exists():
        _add_path(dest)
        return True, "компонент уже на месте"

    tmp = DATA_ROOT / "data" / "downloads"
    tmp.mkdir(parents=True, exist_ok=True)
    zip_path = tmp / f"{feature_id}.zip"

    try:
        from urllib.request import urlopen
        log.info("качаю компонент %s…", feature_id)
        with urlopen(entry["url"], timeout=60) as r, open(zip_path, "wb") as f:
            shutil.copyfileobj(r, f)
    except Exception as e:
        return False, f"не смогла скачать компонент: {e}"

    want = entry.get("sha256")
    if want and _sha256(zip_path) != want:
        # Битую закачку не распаковываем: лучше честная ошибка, чем
        # наполовину распакованный пакет, который потом ищи-свищи.
        zip_path.unlink(missing_ok=True)
        return False, "файл скачался повреждённым — попробуй ещё раз"

    try:
        dest.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zip_path) as z:
            z.extractall(dest)
    except Exception as e:
        return False, f"не смогла распаковать компонент: {e}"
    finally:
        zip_path.unlink(missing_ok=True)

    _add_path(dest)
    return True, "компонент установлен"


def _add_path(dest: Path) -> None:
    """Положить распакованный блок в пути импорта."""
    for cand in (dest, dest / "site-packages", dest / "Lib" / "site-packages"):
        s = str(cand)
        if cand.exists() and s not in sys.path:
            sys.path.insert(0, s)


def pip_install(packages: list[str], timeout: int = 900) -> tuple[bool, str]:
    """Поставить пакеты в текущее окружение.

    БЫЛО: «у клиента pip нет и быть не должно». Мысль верная — клиенту
    незачем собирать окружение, ему привозят готовые блоки. Но 23.08.2026
    выяснилось, что блоков этих нет: манифест пуст, и на просьбу открыть
    окно с моделью система честно отвечала «компонент пока не выложен».
    То есть возможность была закрыта дважды — и штатного пути нет, и
    запасной запрещён.

    Теперь запрет мягче: если pip в сборке ЕСТЬ, ставим им. Нет — говорим
    как раньше. Это не «pip у клиента по умолчанию», это «не отказывать,
    когда средство под рукой».
    """
    if not DEV:
        try:
            import pip                                   # noqa: F401
        except Exception:
            return False, ("в этой сборке нет pip, а готовый блок ещё не "
                           "выложен — поставить нечем")
    if not can_spawn():
        return False, "нет интерпретатора для установки"
    try:
        r = subprocess.run(
            [PY, "-m", "pip", "install", "--disable-pip-version-check",
             *packages, "--timeout", "120", "--retries", "10"],
            capture_output=True, text=True, timeout=timeout)
        if r.returncode == 0:
            return True, "поставила " + ", ".join(packages)
        tail = (r.stderr or r.stdout or "")[-200:]
        return False, "pip не справился: " + tail
    except Exception as e:
        return False, f"установка сорвалась: {e}"


def ensure(feature_id: str, packages: list[str] | None = None,
           check: str | None = None) -> tuple[bool, str]:
    """Добыть всё, что нужно фиче. Один вызов на оба режима.

    feature_id — как фича зовётся в реестре;
    packages   — что ставить pip'ом в рабочей копии;
    check      — модуль, по наличию которого понятно, что всё уже есть.
    """
    if check:
        try:
            __import__(check)
            return True, ""
        except ImportError:
            pass
    if DEV:
        return pip_install(packages or [])
    # Скачиванием и распаковкой занимается packs — здесь только развилка
    # «рабочая копия или билд», чтобы не разъезжались две реализации.
    from anamorf import packs
    ok, why = packs.install(feature_id)
    if ok:
        return ok, why
    # БЛОКА НЕТ — ПРОБУЕМ САМИ (2026-08-23). «Компонент пока не выложен»
    # это не ответ человеку, который просит окно с моделью прямо сейчас.
    # Если пакеты названы и pip под рукой — ставим ими, и пусть блок
    # приедет когда-нибудь потом.
    if packages:
        ok2, why2 = pip_install(packages)
        if ok2:
            return True, why2
        return False, f"{why}; и pip не помог: {why2}"
    return ok, why


def describe() -> dict:
    """Для панели диагностики: где мы и чем запускаем детей."""
    return {"dev": DEV, "frozen": FROZEN, "python": PY, "root": str(ROOT),
            "packs": sorted(_packs_manifest().keys())}
