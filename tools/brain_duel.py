"""ОЧНАЯ СТАВКА МОЗГОВ — слепое сравнение моделей на характере Сайки.

Зачем. Бенчмарки меряют знания, а нам нужен голос: держит ли модель
характер под наездом, шутит ли на статусе, умеет ли промолчать. Это
не меряется числом — это читается глазами. Но читать, зная имя модели,
бесполезно: ожидание красит ответ. Поэтому скрипт делает две вещи —
снимает честные цифры (первый токен, ток/с) и раскладывает ответы под
шифрами A/B/C, чтобы читать их вслепую и только потом смотреть ключ.

Порядок работы:
    python tools\\brain_duel.py --fetch          скачать кандидатов (докачка, зеркало)
    python tools\\brain_duel.py --fetch --dry    только показать размеры и что влезет
    python tools\\brain_duel.py --run            прогнать сцены, собрать слепой отчёт
    python tools\\brain_duel.py --run --only gemma4-26b-a4b-q3xl
    python tools\\brain_duel.py --key <папка>    открыть ключ ПОСЛЕ того, как прочёл

Кандидаты — eval/duel_models.json, сцены — eval/scenes_character.json.
Результат — eval/duel/<дата>/: blind.md (читать), speed.csv (цифры),
key.json (открывать последним).

ВАЖНО про VRAM: скрипт поднимает СВОЙ llama-server на свободном порту и
гасит его после каждой модели. Но если в это время работает Сайка — на
карте уже сидят её мозг, клон-голос и слух, и большая модель просто не
влезет. Останови Сайку перед прогоном.
"""
import argparse
import json
import os
import random
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HOSTS = ["https://hf-mirror.com", "https://huggingface.co"]
GGUF_DIR = ROOT / "models" / "gguf"
OUT_ROOT = ROOT / "eval" / "duel"


def _load(name):
    return json.loads((ROOT / "eval" / name).read_text(encoding="utf-8"))


def _dest(m):
    if m.get("path"):
        return Path(m["path"])
    return GGUF_DIR / m["file"]


# ---------------------------------------------------------------- скачивание
def _url(host, m):
    return f"{host}/{m['repo']}/resolve/main/{m['file']}?download=true"


def _head(url):
    req = urllib.request.Request(url, method="HEAD")
    with urllib.request.urlopen(req, timeout=20) as r:
        return int(r.headers.get("Content-Length") or 0)


def fetch(dry=False, only=None):
    GGUF_DIR.mkdir(parents=True, exist_ok=True)
    for m in _load("duel_models.json")["models"]:
        if only and m["id"] != only:
            continue
        if not m.get("repo"):
            p = _dest(m)
            print(f"[{m['id']}] локальный файл: {p} "
                  f"{'— на месте' if p.exists() else '— НЕ НАЙДЕН'}")
            continue
        dest, total, host = _dest(m), 0, ""
        for h in HOSTS:
            try:
                total, host = _head(_url(h, m)), h
                break
            except Exception as e:
                print(f"[{m['id']}] {h}: недоступен ({e})")
        if not host:
            print(f"[{m['id']}] ни одно зеркало не отвечает — пропускаю")
            continue
        have = dest.stat().st_size if dest.exists() else 0
        print(f"[{m['id']}] {m['file']}  {total/1e9:.1f} ГБ "
              f"(уже есть {have/1e9:.1f})  — {m.get('note','')}")
        if dry or have >= total > 0:
            if have >= total > 0:
                print("   уже скачан целиком")
            continue
        req = urllib.request.Request(_url(host, m))
        if have:
            req.add_header("Range", f"bytes={have}-")
        t0, done = time.time(), have
        with urllib.request.urlopen(req, timeout=60) as r, open(dest, "ab") as f:
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                if done % (500 << 20) < (1 << 20):
                    spd = (done - have) / max(1, time.time() - t0) / 1e6
                    print(f"   {done/1e9:.1f} / {total/1e9:.1f} ГБ "
                          f"({spd:.0f} МБ/с)", flush=True)
        print("   готово")
    return 0


# ------------------------------------------------------------------- сервер
def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def _binary():
    from anamorf.llm import llamacpp
    return llamacpp.binary()


def _spawn(model_path, port, extra, ctx):
    args = [str(_binary()), "-m", str(model_path),
            "--host", "127.0.0.1", "--port", str(port),
            "--ctx-size", str(ctx), "-ngl", "999", "-fa", "on",
            "--parallel", "1", "--jinja",
            "--reasoning-format", "deepseek",
            "--batch-size", "2048", "--ubatch-size", "512",
            "--alias", "duel"] + list(extra)
    flags = 0
    if os.name == "nt":
        flags = subprocess.CREATE_NEW_PROCESS_GROUP | 0x08000000
    return subprocess.Popen(args, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, creationflags=flags)


def _wait(port, proc, limit=300):
    t0 = time.time()
    while time.time() - t0 < limit:
        if proc.poll() is not None:
            raise RuntimeError("сервер упал при загрузке модели "
                               "(скорее всего не хватило видеопамяти)")
        try:
            with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/health", timeout=2) as r:
                if r.status == 200:
                    return time.time() - t0
        except Exception:
            time.sleep(1)
    raise TimeoutError("сервер не поднялся за отведённое время")


