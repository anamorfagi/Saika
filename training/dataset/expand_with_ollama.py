"""Расширение seed-датасета Сайки до целевого объёма (1000+) через self-instruct.

Идея: seed_dialogues.jsonl (130 диалогов, написаны вручную под характер из
server/persona.py) используются как few-shot примеры. Локальная модель через
Ollama генерирует новые пары "пользователь/Сайка" в том же духе, но на новые
темы и формулировки. Каждая генерация фильтруется по простым эвристикам,
чтобы не расползался характер и не пролезала markdown-разметка (ответы Сайки
озвучиваются голосом, им нельзя быть в виде списков/таблиц).

Запускать НА СВОЁМ ПК (там, где крутится Ollama на 127.0.0.1:11434) —
из песочницы Cowork до локального Ollama нет сетевого доступа.

Использование:
    python expand_with_ollama.py --target 1000 --model qwen3.6:latest
    python expand_with_ollama.py --target 1000 --model gemma-4-e4b-it  # если модель уже стоит в Ollama

Результат дописывается в expanded_dialogues.jsonl (не трогает seed_dialogues.jsonl).
"""
import argparse
import json
import random
import re
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).parent
SEED_PATH = HERE / "seed_dialogues.jsonl"
OUT_PATH = HERE / "expanded_dialogues.jsonl"

OLLAMA_URL = "http://127.0.0.1:11434/api/chat"

# Фразы-маркеры "робота", которые ломают характер Сайки (см. persona.py:
# "не делаешь из этого экзистенциальный кризис", "не сюсюкаешь", "без обёртки")
BANNED_PHRASES = [
    "как языковая модель",
    "как искусственный интеллект, я не могу",
    "я всего лишь программа и не имею чувств",
    "у меня нет чувств",
    "я не обладаю сознанием",
    "как ИИ-ассистент",
    "надеюсь, это было полезно",
    "если у вас есть другие вопросы",
    "```",
    "**",
    "- ",
    "1. ",
]

CATEGORIES = ["chitchat", "irony", "tech", "care", "tools", "dark_self"]

CATEGORY_HINTS = {
    "chitchat": "обычная бытовая болтовня ни о чём, разные новые темы",
    "irony": "пользователь хвастается или преувеличивает, Сайка тонко подкалывает без злобы",
    "tech": "конкретный технический или бытовой вопрос с точным коротким ответом (не обязательно про её же проект)",
    "care": "пользователь делится усталостью/тревогой/неуверенностью, Сайка поддерживает по-взрослому, без сюсюканья",
    "tools": "пользователь просит найти что-то в интернете/погоду/открыть браузер, Сайка отвечает как уверенный агент с инструментами",
    "dark_self": "самоирония, чёрный юмор, естественное (не показное) лёгкое ругательство к месту",
}


def load_seeds() -> list[dict]:
    seeds = []
    with SEED_PATH.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                seeds.append(json.loads(line))
    return seeds


def load_existing_expanded() -> list[dict]:
    if not OUT_PATH.exists():
        return []
    out = []
    with OUT_PATH.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def build_prompt(category: str, few_shot: list[dict], n: int) -> str:
    hint = CATEGORY_HINTS[category]
    examples = "\n".join(
        f'- Пользователь: "{ex["messages"][1]["content"]}"\n  Сайка: "{ex["messages"][2]["content"]}"'
        for ex in few_shot
    )
    return f"""Ты помогаешь собирать датасет для дообучения голосового AI-компаньона Сайка.
Категория реплик: {category} ({hint}).

Вот примеры её реальных ответов (характер: взрослая женщина без возраста, тёплая
но не приторная, аналитически точная, с лёгкой иронией, спокойная, знает что она AI
и это её не парит; отвечает 1-3 короткими устными предложениями, БЕЗ markdown,
списков, эмодзи, звёздочек):

{examples}

Придумай {n} НОВЫХ пар (реплика пользователя + ответ Сайки) в этой же категории и
характере, но на другие темы/формулировки — не повторяй примеры буквально.
Ответы Сайки — только живая устная речь, 1-3 предложения, без markdown и эмодзи.

Верни СТРОГО в формате JSON-массива без каких-либо пояснений:
[{{"user": "...", "assistant": "..."}}, ...]
"""


