"""Докачиваемые блоки: тяжёлое приезжает готовым, а не собирается у человека.

Не всё влезает в установщик. Видимый браузер тянет за собой Chromium, окно
аватара — половину Qt, отдельные движки — собственные окружения на гигабайты.
Класть это всем подряд неуважение к диску и к трафику; ставить у человека
через pip — рулетка.

Почему именно рулетка, а не «ну поставится как-нибудь»:

  * у него нет компилятора C++, и любой пакет без готового колеса под его
    версию Python просто не соберётся;
  * pip тянет зависимости и ломает УЖЕ РАБОТАЮЩЕЕ окружение. В этом проекте
    так и было: T-one при установке откатывал numpy до 1.x, за ним падали
    scipy и librosa, и ради этого родился fix_venv.bat с зашитыми версиями;
  * при кривой сети pip падает десятью разными способами, а архив просто
    докачивается;
  * и главное: у всех получается одна и та же битовая копия, а не «что pip
    решил сегодня».

Поэтому блок собирается ОДИН РАЗ на машине автора, кладётся в релиз рядом с
установщиком и приезжает к человеку целиком, с проверкой контрольной суммы.

Собирается блок командой `python tools/make_pack.py <фича>`.
"""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
import sys
import zipfile
from pathlib import Path

log = logging.getLogger("packs")

ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = ROOT / "packs.json"          # что вообще бывает и откуда качать
PACKS_DIR = ROOT / "runtime" / "packs"       # куда распаковано
STATE_PATH = ROOT / "data" / "packs.json"    # что стоит на этой машине

_activated: set[str] = set()


# ------------------------------------------------------------------ опись

def manifest() -> dict:
    try:
        return json.loads(MANIFEST_PATH.read_text(encoding="utf-8")).get("packs", {})
    except Exception:
        return {}


def _features() -> dict:
    """Блоки описаны в общем реестре — отдельного списка заводить не будем."""
    try:
        d = json.loads((ROOT / "features.json").read_text(encoding="utf-8"))
        return {f["id"]: f for g in d["groups"] for f in g["features"]}
    except Exception:
        return {}


def _state() -> dict:
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_state(st: dict) -> None:
    try:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATE_PATH.write_text(json.dumps(st, ensure_ascii=False, indent=2),
                              encoding="utf-8")
    except Exception as e:
        log.warning("не смогла записать список блоков: %s", e)


def catalog() -> list[dict]:
    """Все блоки с их состоянием — для панели «Дополнения» в интерфейсе."""
    feats, man, st = _features(), manifest(), _state()
    out = []
    for fid, f in feats.items():
        if not f.get("pack"):
            continue
        entry = man.get(fid, {})
        out.append({
            "id": fid,
            "title": f.get("title", fid),
            "blurb": f.get("blurb", ""),
            "mb": f.get("mb", 0),
            "level": f.get("level", "stable"),
            "installed": is_installed(fid),
            "version": st.get(fid, {}).get("version", ""),
            # Блок бывает описан в реестре, но ещё не собран и не выложен.
            # Честно говорим «пока недоступен» вместо молчаливой ошибки.
            "available": bool(entry.get("url")),
            "needs": f.get("needs", []),
            "notice": f.get("notice", ""),
        })
    return sorted(out, key=lambda x: (not x["installed"], x["title"]))


# ------------------------------------------------------------- состояние

def path_of(feature_id: str) -> Path:
    return PACKS_DIR / feature_id


def is_installed(feature_id: str) -> bool:
    p = path_of(feature_id)
    return p.is_dir() and any(p.iterdir())


def activate(feature_id: str) -> bool:
    """Положить установленный блок в пути импорта."""
    if feature_id in _activated:
        return True
    p = path_of(feature_id)
    if not p.is_dir():
        return False
    for cand in (p, p / "site-packages", p / "Lib" / "site-packages"):
        s = str(cand)
        if cand.is_dir() and s not in sys.path:
            sys.path.insert(0, s)
    _activated.add(feature_id)
    return True


