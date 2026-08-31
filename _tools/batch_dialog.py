# -*- coding: utf-8 -*-
"""ПАКЕТНЫЙ РАЗБОР: час ролика кусками по 5 минут.

По каждому куску: текст со временем слов -> отпечатки голоса -> ward ->
Витерби -> пословная привязка -> реплики. Плюс честная самооценка:
насколько кластеры отделены друг от друга и часто ли метка прыгает.
"""
import io, os, sys, json, time, wave, glob, traceback
import numpy as np

APP = r"C:\AI\Saika\build\ANAMORF-0.2.1\app"
DIR = r"E:\Loading\_atlas_tmp\chunks"
RES = r"E:\Loading\_atlas_tmp\batch"
LOG = r"E:\Loading\_atlas_tmp\batch.log"
MODEL = (r"C:\AI\Saika\models\hf\hub"
         r"\models--mobiuslabsgmbh--faster-whisper-large-v3-turbo"
         r"\snapshots\0a363e9161cbc7ed1431c9597a8ceaf0c4f78fcf")

def note(m):
    with io.open(LOG, "a", encoding="utf-8") as f:
        f.write("[%s] %s\n" % (time.strftime("%H:%M:%S"), m))

try:
    os.makedirs(RES, exist_ok=True)
    io.open(LOG, "a", encoding="utf-8").write("\n=== пакет %s ===\n" % time.strftime("%H:%M:%S"))
    sys.path.insert(0, APP); os.environ["HF_HUB_OFFLINE"] = "1"
    from anamorf.config import CFG
    CFG.set("voiceprint.encoder", "ecapa"); CFG.set("voiceprint.device", "cpu")
    from anamorf.voiceprint.encoder import Encoder
    enc = Encoder(); enc.warmup()
    note("кодировщик %s dim=%s" % (enc.backend, enc.dim))
    from faster_whisper import WhisperModel
    m = WhisperModel(MODEL, device="cpu", compute_type="int8", local_files_only=True)
    note("движок распознавания поднят")
    from scipy.cluster.hierarchy import linkage, fcluster
    from scipy.spatial.distance import pdist

    def process(path, tag):
        segs, info = m.transcribe(path, language="ru", beam_size=5,
                                  word_timestamps=True, vad_filter=True)
        words = []
        for s in segs:
            for wd in (s.words or []):
                words.append({"w": wd.word.strip(), "t0": float(wd.start),
                              "t1": float(wd.end)})
        wf = wave.open(path, "rb"); sr = wf.getframerate()
        a = np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16); wf.close()
        af = a.astype(np.float32) / 32768.0
        nw, nh = int(2.0 * sr), int(0.5 * sr)
        E, T = [], []
        for off in range(0, max(0, len(a) - nw), nh):
            sg = af[off:off + nw]
            if float(np.sqrt((sg * sg).mean())) < 0.006: continue
            try: v, f0 = enc.encode(a[off:off + nw])
            except Exception: continue
            if v is None: continue
            E.append(np.asarray(v, np.float32)); T.append((off + nw / 2) / sr)
        if len(E) < 20:
            note("%s: речи почти нет (%d окон)" % (tag, len(E))); return None
        E = np.array(E); E = E / (np.linalg.norm(E, axis=1, keepdims=True) + 1e-9)
        Z = linkage(pdist(E, metric="cosine"), method="ward")
        lab = list(fcluster(Z, 2.5, criterion="distance"))
        cs = sorted(set(lab)); K = len(cs)
        cent = np.array([E[[i for i in range(len(lab)) if lab[i] == c]].mean(0) for c in cs])
        cent /= (np.linalg.norm(cent, axis=1, keepdims=True) + 1e-9)
        em = E @ cent.T
        n = len(E); dp = np.zeros((n, K)); bk = np.zeros((n, K), dtype=int); dp[0] = em[0]
        for i in range(1, n):
            for k in range(K):
                cand = dp[i - 1] + np.where(np.arange(K) == k, 0.15, 0.0)
                j = int(np.argmax(cand)); bk[i, k] = j; dp[i, k] = cand[j] + em[i, k]
        path_ = [0] * n; path_[-1] = int(np.argmax(dp[-1]))
        for i in range(n - 1, 0, -1): path_[i - 1] = bk[i, path_[i]]
        moved = sum(1 for i in range(n) if cs[path_[i]] != lab[i])
        # разделимость: своя похожесть минус лучшая чужая
        sep = float(np.mean([em[i, path_[i]] - np.max(np.delete(em[i], path_[i]))
                             for i in range(n)]))
        Ta = np.array(T)
        for wd in words:
            wd["spk"] = int(path_[int(np.argmin(np.abs(Ta - (wd["t0"] + wd["t1"]) / 2)))])
        turns = []
        for wd in words:
            if (turns and turns[-1]["spk"] == wd["spk"]
                    and wd["t0"] - turns[-1]["t1"] < 1.2):
                turns[-1]["text"] += " " + wd["w"]; turns[-1]["t1"] = wd["t1"]
            else:
                turns.append({"spk": wd["spk"], "t0": wd["t0"], "t1": wd["t1"], "text": wd["w"]})
        secs = {}
        for t in turns: secs[t["spk"]] = secs.get(t["spk"], 0) + t["t1"] - t["t0"]
        order = sorted(secs, key=lambda k: -secs[k])
        nm = {c: "Голос %d" % (i + 1) for i, c in enumerate(order)}
        with io.open(os.path.join(RES, tag + ".txt"), "w", encoding="utf-8") as f:
            f.write("%s | людей %d | реплик %d | слов %d\n" % (tag, K, len(turns), len(words)))
            f.write("разделимость голосов %.3f | метка переставлена у %d из %d окон\n\n"
                    % (sep, moved, n))
            for c in order: f.write("  %s — %.0f c\n" % (nm[c], secs[c]))
            f.write("\n" + "-" * 66 + "\n\n")
            for t in turns:
                if len(t["text"].strip()) < 2: continue
                f.write("[%6.1f] %-8s %s\n" % (t["t0"], nm[t["spk"]], t["text"].strip()))
        st = {"кусок": tag, "людей": K, "реплик": len(turns), "слов": len(words),
              "разделимость": round(sep, 3), "переставлено": moved, "окон": n,
              "секунды": {nm[c]: round(secs[c]) for c in order}}
        json.dump(st, io.open(os.path.join(RES, tag + ".json"), "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
        note("%s: людей %d, реплик %d, разделимость %.3f, переставлено %d/%d"
             % (tag, K, len(turns), sep, moved, n))
        return st

    allst = []
    for p in sorted(glob.glob(os.path.join(DIR, "ch*.wav"))):
        tag = os.path.splitext(os.path.basename(p))[0]
        if os.path.exists(os.path.join(RES, tag + ".json")):
            note("%s уже готов — пропускаю" % tag); continue
        try:
            st = process(p, tag)
            if st: allst.append(st)
        except Exception:
            note("%s ОШИБКА:\n%s" % (tag, traceback.format_exc()[:900]))
    note("ПАКЕТ ЗАВЕРШЁН, кусков обработано %d" % len(allst))
except Exception:
    note("ОШИБКА:\n" + traceback.format_exc())
