"""Каталог облачных моделей с бесплатным тиром (2026-07-26).

ЗАЧЕМ. Чтобы человек мог включить Сайку и поговорить с ней, не привязывая
карту и не поднимая локальную модель на 8 гигабайт. Локальный путь остаётся
главным, но первое впечатление не должно требовать RTX.

⚠️ ГЛАВНОЕ, ЧТО ИЗМЕНИЛОСЬ. В конфиге у нас дефолтом стоял OpenRouter, но
**с 27.06.2026 он прекратил доступ для пользователей из РФ и Беларуси**
(письма аккаунтам; платежи для российского региона отключены с 11.05.2026).
Официального анонса нет, источники вторичные, но согласованные. Gemini
free tier для РФ закрыт ОФИЦИАЛЬНО — России и Беларуси нет в списке
доступных регионов, отсюда ошибка «free tier is not available in your
country». Поэтому дефолт сменён, а у обоих стоит честная пометка: человек
должен увидеть причину заранее, а не решить, что приложение сломано.

Данные проверены по официальным страницам провайдеров там, где это было
возможно (см. поле `source`). Лимиты меняются — при сомнении смотреть
ссылку, а не верить этому файлу.
"""
import logging

log = logging.getLogger("saika.free")

# ru: доступность из России без ухищрений
#   "ok"    — работает как есть
#   "vpn"   — нужен VPN
#   "block" — не работает даже с VPN (гео-проверка аккаунта/платежей)
# card: нужна ли банковская карта при регистрации
CATALOG = [
    {
        "id": "gigachat",
        "name": "GigaChat (Сбер)",
        "base_url": "https://gigachat.devices.sberbank.ru/api/v1",
        "models": ["GigaChat-2", "GigaChat-2-Pro", "GigaChat"],
        "free": "365 млн токенов на 12 месяцев (Lite 250M + Pro 40M + "
                "Max 25M + Ultra 50M), генерация в один поток",
        "ru": "ok",
        "card": False,
        "lang": "родной русский — лучший в списке",
        "note": "Без VPN, без карты, без зарубежного телефона. Ключ — не "
                "статический: нужен Authorization key из личного кабинета, "
                "Сайка сама меняет его на access-токен и обновляет каждые "
                "30 минут.",
        "key_url": "https://developers.sber.ru/studio/workspaces",
        "key_hint": "Кабинет → GigaChat API → «Получить Authorization key» "
                    "(длинная строка base64, НЕ Client Secret отдельно)",
        "auth": "gigachat",
        "source": "https://developers.sber.ru/docs/ru/gigachat/tariffs/"
                  "individual-tariffs",
    },
    {
        "id": "groq",
        "name": "Groq",
        "base_url": "https://api.groq.com/openai/v1",
        "models": ["qwen/qwen3.6-27b", "minimaxai/minimax-m2.7",
                   "openai/gpt-oss-120b", "openai/gpt-oss-20b",
                   "llama-3.3-70b-versatile", "llama-3.1-8b-instant"],
        "free": "30 запросов/мин, 1000/день (у llama-3.1-8b-instant — "
                "14 400/день; qwen3.6-27b — 131К контекста, "
                "minimax-m2.7 — 196К)",
        "ru": "vpn",
        "card": False,
        "lang": "qwen3.6-27b говорит по-русски прилично",
        "note": "Самая низкая задержка на рынке — для ГОЛОСОВОГО режима это "
                "важнее качества текста. Бонусом Whisper-STT в том же "
                "бесплатном тире (whisper-large-v3 и turbo, 2000 "
                "запросов/день), то есть весь голосовой конвейер на одном "
                "ключе. Отдельно про характер: здесь крутятся ОТКРЫТЫЕ веса "
                "(Qwen, Llama, GPT-OSS, MiniMax) без надстроенной поверх "
                "цензуры провайдера — для ролевых карточек и живой речи "
                "это заметно свободнее закрытых моделей. Границы всё равно "
                "остаются: у самих весов есть выравнивание, и оно никуда "
                "не девается.",
        "key_url": "https://console.groq.com/keys",
        "source": "https://console.groq.com/docs/rate-limits",
    },
    {
        # ВЕСЬ СТЕК НА ОДНОМ ВЕНДОРЕ (2026-08-13, идея владельца: «прикольно
        # будет содрать стек чисто на Квене, у них вроде все блоки есть»).
        # И правда все: qwen3 — мозги, qwen3-vl — зрение, qwen3.5-omni —
        # речь в обе стороны, Qwen3-TTS у нас УЖЕ основной голосовой движок,
        # плюс ASR и эмбеддинги. Сравнить «однородный стек» против
        # «сборной солянки» — ровно тот эксперимент, ради которого платформа
        # и строится.
        "id": "qwen",
        "name": "Qwen (Alibaba Model Studio)",
        "base_url": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
        "models": ["qwen3-max", "qwen3-plus", "qwq-plus", "qwen3-vl-plus",
                   "qwen3-coder-plus"],
        "free": "бесплатная квота на модель, лимиты зависят от региона; "
                "⚠️ карту требуют ДО выдачи бесплатного уровня",
        "ru": "vpn",
        "card": True,
        "lang": "русский приличный; qwen3-vl умеет смотреть на картинки",
        "note": "Единственный, у кого есть ВСЕ блоки одним ключом: мозги "
                "(qwen3-max/plus), зрение (qwen3-vl-plus), код "
                "(qwen3-coder-plus), рассуждение (qwq-plus). Голос Сайки "
                "и так Qwen3-TTS — то есть стек можно собрать целиком на "
                "одном вендоре. НО (проверено владельцем на живой "
                "регистрации 2026-08-13, вторичные источники врали): "
                "Alibaba Cloud выдаёт бесплатный уровень ТОЛЬКО ТРЕТЬИМ "
                "шагом, после привязки карты — Visa/MC/JCB/Amex/PayPal/"
                "RuPay/UPI. Российская карта там не пройдёт. Хочешь Qwen "
                "без карты — бери его у чужих хостеров: Cloudflare "
                "(@cf/qwen/qwen3-30b-a3b-fp8, без VPN и без карты) или "
                "Groq (qwen/qwen3.6-27b, нужен VPN, карты нет). "
                "Международный адрес dashscope-intl; для Китая — "
                "dashscope.aliyuncs.com.",
        "key_url": "https://modelstudio.console.alibabacloud.com/",
        "key_hint": "Model Studio → API-KEY → создать ключ (sk-…)",
        "source": "https://www.alibabacloud.com/help/en/model-studio/"
                  "compatibility-of-openai-with-dashscope",
    },
    {
        "id": "mistral",
        "name": "Mistral AI",
        "base_url": "https://api.mistral.ai/v1",
        "models": ["mistral-medium-3-5", "mistral-small-2603"],
        "free": "1 запрос/сек, 500 тыс. токенов/мин, 1 МЛРД токенов/месяц",
        "ru": "ok",
        "card": False,
        "lang": "русский приличный, не идеальный",
        "note": "Самый щедрый лимит — миллиард токенов в месяц выбрать "
                "невозможно. По отзывам открывается из РФ без VPN. НО: нужна "
                "верификация по телефону И согласие на использование твоих "
                "данных для обучения — для личных разговоров с компаньоном "
                "это стоит взвесить.",
        "key_url": "https://console.mistral.ai/api-keys",
        "source": "https://help.mistral.ai/en/articles/"
                  "225174-what-are-the-limits-of-the-free-tier",
    },
    {
        "id": "github",
        "name": "GitHub Models",
        "base_url": "https://models.github.ai/inference",
        "models": ["openai/gpt-4.1-mini", "openai/gpt-4.1"],
        "free": "15 запросов/мин, 150/день (сильные модели — 10/мин, 50/день), "
                "8000 входных токенов на запрос",
        "ru": "ok",
        "card": False,
        "lang": "хороший русский",
        "note": "Проще всех, если есть GitHub: токен выдаётся за полминуты в "
                "настройках аккаунта. Нужен PAT со scope «models». Лимит "
                "8000 входных токенов коротким репликам не мешает.",
        "key_url": "https://github.com/settings/personal-access-tokens/new",
        "key_hint": "Fine-grained token → Permissions → Models: Read",
        "source": "https://docs.github.com/en/github-models/use-github-models/"
                  "prototyping-with-ai-models",
    },
    {
        "id": "cerebras",
        "name": "Cerebras",
        "base_url": "https://api.cerebras.ai/v1",
        "models": ["zai-glm-4.7", "gpt-oss-120b", "gemma-4-31b"],
        "free": "5 запросов/мин, 1 млн токенов/день",
        "ru": "vpn",
        "card": False,
        "lang": "zai-glm-4.7 — лучший русский из их набора",
        "note": "Очень быстрая генерация, но 5 запросов в минуту для живого "
                "диалога маловато — годится как резерв, не как основной.",
        "key_url": "https://cloud.cerebras.ai/",
        "source": "https://inference-docs.cerebras.ai/support/rate-limits",
    },
    {
        "id": "gemini",
        "name": "Google Gemini",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "models": ["gemini-3.6-flash", "gemini-3.5-flash",
                   "gemini-2.5-flash"],
        "free": "бесплатный тир есть, точные лимиты Google перестал "
                "публиковать (было ~10 запросов/мин, 250/день у 2.5 Flash)",
        "ru": "block",
        "card": False,
        "lang": "лучший русский из всех",
        "note": "⚠️ России и Беларуси НЕТ в официальном списке регионов — "
                "бесплатный тир отдаёт «free tier is not available in your "
                "country». Нужен VPN И не-российский регион аккаунта Google. "
                "Качество лучшее в списке, но новичок без этого решит, что "
                "сломалось приложение.",
        "key_url": "https://aistudio.google.com/apikey",
        "source": "https://ai.google.dev/gemini-api/docs/available-regions",
    },
    {
        "id": "openrouter",
        "name": "OpenRouter",
        "base_url": "https://openrouter.ai/api/v1",
        "models": ["deepseek/deepseek-v4-flash:free",
                   "google/gemma-4-31b-it:free",
                   "nvidia/nemotron-3-super-120b-a12b:free"],
        "free": "20 запросов/мин, 50/день (1000/день после пополнения на $10)",
        "ru": "block",
        "card": False,
        "lang": "зависит от выбранной модели",
        "note": "⚠️ С 27.06.2026 прекратил доступ для пользователей из РФ и "
                "Беларуси — блокировка по гео аккаунта, VPN не помогает. "
                "Раньше был лучшим вариантом «один ключ, много моделей», "
                "поэтому и стоял у нас дефолтом. Оставлен для тех, кто вне РФ.",
        "key_url": "https://openrouter.ai/keys",
        "source": "https://openrouter.ai/docs/api-reference/limits",
    },
    {
        "id": "cloudflare",
        "name": "Cloudflare Workers AI",
        # адрес личный — в нём сидит account_id. Держим шаблон, а не пустоту:
        # autoconnect подставит llm.cloudflare_account сам (2026-08-13),
        # раньше человеку пришлось бы дописывать адрес руками.
        "base_url": "https://api.cloudflare.com/client/v4/accounts/"
                    "ВАШ_ID/ai/v1",
        # @cf/zhipu/glm-4.7-flash отсюда УБРАН (2026-08-13): Cloudflare
        # отвечает 400 «No such model» — модели с таким именем у них нет.
        # Оба оставшихся проверены живым разговором.
        "models": ["@cf/qwen/qwen3-30b-a3b-fp8",
                   "@cf/meta/llama-3.3-70b-instruct-fp8-fast"],
        "free": "10 000 Neurons/день — примерно 150 ответов",
        "ru": "ok",
        "card": False,
        "lang": "glm-4.7-flash заявляет 100+ языков",
        "note": "Единственный из бесплатных, кто открывается из РФ без VPN "
                "и без карты. Адрес личный (в нём account_id из адресной "
                "строки кабинета) — система подставляет его сама, если он "
                "записан в llm.cloudflare_account. Токену хватает права "
                "«Workers AI: Read», фильтр по IP включать НЕ надо: "
                "домашний адрес меняется, и токен молча умрёт. 150 ответов "
                "в день мало для постоянного разговора, но как резерв и "
                "как способ пощупать Qwen без карты — работает.",
        "key_url": "https://dash.cloudflare.com/profile/api-tokens",
        "source": "https://developers.cloudflare.com/workers-ai/platform/pricing/",
    },
]

# Что показать первым: без VPN, без карты, и лимит достаточен для разговора.
RECOMMENDED = ["gigachat", "groq", "mistral", "github", "cloudflare", "qwen"]


def catalog() -> list:
    """Список для UI: рекомендованные впереди, дальше остальные."""
    order = {pid: i for i, pid in enumerate(RECOMMENDED)}
    return sorted(CATALOG, key=lambda p: (order.get(p["id"], 99), p["name"]))


def get(pid: str) -> dict:
    for p in CATALOG:
        if p["id"] == pid:
            return p
    return {}
