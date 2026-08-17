"""Справочник настроек: собирает ВСЕ ключи конфига из кода (2026-08-17).

Повод: ключей 338, а дефолты к ним размазаны по 73 модулям в виде
CFG.get("что.то", значение). На вопрос «какие вообще есть настройки и что
будет, если ключ не задан» нельзя было ответить, не прогрепав проект.
Схему настроек в одном месте (pydantic-settings и подобное) вводить пока
рано — это переписывание всех 73 модулей. Дешёвая замена: генерировать
справочник ИЗ КОДА, тогда он не устареет молча.

Запуск: python -m tools.config_map   (перезаписывает CONFIG.md)
"""
import ast
import io
import json
import os
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKIP = {".git", "__pycache__", "third_party", "models", "data", "logs",
        "_to_delete", "node_modules"}


def _const(node):
    """Литерал -> питоновское значение, иначе None (выражения не считаем)."""
    try:
        return ast.literal_eval(node)
    except Exception:
        return "<выражение>"


def scan():
    """-> {ключ: {"defaults": {repr: [файлы]}, "writes": [файлы]}}"""
    found = defaultdict(lambda: {"defaults": defaultdict(list), "writes": []})
    for root, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in SKIP and not d.startswith(".venv")]
        for f in files:
            if not f.endswith(".py"):
                continue
            p = os.path.join(root, f)
            rel = os.path.relpath(p, ROOT).replace("\\", "/")
            try:
                tree = ast.parse(io.open(p, encoding="utf-8", errors="ignore").read())
            except Exception:
                continue
            for n in ast.walk(tree):
                if not isinstance(n, ast.Call) or not isinstance(n.func, ast.Attribute):
                    continue
                if n.func.attr not in ("get", "set"):
                    continue
                base = n.func.value
                if not (isinstance(base, ast.Name) and base.id in ("CFG", "cfg")):
                    continue
                if not n.args:
                    continue
                key = _const(n.args[0])
                if not isinstance(key, str):
                    continue
                if n.func.attr == "set":
                    if rel not in found[key]["writes"]:
                        found[key]["writes"].append(rel)
                else:
                    dv = repr(_const(n.args[1])) if len(n.args) > 1 else "—"
                    if rel not in found[key]["defaults"][dv]:
                        found[key]["defaults"][dv].append(rel)
    return found


def current():
    """Плоская карта ключ -> значение из config.json (+ config.local.json)."""
    out = {}

    def walk(node, prefix=""):
        for k, v in (node.items() if isinstance(node, dict) else []):
            path = f"{prefix}{k}"
            if isinstance(v, dict):
                walk(v, path + ".")
            else:
                out[path] = v
    for name in ("config.json", "config.local.json"):
        p = os.path.join(ROOT, name)
        if os.path.exists(p):
            try:
                walk(json.load(io.open(p, encoding="utf-8")))
            except Exception:
                pass
    return out


def short(v, n=42):
    s = json.dumps(v, ensure_ascii=False) if not isinstance(v, str) else f'"{v}"'
    return s if len(s) <= n else s[: n - 1] + "…"


def render(found, cur):
    keys = sorted(set(found) | set(cur))
    groups = defaultdict(list)
    for k in keys:
        groups[k.split(".")[0]].append(k)

    only_code = [k for k in keys if k in found and k not in cur]
    only_file = [k for k in keys if k in cur and k not in found]

    L = ["# Справочник настроек Сайки", "",
         "> Файл СГЕНЕРИРОВАН: `python -m tools.config_map`. Руками не править —",
         "> перезапишется. Правится код или `config.json`.", "",
         f"Всего ключей: **{len(keys)}**. Из них в коде читается "
         f"{len(found)}, в конфигах лежит {len(cur)}.", "",
         "Как это работает: `config.local.json` накладывается поверх "
         "`config.json` при загрузке, поэтому личные настройки машины "
         "переживают `git pull`. Ключа нет нигде — берётся значение по "
         "умолчанию прямо из кода, колонка «по умолчанию».", ""]

    if only_code:
        L += ["## ⚠ Читается в коде, но в конфигах отсутствует", "",
              "Работает на значении по умолчанию. Это нормально (так задумано "
              "для новых возможностей), но если ключ важен — его стоит внести "
              "в `config.json`, чтобы он был виден человеку.", ""]
        L += [f"- `{k}`" for k in only_code[:80]]
        if len(only_code) > 80:
            L.append(f"- …и ещё {len(only_code) - 80}")
        L.append("")

    if only_file:
        L += ["## ⚠ Лежит в конфиге, но код его не читает", "",
              "Кандидаты на удаление: либо остались от вырезанных возможностей, "
              "либо читаются не через `CFG.get` (например, целой веткой — тогда "
              "это ложная тревога).", ""]
        L += [f"- `{k}` = {short(cur[k])}" for k in only_file[:80]]
        if len(only_file) > 80:
            L.append(f"- …и ещё {len(only_file) - 80}")
        L.append("")

    L += ["## Все ключи по разделам", ""]
    for g in sorted(groups):
        L += [f"### {g}", "",
              "| ключ | сейчас | по умолчанию | где читается |",
              "|---|---|---|---|"]
        for k in groups[g]:
            info = found.get(k)
            now = short(cur[k]) if k in cur else "—"
            if info and info["defaults"]:
                ds = sorted(info["defaults"], key=lambda d: -len(info["defaults"][d]))
                dv = ds[0] if len(ds) == 1 else " / ".join(ds[:3]) + (" ⚠" if len(ds) > 1 else "")
                files = sorted({f for lst in info["defaults"].values() for f in lst})
            else:
                dv, files = "—", (info["writes"] if info else [])
            src = ", ".join(f"`{f}`" for f in files[:3])
            if len(files) > 3:
                src += f" +{len(files) - 3}"
            L.append(f"| `{k}` | {now} | `{dv}` | {src or '—'} |")
        L.append("")
    L += ["---", "",
          "⚠ в колонке «по умолчанию» значит, что РАЗНЫЕ модули читают один "
          "ключ с РАЗНЫМИ значениями по умолчанию. Это ловушка: поведение "
          "зависит от того, кто спросил первым. Такие места стоит свести к "
          "одному значению.", ""]
    return "\n".join(L)


if __name__ == "__main__":
    f, c = scan(), current()
    io.open(os.path.join(ROOT, "CONFIG.md"), "w", encoding="utf-8",
            newline="\n").write(render(f, c))
    dup = [k for k, v in f.items() if len(v["defaults"]) > 1]
    print(f"CONFIG.md: {len(set(f) | set(c))} ключей, "
          f"{len([k for k in f if k not in c])} только в коде, "
          f"{len([k for k in c if k not in f])} только в конфиге, "
          f"{len(dup)} с расходящимися дефолтами")
    for k in dup[:12]:
        print("  ⚠", k, "->", " / ".join(sorted(f[k]["defaults"])))
