import sys, json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT))
import requests
g = requests.get("http://127.0.0.1:8765/api/sys", timeout=10).json().get("gpu") or {}
gb = lambda b: round((b or 0)/2**30, 2)
print("на карте физически занято %.2f из %.2f ГБ; застолблено всеми (как в диспетчере) %.2f ГБ; сама Сайка держит %.2f ГБ"
      % (gb(g.get("vram_used")), gb(g.get("vram_total")), gb(g.get("vram_committed")), gb(g.get("vram_ours"))))
