from anamorf import procaudio
import json; print(json.dumps(procaudio.status(), ensure_ascii=False))
print("sys_vad apps:", list((SYS_VAD.get("apps") or {}).keys()))
