# -*- coding: utf-8 -*-
"""Скачать и прогреть ReDimNet2 (замена ECAPA, 2026-08-31).

Зачем отдельным скриптом: первая загрузка через torch.hub тянет код репо и
веса с GitHub — это десятки секунд, и делать это внутри живого слуха значит
подвесить его. Гоняем ЗАРАНЕЕ: веса ложатся в models/torch/hub, дальше
прога поднимает модель за доли секунды. Заодно проверяем, что модель
вообще работает в этом venv, и меряем цену одного эмбеддинга — ДО того,
как её увидит живой конвейер.

Запуск: .venv\\Scripts\\python.exe tools\\get_redimnet2.py [b3] [lm]
"""
import os, sys, time, pathlib
ROOT = pathlib.Path(__file__).resolve().parent.parent
size = sys.argv[1] if len(sys.argv) > 1 else "b3"
ttype = sys.argv[2] if len(sys.argv) > 2 else "lm"
hub = ROOT / "models" / "torch" / "hub"
hub.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("TORCH_HOME", str(ROOT / "models" / "torch"))
import torch, numpy as np
torch.hub.set_dir(str(hub))
print("torch", torch.__version__, "cuda:", torch.cuda.is_available())
t0 = time.time()
kw = dict(model_name=size, train_type=ttype, pretrained=True, trust_repo=True)
try:
    m = torch.hub.load("PalabraAI/redimnet2", "redimnet2", **kw)
except TypeError:
    kw.pop("trust_repo"); m = torch.hub.load("PalabraAI/redimnet2", "redimnet2", **kw)
print("загрузка: %.1fс" % (time.time() - t0))
dev = "cuda" if torch.cuda.is_available() else "cpu"
m = m.eval().to(dev)
n = sum(p.numel() for p in m.parameters())
print("параметров: %.1fM, устройство: %s" % (n / 1e6, dev))
sr = 16000
for sec in (1.0, 2.0, 3.0, 8.0):
    x = torch.randn(1, int(sr * sec)).to(dev)
    with torch.no_grad():
        m(x)                                   # прогрев
        if dev == "cuda": torch.cuda.synchronize()
        t1 = time.time()
        for _ in range(5):
            e = m(x)
        if dev == "cuda": torch.cuda.synchronize()
    ms = (time.time() - t1) / 5 * 1000
    print("  %.0fс звука -> эмбеддинг %s за %.1f мс" % (sec, tuple(e.shape), ms))
# та же речь дважды -> косинус ~1; разный шум -> низкий
a = torch.randn(1, sr * 3).to(dev); b = torch.randn(1, sr * 3).to(dev)
with torch.no_grad():
    ea = torch.nn.functional.normalize(m(a), dim=-1)
    eb = torch.nn.functional.normalize(m(b), dim=-1)
    ea2 = torch.nn.functional.normalize(m(a * 0.7), dim=-1)
print("косинус: тот же кусок тише=%.3f, чужой шум=%.3f" %
      (float((ea * ea2).sum()), float((ea * eb).sum())))
print("OK: веса в", hub)
