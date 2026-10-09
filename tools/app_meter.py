import time
try:
    from pycaw.pycaw import AudioUtilities, IAudioMeterInformation
    from comtypes import CLSCTX_ALL
except Exception as e:
    print("pycaw NO:", e); raise SystemExit
for _ in range(15):
    row=[]
    for s in AudioUtilities.GetAllSessions():
        try:
            name = s.Process.name() if s.Process else (s.DisplayName or "?")
            m = s._ctl.QueryInterface(IAudioMeterInformation)
            pk = m.GetPeakValue()
            if pk > 0.003: row.append("%s:%.2f" % (name, pk))
        except Exception as e:
            pass
    print(time.strftime("%H:%M:%S"), " ".join(row) or "тихо")
    time.sleep(0.5)
