"""Сборка докачиваемого блока — один раз на машине автора.

Блок это готовый архив с пакетами, который у человека просто распаковывается.
Никакого pip на его стороне: у него нет компилятора, а любой pip-заход рискует
уронить уже работающее окружение (в этом проекте так и было — T-one откатывал
numpy и ронял слух вместе с голосом).

    python tools\\make_pack.py browser              собрать один блок
    python tools\\make_pack.py --all                собрать все
    python tools\\make_pack.py browser --version 0.9.5
    python tools\\make_pack.py locallm --from .venv_locallm

Последняя форма — для блоков, у которых в реестре нет списка пакетов, потому
что это целое отдельное окружение: его не собирают заново, а пакуют как есть.

На выходе: build/packs/pack-<фича>-<версия>.zip и обновлённый packs.json с
размером и контрольной суммой. Архив кладётся в релиз рядом с установщиком,
адрес в packs.json проставляется на публикации.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "build" / "packs"
REPO = "anamorfagi/Saika"


def features() -> dict:
    d = json.loads((ROOT / "features.json").read_text(encoding="utf-8"))
    return {f["id"]: f for g in d["groups"] for f in g["features"]}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def zip_dir(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        dst.unlink()
    n = 0
    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for p in sorted(src.rglob("*")):
            if p.is_dir() or "__pycache__" in p.parts:
                continue
            z.write(p, p.relative_to(src).as_posix())
            n += 1
            if n % 500 == 0:
                print(f"      упаковано файлов: {n}")
    print(f"      упаковано файлов: {n}")


def build(fid: str, version: str, from_dir: str | None) -> dict | None:
    feats = features()
    f = feats.get(fid)
    if not f:
        print(f"[!] фичи {fid} нет в реестре")
        return None
    if not f.get("pack"):
        print(f"[!] {fid} не помечена как докачиваемая (pack: true) — "
              f"она должна ехать прямо в установщике")
        return None

    stage = OUT / fid
    shutil.rmtree(stage, ignore_errors=True)
    stage.mkdir(parents=True, exist_ok=True)

    if from_dir:
        src = ROOT / from_dir
        if not src.is_dir():
            print(f"[!] нет папки {src}")
            return None
        print(f"   копирую готовое окружение {from_dir} …")
        # Lib/site-packages — то единственное, что нужно: интерпретатор у
        # человека уже свой, тащить второй незачем.
        sp = src / "Lib" / "site-packages"
        shutil.copytree(sp if sp.is_dir() else src, stage,
                        dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    else:
        pkgs = f.get("pip") or []
        if not pkgs:
            print(f"[!] у {fid} пустой список пакетов — укажи --from <папка>")
            return None
        print(f"   ставлю {', '.join(pkgs)} в отдельную папку …")
        r = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--target", str(stage),
             "--no-compile", "--disable-pip-version-check", *pkgs],
            text=True, encoding="utf-8", errors="replace")
        if r.returncode != 0:
            print("[!] pip не справился")
            return None

    # Браузер — особый случай: сам Chromium лежит рядом, иначе блок
    # бесполезен, а человек полезет в интернет ровно за тем, от чего мы
    # его и уводим.
    if fid == "browser":
        print("   качаю Chromium внутрь блока …")
        env = dict(os.environ, PLAYWRIGHT_BROWSERS_PATH=str(stage / "browsers"))
        subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"],
                       env=env, text=True)
        print("   ! проверь лицензию бинаря ffmpeg внутри блока: у Playwright "
              "встречался GPL-3.0. Не нужен для работы — можно выкинуть.")

    zip_path = OUT / f"pack-{fid}-{version}.zip"
    print("   пакую …")
    zip_dir(stage, zip_path)
    shutil.rmtree(stage, ignore_errors=True)

    mb = zip_path.stat().st_size / 1e6
    entry = {
        "version": version,
        "mb": round(mb, 1),
        "sha256": sha256(zip_path),
        "url": (f"https://github.com/{REPO}/releases/download/"
                f"v{version}/pack-{fid}-{version}.zip"),
    }
    print(f"   готово: {zip_path.name}  {mb:.0f} МБ")
    return entry


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("feature", nargs="?", help="какой блок собрать")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--version", default="0.9.5")
    ap.add_argument("--from", dest="from_dir", default=None,
                    help="упаковать готовое окружение, а не ставить заново")
    a = ap.parse_args()

    feats = features()
    todo = ([fid for fid, f in feats.items() if f.get("pack")]
            if a.all else ([a.feature] if a.feature else []))
    if not todo:
        print("Что собирать? Докачиваемые блоки:")
        for fid, f in feats.items():
            if f.get("pack"):
                print(f"   {fid:<14} {f.get('title','')}  ~{f.get('mb',0)} МБ")
        return 1

    man_path = ROOT / "packs.json"
    try:
        man = json.loads(man_path.read_text(encoding="utf-8"))
    except Exception:
        man = {"_note": "Опись докачиваемых блоков. Собирается "
                        "tools/make_pack.py, адреса проставляются при "
                        "публикации релиза.", "packs": {}}

    ok = 0
    for fid in todo:
        print(f"\n=== {fid} ===")
        entry = build(fid, a.version, a.from_dir)
        if entry:
            man["packs"][fid] = entry
            ok += 1

    man_path.write_text(json.dumps(man, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")
    print(f"\nсобрано блоков: {ok} из {len(todo)}   опись: packs.json")
    print("Дальше: выложи архивы из build/packs/ в релиз с тем же тегом.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
