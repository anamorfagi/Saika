"""КАРТА МОДУЛЕЙ ИЗ ДОКСТРИНГОВ (2026-08-19).

Собирает `server/MODULES.md` — список всех модулей с ПЕРВОЙ строкой их
докстринга, разложенный по подсистемам (слух, голос, зрение, мозги,
память, руки, тело, здоровье).

Зачем механически, а не руками: рукописный список устаревает через
неделю и начинает врать. Здесь единственный источник правды — сам код:
поправил докстринг, пересобрал карту.

    python tools/make_modules_map.py
"""
import ast
import io
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "server")
OUT = os.path.join(SRC, "MODULES.md")

GROUPS = [
    ("Слух", ["hearing", "stt", "clap_ears", "denoise", "earlog", "draft",
              "misheard", "hear_bench", "transcript", "unmix", "beatbox",
              "clap", "mic_passport", "voiceprint", "gender", "turns"]),
    ("Голос", ["tts", "voice", "speak"]),
    ("Зрение", ["vision", "ocr", "screen"]),
    ("Мозги", ["llm", "cortex", "psyche", "agent", "capabilities", "recipes",
               "prompt_blocks", "lorebook", "persona", "draft_reply",
               "model_dossier", "ai_consult", "knobs", "ratings", "workflow",
               "skills", "brains", "passport"]),
    ("Память", ["memory", "dataset_hub", "cards", "devboard", "app_memory",
                "desk_habits", "focus", "attention"]),
    ("Руки", ["pc_control", "ui_hands", "browser_hands", "file_hands",
              "explorer", "app_finder", "hotkeys", "system_control", "phone",
              "messengers", "pdf_hands", "self_control", "reflex", "trust",
              "dictation", "highlight"]),
    ("Тело и лицо", ["avatar", "anim_hub", "desk_avatar", "desk_slots"]),
    ("Здоровье", ["guard", "triage", "heal", "baymax", "diagnostics",
                  "proc_utils", "netpolicy", "network", "git_sync"]),
]


def first_line(path: str) -> str:
    try:
        doc = ast.get_docstring(ast.parse(io.open(
            path, encoding="utf-8").read())) or ""
    except Exception:
        return ""
    line = (doc.strip().splitlines() or [""])[0].strip()
    line = re.sub(r"\s*\(20\d\d-\d\d-\d\d\)\.?$", "", line).rstrip(".")
    return line[:120]


def collect():
    files = sorted(f for f in os.listdir(SRC) if f.endswith(".py")
                   and f != "__init__.py" and "broken" not in f)
    pkgs = sorted(d for d in os.listdir(SRC)
                  if os.path.isdir(os.path.join(SRC, d))
                  and os.path.exists(os.path.join(SRC, d, "__init__.py")))
    used, out = set(), []
    for title, keys in GROUPS:
        rows = []
        for f in files:
            name = f[:-3]
            if name in used:
                continue
            if any(k == name or name.startswith(k) or k in name for k in keys):
                used.add(name)
                rows.append((f, first_line(os.path.join(SRC, f))))
        for d in pkgs:
            if d in used:
                continue
            if any(k == d or d.startswith(k) for k in keys):
                used.add(d)
                rows.append((d + "/",
                             first_line(os.path.join(SRC, d, "__init__.py"))))
        if rows:
            out.append((title, rows))
    rest = [(f, first_line(os.path.join(SRC, f)))
            for f in files if f[:-3] not in used]
    rest += [(d + "/", first_line(os.path.join(SRC, d, "__init__.py")))
             for d in pkgs if d not in used]
    if rest:
        out.append(("Прочее", rest))
    return out


def main() -> int:
    out = collect()
    total = sum(len(r) for _t, r in out)
    with io.open(OUT, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("# Карта модулей\n\n")
        fh.write("> Собрано механически из ПЕРВЫХ строк докстрингов "
                 "(`server/*.py`). Если строка выглядит\n> странно — правь "
                 "докстринг модуля, а не эту таблицу: файл пересобирается "
                 "командой\n> `python tools/make_modules_map.py`.\n\n")
        fh.write(f"Всего модулей: **{total}**. Проводка (HTTP, WebSocket, "
                 "конвейер ответа) живёт в `server/main.py` —\n"
                 "он один на 9 тысяч строк — навигация по нему в "
                 "[MAIN_MAP.md](MAIN_MAP.md),\n"
                 "план распила в [ARCHITECTURE.md](../ARCHITECTURE.md).\n\n")
        for title, rows in out:
            fh.write(f"## {title}\n\n")
            for f, d in rows:
                fh.write(f"- **`{f}`** — {d or '—'}\n")
            fh.write("\n")
    print(f"{OUT}: {total} модулей")
    return 0


if __name__ == "__main__":
    sys.exit(main())
