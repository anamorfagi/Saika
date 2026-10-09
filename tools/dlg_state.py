from anamorf.stt import dialog_llm as D
import sys
print({k:v for k,v in D.STATE.items() if k!="who"}, "окно", len(D._WIN), "emit", D._emit, "modid", id(D), "in sys.modules", id(sys.modules.get("anamorf.stt.dialog_llm")))
print("last who:", list(D.STATE["who"].items())[-5:])
