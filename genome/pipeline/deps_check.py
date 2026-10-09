# -*- coding: utf-8 -*-
"""deps_check.py — проверка модулей Python при запуске студии.

Лаунчер запускает этот скрипт при старте. Он:
  1. сам находит сторонние модули, которые импортируют скрипты pipeline/ (список не надо вести руками);
  2. проверяет, стоят ли они у ЭТОГО python (того же, что запускает chat.py и исследование);
  3. недостающие ставит через pip и пишет итог в logs/deps.log и в журнал студии.

---- учебный блок: имя модуля ≠ имя пакета ----
import PIL ставится как pillow, import yt_dlp — как yt-dlp. Поэтому есть словарь PIP.
Модули из SKIP не ставим сами: это либо свой пакет (anamorf), либо тяжёлое (crawl4ai тянет браузер).
"""
import sys, re, json, time, pathlib, subprocess, importlib.util
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
P = pathlib.Path(__file__).resolve().parent
LOG = P.parent / "logs" / "deps.log"
PIP = {"PIL": "pillow", "yt_dlp": "yt-dlp", "pdfminer": "pdfminer.six", "parselmouth": "praat-parselmouth",
       "faster_whisper": "faster-whisper", "av": "av"}
SKIP = {"anamorf", "crawl4ai"}


def нужные():
    свои = {p.stem for p in P.glob("*.py")}
    мод = {}
    for f in P.glob("*.py"):
        for m in re.findall(r"^\s*(?:from|import)\s+([A-Za-z_]\w*)", f.read_text(encoding="utf-8", errors="ignore"), re.M):
            if m not in свои and m not in sys.stdlib_module_names:
                мод.setdefault(m, set()).add(f.name)
    return мод


def main():
    мод = нужные()
    нет = [m for m in sorted(мод) if importlib.util.find_spec(m) is None]
    строки = [f"{time.strftime('%Y-%m-%d %H:%M')} · python {sys.version.split()[0]} · модулей {len(мод)}, нет {len(нет)}"]
    for m in нет:
        if m in SKIP:
            строки.append(f"  пропущен {m} (ставить вручную) — нужен для {', '.join(sorted(мод[m]))}"); continue
        пакет = PIP.get(m, m)
        r = subprocess.run([sys.executable, "-m", "pip", "install", "-q", пакет], capture_output=True, text=True, timeout=900)
        ок = r.returncode == 0 and importlib.util.find_spec(m) is not None
        строки.append(f"  {'поставлен' if ок else 'НЕ ПОСТАВИЛСЯ'} {пакет}" + ("" if ок else " — " + (r.stderr or r.stdout).strip()[-200:]))
    if not нет:
        строки.append("  всё на месте")
    LOG.parent.mkdir(exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write("\n".join(строки) + "\n")
    print("\n".join(строки), flush=True)


if __name__ == "__main__":
    main()
