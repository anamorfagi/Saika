from anamorf import knobs as K, config as C
import json
for k, v in (("stt.turns", False),):
    try:
        K.set(k, v); print("knob", k, v)
    except Exception as e:
        C.CFG.set(k, v); print("cfg", k, v, e)
