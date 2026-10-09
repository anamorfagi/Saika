# -*- coding: utf-8 -*-
"""ЧТО РЕАЛЬНО ЛЕЖИТ В ВИДЕОПАМЯТИ (06.09.2026).

Владелец жмёт «выгрузить» и не видит эффекта. Разговоры про логи тут
бесполезны — нужен прямой ответ: сколько занято, какими процессами, и
жив ли llama-server. Спрашиваем у драйвера, а не у своего кода.
"""
import subprocess, sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))

def sh(cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=20).stdout.strip()
    except Exception as e:
        return "нет: %r" % e

print("== всего/занято, МБ ==")
print(sh(["nvidia-smi", "--query-gpu=memory.total,memory.used", "--format=csv,noheader"]))
print("== кто занимает ==")
print(sh(["nvidia-smi", "--query-compute-apps=pid,used_memory,process_name", "--format=csv,noheader"]) or "никто")
print("== жив ли llama-server ==")
try:
    from anamorf.llm import llamacpp
    p = getattr(llamacpp, "_proc", None)
    print("_proc:", "нет" if p is None else ("жив" if p.poll() is None else "мёртв"))
    print("health:", "отвечает" if llamacpp._health() else "не отвечает")
except Exception as e:
    print("не спросить:", repr(e))
print("== что думает менеджер ==")
try:
    from anamorf.llm import manager as M
    print("loaded_models():", M.loaded_models())
except Exception as e:
    print("не спросить:", repr(e))
