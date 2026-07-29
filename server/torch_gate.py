"""ОДИН ЗАМОК НА ВСЕ ТЯЖЁЛЫЕ ЛЕНИВЫЕ ЗАГРУЗКИ (2026-07-28).

ПОВОД — живой лог владельца: «faster_whisper упал: Tried to register an
operator (_dtensor::mesh_get_process_group) ... multiple times». Это не
поломка движка, это ГОНКА: в один момент времени три потока лениво
поднимали торчёвые модели — сменился STT-движок, упал и перезагружался
TTS, а слой нормализации впервые позвал silero_te. Параллельный импорт
внутренностей torch иногда регистрирует операторы дважды — и валится тот,
кто пришёл вторым, причём с ошибкой, по которой ни за что не догадаешься
о причине.

Загрузка модели и так занимает секунды — очередь из загрузок ничего не
замедляет заметно. Зато убирает целый класс «упал с незнакомой ошибкой
при смене движка». Пользоваться так:

    from server.torch_gate import TORCH_GATE
    with TORCH_GATE:
        import torch; ...  # любая ленивая загрузка тяжёлой модели

Замок нужен только на ЗАГРУЗКУ. Инференс уже загруженных моделей друг
другу не мешает и сюда не ходит.
"""
import threading

TORCH_GATE = threading.RLock()


def defuse_speechbrain():
    """Обезвредить ленивые модули speechbrain. Зовётся ОТКУДА УГОДНО и сколько
    угодно раз — идемпотентно.

    ПОВОД (2026-07-29, третий заход по одной болячке). Защита жила в прогреве
    отпечатка голоса, и в логе владельца стало видно, почему этого мало:

        18:50:26,846  qwen3 упал: Lazy import of k2_fsa failed
        18:50:27,043  обезврежено ленивых модулей speechbrain: 56

    Двести миллисекунд. Автопуск озвучки успевал раньше прогрева голосов —
    и лечение опаздывало ровно к моменту, когда было нужно. Привязывать
    защиту к порядку запуска подсистем нельзя: порядок меняется от машины к
    машине и от настроек. Поэтому теперь это отдельная функция, и её зовёт
    КАЖДЫЙ, кто собирается тревожить torch.

    Два слоя, потому что одного мало:
      1. заменяем ленивые атрибуты пустышками — лечит то, что уже создано;
      2. смягчаем сам КЛАСС ленивого модуля: неудачный импорт отвечает
         «атрибута нет» вместо взрыва — лечит то, что родится потом.
    """
    import sys
    import types
    n = 0
    cls = None          # класс ленивого модуля ловим ПО ХОДУ первого прохода
    try:
        for pkg in [m for nm, m in list(sys.modules.items())
                    if nm.startswith("speechbrain")
                    and isinstance(m, types.ModuleType)]:
            for k, v in list(vars(pkg).items()):
                if type(v).__name__ != "LazyModule":
                    continue
                # ГРАБЛИ, ПОЙМАННЫЕ СТЕНДОМ 2026-07-29: класс искался ВТОРЫМ
                # проходом — а к тому времени все экземпляры уже заменены
                # пустышками, и искать нечего. Класс не смягчался, мина,
                # рождённая позже, снова взрывалась. Запоминаем здесь.
                if cls is None:
                    cls = type(v)
                full = str(getattr(v, "target", None) or f"{pkg.__name__}.{k}")
                stub = types.ModuleType(full)
                stub.__file__ = "<lazy-disabled-by-saika>"
                try:
                    setattr(pkg, k, stub)
                except Exception:
                    pass
                # ТОЛЬКО имена внутри speechbrain: под чужими именами лежат
                # настоящие пакеты (однажды так подменили tokenizers, и
                # свалились и qwen3, и faster-whisper)
                if full.startswith("speechbrain"):
                    sys.modules.setdefault(full, stub)
                n += 1
    except Exception:
        pass
    try:
        if cls is None:
            from speechbrain.utils.importutils import LazyModule as cls
        if not getattr(cls, "_saika_soft", False):
            orig = cls.__getattr__

            def soft(self, name, __o=orig):
                try:
                    return __o(self, name)
                except AttributeError:
                    raise
                except BaseException as e:
                    raise AttributeError(name) from e

            cls.__getattr__ = soft
            cls._saika_soft = True
            n += 1000000        # признак «класс смягчён» для лога
    except Exception:
        pass
    return n
