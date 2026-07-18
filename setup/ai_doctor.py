"""ИИ-Беймакс: локальная LLM (Ollama / LM Studio) читает логи и чинит Сайку.

Как работает:
 1. Собирает контекст: отчёт обычного доктора, хвост logs/saika.log,
    config.json, версии окружения.
 2. Отдаёт это локальной LLM (той же, что выбрана для Сайки) и просит
    план починки в виде СТРОГОГО JSON из безопасного набора действий.
 3. Выполняет только действия из белого списка (см. ниже), максимум 5 за
    раунд, до 3 раундов; после каждого раунда перепроверяет доктором.
 4. Всё пишет в logs/ai_doctor.log.

Белый список действий (ничего другого LLM сделать не может):
  pip_install          установка pip-пакетов (имена валидируются)
  reinstall_editable   переустановка editable-пакета из third_party/
  set_config           смена ключей конфига только в stt./tts./llm.
  note / done          пояснение пользователю / завершение

Запуск:
  python setup/ai_doctor.py          интерактивно (спросит подтверждение)
  python setup/ai_doctor.py --auto   молча: выходит если всё ок, чинит если нет
                                     (вызывается из start.bat при падениях)
Нужен работающий Ollama или LM Studio с хотя бы одной моделью.
"""
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")

LOG_PATH = ROOT / "logs" / "ai_doctor.log"
MAX_ROUNDS = 3
MAX_ACTIONS = 5
SAFE_PKG = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._\[\],<>=!~+\- ]*$")
ALLOWED_CFG_PREFIX = ("stt.", "tts.", "llm.")

SYSTEM = """Ты — ИИ-Беймакс локального голосового ассистента «Сайка» (Windows, \
Python 3.12, venv в .venv, движки STT/TTS, LLM через Ollama/LM Studio, \
переносимый диск — буква диска может меняться, из-за чего ломаются \
editable-пакеты в third_party/).

Тебе дают отчёт диагностики, хвост лога и конфиг. Найди причины ошибок и \
верни план починки СТРОГО в виде JSON-массива, без какого-либо текста вокруг.

Доступные действия (других НЕТ):
[
 {"action":"pip_install","packages":["имя-пакета==версия"]},
 {"action":"pip_force_reinstall","packages":["имя-пакета"]},
 {"action":"repair_venv"},
 {"action":"reinstall_editable","path":"third_party/ИмяПакета"},
 {"action":"set_config","key":"tts.engine","value":"qwen3"},
 {"action":"note","text":"короткое пояснение пользователю по-русски"},
 {"action":"done","text":"итог"}
]

Правила:
- максимум 5 действий;
- СНАЧАЛА сверься со шпаргалкой известных проблем (она в контексте) — если
симптом там есть, применяй её решение, не изобретай своё;
- чини только то, что реально видно в отчёте/логах, не выдумывай;
- «No module named X», а pip говорит "already satisfied" — это битые файлы:
pip_force_reinstall владельца модуля или repair_venv, НЕ pip_install;
- сетевые ошибки (getaddrinfo failed, ConnectionReset) НЕ чинятся пакетами — \
только note с объяснением;
- «No module named X» при существующем third_party/<репозиторий X> — это \
reinstall_editable, а не pip_install;
- если всё в порядке или починить нельзя — верни [{"action":"done","text":"…"}].
"""


def _log(msg):
    print(msg)
    LOG_PATH.parent.mkdir(exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}\n")


def _pip(*args):
    return subprocess.run([sys.executable, "-m", "pip", *args],
                          check=False).returncode == 0


def collect_context():
    """Отчёт доктора + хвост лога + конфиг + окружение -> текст для LLM."""
    from setup.doctor import run_checks
    report = run_checks(fix=False)

    log_tail = ""
    saika_log = ROOT / "logs" / "saika.log"
    if saika_log.exists():
        log_tail = saika_log.read_text(encoding="utf-8", errors="ignore")[-6000:]

    cfg = (ROOT / "config.json").read_text(encoding="utf-8")
    tp = [d.name for d in (ROOT / "third_party").iterdir() if d.is_dir()] \
        if (ROOT / "third_party").exists() else []

    issues = ""
    ki = ROOT / "setup" / "known_issues.md"
    if ki.exists():
        issues = ki.read_text(encoding="utf-8")

    ctx = (f"ШПАРГАЛКА ИЗВЕСТНЫХ ПРОБЛЕМ:\n{issues}\n\n"
           f"ОТЧЁТ ДИАГНОСТИКИ:\n{json.dumps(report, ensure_ascii=False, indent=1)}\n\n"
           f"ПАПКИ В third_party/: {tp}\n\n"
           f"КОНФИГ:\n{cfg}\n\n"
           f"ХВОСТ ЛОГА saika.log:\n{log_tail}")
    return report, ctx


