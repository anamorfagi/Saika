"""ИСПОЛНИТЕЛЬ ПОЧИНОК: не рассказать, а сделать и проверить (2026-08-22).

До этого файла у Сайки была только ДИАГНОСТИКА: `diagnostics.classify()`
называл причину и код лечения (`redownload|pagefile|switch|cpu|wait|
download|absent`), `baymax.py` пересказывал это человеку, `repairs.py`
помнил, что уже пробовали. Лечить было некому — код лечения ехал в UI
строкой и там умирал.

ГЛАВНОЕ ПРАВИЛО ЗДЕСЬ — НЕ ВРАТЬ (этап 1 плана билда). Ни один шаг не
имеет права сказать «починила», пока результат не проверен ЗАГРУЗКОЙ:
после любого действия мы пробуем поднять движок и смотрим `is_loaded()`.
Поэтому наружу уезжает не «ок», а факт: что сделали, что стало, и если не
вышло — почему именно.

ВТОРОЕ ПРАВИЛО — НЕ КРУТИТЬСЯ ПО КРУГУ. Одна попытка на одно действие,
никаких «а вдруг со второго раза». Что не поддалось — уходит человеку
честной строкой, а не новым кругом ожидания.

ТРЕТЬЕ — ПОМНИТЬ. Каждая починка пишется в журнал `repairs.py`: на
следующем здоровом старте она пометится «помогло», на падении — «не
помогло», и Беймакс больше не полезет тем же путём.
"""
from __future__ import annotations

import hashlib
import logging
import shutil
import subprocess
import threading
import time
from pathlib import Path

from anamorf.config import CFG, ROOT, DATA_ROOT

log = logging.getLogger("saika.repair")

# кто сейчас чинится — чтобы два клика по «Починить» не полезли вдвоём в
# одну и ту же модель (загрузка движка не переживает параллельного входа)
_BUSY: dict[str, float] = {}
_BUSY_LOCK = threading.Lock()

# лёгкие движки голоса: процессор, видеопамять не занимают. Порядок = кого
# пробовать первым. Тот же список, что в triage.py, — намеренно продублирован
# (тянуть модуль ради константы значит поднимать голос при первом же вызове).
_LIGHT_VOICES = ("silero", "piper", "edge")

GIGAAM_CDN = "https://cdn.chatwm.opensmodel.sberdevices.ru/GigaAM"
# md5 из паспорта пакета gigaam: битую закачку ловим сами, а не движком
GIGAAM_MD5 = {"v3_e2e_rnnt": "2730de7545ac43ad256485a462b0a27a"}


# ───────────────────────────── помощники ─────────────────────────────
def _mgr():
    """Менеджеры слуха и голоса живут в main — импорт поздний, иначе цикл."""
    from anamorf.main import stt, tts
    return stt, tts


def _split(component: str) -> tuple[str, str]:
    c = (component or "").strip()
    if "." in c:
        kind, name = c.split(".", 1)
        return kind, name
    return c, ""


def diag_for(component: str) -> dict | None:
    """Последний разбор ошибки этого модуля, как его видит менеджер."""
    kind, name = _split(component)
    stt, tts = _mgr()
    try:
        if kind == "stt":
            return (stt.last_diag or {}).get(name)
        if kind == "tts":
            return (tts.last_diag or {}).get(name)
    except Exception:
        pass
    return None


def _try_load(kind: str, name: str) -> tuple[bool, str]:
    """ЕДИНСТВЕННЫЙ источник правды о результате: поднялся или нет."""
    stt, tts = _mgr()
    try:
        if kind == "stt":
            stt.load_engine(name)
            eng = stt.instances.get(name)
            ok = bool(eng and eng.is_loaded())
            return ok, "" if ok else "движок не отдал is_loaded()"
        if kind == "tts":
            tts.load_engine(name, by_owner=True)
            eng = tts.engines.get(name)
            ld = eng.is_loaded() if eng else False
            # у онлайн-движка грузить нечего — is_loaded() отдаёт None,
            # и это «готов», а не «не поднялся»
            ok = (ld is None) or bool(ld)
            return ok, "" if ok else "движок не отдал is_loaded()"
    except Exception as e:
        return False, str(e)
    return False, f"не знаю, как поднимать «{kind}»"