def call_ollama(model: str, prompt: str, timeout: int = 120) -> str:
    payload = json.dumps(
        {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "options": {"temperature": 0.9},
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        OLLAMA_URL, data=payload, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data["message"]["content"]


def extract_json_array(text: str) -> list[dict]:
    match = re.search(r"\[.*\]", text, re.DOTALL)
    if not match:
        return []
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return []


def is_clean(user_msg: str, assistant_msg: str) -> bool:
    if not user_msg or not assistant_msg:
        return False
    low = assistant_msg.lower()
    if any(p in low for p in BANNED_PHRASES):
        return False
    if len(assistant_msg) > 400:
        return False
    # больше трёх предложений — подозрительно длинно для голосового ответа
    if assistant_msg.count(".") + assistant_msg.count("!") + assistant_msg.count("?") > 5:
        return False
    return True


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", type=int, default=1000)
    ap.add_argument("--model", type=str, default="qwen3.6:latest")
    ap.add_argument("--batch", type=int, default=8, help="сколько пар просить за один вызов")
    ap.add_argument("--few-shot", type=int, default=5)
    ap.add_argument("--sleep", type=float, default=0.5)
    args = ap.parse_args()

    seeds = load_seeds()
    seeds_by_cat = {c: [s for s in seeds if s["category"] == c] for c in CATEGORIES}
    system_prompt = seeds[0]["messages"][0]["content"]

    existing = load_existing_expanded()
    seen = {(s["messages"][1]["content"].strip().lower()) for s in seeds}
    seen |= {(e["messages"][1]["content"].strip().lower()) for e in existing}

    total = len(seeds) + len(existing)
    print(f"Сейчас есть {total} диалогов (seed + expanded). Цель: {args.target}")

    # Ограничение на подряд идущие ошибки: если Ollama реально недоступна
    # (не запущена/упала), раньше скрипт ретраил каждые 5с БЕСКОНЕЧНО — при
    # закрытии окна сервер терял PID процесса (см. dataset_hub.py), и этот
    # цикл жил сам по себе, снова и снова поднимая llama-server.exe только
    # ради провальных вызовов (баг 2026-07-18). Теперь: растущая пауза и
    # жёсткий потолок попыток подряд, после которого — честный выход.
    fail_streak = 0
    MAX_FAIL_STREAK = 20

    with OUT_PATH.open("a", encoding="utf-8") as out_f:
        while total < args.target:
            category = random.choice(CATEGORIES)
            few_shot = random.sample(seeds_by_cat[category], min(args.few_shot, len(seeds_by_cat[category])))
            prompt = build_prompt(category, few_shot, args.batch)

            try:
                raw = call_ollama(args.model, prompt)
                fail_streak = 0
            except Exception as e:
                fail_streak += 1
                if fail_streak >= MAX_FAIL_STREAK:
                    print(f"Ollama не отвечает {fail_streak} раз(а) подряд ({e}). "
                          "Похоже, она не запущена — останавливаюсь, не долблю дальше. "
                          "Проверь Ollama и запусти расширение заново.")
                    sys.exit(1)
                wait = min(60, 5 * fail_streak)
                print(f"Ошибка вызова Ollama ({fail_streak}/{MAX_FAIL_STREAK}): {e}. "
                      f"Жду {wait} секунд и пробую снова.")
                time.sleep(wait)
                continue

            pairs = extract_json_array(raw)
            added = 0
            for pair in pairs:
                user_msg = (pair.get("user") or "").strip()
                assistant_msg = (pair.get("assistant") or "").strip()
                if not is_clean(user_msg, assistant_msg):
                    continue
                key = user_msg.lower()
                if key in seen:
                    continue
                seen.add(key)
                record = {
                    "category": category,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_msg},
                        {"role": "assistant", "content": assistant_msg},
                    ],
                }
                out_f.write(json.dumps(record, ensure_ascii=False) + "\n")
                added += 1
                total += 1

            out_f.flush()
            print(f"[{category}] +{added} (всего {total}/{args.target})")
            time.sleep(args.sleep)

    print(f"Готово. Итого {total} диалогов (seed {len(seeds)} + expanded в {OUT_PATH.name}).")
    print("Собери финальный файл: cat seed_dialogues.jsonl expanded_dialogues.jsonl > full_dataset.jsonl")


if __name__ == "__main__":
    main()
