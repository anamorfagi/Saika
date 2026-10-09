# -*- coding: utf-8 -*-
"""Сколько видеопамяти держит САМА Сайка и что именно (06.09.2026).

Диспетчер задач показывает 12.9 из 16 ГБ занятыми, а nvidia-smi на
Windows не умеет разложить память по процессам (WDDM отдаёт [N/A]).
Значит спрашиваем изнутри: torch знает, сколько выделил он сам, и какие
модели сейчас в наших руках. Разница между «занято на карте» и «держим
мы» — и есть ответ, кому там мешать.
"""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
gb = lambda b: round(b / (1024 ** 3), 2)
try:
    import torch
    if torch.cuda.is_available():
        free, total = torch.cuda.mem_get_info()
        print("карта: всего %.2f ГБ, свободно %.2f ГБ, занято всеми %.2f ГБ"
              % (gb(total), gb(free), gb(total - free)))
        print("держит НАШ процесс: выделено %.2f ГБ, зарезервировано %.2f ГБ"
              % (gb(torch.cuda.memory_allocated()), gb(torch.cuda.memory_reserved())))
    else:
        print("cuda недоступна")
except Exception as e:
    print("torch не спросить:", repr(e))
try:
    from anamorf import tts
    m = getattr(tts, "MANAGER", None) or getattr(tts, "manager", None)
    eng = getattr(m, "engine", None) if m else None
    print("озвучка: движок", type(eng).__name__ if eng else "нет",
          "| модель в памяти:", bool(getattr(eng, "model", None)))
except Exception as e:
    print("озвучку не спросить:", repr(e))
try:
    from anamorf import voiceprint as vp
    print("отпечаток голоса: устройство", vp.S.device if hasattr(vp, "S") else "?")
except Exception as e:
    pass
