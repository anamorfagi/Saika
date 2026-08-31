# -*- coding: utf-8 -*-
import io, sys
p = sys.argv[1]
s = io.open(p, encoding='utf-8').read()

a = '''                _emit({"type": "voiceprint_met", "who": nm})
                refit()'''
b = '''                _emit({"type": "voiceprint_met", "who": nm})
                merge_autos()
                refit()'''
assert s.count(a) == 1
s = s.replace(a, b)

anchor = "def enabled():"
add = '''def merge_autos(thr: float = 0.0) -> list:
    """СВОДИТЬ РАЗВАЛИВШИЙСЯ ГОЛОС ОБРАТНО (27.08.2026, владелец: «голосов
    он там нахуячил просто пиздец» — на двух людях из ролика завелось
    четырнадцать «Голосов»).

    Почему так выходит. Порог узнавания у каждого голоса свой и считается
    от РАЗБРОСА ЕГО СОБСТВЕННЫХ точек: mu - 2.5*sd. У свежего автоголоса
    точек мало и они из одной фразы — разброс крошечный, порог задран почти
    вплотную к центру. Следующая фраза того же человека до него уже не
    дотягивается, и заводится ещё один «Голос». Дальше по кругу.

    Лечим не порогом, а сведением: после каждого знакомства сравниваем
    центры всех автоматических голосов между собой и сливаем те, что стоят
    ближе, чем вообще стоят разные люди. Слитый эталон становится шире —
    порог опускается сам, и третья фраза уже узнаётся."""
    try:
        reg = S.reg
        auto = [n for n, v in list(reg.speakers.items())
                if v.get("auto") and not v.get("pinned")]
        if len(auto) < 2:
            return []
        dim = int(reg.speakers[auto[0]]["embs"].shape[1])
        if not thr:
            thr = float(CFG.get("voiceprint.merge_cos",
                                0.55 if dim >= 128 else 0.82))
        cen = {}
        for n in auto:
            c = reg.centroid(n)
            if c is None:
                continue
            cen[n] = np.asarray(c, dtype=np.float32)
        names = [n for n in auto if n in cen]
        # порядок по числу векторов: крупный голос становится приёмником
        names.sort(key=lambda n: -int(reg.speakers[n]["embs"].shape[0]))
        done, gone = [], set()
        for i, dst in enumerate(names):
            if dst in gone:
                continue
            for src in names[i + 1:]:
                if src in gone or src not in cen or dst not in cen:
                    continue
                c1, c2 = cen[dst], cen[src]
                if c1.shape != c2.shape:
                    continue
                sim = float(c1 @ c2 / max(1e-9, float(np.linalg.norm(c1)) *
                                          float(np.linalg.norm(c2))))
                if sim < thr:
                    continue
                r = reg.merge(src, dst)
                if not r.get("ok"):
                    continue
                # слияние руками закрепляет имя; наше — служебное: голос
                # остаётся автоматическим и может слиться дальше
                v = reg.speakers.get(dst) or {}
                v["pinned"] = False
                v["auto"] = True
                gone.add(src)
                _c = reg.centroid(dst)
                if _c is not None:
                    cen[dst] = np.asarray(_c, dtype=np.float32)
                done.append((src, dst, round(sim, 3)))
        if done:
            reg.save()
            log.info("Отпечаток голоса: свела автоголоса — %s",
                     ", ".join("%s -> %s (%.2f)" % d for d in done))
            _emit({"type": "voiceprint_merged", "pairs": done})
        return done
    except Exception as e:
        log.debug("сведение автоголосов пропущено: %s", e)
        return []


def enabled():'''
assert s.count(anchor) == 1
s = s.replace(anchor, add, 1)
io.open(p, 'w', encoding='utf-8').write(s)
print('ok')
