# -*- coding: utf-8 -*-
"""agent_images.py — руки ассистента для картинок персонажа.

Три инструмента для chat.py:
  find_images  — поиск картинок в интернете (ddgs: Bing/DDG и др.), отдаёт список кандидатов с размерами;
  set_avatar   — скачать выбранную картинку (по ссылке или номеру из поиска), обрезать до квадрата 600 px,
                 положить в ava/<id>.jpg и вшить в карточку share/<id>.genome.json (поле avatar);
  gen_avatar   — нарисовать картинку в локальном ComfyUI (если он выключен — запустить и дождаться),
                 дальше так же: ava/<id>.jpg + вшивка в карточку.

---- учебный блок: почему кандидаты, а не «первая попавшаяся» ----
Поиск картинок возвращает много мусора: фанарт, постеры с кучей людей, кадры с подписями.
Поэтому find_images только показывает варианты (с размерами и источником), а выбирает агент —
по заголовку и источнику (вики, официальные арты лучше), и уже потом зовёт set_avatar.
"""
import base64, io, json, pathlib, random, subprocess, time, urllib.request, urllib.parse

ROOT = pathlib.Path(__file__).resolve().parent.parent
SHARE, AVA, LOGS = ROOT / "share", ROOT / "ava", ROOT / "logs"
COMFY = "http://127.0.0.1:8188"
COMFY_DIR = pathlib.Path(r"C:\comfy ui\ComfyUI_windows_portable")
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AnamorfGenom/1.0"}
# стиль → чекпоинт и обёртка промпта (теги качества для Illustrious, фото-слова для реализма)
STYLES = {
    "anime": ("waiIllustriousSDXL_v170.safetensors",
              "masterpiece, best quality, amazing quality, very aesthetic, anime illustration, upper body portrait, looking at viewer, detailed eyes, {p}",
              "lowres, worst quality, bad quality, bad anatomy, bad hands, extra fingers, text, watermark, signature, logo, nsfw, nude, multiple people"),
    "real": ("juggernautXL_ragnarok.safetensors",
             "photo portrait, upper body, looking at camera, natural skin texture, soft light, 85mm, sharp focus, {p}",
             "cartoon, anime, illustration, deformed, bad hands, extra fingers, text, watermark, logo, nsfw, nude, multiple people"),
}
_ПОИСК = []   # последний поиск: set_avatar(index=…) берёт отсюда


def _id(x):
    import re
    return re.sub(r"[^a-z0-9_]", "", str(x or "").lower())


def _квадрат(сырые):
    """Любая картинка → квадрат 600×600 JPEG. Верх кадра важнее низа: лицо почти всегда сверху."""
    from PIL import Image
    im = Image.open(io.BytesIO(сырые)).convert("RGB"); w, h = im.size
    if min(w, h) < 200:
        raise RuntimeError(f"картинка слишком маленькая: {w}×{h}")
    if h >= w:
        top = int((h - w) * 0.15); im = im.crop((0, top, w, top + w))
    else:
        left = (w - h) // 2; im = im.crop((left, 0, left + h, h))
    im = im.resize((600, 600), Image.LANCZOS)
    b = io.BytesIO(); im.save(b, "JPEG", quality=88); return b.getvalue(), (w, h)


def _поставить(cid, jpg, откуда):
    """ava/<id>.jpg + вшивка в карточку — как делает студия, когда картинку перетаскивают руками."""
    AVA.mkdir(exist_ok=True); (AVA / f"{cid}.jpg").write_bytes(jpg)
    файл = SHARE / f"{cid}.genome.json"
    if not файл.exists():
        return f"ava/{cid}.jpg записан, но карточки {cid} нет — заведи её, картинка подхватится"
    карта = json.loads(файл.read_text(encoding="utf-8"))
    карта["avatar"] = "data:image/jpeg;base64," + base64.b64encode(jpg).decode()
    карта.setdefault("meta", {})["avatar_src"] = откуда
    файл.write_text(json.dumps(карта, ensure_ascii=False, indent=2), encoding="utf-8")
    return f"аватар поставлен: ava/{cid}.jpg и вшит в share/{cid}.genome.json"


def find_images(query, n=8):
    from ddgs import DDGS
    global _ПОИСК
    with DDGS(timeout=25) as d:
        ряды = list(d.images(query, max_results=max(3, min(int(n or 8), 15))))
    _ПОИСК = [{"url": r.get("image"), "title": r.get("title", ""), "src": r.get("url", ""),
               "w": int(r.get("width") or 0), "h": int(r.get("height") or 0)} for r in ряды if r.get("image")]
    (LOGS.mkdir(exist_ok=True), (LOGS / "_img_search.json").write_text(json.dumps(_ПОИСК, ensure_ascii=False), encoding="utf-8"))
    текст = "\n".join(f"{i}. {x['w']}×{x['h']} · {x['title'][:80]} · {x['src'][:90]}\n   {x['url']}" for i, x in enumerate(_ПОИСК))
    return текст or "картинок не нашлось", [x["url"] for x in _ПОИСК]


