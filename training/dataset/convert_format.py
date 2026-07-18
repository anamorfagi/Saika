"""Конвертация датасета Сайки (messages-JSONL) в форматы под конкретные пайплайны дообучения.

Вход: seed_dialogues.jsonl / expanded_dialogues.jsonl / full_dataset.jsonl
  {"category": "...", "messages": [{"role": "system"|"user"|"assistant", "content": "..."}]}

Форматы на выходе:
  sharegpt  -> {"conversations": [{"from": "system"|"human"|"gpt", "value": "..."}]}
              (формат, который понимают axolotl/unsloth ShareGPT-лоадеры)
  alpaca    -> {"instruction": "...", "input": "", "output": "..."}
              (system не переносится отдельным полем — обычно задаётся один раз в конфиге трейнера)
  openai    -> как есть, {"messages": [...]}  (для API fine-tuning / большинства HF SFTTrainer)

Использование:
    python convert_format.py --in full_dataset.jsonl --format sharegpt --out full_sharegpt.jsonl
    python convert_format.py --in full_dataset.jsonl --format alpaca --out full_alpaca.jsonl
    python convert_format.py --in full_dataset.jsonl --format openai --out full_openai.jsonl
"""
import argparse
import json
from pathlib import Path

ROLE_TO_SHAREGPT = {"system": "system", "user": "human", "assistant": "gpt"}


def to_sharegpt(record: dict) -> dict:
    conversations = [
        {"from": ROLE_TO_SHAREGPT[m["role"]], "value": m["content"]}
        for m in record["messages"]
    ]
    return {"conversations": conversations}


def to_alpaca(record: dict) -> dict:
    msgs = {m["role"]: m["content"] for m in record["messages"]}
    return {
        "instruction": msgs.get("user", ""),
        "input": "",
        "output": msgs.get("assistant", ""),
    }


def to_openai(record: dict) -> dict:
    return {"messages": record["messages"]}


CONVERTERS = {"sharegpt": to_sharegpt, "alpaca": to_alpaca, "openai": to_openai}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", required=True)
    ap.add_argument("--format", choices=list(CONVERTERS), required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    converter = CONVERTERS[args.format]
    in_path = Path(args.inp)
    out_path = Path(args.out)

    count = 0
    with in_path.open(encoding="utf-8") as f_in, out_path.open("w", encoding="utf-8") as f_out:
        for line in f_in:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            converted = converter(record)
            f_out.write(json.dumps(converted, ensure_ascii=False) + "\n")
            count += 1

    print(f"Сконвертировано {count} записей -> {out_path} (формат: {args.format})")


if __name__ == "__main__":
    main()
