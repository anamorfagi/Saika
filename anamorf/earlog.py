"""ЖУРНАЛ СЛУХА — час записи, на выходе отчёт: какие были звуки и голоса.

2026-07-28, просьба владельца: «включить на час и получить метки — на что
похожи звуки, сколько было голосов и их спектры отдельно».

ЧЕМ ЭТО ОТЛИЧАЕТСЯ ОТ ЖИВОЙ ПАНЕЛИ. Панель показывает «сейчас»: точка едет,
спектр бежит, лента помнит минуту. Живя в моменте, нельзя ответить на вопрос
«а кто вообще был в комнате за вечер и что там щёлкало». Для этого нужна
память и разбор ПОСЛЕ, а не во время: пока звук идёт, неизвестно, окажется
ли этот голос новым человеком или тем же самым, что говорил час назад.

ЧТО КОПИМ. Ровно то, что и так считается в конвейере отпечатка, — эмбеддинг
голоса и мел-профиль звука. Ни одной лишней модели, ни одного лишнего окна
FFT: журнал подписывается на уже готовые события. Час записи — это порядка
десяти тысяч записей по сотне чисел, единицы мегабайт.

ЗВУК НЕ ХРАНИМ. Только числа. Час звука с микрофона в квартире — это чужие
разговоры, телевизор и всё остальное; складывать это на диск ради отчёта
про щелчки было бы не тем разменом. Из мел-профиля речь не восстановишь.

КАК СЧИТАЮТСЯ ГОЛОСА. Агломеративная кластеризация по косинусу: начинаем с
того, что каждый кусок — свой голос, и склеиваем ближайшие пары, пока они
похожи сильнее порога. Порог берём от уже записанных эталонов, если они есть
(мы знаем, как человек похож сам на себя), иначе по умолчанию. Кластеры
мельче трёх кусков выбрасываем — это обрывки и ошибки, а не люди.

КАК НАЗЫВАЮТСЯ ЗВУКИ. Пока без нейросети: имя собирается из формы спектра —
длительность, тональность, где центр тяжести. «Короткий щелчок, высокий»,
«ровный гул, низкий». Это честное описание того, что реально измерено. Когда
подключим модель меток из HEARING.md (YAMNet / PANNs / CLAP), она встанет
сюда же через label_fn и заменит описания на настоящие названия — «клавиши»,
«посуда», «дождь». Формат отчёта менять не придётся.
"""
import json
import logging
import time
from pathlib import Path

import numpy as np

from anamorf.config import CFG, ROOT, DATA_ROOT

log = logging.getLogger("saika.earlog")

DIR = DATA_ROOT / "data" / "earlog"
MAX_ITEMS = 40000          # ~ несколько часов; дальше кольцо
MIN_CLUSTER = 3            # меньше — обрывки, а не отдельный голос/звук


