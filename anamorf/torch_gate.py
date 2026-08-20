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

    from anamorf.torch_gate import TORCH_GATE
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
    # НИЧЕГО НЕ ИМПОРТИРУЕМ (2026-08-14, четвёртый заход по той же болячке).
    # Живой лог владельца:
    #     Отпечаток голоса: ECAPA недоступна (partially initialized module
    #     'speechbrain' has no attribute 'utils')
    # Виновата была ЭТА функция. Её зовёт и озвучка, и отпечаток голоса —
    # и когда speechbrain ещё не загружен, она сама лезла за классом
    # ленивого модуля («from speechbrain.utils.importutils import …»),
    # то есть НАЧИНАЛА импорт speechbrain из чужого потока. Второй поток в
    # это время делал свой импорт и видел полусобранный пакет. Лечение
    # запускало болезнь. Правило теперь железное: нечего обезвреживать —
    # молча выходим. Мины появятся вместе с пакетом, и нас позовут снова.
    if "speechbrain" not in sys.modules:
        return 0
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
                # СВОИ ЛЕНИВЫЕ МОДУЛИ НЕ ТРОГАЕМ (2026-08-14). Раньше под
                # раздачу попадал и speechbrain.utils — настоящая, нужная
                # часть пакета, которую он подгружает лениво. Заглушка
                # вместо неё и давала «has no attribute 'utils'». Мины,
                # ради которых всё затевалось, лежат СНАРУЖИ: k2_fsa,
                # kenlm, ctc_segmentation — необязательные тяжёлые чужаки,
                # которых на машине нет. Их и глушим.
                if full.startswith("speechbrain"):
                    continue
                stub = types.ModuleType(full)
                stub.__file__ = "<lazy-disabled-by-saika>"
                try:
                    setattr(pkg, k, stub)
                except Exception:
                    pass
                # в sys.modules НЕ пишем совсем: под этими именами могут
                # лежать настоящие пакеты (однажды так подменили tokenizers,
                # и свалились и qwen3, и faster-whisper). Подмены атрибута
                # достаточно — обращение идёт через пакет.
                n += 1
    except Exception:
        pass
    try:
        if cls is None:
            # класс берём ТОЛЬКО из уже живущего модуля — импортом его
            # доставать нельзя, см. выше
            _iu = sys.modules.get("speechbrain.utils.importutils")
            cls = getattr(_iu, "LazyModule", None) if _iu else None
        if cls is not None and not getattr(cls, "_saika_soft", False):
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


# ═══════ FLASH-ATTENTION ОТ ЧУЖОГО TORCH (2026-08-14) ═══════
# Живой случай: при старте Windows выкинула МОДАЛЬНОЕ окно
#
#   python.exe — Точка входа не найдена
#   Точка входа в процедуру ??0MessageLogger@c10@@QEAA@PEBDHH_N@Z не найдена
#   в библиотеке DLL …\site-packages\flash_attn_2_cuda.cp312-win_amd64.pyd
#
# и запуск встал, пока человек не нажмёт «ОК». Причина видна в именах папок:
# flash_attn-2.8.3+cu130 **torch2.10**, а стоит torch 2.13.0+cu130. Символ
# MessageLogger живёт в c10.dll и между версиями меняет сигнатуру — бинарник
# просто не той сборки.
#
# Лечить установкой «правильного» flash-attn нельзя автоматически: это
# гигабайтная рулетка версий на каждое обновление torch. А без него ничего
# не теряется — transformers сам берёт SDPA, встроенное внимание самого
# PyTorch, оно почти такое же быстрое и всегда совместимо.
#
# Поэтому: перед любой тяжёлой загрузкой сверяем, под какой torch собран
# flash_attn, и если не под наш — делаем его НЕИМПОРТИРУЕМЫМ заранее.
# Тогда transformers получит честный ImportError вместо окна от загрузчика
# Windows, которое некому нажать, когда человек лежит на диване.
import logging as _logging
import re as _re
import sys as _sys