def set_avatar(cid, url="", index=None):
    cid = _id(cid)
    if not cid:
        raise RuntimeError("нужен id персонажа латиницей")
    if not url and index is not None and str(index) != "":
        i = int(index)
        поиск = _ПОИСК or json.loads((LOGS / "_img_search.json").read_text(encoding="utf-8")) if (LOGS / "_img_search.json").exists() else _ПОИСК
        if not (0 <= i < len(поиск)):
            raise RuntimeError(f"в последнем поиске нет номера {i} — сначала find_images")
        url = поиск[i]["url"]
    if not url:
        raise RuntimeError("нужна ссылка на картинку или номер из find_images")
    req = urllib.request.Request(url, headers=UA)
    сырые = urllib.request.urlopen(req, timeout=30).read()
    jpg, (w, h) = _квадрат(сырые)
    итог = _поставить(cid, jpg, {"from": "web", "url": url, "orig": f"{w}x{h}", "at": time.strftime("%Y-%m-%d %H:%M")})
    return f"скачано {len(сырые)//1024} КБ, исходник {w}×{h} → 600×600. {итог}", [f"/ava/{cid}.jpg?t={int(time.time())}"]


def _comfy_жив():
    try:
        urllib.request.urlopen(COMFY + "/system_stats", timeout=3); return True
    except Exception:
        return False


def _comfy_запустить(ждать=180):
    """ComfyUI выключен — запускаем его батник сами (свёрнутым окном) и ждём, пока поднимется API."""
    bat = COMFY_DIR / "run_nvidia_gpu.bat"
    if not bat.exists():
        raise RuntimeError(f"ComfyUI не найден: {bat}")
    subprocess.Popen(["cmd", "/c", "start", "/min", "ComfyUI", str(bat)], cwd=str(COMFY_DIR))
    t0 = time.time()
    while time.time() - t0 < ждать:
        if _comfy_жив():
            return round(time.time() - t0)
        time.sleep(3)
    raise RuntimeError(f"ComfyUI не поднялся за {ждать} с")


def gen_avatar(cid, prompt, style="anime", seed=None):
    cid = _id(cid)
    if not cid or not prompt:
        raise RuntimeError("нужны id и prompt (теги внешности по-английски)")
    ckpt, pos, neg = STYLES.get(style, STYLES["anime"])
    запуск = "" if _comfy_жив() else f"ComfyUI был выключен — запустил, поднялся за {_comfy_запустить()} с. "
    seed = int(seed) if seed not in (None, "") else random.randint(1, 2**31)
    граф = {
        "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": ckpt}},
        "2": {"class_type": "CLIPTextEncode", "inputs": {"text": pos.format(p=prompt), "clip": ["1", 1]}},
        "3": {"class_type": "CLIPTextEncode", "inputs": {"text": neg, "clip": ["1", 1]}},
        "4": {"class_type": "EmptyLatentImage", "inputs": {"width": 896, "height": 1152, "batch_size": 1}},
        "5": {"class_type": "KSampler", "inputs": {"model": ["1", 0], "positive": ["2", 0], "negative": ["3", 0], "latent_image": ["4", 0],
              "seed": seed, "steps": 28, "cfg": 5.5, "sampler_name": "euler_ancestral", "scheduler": "normal", "denoise": 1.0}},
        "6": {"class_type": "VAEDecode", "inputs": {"samples": ["5", 0], "vae": ["1", 2]}},
        "7": {"class_type": "SaveImage", "inputs": {"images": ["6", 0], "filename_prefix": "genome_agent"}},
    }
    req = urllib.request.Request(COMFY + "/prompt", data=json.dumps({"prompt": граф}).encode(), headers={"Content-Type": "application/json"})
    pid = json.loads(urllib.request.urlopen(req, timeout=30).read())["prompt_id"]
    t0 = time.time()
    while time.time() - t0 < 300:
        h = json.loads(urllib.request.urlopen(f"{COMFY}/history/{pid}", timeout=30).read())
        if pid in h and h[pid].get("outputs"):
            im = h[pid]["outputs"]["7"]["images"][0]
            q = urllib.parse.urlencode({"filename": im["filename"], "subfolder": im["subfolder"], "type": im["type"]})
            png = urllib.request.urlopen(f"{COMFY}/view?{q}", timeout=60).read(); break
        if pid in h and h[pid].get("status", {}).get("status_str") == "error":
            raise RuntimeError("ComfyUI: " + json.dumps(h[pid]["status"])[:300])
        time.sleep(1.5)
    else:
        raise RuntimeError("ComfyUI не отдал картинку за 300 с")
    LOGS.mkdir(exist_ok=True); (LOGS / f"{cid}.agent.png").write_bytes(png)
    jpg, _ = _квадрат(png)
    итог = _поставить(cid, jpg, {"from": "ComfyUI", "ckpt": ckpt, "seed": seed, "prompt": prompt, "sec": round(time.time() - t0, 1)})
    return f"{запуск}нарисовано за {time.time()-t0:.1f} с ({ckpt}, seed {seed}). {итог}", [f"/ava/{cid}.jpg?t={int(time.time())}"]