def _vram() -> dict:
    try:
        from anamorf.guard import _read_gpu
        return _read_gpu() or {}
    except Exception:
        return {}


def _free_vram(keep_kind: str = "", keep_name: str = "") -> list[str]:
    """Снять с видеокарты всё, что не нужно прямо сейчас. Порядок тот же,
    что у ступеней разгрузки: сперва лишние модели, потом тяжёлый голос."""
    freed = []
    stt, tts = _mgr()
    try:
        from anamorf.llm import manager as llm
        failed = llm.unload_others(str(CFG.get("llm.backend", "")),
                                   str(CFG.get("llm.model", "")))
        freed.append("лишние LLM" + (f" (кроме {failed})" if failed else ""))
    except Exception as e:
        log.debug("лишние LLM не выгрузились: %s", e)
    # тяжёлый голос — самый жирный необязательный кусок
    for n in list(getattr(tts, "engines", {}) or {}):
        if keep_kind == "tts" and n == keep_name:
            continue
        if n in _LIGHT_VOICES or n in ("off", "none"):
            continue
        try:
            if tts.engines[n].is_loaded():
                tts.unload_engine(n)
                freed.append("голос " + n)
        except Exception:
            pass
    # чужие движки слуха (два слуха в памяти держать незачем)
    for n in list(getattr(stt, "instances", {}) or {}):
        if keep_kind == "stt" and n == keep_name:
            continue
        try:
            if stt.instances[n].is_loaded():
                stt.unload_engine(n)
                freed.append("слух " + n)
        except Exception:
            pass
    try:
        import gc
        gc.collect()
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass
    return freed


