"""ЗАМЕР ЗАДЕРЖКИ ДО ПЕРВОГО ТОКЕНА (2026-07-27).

Зачем. В LM Studio модель отвечает за ~0.3с, у Сайки та же модель — за 2.7-9с.
Догадками это не лечится: в задержке смешаны три разные вещи —
  1) РАЗМЫШЛЕНИЯ модели (gemma-4 думает по умолчанию; в логе это видно как
     completion_tokens_details.reasoning_tokens = 243..546 — при 60 ток/с это
     4-9 секунд ДО первого видимого токена, то есть почти вся задержка);
  2) PREFILL промпта (~6.5к токенов) — сколько из него реально пережёвывается
     заново, а сколько берётся из KV-кэша;
  3) наши накладные (память, лорбук, сборка промпта) — они в логе уже видны и
     стоят копейки (0.1-0.5с).
Скрипт разделяет 1 и 2 и показывает, какой способ выключить размышления
РЕАЛЬНО работает на этой сборке LM Studio (документация врёт: часть полей
OpenAI-слой LM Studio молча выбрасывает).

Как запускать (LM Studio должна быть запущена, модель загружена):
    .venv\\Scripts\\python tools\\latency_bench.py
    .venv\\Scripts\\python tools\\latency_bench.py --model google/gemma-4-e4b
    .venv\\Scripts\\python tools\\latency_bench.py --repeat 3

Что читать в выводе: колонка ДУМАЛА (reasoning-токены) и ПЕРВЫЙ ТОКЕН.
Строка, где ДУМАЛА=0 и первый токен < 1с, — это и есть рабочий рецепт.
"""

import argparse
import json
import sys
import time

try:
    import requests
except ImportError:                                    # pragma: no cover
    print("нужен requests: .venv\\Scripts\\pip install requests")
    sys.exit(1)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DEFAULT_URL = "http://127.0.0.1:1234"

# Наполнитель истории: осмысленный русский текст того же характера, что и
# реальный диалог, — токенизируется так же плотно, как настоящий контекст.
FILLER = [
    ("user", "Слушай, а что там по вчерашней задаче с аватаром?"),
    ("assistant", "Руки поправила: калибровка теперь меряет отведение плеча, "
                  "а не прижатость к телу. На нашей модели углы вышли ровно "
                  "авторские, поза не поехала."),
    ("user", "Хорошо. А по звуку что?"),
    ("assistant", "Qwen3 греется дольше, поэтому на старте включается edge как "
                  "времянка, потом подменяется. Пайпер держит 0.07x реального "
                  "времени, этого хватает с запасом."),
    ("user", "Понял. Напомни, где логи лежат."),
    ("assistant", "logs/saika.log, там же тайминги ответа по этапам: очередь, "
                  "память, лор, зрение, промпт и prefill."),
]


def build_messages(target_chars: int) -> list:
    """История примерно нужного размера + системный промпт."""
    system = ("Ты Сайка — локальный голосовой компаньон. Отвечай коротко, "
              "живо и по делу, без канцелярита и без списков, если не просят. "
              "Ты умеешь искать в интернете, работать с файлами и управлять "
              "компьютером. Не выдумывай результаты инструментов. ") * 12
    msgs = [{"role": "system", "content": system}]
    used = len(system)
    i = 0
    while used < target_chars:
        role, text = FILLER[i % len(FILLER)]
        msgs.append({"role": role, "content": text})
        used += len(text)
        i += 1
    if msgs[-1]["role"] != "user":
        msgs.append({"role": "user", "content": "И ещё вопрос был."})
        msgs.append({"role": "assistant", "content": "Слушаю."})
    msgs.append({"role": "user", "content": "ты тут?"})
    return msgs


