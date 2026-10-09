# -*- coding: utf-8 -*-
"""Дымовой тест ядра v2 БЕЗ Сайки: поднять движок, проверить нативные
вызовы инструментов и скорость. Ничего на ПК не исполняет — инструменты
здесь фальшивые, проверяется только то, КАК модель их зовёт.
    .venv\\Scripts\\python.exe tools\\core_smoke.py
"""
import io, json, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
from anamorf.core import engine, persona, agent_loop, registry

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "core_smoke.txt")
lines = []
def p(*a):
    s = " ".join(str(x) for x in a); print(s, flush=True); lines.append(s)

t0 = time.time()
ok = engine.ensure(180)
p("engine up:", ok, f"{time.time()-t0:.1f}s")
# фальшивый исполнитель: возвращает правдоподобный результат и пишет вызов
calls = []
def fake_exec(name, args, user_text, timeout=60):
    calls.append((name, args))
    return {"web_open": "Открыла https://ya.ru в браузере.",
            "volume_set": "Громкость системы: 30%.",
            "memory_recall": "Из памяти: Виталя делает Сайку и печатает таблички по ГОСТу.",
            }.get(name, f"{name}: выполнено")
registry.execute = fake_exec
sys_text = persona.system_prompt("Виталий") + "\n\n" + registry.index_text()
p("system chars:", len(sys_text), "schemas:", len(registry.schemas()),
  "schema chars:", len(json.dumps(registry.schemas(), ensure_ascii=False)))
for q in ["привет", "открой страницу ya.ru", "сделай громкость 30 процентов",
          "что ты помнишь обо мне?", "как дела?", "переключись на голос silero"]:
    calls.clear(); buf = []
    t = time.time()
    r = agent_loop.run([{"role": "system", "content": sys_text},
                        {"role": "user", "content": q}], q,
                       on_text=buf.append, on_tool=lambda *a: None)
    p(f"\n> {q}\n  calls={calls}\n  reply={''.join(buf)[:200]!r}\n"
      f"  {time.time()-t:.1f}s steps={r['steps']} stats={r['stats']}")
io.open(OUT, "w", encoding="utf-8").write("\n".join(lines))
