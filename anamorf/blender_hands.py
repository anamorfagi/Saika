"""РУКИ В БЛЕНДЕРЕ: тот же канал, которым пользуюсь я (05.09.2026).

Владелец: «я в блендере сижу, начинаю моделить, прошу закинуть реф на
задний фон — она параллельно мне в блендер закидывает реф под мою сетку…
такая совместная фул-работа». И на прямой вопрос про канал ответил:
через BlenderMCP — тот аддон, что у него уже стоит и через который с
Блендером работаю я.

═══ ПОЧЕМУ ИМЕННО ЭТОТ ПУТЬ, А НЕ КЛИКИ ПО ИНТЕРФЕЙСУ ═══

У неё есть три способа дотянуться до чужой программы, и они различаются
не удобством, а НАДЁЖНОСТЬЮ:

  1. Разговор с самой программой (здесь — сокет аддона). Она отвечает
     фактами: «объект создан», «файл сохранён сюда». Не зависит от того,
     где окно, какая тема оформления и не перекрыл ли его браузер.
  2. Горячие клавиши и меню. Работает, пока окно впереди и раскладка
     ожидаемая; ломается молча.
  3. Смотреть на экран и кликать. Последнее средство: медленно, зависит
     от разрешения и темы, и промах не всегда заметен.

Правило простое: если у программы есть первый способ — пользуемся только
им. Клики — там, где разговаривать не с кем.

═══ ГЛАВНОЕ ПРАВИЛО РАБОТЫ В ЧУЖОЙ СЦЕНЕ ═══

Он в этой сцене РАБОТАЕТ. Значит: ничего не удаляем, ничего не двигаем из
того, что не создавали сами, не трогаем выделение и активный объект
дольше, чем нужно, и всё своё называем с приставкой, чтобы он одним
взглядом видел, что тут её, а что его. Реф под сетку — это добавить
объект, а не переставить его мир.
"""
import json
import logging
import socket
import time
from pathlib import Path

from anamorf.config import CFG

log = logging.getLogger("saika.blender")

PREFIX = "Сайка_"          # всё, что она создаёт, помечено


def _addr():
    return (str(CFG.get("blender.host", "127.0.0.1")),
            int(CFG.get("blender.port", 9876)))


def _send(kind: str, params: dict = None, timeout: float = 20.0) -> dict:
    """Один запрос к аддону. Соединение НЕ держим: аддон однопоточный, и
    висящий сокет мешает и ему, и мне, когда я работаю в той же сцене."""
    host, port = _addr()
    msg = json.dumps({"type": kind, "params": params or {}}).encode("utf-8")
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect((host, port))
        s.sendall(msg)
        buf = b""
        while True:
            chunk = s.recv(65536)
            if not chunk:
                break
            buf += chunk
            try:
                return json.loads(buf.decode("utf-8", "replace"))
            except Exception:
                continue          # ответ ещё не целиком
        raise ConnectionError("аддон закрыл соединение, не ответив")
    finally:
        try:
            s.close()
        except Exception:
            pass


def alive() -> bool:
    try:
        r = _send("get_scene_info", {}, timeout=6.0)
        return str(r.get("status")) == "success"
    except Exception:
        return False


def run(code: str, timeout: float = 30.0) -> str:
    """Выполнить питон внутри Блендера. Возвращает человеческий текст."""
    try:
        r = _send("execute_code", {"code": code}, timeout=timeout)
    except Exception as e:
        return ("Блендер не отвечает (%s). Открыт ли он и включён ли аддон "
                "BlenderMCP — в нём кнопка «Connect»." % e)
    if str(r.get("status")) != "success":
        return "Блендер ответил ошибкой: %s" % str(
            r.get("message") or r.get("result"))[:300]
    res = r.get("result")
    if isinstance(res, dict):
        res = res.get("result", res)
    return str(res or "готово")[:1500]


