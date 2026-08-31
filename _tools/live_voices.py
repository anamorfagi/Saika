# -*- coding: utf-8 -*-
"""СКВОЗНОЙ ПРОГОН: играем в комнату диалог нескольких людей и смотрим,
заведёт ли система голоса сама. Ничего не подкручиваем — пороги штатные."""
import io, os, json, time, urllib.request, traceback, threading
OUT = r"E:\Loading\_atlas_tmp"
LOG = os.path.join(OUT, "live_voices.log")
def w(m):
    with io.open(LOG, "a", encoding="utf-8") as f:
        f.write("[%s] %s\n" % (time.strftime("%H:%M:%S"), m))
def vp():
    try:
        r = urllib.request.urlopen("http://127.0.0.1:8765/api/voiceprint", timeout=6)
        return json.loads(r.read().decode("utf-8"))
    except Exception as e:
        return {"ОШИБКА": repr(e)[:120]}
try:
    io.open(LOG, "w", encoding="utf-8").write("")
    d = vp()
    w("до прогона: голосов %d, облако %s, услышано %s c, порог знакомства %s"
      % (len(d.get("speakers") or {}), d.get("cloud"), d.get("heard_s"),
         d.get("auto_meet_n", "?")))
    wav = os.path.join(OUT, "crowd.wav")
    w("играю диалог: %s" % wav)
    import winsound
    winsound.PlaySound(wav, winsound.SND_FILENAME | winsound.SND_ASYNC)
    for i in range(14):
        time.sleep(30)
        d = vp()
        sp = d.get("speakers") or {}
        w("+%3d c | голосов %d %s | облако %s | услышано %s c | сейчас: %s"
          % ((i + 1) * 30, len(sp), list(sp.keys())[:6], d.get("cloud"),
             d.get("heard_s"), (d.get("last") or {}).get("who") or "—"))
    winsound.PlaySound(None, 0)
    d = vp()
    json.dump(d, io.open(os.path.join(OUT, "voices_after.json"), "w",
                         encoding="utf-8"), ensure_ascii=False, indent=1)
    w("ИТОГ: голосов %d -> %s" % (len(d.get("speakers") or {}),
                                  list((d.get("speakers") or {}).keys())))
    w("ГОТОВО")
except Exception:
    w("ОШИБКА:\n" + traceback.format_exc())
