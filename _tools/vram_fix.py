# -*- coding: utf-8 -*-
"""План памяти перестаёт считать свою же занятую память чужой."""
import io, sys
sc_p, vp_p = sys.argv[1], sys.argv[2]

# ── 1. список процессов на карте не теряется, когда Windows не даёт цифру ──
s = io.open(sc_p, encoding='utf-8').read()
a = """        out = []
        for line in r.stdout.strip().splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 3 and parts[1].isdigit():
                name = ",".join(parts[2:])
                out.append((name, parts[0], int(parts[1])))"""
b = """        out = []
        for line in r.stdout.strip().splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) < 3 or not parts[0].isdigit():
                continue
            # ПАМЯТЬ ПО ПРОЦЕССАМ WINDOWS НЕ ОТДАЁТ (27.08.2026). На WDDM
            # nvidia-smi пишет в этой колонке «[N/A]» или «Insufficient
            # Permissions» — и строка целиком отбрасывалась. Список
            # становился ПУСТЫМ, хотя на карте сидели и llama-server, и наш
            # же python. Планировщик памяти делал из пустого списка вывод
            # «своего на карте нет» и считал занятое чужим. Имя процесса
            # нам известно всегда — сохраняем строку с нулём вместо цифры.
            name = ",".join(parts[2:])
            mb = int(parts[1]) if parts[1].isdigit() else 0
            out.append((name, parts[0], mb))"""
assert s.count(a) == 1, 'gpu_top_processes'
io.open(sc_p, 'w', encoding='utf-8').write(s.replace(a, b))

# ── 2. свою занятую память оцениваем, а не вычитаем в ноль ────────────────
s = io.open(vp_p, encoding='utf-8').read()
a2 = """def total_gb() -> float:"""
b2 = '''def own_est_gb(weights_gb: float) -> float:
    """Сколько видеопамяти держат НАШИ уже поднятые движки.

    ЗАЧЕМ (27.08.2026, живой случай владельца: «эта ллм, мой голос и слух
    должны работать одновременно — и работали»). Раньше своё считалось по
    колонке used_memory из nvidia-smi. На Windows её нет: карта отвечает
    «[N/A]» без прав администратора. Своё выходило нулём, свободного на
    карте — два гигабайта из шестнадцати (всё остальное держим мы сами!),
    и план каждый раз приходил к выводу «не влезает даже с окном 4096».
    Дальше сервер поднимался с окном 4096, куда её собственный промпт на
    восемь тысяч токенов не влезает НИКОГДА, — и каждый ход отвечал 400.
    Рабочая связка ломалась не от нехватки памяти, а от слепоты замера.

    Считаем по тому, что мы сами и загрузили: живой llama-server — это вес
    модели плюс KV текущего окна; живой процесс Сайки — голос и слух."""
    names = []
    try:
        from anamorf import system_control as sc
        names = [(n or "").lower() for n, _pid, _mb in sc.gpu_top_processes(64)]
    except Exception:
        pass
    own = 0.0
    if any("llama" in n for n in names):
        try:
            cur = int(CFG.get("llamacpp.n_ctx_live", 0) or 0)
        except Exception:
            cur = 0
        own += weights_gb + kv_gb(weights_gb, cur or _CTX_STEPS[-1])
    if any("python" in n or "anamorf" in n for n in names):
        own += voice_gb() + stt_gb()
    return own


def total_gb(weights_gb: float = 0.0) -> float:'''
assert s.count(a2) == 1, 'total_gb def'
s = s.replace(a2, b2)

a3 = """            try:
                own = sum(m for n, _pid, m in sc.gpu_top_processes(16)
                          if any(o in (n or "").lower() for o in _OUR_GPU))
            except Exception:
                own = 0
            avail = min(total, free + own)"""
b3 = """            try:
                own = sum(m for n, _pid, m in sc.gpu_top_processes(64)
                          if any(o in (n or "").lower() for o in _OUR_GPU))
            except Exception:
                own = 0
            own_gb = max(own / 1024.0, own_est_gb(weights_gb))
            avail = min(total / 1024.0, free / 1024.0 + own_gb) * 1024.0"""
assert s.count(a3) == 1, 'own calc'
s = s.replace(a3, b3)

a4 = """    total = total_gb()
    v, s = voice_gb(), stt_gb()"""
b4 = """    total = total_gb(weights_gb)
    v, s = voice_gb(), stt_gb()"""
assert s.count(a4) == 1, 'plan total'
s = s.replace(a4, b4)

# ── 3. окно меньше её собственного промпта — не окно ──────────────────────
a5 = "_CTX_STEPS = (16384, 12288, 8192, 6144, 4096)"
b5 = """# НИЖЕ 8192 ОКНА НЕ БЫВАЕТ (27.08.2026). Её собственный промпт — характер,
# память, инструменты — стабильно 7.5–8 тысяч токенов. Окно 4096 не «хуже»,
# оно нерабочее по построению: движок отвечает 400 на КАЖДЫЙ ход. Предлагать
# его как компромисс — значит поднять заведомо мёртвый мозг и молчать об этом.
_CTX_STEPS = (16384, 12288, 8192)"""
assert s.count(a5) == 1, 'ctx steps'
s = s.replace(a5, b5)

io.open(vp_p, 'w', encoding='utf-8').write(s)
print('ok')
