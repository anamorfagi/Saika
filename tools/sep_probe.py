import importlib, sys
for m in ("speechbrain","asteroid","torchaudio","huggingface_hub"):
    try:
        mod=importlib.import_module(m); print(m, getattr(mod,"__version__","?"))
    except Exception as e: print(m, "NO", repr(e)[:80])
from pathlib import Path
hub=Path(r"C:\AI\Saika\models\hf\hub")
print([p.name for p in hub.glob("models--*")][:40])
