# -*- coding: utf-8 -*-
"""ОБЛАЧКА ДИАЛОГА: кто что сказал, по-настоящему.

Тракт: faster-whisper даёт текст со временем каждого СЛОВА -> ECAPA даёт
отпечаток голоса на скользящем окне -> ward-кластеризация разводит людей ->
Витерби убирает одиночные перескоки -> каждое слово получает говорящего по
своему времени, и слова склеиваются в реплики.

Пословная привязка — принципиальный момент: раньше метка ставилась на целую
фразу, и если внутри неё сменился человек, весь кусок уезжал не тому.
"""
import io, os, sys, json, time, wave, traceback
import numpy as np

APP = r"C:\AI\Saika\build\ANAMORF-0.2.1\app"
WAV = r"E:\Loading\_atlas_tmp\crowd.wav"
OUT = r"E:\Loading\_atlas_tmp\dialog.json"
TXT = r"E:\Loading\_atlas_tmp\dialog.txt"
LOG = r"E:\Loading\_atlas_tmp\dialog.log"
MODEL = (r"C:\AI\Saika\models\hf\hub"
         r"\models--mobiuslabsgmbh--faster-whisper-large-v3-turbo"
         r"\snapshots\0a363e9161cbc7ed1431c9597a8ceaf0c4f78fcf")

def note(m):
    with io.open(LOG, "a", encoding="utf-8") as f:
        f.write("[%s] %s\n" % (time.strftime("%H:%M:%S"), m))

try:
    io.open(LOG, "w", encoding="utf-8").write("")
    note("старт")
    sys.path.insert(0, APP); os.environ["HF_HUB_OFFLINE"] = "1"
    from anamorf.config import CFG
    CFG.set("voiceprint.encoder", "ecapa"); CFG.set("voiceprint.device", "cpu")
    from anamorf.voiceprint.encoder import Encoder
    enc = Encoder(); enc.warmup()
    note("кодировщик %s dim=%s" % (enc.backend, enc.dim))

    # ── 1. слова со временем ──
    from faster_whisper import WhisperModel
    m = WhisperModel(MODEL, device="cpu", compute_type="int8", local_files_only=True)
    note("распознаю речь…")
    segs, info = m.transcribe(WAV, language="ru", beam_size=5,
                              word_timestamps=True, vad_filter=True)
    words = []
    for s in segs:
        for wd in (s.words or []):
            words.append({"w": wd.word.strip(), "t0": float(wd.start),
                          "t1": float(wd.end)})
    note("слов: %d, длительность %.0f c" % (len(words), info.duration))

    # ── 2. отпечатки голоса скользящим окном ──
    wf = wave.open(WAV, "rb"); sr = wf.getframerate()
    a = np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16); wf.close()
    af = a.astype(np.float32) / 32768.0
    WIN, HOP = 2.0, 0.5
    nw, nh = int(WIN * sr), int(HOP * sr)
    E, T = [], []
    for off in range(0, max(0, len(a) - nw), nh):
        seg = af[off:off + nw]
        if float(np.sqrt((seg * seg).mean())) < 0.006: continue
        try: v, f0 = enc.encode(a[off:off + nw])
        except Exception: continue
        if v is None: continue
        E.append(np.asarray(v, np.float32)); T.append(((off + nw / 2) / sr))
    E = np.array(E); E = E / (np.linalg.norm(E, axis=1, keepdims=True) + 1e-9)
    note("отпечатков: %s" % (E.shape,))

    # ── 3. ward + Витерби (настройки со стенда) ──
    from scipy.cluster.hierarchy import linkage, fcluster
    from scipy.spatial.distance import pdist
    Z = linkage(pdist(E, metric="cosine"), method="ward")
    lab = list(fcluster(Z, 2.5, criterion="distance"))
    cs = sorted(set(lab)); K = len(cs)
    note("людей найдено: %d" % K)
    cent = np.array([E[[i for i in range(len(lab)) if lab[i] == c]].mean(0) for c in cs])
    cent /= (np.linalg.norm(cent, axis=1, keepdims=True) + 1e-9)
    em = E @ cent.T
    stay = 0.15; n = len(E)
    dp = np.zeros((n, K)); bk = np.zeros((n, K), dtype=int); dp[0] = em[0]
    for i in range(1, n):
        for k in range(K):
            cand = dp[i - 1] + np.where(np.arange(K) == k, stay, 0.0)
            j = int(np.argmax(cand)); bk[i, k] = j; dp[i, k] = cand[j] + em[i, k]
    path = [0] * n; path[-1] = int(np.argmax(dp[-1]))
    for i in range(n - 1, 0, -1): path[i - 1] = bk[i, path[i]]
    T = np.array(T)

    # ── 4. каждому СЛОВУ — свой человек по его времени ──
    def who_at(t):
        if not len(T): return 0
        return int(path[int(np.argmin(np.abs(T - t)))])
    for wd in words:
        wd["spk"] = who_at((wd["t0"] + wd["t1"]) / 2)

    # ── 5. склейка слов в реплики: рвём при смене человека или паузе ──
    turns = []
    for wd in words:
        if (turns and turns[-1]["spk"] == wd["spk"]
                and wd["t0"] - turns[-1]["t1"] < 1.2):
            turns[-1]["text"] += " " + wd["w"]; turns[-1]["t1"] = wd["t1"]
        else:
            turns.append({"spk": wd["spk"], "t0": wd["t0"], "t1": wd["t1"],
                          "text": wd["w"]})
    note("реплик: %d" % len(turns))

    secs = {}
    for t in turns: secs[t["spk"]] = secs.get(t["spk"], 0) + t["t1"] - t["t0"]
    order = sorted(secs, key=lambda k: -secs[k])
    name = {c: "Голос %d" % (i + 1) for i, c in enumerate(order)}

    with io.open(TXT, "w", encoding="utf-8") as f:
        f.write("РАЗБОР ДИАЛОГА — кто что сказал\n")
        f.write("людей: %d | реплик: %d | слов: %d\n\n" % (K, len(turns), len(words)))
        for c in order:
            f.write("  %s — %.0f c речи\n" % (name[c], secs[c]))
        f.write("\n" + "-" * 70 + "\n\n")
        for t in turns:
            if len(t["text"].strip()) < 2: continue
            f.write("[%6.1f] %-9s %s\n" % (t["t0"], name[t["spk"]], t["text"].strip()))
    json.dump({"людей": K, "реплики": [
        {"кто": name[t["spk"]], "с": round(t["t0"], 2), "по": round(t["t1"], 2),
         "текст": t["text"].strip()} for t in turns]},
        io.open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    note("ГОТОВО -> %s" % TXT)
except Exception:
    note("ОШИБКА:\n" + traceback.format_exc())
