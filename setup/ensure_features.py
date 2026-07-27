"""Дозаливка зависимостей отдельных возможностей (2026-07-25).

ЗАЧЕМ. first_run.py отрабатывает ОДИН раз и после этого не запускается —
в .setup_state.json стоит setup_complete. Значит любая новая возможность
(зрение, следующие после неё) на уже настроенной машине оказывается без
своих библиотек, и владелец видит «No module named …» вместо работы.
Особенно больно на втором ПК: код приезжает по git, а pip install никто
не делал.

Этот скрипт зовётся из start.bat КАЖДЫЙ запуск и стоит миллисекунды:
importlib.util.find_spec не импортирует модуль, только ищет его. Нашёл
всё — молча вышел. Чего-то нет — ставит и продолжает.

ПОЧЕМУ НЕ ПРОСТО pip install ПРИ КАЖДОМ СТАРТЕ. Потому что бывает офлайн,
провайдер режет PyPI, а колесо может не собраться на этой машине. Тогда
установка при каждом старте — это минута ожидания перед каждым запуском
Сайки, навсегда. Поэтому неудачи запоминаются и повторяются с задержкой
(RETRY_AFTER_H), а не бесконечно.

Ручной запуск:
    .venv\\Scripts\\python.exe setup\\ensure_features.py            # доставить
    .venv\\Scripts\\python.exe setup\\ensure_features.py --check    # только отчёт
    .venv\\Scripts\\python.exe setup\\ensure_features.py --force    # забыть отказы
    .venv\\Scripts\\python.exe setup\\ensure_features.py vision     # одну штуку
"""
import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = str(ROOT / ".venv" / "Scripts" / "python.exe")
if not Path(PY).exists():                 # запустили не из venv-питона
    PY = sys.executable
STATE_PATH = ROOT / ".setup_state.json"
RETRY_AFTER_H = 24        # неудачная установка повторится не раньше, чем через сутки
MAX_ATTEMPTS = 3          # ...и не больше стольких раз, пока не позовут с --force

# Возможность = что импортируем + что ставим.
#   core  — без этого возможность не работает вообще
#   extra — ускорители и удобства, их отсутствие не беда
# Новая фича = новая запись здесь, больше ничего трогать не надо.
FEATURES = {
    "vision": {
        "title": "Глаза: экран и вебка",
        # opencv закреплён на 4.13.x осознанно: 5.0.0 вышел 02.07.2026, это
        # major трёхнедельной давности, а сервер перезапускается вручную —
        # поломку от свежего major владелец обнаружит не сразу.
        "core_modules": ["cv2", "mss"],
        "core_pip": ["opencv-python==4.13.0.92", "mss"],
        # dxcam/windows-capture — быстрые бэкенды захвата. Не встанут —
        # зрение останется на mss, просто медленнее. pygrabber даёт
        # человеческие имена вебок вместо «Камера 0».
        "extra_modules": ["dxcam", "windows_capture", "pygrabber"],
        "extra_pip": ["dxcam[cv2]", "windows-capture", "pygrabber"],
    },
    "piper": {
        "title": "Голос Piper (офлайн, MIT)",
        # onnxruntime, а не torch — ставится за секунды и не тянет CUDA.
        # Русские голоса качаются при первом запуске в models/piper.
        "core_modules": ["piper"],
        "core_pip": ["piper-tts"],
        "extra_modules": [],
        "extra_pip": [],
    },
    "pc": {
        "title": "Руки в Windows: программы, окна, звук, вкладки",
        # Окна и запуск программ работают на голом ctypes — без единой
        # зависимости. Здесь только то, без чего часть команд деградирует:
        # keyboard нужен вкладкам браузера, pycaw — точному проценту
        # громкости (без него остаётся «громче/тише» клавишами).
        "core_modules": [],
        "core_pip": [],
        "extra_modules": ["keyboard", "pycaw"],
        "extra_pip": ["keyboard", "pycaw"],
    },
    "phone": {
        "title": "Доступ с телефона (QR)",
        # Без qrcode всё работает, просто адрес придётся набирать руками —
        # поэтому библиотека в extra, а не в core.
        "core_modules": [],
        "core_pip": [],
        # cryptography нужна для самоподписанного сертификата: без https
        # браузер не отдаёт микрофон на телефоне (защищённый контекст)
        "extra_modules": ["qrcode", "cryptography"],
        "extra_pip": ["qrcode", "cryptography"],
    },
    "pdf": {
        "title": "Чтение PDF-чертежей",
        "core_modules": ["fitz"],
        "core_pip": ["PyMuPDF"],
        "extra_modules": [],
        "extra_pip": [],
    },
    # НЕ ПАКЕТ, А ПРОГРАММА (2026-07-27). Свой движок мозгов — нативный
    # llama-server из llama.cpp: он не ставится через pip, это .exe из
    # релиза на GitHub. Раньше такие вещи приходилось ставить руками
    # отдельной командой — ровно то, чего в проекте быть не должно: всё
    # доставляется само, при обычном запуске start.bat.
    "llamacpp": {
        "title": "Свой движок мозгов (llama.cpp, CUDA)",
        "core_modules": [],
        "core_pip": [],
        "extra_modules": [],
        "extra_pip": [],
        # проверка — по файлу на диске, а не по importlib
        "core_files": ["third_party/llamacpp/llama-server.exe"],
        "install_script": "setup/install_llamacpp.py",
        # ~600 МБ разово; отключается llamacpp.autoinstall=false в config
        "config_flag": "llamacpp.autoinstall",
        "windows_only": True,
    },
}