def activate_all() -> int:
    """Подключить всё установленное. Зовётся при старте, до любых импортов.

    Если этого не сделать, установленный блок будет лежать на диске, а
    `import playwright` всё равно не найдёт его — и человек увидит «поставь
    компонент» сразу после того, как его поставил.
    """
    if not PACKS_DIR.is_dir():
        return 0
    n = 0
    for p in sorted(PACKS_DIR.iterdir()):
        if p.is_dir() and activate(p.name):
            n += 1
    if n:
        log.info("подключено дополнительных блоков: %s", n)
    return n


# ------------------------------------------------------------- установка

def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def install(feature_id: str, on_progress=None) -> tuple[bool, str]:
    """Скачать и распаковать блок.

    on_progress(готово_мб, всего_мб) — чтобы кнопка в интерфейсе не была
    мёртвой полторы минуты. Установка блока это гигабайты; молчащая кнопка
    здесь читается как «зависло».
    """
    if is_installed(feature_id):
        activate(feature_id)
        return True, "уже установлен"

    entry = manifest().get(feature_id)
    if not entry or not entry.get("url"):
        return False, ("этот компонент пока не выложен — он появится "
                       "в одном из следующих обновлений")

    tmp_dir = ROOT / "data" / "downloads"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    zip_path = tmp_dir / f"{feature_id}.zip"

    try:
        from urllib.request import urlopen
        log.info("качаю блок %s…", feature_id)
        with urlopen(entry["url"], timeout=60) as r:
            total = int(r.headers.get("Content-Length") or 0)
            done = 0
            with open(zip_path, "wb") as f:
                while True:
                    chunk = r.read(1 << 20)
                    if not chunk:
                        break
                    f.write(chunk)
                    done += len(chunk)
                    if on_progress:
                        try:
                            on_progress(done / 1e6, total / 1e6)
                        except Exception:
                            pass
    except Exception as e:
        zip_path.unlink(missing_ok=True)
        return False, f"не смогла скачать: {e}"

    want = entry.get("sha256")
    if want and _sha256(zip_path) != want:
        # Битую закачку не распаковываем. Наполовину распакованный блок
        # хуже отсутствующего: он выглядит установленным.
        zip_path.unlink(missing_ok=True)
        return False, "файл скачался повреждённым — попробуй ещё раз"

    dest = path_of(feature_id)
    try:
        dest.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zip_path) as z:
            z.extractall(dest)
    except Exception as e:
        shutil.rmtree(dest, ignore_errors=True)
        return False, f"не смогла распаковать: {e}"
    finally:
        zip_path.unlink(missing_ok=True)

    st = _state()
    st[feature_id] = {"version": entry.get("version", ""),
                      "sha256": want or "", "mb": entry.get("mb", 0)}
    _save_state(st)
    activate(feature_id)
    log.info("блок %s установлен", feature_id)
    return True, "компонент установлен"


def remove(feature_id: str) -> tuple[bool, str]:
    """Убрать блок с диска — вернуть место, если фича не пригодилась."""
    dest = path_of(feature_id)
    if not dest.is_dir():
        return False, "этого компонента и так нет"
    try:
        shutil.rmtree(dest)
    except Exception as e:
        return False, f"не смогла удалить: {e}"
    st = _state()
    st.pop(feature_id, None)
    _save_state(st)
    _activated.discard(feature_id)
    return True, "компонент удалён (перезапусти, чтобы освободить память)"


def ensure(feature_id: str, packages=None, check: str | None = None
           ) -> tuple[bool, str]:
    """Есть ли всё нужное фиче. Нет — добыть тем способом, который уместен.

    В рабочей копии автора это pip, как было всегда. В собранном
    приложении — готовый блок. Вызывающему коду разница не видна, и это
    важно: иначе каждый модуль решал бы сам, и каждый по-своему.
    """
    activate_all()
    if check:
        try:
            __import__(check)
            return True, ""
        except ImportError:
            pass
    from anamorf import runtime_env
    if runtime_env.DEV:
        return runtime_env.pip_install(list(packages or []))
    return install(feature_id)
