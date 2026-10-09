import re
from anamorf.stt import dialog_llm as D
src=open(r"C:\AI\Saika\anamorf\stt\dialog_llm.py",encoding="utf-8").read()
m=re.search(r"^_SYS = \(.*?\)\n", src, re.S|re.M); ns={}; exec(m.group(0), ns); D._SYS=ns["_SYS"]
print("SYS обновлён:", "КТО ГОВОРИТ" in D._SYS)
