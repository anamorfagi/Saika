"""ЧТО ВНУТРИ ФАЙЛА МОДЕЛИ — ЧИТАЕМ, А НЕ УГАДЫВАЕМ (2026-09-05).

Владелец: «нужна модель нормальная по качеству, окно 120 тысяч, и чтобы
всё работало как часы, и игру одновременно».

До этого план памяти (anamorf/vramplan.py) считал KV-кэш пропорцией от
РАЗМЕРА ФАЙЛА: «8 ГБ весов ≈ 1.4 ГБ на 16k». Для плотной модели это
терпимая грубость. Для MoE это ложь в разы: у Qwen3.6-35B-A3B файл на
21 ГБ, а KV живёт только во внимании — там сорок восемь слоёв по четыре
KV-головы, и на те же 16k нужно меньше гигабайта. Планировщик по старой
пропорции решал бы, что не влезает ничего, и резал окно до 8192 — ровно
то молчаливое ужимание, на которое владелец и жаловался.

Здесь читается заголовок GGUF: числа берутся из самого файла. Модель при
этом НЕ загружается — читаются первые сотни килобайт.

Отдельно считается разделение весов: тензоры экспертов (ffn_*_exps) — те
самые, что флаг --n-cpu-moe уводит в системную память, — против всего
остального, что обязано лежать на карте. Это позволяет сказать честно:
«из двадцати одного гигабайта на карту ляжет два с половиной».
"""
import logging
import struct
from pathlib import Path

log = logging.getLogger("saika.gguf")

# (размер блока, байт на блок) по номеру типа ggml. Нужно, чтобы посчитать
# вес тензора по его форме и типу, не читая сами данные.
_GGML = {
    0: (1, 4), 1: (1, 2), 2: (32, 18), 3: (32, 20), 6: (32, 22),
    7: (32, 24), 8: (32, 34), 9: (32, 36), 10: (256, 84), 11: (256, 110),
    12: (256, 144), 13: (256, 176), 14: (256, 210), 15: (256, 292),
    16: (256, 66), 17: (256, 74), 18: (256, 98), 19: (256, 50),
    20: (32, 18), 21: (256, 110), 22: (256, 82), 23: (256, 136),
    24: (1, 1), 25: (1, 2), 26: (1, 4), 27: (1, 8), 28: (1, 8),
    29: (256, 56), 30: (1, 2), 39: (32, 17),
}

# сколько байт на элемент занимает KV-кэш при данном квантовании
KV_BYTES = {"f32": 4.0, "f16": 2.0, "bf16": 2.0,
            "q8_0": 34 / 32.0, "q5_1": 24 / 32.0, "q5_0": 22 / 32.0,
            "q4_1": 20 / 32.0, "q4_0": 18 / 32.0, "iq4_nl": 18 / 32.0}


class _R:
    """Курсор по файлу. Заголовок GGUF читается строго последовательно,
    поэтому проще держать позицию, чем таскать её через все функции."""

    def __init__(self, f):
        self.f = f

    def raw(self, n):
        b = self.f.read(n)
        if len(b) != n:
            raise EOFError("файл модели обрывается на заголовке")
        return b

    def u32(self):
        return struct.unpack("<I", self.raw(4))[0]

    def u64(self):
        return struct.unpack("<Q", self.raw(8))[0]

    def s(self):
        return self.raw(self.u64()).decode("utf-8", "replace")

    def val(self, t):
        if t == 8:
            return self.s()
        if t == 9:                                    # массив
            et = self.u32()
            n = self.u64()
            # длинные массивы (словарь токенизатора — сотни тысяч строк)
            # нам не нужны ни разу: пропускаем, но пропустить можно только
            # прочитав, потому что строки переменной длины
            out = []
            for i in range(n):
                v = self.val(et)
                if i < 64:
                    out.append(v)
            return out
        fmt = {0: "<B", 1: "<b", 2: "<H", 3: "<h", 4: "<I", 5: "<i",
               6: "<f", 7: "<?", 10: "<Q", 11: "<q", 12: "<d"}.get(t)
        if not fmt:
            raise ValueError(f"неизвестный тип значения GGUF: {t}")
        return struct.unpack(fmt, self.raw(struct.calcsize(fmt)))[0]


