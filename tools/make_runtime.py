"""Сборка runtime\\ — интерпретатора с пакетами, который поедет к человеку.

Собирается ОДИН РАЗ на машине автора и кладётся в билд как есть. У человека
ничего не ставится: ни pip, ни компилятора, ни колёс под его версию Python.
Что собралось здесь — то и работает там, побайтово одинаково.

    python tools\\make_runtime.py --profile base
    python tools\\make_runtime.py --features stt,tts,pc
    python tools\\make_runtime.py --profile base --torch

Что делает:
    1. берёт набор пакетов включённых фич из features.json;
    2. сверяет версии с requirements.lock.txt — замок наконец начинает
       работать, а не лежать (до сих пор его не читал НИ ОДИН скрипт проекта);
    3. ставит всё в build/runtime/Lib/site-packages;
    4. кладёт рядом переносимый интерпретатор;
    5. считает вес и пишет отчёт.

Про torch. Он тянется фичами слуха, голоса и зрения и весит около 2.9 ГБ в
установленном виде. Отдельным флагом, потому что это половина размера
дистрибутива и решение принимается осознанно, а не «ну как-то само вышло».

Про переносимый интерпретатор. Windows embeddable — это zip с python.exe и
стандартной библиотекой, ~15 МБ. Его надо скачать с python.org руками один
раз и положить в third_party\\python-embed\\ — сеть у сборки не спрашиваем,
чтобы билд был воспроизводим и не зависел от того, что сегодня отдаёт сайт.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "build" / "runtime"
EMBED_SRC = ROOT / "third_party" / "python-embed"
LOCK = ROOT / "requirements.lock.txt"

TORCH_PKGS = ("torch", "torchaudio", "torchvision")
TORCH_INDEX = "https://download.pytorch.org/whl/cu130"


def features() -> dict:
    d = json.loads((ROOT / "features.json").read_text(encoding="utf-8"))
    return {f["id"]: f for g in d["groups"] for f in g["features"]}


def pinned() -> dict:
    """Имя пакета → строка с версией из замка.

    Замок здесь не формальность: без него у человека окажется не то, что
    проверял автор, а то, что PyPI отдал в день сборки.
    """
    out = {}
    if not LOCK.exists():
        print("[!] нет requirements.lock.txt — версии не будут закреплены")
        return out
    for line in LOCK.read_text(encoding="utf-8").splitlines():
        line = line.split("#")[0].strip()
        if not line or line.startswith("-"):
            continue
        m = re.match(r"^([A-Za-z0-9._\-\[\]]+)\s*([=<>!~].*)?$", line)
        if m:
            out[m.group(1).split("[")[0].lower()] = line
    return out


def _norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).strip().lower()


def closure(roots: list[str]) -> list[str]:
    """Все пакеты, которые на самом деле нужны перечисленным — по факту.

    Почему не даём pip решать самому. Решатель читает объявленные
    зависимости и отказывается ставить комбинацию, которой «не должно
    существовать»: opencv 4.13 требует numpy>=2, замок пинит 1.26.4. При
    этом обе библиотеки у автора стоят рядом и работают. Спорить с
    метаданными бессмысленно — рабочее окружение есть, его надо
    ВОСПРОИЗВЕСТИ, а не пересобрать заново по чужим пожеланиям.

    Поэтому граф зависимостей берём из живого окружения, а не с PyPI, и
    ставим готовый список с --no-deps. Что у автора работает, то и
    приедет к человеку — побайтово.
    """
    from importlib import metadata as md

    try:
        from packaging.markers import default_environment
        from packaging.requirements import Requirement
    except ImportError:
        print("[!] нет packaging — ставлю только перечисленное, без зависимостей")
        return list(roots)

    env = default_environment()
    have = {}
    for d in md.distributions():
        name = d.metadata.get("Name")
        if name:
            have[_norm(name)] = d

    # Корень может быть заказан с набором: uvicorn[standard]. Набор — это
    # не украшение: в нём лежит httptools, на котором сервер работает
    # быстрее, и websockets. Раньше мы наборы отбрасывали целиком, и
    # получалось, что в билд не попадало то, что у автора стоит и
    # используется. Ещё хуже вышло с python-multipart: fastapi объявляет
    # его в наборе, без него падает ЛЮБОЙ обработчик с загрузкой файла —
    # и падает не при импорте, а при разборе маршрутов, то есть в момент
    # запуска. Поэтому наборы корней раскрываем.
    queue = []
    for r in roots:
        base = r.split("[")[0].split("=")[0].split(">")[0].split("<")[0]
        extras = re.findall(r"\[([^\]]+)\]", r)
        extras = {e.strip() for group in extras for e in group.split(",")}
        queue.append((_norm(base), extras))

    seen, order, missing = set(), [], []
    while queue:
        name, extras = queue.pop(0)
        if name in seen:
            continue
        seen.add(name)
        dist = have.get(name)
        if dist is None:
            missing.append(name)
            continue
        order.append(name)
        for raw in (dist.requires or []):
            try:
                req = Requirement(raw)
            except Exception:
                continue
            if req.marker:
                # Зависимость берём, если она нужна без наборов ИЛИ
                # входит в один из заказанных.
                ok = req.marker.evaluate({**env, "extra": ""})
                for e in extras:
                    ok = ok or req.marker.evaluate({**env, "extra": e})
                if not ok:
                    continue
            queue.append((_norm(req.name), set(req.extras or ())))

    if missing:
        print(f"   не нашлись в окружении (поставятся как есть): "
              f"{', '.join(sorted(missing))}")
    return order + missing


def collect(feats: dict, on: set[str]) -> list[str]:
    """Пакеты фич + всё, что они за собой тянут, с версиями из замка."""
    pins = pinned()
    roots = []
    for fid in sorted(on):
        for pkg in feats[fid].get("pip", []):
            roots.append(pkg)

    full = closure(roots)
    # Семейство torch ставится отдельно, со своего индекса: версии с
    # суффиксом +cu130 на PyPI не существует, и обычная установка на ней
    # споткнётся. Здесь просто убираем их из общего списка.
    full = [n for n in full if n not in TORCH_PKGS]
    out = []
    for name in full:
        spec = pins.get(name)
        if spec:
            out.append(spec)
            continue
        # версии в замке нет — берём ту, что стоит сейчас
        try:
            from importlib import metadata as md
            out.append(f"{name}=={md.version(name)}")
        except Exception:
            out.append(name)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", default="base",
                    choices=["min", "base", "full", "pro"])
    ap.add_argument("--features", default=None)
    ap.add_argument("--torch", action="store_true",
                    help="положить torch (+~2.9 ГБ)")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--top-up", dest="top_up", nargs="?",
                    const=str(OUT), default=None,
                    help="доставить недостающее в уже собранный runtime, "
                         "не пересобирая его целиком")
    a = ap.parse_args()

    feats = features()
    if a.features:
        on = {s.strip() for s in a.features.split(",") if s.strip()}
    else:
        test = {"min": lambda f: f.get("lock"),
                "base": lambda f: f.get("lock") or f.get("base"),
                "full": lambda f: f.get("tier", "free") == "free",
                "pro": lambda f: True}[a.profile]
        on = {fid for fid, f in feats.items() if test(f) and not f.get("dev")}

    pkgs = collect(feats, on)
    needs_torch = a.torch or any(feats[f].get("torch") for f in on)

    print(f"фич: {len(on)}   пакетов с зависимостями: {len(pkgs)}")
    for i in range(0, len(pkgs), 4):
        print("   " + "  ".join(f"{x:<26}" for x in pkgs[i:i + 4]).rstrip())
    if needs_torch:
        print(f"   + torch, torchaudio  (индекс {TORCH_INDEX}, ~2.9 ГБ)")

    if not EMBED_SRC.is_dir():
        print(f"\n[!] нет переносимого интерпретатора: {EMBED_SRC}")
        print("    Скачай «Windows embeddable package (64-bit)» для Python 3.12")
        print("    с python.org и распакуй туда. Один раз.")

    # ДОЗАЛИВКА. Пока собранный билд впервые запускают, нехватки всплывают
    # по одной: fastapi роняет обработчики с файлами без python-multipart,
    # uvicorn тихо переходит на медленный путь без httptools. Пересобирать
    # ради каждой такой находки четыре гигабайта — потерянные полчаса,
    # поэтому есть отдельный ход: доставить в уже готовое.
    if a.top_up:
        target = pathlib.Path(a.top_up)
        site_dir = target if target.name == "site-packages" else \
            target / "Lib" / "site-packages"
        if not site_dir.is_dir():
            print(f"[!] не вижу site-packages в {target}")
            return 1
        # Эталон один: build/runtime. Готовая раскладка — его копия, и
        # следующая же сборка перезапишет её целиком. Долитое в копию
        # исчезнет молча, а выглядеть будет как «пакет не установился».
        if OUT.resolve() != site_dir.parent.parent.resolve():
            print(f"[!] {target} — это КОПИЯ, её перезапишет ближайшая сборка.")
            print(f"    Доливать надо в эталон: {OUT}")
            print(f"    Продолжаю, но потом всё равно повтори для эталона.")
        have = {p.name.split("-")[0].lower().replace("_", "-")
                for p in site_dir.glob("*.dist-info")}
        need = [p for p in pkgs
                if _norm(p.split("=")[0].split("[")[0]) not in have]
        if not need:
            print("\nвсё нужное уже на месте")
            return 0
        print(f"\nдоставляю {len(need)}: {', '.join(need)}")
        r = subprocess.run([sys.executable, "-m", "pip", "install",
                            "--target", str(site_dir), "--no-compile",
                            "--no-deps", "--upgrade",
                            "--disable-pip-version-check", *need],
                           text=True, encoding="utf-8", errors="replace")
        print("готово" if r.returncode == 0 else "[!] pip не справился")
        return 0 if r.returncode == 0 else 1

    if not a.apply:
        print("\n(это была прикидка — собрать: --apply)")
        return 0

    if not EMBED_SRC.is_dir():
        return 1

    site = OUT / "Lib" / "site-packages"
    shutil.rmtree(OUT, ignore_errors=True)
    site.mkdir(parents=True, exist_ok=True)

    print("\nкопирую интерпретатор…")
    shutil.copytree(EMBED_SRC, OUT, dirs_exist_ok=True)
    # ЧТО ВИДИТ ЭТОТ ИНТЕРПРЕТАТОР — РЕШАЕТ ТОЛЬКО ._pth.
    #
    # У embeddable-сборки пути урезаны намеренно, чтобы она не подхватила
    # чужой Python с машины. Но есть следствие, о котором узнаёшь только
    # споткнувшись: САМО НАЛИЧИЕ файла ._pth переводит Python в
    # изолированный режим, и он перестаёт смотреть на PYTHONPATH вообще.
    # Лаунчер честно выставлял переменную, а интерпретатор её игнорировал
    # и отвечал «No module named 'anamorf'».
    #
    # Поэтому оба нужных пути пишем сюда. Они относительны папке с
    # python.exe, а раскладка у нас фиксированная: runtime\ и app\ — соседи.
    for pth in OUT.glob("python*._pth"):
        lines = [l.rstrip() for l in
                 pth.read_text(encoding="utf-8").splitlines()]
        for need in ("Lib\\site-packages", "..\\app", "import site"):
            if need not in lines:
                lines.append(need)
        pth.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"   {pth.name}: подключены site-packages и app\\")

    if pkgs:
        print("\nставлю пакеты…")
        # --no-deps принципиально: список уже полный и проверен работой.
        # Дать pip досчитать своё — значит снова упереться в противоречие
        # объявленных зависимостей там, где реальность давно сложилась.
        r = subprocess.run([sys.executable, "-m", "pip", "install",
                            "--target", str(site), "--no-compile", "--no-deps",
                            "--disable-pip-version-check", *pkgs],
                           text=True, encoding="utf-8", errors="replace")
        if r.returncode != 0:
            print("[!] pip не справился — сборка не завершена")
            return 1

    if needs_torch:
        print("\nставлю torch (это надолго)…")
        subprocess.run([sys.executable, "-m", "pip", "install",
                        "--target", str(site), "--no-compile", "--no-deps",
                        "--index-url", TORCH_INDEX,
                        pinned().get("torch", "torch"),
                        pinned().get("torchaudio", "torchaudio")],
                       text=True, encoding="utf-8", errors="replace")

    total = sum(p.stat().st_size for p in OUT.rglob("*") if p.is_file())
    print(f"\nготово: {OUT}")
    print(f"   вес: {total/1e9:.2f} ГБ")
    print("   проверь запуск:  build\\runtime\\python.exe -c \"import fastapi\"")
    return 0


if __name__ == "__main__":
    sys.exit(main())