def scene() -> str:
    try:
        r = _send("get_scene_info", {}, timeout=8.0)
    except Exception as e:
        return "Блендер не отвечает (%s)." % e
    return json.dumps(r.get("result", r), ensure_ascii=False)[:1200]


def new_project(path: str, name: str = "") -> str:
    """Новый файл и СРАЗУ сохранить его в папку проекта.

    Сохраняем сразу намеренно: несохранённый блендер — это файл, который
    живёт только в оперативке, и первый же вылет уносит работу. Плюс
    только у сохранённого файла есть папка, относительно которой можно
    складывать текстуры и экспорт."""
    p = Path(path)
    if p.is_dir():
        p = p / ((name or "сцена").strip() + ".blend")
    if p.suffix.lower() != ".blend":
        p = p.with_suffix(".blend")
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        return "не смогла создать папку %s: %s" % (p.parent, e)
    code = (
        "import bpy, json\n"
        "bpy.ops.wm.read_homefile(use_empty=False)\n"
        "bpy.ops.wm.save_as_mainfile(filepath=r%r)\n"
        "print(json.dumps({'saved': bpy.data.filepath}))\n" % str(p))
    out = run(code, timeout=60.0)
    if p.exists():
        return "Новый файл создан и сохранён: %s" % p
    return "Похоже, не сохранилось. Блендер сказал: %s" % out


def save_as(path: str) -> str:
    p = Path(path)
    if p.suffix.lower() != ".blend":
        p = p.with_suffix(".blend")
    out = run("import bpy\nbpy.ops.wm.save_as_mainfile(filepath=r%r)\n"
              % str(p), timeout=60.0)
    return ("Сохранила: %s" % p) if p.exists() else out


def ref_background(image: str, axis: str = "front", behind: bool = True,
                   height: float = 2.0) -> str:
    """ПОЛОЖИТЬ РЕФЕРЕНС ПОД СЕТКУ.

    Делается пустышкой типа IMAGE, а не плоскостью с материалом: пустышка
    не участвует в рендере, не мешает выделению рамкой и не попадает в
    экспорт. Ровно то, чем пользуются моделлеры, когда обводят реф.

    Ставим ЗА сцену по глубине и снимаем выделение обратно на его объект:
    он в этот момент моделит, и увести у него активный объект — значит
    сломать ему следующее действие."""
    img = Path(image)
    if not img.exists():
        return "Файла нет: %s" % img
    rot = {"front": "(1.5708, 0, 0)", "side": "(1.5708, 0, 1.5708)",
           "top": "(0, 0, 0)", "back": "(1.5708, 0, 3.14159)"}.get(
               (axis or "front").lower(), "(1.5708, 0, 0)")
    off = "-3.0" if behind else "0.0"
    code = f'''
import bpy, os
prev = bpy.context.view_layer.objects.active
sel = [o for o in bpy.context.selected_objects]
img = bpy.data.images.load(r{str(img)!r}, check_existing=True)
e = bpy.data.objects.new("{PREFIX}реф_" + os.path.splitext(img.name)[0][:24], None)
e.empty_display_type = 'IMAGE'
e.data = img
e.empty_display_size = {height}
e.rotation_euler = {rot}
e.location = (0.0, {off}, {height} / 2.0)
e.show_in_front = False
e.hide_select = True          # чтобы не хватал его мышью во время работы
bpy.context.scene.collection.objects.link(e)
# вернуть человеку его выделение — он в этот момент моделит
for o in bpy.context.selected_objects:
    o.select_set(False)
for o in sel:
    try:
        o.select_set(True)
    except Exception:
        pass
bpy.context.view_layer.objects.active = prev
print("ok:" + e.name)
'''
    out = run(code, timeout=45.0)
    if "ok:" in out:
        return ("Реф на месте, стоит за сеткой и не хватается мышью "
                "(%s)." % img.name)
    return out


def status() -> dict:
    return {"alive": alive(), "host": _addr()[0], "port": _addr()[1],
            "ts": time.time()}
