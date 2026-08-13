"""Скачать uBlock Origin для Chromium в third_party/ublock.

Зачем расширение, а не свои фильтры: баннеры, куки-стены и окна подписки —
это гонка вооружений, которую годами ведут другие люди. Свой детектор
перекрытий (browser_hands.close_ad) оставляем страховкой на то, что uBlock
пропустит, но основную работу должен делать тот, кто ей занимается всерьёз.

Ставится один раз. Playwright умеет расширения ТОЛЬКО в persistent-контексте
и только в headed-режиме — у Сайки окно как раз видимое, так что подходит.
"""
import io
import json
import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEST = ROOT / "third_party" / "ublock"
# ТОЛЬКО MV3 (исправлено 2026-08-13 по живому отказу: Chromium показал
# «Не удалось установить расширение, неподдерживаемая версия манифеста»).
# Классический uBlock Origin (gorhill/uBlock) — Manifest V2, а свежий
# Chromium его уже не принимает. Нужен uBlock Origin Lite из uBOL-home:
# это MV3-сборка того же проекта, фильтры декларативные. Для «убрать
# баннеры со страницы, которую читает Сайка» его достаточно с запасом.
API = "https://api.github.com/repos/uBlockOrigin/uBOL-home/releases/latest"


def _pick_asset(rel):
    """Нужна распакованная chromium-сборка на MV3 (uBOLite_*.chromium.mv3.zip)."""
    assets = rel.get("assets", [])
    for want in (("chromium", "mv3"), ("chromium",)):
        for a in assets:
            n = a.get("name", "").lower()
            if not n.endswith(".zip"):
                continue
            if all(w in n for w in want):
                return a["browser_download_url"], a["name"]
    return None, None


def main():
    if (DEST / "manifest.json").exists():
        try:
            man = json.loads((DEST / "manifest.json").read_text(
                encoding="utf-8"))
        except Exception:
            man = {}
        if int(man.get("manifest_version", 2)) >= 3:
            print(f"uBlock уже стоит: {DEST}")
            return 0
        # осталась MV2-папка от прошлой попытки — Chromium её не примет
        print("Нашла старую MV2-сборку — сношу и качаю MV3")
        shutil.rmtree(DEST, ignore_errors=True)
    url = name = None
    for api in (API,):
        try:
            req = urllib.request.Request(
                api, headers={"User-Agent": "saika-setup"})
            with urllib.request.urlopen(req, timeout=30) as r:
                rel = json.load(r)
            url, name = _pick_asset(rel)
            if url:
                print(f"Нашла {name} ({rel.get('tag_name')})")
                break
        except Exception as e:
            print(f"  {api} не ответил: {e}")
    if not url:
        print("Не нашла MV3-сборку uBlock Origin Lite. Поставь вручную:")
        print("  https://github.com/uBlockOrigin/uBOL-home/releases")
        print("  нужен файл вида uBOLite_*.chromium.mv3.zip")
        print(f"  распакуй так, чтобы был файл {DEST / 'manifest.json'}")
        return 1

    print("Качаю…")
    req = urllib.request.Request(url, headers={"User-Agent": "saika-setup"})
    with urllib.request.urlopen(req, timeout=180) as r:
        blob = r.read()
    print(f"  {len(blob) / 1048576:.1f} МБ")

    tmp = ROOT / "third_party" / "_ublock_tmp"
    if tmp.exists():
        shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        z.extractall(tmp)

    # архив обычно с одной папкой внутри — находим manifest.json и берём ЕЁ
    man = next(iter(sorted(tmp.rglob("manifest.json"),
                           key=lambda p: len(p.parts))), None)
    if man is None:
        print("В архиве нет manifest.json — формат поменялся, ставь вручную")
        return 1
    if DEST.exists():
        shutil.rmtree(DEST, ignore_errors=True)
    DEST.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(man.parent), str(DEST))
    shutil.rmtree(tmp, ignore_errors=True)
    # МЕТКА ДЛЯ ensure_features: проверять просто manifest.json нельзя —
    # от неудачной MV2-попытки он тоже остаётся на месте, и автоустановка
    # решала бы «всё стоит» вместо переустановки (живой отказ 2026-08-13).
    try:
        (DEST / ".saika_mv3").write_text("ok", encoding="utf-8")
    except Exception:
        pass
    print(f"Готово: {DEST}")
    print("Перезапусти Сайку — она подхватит расширение сама.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
