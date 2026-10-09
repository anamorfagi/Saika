"""ГЛАЗА ЯДРА v2 — тем же мозгом.

Было: look_screen звал ОТДЕЛЬНУЮ модель зрения (в логе — Poe-8B через
второй движок): 25 с на загрузку, ещё гигабайты памяти, и «кадр сделан,
но разобрать не вышло». А Qwen3.6 сама мультимодальная — проектор
картинок (mmproj) уже загружен в движок ядра. Значит: кадр -> тот же
движок -> описание. Ноль новых процессов.
"""
import logging
import time

import requests

from anamorf.core import engine

log = logging.getLogger("saika.core.eyes")


def look(source: str = "screen", question: str = "", monitor=None) -> str:
    from anamorf import vision
    t0 = time.monotonic()
    try:
        if source == "camera":
            img = vision.grab_camera()
        else:
            mon = None
            try:
                mon = int(monitor) if monitor not in (None, "", -1, "-1") else None
            except Exception:
                mon = None
            img = vision.grab_screen(mon)
        if img is None:
            return "кадр не снялся — глаза не получили картинку"
        url = vision.to_data_url(img, max_side=1280, quality=80)
    except Exception as e:
        return f"кадр не снялся: {e}"
    q = question.strip() or "Что сейчас на экране? Коротко: какие окна, что в них главное."
    body = {"model": "saika-core", "max_tokens": 400, "temperature": 0.2,
            "id_slot": 1,                    # служебный слот: разговор не трогаем
            "chat_template_kwargs": {"enable_thinking": False},
            "messages": [{"role": "user", "content": [
                {"type": "text", "text": q + " Отвечай по-русски, по фактам, без догадок."},
                {"type": "image_url", "image_url": {"url": url}}]}]}
    try:
        r = requests.post(engine.url() + "/v1/chat/completions", json=body, timeout=90)
        r.raise_for_status()
        txt = (r.json()["choices"][0]["message"].get("content") or "").strip()
    except Exception as e:
        return f"кадр снят, но разобрать не вышло: {e}"
    log.info("глаза ядра: %s за %.1f с", source, time.monotonic() - t0)
    return f"(увидела сама, {source}) {txt}"
