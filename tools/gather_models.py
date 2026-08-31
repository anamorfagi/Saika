"""Собрать МИНИМАЛЬНЫЙ портативный набор весов рядом со сборкой (2026-08-25).

Задача владельца: «чтобы прогу можно было запаковать со всеми весами и
моделями — максимально портативной». Модели живут в трёх разных местах:
проект (models\), каталог LM Studio (.lmstudio), кэш пользователя (.cache).
Собранное приложение по умолчанию их там же и ищет — то есть без этих папок
у ДРУГОГО человека оно немое и слепое. Скрипт копирует нужное внутрь сборки:
    build\ANAMORF-<ver>\models\...   (переживает обновление app\)
    build\ANAMORF-<ver>\models\gguf\ (мозг — llamacpp.find_model смотрит сюда)

ВНИМАНИЕ: набор нарочно минимальный — один мозг, один клон-голос, один слух,
отпечаток голоса, запасной голос и черновик. Полный models\hf\hub (100+ ГБ)
НЕ копируется: там весь зоопарк скачанного, клиенту он не нужен.

Запуск:
    python tools\gather_models.py --version 0.1.2 --brain Qwen3.5-9B --check
    python tools\gather_models.py --version 0.1.2 --brain Qwen3.5-9B --apply

--brain — имя .gguf (без пути), которое станет встроенным мозгом. Ищется в
проекте и в LM Studio. Лёгкий вариант — gemma-4-E4B (~3 ГБ), обычный —
Qwen3.5-9B (~6 ГБ).
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOME = Path.home()


def _lmstudio_roots():
    roots = [HOME / ".lmstudio" / "models", HOME / ".cache" / "lm-studio" / "models"]
    return [r for r in roots if r.is_dir()]


def find_gguf(name: str):
    """Найти .gguf по имени (и его mmproj-проектор, если рядом)."""
    stem = name.lower().replace(".gguf", "")
    roots = [ROOT / "models" / "gguf", ROOT / "models" / "llm"] + _lmstudio_roots()
    for root in roots:
        for f in root.rglob("*.gguf"):
            if stem in f.name.lower() and "mmproj" not in f.name.lower():
                mm = None
                for cand in f.parent.glob("mmproj*.gguf"):
                    mm = cand
                    break
                return f, mm
    return None, None


# что берём: (человеческое имя, откуда, куда_внутри_сборки, обязательно ли)
def plan_items(brains):
    """brains — список (gguf_path, mmproj_path|None)."""
    items = []
    for brain_gguf, brain_mm in brains:
        if not brain_gguf:
            continue
        items.append(("мозг " + brain_gguf.name, brain_gguf,
                      Path("models/gguf") / brain_gguf.name, True))
        if brain_mm:
            items.append(("зрение мозга " + brain_mm.name, brain_mm,
                          Path("models/gguf") / brain_mm.name, False))
    # клон-голос Qwen3-TTS
    for p in (ROOT / "models" / "hf" / "hub").glob("models--Qwen--Qwen3-TTS*"):
        items.append(("клон-голос " + p.name, p,
                      Path("models/hf/hub") / p.name, True))
    # слух gigaam
    for cand in (HOME / ".cache" / "gigaam", ROOT / "models" / "gigaam"):
        if cand.is_dir() and any(cand.glob("*")):
            items.append(("слух gigaam", cand, Path("models/gigaam"), True))
            break
    # отпечаток голоса + разделение
    for nm in ("ecapa", "sepformer"):
        d = ROOT / "models" / nm
        if d.is_dir() and any(d.glob("*")):
            items.append(("голос: " + nm, d, Path("models") / nm, False))
    # запасной голос piper, черновик vosk, torch-хаб (silero/panns), аватар
    for nm in ("piper", "vosk-model-small-ru-0.22", "torch", "avatar"):
        d = ROOT / "models" / nm
        if d.is_dir() and any(d.glob("*")):
            items.append((nm, d, Path("models") / nm, False))
    # panns и silero кэши в .cache пользователя
    for sub, dst in (("panns_data", "panns_data"),
                     ("torch/hub", "torch/hub")):
        c = HOME / ".cache" / sub if sub == "panns_data" else HOME / sub
        # panns кладётся в ~/panns_data; silero — в models/torch/hub (уже выше)
    return items


def human_size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", required=True, help="версия сборки, напр. 0.1.2")
    ap.add_argument("--brain", default="Qwen3.5-9B,gemma-4-E4B",
                    help="имена .gguf встроенных мозгов через запятую "
                         "(прога сама выберет по железу при запуске)")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    out = ROOT / "build" / ("ANAMORF-" + a.version)
    if not out.is_dir():
        print("нет сборки %s — сначала собери build_client.py" % out)
        return 1

    brains, missing = [], []
    for nm in [x.strip() for x in a.brain.split(",") if x.strip()]:
        bg, bm = find_gguf(nm)
        if bg:
            brains.append((bg, bm))
        else:
            missing.append(nm)
    if missing:
        print("! не нашла .gguf: %s" % ", ".join(missing))
        print("  доступные .gguf:")
        seen = set()
        for root in [ROOT / "models" / "gguf"] + _lmstudio_roots():
            for f in root.rglob("*.gguf"):
                if "mmproj" in f.name.lower() or f.name in seen:
                    continue
                seen.add(f.name)
                print("   ", f.name, "(%.1f ГБ)" % (f.stat().st_size / 2**30))
    if not brains:
        print("ни одного мозга не нашла — прервусь")
        return 1

    items = plan_items(brains)
    print("=" * 60)
    print("ПОРТАТИВНЫЙ НАБОР для", out.name, "· мозги:",
          ", ".join(b.name for b, _ in brains))
    print("=" * 60)
    total = 0
    for name, src, dst, need in items:
        sz = human_size(src)
        total += sz
        mark = "*" if need else " "
        print(" %s %-40s %6.2f ГБ -> %s" % (mark, name[:40], sz / 2**30, dst))
    print("-" * 60)
    print("ИТОГО: %.1f ГБ" % (total / 2**30))
    if not a.apply:
        print("\n(это только смета — скопировать: --apply)")
        return 0

    for name, src, dst, need in items:
        d = out / dst
        try:
            if src.is_file():
                d.parent.mkdir(parents=True, exist_ok=True)
                if not d.exists():
                    shutil.copy2(src, d)
            else:
                if not d.exists():
                    shutil.copytree(src, d,
                                    ignore=shutil.ignore_patterns(
                                        "__pycache__", "*.pyc", "*.tmp"))
            print("   ok:", name)
        except Exception as e:
            print("   ! не скопировала %s: %s" % (name, e))
    print("\nГотово. Мозг лежит в models\\gguf — приложение найдёт его само,")
    print("каталог LM Studio больше не нужен. Проверь запуск build\\%s\\ANAMORF.exe"
          % out.name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
