# -*- coding: utf-8 -*-
"""Проверка системной петли в НАСТОЯЩЕМ окружении программы."""
import sys, traceback
print("python:", sys.executable)
try:
    import pycparser
    print("pycparser:", pycparser.__version__, pycparser.__file__)
    from pycparser import c_ast, ast_transforms
    print("  c_ast и ast_transforms импортируются")
except Exception:
    print("pycparser СЛОМАН:"); traceback.print_exc()
try:
    import cffi; print("cffi:", cffi.__version__)
except Exception:
    print("cffi СЛОМАН:"); traceback.print_exc()
try:
    import soundcard as sc
    print("soundcard: ок")
    ls=[m for m in sc.all_microphones(include_loopback=True)
        if getattr(m,'isloopback',False)]
    print("петель найдено:", len(ls))
    import numpy as np
    for m in ls:
        try:
            with m.recorder(samplerate=16000, channels=1, blocksize=1600) as r:
                a=r.record(numframes=4000)
            x=np.asarray(a,dtype=np.float32).ravel()
            rms=float(np.sqrt(np.mean(x*x))+1e-12)
            db=20*np.log10(rms) if rms>1e-9 else -120
            print("   %-45s %6.1f дБ" % (m.name[:45], db))
        except Exception as e:
            print("   %-45s НЕ ОТДАЁТ: %s" % (m.name[:45], str(e)[:60]))
except Exception:
    print("soundcard СЛОМАН:"); traceback.print_exc()