def run(url: str, model: str, messages: list, extra: dict, timeout=180):
    """Один замер: время до первого ВИДИМОГО токена + usage."""
    payload = {
        "model": model,
        "messages": messages,
        "stream": True,
        "temperature": 0.8,
        "stream_options": {"include_usage": True},
    }
    payload.update(extra)
    t0 = time.monotonic()
    t_first = None
    t_first_any = None          # включая reasoning-токены, если их стримят
    vis_tokens = 0
    usage = {}
    err = None
    try:
        r = requests.post(url + "/v1/chat/completions", json=payload,
                          stream=True, timeout=(10, timeout))
        if not r.ok:
            return {"err": f"HTTP {r.status_code}: {r.text[:200]}"}
        for line in r.iter_lines(decode_unicode=True):
            if not line or not line.startswith("data: "):
                continue
            body = line[6:]
            if body.strip() == "[DONE]":
                break
            try:
                chunk = json.loads(body)
            except Exception:
                continue
            if chunk.get("usage"):
                usage = chunk["usage"]
            for ch in chunk.get("choices") or []:
                d = ch.get("delta") or {}
                if (d.get("reasoning") or d.get("reasoning_content")) \
                        and t_first_any is None:
                    t_first_any = time.monotonic()
                tok = d.get("content")
                if tok:
                    if t_first_any is None:
                        t_first_any = time.monotonic()
                    if t_first is None:
                        t_first = time.monotonic()
                    vis_tokens += 1
            # ответ короткий, но на всякий случай не ждём вечно
            if vis_tokens > 400:
                break
        r.close()
    except Exception as e:
        err = str(e)[:200]
    det = (usage.get("completion_tokens_details") or {})
    return {
        "ttft": None if t_first is None else t_first - t0,
        "ttfa": None if t_first_any is None else t_first_any - t0,
        "total": time.monotonic() - t0,
        "prompt_tokens": usage.get("prompt_tokens"),
        "completion_tokens": usage.get("completion_tokens"),
        "reasoning_tokens": det.get("reasoning_tokens"),
        "vis": vis_tokens,
        "err": err,
    }


# СПОСОБЫ ВЫКЛЮЧИТЬ РАЗМЫШЛЕНИЯ. Ни один не гарантирован: llama.cpp понимает
# chat_template_kwargs, LM Studio с 0.3.29 — reasoning.effort, а её
# OpenAI-совместимый слой часть полей молча выбрасывает. Поэтому меряем все.
# 2026-07-27, ПО ИТОГАМ ПЕРВОГО ПРОГОНА. Способов было восемь, сработал
# ровно один: ПЛОСКОЕ поле reasoning_effort. Вложенное reasoning.effort из
# changelog LM Studio (0.3.29) и chat_template_kwargs из llama.cpp она молча
# выбрасывает — оставлены в списке как контроль, чтобы после обновления
# LM Studio было видно, если поведение изменится.
VARIANTS = [
    ("reasoning_effort=none (рабочий)", {"reasoning_effort": "none"}),
    ("ничего не просим (базовый)", {}),
    ("chat_template_kwargs (не работает)",
     {"chat_template_kwargs": {"enable_thinking": False}}),
    ("reasoning.effort=none (не работает)", {"reasoning": {"effort": "none"}}),
]

# Досыл «мысль уже закончена» последним сообщением ассистента: шаблон
# продолжает НАЧАТЫЙ ход, и фаза размышления оказывается закрытой ещё до
# первого сгенерированного токена. Работает даже там, где поля игнорируются.
PREFILLS = [
    ("префилл <think></think>", "<think>\n\n</think>"),
    ("префилл gemma-канал", "<|channel>thought<channel|>"),
]


def fmt(v, suffix="с"):
    return "  —  " if v is None else f"{v:5.2f}{suffix}"


def probe(url: str):
    """Кто живёт по адресу и с каким окном. Возвращает (модель, окно)."""
    model, ctx = None, 0
    try:
        r = requests.get(url + "/v1/models", timeout=5)
        model = (r.json().get("data") or [{}])[0].get("id")
    except Exception:
        return None, 0
    try:                                   # LM Studio
        r = requests.get(url + "/api/v0/models", timeout=4)
        for m in r.json().get("data", []):
            if m.get("id") == model:
                ctx = int(m.get("loaded_context_length")
                          or m.get("context_length")
                          or m.get("max_context_length") or 0)
    except Exception:
        pass
    if not ctx:
        try:                               # llama-server
            r = requests.get(url + "/props", timeout=4)
            g = (r.json() or {}).get("default_generation_settings") or {}
            ctx = int(g.get("n_ctx") or 0)
        except Exception:
            pass
    return model, ctx


