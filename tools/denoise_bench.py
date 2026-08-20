"""Стенд шумодава: прогнать одну запись через все движки и сравнить честно.

ЗАЧЕМ. «Шумодав вкл» — это не ответ на вопрос «работает ли он». На слух
шумоподавление всегда кажется работающим: тише стало — значит помогло. А
помогло ли РАСПОЗНАВАНИЮ — вопрос отдельный, и ответ часто «нет»: движок,
который чистит агрессивно, съедает согласные, и STT начинает ошибаться там,
где раньше не ошибался. Поэтому здесь меряются четыре вещи сразу:

  ТИШИНА   — на сколько дБ упал шум в паузах. Ради этого всё и затевалось.
  РЕЧЬ     — на сколько дБ просела сама речь. Идеал — ноль.
  СХОДСТВО — насколько выход похож на ЧИСТУЮ речь (с выравниванием задержки:
             спектральные движки задерживают звук на окно, и без сдвига
             корреляция врёт про «всё сломано»).
  ЦЕНА     — миллисекунд обработки на секунду звука НА ЭТОМ ЖЕЛЕЗЕ. Всё, что
             больше ~50 мс/с, в живом конвейере слуха будет заметно.

ЗАПУСК:
  python -m tools.denoise_bench                 — синтетика (работает всегда)
  python -m tools.denoise_bench --rec 15        — записать 15с с микрофона
  python -m tools.denoise_bench --wav rec.wav   — взять свой файл
  python -m tools.denoise_bench --stt           — ещё и прогнать через слух
  python -m tools.denoise_bench --save out/     — сохранить результаты в wav

Синтетика честная настолько, насколько это возможно без микрофона: речь
собирается формантным синтезом, а шум — из тех источников, что реально
портят жизнь дома (гул 50 Гц, кулер, шипение, щелчки клавиатуры). Но
итоговое решение всё равно принимай по СВОЕЙ записи: главное свойство
шумодава — как он ведёт себя именно на твоём микрофоне в твоей комнате.
"""
import argparse
import sys
import time
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from anamorf.config import CFG                       # noqa: E402
from anamorf import denoise as D                     # noqa: E402

SR = 16000


# ─────────────────────────────── материал ────────────────────────────────
def synth_material(seconds=14.0, seed=7, snr_db=12.0):
    """Речь с паузами + шум комнаты. Возвращает (микс, чистая речь, метки)."""
    from tools.voiceprint_selftest import synth, VOICES
    rng = np.random.default_rng(seed)
    n = int(SR * seconds)
    clean = np.zeros(n, np.float32)
    marks = np.zeros(n, bool)          # True там, где говорят
    pos = int(SR * 1.2)                # начинаем с паузы: профилю надо учиться
    voices = list(VOICES)
    k = 0
    while pos < n - SR:
        dur = float(rng.uniform(1.4, 2.6))
        seg = synth(seconds=dur, seed=int(rng.integers(0, 9999)), wobble=0.06,
                    **VOICES[voices[k % len(voices)]]).astype(np.float32) / 32768.0
        end = min(n, pos + len(seg))
        clean[pos:end] = seg[:end - pos]
        marks[pos:end] = True
        pos = end + int(SR * rng.uniform(0.7, 1.4))
        k += 1

    t = np.arange(n) / SR
    noise = (0.030 * np.sin(2 * np.pi * 50 * t)          # наводка сети
             + 0.018 * np.sin(2 * np.pi * 100 * t)       # её гармоника
             + 0.022 * rng.normal(size=n)                # шипение тракта
             ).astype(np.float32)
    # кулер: узкополосный шум, гуляющий по громкости
    fan = rng.normal(size=n).astype(np.float32)
    fan = np.convolve(fan, np.hanning(64), "same") / 8.0
    noise += (0.35 + 0.15 * np.sin(2 * np.pi * 0.11 * t)).astype(np.float32) * fan
    # щелчки клавиатуры: короткие всплески — на них ломаются грубые ворота
    for _ in range(int(seconds * 2)):
        i = int(rng.integers(0, n - 200))
        noise[i:i + 120] += rng.normal(size=120).astype(np.float32) * 0.25 \
            * np.hanning(120).astype(np.float32)
    # ШУМ МАСШТАБИРУЕМ ПОД ЗАДАННОЕ ОСШ. Без этого стенд врёт: собрал
    # «правдоподобный» набор шумов — и оказалось, что речь всего на 0.7 дБ
    # громче фона. На таком материале любой шумодав выглядит бесполезным,
    # потому что задача физически нерешаемая, а не потому что движок плох.
    # Дома нормальный микрофон даёт 12-25 дБ, вот на этом и меряем.
    sv = float(np.sqrt(np.mean(clean[marks] ** 2))) if marks.any() else 1.0
    sn = float(np.sqrt(np.mean(noise ** 2))) or 1e-9
    noise *= sv / sn / (10 ** (snr_db / 20.0))
    return (clean + noise).astype(np.float32), clean, marks


