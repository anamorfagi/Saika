"""ЗОЛОТОЙ ГОЛОС СОЗДАТЕЛЯ — зашитый в проект, зашифрованный (2026-07-28).

ЗАДУМКА ВЛАДЕЛЬЦА. Его голос должен ехать ВМЕСТЕ с проектом: поставил Сайку
на другой компьютер — она услышала его и узнала («о, это ты, я тебя помню»),
без записи эталона заново. Но репозиторий публичный, а отпечаток голоса —
биометрия: класть её в git открытой нельзя, это то же правило, по которому
в гитигноре сидят data/ и voice/.

РЕШЕНИЕ — печать. Векторы голоса шифруются AES-GCM ключом из secrets.json
(поле owner_voice_key, генерится само при первом запечатывании). Сам файл
печати лежит В РЕПОЗИТОРИИ, рядом с кодом: без ключа это шум, а ключ живёт
в secrets.json, который и так переносится на новую машину руками — вместе
с остальными секретами. Скопировал secrets.json -> она узнала создателя.

ЧТО ВНУТРИ ПЕЧАТИ: имя, до 60 векторов эталона (float16 — точности хватает,
косинус не замечает), диапазон тона. НЕ звук: восстановить голос из векторов
нельзя, но и вектора чужим глазам ни к чему.
"""
import base64
import json
import logging
import os

import numpy as np

from anamorf.config import ROOT

log = logging.getLogger("saika.voiceprint")

# лежит в репозитории рядом с кодом — потому и шифруется
SEAL_PATH = ROOT / "anamorf" / "voiceprint" / "owner_voice.sealed"
KEY_FIELD = "owner_voice_key"
MAX_VECS = 60


def _secrets_path():
    return ROOT / "secrets.json"


def _load_secrets() -> dict:
    try:
        return json.loads(_secrets_path().read_text("utf-8"))
    except Exception:
        return {}


def _key(create: bool = False):
    """32 байта ключа из secrets.json. create=True — сгенерить и дописать."""
    sec = _load_secrets()
    tok = sec.get(KEY_FIELD)
    if not tok and create:
        tok = base64.urlsafe_b64encode(os.urandom(32)).decode()
        sec[KEY_FIELD] = tok
        try:
            _secrets_path().write_text(
                json.dumps(sec, ensure_ascii=False, indent=2), "utf-8")
            log.info("Печать голоса: ключ создан и записан в secrets.json")
        except Exception as e:
            log.warning("Печать голоса: не смогла дописать ключ в "
                        "secrets.json: %s", e)
            return None
    if not tok:
        return None
    try:
        raw = base64.urlsafe_b64decode(tok.encode())
        if len(raw) >= 32:
            return raw[:32]
        # ключ задали руками произвольной строкой — растягиваем честно
        import hashlib
        return hashlib.pbkdf2_hmac("sha256", tok.encode(), b"saika-owner", 200_000)
    except Exception:
        import hashlib
        return hashlib.pbkdf2_hmac("sha256", str(tok).encode(),
                                   b"saika-owner", 200_000)


def seal(name: str, embs: np.ndarray, stat: dict | None = None) -> dict:
    """Запечатать голос создателя в файл проекта."""
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except Exception:
        return {"ok": False, "error": "нет пакета cryptography — поставится "
                                      "при следующем запуске start.bat"}
    key = _key(create=True)
    if key is None:
        return {"ok": False, "error": "не смогла получить ключ (secrets.json "
                                      "недоступен на запись)"}
    embs = np.asarray(embs, dtype=np.float16)[-MAX_VECS:]
    payload = json.dumps({
        "name": str(name)[:32],
        "dim": int(embs.shape[1]),
        "n": int(len(embs)),
        "stat": {k: stat.get(k) for k in ("plo", "phi")} if stat else {},
        "embs": base64.b64encode(embs.tobytes()).decode(),
    }).encode()
    nonce = os.urandom(12)
    blob = nonce + AESGCM(key).encrypt(nonce, payload, b"saika-owner-voice")
    try:
        SEAL_PATH.write_bytes(blob)
    except Exception as e:
        return {"ok": False, "error": f"не записалась печать: {e}"}
    log.info("Печать голоса: «%s» запечатан (%d векторов, %d байт)",
             name, len(embs), len(blob))
    return {"ok": True, "name": str(name), "vectors": int(len(embs))}


def unseal():
    """-> (имя, векторы float32, stat) или None. Тихо: нет файла или ключа —
    это нормальное состояние чужой машины."""
    if not SEAL_PATH.exists():
        return None
    key = _key(create=False)
    if key is None:
        log.info("Печать голоса найдена, но ключа в secrets.json нет — "
                 "перенеси secrets.json с машины создателя")
        return None
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        blob = SEAL_PATH.read_bytes()
        payload = AESGCM(key).decrypt(blob[:12], blob[12:], b"saika-owner-voice")
        d = json.loads(payload)
        embs = np.frombuffer(base64.b64decode(d["embs"]),
                             dtype=np.float16).reshape(d["n"], d["dim"])
        return d["name"], embs.astype(np.float32), d.get("stat") or {}
    except Exception as e:
        log.warning("Печать голоса не открылась (%s) — ключ не от этой "
                    "печати?", str(e)[:120])
        return None
