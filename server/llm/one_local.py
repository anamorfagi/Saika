"""ОДИН ЛОКАЛЬНЫЙ ДВИЖОК НА ВИДЕОКАРТУ (2026-08-20).

Живой лог 09:03. За тридцать девять секунд:

    09:03:13  locallm: запускаю воркер T-lite-it-2.1 (Q4_K_M, 32k)
    09:03:18  ЗАЩИТА: VRAM 96% — выгружаю всё, чтобы не уронить ПК
    09:03:33  временно выключила ОЗВУЧКУ
    09:03:52  выгрузила локальные МОЗГИ
    09:04:11  ответ через 59 секунд

Разговор шёл на llamacpp/gemma-4-e4b, она уже занимала видеокарту. Второй
восьмимиллиардный движок туда физически не влезал — и не должен был
пытаться. Дальше сработало всё, что должно: сторож, ступени разгрузки,
облако. Но лечили они не болезнь, а её последствие: в шестнадцати
гигабайтах нельзя держать две большие модели, и решать это надо ДО
запуска, а не выгрузкой всего подряд после.

Владелец про этот же случай месяцем раньше, дословно: «бля какого хера он
грузит 2е ллм одновременно».

ПРАВИЛО. Пока жив один локальный движок, второй не поднимается. Не
«выгружаем первый и грузим второй» — именно не поднимаем: разговор уже
идёт на первом, а выгрузка посреди фразы обрывает ответ. Тот, кому
отказали, поднимается по лестнице мозгов выше — в облако — или ждёт.

ИСКЛЮЧЕНИЕ. Человек попросил прямо («подними T-lite») — тогда это его
решение, и запрет снимается ключом llm.two_local_ok или вызовом с
force=True. Мы бережём железо, а не запрещаем им пользоваться.
"""
import logging

from server.config import CFG

log = logging.getLogger("saika.llm")

# Кто из движков держит ВИДЕОКАРТУ. Все четыре, а не два: владелец
# 20.08, про тот же случай в третий раз — «у нас есть своя ллм на c++,
# нафиг он стартует ещё одну с лм студио такую же; я вот тебе уже об этом
# говорил, но ты не правил — мне приходилось вырубать лм студио руками».
# Прошлая правка закрыла только связку llamacpp/locallm, а LM Studio и
# Ollama грузят модель в ту же память ровно так же.
BACKENDS = ("llamacpp", "locallm", "lmstudio", "ollama")


def _alive(name: str) -> bool:
    """Держит ли этот движок модель в памяти ПРЯМО СЕЙЧАС.

    Спрашиваем каждого его собственным способом и никогда — через импорт
    соседа: иначе проверка сама подняла бы то, что проверяет.
    """
    try:
        if name == "llamacpp":
            from server.llm import llamacpp as m
            h = m._health()
            return bool(h is not None and not h.get("error"))
        if name == "locallm":
            from server.llm import locallm as m
            if not m.installed():
                return False
            h = m._health()
            return bool(h is not None and not h.get("error"))
        import requests
        from server.llm import manager as mgr
        if name == "ollama":
            r = requests.get(mgr._ollama_url() + "/api/ps", timeout=2)
            return bool(r.ok and (r.json().get("models") or []))
        if name == "lmstudio":
            r = requests.get(mgr._lmstudio_url() + "/api/v0/models", timeout=2)
            return any(x.get("state") == "loaded"
                       for x in (r.json().get("data") or []))
    except Exception:
        return False
    return False


def holder(me: str) -> str:
    """Имя ЧУЖОГО локального движка, который сейчас держит видеокарту.
    Пусто — путь свободен."""
    for name in BACKENDS:
        if name != me and _alive(name):
            return name
    return ""


def refuse(me: str, force: bool = False) -> dict:
    """{} — можно поднимать. Иначе — готовая ошибка для ensure_running."""
    if force or CFG.get("llm.two_local_ok", False):
        return {}
    who = holder(me)
    if not who:
        return {}
    log.warning("Второй локальный движок не поднимаю: видеокарту держит "
                "«%s», просили «%s» (правило server/llm/one_local.py)",
                who, me)
    return {"error": f"видеокарту уже держит локальный движок «{who}» — "
                     f"второй ({me}) в неё не влезет. Отвечаю тем, что "
                     "поднято, или облаком. Если нужен именно этот — "
                     "скажи прямо, тогда сперва выгружу первый."}