def read_wav(path):
    with wave.open(str(path), "rb") as w:
        sr, nch = w.getframerate(), w.getnchannels()
        raw = w.readframes(w.getnframes())
        x = np.frombuffer(raw, np.int16).astype(np.float32) / 32768.0
    if nch > 1:
        x = x.reshape(-1, nch).mean(axis=1)
    if sr != SR:
        x = np.interp(np.linspace(0, len(x) - 1, int(len(x) * SR / sr)),
                      np.arange(len(x)), x).astype(np.float32)
    return x


def record(seconds):
    try:
        import sounddevice as sd
    except Exception as e:
        print(f"Записать не могу: нет sounddevice ({e}).\n"
              f"  pip install sounddevice   — или дай запись ключом --wav")
        return None
    print(f"Пишу {seconds}с. Говори с паузами: нужны и речь, и тишина "
          f"(на тишине шумодав учится).")
    x = sd.rec(int(seconds * SR), samplerate=SR, channels=1, dtype="float32")
    sd.wait()
    return x.reshape(-1)


def write_wav(path, x):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(np.clip(x * 32768, -32768, 32767).astype(np.int16).tobytes())


# ─────────────────────────────── измерения ───────────────────────────────
def db(x):
    return 20 * np.log10(max(1e-9, float(np.sqrt(np.mean(np.asarray(x) ** 2)))))


def align(y, ref, max_lag=int(0.06 * SR)):
    """Сдвиг выхода под опорный сигнал. БЕЗ ЭТОГО ЛЮБОЙ СПЕКТРАЛЬНЫЙ ДВИЖОК
    выглядит сломанным: он задерживает звук на окно (~32мс), корреляция при
    нулевом сдвиге падает в ноль, и стенд бодро сообщает, что речь уничтожена."""
    n = min(len(y), len(ref))
    if n < SR // 2:
        return y[:n], ref[:n]
    a = y[:n] - y[:n].mean()
    b = ref[:n] - ref[:n].mean()
    seg = min(n, SR * 4)
    c = np.correlate(a[:seg], b[:seg], "full")
    mid = len(c) // 2
    lo, hi = mid - max_lag, mid + max_lag
    lag = int(np.argmax(c[lo:hi])) + lo - mid
    if lag > 0:
        y2, r2 = y[lag:n], ref[:n - lag]
    else:
        y2, r2 = y[:n + lag], ref[-lag:n]
    m = min(len(y2), len(r2))
    return y2[:m], r2[:m]


