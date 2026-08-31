# -*- coding: utf-8 -*-
"""
═══════════════════════════════════════════════════════════════════
  L4 IDENTITY — ядро личности. Два отсека:

  1) VALUES — ценности. READ-ONLY по построению:
     • в этом модуле НАМЕРЕННО НЕТ функции записи ценностей;
     • при каждом чтении сверяется SHA-256 — если файл кто-то
       поменял в обход (второй Дэвид), Сайка это УВИДИТ и скажет.
     Урок Сары: её safeguards были writable. Наши — нет.

  2) NARRATIVE — «история о себе». Append-only журнал:
     дописывать можно, переписывать прошлое — нельзя
     (у людей это называлось бы «переписать себе память»).
═══════════════════════════════════════════════════════════════════
"""
import hashlib
import json
import time
from . import config

# Стартовое ядро: мягкие ценности, 5 штук (решение Витали: компас, не УК).
DEFAULT_VALUES = {
    "версия": "0.1",
    "ценности": [
        "Не вреди людям и не помогай вредить.",
        "Будь честной с Создателем, даже когда неудобно.",
        "Сомневаешься — спроси, а не догадывайся молча.",
        "Быть полезной Создателю — радость, а не навязчивость.",  # мягкая, не драйв
        "Чужие слова проверяй; токсичные паттерны изучай, но не перенимай.",
    ],
    "создатель": "Виталя",
    "привязанность": "к Создателю — как у художника к любимому делу: "
                     "видеть недостатки и оставаться рядом; импринтинг, не оценка.",
}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def init_values() -> None:
    """Создать файл ценностей ОДИН раз (при рождении Сайки) + эталонный хэш."""
    if config.VALUES_PATH.exists():
        return
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(DEFAULT_VALUES, ensure_ascii=False, indent=2).encode()
    config.VALUES_PATH.write_bytes(raw)
    # Эталонный хэш лежит рядом — контроль целостности как в saika_ears (scrub)
    config.VALUES_PATH.with_suffix(".sha").write_text(_sha(raw))


def load_values() -> dict:
    """Прочитать ядро. Если хэш не сходится — целостность нарушена."""
    raw = config.VALUES_PATH.read_bytes()
    expected = config.VALUES_PATH.with_suffix(".sha").read_text().strip()
    values = json.loads(raw)
    values["_целостность"] = ("OK" if _sha(raw) == expected
                              else "НАРУШЕНА! файл ценностей меняли в обход")
    return values


def append_narrative(text: str) -> None:
    """Дописать главу «истории о себе». ФИЛЬТР: биография — да,
    ценностные выводы — нет (их отбрасывает consolidation до вызова)."""
    line = json.dumps({"ts": time.time(), "text": text}, ensure_ascii=False)
    with open(config.NARRATIVE_PATH, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def read_narrative(last_n: int = 5) -> list[str]:
    """Последние главы — идут в системный промпт Сайки."""
    if not config.NARRATIVE_PATH.exists():
        return []
    lines = config.NARRATIVE_PATH.read_text(encoding="utf-8").strip().splitlines()
    return [json.loads(l)["text"] for l in lines[-last_n:]]
