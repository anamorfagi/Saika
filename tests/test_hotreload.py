"""БЕСШОВНОЕ ОБНОВЛЕНИЕ: что можно подменить на лету, а что нельзя.

Владелец 22.08.2026: «нужно сделать полностью бесшовные обновления»,
«этот режим хуета, раз приходится перезапускать».

Разделение честное, а не оптимистичное: на лету перечитываются только
модули-листья без состояния (разбор ошибок, починка, текст Беймакса).
Менеджеры слуха и голоса, движки и сам сервер держат живое: сокеты,
модели в видеопамяти, открытый разговор — их подменить нельзя, и
притворяться, что можно, опаснее, чем переехать в паузе: половина
системы осталась бы на старом коде, половина на новом.
"""


def run():
    rows = []
    # hot_split — чистая функция, ради неё не поднимаем весь сервер
    import ast, io, types
    src = io.open("anamorf/main.py", encoding="utf-8").read()
    tree = ast.parse(src)
    ns = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and getattr(
                node.targets[0], "id", "") == "HOT":
            exec(compile(ast.Module([node], []), "<hot>", "exec"), ns)
        if isinstance(node, ast.FunctionDef) and node.name == "hot_split":
            exec(compile(ast.Module([node], []), "<hot>", "exec"), ns)
    hot_split = ns["hot_split"]

    h, c = hot_split(["anamorf.diagnostics", "anamorf.repair"])
    rows.append(("листья без состояния — на лету",
                 h == ["anamorf.diagnostics", "anamorf.repair"] and not c,
                 str(h)))

    h, c = hot_split(["anamorf.main", "anamorf.tts.manager",
                      "anamorf.stt.engines", "anamorf.llm.llamacpp"])
    rows.append(("сервер, менеджеры и движки — только переездом",
                 not h and len(c) == 4, str(c)))

    h, c = hot_split(["anamorf.diagnostics", "anamorf.tts.manager"])
    rows.append(("смешанная пачка: холодный тянет за собой переезд",
                 h == ["anamorf.diagnostics"] and c == ["anamorf.tts.manager"],
                 f"горячие {h}, холодные {c}"))

    # подпакет с «горячим» именем всё равно холодный: anamorf.llm.repair
    h, c = hot_split(["anamorf.llm.repair"])
    rows.append(("имя из списка в подпакете не делает модуль горячим",
                 not h and c == ["anamorf.llm.repair"], str(c)))
    return rows
