"""ПАМЯТЬ ОКНА ОТДЕЛЬНО ДЛЯ КАЖДОЙ МОДЕЛИ (2026-08-14).

Владелец: «добавь запоминание размера окна, положения модельки — как в
прошлый раз оно было запущено, также для всех моделей».

Первая половина уже работала: окно писало x/y/w/h в конфиг, а страница —
масштаб и поворот. Но всё это лежало ОДНОЙ кучей на avatar.desk, поэтому
библиотека аватаров ломала настройку: у высокой модели своя рамка, у
чиби — своя, у 2D-спрайта третья. Человек переодевал аватар и каждый раз
заново подгонял окно, потому что новая модель приходила в чужие размеры.

Теперь на avatar.desk есть slots: {ключ модели: {x,y,w,h,view}}. Старые
поля НИКУДА НЕ ДЕЛИСЬ и продолжают писаться — это «как было в прошлый
раз вообще», запасной вариант для модели, которую ещё ни разу не ставили
(и заодно то, что читает любой старый код, ничего не зная про слоты).

Модуль намеренно голый: ни одного импорта из server. Его читает и
tools/desk_avatar.py — отдельный процесс окна, которому пакет server
поднимать незачем и опасно (там торч, голоса, полминуты запуска)."""

GEOM = ("x", "y", "w", "h")
_EXT = (".vrm", ".glb", ".gltf", ".png", ".webp", ".gif", ".jpg", ".jpeg")


def key_of(model) -> str:
    """Ключ модели — её имя без папок и расширения.

    Именно имя, а не полный путь: файл переносят из library в outfits и
    обратно, и терять из-за этого настроенное окно человек не подписывался."""
    s = str(model or "").replace("\\", "/").strip().lower().rstrip("/")
    s = s.rsplit("/", 1)[-1]
    for e in _EXT:
        if s.endswith(e):
            s = s[:-len(e)]
            break
    return s or "default"


def slot_of(desk: dict, key: str) -> dict:
    d = (desk or {}).get("slots") or {}
    v = d.get(key)
    return dict(v) if isinstance(v, dict) else {}


def geom_for(desk: dict, key: str) -> dict:
    """Где и какого размера окно у ЭТОЙ модели.

    Нет своего — берём общее последнее: пусть новая модель встанет туда
    же, где стояла прошлая, а не в угол по умолчанию."""
    s, out = slot_of(desk, key), {}
    for k in GEOM:
        v = s.get(k, (desk or {}).get(k))
        if v is not None:
            try:
                out[k] = int(v)
            except (TypeError, ValueError):
                pass
    return out


def view_for(desk: dict, key: str):
    """Как модель стояла ВНУТРИ окна: масштаб, смещение, поворот."""
    v = slot_of(desk, key).get("view")
    if isinstance(v, dict) and v:
        return v
    return (desk or {}).get("view") or None


def remember(desk: dict, key: str, geom: dict = None, view: dict = None) -> dict:
    """Записать в слот модели И в общий «последний» слой. Меняет desk на месте."""
    slot = (desk.setdefault("slots", {})).setdefault(key, {})
    if geom:
        for k in GEOM:
            if geom.get(k) is None:
                continue
            try:
                desk[k] = slot[k] = int(geom[k])
            except (TypeError, ValueError):
                pass
    if isinstance(view, dict) and view:
        desk["view"] = slot["view"] = view
    return desk


def forget(desk: dict, key: str) -> bool:
    """Забыть настройку одной модели — общая при этом остаётся."""
    return (desk.get("slots") or {}).pop(key, None) is not None
