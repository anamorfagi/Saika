# Создать папку нового проекта слуха рядом с Сайкой (pyexec из живого процесса).
import os, pathlib
p = pathlib.Path(r"C:\AI\Hear")
for d in ("hear", "hear/capture", "hear/scene", "hear/ears", "ui", "tools", "data", "logs", "docs"):
    (p / d).mkdir(parents=True, exist_ok=True)
open(r"C:\AI\Saika\data\pyexec_out.txt", "w", encoding="utf-8").write("ok " + str(p) + " " + str(sorted(os.listdir(p))))
