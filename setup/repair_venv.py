"""Лекарь venv: находит пакеты с пропавшими/нечитаемыми файлами и
переустанавливает их. Нужен после сбоя диска или копирования с битого
носителя (robocopy пропускает нечитаемое — пакеты остаются без части файлов).

Запуск ИЗ ТОГО venv, который лечим:
  .venv\\Scripts\\python.exe setup\\repair_venv.py          быстрая проверка
  .venv\\Scripts\\python.exe setup\\repair_venv.py --deep   + чтение файлов
                                                  (ловит нечитаемые, дольше)
"""
import importlib.metadata as md
import subprocess
import sys
from pathlib import Path

TORCH_PKGS = {"torch", "torchaudio", "torchvision"}
TORCH_INDEX = "https://download.pytorch.org/whl/cu130"
DEEP = "--deep" in sys.argv


def is_broken(dist) -> bool:
    try:
        files = dist.files or []
    except Exception:
        return True
    for f in files:
        try:
            p = Path(dist.locate_file(f))
            if not p.exists():
                return True
            if DEEP:
                with open(p, "rb") as fh:
                    fh.read(1)
        except OSError:
            return True
    return False


def main():
    print(f"Проверяю пакеты venv ({sys.prefix})…"
          + (" [глубокая проверка]" if DEEP else ""))
    broken, editable = [], []
    for dist in md.distributions():
        name = (dist.metadata or {}).get("Name") or ""
        if not name:
            continue
        # editable-пакеты (qwen-tts, gigaam) чинит доктор — пропускаем
        origin = getattr(dist, "origin", None)
        if origin and getattr(getattr(origin, "dir_info", None),
                              "editable", False):
            editable.append(name)
            continue
        if is_broken(dist):
            broken.append(name)
            print(f"  [битый] {name}")
    if not broken:
        print("✓ Все пакеты целы.")
        return

    print(f"\nПереустанавливаю {len(broken)} пакет(ов)…")
    plain = [p for p in broken if p.lower() not in TORCH_PKGS]
    torchy = [p for p in broken if p.lower() in TORCH_PKGS]
    ok = True
    if plain:
        ok &= subprocess.run(
            [sys.executable, "-m", "pip", "install", "--force-reinstall",
             "--no-deps", *plain, "--timeout", "180", "--retries", "5"]
        ).returncode == 0
    if torchy:
        ok &= subprocess.run(
            [sys.executable, "-m", "pip", "install", "--force-reinstall",
             "--no-deps", *torchy, "--index-url", TORCH_INDEX,
             "--timeout", "180", "--retries", "10"]
        ).returncode == 0
    print("\n✓ Готово. Запусти start.bat — доктор доперепроверит."
          if ok else "\n[!] Часть пакетов не переустановилась — смотри вывод.")


if __name__ == "__main__":
    main()
