"""СКАЧАТЬ НОВЫЙ МОЗГ — Qwen3-14B GGUF (2026-08-23).

Владелец: «давай подберём модель, на которой дотла отработаем все
технологии, что-то современное из новых».

ПОЧЕМУ ИМЕННО ЭТА. Ограничения железа жёсткие: 16 ГБ видеопамяти на всех,
и на карте одновременно живут клон-голос Qwen3-TTS (~3 ГБ) и слух. На
мозг остаётся ~10 ГБ. Из современного в этот бюджет лучше всех ложится
Qwen3-14B в Q4_K_M (~9 ГБ): родной русский, честный tool calling (наш
формат OpenAI-совместимый, она его знает), и режим «думать/не думать»
переключается на лету — для рефлекторных команд думанье выключаем, для
разговора оставляем. Прыжок с нынешней gemma-4-e4b (4B активных) заметный.

ПОЧЕМУ НЕ НАПРЯМУЮ С HUGGING FACE. На этой сети huggingface.co не
отвечает (в логах программы он давно помечен офлайном). Качаем с зеркала
hf-mirror.com — это прозрачный прокси тех же файлов; на всякий случай
пробуем и оригинал, вдруг сеть сменилась.

Докачка поддержана: файл на 9 ГБ обязан переживать обрыв соединения.

    python tools\\get_brain.py           — скачать и прописать в конфиг
    python tools\\get_brain.py --dry     — только показать, что будет делать
"""
import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

REPO = "Qwen/Qwen3-14B-GGUF"
FILE = "Qwen3-14B-Q4_K_M.gguf"
HOSTS = ["https://hf-mirror.com", "https://huggingface.co"]
DEST = ROOT / "models" / "gguf" / FILE
MODEL_NAME = "qwen3-14b"


def _url(host):
    return f"{host}/{REPO}/resolve/main/{FILE}?download=true"


def _head(url):
    req = urllib.request.Request(url, method="HEAD")
    with urllib.request.urlopen(req, timeout=20) as r:
        return int(r.headers.get("Content-Length") or 0)


def download(dry=False) -> int:
    DEST.parent.mkdir(parents=True, exist_ok=True)
    total, host = 0, ""
    for h in HOSTS:
        try:
            total = _head(_url(h))
            host = h
            break
        except Exception as e:
            print(f"{h}: недоступен ({e})")
    if not host:
        print("Ни один источник не отвечает. Проверь сеть и запусти снова.")
        return 1
    have = DEST.stat().st_size if DEST.exists() else 0
    print(f"Источник: {host}\nФайл: {FILE}  ({total/1e9:.1f} ГБ, "
          f"докачано {have/1e9:.1f} ГБ)")
    if dry:
        return 0
    if have >= total > 0:
        print("Уже скачан целиком.")
    else:
        req = urllib.request.Request(_url(host))
        if have:
            req.add_header("Range", f"bytes={have}-")
        t0, done = time.time(), have
        with urllib.request.urlopen(req, timeout=60) as r, \
                open(DEST, "ab") as f:
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                if done % (200 << 20) < (1 << 20):
                    spd = (done - have) / max(1, time.time() - t0) / 1e6
                    print(f"  {done/1e9:.1f} / {total/1e9:.1f} ГБ "
                          f"({spd:.0f} МБ/с)", flush=True)
        print("Скачан.")
    # прописать в конфиг: model_path — самый прямой путь, без поиска
    cfgp = ROOT / "config.json"
    cfg = json.loads(cfgp.read_text(encoding="utf-8"))
    cfg.setdefault("llm", {})["model"] = MODEL_NAME
    cfg.setdefault("llamacpp", {})["model_path"] = str(DEST)
    # рефлекторным командам думанье не нужно; в разговоре Qwen сам решает
    cfg["llm"]["think"] = False
    cfgp.write_text(json.dumps(cfg, ensure_ascii=False, indent=2),
                    encoding="utf-8")
    print(f"Прописан в config.json: llm.model={MODEL_NAME}. "
          "Живая замена подхватит сама — кнопки не нужны: скажи ей "
          "«переключись на qwen3-14b» или выбери в списке моделей.")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    sys.exit(download(dry=ap.parse_args().dry))
