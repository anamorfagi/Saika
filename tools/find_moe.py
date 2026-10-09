# -*- coding: utf-8 -*-
"""Найти скачанную MoE-модель и показать её паспорт (05.09.2026)."""
import io, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
O = []
def say(*a): O.append(" ".join(str(x) for x in a))
try:
    from anamorf.llm import llamacpp
    from anamorf import gguf_meta, vramplan
    roots = [ROOT / "models" / "gguf", ROOT / "models" / "llm"]
    try:
        roots += [Path(r) for r in llamacpp._lmstudio_roots()]
    except Exception as e:
        say("каталоги LM Studio не нашлись:", e)
    seen = []
    for r in roots:
        try:
            if not Path(r).exists():
                continue
            for f in Path(r).rglob("*.gguf"):
                gb = f.stat().st_size / (1 << 30)
                if gb < 1.0:
                    continue
                seen.append((gb, str(f)))
        except Exception:
            pass
    seen.sort(reverse=True)
    say("НАЙДЕНО МОДЕЛЕЙ:", len(seen))
    for gb, f in seen[:15]:
        say("  %6.1f ГБ  %s" % (gb, f))
    say("")
    say("сейчас выбрана:", llamacpp.find_model())
    # паспорт самой крупной — скорее всего это она и есть
    for gb, f in seen[:4]:
        if gb < 8:
            continue
        try:
            m = gguf_meta.read(f)
            say("")
            say("--- " + Path(f).name)
            say(gguf_meta.describe(m))
            if m.get("n_expert"):
                for c in (32768, 65536, 122880):
                    say("   KV q8_0 окно %-7d = %.2f ГБ" % (c, gguf_meta.kv_gb(m, c, "q8_0")))
        except Exception as e:
            say("паспорт %s не прочитался: %r" % (Path(f).name, e))
except Exception:
    import traceback; say(traceback.format_exc())
io.open(ROOT / "data" / "find_moe.txt", "w", encoding="utf-8").write("\n".join(O))
