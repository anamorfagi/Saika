"""Подтяжка готовых датасетов с Hugging Face Hub или GitHub и приведение их
к общему messages-формату (совместимому с seed_dialogues.jsonl / convert_format.py).

Готовые датасеты НЕ содержат характер Сайки — они дают общую диалоговую/
инструктивную грамотность (речь, факты, разнообразие тем) и обычно подмешиваются
в небольшой пропорции (условно 10-20%) к датасету персонажа, чтобы модель не
"забывала" общие навыки, дообучаясь только на 130-1000 репликах одного характера.
Смешивать выборочно, а не просто заливать всё подряд — не каждый датасет тут подходит
(например, англоязычные instruction-датасеты дадут смешение языка).

Источник 1: Hugging Face Hub, через лёгкий REST API datasets-server (без
установки тяжёлой библиотеки `datasets`):
    python fetch_dataset.py --source hf --name IlyaGusev/ru_turbo_alpaca --split train --limit 300 --preview

Источник 2: сырой файл на GitHub (jsonl/json/csv):
    python fetch_dataset.py --source github --url https://raw.githubusercontent.com/.../data.jsonl --preview

Без --preview результат сохраняется в raw_imports/<name>.messages.jsonl в общем
messages-формате (best-effort автомаппинг полей — проверь --preview перед сохранением,
структура датасетов на HF/GitHub не стандартизирована).
"""
import argparse
import csv
import io
import json
import urllib.request
from pathlib import Path

HERE = Path(__file__).parent
RAW_IMPORTS_DIR = HERE / "raw_imports"

HF_ROWS_API = "https://datasets-server.huggingface.co/rows"


def fetch_hf_rows(name: str, config: str, split: str, limit: int) -> list[dict]:
    rows = []
    offset = 0
    page = 100
    while len(rows) < limit:
        url = (
            f"{HF_ROWS_API}?dataset={urllib.parse.quote(name)}"
            f"&config={config}&split={split}&offset={offset}&length={page}"
        )
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            print(f"Ошибка запроса к HF datasets-server: {e}")
            break
        batch = [r["row"] for r in data.get("rows", [])]
        if not batch:
            break
        rows.extend(batch)
        offset += page
    return rows[:limit]


def fetch_github_raw(url: str) -> str:
    req = urllib.request.Request(url, headers={"Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8")


def parse_github_content(url: str, text: str) -> list[dict]:
    if url.endswith(".jsonl"):
        return [json.loads(line) for line in text.splitlines() if line.strip()]
    if url.endswith(".json"):
        data = json.loads(text)
        return data if isinstance(data, list) else data.get("data", [])
    if url.endswith(".csv"):
        return list(csv.DictReader(io.StringIO(text)))
    # без расширения — пробуем как jsonl, потом как json
    try:
        return [json.loads(line) for line in text.splitlines() if line.strip()]
    except json.JSONDecodeError:
        data = json.loads(text)
        return data if isinstance(data, list) else data.get("data", [])


import urllib.parse  # noqa: E402  (используется в fetch_hf_rows)


def auto_map_to_messages(row: dict) -> dict | None:
    """Best-effort приведение произвольной записи к {"messages": [...]}"""
    keys = {k.lower() for k in row}

    # уже ShareGPT-подобный формат
    if "conversations" in row and isinstance(row["conversations"], list):
        role_map = {"human": "user", "gpt": "assistant", "system": "system", "user": "user", "assistant": "assistant"}
        messages = []
        for turn in row["conversations"]:
            role = role_map.get(str(turn.get("from", "")).lower())
            value = turn.get("value")
            if role and value:
                messages.append({"role": role, "content": value})
        return {"messages": messages} if len(messages) >= 2 else None

    # уже OpenAI messages
    if "messages" in row and isinstance(row["messages"], list):
        return {"messages": row["messages"]}

    # instruction/input/output (alpaca-стиль)
    if {"instruction", "output"} <= keys:
        instr = row.get("instruction") or row.get("Instruction", "")
        inp = row.get("input") or row.get("Input", "")
        out = row.get("output") or row.get("Output", "")
        user_content = f"{instr}\n{inp}".strip() if inp else instr
        return {
            "messages": [
                {"role": "user", "content": user_content},
                {"role": "assistant", "content": out},
            ]
        }

    # question/answer
    if {"question", "answer"} <= keys:
        return {
            "messages": [
                {"role": "user", "content": row.get("question") or row.get("Question")},
                {"role": "assistant", "content": row.get("answer") or row.get("Answer")},
            ]
        }

    # prompt/response(-s)
    if "prompt" in keys and ("response" in keys or "responses" in keys or "chosen" in keys):
        resp = row.get("response") or row.get("chosen") or (row.get("responses") or [None])[0]
        return {
            "messages": [
                {"role": "user", "content": row.get("prompt")},
                {"role": "assistant", "content": resp},
            ]
        }

    return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", choices=["hf", "github"], required=True)
    ap.add_argument("--name", help="имя датасета на Hugging Face, например IlyaGusev/ru_turbo_alpaca")
    ap.add_argument("--config", default="default")
    ap.add_argument("--split", default="train")
    ap.add_argument("--url", help="прямая ссылка на raw-файл GitHub (jsonl/json/csv)")
    ap.add_argument("--limit", type=int, default=200)
    ap.add_argument("--preview", action="store_true", help="только показать первые записи, не сохранять")
    args = ap.parse_args()

    if args.source == "hf":
        if not args.name:
            raise SystemExit("--name обязателен для --source hf")
        raw_rows = fetch_hf_rows(args.name, args.config, args.split, args.limit)
        out_name = args.name.replace("/", "__")
    else:
        if not args.url:
            raise SystemExit("--url обязателен для --source github")
        text = fetch_github_raw(args.url)
        raw_rows = parse_github_content(args.url, text)
        out_name = args.url.rstrip("/").split("/")[-1].rsplit(".", 1)[0]

    print(f"Скачано сырых записей: {len(raw_rows)}")

    mapped = []
    unmapped = 0
    for row in raw_rows:
        m = auto_map_to_messages(row)
        if m and all(msg.get("content") for msg in m["messages"]):
            mapped.append(m)
        else:
            unmapped += 1

    print(f"Успешно смаплено: {len(mapped)}, не удалось смаппить: {unmapped}")

    if args.preview:
        for m in mapped[:5]:
            print(json.dumps(m, ensure_ascii=False, indent=2))
        if unmapped and not mapped:
            print("\nНи одной записи не смаплено автоматически. Пример сырой записи:")
            print(json.dumps(raw_rows[0], ensure_ascii=False, indent=2)[:1000])
        return

    RAW_IMPORTS_DIR.mkdir(exist_ok=True)
    out_path = RAW_IMPORTS_DIR / f"{out_name}.messages.jsonl"
    with out_path.open("w", encoding="utf-8") as f:
        for m in mapped:
            f.write(json.dumps(m, ensure_ascii=False) + "\n")
    print(f"Сохранено в {out_path}")
    print(
        "Важно: у этих реплик нет системного промпта с характером Сайки и они "
        "не в её стиле — использовать как общую SFT-добавку в небольшой доле "
        "(10-20% от датасета персонажа), а не как основной материал."
    )


if __name__ == "__main__":
    main()
