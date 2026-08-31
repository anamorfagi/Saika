# -*- coding: utf-8 -*-
"""РАЗУМ — вторая архитектура памяти: L1–L4, карты личностей,
цитатник, качели доверия и критики, режим спарринга.

Имя не «saika_memory» намеренно: так называется БАЗА старой
памяти (data/saika_memory.db), и два разных смысла у одного
слова в одном проекте — это ловушка, а не экономия.
"""
from . import (config, db, identity, writer, consolidation, recall,  # noqa
               persons, llm, onboarding, codex, balance, spar, tuning,
               temper, circles, patterns, stance, ladder, moves, score)

__version__ = "0.1.0"
