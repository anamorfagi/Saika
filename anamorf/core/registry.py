"""ИНСТРУМЕНТЫ ЯДРА v2: что видит модель и что ей разрешено.

Было: 112 схем на 50 тыс. символов, каждый ход отбирались «по словам»
— набор менялся, KV-кэш слетал, модель путала похожие имена.
Стало:
  * CORE — ~18 частых инструментов со схемами (стабильный набор, кэш живёт);
  * use_tool(name, args) — дверь ко ВСЕМ остальным по имени из указателя.
    Набор схем от этого не меняется никогда.
  * policy() — один слой риска у исполнителя, а не регулярки по фразам.
Реализации инструментов — старые (anamorf/llm/tools.py), мы их не трогаем.
"""
import json
import logging
import re

log = logging.getLogger("saika.core.tools")

CORE = [
    "web_open", "web_research", "tabs_list", "tab_control", "media_control",
    "app_launch", "where_am_i", "window_focus", "window_close",
    "open_folder", "folder_list", "find_folder", "run_file",
    "volume_set", "look_screen", "memory_recall", "memory_about", "recall_thread",
]

# риск: что требует явного «да» владельца в ЭТОЙ реплике
CONFIRM = {"fs_delete", "fs_write", "fs_move", "fs_rename", "shutdown_self",
           "unload_memory", "model_switch", "set_engine", "net_bypass",
           "guests_may_talk", "remember_my_voice", "delegate_task"}
# никогда из ядра (внутренняя кухня старой системы)
DENY = {"fs_grep", "fs_slice", "fs_log", "fs_lasterr", "workshop_create"}
_YES = re.compile(r"^\s*(да|ага|давай|подтверждаю|удаляй|выключай|делай|можно|"
                  r"конечно|ок|окей|закрывай|жми|печатай|отправляй)\b", re.I)

_CACHE = {"core": None, "all": None, "index": ""}

USE_TOOL = {"type": "function", "function": {
    "name": "use_tool",
    "description": ("Вызвать ЛЮБОЙ другой свой инструмент по имени из указателя "
                    "«Остальные инструменты». Если не знаешь его параметров — сначала "
                    "tool_help(name)."),
    "parameters": {"type": "object", "properties": {
        "name": {"type": "string", "description": "имя инструмента из указателя"},
        "args": {"type": "object", "description": "параметры инструмента"}},
        "required": ["name"]}}}

TOOL_HELP = {"type": "function", "function": {
    "name": "tool_help",
    "description": "Описание и параметры инструмента из указателя.",
    "parameters": {"type": "object", "properties": {
        "name": {"type": "string"}}, "required": ["name"]}}}


CALC = {"type": "function", "function": {
    "name": "calc",
    "description": ("Точно посчитать арифметику (+ - * / ** %, скобки). Любые числа "
                    "считай ТОЛЬКО так: в уме модель ошибается (стенд: 17×23 -> «309»)."),
    "parameters": {"type": "object", "properties": {
        "expr": {"type": "string", "description": "например 17*23"}},
        "required": ["expr"]}}}


def _calc(expr: str) -> str:
    import ast
    import operator as op
    ops = {ast.Add: op.add, ast.Sub: op.sub, ast.Mult: op.mul, ast.Div: op.truediv,
           ast.Pow: op.pow, ast.Mod: op.mod, ast.FloorDiv: op.floordiv,
           ast.USub: op.neg, ast.UAdd: op.pos}

    def ev(n):
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)):
            return n.value
        if isinstance(n, ast.BinOp) and type(n.op) in ops:
            a, b = ev(n.left), ev(n.right)
            if isinstance(n.op, ast.Pow) and abs(b) > 100:
                raise ValueError("слишком большая степень")
            return ops[type(n.op)](a, b)
        if isinstance(n, ast.UnaryOp) and type(n.op) in ops:
            return ops[type(n.op)](ev(n.operand))
        raise ValueError("только числа и + - * / ** %")
    try:
        e = expr.replace("×", "*").replace("÷", "/").replace(",", ".").replace("^", "**")
        v = ev(ast.parse(e, mode="eval").body)
        if isinstance(v, float) and v.is_integer():
            v = int(v)
        return f"{expr} = {v}"
    except Exception as ex:
        return f"не посчитала «{expr}»: {ex}"


def _all() -> dict:
    if _CACHE["all"] is None:
        from anamorf.llm import tools as _t
        _CACHE["all"] = {(s.get("function") or {}).get("name"): s
                         for s in _t.schemas()}
    return _CACHE["all"]


def schemas() -> list:
    """Стабильный набор схем: одни и те же байты каждый ход."""
    if _CACHE["core"] is None:
        a = _all()
        _CACHE["core"] = [a[n] for n in CORE if n in a] + [CALC, USE_TOOL, TOOL_HELP]
    return _CACHE["core"]


