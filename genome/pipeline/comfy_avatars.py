#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
comfy_avatars.py — аватары для готовых образов через локальный ComfyUI (:8188).

Что делает по шагам:
  1. читает share/obraz_*.genome.json, берёт meta.img_prompt (теги внешности под характер)
  2. отправляет в ComfyUI простой SDXL-граф (checkpoint → 2×CLIP → KSampler → VAE → Save)
  3. ждёт результат через /history, скачивает PNG через /view
  4. кладёт ava/<id>.jpg (600 px) и вшивает тот же JPEG в файл персонажа (поле avatar)

Запуск:  python comfy_avatars.py                 → все без аватара
         python comfy_avatars.py --only kovarn --force --seed 7
"""
import json, time, random, base64, io, argparse, pathlib, urllib.request, urllib.parse
from PIL import Image

ROOT = pathlib.Path(__file__).parent.parent
SHARE, AVA = ROOT / "share", ROOT / "ava"
URL = "http://127.0.0.1:8188"
CKPT = "waiIllustriousSDXL_v170.safetensors"

# ---- учебный блок: качество и запреты для Illustrious-моделей ----
POS = "masterpiece, best quality, amazing quality, very aesthetic, anime illustration, game character art, adult woman, upper body portrait, looking at viewer, detailed eyes, {img}"
NEG = "lowres, worst quality, bad quality, bad anatomy, bad hands, extra fingers, text, watermark, signature, logo, nsfw, nude, child, loli, multiple girls"

def graph(pos, neg, seed):
    """API-формат ComfyUI: узлы по номерам, связи — [номер_узла, номер_выхода]."""
    return {
        "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": CKPT}},
        "2": {"class_type": "CLIPTextEncode", "inputs": {"text": pos, "clip": ["1", 1]}},
        "3": {"class_type": "CLIPTextEncode", "inputs": {"text": neg, "clip": ["1", 1]}},
        "4": {"class_type": "EmptyLatentImage", "inputs": {"width": 896, "height": 1152, "batch_size": 1}},
        "5": {"class_type": "KSampler", "inputs": {"model": ["1", 0], "positive": ["2", 0], "negative": ["3", 0], "latent_image": ["4", 0],
              "seed": seed, "steps": 28, "cfg": 5.5, "sampler_name": "euler_ancestral", "scheduler": "normal", "denoise": 1.0}},
        "6": {"class_type": "VAEDecode", "inputs": {"samples": ["5", 0], "vae": ["1", 2]}},
        "7": {"class_type": "SaveImage", "inputs": {"images": ["6", 0], "filename_prefix": "genome_obraz"}},
    }

def post(path, data):
    req = urllib.request.Request(URL + path, data=json.dumps(data).encode(), headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=30).read())

def run(pos, neg, seed):
    pid = post("/prompt", {"prompt": graph(pos, neg, seed)})["prompt_id"]
    t0 = time.time()
    while True:
        h = json.loads(urllib.request.urlopen(f"{URL}/history/{pid}", timeout=30).read())
        if pid in h and h[pid].get("outputs"):
            im = h[pid]["outputs"]["7"]["images"][0]
            q = urllib.parse.urlencode({"filename": im["filename"], "subfolder": im["subfolder"], "type": im["type"]})
            return urllib.request.urlopen(f"{URL}/view?{q}", timeout=60).read(), time.time() - t0
        if pid in h and h[pid].get("status", {}).get("status_str") == "error":
            raise RuntimeError(json.dumps(h[pid]["status"])[:400])
        time.sleep(1.5)

def to_jpeg(png):
    """Квадрат по верхней части (лицо в кадре) → 600×600 JPEG — так же, как студия ужимает аватары."""
    im = Image.open(io.BytesIO(png)).convert("RGB"); w, h = im.size
    top = int(h * 0.04); im = im.crop((0, top, w, top + w)).resize((600, 600), Image.LANCZOS)
    b = io.BytesIO(); im.save(b, "JPEG", quality=88); return b.getvalue()

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--only"); ap.add_argument("--force", action="store_true"); ap.add_argument("--seed", type=int)
    a = ap.parse_args(); AVA.mkdir(exist_ok=True)
    for f in sorted(SHARE.glob("obraz_*.genome.json")):
        obj = json.loads(f.read_text(encoding="utf-8")); cid = obj["id"]
        if a.only and a.only not in cid: continue
        if obj.get("avatar") and not a.force: print(cid, "— аватар уже есть"); continue
        seed = a.seed if a.seed is not None else random.Random(cid).randint(1, 2**31)
        png, dt = run(POS.format(img=obj["meta"]["img_prompt"]), NEG, seed)
        jpg = to_jpeg(png)
        (AVA / f"{cid}.jpg").write_bytes(jpg)
        (ROOT / "logs").mkdir(exist_ok=True); (ROOT / "logs" / f"{cid}.full.png").write_bytes(png)
        obj["avatar"] = "data:image/jpeg;base64," + base64.b64encode(jpg).decode()
        obj["meta"]["avatar_gen"] = {"engine": "ComfyUI", "ckpt": CKPT, "seed": seed, "sec": round(dt, 1)}
        f.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"{cid:28} seed {seed:<11} {dt:5.1f} c → ava/{cid}.jpg", flush=True)