def compare(urls: list, chars: int, repeat: int):
    """ЛОБ В ЛОБ: один и тот же промпт по двум движкам подряд.

    Смысл ровно один — увидеть, даёт ли свой llama-server ту же скорость,
    что чужой LM Studio в своём окне, на НАШЕМ промпте (а не на пустом чате,
    где быстро у всех). Меряем то, что чувствует человек: время до первого
    слова при ТЁПЛОМ кэше, то есть на второй одинаковой реплике.
    """
    msgs = build_messages(chars)
    p_chars = sum(len(m["content"]) for m in msgs)
    print(f"промпт: {p_chars} симв в {len(msgs)} сообщ.")
    print("ВАЖНО: замеряй при ОСТАНОВЛЕННОЙ Сайке. Qwen3-TTS и GigaAM висят "
          "в той же VRAM,\nи с ними движку остаётся не вся карта — числа "
          "будут не про движок, а про тесноту.\n")
    # ДВА РАЗНЫХ ВРЕМЕНИ, которые легко перепутать (2026-07-27):
    #   «1-й токен»  — первый чанк ВООБЩЕ, включая токены размышлений. Именно
    #                  это число показывает LM Studio в своём чате (её «0.22s»).
    #   «1-е слово»  — первый ВИДИМЫЙ токен ответа. Это то, что чувствует
    #                  человек, и то, что меряет сама Сайка.
    # На думающей модели они расходятся на секунды: в чате LM Studio «0.22s»
    # соседствует с «Thought for 2.66 seconds» — ответа не было почти три
    # секунды, хотя красивая цифра говорит про 0.22.
    head = (f"{'движок':30} {'модель':20} {'окно':>6} {'1-й токен':>10} "
            f"{'1-е слово':>10} {'думала':>7} {'промпт':>7}")
    print(head)
    print("-" * len(head))
    best = []
    for url in urls:
        model, ctx = probe(url)
        if not model:
            print(f"{url:34} — не отвечает")
            continue
        # тот же набор полей, что шлёт сама Сайка
        extra = {"reasoning_effort": "none",
                 "chat_template_kwargs": {"enable_thinking": False},
                 "cache_prompt": True}
        cold = run(url, model, msgs, extra)
        if cold.get("err"):
            print(f"{url:34} ОШИБКА: {cold['err']}")
            continue
        warm = cold
        for _ in range(max(1, repeat - 1)):
            warm = run(url, model, msgs, extra)
        print(f"{url:30} {str(model)[:20]:20} {ctx or '—':>6} "
              f"{fmt(warm['ttfa']):>10} {fmt(warm['ttft']):>10} "
              f"{str(warm['reasoning_tokens'] if warm['reasoning_tokens'] is not None else '—'):>7} "
              f"{str(warm['prompt_tokens'] or '—'):>7}")
        print(f"{'':30} на холодную: {fmt(cold['ttft'])} -> на тёплом кэше: "
              f"{fmt(warm['ttft'])}")
        best.append((url, warm, ctx, p_chars))
    print()
    for url, w, ctx, pc in best:
        if w["prompt_tokens"] and pc / w["prompt_tokens"] > 5:
            print(f"{url}: промпт режется — принято всего "
                  f"{w['prompt_tokens']} токенов на {pc} символов. Окно "
                  f"{ctx or '?'} мало.")
    if len(best) == 2:
        (u1, w1, _, _), (u2, w2, _, _) = best
        if w1["ttft"] and w2["ttft"]:
            fast, slow = sorted([(w1["ttft"], u1), (w2["ttft"], u2)])
            print(f"ИТОГ: {fast[1]} быстрее в {slow[0]/fast[0]:.1f} раза "
                  f"({fast[0]:.2f}с против {slow[0]:.2f}с до первого слова "
                  f"на тёплом кэше).")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=DEFAULT_URL)
    ap.add_argument("--compare", nargs="*", default=None,
                    help="сравнить движки лоб в лоб; без аргументов берёт "
                         "llama-server (8771) и LM Studio (1234)")
    ap.add_argument("--model", default=None,
                    help="по умолчанию — первая загруженная в LM Studio")
    ap.add_argument("--chars", type=int, default=29000,
                    help="размер промпта в символах (у Сайки ~29000)")
    ap.add_argument("--repeat", type=int, default=2,
                    help="сколько раз повторить каждый вариант (2-й прогон "
                         "показывает, работает ли KV-кэш)")
    a = ap.parse_args()

    if a.compare is not None:
        urls = [u.rstrip("/") for u in a.compare] or [
            "http://127.0.0.1:8771", "http://127.0.0.1:1234"]
        return compare(urls, a.chars, a.repeat)

    url = a.url.rstrip("/")
    model = a.model
    if not model:
        try:
            r = requests.get(url + "/v1/models", timeout=5)
            model = (r.json()["data"] or [{}])[0].get("id")
        except Exception as e:
            print(f"LM Studio не отвечает на {url}: {e}")
            return 1
    if not model:
        print("в LM Studio не загружена ни одна модель")
        return 1

    # ОКНО КОНТЕКСТА — первым делом. Если оно меньше промпта, всё остальное
    # в этой таблице не имеет смысла: LM Studio молча режет начало промпта,
    # и KV-кэш не может сработать в принципе (окно сдвигается каждый запрос).
    ctx = 0
    try:
        r = requests.get(url + "/api/v0/models", timeout=5)
        for m in r.json().get("data", []):
            if m.get("id") == model:
                ctx = int(m.get("loaded_context_length")
                          or m.get("context_length")
                          or m.get("max_context_length") or 0)
    except Exception:
        pass

    messages = build_messages(a.chars)
    small = build_messages(400)
    p_chars = sum(len(m["content"]) for m in messages)
    print(f"модель: {model}")
    print(f"окно контекста: {ctx or 'не сказала'} токенов")
    print(f"промпт: {p_chars} симв в {len(messages)} сообщ.\n")

    head = (f"{'вариант':38} {'1-й токен':>9} {'на холодную':>12} "
            f"{'думала':>7} {'промпт':>7}")
    print(head)
    print("-" * len(head))

    rows = []
    cases = [(n, e, messages) for n, e in VARIANTS]
    cases += [(n, {}, messages + [{"role": "assistant", "content": p}])
              for n, p in PREFILLS]
    cases.append(("короткий промпт (пол задержки)", {}, small))

    for name, extra, msgs in cases:
        best, first = None, None
        for k in range(a.repeat):
            res = run(url, model, msgs, extra)
            if res.get("err"):
                print(f"{name:44} ОШИБКА: {res['err']}")
                best = None
                break
            if first is None:
                first = res
            # берём ПОСЛЕДНИЙ прогон: KV-кэш уже тёплый, как в живом диалоге
            best = res
        if best and first is not None and first is not best:
            best["cold_ttft"] = first["ttft"]
        if not best:
            continue
        rows.append((name, best))
        print(f"{name:38} {fmt(best['ttft']):>9} "
              f"{fmt(best.get('cold_ttft')):>12} "
              f"{str(best['reasoning_tokens'] if best['reasoning_tokens'] is not None else '—'):>7} "
              f"{str(best['prompt_tokens'] or '—'):>7}")

    print()
    # ПОДРЕЗКА. Считаем плотность токенов по КОРОТКОМУ промпту (он влезает
    # всегда) и прикидываем, сколько токенов должно было уйти в большом.
    # Если ушло заметно меньше — начало промпта отрезано.
    sm = [b for n, b in rows if n.startswith("короткий")]
    big = [b for n, b in rows if not n.startswith("короткий")
           and b.get("prompt_tokens")]
    if sm and big and sm[0].get("prompt_tokens"):
        dens = sum(len(m["content"]) for m in small) / sm[0]["prompt_tokens"]
        expect = p_chars / dens
        got = max(b["prompt_tokens"] for b in big)
        if got < expect * 0.8:
            print(f"ПРОМПТ РЕЖЕТСЯ: отправили ~{expect:.0f} токенов, "
                  f"модель приняла {got}. Окно {ctx or '?'} мало — LM Studio "
                  f"молча отрезает начало. Сайка при этом теряет системный "
                  f"промпт и память, а KV-кэш не работает вообще.\n"
                  f"Лечение: в LM Studio у модели поднять Context Length до "
                  f"16384-32768 и перезагрузить её.")
    # КЭШ. Второй одинаковый запрос обязан быть заметно быстрее первого: у
    # него совпадает весь промпт. Если время то же — кэш выключен или сорван.
    warm = [(n, b) for n, b in rows if b.get("cold_ttft") and b.get("ttft")]
    if warm:
        n, b = warm[0]
        gain = 1 - b["ttft"] / b["cold_ttft"]
        if gain < 0.3:
            print(f"KV-КЭШ НЕ РАБОТАЕТ: повтор того же запроса занял "
                  f"{b['ttft']:.2f}с против {b['cold_ttft']:.2f}с на холодную "
                  f"(выигрыш {gain*100:.0f}%). Должно быть в разы быстрее.\n"
                  f"Смотреть: окно контекста (см. выше) и в настройках "
                  f"LM Studio — Prompt/KV cache reuse, Flash Attention, "
                  f"полный GPU offload.")
        else:
            print(f"KV-кэш живой: повтор {b['ttft']:.2f}с против "
                  f"{b['cold_ttft']:.2f}с на холодную.")
    print()
    ok = [r for r in rows if (r[1]["reasoning_tokens"] or 0) == 0
          and r[1]["ttft"] is not None]
    if ok:
        ok.sort(key=lambda r: r[1]["ttft"])
        n, b = ok[0]
        print(f"ЛУЧШИЙ РЕЦЕПТ: «{n}» — первый токен за {b['ttft']:.2f}с "
              f"без размышлений.")
    else:
        print("НИ ОДИН способ не выключил размышления через API. "
              "Значит, чинить надо в самой LM Studio: вкладка модели → "
              "Prompt Template → в начало шаблона добавить "
              "{%- set enable_thinking = false %} "
              "(или загрузить модель через lms с --reasoning off).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
