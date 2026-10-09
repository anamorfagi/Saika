# -*- coding: utf-8 -*-
"""free_probe.py — сравнение БЕСПЛАТНЫХ моделей на одной реальной задаче (сценарий «унижение» Бай Сяочуня).

---- учебный блок ----
Не пинг «привет», а настоящая работа: те же 8 эпизодов, тот же промпт, что в behavior_fill.
Меряем: ответила ли, сколько секунд, валидный ли JSON, сколько действий заполнено. Ничего не пишет в карточку.
"""
import sys, io, json, time, random, pathlib
import concurrent.futures as cf
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from llm import Client
from research import object_response
import behavior_fill as bf

КАНДИДАТЫ = [(a.split("|")[0], a.split("|")[1]) for a in sys.argv[1:]] or [
    ("mistral", "mistral-small-latest"),
    ("mistral", "mistral-large-latest"),
    ("github", "openai/gpt-4o-mini"),
    ("openrouter", "qwen/qwen3-235b-a22b:free"),
    ("openrouter", "deepseek/deepseek-chat-v3-0324:free"),
    ("cloudflare", "@cf/meta/llama-3.3-70b-instruct-fp8-fast"),
    ("gigachat", "GigaChat-2"),
    ("ollama", "qwen2.5:7b-instruct"),
]

random.seed(7)
сц = next(s for s in json.loads((pathlib.Path(__file__).parent / "scen.json").read_text(encoding="utf-8")) if s["id"] == "humil")
эп = bf.подобрать(bf.эпизоды("bai_xiaochun"), bf.КЛЮЧИ["humil"])
user = ("Персонаж: Бай Сяочунь (A Will Eternal) — трусоватый, хвастливый, хитрый культиватор, боится смерти.\n"
        "Реальные эпизоды:\n" + "\n".join(bf.кратко(e) for e in эп) +
        f"\n\nСитуация: {сц['t']}. {сц['in']}\nДля каждого действия — 1–2 фразы по-русски его манерой. И поле \"_выбор\".\n"
        "Действия: " + json.dumps(сц["acts"], ensure_ascii=False) + '\nФормат: {"<действие>": "<реплика>", "_выбор": "<действие>"}')


def один(пм):
    п, м = пм; t = time.time()
    try:
        к = Client(provider=п, model=м, timeout=120)
        сырое = к.chat("Ответ — только JSON.", user, temperature=0.7, max_tokens=900, json_mode=(п != "gigachat"))
        (pathlib.Path(__file__).parent.parent / "logs" / f"free_{п}_{м.replace('/', '_').replace(':', '_')}.txt").write_text(str(сырое), encoding="utf-8")
        r = bf.все_объекты(сырое)
        n = sum(1 for a in сц["acts"] if r.get(a))
        return п, м, round(time.time() - t, 1), f"{n}/5", str(сырое).replace("\n", " ")[:300]
    except Exception as ex:
        return п, м, round(time.time() - t, 1), "ОШИБКА", str(ex)[:120]


with cf.ThreadPoolExecutor(8) as пул:
    for п, м, с, ок, пример in пул.map(один, КАНДИДАТЫ):
        print(f"{п:11} {м:42} {с:6}с {ок:8} {пример}", flush=True)
