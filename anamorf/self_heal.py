"""Живой самолечащийся сторож — работает ВНУТРИ запущенного сервера.

Философия проекта: само ставится, само чинится, Беймакс человеческим языком
говорит что не так и в это же время лечит. Доктор (setup/doctor.py) чинит
на СТАРТЕ и при КРАШЕ; этот модуль закрывает пробел — следит в РЕАЛЬНОМ
времени, пока Сайка работает.

Раз в heal.interval_sec делает лёгкие проверки (только дешёвые — сетевые
пинги и статусы, без тяжёлого импорта torch), и при проблеме:
  1) один раз сообщает через report_problem -> Беймакс говорит в чат;
  2) СРАЗУ запускает починку в фоне (поднять Ollama, прогреть модель…).
Повторно об одной и той же проблеме не долбит (кулдаун), о восстановлении
сообщает отдельно (Беймакс радуется).
"""
import logging
import threading
import time

from anamorf.config import CFG

log = logging.getLogger("saika.heal")

_state = {}          # key -> {"bad": bool, "since": ts, "reported": ts}
_COOLDOWN = 300      # не жаловаться на одно и то же чаще, чем раз в 5 мин


def _once(key, is_bad, report, bad_msg, action, fix=None):
    """Сообщить о проблеме один раз и запустить фикс; о починке — тоже раз."""
    st = _state.setdefault(key, {"bad": False, "reported": 0})
    now = time.time()
    if is_bad:
        if not st["bad"] or now - st["reported"] > _COOLDOWN:
            report("heal." + key, bad_msg, action)
            st["reported"] = now
            if fix:
                threading.Thread(target=_safe_fix, args=(key, fix),
                                 daemon=True).start()
        st["bad"] = True
    else:
        if st["bad"]:
            report("heal." + key, "", "восстановлено")  # пустая ошибка = ok
        st["bad"] = False


def _safe_fix(key, fix):
    try:
        fix()
        log.info("self-heal: попытка починки '%s' выполнена", key)
    except Exception as e:
        log.warning("self-heal: починка '%s' не удалась: %s", key, e)


# ---------------- проверки (все дешёвые) ----------------
def _check_llm(report):
    """Оба LLM-бэкенда недоступны -> Беймакс говорит и поднимает Ollama."""
    from anamorf.llm import manager as llm
    try:
        st = llm.backend_status()
    except Exception:
        return
    any_up = any(st.values())

    def fix():
        import shutil
        import subprocess
        if shutil.which("ollama"):
            subprocess.Popen(["ollama", "serve"],
                             creationflags=getattr(subprocess,
                                                   "CREATE_NO_WINDOW", 0))
            time.sleep(4)

    _once("llm", not any_up, report,
          "ни один LLM-бэкенд не отвечает (LM Studio/Ollama)",
          "поднимаю Ollama и жду возврата", fix)


def _check_models(report):
    """Выбранный бэкенд жив, но моделей нет -> подсказать (не чиним молча:
    ollama pull долгий, пусть человек решит; Беймакс просто предупредит)."""
    from anamorf.llm import manager as llm
    try:
        st = llm.backend_status()
        if not any(st.values()):
            return                       # это ловит _check_llm
        models = llm.list_models()
    except Exception:
        return
    _once("models", len(models) == 0, report,
          "LLM работает, но не загружено ни одной модели",
          "загрузи модель в LM Studio или Ollama — отвечать пока нечем")


def _check_disk(report):
    """Заканчивается место на диске проекта -> предупредить заранее."""
    try:
        import shutil
        from anamorf.config import ROOT
        free_gb = shutil.disk_usage(ROOT).free / 1e9
    except Exception:
        return
    _once("disk", free_gb < 2, report,
          f"на диске меньше {free_gb:.1f} ГБ свободно",
          "освободи место — модели и логи могут не записаться")


_CHECKS = [_check_llm, _check_models, _check_disk]


def tick(report):
    for chk in _CHECKS:
        try:
            chk(report)
        except Exception as e:
            log.debug("self-heal check %s: %s", getattr(chk, "__name__", "?"), e)


def start(report):
    """Фоновый цикл. report — это report_problem из main (он же зовёт Беймакса)."""
    if not CFG.get("heal.enabled", True):
        return
    interval = CFG.get("heal.interval_sec", 90)

    def loop():
        time.sleep(20)   # дать серверу подняться
        while True:
            try:
                tick(report)
            except Exception as e:
                log.debug("self-heal tick: %s", e)
            time.sleep(interval)

    threading.Thread(target=loop, daemon=True).start()
    log.info("Живой самолечащий сторож запущен (каждые %sс)", interval)
