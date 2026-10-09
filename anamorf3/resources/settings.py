"""Настройки resources/ — свой файл, НЕ config.json старой Сайки.

ЗАЧЕМ (2026-10-09): у старой системы 640 ключей, и движок нового ядра
читал их вперемешку со старыми сторожами. Здесь всё, что нужно ресурсам,
лежит в одном маленьком settings.json рядом с кодом.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]          # C:/AI/Saika
_FILE = Path(__file__).with_name("settings.json")


def load(override: dict | None = None) -> dict:
    s = json.loads(_FILE.read_text(encoding="utf-8"))
    s.pop("_doc", None)
    if override:                                    # для стенда и тестов
        for k, v in override.items():
            if isinstance(v, dict) and isinstance(s.get(k), dict):
                s[k] = {**s[k], **v}
            else:
                s[k] = copy.deepcopy(v)
    return s


def path(p: str) -> Path:
    q = Path(p)
    return q if q.is_absolute() else ROOT / q


def secret(s: dict, ref: str) -> str:
    """Достать ключ по ссылке вида 'llm.cloud_keys.mistral'. Значение
    никуда не пишется и в status() не попадает — только факт наличия."""
    try:
        o = json.loads(path(s["secrets_file"]).read_text(encoding="utf-8-sig"))
        for part in ref.split("."):
            o = o[part]
        return str(o or "")
    except Exception:
        return ""