def index_text() -> str:
    """Указатель остальных инструментов: имя — первая фраза описания."""
    if not _CACHE["index"]:
        rows = []
        for n, s in sorted(_all().items()):
            if not n or n in CORE or n in DENY:
                continue
            d = ((s.get("function") or {}).get("description") or "").strip()
            d = re.split(r"(?<=[.!?])\s", d, 1)[0][:110]
            rows.append(f"{n} — {d}")
        _CACHE["index"] = "Остальные инструменты (зови через use_tool):\n" + "\n".join(rows)
    return _CACHE["index"]


def reset():
    _CACHE.update(core=None, all=None, index="")


def policy(name: str, user_text: str) -> str:
    """Пусто — можно. Иначе — текст отказа, который вернётся МОДЕЛИ
    (она сама скажет человеку словами и спросит подтверждение)."""
    if name in DENY:
        return f"отказ: {name} недоступен из разговора."
    if name in CONFIRM and not _YES.search(user_text or ""):
        return (f"нужно подтверждение: {name} меняет что-то необратимо. "
                "Ничего не сделано. Спроси Виталю прямо одной фразой; "
                "выполнишь после его «да».")
    if name not in _all() and name not in ("use_tool", "tool_help", "calc"):
        return f"нет такого инструмента: {name}. Посмотри указатель."
    return ""


def execute(name: str, args: dict, user_text: str, timeout: float = 60.0) -> str:
    """Исполнить вызов модели. Возвращает текст результата для модели."""
    import threading
    if name == "tool_help":
        s = _all().get(str(args.get("name", "")))
        return json.dumps(s["function"], ensure_ascii=False) if s else "нет такого"
    if name == "use_tool":
        name = str(args.get("name", "")).strip()
        args = args.get("args") or {}
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except Exception:
                args = {}
    if name == "calc":
        return _calc(str(args.get("expr", "")))
    # ПОИСК — НЕ В ГУГЛ, ЕСЛИ ЧЕЛОВЕК ЕГО НЕ НАЗВАЛ (2026-10-09, скрин: Google
    # выдал капчу «подозрительный трафик» на автоматический запрос). Яндекс
    # с этого IP отвечает без капчи; Google — только по прямой просьбе.
    if name == "web_open" and str(args.get("site", "")).lower() in ("google", "гугл", "google.com") \
            and not re.search(r"гугл|google", user_text or "", re.I):
        args = dict(args, site="яндекс")
    why = policy(name, user_text)
    if why:
        log.info("ядро v2: %s остановлен политикой: %s", name, why[:80])
        return why
    if name in ("look_screen", "look_camera"):
        # глаза — тем же движком (Qwen3.6 + mmproj), без второй модели
        from anamorf.core import eyes
        return eyes.look("camera" if name == "look_camera" else "screen",
                         str(args.get("question", "") or ""), args.get("monitor"))
    from anamorf.llm import tools as _t
    _t.LAST_USER["text"] = user_text
    _t.LAST_USER["core_v2"] = True
    box = {}

    def run():
        try:
            box["r"] = str(_t.call(name, args) or "")
        except Exception as e:
            box["r"] = f"ошибка: {e}"
    from anamorf.core import attention
    attention.before(name, args)            # рамка: куда она идёт
    th = threading.Thread(target=run, daemon=True, name=f"tool-{name}")
    th.start()
    th.join(timeout)
    if th.is_alive():
        return f"инструмент {name} не ответил за {int(timeout)} с — брошен, ничего не подтверждено"
    res = box.get("r", "") or "(пустой результат)"
    attention.after(name, args, res)        # рамка: что получилось
    # КАПЧА — ДЕЛО ЧЕЛОВЕКА. Обходить защиту сайтов от роботов мы не будем:
    # это ровно то, от чего сайт защищается, и прямая дорога к бану IP.
    # Профессиональный путь — не вызывать её (меньше автоматических запросов
    # к поисковикам, Яндекс вместо Google, прямые адреса вроде
    # youtube.com/results), а если всё же выскочила — честно позвать человека
    # и не долбить сайт повторами.
    if _CAPTCHA.search(res) or _captcha_on_screen():
        log.info("ядро v2: капча после %s — зову человека", name)
        return ("КАПЧА: сайт просит подтвердить, что запрос делает человек. "
                "Не обходи и не повторяй запрос. Скажи Виталию одной фразой, "
                "что нужна его галочка в браузере, и предложи другой путь "
                "(Яндекс или прямой адрес).")
    return res


_CAPTCHA = re.compile(r"google\.com/sorry|recaptcha|я не робот|i'?m not a robot|"
                      r"подозрительный трафик|unusual traffic|captcha", re.I)


def _captcha_on_screen() -> bool:
    try:
        import ctypes
        h = ctypes.windll.user32.GetForegroundWindow()
        n = ctypes.windll.user32.GetWindowTextLengthW(h)
        b = ctypes.create_unicode_buffer(n + 1)
        ctypes.windll.user32.GetWindowTextW(h, b, n + 1)
        return bool(re.search(r"google\.com/sorry|captcha|подтвердите", b.value, re.I))
    except Exception:
        return False
