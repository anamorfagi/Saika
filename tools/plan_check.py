# -*- coding: utf-8 -*-
"""Проверка нового плана памяти на живом железе (05.09.2026).

Ничего не меняет. Читает паспорт текущей модели, считает, какое окно и
какой раскрой MoE влезли бы, и печатает числа. Нужен, чтобы не спорить
о гигабайтах на словах."""
import io
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
# Пишем в файл, а не в stdout: канал runpy забирает stdout процесса, но
# подмена sys.stdout в дочернем процессе до него не доезжает — в прошлый
# раз отчёт вышел пустым при RC=0.
_OUT = []


def print(*a, **k):
    _OUT.append(" ".join(str(x) for x in a))


def _dump():
    io.open(Path(__file__).resolve().parents[1] / "data" / "plan_report.txt",
            "w", encoding="utf-8").write("\n".join(_OUT))


def main():
    from anamorf.config import CFG
    from anamorf import vramplan, gguf_meta
    from anamorf.llm import llamacpp

    print("=== ЖЕЛЕЗО ===")
    print("VRAM доступно заказу: %.1f ГБ" % vramplan.total_gb())
    print("ОЗУ свободно:        %.1f ГБ" % vramplan.ram_free_gb())
    try:
        from anamorf import system_control as sc
        free, total = sc.gpu_mem()
        print("карта: свободно %s МБ из %s МБ" % (free, total))
        for n, pid, mb in sc.gpu_top_processes(12):
            print("   на карте: %-28s pid %-7s %s МБ" % (n, pid, mb))
    except Exception as e:
        print("замер карты не вышел:", e)

    print("\n=== СОСЕДИ ===")
    print("голос  %s -> %.1f ГБ" % (CFG.get("tts.engine"), vramplan.voice_gb()))
    print("слух   %s -> %.1f ГБ" % (CFG.get("stt.engine"), vramplan.stt_gb()))
    print("зрение %s -> %.1f ГБ" % (CFG.get("vision.enabled"),
                                    vramplan.vision_gb()))
    print("режим по требованию (tts.ondemand):", CFG.get("tts.ondemand", False))

    mp = llamacpp.find_model()
    print("\n=== МОДЕЛЬ ===")
    print("файл:", mp)
    if not mp:
        print("модель не найдена — дальше считать нечего")
        return
    m = gguf_meta.read(mp)
    print(gguf_meta.describe(m))
    for q in ("f16", "q8_0"):
        print("  KV на 32k: %.2f ГБ | на 120k: %.2f ГБ  (%s)"
              % (gguf_meta.kv_gb(m, 32768, q), gguf_meta.kv_gb(m, 122880, q), q))

    print("\n=== ПЛАН ДЛЯ ЭТОЙ МОДЕЛИ ===")
    for want in (0, 131072):
        pl = vramplan.plan(model_path=mp, want_ctx=want)
        print("хочу %-7s -> влезает=%s окно=%s n_cpu_moe=%s"
              % (want or "как есть", pl["fits"], pl["n_ctx"], pl["n_cpu_moe"]))
        print("   ", pl["note"])

    print("\n=== 35B-A3B НА ЭТОМ ЖЕЛЕЗЕ (типовая геометрия) ===")
    fake = {"name": "Qwen3.6-35B-A3B Q4_K_M", "n_layer": 48, "kv_layers": 48,
            "n_head_kv": 4, "k_len": 128, "v_len": 128, "n_expert": 128,
            "n_expert_used": 8, "gb_experts": 18.3, "gb_rest": 2.9,
            "gb_total": 21.2, "ctx_train": 262144, "arch": "qwen35moe"}
    print(gguf_meta.describe(fake))
    total = vramplan.total_gb()
    ram = vramplan.ram_free_gb()
    res, peak, who = vramplan._companions()
    budget = total - res - peak - vramplan._RESERVE_GB
    print("бюджет мозгу на карте: %.1f ГБ (всего %.1f, соседи: %s, запас %.1f)"
          % (budget, total, who, vramplan._RESERVE_GB))
    print("свободной ОЗУ под экспертов: %.1f ГБ (нужно 18.3)" % ram)
    for qk, qv in (("q8_0", "q8_0"), ("q8_0", "q4_0"), ("q4_0", "q4_0")):
        print("  --- кэш K=%s V=%s ---" % (qk, qv))
        for c in (32768, 65536, 122880):
            kv = gguf_meta.kv_gb(fake, c, qk, qv)
            got = vramplan._fit_moe(fake, budget, ram - 2.0, c, qk)
            need_gpu = fake["gb_rest"] + kv
            print("    окно %-7d KV %.2f ГБ | на карте минимум %.2f | %s"
                  % (c, kv, need_gpu,
                     ("влезает, экспертов в ОЗУ %d/48, на карте %.2f"
                      % (got[0], got[1])) if got else "НЕ влезает"))


try:
    main()
except Exception:
    print(traceback.format_exc())
_dump()
