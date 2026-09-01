# -*- coding: utf-8 -*-
import sys, os, traceback
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np
from anamorf.voiceprint.tracks import Tracks, _cfg
print("link_cos ->", repr(_cfg("link_cos", 0.45)), type(_cfg("link_cos", 0.45)))
print("min_s    ->", repr(_cfg("min_s", 0.6)))
print("rho_s    ->", repr(_cfg("rho_s", 0.8)))
print("confirm  ->", repr(_cfg("confirm_s", 3.0)))
t = Tracks(to_registry=False, tag="проба")
rng = np.random.default_rng(0)
a = rng.normal(size=192).astype(np.float32); a /= np.linalg.norm(a)
b = rng.normal(size=192).astype(np.float32); b /= np.linalg.norm(b)
for i, v in enumerate([a, a*0.9+b*0.1, b, b*0.95+a*0.05, a]):
    v = v / np.linalg.norm(v)
    try:
        print(i, t.observe(v, 4.0))
    except Exception:
        traceback.print_exc(); break
print("кластеров:", len(t.clusters), "stat:", t.stat)