_log_fa = _logging.getLogger("saika.flashattn")
_fa_checked = {"done": False}


def _flash_attn_built_for() -> str:
    """Под какой torch собран установленный flash_attn ('' — не найден)."""
    try:
        from importlib import metadata
        v = metadata.version("flash_attn")
    except Exception:
        return ""
    m = _re.search(r"torch(\d+\.\d+)", v or "")
    return m.group(1) if m else ""


def _quarantine_binary() -> str:
    """Увести несовместимый бинарник flash_attn с глаз долой.

    2026-08-14, ВТОРОЙ ЗАХОД. Первая версия вешала заглушку в sys.meta_path
    и бросала ImportError на любое упоминание flash_attn. Красиво и
    неправильно: transformers щупает наличие flash_attn и когда грузит
    модель через sdpa, — исключение прилетало и туда, и падали ОБЕ попытки.
    Живое последствие: у Сайки перестал грузиться собственный голос
    (qwen3-TTS), хотя в коде честно написано ["flash_attention_2", "sdpa"].

    Правильный отказ — не «взрывается при упоминании», а «пакет не собран».
    Такой умеют обрабатывать все библиотеки, потому что он штатный. Поэтому
    просто переименовываем .pyd: импорт падает внутри самого flash_attn,
    ровно как при неудачной сборке, и запасной путь срабатывает сам.
    Обратимо: файл лежит рядом с пометкой, под какой torch он собран."""
    import glob
    import os
    out = ""
    for pat in ("flash_attn_2_cuda*.pyd", "flash_attn_2_cuda*.so"):
        for site in _sys.path:
            for f in glob.glob(os.path.join(site, pat)):
                try:
                    os.rename(f, f + ".disabled-wrong-torch")
                    out = f
                    _log_fa.warning(
                        "Убрала несовместимый %s — он собран под другой "
                        "PyTorch и роняет Windows окном «Точка входа не "
                        "найдена». Вернуть: убрать суффикс "
                        "«.disabled-wrong-torch» из имени файла.",
                        os.path.basename(f))
                except Exception as e:
                    _log_fa.debug("не смогла убрать %s: %s", f, e)
    return out


def defuse_flash_attn():
    """Отключить несовместимый flash_attn. Идемпотентно, зовётся откуда угодно."""
    if _fa_checked["done"]:
        return
    _fa_checked["done"] = True
    built = _flash_attn_built_for()
    if not built:
        return                        # не установлен — и хорошо
    # ВЕРСИЮ TORCH БЕРЁМ ИЗ МЕТАДАННЫХ, А НЕ ИМПОРТОМ (2026-08-14, живая
    # регрессия). Первая версия делала здесь `import torch`, и поскольку
    # эта проверка живёт в anamorf/__init__.py, torch поднимался РАНЬШЕ
    # всего остального — до speechbrain и его ленивых модулей. Результат в
    # логе владельца: «partially initialized module 'speechbrain' has no
    # attribute 'utils' (circular import)», отпечаток голоса свалился на
    # лёгкие признаки. Порядок импорта тяжёлых пакетов трогать нельзя —
    # ради него и написан весь этот файл. Метаданные лежат на диске, читать
    # их можно без единого импорта.
    try:
        from importlib import metadata
        have = ".".join(metadata.version("torch").split("+")[0].split(".")[:2])
    except Exception:
        return                        # нет torch — нечего и сверять
    if built == have:
        return                        # версии сошлись, пусть работает
    _log_fa.warning(
        "flash_attn собран под torch %s, а стоит %s — убираю его бинарник, "
        "чтобы Windows не выбрасывала окно «Точка входа не найдена». "
        "Внимание будет считаться штатным SDPA: качество то же, скорость "
        "чуть ниже, зато ничего не падает.", built, have)
    _quarantine_binary()
