# подхватить новые переводы без перезапуска: словарь _RU — существующее имя, живая правка его не трогает
import importlib.util, re
from anamorf import hearing as H
src = open(r"C:\AI\Saika\anamorf\hearing.py", encoding="utf-8").read()
ns = {}
m = re.search(r"^_RU = \{.*?^\}", src, re.S | re.M)
exec(m.group(0), ns)
added = 0
for k, v in ns["_RU"].items():
    if k not in H._RU: H._RU[k] = v; added += 1
H._RU_ORDER = sorted(H._RU.items(), key=lambda kv: -len(kv[0]))
print("добавлено переводов:", added, "| Guitar ->", H._ru("Guitar"), "| Fire crackle ->", H._ru("Fire crackle"))
