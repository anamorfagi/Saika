"""КАРТА main.py (2026-08-19).

Повод. `anamorf/main.py` — 9 тысяч строк, и человек, открывший проект
впервые, первым делом упирается именно в него. Распил на модули записан
в план (PLAN_BUILD.md, ARCHITECTURE.md), но он рискованный и небыстрый, а
читать надо уже сегодня. Дешёвая замена распилу — навигация: где какой
раздел, какие ручки HTTP он отдаёт, где живут два самых больших куска.

Как и карта модулей, собирается ИЗ КОДА, иначе устареет через неделю и
начнёт врать.

    python tools/make_main_map.py
"""
import ast
import io
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "server", "main.py")
OUT = os.path.join(ROOT, "server", "MAIN_MAP.md")

# «# ---------------------- REST ----------------------» и подобное
BANNER = re.compile(r"^#\s*[-=~]{3,}\s*(.+?)\s*[-=~]{3,}\s*$")
# «# ==========» пустой рамкой, а название — строкой ниже
FRAME = re.compile(r"^#\s*[-=~]{6,}\s*$")
DECOR = "═-=~*·—"
ROUTE = re.compile(r"^@app\.(get|post|put|delete|websocket)\(\s*['\"]([^'\"]+)")


def _first_line(node):
    d = ast.get_docstring(node) or ""
    return d.split("\n")[0].strip()


def _clean(head):
    """Убрать рамки, хвост незакрытой скобки и точку в конце."""
    head = re.split(r"[═=~*·]{2,}", head.strip(DECOR + " "))[0]
    if "(" in head and ")" not in head:      # «... (2026-08-15» — обрезок
        head = head[:head.index("(")]
    return head.strip(DECOR + " .:")


def _blocks(fn, src_lines):
    """Внутренние комментарии-заголовки большой функции — её оглавление.

    Заголовком считаем ЗАГЛАВНУЮ фразу в НАЧАЛЕ блока комментариев: так в
    этом проекте пишут «что здесь происходит», а строчными ниже — «почему
    так». Продолжения блока пропускаем, иначе оглавление превращается в
    пересказ комментариев обрывками вроде «ДОЛЖНЫ ОБА».
    """
    out, prev_comment = [], False
    for i in range(fn.lineno, min(fn.end_lineno, len(src_lines))):
        s = src_lines[i].strip()
        is_comment = s.startswith("#")
        if not is_comment or prev_comment:
            prev_comment = is_comment
            continue
        prev_comment = True
        head = _clean(s.lstrip("#").strip().split(".")[0].split(",")[0])
        if len(head) < 8 or len(head) > 70:
            continue
        letters = [c for c in head if c.isalpha()]
        if not letters or sum(c.isupper() for c in letters) < len(letters) * 0.8:
            continue
        out.append((i + 1, head))
    return out


def main():
    src = io.open(SRC, encoding="utf-8").read()
    lines = src.split("\n")
    tree = ast.parse(src)

    sections = []
    for i, l in enumerate(lines):
        m = BANNER.match(l.strip())
        if m and _clean(m.group(1)):
            sections.append((i + 1, _clean(m.group(1))))
            continue
        # рамка без текста: название — первой строкой внутри неё
        if FRAME.match(l.strip()) and i + 1 < len(lines):
            nxt = lines[i + 1].strip()
            if nxt.startswith("#") and not FRAME.match(nxt):
                name = _clean(nxt.lstrip("#").strip().split(".")[0])
                if name and (not sections or sections[-1][0] != i + 1):
                    sections.append((i + 1, name))
    routes = [(i + 1, m.group(1).upper(), m.group(2)) for i, l in enumerate(lines)
              if (m := ROUTE.match(l.strip()))]
    funcs = [n for n in tree.body
             if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    classes = [n for n in tree.body if isinstance(n, ast.ClassDef)]
    big = sorted(funcs, key=lambda n: n.end_lineno - n.lineno, reverse=True)[:5]

    p = []
    p.append("# Карта `anamorf/main.py`")
    p.append("")
    p.append("> Собрано механически: `python tools/make_main_map.py`. "
             "Правь код, а не эту страницу.")
    p.append("")
    p.append(f"Всего строк: **{len(lines)}**, ручек HTTP: **{len(routes)}**, "
             f"функций верхнего уровня: **{len(funcs)}**.")
    p.append("")
    p.append("Это проводка, а не логика: HTTP, WebSocket и конвейер ответа. "
             "Вся предметная работа живёт в модулях — карта в "
             "[MODULES.md](MODULES.md). Файл большой не потому, что так "
             "задумано: распил записан в "
             "[../PLAN_BUILD.md](../PLAN_BUILD.md).")
    p.append("")

    p.append("## Разделы по порядку")
    p.append("")
    p.append("| Строка | Раздел |")
    p.append("|---:|---|")
    for ln, name in sections:
        p.append(f"| {ln} | {name} |")
    p.append("")

    p.append("## Самые большие куски")
    p.append("")
    p.append("Эти пять функций — половина файла. Читать их подряд не надо: "
             "ниже оглавление по внутренним заголовкам.")
    p.append("")
    for fn in big:
        size = fn.end_lineno - fn.lineno
        doc = _first_line(fn)
        p.append(f"### `{fn.name}()` — строки {fn.lineno}–{fn.end_lineno} "
                 f"({size})")
        p.append("")
        if doc:
            p.append(f"{doc}")
            p.append("")
        blocks = _blocks(fn, lines)
        if blocks:
            for ln, head in blocks:
                p.append(f"- {ln} — {head}")
            p.append("")

    p.append("## Ручки HTTP и WebSocket")
    p.append("")
    p.append("| Строка | Метод | Путь |")
    p.append("|---:|---|---|")
    for ln, meth, path in sorted(routes, key=lambda r: r[2]):
        p.append(f"| {ln} | {meth} | `{path}` |")
    p.append("")

    if classes:
        p.append("## Классы")
        p.append("")
        for c in classes:
            doc = _first_line(c)
            p.append(f"- **`{c.name}`** (строки {c.lineno}–{c.end_lineno})"
                     + (f" — {doc}" if doc else ""))
        p.append("")

    io.open(OUT, "w", encoding="utf-8", newline="\n").write("\n".join(p))
    print(f"{OUT}: {len(lines)} строк, {len(routes)} ручек, "
          f"{len(sections)} разделов")


if __name__ == "__main__":
    main()