def read(path: str) -> dict:
    """Паспорт модели из заголовка GGUF.

    Возвращает: arch, n_layer, n_head_kv, k_len, v_len, n_expert,
    ctx_train, gb_total, gb_experts, gb_rest. Всё, чего не нашли,
    отсутствует в словаре — вызывающий обязан это пережить, а не
    подставлять красивое число вместо правды."""
    p = Path(path)
    out = {"path": str(p), "gb_file": p.stat().st_size / (1 << 30)}
    with open(p, "rb") as f:
        r = _R(f)
        if r.raw(4) != b"GGUF":
            raise ValueError("это не файл GGUF")
        r.u32()                                        # версия
        n_tensor = r.u64()
        n_kv = r.u64()
        kv = {}
        for _ in range(n_kv):
            k = r.s()
            kv[k] = r.val(r.u32())
        arch = str(kv.get("general.architecture") or "")
        out["arch"] = arch
        out["name"] = str(kv.get("general.name") or p.stem)

        def a(key, default=None):
            return kv.get(f"{arch}.{key}", default)

        n_layer = a("block_count")
        n_emb = a("embedding_length")
        n_hkv = a("attention.head_count_kv")
        # у некоторых архитектур head_count_kv — массив по слоям (слои без
        # внимания стоят нулём). Тогда KV живёт не во всех слоях, и считать
        # надо по сумме, а не по числу слоёв: ровно этим MoE-гибриды и
        # ломают наивную оценку.
        if isinstance(n_hkv, list) and n_hkv:
            out["kv_layers"] = sum(1 for x in n_hkv if x)
            n_hkv = max(n_hkv)
        else:
            out["kv_layers"] = n_layer
        n_head = a("attention.head_count")
        if isinstance(n_head, list):
            n_head = max(n_head) if n_head else None
        k_len = a("attention.key_length")
        v_len = a("attention.value_length")
        if not k_len and n_emb and n_head:
            k_len = v_len = int(n_emb // n_head)
        for k, v in (("n_layer", n_layer), ("n_emb", n_emb),
                     ("n_head", n_head), ("n_head_kv", n_hkv),
                     ("k_len", k_len), ("v_len", v_len or k_len),
                     ("n_expert", a("expert_count")),
                     ("n_expert_used", a("expert_used_count")),
                     ("ctx_train", a("context_length"))):
            if v is not None:
                out[k] = int(v)

        # --- разделение весов: эксперты против всего остального ---
        # Флаг --n-cpu-moe уводит в системную память ровно тензоры
        # экспертов. Считаем их точно, по форме и типу каждого тензора.
        exps = rest = 0
        for _ in range(n_tensor):
            name = r.s()
            nd = r.u32()
            dims = [r.u64() for _ in range(nd)]
            t = r.u32()
            r.u64()                                    # смещение данных
            blk, sz = _GGML.get(t, (1, 4))
            n_el = 1
            for d in dims:
                n_el *= d
            b = n_el // blk * sz if blk > 1 else n_el * sz
            if "_exps" in name:
                exps += b
            else:
                rest += b
        out["gb_experts"] = exps / (1 << 30)
        out["gb_rest"] = rest / (1 << 30)
        out["gb_total"] = (exps + rest) / (1 << 30)
    return out


def kv_gb(meta: dict, n_ctx: int, quant: str = "q8_0",
          quant_v: str = "") -> float:
    """Сколько видеопамяти займёт KV-кэш при таком окне.

    Формула не «примерно от размера файла», а по устройству модели:
    на каждый токен каждый слой со вниманием держит K и V размером
    n_head_kv * длина головы. Это то самое число, из-за которого окно в
    120 тысяч у MoE стоит терпимо, а у плотной 27B — неподъёмно.

    K и V считаются РАЗДЕЛЬНО (2026-09-05). llama.cpp квантует их двумя
    независимыми флагами, и это не мелочь: значения (V) переносят грубое
    квантование заметно легче ключей (K). Держать K в q8_0, а V в q4_0 —
    это минус четверть памяти под кэш почти без потери связности на
    длинном контексте, и ровно этой четверти не хватало, чтобы окно 120
    тысяч ужилось на одной карте с клон-голосом."""
    lay = int(meta.get("kv_layers") or meta.get("n_layer") or 0)
    hkv = int(meta.get("n_head_kv") or 0)
    kl = int(meta.get("k_len") or 0)
    vl = int(meta.get("v_len") or kl)
    if not (lay and hkv and kl):
        return 0.0
    bk = KV_BYTES.get(str(quant or "f16").lower(), 2.0)
    bv = KV_BYTES.get(str(quant_v or quant or "f16").lower(), bk)
    per_tok = lay * hkv * (kl * bk + vl * bv)
    return per_tok * n_ctx / (1 << 30)


def describe(meta: dict) -> str:
    """Человеческая строка для лога — чтобы в логе было видно, из каких
    чисел взялось решение, а не только само решение."""
    moe = (f", экспертов {meta['n_expert']} (работает "
           f"{meta.get('n_expert_used', '?')})") if meta.get("n_expert") else ""
    return (f"{meta.get('name', '?')}: {meta.get('arch', '?')}, "
            f"{meta.get('n_layer', '?')} слоёв (KV в "
            f"{meta.get('kv_layers', '?')}), "
            f"{meta.get('n_head_kv', '?')} KV-голов по "
            f"{meta.get('k_len', '?')}{moe}; вес {meta.get('gb_total', 0):.1f} ГБ "
            f"= эксперты {meta.get('gb_experts', 0):.1f} + остальное "
            f"{meta.get('gb_rest', 0):.1f}; родное окно "
            f"{meta.get('ctx_train', '?')}")