def _state():
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save(st):
    try:
        STATE_PATH.write_text(json.dumps(st, indent=2, ensure_ascii=False),
                              encoding="utf-8")
    except Exception as e:
        print(f"[!] не смогла записать {STATE_PATH.name}: {e}")


def have(mod: str) -> bool:
    """Есть ли модуль. find_spec НЕ импортирует — стоит доли миллисекунды,
    поэтому проверку можно звать на каждом старте без раздумий."""
    try:
        return importlib.util.find_spec(mod) is not None
    except Exception:
        return False


def missing(mods) -> list:
    return [m for m in mods if not have(m)]


def missing_files(paths) -> list:
    """Чего не хватает из ПРОГРАММ (не пакетов). Проверка на существование
    файла — такая же дешёвая, как find_spec, и так же безопасна на каждом
    старте."""
    return [p for p in (paths or []) if not (ROOT / p).exists()]


def run_installer(script: str) -> bool:
    """Своя установка возможности (скачать бинарь, распаковать). Скрипт сам
    решает, что делать; наше дело — позвать и не уронить старт."""
    print(f"    > {script}")
    try:
        return subprocess.run([PY, str(ROOT / script)],
                              cwd=str(ROOT)).returncode == 0
    except Exception as e:
        print(f"    [!] {script} не запустился: {e}")
        return False


def _flag_allows(spec: dict) -> bool:
    """Возможность может быть выключена настройкой (напр. не качать 600 МБ
    движка на машине, где он не нужен). Конфиг читаем сами, без импорта
    server.config: этот скрипт зовётся ДО того, как проект вообще готов."""
    key = spec.get("config_flag")
    if not key:
        return True
    val = None
    for name in ("config.local.json", "config.json"):
        try:
            data = json.loads((ROOT / name).read_text(encoding="utf-8"))
        except Exception:
            continue
        node = data
        for part in key.split("."):
            if not isinstance(node, dict) or part not in node:
                node = None
                break
            node = node[part]
        if node is not None:
            val = node
            break
    return True if val is None else bool(val)


def pip_install(pkgs) -> bool:
    """pip с гигиеной проекта: временные файлы на диске проекта (антивирус
    любит блокировать большие whl в C:\\Windows\\Temp — WinError 32),
    длинный таймаут и повторы (колёса рвутся по сети)."""
    tmp = ROOT / ".pip_tmp"
    tmp.mkdir(exist_ok=True)
    env = dict(os.environ, TMP=str(tmp), TEMP=str(tmp))
    cmd = [PY, "-m", "pip", "install", *pkgs, "--timeout", "180",
           "--retries", "5"]
    print("    >", " ".join(pkgs))
    try:
        return subprocess.run(cmd, env=env, cwd=str(ROOT)).returncode == 0
    except Exception as e:
        print(f"    [!] pip не запустился: {e}")
        return False


def _skip_reason(rec: dict, force: bool) -> str:
    """Почему НЕ пытаемся ставить снова. Пустая строка = пытаемся."""
    if force or not rec:
        return ""
    if rec.get("status") == "ok":
        return ""                       # ok — но модулей нет, значит пробуем
    tries = int(rec.get("attempts", 0))
    if tries >= MAX_ATTEMPTS:
        return (f"установка не удавалась {tries} раза — больше не пробую "
                "сама. Запусти setup\\ensure_features.py --force")
    left = rec.get("ts", 0) + RETRY_AFTER_H * 3600 - time.time()
    if left > 0:
        return f"недавняя попытка не удалась, повторю через {left / 3600:.0f} ч"
    return ""