# ──────────────────────────── качалки весов ──────────────────────────
def _md5(path: Path) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _fetch(url: str, dest: Path, note=None) -> None:
    """Скачать в .part и переименовать: недокачанный файл не должен
    выглядеть как готовый — на этом уже горели с битым .ckpt."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(dest.suffix + ".part")
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": "ANAMORF"})
    with urllib.request.urlopen(req, timeout=60) as r:
        total = int(r.headers.get("Content-Length") or 0)
        got, last = 0, 0.0
        with open(part, "wb") as f:
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                f.write(chunk)
                got += len(chunk)
                if note and total and time.time() - last > 2:
                    last = time.time()
                    note(f"качаю {dest.name}: {got * 100 // total}%")
    part.replace(dest)


def gigaam_weights(note=None) -> dict:
    """Веса GigaAM берутся НЕ с huggingface, а с CDN Сбера, и кладутся в
    ~/.cache/gigaam. Пакет их сам не перекачивает — качаем и сверяем md5."""
    model = str(CFG.get("stt.engines.gigaam.model", "v3_e2e_rnnt"))
    d = Path.home() / ".cache" / "gigaam"
    ckpt, tok = d / f"{model}.ckpt", d / f"{model}_tokenizer.model"
    want = GIGAAM_MD5.get(model, "")
    try:
        if not tok.exists():
            _fetch(f"{GIGAAM_CDN}/{model}_tokenizer.model", tok, note)
        if not ckpt.exists():
            _fetch(f"{GIGAAM_CDN}/{model}.ckpt", ckpt, note)
        if want:
            have = _md5(ckpt)
            if have != want:
                ckpt.unlink(missing_ok=True)
                return {"ok": False,
                        "why": f"файл скачался битым (md5 {have[:8]}…, "
                               f"ждали {want[:8]}…) — удалила, попробуй ещё"}
        return {"ok": True, "where": str(d)}
    except Exception as e:
        return {"ok": False, "why": f"не скачалось: {e}"}


_DOWNLOADERS = {("stt", "gigaam"): gigaam_weights}


# ───────────────── устаревший пакет в runtime ────────────────────────
# ДВА ЖИВЫХ СЛУЧАЯ ОДНОЙ ПРИРОДЫ (22.08.2026), оба стоили вечера:
#
#   1. `Model 'v3_e2e_rnnt' not found. Available model names: [... v2_rnnt]`
#      — в runtime стоял gigaam 0.1.0 с pypi, который про v3 не знает
#      вовсе. Разбор ошибок при этом кричал «что-то с сетью, проверь
#      VPN», человек искал VPN, а сломан был пакет.
#   2. `'Qwen3TTSModel' object has no attribute
#      'stream_generate_voice_clone'` — потоковый форк был подложен в
#      site-packages ПОСЛЕ старта программы: на диске он новый, а в
#      памяти живёт старый, и никакая перезагрузка ДВИЖКА этого не
#      меняет, потому что модуль лежит в sys.modules.
#
# Лечение у обоих одно: положить правильный пакет и ВЫКИНУТЬ его из
# sys.modules, чтобы следующий импорт прочитал файлы заново. Это и есть
# «не выходя из программы»: перезапуск ради подменённой папки — цена,
# которую платить незачем.
_PKG_SRC = {
    "gigaam": ("third_party/GigaAM/gigaam", "stt"),
    "qwen_tts": ("third_party/Qwen3-TTS-streaming/qwen_tts", "tts"),
}
_ENGINE_PKG = {("stt", "gigaam"): "gigaam", ("tts", "qwen3"): "qwen_tts"}


def _site_packages() -> Path | None:
    import sysconfig
    for key in ("purelib", "platlib"):
        try:
            p = Path(sysconfig.get_paths()[key])
            if p.is_dir():
                return p
        except Exception:
            continue
    return None


def drop_modules(prefix: str) -> int:
    """Выкинуть пакет из памяти, чтобы следующий импорт прочитал диск."""
    import sys
    names = [m for m in list(sys.modules)
             if m == prefix or m.startswith(prefix + ".")]
    for m in names:
        sys.modules.pop(m, None)
    return len(names)


def _pkg_source(pkg: str) -> Path | None:
    rel = (_PKG_SRC.get(pkg) or ("", ""))[0]
    if not rel:
        return None
    for base in (ROOT, DATA_ROOT, ROOT.parent):
        p = base / rel
        if p.is_dir():
            return p
    return None


def refresh_package(pkg: str) -> dict:
    """Поставить наш пакет поверх того, что лежит в runtime, и забыть его.

    Старую версию НЕ удаляем, а уводим в `_to_delete/` — снос чужого
    пакета вслепую отличается от подмены ровно тем, что его нельзя
    отменить.
    """
    src = _pkg_source(pkg)
    if not src:
        return {"ok": False,
                "why": f"свежего «{pkg}» нет рядом со сборкой — "
                       f"он лежит в third_party у разработчика"}
    sp = _site_packages()
    if not sp:
        return {"ok": False, "why": "не нашла site-packages этой сборки"}
    dst = sp / pkg
    try:
        if dst.exists():
            old = DATA_ROOT / "_to_delete" / f"{pkg}_{int(time.time())}"
            old.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(dst), str(old))
        shutil.copytree(src, dst,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    except Exception as e:
        return {"ok": False, "why": f"пакет не подменился: {e}"}
    n = drop_modules(pkg)
    return {"ok": True,
            "did": f"поставила свой «{pkg}» из third_party"
                   + (f" и выкинула из памяти {n} модулей" if n else "")}


def _pkg_fix(kind: str, name: str) -> dict:
    pkg = _ENGINE_PKG.get((kind, name))
    if not pkg:
        return {"ok": False,
                "why": f"не знаю, какой пакет отвечает за «{name}»"}
    r = refresh_package(pkg)
    if r.get("ok"):
        # движок держит ссылку на старый класс — сбрасываем экземпляр
        stt, tts = _mgr()
        try:
            if kind == "stt":
                stt.unload_engine(name)
                stt.instances.pop(name, None)
            else:
                tts.unload_engine(name)
                eng = tts.engines.get(name)
                for attr in ("model", "prompt"):
                    if hasattr(eng, attr):
                        setattr(eng, attr, None)
        except Exception as e:
            log.debug("старый экземпляр не сброшен: %s", e)
    return r


# ─────────────────────────────── лечение ─────────────────────────────
def _switch(kind: str, broken: str) -> dict:
    """Уйти на живой движок. Не «переключаюсь», а переключилась и проверила."""
    stt, tts = _mgr()
    if kind == "stt":
        order = [n for n in stt.status().get("engines", [])
                 if n not in ("off", broken)]
    else:
        # у голоса первым делом лёгкие: они не спорят за видеопамять
        have = list(getattr(tts, "engines", {}) or {})
        order = [n for n in _LIGHT_VOICES if n in have] + \
                [n for n in have if n not in _LIGHT_VOICES and n != broken
                 and n not in ("off", "none")]
    for n in order:
        ok, why = _try_load(kind, n)
        if ok:
            try:
                (stt if kind == "stt" else tts).set_engine(n)
            except Exception as e:
                return {"ok": False, "why": f"«{n}» поднялся, но не встал "
                                            f"текущим: {e}"}
            return {"ok": True, "did": f"перешла на «{n}»", "who": n}
        log.info("repair: запасной «%s» тоже не встал: %s", n, why)
    return {"ok": False, "why": "живых запасных движков не осталось"}


def _redownload(kind: str, name: str) -> dict:
    """Снести битый кэш, чтобы движок скачал заново на следующей загрузке."""
    killed = []
    if kind == "stt" and name == "gigaam":
        model = str(CFG.get("stt.engines.gigaam.model", "v3_e2e_rnnt"))
        p = Path.home() / ".cache" / "gigaam" / f"{model}.ckpt"
        if p.exists():
            p.unlink(missing_ok=True)
            killed.append(str(p))
    elif kind == "tts" and name == "silero":
        try:
            eng = _mgr()[1].engines.get("silero")
            pack = str(CFG.get("tts.silero.model", "v5_cis_base"))
            if eng and hasattr(eng, "_drop_if_corrupt") and \
                    eng._drop_if_corrupt(pack):
                killed.append(f"пакет silero {pack}")
        except Exception as e:
            log.debug("silero: битый пакет не снесён: %s", e)
    if not killed:
        return {"ok": False, "why": "битого файла в кэше не нашла — "
                                    "значит дело не в закачке"}
    return {"ok": True, "did": "снесла битое: " + ", ".join(killed)}


def _download(kind: str, name: str, note=None) -> dict:
    fn = _DOWNLOADERS.get((kind, name))
    if not fn:
        return {"ok": False,
                "why": f"весов «{name}» я качать не умею — их ставит "
                       "setup/first_run.py"}
    r = fn(note)
    if not r.get("ok"):
        return {"ok": False, "why": r.get("why", "не скачалось")}
    return {"ok": True, "did": f"скачала веса «{name}» в {r.get('where', '')}"}


def _to_cpu(kind: str, name: str) -> dict:
    key = f"{kind}.engines.{name}.device"
    if CFG.get(key, None) is None:
        return {"ok": False,
                "why": f"у «{name}» нет ручки выбора устройства — он сам "
                       "решает, где считать"}
    CFG.set(key, "cpu")
    return {"ok": True, "did": f"перевела «{name}» на процессор"}


def _pagefile() -> dict:
    """Файл подкачки правится ТОЛЬКО с правами администратора: запустить
    можем, но обещать результат — нет, пока человек не подтвердит UAC."""
    bat = ROOT / "tools" / "fix_pagefile.bat"
    if not bat.exists():
        return {"ok": False, "why": f"нет {bat} — в сборке этого нет; "
                                    "увеличь файл подкачки Windows вручную"}
    try:
        subprocess.Popen(["cmd", "/c", "start", "", str(bat)],
                         creationflags=getattr(subprocess,
                                               "CREATE_NEW_CONSOLE", 0))
    except Exception as e:
        return {"ok": False, "why": f"не запустилось: {e}"}
    return {"ok": False, "why": "запустила tools/fix_pagefile.bat — "
                                "подтверди запрос администратора в окне, "
                                "потом жми «Починить» ещё раз"}


# ───────────────────────────── точка входа ───────────────────────────
def run(component: str, fix: str | None = None, note=None) -> dict:
    """Починить один модуль. component: 'stt.<движок>' | 'tts.<движок>'.

    Возвращает ЧЕСТНЫЙ разбор:
      ok      — работает ли модуль ПОСЛЕ починки (проверено загрузкой);
      did     — что именно сделано, по шагам;
      why     — если не вышло: почему, человеческим языком;
      state   — 'ready' | 'broken' | 'switched' (живём на запасном).
    """
    kind, name = _split(component)
    if kind not in ("stt", "tts"):
        return {"ok": False, "component": component,
                "why": f"«{component}» я чинить не умею — здесь только слух "
                       "и голос"}
    with _BUSY_LOCK:
        if time.time() - _BUSY.get(component, 0) < 120:
            return {"ok": False, "component": component,
                    "why": "этот модуль уже чинится, жду результата"}
        _BUSY[component] = time.time()
    try:
        return _run(kind, name, component, fix, note)
    finally:
        _BUSY.pop(component, None)


def _run(kind, name, component, fix, note) -> dict:
    d = diag_for(component) or {}
    cat = d.get("category", "")
    fix = fix or d.get("fix") or "switch"
    did: list[str] = []

    # СНАЧАЛА СМОТРИМ НА ДИСК, ПОТОМ НА ТЕКСТ ОШИБКИ (2026-08-22). Разбор
    # мог сложиться до того, как стало ясно, что весов вообще нет: у
    # GigaAM закачка упирается в таймаут, и в last_diag остаётся «сеть» с
    # лечением «уйти на запасной». Уходить некуда — файла нет, и никакой
    # запасной этого не изменит. Если веса отсутствуют, единственное
    # осмысленное действие — качать, чем бы ни закончилась прошлая попытка.
    from anamorf import diagnostics as _dg
    if fix in ("switch", "cpu", "wait") and cat != "oldpkg" \
            and _dg._weights_missing(name):
        fix, cat = "download", "nomodel"

    def say(t):
        did.append(t)
        log.info("repair %s: %s", component, t)
        if note:
            try:
                note(t)
            except Exception:
                pass

    # 1. Случаи, где чинить нечего, и врать про починку нельзя.
    if fix == "wait" or cat == "loading":
        ok, why = _try_load(kind, name)
        return {"ok": ok, "component": component, "did": did,
                "state": "ready" if ok else "loading",
                "why": "" if ok else "модель ещё едет — это не поломка, ждём"}
    if fix == "absent":
        return {"ok": False, "component": component, "did": did,
                "state": "broken",
                "why": d.get("human") or f"«{name}» нет в этой сборке — "
                                         "чинить нечего"}

    # 2. Настоящее лечение по коду причины.
    step = {"ok": True}
    if fix == "pkg" or cat == "oldpkg":
        step = _pkg_fix(kind, name)
    elif fix == "download" or cat == "nomodel":
        step = _download(kind, name, note)
    elif fix == "redownload" or cat == "corrupt":
        step = _redownload(kind, name)
    elif fix == "cpu" or cat == "cuda":
        step = _to_cpu(kind, name)
    elif fix == "pagefile" or cat == "space":
        step = _pagefile()
    elif cat in ("vram", ""):
        freed = _free_vram(kind, name)
        step = {"ok": bool(freed),
                "did": "освободила видеопамять: " + ", ".join(freed)
                       if freed else "",
                "why": "освобождать нечего — память держит не моя модель"}
    if step.get("did"):
        say(step["did"])

    # 3. ПРОВЕРКА. Единственное, что даёт право сказать «работает».
    ok, why = _try_load(kind, name)
    if ok:
        try:
            (_mgr()[0] if kind == "stt" else _mgr()[1]).set_engine(name)
        except Exception as e:
            log.debug("не поставился текущим: %s", e)
        say(f"«{name}» поднялся и стал текущим")
        _remember(component, did, True)
        return {"ok": True, "component": component, "did": did,
                "state": "ready", "why": ""}

    # 4. Не поднялся — вторая правда: на чём мы живём сейчас.
    if not step.get("ok") and step.get("why"):
        why = step["why"] + (f" (движок сказал: {why})" if why else "")
    sw = _switch(kind, name)
    if sw.get("ok"):
        say(sw["did"])
        _remember(component, did, False)
        return {"ok": False, "component": component, "did": did,
                "state": "switched", "who": sw.get("who", ""),
                "why": f"«{name}» не поднялся: {why}. Работаю на "
                       f"«{sw.get('who')}»"}
    _remember(component, did, False)
    return {"ok": False, "component": component, "did": did,
            "state": "broken",
            "why": f"«{name}» не поднялся: {why}. {sw.get('why', '')}"}


def _remember(component: str, did: list, ok: bool):
    try:
        from anamorf import repairs
        repairs.note_fix(f"{component}: починка по кнопке",
                         "; ".join(did) or "ничего не сделано")
    except Exception as e:
        log.debug("журнал починок не записан: %s", e)
