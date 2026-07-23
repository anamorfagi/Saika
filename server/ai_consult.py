"""Умная облачная починка — «консилиум» Беймакса (2026-07-23).

Локальный Беймакс говорит шаблонами и чинит по шпаргалке. Когда случается
что-то умное (модель молчит, странные ошибки), зовём СИЛЬНУЮ облачную модель
(Kimi K3, ключ в secrets.json -> llm.cloud_keys.kimi): даём ей симптом +
хвост лога, она возвращает 2-4 строки «что это и что сделать прямо сейчас»,
и совет уходит в чат пузырём Беймакса.

Не мешает работе: всё в фоне, с кулдауном (consult.cooldown_s, 180с), при
отсутствии ключа/сети просто молчит. Настройки: consult.enabled,
consult.model (kimi-k3), consult.base_url.
"""
import json
import logging
import threading
import time

import requests

from server.config import CFG, ROOT

log = logging.getLogger("saika.consult")
_last = {"ts": 0.0}


def _kimi_key() -> str:
    try:
        s = json.loads((ROOT / "secrets.json").read_text(encoding="utf-8"))
        lm = s.get("llm", {}) or {}
        return ((lm.get("cloud_keys", {}) or {}).get("kimi", "")
                or "")
    except Exception:
        return ""


def available() -> bool:
    return bool(_kimi_key())


def _log_tail(n_chars: int = 4000) -> str:
    try:
        return (ROOT / "logs" / "saika.log").read_text(
            encoding="utf-8", errors="ignore")[-n_chars:]
    except Exception:
        return ""


def consult_async(problem: str, broadcast):
    """Спросить облачного доктора и передать совет в чат.
    broadcast(dict) — рассылка события всем websocket-клиентам (как пузыри
    Беймакса в report_problem). Вызов дешёвый: сам решает, идти ли (ключ,
    кулдаун), работа — в фоновом потоке."""
    if not CFG.get("consult.enabled", True) or not available():
        return False
    now = time.time()
    if now - _last["ts"] < CFG.get("consult.cooldown_s", 180):
        return False
    _last["ts"] = now

    def run():
        try:
            base = (CFG.get("consult.base_url",
                            "https://api.moonshot.ai/v1") or "").rstrip("/")
            model = CFG.get("consult.model", "kimi-k3")
            # без temperature: Moonshot на части моделей принимает только
            # своё значение и отвечает 400 на любое другое
            r = requests.post(
                base + "/chat/completions",
                headers={"Authorization": "Bearer " + _kimi_key()},
                json={"model": model, "max_tokens": 400,
                      "messages": [
                          {"role": "system", "content":
                           "Ты — инженер-медик локального голосового "
                           "ассистента «Сайка» (Windows, FastAPI, LM Studio/"
                           "Ollama, GPU 16 ГБ VRAM). Тебе дают симптом и "
                           "хвост лога. Ответь ПО-РУССКИ, 2-4 короткие "
                           "строки: (1) наиболее вероятная причина, "
                           "(2) что сделать прямо сейчас — конкретно (какую "
                           "модель выгрузить, что перезапустить, какую "
                           "настройку поменять). Без воды, без markdown."},
                          {"role": "user", "content":
                           f"Симптом: {problem}\n\nХвост лога:\n{_log_tail()}"
                           }]},
                timeout=45)
            if not r.ok:
                # тело ответа — единственное объяснение провайдера, почему
                # 400 (raise_for_status его теряет)
                raise RuntimeError(f"{r.status_code}: {r.text[:300]}")
            text = ((r.json().get("choices") or [{}])[0]
                    .get("message", {}).get("content", "") or "").strip()
            if text:
                log.info("Консилиум (%s): %s", model, text)
                broadcast({"type": "baymax", "mood": "meh",
                           "text": "🩺 Консилиум (" + model + "): " + text})
        except Exception as e:
            log.info("Консилиум не удался: %s", e)

    threading.Thread(target=run, daemon=True).start()
    return True
