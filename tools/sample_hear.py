import sys, time, threading, collections, traceback
names = {t.ident: t.name for t in threading.enumerate()}
want = [i for i, n in names.items() if n in ("hear", "stt", "tone", "sys-audio", "ears", "voiceprint")]
hist = collections.Counter(); N = 80
for _ in range(N):
    fr = sys._current_frames()
    for i in want:
        f = fr.get(i)
        if f is None: continue
        st = traceback.extract_stack(f)[-4:]
        key = names[i] + " | " + " <- ".join("%s:%d %s" % (s.filename.rsplit("\\",1)[-1], s.lineno, s.name) for s in reversed(st))
        hist[key] += 1
    time.sleep(0.05)
for k, v in hist.most_common(14): print("%3d%%  %s" % (100*v//N, k[:230]))
try: print("hear_q:", _AUDIO_LAB["q"].qsize(), "seg_q?", HEAR_STAT.get("lag"))
except Exception as e: print(e)