# --------------------------------------------------------------------- ход
def ask(port, system, history, user, max_tokens=400):
    """Стримом — только так видно ЧЕСТНЫЙ первый токен."""
    msgs = [{"role": "system", "content": system}]
    for role, text in history:
        msgs.append({"role": role, "content": text})
    msgs.append({"role": "user", "content": user})
    body = json.dumps({"model": "duel", "messages": msgs, "stream": True,
                       "temperature": 0.8, "max_tokens": max_tokens,
                       "chat_template_kwargs": {"enable_thinking": False}},
                      ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/v1/chat/completions", data=body,
        headers={"Content-Type": "application/json"})
    t0, ttft, out, n = time.time(), None, [], 0
    with urllib.request.urlopen(req, timeout=180) as r:
        for raw in r:
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if payload == "[DONE]":
                break
            try:
                d = json.loads(payload)
            except Exception:
                continue
            piece = (d.get("choices") or [{}])[0].get("delta", {}).get("content")
            if piece:
                if ttft is None:
                    ttft = time.time() - t0
                out.append(piece)
                n += 1
    dt = time.time() - t0
    gen = max(1e-6, dt - (ttft or 0))
    return {"text": "".join(out).strip(), "ttft": ttft or dt,
            "total": dt, "chunks": n, "tps": (n - 1) / gen if n > 1 else 0.0}


# -------------------------------------------------------------------- прогон
def run(only=None, ctx=8192, warm=True):
    from anamorf import persona
    system = persona.build_system_prompt(None, "Виталий")
    scenes = _load("scenes_character.json")["scenes"]
    models = [m for m in _load("duel_models.json")["models"]
              if not only or m["id"] == only]

    stamp = datetime.now().strftime("%Y-%m-%d_%H%M")
    out = OUT_ROOT / stamp
    out.mkdir(parents=True, exist_ok=True)

    letters = [chr(65 + i) for i in range(len(models))]
    random.shuffle(letters)
    key = {letters[i]: m["id"] for i, m in enumerate(models)}
    results = {}

    for i, m in enumerate(models):
        path = _dest(m)
        if not path.exists():
            print(f"[{m['id']}] файла нет: {path} — пропускаю")
            continue
        port = _free_port()
        print(f"\n=== {m['id']} → шифр {letters[i]} (порт {port}) ===")
        proc = _spawn(path, port, m.get("extra", []), ctx)
        try:
            load_s = _wait(port, proc)
            print(f"    загрузилась за {load_s:.0f} с")
            if warm:
                ask(port, system, [], "Скажи одно слово: готова.", 16)
            rows = []
            for sc in scenes:
                r = ask(port, system, sc.get("history", []), sc["user"])
                r["id"], r["tag"] = sc["id"], sc["tag"]
                rows.append(r)
                print(f"    {sc['id']:<14} первый токен {r['ttft']:.2f}с  "
                      f"{r['tps']:.0f} ток/с")
            results[letters[i]] = {"load_s": load_s, "rows": rows}
        except Exception as e:
            print(f"    ОШИБКА: {e}")
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=30)
            except Exception:
                proc.kill()
            time.sleep(3)

    if not results:
        print("Ни одна модель не отработала — отчёта не будет.")
        return 1

    # --- слепой отчёт: внутри каждой сцены порядок шифров тоже мешаем
    lines = ["# Слепая читка\n",
             "Читай ответы, не открывая key.json. Для каждой сцены отметь, "
             "какой шифр звучит как Сайка, а какой — как вежливый ассистент.\n",
             "Ключ — в key.json, цифры — в speed.csv.\n"]
    for sc in scenes:
        lines.append(f"\n## {sc['id']} — {sc['tag']}\n")
        for role, text in sc.get("history", []):
            lines.append(f"> _({role})_ {text}\n")
        lines.append(f"\n**Человек:** {sc['user']}\n")
        order = list(results.keys())
        random.shuffle(order)
        for L in order:
            row = next((r for r in results[L]["rows"] if r["id"] == sc["id"]), None)
            if row:
                lines.append(f"\n**{L}:** {row['text']}\n")
    (out / "blind.md").write_text("".join(lines), encoding="utf-8")

    csv = ["шифр,сцена,первый_токен_с,ток_в_сек,всего_с"]
    for L, data in results.items():
        for r in data["rows"]:
            csv.append(f"{L},{r['id']},{r['ttft']:.3f},{r['tps']:.1f},"
                       f"{r['total']:.2f}")
    (out / "speed.csv").write_text("\n".join(csv), encoding="utf-8")

    (out / "key.json").write_text(json.dumps(
        {"key": {L: key[L] for L in results},
         "load_seconds": {L: round(d["load_s"]) for L, d in results.items()}},
        ensure_ascii=False, indent=2), encoding="utf-8")

    med = {L: sorted(r["ttft"] for r in d["rows"])[len(d["rows"]) // 2]
           for L, d in results.items()}
    avg = {L: sum(r["tps"] for r in d["rows"]) / len(d["rows"])
           for L, d in results.items()}
    print(f"\nГотово: {out}")
    for L in results:
        print(f"  {L}: первый токен (медиана) {med[L]:.2f}с, "
              f"в среднем {avg[L]:.0f} ток/с")
    print("\nСначала прочти blind.md. Ключ откроешь после:")
    print(f"  python tools\\brain_duel.py --key {out.name}")
    return 0


def show_key(name):
    p = OUT_ROOT / name / "key.json"
    if not p.exists():
        print(f"нет такого прогона: {p}")
        return 1
    print(p.read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--fetch", action="store_true")
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--only")
    ap.add_argument("--ctx", type=int, default=8192)
    ap.add_argument("--key")
    a = ap.parse_args()
    if a.key:
        sys.exit(show_key(a.key))
    if a.fetch:
        sys.exit(fetch(dry=a.dry, only=a.only))
    if a.run:
        sys.exit(run(only=a.only, ctx=a.ctx))
    ap.print_help()