def has_problems(report):
    if any(c["status"] == "fail" and c["required"] for c in report):
        return True
    saika_log = ROOT / "logs" / "saika.log"
    if saika_log.exists():
        tail = saika_log.read_text(encoding="utf-8", errors="ignore")[-4000:]
        if " ERROR " in tail:
            return True
    return False


def ask_llm(ctx):
    from server.llm import manager as llm
    if not any(llm.backend_status().values()):
        _log("[X] Ни Ollama, ни LM Studio не отвечают — ИИ-Беймаксу не с кем думать.")
        return None
    _log("[ai] Спрашиваю локальную модель…")
    raw = llm.chat_once([{"role": "system", "content": SYSTEM},
                         {"role": "user", "content": ctx}], max_len=8000)
    m = re.search(r"\[.*\]", raw, re.S)
    if not m:
        _log(f"[!] Модель ответила не-JSON: {raw[:300]}")
        return []
    try:
        plan = json.loads(m.group(0))
        return plan if isinstance(plan, list) else []
    except Exception as e:
        _log(f"[!] Не смог разобрать JSON ({e}): {m.group(0)[:300]}")
        return []


def execute(act) -> str:
    """Выполнить одно действие из белого списка. Возвращает '', 'done'."""
    a = act.get("action")
    if a == "pip_install":
        pkgs = [p for p in act.get("packages", [])
                if isinstance(p, str) and SAFE_PKG.match(p)
                and not p.strip().startswith("-")]
        if pkgs:
            _log(f"[fix] pip install {' '.join(pkgs)}")
            _pip("install", *pkgs, "--timeout", "180", "--retries", "5")
    elif a == "pip_force_reinstall":
        pkgs = [p for p in act.get("packages", [])
                if isinstance(p, str) and SAFE_PKG.match(p)
                and not p.strip().startswith("-")]
        if pkgs:
            _log(f"[fix] pip install --force-reinstall --no-deps {' '.join(pkgs)}")
            _pip("install", "--force-reinstall", "--no-deps", *pkgs,
                 "--timeout", "180", "--retries", "5")
    elif a == "repair_venv":
        _log("[fix] Проверка целостности venv (setup/repair_venv.py --deep)…")
        subprocess.run([sys.executable, str(ROOT / "setup" / "repair_venv.py"),
                        "--deep"], check=False)
    elif a == "reinstall_editable":
        p = (ROOT / str(act.get("path", ""))).resolve()
        tp = (ROOT / "third_party").resolve()
        if str(p).startswith(str(tp)) and p.exists():
            _log(f"[fix] pip install -e {p} --no-deps")
            _pip("install", "-e", str(p), "--no-deps")
        else:
            _log(f"[skip] подозрительный путь: {act.get('path')}")
    elif a == "set_config":
        key = str(act.get("key", ""))
        if key.startswith(ALLOWED_CFG_PREFIX):
            from server.config import CFG
            _log(f"[fix] config {key} = {act.get('value')}")
            CFG.set(key, act.get("value"))
        else:
            _log(f"[skip] ключ вне белого списка: {key}")
    elif a == "note":
        _log(f"[ai] {act.get('text', '')}")
    elif a == "done":
        _log(f"[ai] Итог: {act.get('text', '')}")
        return "done"
    else:
        _log(f"[skip] неизвестное действие: {a}")
    return ""


def main():
    auto = "--auto" in sys.argv
    report, ctx = collect_context()
    if not has_problems(report):
        _log("✓ Проблем не вижу — ИИ-Беймакс не нужен.")
        return

    if not auto:
        ans = input("Найдены проблемы. Позвать локальную LLM чинить? [y/N] ")
        if ans.strip().lower() not in ("y", "д", "да", "yes"):
            return

    for rnd in range(1, MAX_ROUNDS + 1):
        _log(f"\n── ИИ-Беймакс, раунд {rnd}/{MAX_ROUNDS} ──")
        plan = ask_llm(ctx)
        if plan is None:  # нет LLM
            return
        if not plan:
            _log("[!] Пустой план — прекращаю.")
            return
        finished = False
        for act in plan[:MAX_ACTIONS]:
            if execute(act) == "done":
                finished = True
                break
        # перепроверка обычным доктором (с его собственными фиксами)
        from setup.doctor import run_checks
        report = run_checks(fix=True)
        if finished or not has_problems(report):
            _log("✓ ИИ-Беймакс закончил.")
            return
        _, ctx = collect_context()
    _log("[!] Раунды кончились — что осталось, чинить руками (см. logs/ai_doctor.log).")


if __name__ == "__main__":
    main()