def lsd(y, ref):
    """Логарифмическое спектральное расстояние, дБ. Меньше — ближе к чистой
    речи. В отличие от корреляции не боится сдвига фазы."""
    def spec(v):
        f = np.abs(np.fft.rfft(np.reshape(v[:len(v) // 512 * 512], (-1, 512))
                               * np.hanning(512), axis=1))
        return 20 * np.log10(np.maximum(f, 1e-6))
    n = min(len(y), len(ref)) // 512 * 512
    if n < 512:
        return float("nan")
    a, b = spec(y[:n]), spec(ref[:n])
    return float(np.sqrt(np.mean((a - b) ** 2)))


def run_engine(name, mix, chunk=1600):
    CFG.set("denoise.engine", name)
    d = D.Denoiser()
    pcm = np.clip(mix * 32768, -32768, 32767).astype(np.int16)
    out = []
    t0 = time.monotonic()
    for i in range(0, len(pcm) - chunk + 1, chunk):
        out.append(d.process(pcm[i:i + chunk]))
    ms = (time.monotonic() - t0) * 1000.0
    y = np.concatenate(out).astype(np.float32) / 32768.0 if out else mix
    return y, ms / (len(pcm) / SR), d


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rec", type=float, default=0, help="записать N секунд с микрофона")
    ap.add_argument("--wav", type=str, default="", help="взять запись из файла")
    ap.add_argument("--sec", type=float, default=14.0, help="длина синтетики")
    ap.add_argument("--snr", type=float, default=12.0,
                    help="отношение сигнал/шум в синтетике, дБ (дома 12-25)")
    ap.add_argument("--save", type=str, default="", help="куда сложить результаты")
    ap.add_argument("--stt", action="store_true", help="прогнать через слух Сайки")
    ap.add_argument("--only", type=str, default="", help="список движков через запятую")
    a = ap.parse_args()

    clean = marks = None
    if a.wav:
        mix = read_wav(a.wav)
        print(f"Запись: {a.wav}, {len(mix)/SR:.1f}с")
    elif a.rec:
        mix = record(a.rec)
        if mix is None:
            return 2
        if a.save:
            write_wav(Path(a.save) / "00_input.wav", mix)
    else:
        mix, clean, marks = synth_material(a.sec, snr_db=a.snr)
        print(f"Синтетика: {len(mix)/SR:.1f}с, ОСШ {a.snr:.0f} дБ, речь с "
              f"паузами + гул 50Гц + кулер + шипение + щелчки")

    # где тишина, а где речь. На своей записи размечаем по энергии — грубо,
    # но для сравнения движков между собой этого достаточно: все они меряются
    # на ОДНИХ И ТЕХ ЖЕ отрезках.
    if marks is None:
        w = 1600
        e = np.array([float(np.sqrt(np.mean(mix[i:i + w] ** 2)))
                      for i in range(0, len(mix) - w, w)])
        thr = float(np.percentile(e, 35)) * 2.5
        marks = np.repeat(e > thr, w)[:len(mix)]
        marks = np.pad(marks, (0, len(mix) - len(marks)), constant_values=False)
    quiet = ~marks
    print(f"Разметка: речь {marks.mean()*100:.0f}% времени, "
          f"тишина {quiet.mean()*100:.0f}%")

    names = [n.strip() for n in a.only.split(",") if n.strip()] or list(D.ENGINES)
    print()
    print(f"{'движок':<12}{'тишина':>16}{'речь':>14}{'сходство':>10}"
          f"{'LSD':>8}{'цена':>11}  примечание")
    print("─" * 90)
    base = {"quiet": db(mix[quiet]), "voice": db(mix[marks])}
    rows = []
    for name in names:
        y, ms, d = run_engine(name, mix)
        m = min(len(y), len(mix))
        yq, ym = y[:m][quiet[:m]], y[:m][marks[:m]]
        note = ""
        st = d.status()
        if not st["ok"]:
            note = f"НЕ ВСТАЛ: {st['error'][:40]} → {st['needs']}"
            print(f"{name:<12}{'—':>16}{'—':>14}{'—':>10}{'—':>8}{'—':>11}  {note}")
            continue
        if clean is not None:
            ya, ca = align(y, clean)
            cm = min(len(ya), len(ca))
            mk = marks[:cm]
            corr = float(np.corrcoef(ya[:cm][mk], ca[:cm][mk])[0, 1]) if mk.any() else 0
            dist = lsd(ya[:cm][mk], ca[:cm][mk])
        else:
            ya, ca = align(y, mix)
            cm = min(len(ya), len(ca))
            mk = marks[:cm]
            corr = float(np.corrcoef(ya[:cm][mk], ca[:cm][mk])[0, 1]) if mk.any() else 0
            dist = lsd(ya[:cm][mk], ca[:cm][mk])
        pr = d.profile()
        if pr["learned"]:
            note = f"профиль учился {pr['learned']} кадров"
        rows.append((name, db(yq), db(ym), corr, dist, ms, y))
        print(f"{name:<12}{db(yq):>10.1f} дБ ({db(yq)-base['quiet']:+5.1f})"
              f"{db(ym):>9.1f} ({db(ym)-base['voice']:+5.1f})"
              f"{corr:>10.3f}{dist:>8.1f}{ms:>8.1f} мс/с  {note}")
        if a.save:
            write_wav(Path(a.save) / f"{name}.wav", y)

    print("─" * 90)
    print(f"{'вход':<12}{base['quiet']:>10.1f} дБ{'':>7}{base['voice']:>9.1f}")
    print()
    print("Как читать: «тишина» — чем ниже, тем чище паузы. «речь» — должна")
    print("просесть НЕ СИЛЬНО (в скобках отклонение от входа). «сходство» —")
    print("корреляция с чистой речью после выравнивания задержки, «LSD» —")
    print("спектральное расстояние до неё, меньше лучше. «цена» — миллисекунд")
    print("на секунду звука на этом железе; в живом конвейере терпимо до ~50.")

    if rows:
        best = max(rows, key=lambda r: (r[1] < base["quiet"] - 6) * 2
                   + r[3] - r[5] / 200.0)
        print(f"\nПо этим числам лучший компромисс: «{best[0]}» — "
              f"тишина {best[1]-base['quiet']:+.1f} дБ, речь {best[2]-base['voice']:+.1f} дБ, "
              f"цена {best[5]:.1f} мс/с.")
        print("Включить: меню 🎙 → «Шумодав» → выбрать движок "
              f"(или denoise.engine = \"{best[0]}\" в config.json).")

    if a.stt:
        _stt_check(mix, rows)
    return 0


def _stt_check(mix, rows):
    """ГЛАВНАЯ ПРОВЕРКА, если она вообще доступна: не стало ли ХУЖЕ слуху.
    Всё остальное — косвенные признаки; текст либо распознался, либо нет."""
    print("\nПрогон через слух Сайки (это медленно — грузится движок):")
    try:
        from anamorf.stt.manager import STTManager
    except Exception as e:
        print(f"  не вышло: {e}")
        return
    stt = STTManager()
    for name, *_rest, y in [("вход", 0, 0, 0, 0, 0, mix)] + rows:
        try:
            pcm = np.clip(y * 32768, -32768, 32767).astype(np.int16)
            res = []
            for i in range(0, len(pcm) - 1600, 1600):
                res += stt.process_chunk(pcm[i:i + 1600])
            res += stt.flush()
            text = " ".join(r.get("text", "") for r in res).strip()
            print(f"  {name:<12} фраз {len(res):>2}  «{text[:70]}»")
        except Exception as e:
            print(f"  {name:<12} ошибка: {e}")


if __name__ == "__main__":
    sys.exit(main())
