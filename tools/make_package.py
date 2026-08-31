"""Собирает переносимый архив Saika_portable.zip в I:\\Aitest\\Saika
(точнее — в папку НАД проектом, где бы он ни лежал).

Внутрь идёт всё, включая .venv и модели — распаковал на другом ПК и сразу
запустил start.bat. Исключается мусор: __pycache__, pip-кэши, логи, локи.

Занятые файлы (например, база памяти при работающей Сайке) не валят паковку —
они пропускаются с предупреждением. Но лучше закрыть Сайку перед упаковкой,
чтобы память уехала целиком.

Запуск:  tools\\make_package.bat
"""
import sys
import zipfile
from pathlib import Path

KEEP_PRIVATE = False

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT.parent / "Saika_portable.zip"
EXCLUDE_DIRS = {"__pycache__", ".pip_tmp", ".pip_cache", "logs", ".locks",
                ".git"}
EXCLUDE_SUFFIXES = {".lock", ".pyc"}
# ЛИЧНОЕ В ПЕРЕНОСНОЙ АРХИВ НЕ КЛАДЁМ (2026-08-25, аудит). Архив задуман как
# перенос между машинами автора, но его легко передать другому человеку —
# и тогда secrets.json (ключи, токены ботов) и голосовые отпечатки уехали
# бы вместе с ним. Секреты исключаем всегда; личные данные (память, база
# голосов) — по флагу, чтобы «перенос к себе» их всё же захватывал.
EXCLUDE_FILES = {"secrets.json"}
PRIVATE_DIRS = {"voiceprint", "webview", "browser_profile"}  # внутри data/


def main():
    global KEEP_PRIVATE
    KEEP_PRIVATE = "--keep-private" in sys.argv   # для переноса к себе
    print("secrets.json и" if not KEEP_PRIVATE else "секреты; но",
          "личные данные" + (" и голоса — В АРХИВ НЕ ИДУТ (безопасно для "
          "передачи)" if not KEEP_PRIVATE else " СОХРАНЕНЫ (--keep-private): "
          "не передавай архив чужим"))
    if OUT.exists():
        OUT.unlink()
    n, total, skipped = 0, 0, []
    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED,
                         compresslevel=1, allowZip64=True) as z:
        for f in ROOT.rglob("*"):
            try:
                rel = f.relative_to(ROOT)
                parts = set(rel.parts)
                if (not f.is_file()
                        or parts & EXCLUDE_DIRS
                        or f.suffix.lower() in EXCLUDE_SUFFIXES
                        or f.name in EXCLUDE_FILES
                        or (KEEP_PRIVATE is False
                            and "data" in rel.parts
                            and parts & PRIVATE_DIRS)):
                    continue
                z.write(f, Path(ROOT.name) / rel)
                n += 1
                total += f.stat().st_size
                if n % 1000 == 0:
                    print(f"  …{n} файлов, {total / 2**30:.1f} ГБ")
            except (PermissionError, OSError) as e:
                skipped.append(f"{rel}: {e}")
    print(f"\n✓ Готово: {OUT}")
    print(f"  файлов: {n}, исходный объём: {total / 2**30:.1f} ГБ, "
          f"архив: {OUT.stat().st_size / 2**30:.1f} ГБ")
    if skipped:
        print(f"\n[!] Пропущено занятых/недоступных файлов: {len(skipped)}")
        for s in skipped[:20]:
            print("   ", s)
        lst = ROOT.parent / "Saika_package_skipped.txt"
        lst.write_text("\n".join(skipped), encoding="utf-8")
        print(f"    Полный список: {lst}")
        print("    WinError 1392 = повреждена файловая система: chkdsk I: /f,")
        print("    затем переустанови битые пакеты и собери архив заново.")
        print("    Если среди них data/… — закрой Сайку и собери архив заново.")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\n[X] Паковка упала: {e!r}")
        print("Пришли этот текст — починим.")