def ensure(name: str, spec: dict, st: dict, force=False, check=False) -> dict:
    core_miss = missing(spec["core_modules"]) + missing_files(
        spec.get("core_files"))
    extra_miss = missing(spec.get("extra_modules", []))
    rec = st.setdefault("features", {}).setdefault(name, {})

    if check:
        return {"feature": name, "core_missing": core_miss,
                "extra_missing": extra_miss,
                "ok": not core_miss, "status": rec.get("status", "?")}

    if not core_miss and not extra_miss:
        rec.update(status="ok", ts=time.time())
        return {"feature": name, "ok": True, "action": "уже всё есть"}

    if spec.get("windows_only") and os.name != "nt":
        return {"feature": name, "ok": True, "action": "не для этой ОС"}
    if not _flag_allows(spec):
        return {"feature": name, "ok": True, "action": "выключено настройкой"}

    reason = _skip_reason(rec, force)
    if reason and core_miss:
        print(f"[~] {spec['title']}: пропускаю — {reason}")
        return {"feature": name, "ok": False, "action": "пропущено: " + reason}

    print(f"\n[*] {spec['title']}: доставляю недостающее")
    ok = True
    if core_miss:
        print(f"    нет: {', '.join(core_miss)}")
        if spec.get("install_script"):
            ok = run_installer(spec["install_script"])
        else:
            ok = pip_install(spec["core_pip"])
    if extra_miss and (ok or not core_miss):
        # ускорители ставим отдельной командой, чтобы падение одного колеса
        # не утащило за собой обязательную часть
        print(f"    необязательные: {', '.join(extra_miss)}")
        if not pip_install(spec["extra_pip"]):
            print("    [~] ускорители не встали — не страшно, работаем без них")

    still = missing(spec["core_modules"]) + missing_files(
        spec.get("core_files"))
    if still:
        rec.update(status="failed", ts=time.time(),
                   attempts=int(rec.get("attempts", 0)) + 1,
                   missing=still)
        print(f"[X] {spec['title']}: всё ещё нет {', '.join(still)}. "
              "Сайка запустится, но эта возможность будет молчать.")
        return {"feature": name, "ok": False, "action": "не удалось"}

    rec.update(status="ok", ts=time.time(), attempts=0, missing=[])
    print(f"[+] {spec['title']}: готово")
    return {"feature": name, "ok": True, "action": "установлено"}


def check_secrets():
    """secrets.json намеренно НЕ в git (репо публичный) — значит на второй
    машине его просто нет, и облачные модели с ботами молча не работают.
    Молчаливый отказ хуже громкого: печатаем напоминание один раз за старт."""
    if (ROOT / "secrets.json").exists():
        return True
    if not (ROOT / "secrets.example.json").exists():
        return True
    print("\n[i] secrets.json на этой машине нет — это нормально сразу после "
          "git clone/pull:\n    ключи и токены намеренно не лежат в "
          "публичном репозитории.\n    Скопируй secrets.json с первого ПК "
          "(флешкой/мессенджером) или создай\n    из secrets.example.json. "
          "Без него не будет облачных моделей и ботов,\n    всё остальное "
          "работает как обычно.")
    return False


def main(argv):
    force = "--force" in argv
    check = "--check" in argv
    wanted = [a for a in argv[1:] if not a.startswith("-")]
    names = wanted or list(FEATURES)

    st = _state()
    if force:
        for n in names:
            st.get("features", {}).pop(n, None)

    results = []
    for n in names:
        spec = FEATURES.get(n)
        if not spec:
            print(f"[?] неизвестная возможность: {n}")
            continue
        try:
            results.append(ensure(n, spec, st, force=force, check=check))
        except Exception as e:
            print(f"[X] {n}: {e}")
            results.append({"feature": n, "ok": False, "action": str(e)})

    if not check:
        _save(st)
        check_secrets()
    else:
        print(json.dumps(results, ensure_ascii=False, indent=2))

    # НИКОГДА не роняем старт: Сайка должна подниматься даже если интернета
    # нет и ничего не поставилось. Отсутствие фичи — не повод не жить.
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