class EarLog:
    def __init__(self):
        self.on = False
        self.t0 = 0.0
        self.until = 0.0
        self.voices: list = []      # (ts, emb, mel, pitch, energy, who)
        self.sounds: list = []      # (ts, mel, energy, parts)
        self.label_fn = None        # сюда встанет модель меток, когда появится
        self.last_report = ""
        # эмбеддинги по кластерам последнего разбора: из них можно ЗАПОМНИТЬ
        # найденный голос как знакомый — «услышала пятерых, вот этот пусть
        # будет Кимико». Это и есть обучение по факту прослушанного.
        self._clusters: dict = {}

    # ------------------------------------------------------------ запись
    def start(self, minutes=60.0, keep=False):
        if not keep:
            self.voices, self.sounds = [], []
        self.on = True
        self.t0 = time.time()
        self.until = self.t0 + minutes * 60.0
        log.info("Журнал слуха: пишу %.0f минут", minutes)
        return self.status()

    def stop(self):
        self.on = False
        log.info("Журнал слуха: остановлен, голосов %d, звуков %d",
                 len(self.voices), len(self.sounds))
        return self.status()

    def _tick(self):
        if self.on and self.until and time.time() > self.until:
            self.on = False
            log.info("Журнал слуха: время вышло")
        return self.on

    def note_voice(self, emb, mel, pitch, energy, who):
        if not self._tick():
            return
        self.voices.append((time.time(), np.asarray(emb, np.float32),
                            np.asarray(mel, np.float32), float(pitch),
                            float(energy), who or ""))
        del self.voices[:-MAX_ITEMS]

    def note_sound(self, mel, energy, parts):
        if not self._tick():
            return
        self.sounds.append((time.time(), np.asarray(mel, np.float32),
                            float(energy), dict(parts or {})))
        del self.sounds[:-MAX_ITEMS]

    def status(self):
        left = max(0.0, self.until - time.time()) if self.on else 0.0
        return {
            "on": bool(self.on),
            "started": round(self.t0, 1),
            "left_s": int(left),
            "elapsed_s": int(time.time() - self.t0) if self.t0 else 0,
            "voices": len(self.voices),
            "sounds": len(self.sounds),
            "report": self.last_report,
            "labels": bool(self.label_fn),
        }

    # -------------------------------------------------------- кластеризация
    @staticmethod
    def _cluster(vecs, thr, center=False):
        """Агломеративная склейка по косинусу. Возвращает метки кластеров.

        O(n²) по памяти на матрицу похожести — при десятке тысяч кусков это
        сотни мегабайт, поэтому для больших наборов прореживаем: точность
        «сколько было голосов» от каждого сотого куска не меняется."""
        n = len(vecs)
        if n == 0:
            return np.zeros(0, int)
        X = np.asarray(vecs, np.float32)
        if center:
            # ДЛЯ ЗВУКОВ СРАВНИВАЕМ ФОРМУ, А НЕ УРОВЕНЬ. Мел-профили любых
            # звуков похожи «в целом» — энергия падает с частотой, косинус у
            # всех пар получается 0.9+, и щелчок склеивается с гулом. Вычли у
            # каждого профиля его собственное среднее — осталась форма, и
            # косинус превратился в корреляцию: горбы против горбов.
            X = X - X.mean(axis=1, keepdims=True)
        nrm = np.linalg.norm(X, axis=1, keepdims=True)
        X = X / np.maximum(nrm, 1e-9)
        sim = X @ X.T
        lab = np.arange(n)
        # склеиваем, пока есть пара кластеров ближе порога (среднее сходство)
        for _ in range(n):
            uniq = np.unique(lab)
            if len(uniq) < 2:
                break
            best, pair = -1.0, None
            for i in range(len(uniq)):
                mi = lab == uniq[i]
                for j in range(i + 1, len(uniq)):
                    mj = lab == uniq[j]
                    s = float(sim[np.ix_(mi, mj)].mean())
                    if s > best:
                        best, pair = s, (uniq[i], uniq[j])
            if pair is None or best < thr:
                break
            lab[lab == pair[1]] = pair[0]
        # перенумеровать по размеру
        order = sorted(np.unique(lab), key=lambda u: -int((lab == u).sum()))
        remap = {u: k for k, u in enumerate(order)}
        return np.array([remap[v] for v in lab], int)

    @staticmethod
    def _thin(items, cap):
        """Проредить равномерно по времени, а не «взять первые N»: за час
        человек говорит в разные моменты, и обрезка по началу превратила бы
        отчёт в рассказ про первые десять минут."""
        if len(items) <= cap:
            return items, 1
        step = len(items) / cap
        idx = [int(i * step) for i in range(cap)]
        return [items[i] for i in idx], step

    # -------------------------------------------------------------- разбор
    def analyse(self, reg=None):
        """Собрать отчёт. reg — реестр известных голосов (может быть None)."""
        self._clusters = {}
        out = {"from": self.t0, "to": time.time(),
               "voices": [], "sounds": [],
               "n_voice_items": len(self.voices), "n_sound_items": len(self.sounds)}

        # ── голоса ────────────────────────────────────────────────────────
        vs, vstep = self._thin(self.voices, int(CFG.get("earlog.max_cluster", 900)))
        if vs:
            thr = float(CFG.get("earlog.voice_thr", 0.0))
            if not thr and reg is not None and reg.speakers:
                # порог из реальных данных: насколько ЗАПИСАННЫЙ человек похож
                # сам на себя. Так число голосов не зависит от движка энкодера
                mus = []
                for name in reg.speakers:
                    try:
                        _c, mu, sd = reg._prof(name)
                        mus.append(mu - 2.0 * sd)
                    except Exception:
                        pass
                thr = float(np.mean(mus)) if mus else 0.0
            thr = thr or 0.78
            lab = self._cluster([v[1] for v in vs], thr)
            for k in np.unique(lab):
                m = lab == k
                items = [vs[i] for i in np.where(m)[0]]
                if len(items) < MIN_CLUSTER:
                    continue
                embs = np.vstack([it[1] for it in items])
                self._clusters[int(k) + 1] = embs
                mel = np.mean([it[2] for it in items], axis=0)
                pit = [it[3] for it in items if it[3] > 40]
                names = [it[5] for it in items if it[5]]
                known = max(set(names), key=names.count) if names else ""
                out["voices"].append({
                    "id": int(k) + 1,
                    "known": known,
                    "segments": int(len(items) * vstep),
                    "seconds": round(len(items) * vstep * 0.32, 1),
                    "first": items[0][0], "last": items[-1][0],
                    "pitch_lo": int(min(pit)) if pit else 0,
                    "pitch_hi": int(max(pit)) if pit else 0,
                    "pitch_med": int(np.median(pit)) if pit else 0,
                    "mel": [round(float(x), 3) for x in mel],
                    "spread": round(float(np.mean(
                        embs @ (embs.mean(axis=0) /
                                max(1e-9, np.linalg.norm(embs.mean(axis=0)))))), 3),
                })

        # ── звуки ─────────────────────────────────────────────────────────
        ss, sstep = self._thin(self.sounds, int(CFG.get("earlog.max_cluster", 900)))
        if ss:
            # ФОРМА СПЕКТРА ПЛЮС ХАРАКТЕР ВО ВРЕМЕНИ. Одного усреднённого
            # мела мало: щелчок мышки и стук по столу дают почти одинаковый
            # профиль (оба — широкополосный всплеск), корреляция между ними
            # выше, чем внутри своей же группы. Дописываем к вектору признаки
            # времени и тональности (длительность, тон, ровность, доля низа)
            # с весом — по ним ударное отделяется от тянущегося.
            feats = []
            for it in ss:
                m = np.asarray(it[1], np.float32)
                m = m - m.mean()
                m = m / max(1e-6, float(np.linalg.norm(m)))
                pr = it[3] or {}
                extra = np.array([pr.get("hold", .5), pr.get("tone", .5),
                                  pr.get("shape", .5), pr.get("low", .5)],
                                 np.float32) * 1.6
                feats.append(np.concatenate([m, extra]))
            lab = self._cluster(feats, float(CFG.get("earlog.sound_thr", 0.45)))
            for k in np.unique(lab):
                m = lab == k
                items = [ss[i] for i in np.where(m)[0]]
                if len(items) < MIN_CLUSTER:
                    continue
                mel = np.mean([it[1] for it in items], axis=0)
                parts = items[len(items) // 2][3]
                out["sounds"].append({
                    "id": int(k) + 1,
                    "label": self._name_sound(mel, parts),
                    "count": int(len(items) * sstep),
                    "first": items[0][0], "last": items[-1][0],
                    "energy": round(float(np.mean([it[2] for it in items])), 3),
                    "mel": [round(float(x), 3) for x in mel],
                })
        out["voices"].sort(key=lambda v: -v["segments"])
        out["sounds"].sort(key=lambda s: -s["count"])
        return out

    def _name_sound(self, mel, parts):
        """Описание звука из того, что измерено. Когда появится модель меток,
        она подменит это настоящими названиями через label_fn."""
        if self.label_fn:
            try:
                got = self.label_fn(mel, parts)
                if got:
                    return got
            except Exception as e:
                log.debug("модель меток не ответила: %s", e)
        n = len(mel)
        idx = np.arange(n)
        centre = float((mel * idx).sum() / max(1e-9, mel.sum())) / max(1, n - 1)
        hold = float(parts.get("hold", 0.5))
        shape = float(parts.get("shape", 0.5))
        low = float(parts.get("low", 0.5))
        where = ("низкий" if centre < 0.33 else
                 "средний" if centre < 0.62 else "высокий")
        tone = float(parts.get("tone", 0.0))
        if hold < 0.40 and tone < 0.2:
            # короткий и без тона — ударный звук. Различаем по тому, где
            # энергия: клавиши и мышь звенят сверху, кулак по столу гудит снизу
            kind = "щелчки" if centre > 0.45 else "стук"
        elif tone > 0.6 and shape > 0.5:
            kind = "гул"
        elif shape < 0.3:
            kind = "шипение"
        else:
            kind = "шорох"
        return f"{kind}, {where}"

    def adopt(self, vid: int, name: str, reg):
        """Запомнить найденный в отчёте голос как знакомого.

        ЗАЧЕМ. Кластеризация отвечает «сколько голосов», но имён не знает и
        знать не может. А человек знает: посмотрел серию — вот этот кластер
        главный герой. Один клик, и дальше она узнаёт его вживую, наравне с
        записанными вручную."""
        embs = self._clusters.get(int(vid))
        if embs is None or not len(embs):
            return {"ok": False, "error": "такого голоса в отчёте нет"}
        name = (name or "").strip()[:32]
        if not name:
            return {"ok": False, "error": "нужно имя"}
        n = reg.enroll(name, np.asarray(embs, np.float32))
        reg.dirty = True
        reg.save()
        log.info("Журнал слуха: голос %s запомнен как «%s» (%d векторов)",
                 vid, name, n)
        return {"ok": True, "name": name, "vectors": int(n)}

    # -------------------------------------------------------------- отчёт
    def report(self, reg=None):
        data = self.analyse(reg)
        DIR.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d_%H%M", time.localtime(data["to"]))
        path = DIR / f"report_{stamp}.html"
        path.write_text(_html(data), "utf-8")
        (DIR / f"report_{stamp}.json").write_text(
            json.dumps(data, ensure_ascii=False), "utf-8")
        self.last_report = path.name
        log.info("Журнал слуха: отчёт %s (голосов %d, звуков %d)",
                 path.name, len(data["voices"]), len(data["sounds"]))
        return {"file": path.name, **data}


# ─────────────────────────────── отчёт как страница ───────────────────────
def _bars(mel, color):
    """Спектр столбиками прямо в SVG: отчёт должен открываться сам по себе,
    без сервера, скриптов и интернета — файл можно просто переслать."""
    w, h, n = 260, 54, len(mel) or 1
    bw = w / n
    parts = []
    for i, v in enumerate(mel):
        bh = max(1.0, float(v) * (h - 4))
        parts.append(f'<rect x="{i*bw:.1f}" y="{h-bh:.1f}" width="{bw*0.86:.1f}" '
                     f'height="{bh:.1f}" fill="{color}" opacity="{0.35+0.6*float(v):.2f}"/>')
    return (f'<svg viewBox="0 0 {w} {h}" width="{w}" height="{h}">'
            + "".join(parts) + "</svg>")


def _dur(a, b):
    m = max(0, int((b - a) / 60))
    return f"{m} мин" if m else "меньше минуты"


# Скрипт отчёта держим ОТДЕЛЬНОЙ строкой, а не внутри f-строки: в f-строке
# каждую фигурную скобку JS пришлось бы удваивать, и первая же правка кода
# превратилась бы в ребус.
_ADOPT_JS = """
<script>
/* «Запомнить» работает, когда отчёт открыт из интерфейса Сайки (по ссылке
   /earlog/...): тогда это тот же адрес, и запрос доходит. Открытый как
   отдельный файл с диска отчёт остаётся просто отчётом. */
async function adopt(id){
  const el = document.getElementById('n' + id);
  const name = (el && el.value || '').trim();
  if(!name){ el && el.focus(); return; }
  try{
    const r = await fetch('/api/earlog/adopt', {method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({id: id, name: name})});
    const d = await r.json();
    el.value = d.ok ? 'запомнила: ' + d.name + ' (' + d.vectors + ' векторов)'
                    : (d.error || 'не вышло');
    el.disabled = true;
  }catch(e){ el.value = 'нужно открыть отчёт из интерфейса Сайки'; }
}
</script>
"""


def _html(d):
    C = ["#4dd0e1", "#ffb74d", "#ba68c8", "#81c784", "#f06292", "#9fa8da"]
    when = time.strftime("%d.%m %H:%M", time.localtime(d["from"]))
    rows_v = ""
    for i, v in enumerate(d["voices"]):
        col = C[i % len(C)]
        rows_v += f"""<div class="card">
          <div class="hd"><span class="dot" style="background:{col}"></span>
            <b>{'Голос ' + str(v['id']) if not v['known'] else v['known']}</b>
            <span class="dim">{v['seconds']} с речи · {v['segments']} кусков</span></div>
          <div class="row"><input id="n{v['id']}" placeholder="назвать этот голос">
            <button onclick="adopt({v['id']})">запомнить</button></div>
          <div class="sp">{_bars(v['mel'], col)}</div>
          <div class="dim">тон {v['pitch_med']} Гц (от {v['pitch_lo']} до
            {v['pitch_hi']}) · слышно с {time.strftime('%H:%M', time.localtime(v['first']))}
            по {time.strftime('%H:%M', time.localtime(v['last']))} ·
            плотность голоса {v['spread']}</div></div>"""
    rows_s = ""
    for i, s in enumerate(d["sounds"]):
        rows_s += f"""<div class="card">
          <div class="hd"><b>{s['label']}</b>
            <span class="dim">{s['count']} раз</span></div>
          <div class="sp">{_bars(s['mel'], '#8892a6')}</div>
          <div class="dim">с {time.strftime('%H:%M', time.localtime(s['first']))}
            по {time.strftime('%H:%M', time.localtime(s['last']))} ·
            громкость {int(s['energy']*100)}%</div></div>"""
    if not rows_v:
        rows_v = '<div class="dim">за это время голосов не набралось</div>'
    if not rows_s:
        rows_s = '<div class="dim">посторонних звуков не набралось</div>'
    return f"""<!doctype html><html lang="ru"><head><meta charset="utf-8">
<title>Слух Сайки — {when}</title><style>
body{{margin:0;padding:26px;background:#0b0d16;color:#e9e9ed;
  font:14px/1.5 system-ui,-apple-system,Segoe UI,sans-serif}}
h1{{font-size:19px;margin:0 0 4px}} h2{{font-size:13px;text-transform:uppercase;
  letter-spacing:.12em;color:rgba(233,233,237,.45);margin:26px 0 10px}}
.dim{{color:rgba(233,233,237,.5);font-size:12px}}
.wrap{{max-width:900px;margin:0 auto}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:12px}}
.card{{background:rgba(255,255,255,.045);border:1px solid rgba(255,255,255,.08);
  border-radius:16px;padding:12px 14px}}
.hd{{display:flex;align-items:center;gap:8px;margin-bottom:6px}}
.dot{{width:9px;height:9px;border-radius:50%;flex:none}}
.hd .dim{{margin-left:auto}}
.sp{{background:rgba(0,0,0,.25);border-radius:10px;padding:4px;margin:6px 0;
  overflow:hidden}}
.sp svg{{width:100%;height:54px;display:block}}
.row{{display:flex;gap:6px;margin:6px 0 2px}}
.row input{{flex:1;min-width:0;background:rgba(255,255,255,.06);color:#e9e9ed;
  border:1px solid rgba(255,255,255,.14);border-radius:9px;padding:5px 8px;
  font:12px inherit;outline:none}}
.row button{{background:rgba(77,208,225,.14);color:#9fe7f0;cursor:pointer;
  border:1px solid rgba(77,208,225,.45);border-radius:9px;padding:5px 10px;
  font:12px inherit}}
.row button:hover{{background:rgba(77,208,225,.24)}}
</style></head><body><div class="wrap">
<h1>Что слышала Сайка</h1>
<div class="dim">{when} · {_dur(d['from'], d['to'])} ·
  кусков речи {d['n_voice_items']}, посторонних звуков {d['n_sound_items']}</div>
<h2>Голоса — {len(d['voices'])}</h2><div class="grid">{rows_v}</div>
<h2>Звуки — {len(d['sounds'])}</h2><div class="grid">{rows_s}</div>
<h2>Как это считалось</h2>
<div class="dim">Каждые ~0.32 с звук превращался в вектор. Речь и не-речь
разделены по строению звука (тон, форма спектра, доля низа, длительность).
Голоса собраны в группы по близости векторов — «сколько голосов» это сколько
получилось групп, а не сколько распознано людей. Спектр в карточке —
усреднённый мел-профиль группы: слева низкие частоты, справа высокие.
Названия звуков описательные, из измеренной формы; настоящие названия
появятся, когда подключим модель меток. Сам звук не сохранялся — только
числа.</div>
</div>""" + _ADOPT_JS + """</body></html>"""


EARLOG = EarLog()
