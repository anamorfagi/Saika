# -*- coding: utf-8 -*-
"""КАКОЙ ИМЕННО ВХОД БРАТЬ (2026-09-01).

«Multiple input devices found» означает, что одно устройство видно
через несколько звуковых подсистем. Печатаем все входы с их
подсистемами и показываем, какой выберет новая логика.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import sounddevice as sd
from anamorf.config import CFG
from anamorf.voice_local import _re_dev

want = CFG.get("mic.device") or ""
want = _re_dev.sub("", str(want)).strip()
print("в настройках: %r\n" % want)

apis = {i: (a.get("name") or "") for i, a in enumerate(sd.query_hostapis())}
print("%-4s %-38s %-14s %s" % ("№", "устройство", "подсистема", "вх"))
hits = []
for i, d in enumerate(sd.query_devices()):
    ch = int(d.get("max_input_channels") or 0)
    if ch < 1:
        continue
    nm = d.get("name") or ""
    api = apis.get(d.get("hostapi"), "?")
    mark = ""
    if want and want.lower() in nm.lower():
        hits.append((i, nm, api))
        mark = "  <-- подходит по имени"
    print("%-4d %-38s %-14s %d%s" % (i, nm[:38], api[:14], ch, mark))

print("\nсовпадений по имени: %d" % len(hits))
from anamorf.voice_local import LocalVoiceLoop as LocalVoice
try:
    pick = LocalVoice._pick_device(sd, want)
except Exception as e:
    pick = "ошибка: %s" % e
print("новая логика выберет:", pick)
if isinstance(pick, int):
    d = sd.query_devices(pick)
    print("   ->", d.get("name"), "|", apis.get(d.get("hostapi"), "?"))
