# Карта `server/main.py`

> Собрано механически: `python tools/make_main_map.py`. Правь код, а не эту страницу.

Всего строк: **9461**, ручек HTTP: **160**, функций верхнего уровня: **212**.

Это проводка, а не логика: HTTP, WebSocket и конвейер ответа. Вся предметная работа живёт в модулях — карта в [MODULES.md](MODULES.md). Файл большой не потому, что так задумано: распил записан в [../PLAN_BUILD.md](../PLAN_BUILD.md).

## Разделы по порядку

| Строка | Раздел |
|---:|---|
| 294 | REST |
| 303 | собственный веб-аватар (three-vrm, 2026-07-25) |
| 501 | LLM |
| 522 | Слух (STT) |
| 532 | Голос (TTS) |
| 617 | текстовый протокол жестов для маленьких моделей (2026-07-25) |
| 1340 | журнал слуха (час записи) |
| 1384 | шумодав |
| 1446 | отпечаток голоса (кто говорит) |
| 2239 | дев-доска (карта разработки) |
| 2283 | голоса |
| 2372 | лорбук |
| 2417 | заметки автора |
| 2443 | сэмплинг LLM |
| 2886 | зрение |
| 3064 | Инженерная вкладка обучения: датасет (локальный + HF) + LoRA-обучение |
| 3249 | REST-чат для нативных клиентов (UE5 и т.п.) |
| 3524 | диалоговый пайплайн |
| 5694 | импульсы (heartbeat) |
| 6237 | ступени тишины (как idle-анимации персонажа в игре) |
| 6309 | окно браузера простаивает -> сама спрашивает/закрывает |
| 6379 | WebSocket |
| 7680 | внимание: когда фраза адресована Сайке |

## Самые большие куски

Эти пять функций — половина файла. Читать их подряд не надо: ниже оглавление по внутренним заголовкам.

### `ws_endpoint()` — строки 6381–8724 (2343)

- 6442 — ГЛУБИНА ОЧЕРЕДИ СЛУХА
- 6458 — ОЧЕРЕДЬ ГОТОВЫХ ФРАЗ
- 6496 — КОРОТКИЙ ПУТЬ ДЛЯ СИСТЕМНОГО ЗВУКА
- 6503 — УШИ СЛУШАЮТ И КОМПЬЮТЕР (2026-08-16)
- 6548 — СВОЁ ЭХО НЕ ГОНЯЕМ ЧЕРЕЗ ТЯЖЁЛЫЙ КОНВЕЙЕР (2026-08-15)
- 6568 — «СТОЙ» ОБЯЗАНО РАБОТАТЬ И КОГДА ОНА ГОВОРИТ
- 6592 — ПРЕДОХРАНИТЕЛЬ РЕАЛЬНОГО ВРЕМЕНИ
- 6617 — «БУДЬ ЗДОРОВ»
- 6640 — БИТБОКС-ТРАНСКРИБ
- 6648 — КЛАВИАТУРА — НЕ БИТБОКС
- 6703 — ОТПЕЧАТОК — ТОЛЬКО НА НАСТОЯЩЕЙ РЕЧИ (2026-08-15)
- 6817 — СКОЛЬЗЯЩАЯ НОРМАЛИЗАЦИЯ
- 6861 — ЖИВАЯ ПОДСВЕТКА КАЧЕСТВА
- 6899 — ДОЛЯ ОЗВОНЧЕННОГО (2026-08-16)
- 6996 — ПРОТУХШИЙ КУСОК НЕ РОЖДАЕТ ФРАЗУ
- 7012 — ОПОЗДАТЬ И НАПИСАТЬ ЛУЧШЕ
- 7041 — НАЗЫВАЕМ ВИНОВНИКА ВСЛУХ
- 7075 — ВТОРОЙ ПРОХОД ШУМОДАВА — НА СОБРАННОЙ ФРАЗЕ (2026-08-15)
- 7093 — СМЕНА ГОЛОСА ВНУТРИ ФРАЗЫ (2026-08-15)
- 7124 — ДВЕ ДОРОЖКИ ИЗ ОДНОГО МИКРОФОНА (2026-08-16)
- 7149 — МАСТЕРИНГ ФРАЗЫ ПЕРЕД ДВИЖКОМ (2026-08-16)
- 7169 — АНАЛИЗ — ПО ВЫРОВНЕННОМУ ЗВУКУ ТОЖЕ
- 7205 — МЕТКИ ГОЛОСА
- 7220 — ДЛЯ РАЗВОДА ПО ЛЮДЯМ — ECAPA
- 7273 — СКЛЕЙКА ОБОРВАННОЙ МЫСЛИ (2026-08-16)
- 7291 — СКЛЕЙКА — ПО КАНАЛАМ
- 7304 — ДВА ГОЛОСА ЗА «МЫСЛЬ КОНЧИЛАСЬ»
- 7321 — ФАНТОМ НА КЛАВИАТУРЕ
- 7341 — УДАР — ТА ЖЕ УЛИКА
- 7400 — ЛОГИКА ПРАВИЛЬНОГО НАПИСАНИЯ (2026-08-15)
- 7406 — РАСТЯЖКА
- 7529 — МОДЕЛЬ ВЫКЛЮЧЕНА (2026-07-28)
- 7562 — МОЛЧА И ВИДНО
- 7609 — ПРИДЕРЖКА ПЕРЕБИВОК
- 7863 — ШИРОКАЯ ПОЛОСА — НЕ УЛИКА
- 7908 — ТОН БЕЗ ТЕМБРА НОВЫХ ИМЁН НЕ РАЗДАЁТ
- 7926 — ГРУППЫ ПО ТОНУ: КОГДА КАРТА ГОЛОСОВ ЕЩЁ НИКОГО НЕ ЗНАЕТ
- 7974 — ПОРОГ ЗАВИСИТ ОТ ТОГО
- 8111 — НОВЫЙ ЧЕЛОВЕК ЗАВОДИТСЯ ТОЛЬКО С ХОРОШЕГО КУСКА
- 8158 — СЛИЯНИЕ СБЛИЗИВШИХСЯ ГРУПП
- 8251 — «СТОП» ВЫШЕ ВСЕГО ОСТАЛЬНОГО
- 8275 — МЕТКА ГОВОРЯЩЕГО (2026-07-28)
- 8298 — КОРМИМ СКЕЛЕТ ГОЛОСА (2026-08-16)
- 8324 — ПОД МУЗЫКУ ТИХИЙ КУСОК — ПОЧТИ ВСЕГДА ВЫДУМКА
- 8351 — СТЕНОГРАММА
- 8377 — ЭХО ИЗ КОЛОНОК
- 8396 — ОТВЕЧАЮ ТОЛЬКО ВЛАДЕЛЬЦУ
- 8418 — ТИХАЯ ЗАЩИТА — НЕ ЗАЩИТА (2026-08-14)
- 8435 — ЛИДЕР СРАВНЕНИЯ
- 8480 — ТИХИЙ РЕЖИМ
- 8492 — СОЦИАЛЬНЫЙ ТАКТ
- 8501 — СЧИТАЕМ ФРАЗЫ
- 8542 — СЛУХ ЖИВЁТ В СВОЁМ ПОТОКЕ
- 8634 — КОРОТКИЕ КУСКИ ДЛЯ НЕПРЕРЫВНОЙ РЕЧИ (2026-07-28)
- 8646 — ЧИСЛА ВЫНЕСЕНЫ В КОНФИГ (2026-08-16)

### `run_dialog()` — строки 3596–5691 (2095)

Блокирующий пайплайн в отдельном потоке: LLM stream -> TTS stream.

- 3647 — В РАЗГОВОРЕ МОЗГИ НЕ МЕНЯЮТСЯ (2026-08-15)
- 3663 — ЛЕСТНИЦА МОЗГОВ
- 3693 — РУКИ — ТОЛЬКО ТОМУ
- 3745 — ЧТО ИЗ ЭТОГО ВЫШЛО — В ЧАТ
- 3756 — АГЕНТНЫЙ ЦИКЛ
- 3813 — ОТКЛИК ВЛАДЕЛЬЦА (2026-07-26)
- 3826 — МЕТКА ТОНА
- 3847 — РЕАКЦИЯ АВАТАРА
- 3855 — БЫСТРЫЙ РЕЖИМ
- 3871 — КТО ПЕРЕД ТОБОЙ
- 3894 — ГДЕ Я СЕЙЧАС
- 3912 — ЧТО Я УМЕЮ И ЧЬИМИ РУКАМИ
- 3924 — ГДЕ МЫ СЕЙЧАС СТОИМ В ПАПКАХ И ЧТО ПОКАЗАНО СПИСКОМ (2026-08-14)
- 3937 — ЧТО НА СТОЛЕ
- 3949 — РАБОЧЕЕ МЕСТО
- 3973 — КОСТЮМ (2026-08-13)
- 3983 — РЕГЛАМЕНТ РУК
- 3997 — ЧТО СЛЫШНО ВОКРУГ
- 4063 — СВОДКА ПРО СВОИ ЖЕ МОЗГИ (2026-07-26)
- 4085 — КТО ЭТО УМЕЕТ (2026-08-15)
- 4096 — ЯКОРЬ ДЛЯ КОРОТКОЙ РЕПЛИКИ (2026-08-15)
- 4112 — ЧТО В РУКАХ ПРЯМО СЕЙЧАС
- 4194 — СЛЕПАЯ МОДЕЛЬ — НЕ ПОВОД ПЕРЕСПРАШИВАТЬ
- 4346 — «НАЙДИ» ПРО ДИСК — НЕ ПОВОД ЛЕЗТЬ В ИНТЕРНЕТ (2026-08-14)
- 4541 — ЯКОРЬ ИСТОРИИ
- 4565 — ОКНО БЕРЁМ У ТОГО
- 4608 — ПОТОЛОК ПО МОДЕЛИ
- 4620 — ОКНО МЕРЯЕМ У ТОЙ МОДЕЛИ
- 4662 — СЧИТАЕМ ТО
- 4672 — ПАСПОРТНЫЙ ПОТОЛОК — НЕ ДЛЯ СВОЕГО ДВИЖКА (2026-07-28)
- 4688 — ОКНО МЕНЬШЕ
- 4703 — СОВЕТ ПРО LM STUDIO ОБЛАЧНОЙ МОДЕЛИ — ЭТО МУСОР
- 4721 — И В ИНТЕРФЕЙС
- 4838 — СВОЙ ГОЛОС В ПРОСТРАНСТВО ГОЛОСОВ (2026-07-28)
- 4865 — РОД — МЕХАНИЧЕСКИ
- 4875 — РОД ПРАВИМ И В ЧАТЕ
- 4894 — ПРИДЕРЖАННОЕ ТОЖЕ НАДО ПОКАЗАТЬ (2026-08-15)
- 4945 — ЖИВОЙ СТАТУС ПРИ ДОЛГОМ МОЛЧАНИИ (2026-07-23)
- 5203 — ЛЮБОЙ ИНСТРУМЕНТ
- 5357 — ХВОСТ ПОКАЗЫВАЕМ
- 5423 — СКОЛЬКО ПРОМПТА ВЗЯЛОСЬ ИЗ КЭША
- 5491 — ТРИ ПОПЫТКИ (2026-07-26)
- 5506 — ДОСЬЕ МОДЕЛИ (2026-07-26)
- 5598 — «СКАЗАЛА "ПОНЯЛА"
- 5638 — ДЕЛО СДЕЛАНО — МОЛЧАНИЕ НЕ СТРАШНО

### `_autostart_components()` — строки 8761–9117 (356)

Автопуск слуха/голоса/мозгов при старте (2026-07-20). Каждый компонент

- 8778 — ПОДКЛЮЧИТЬ ВСЁ
- 8792 — БРАУЗЕР ЧЕЛОВЕКА — САМИ
- 8860 — СТРАЖ ПЕТЛИ КРАШЕЙ — ДО ВСЯКОЙ ЗАГРУЗКИ ГОЛОСА (2026-08-14)
- 8875 — РЕВИЗИЯ СВЯЗНОСТИ (2026-08-15)
- 8958 — ПОРЯДОК ЗАПУСКА
- 9007 — ОБЛАКО ТОЖЕ УЧАСТВУЕТ (2026-08-14)
- 9052 — ОБЛАЧНАЯ ПЕРВОЙ — И ЭТО МГНОВЕННО
- 9109 — ЗАСЕЧКА ЗДОРОВОГО ЗАПУСКА (2026-08-14)

### `main()` — строки 9120–9456 (336)

- 9233 — ЗАЩИТА ЖЕЛЕЗА
- 9242 — БЕСХОЗНЫЙ ДВИЖОК ПРИ ТЕСНОЙ ПАМЯТИ ВЫГРУЖАЕМ САМИ
- 9268 — СНАЧАЛА ЛИШНЕЕ
- 9375 — СКОЛЬКО ЖДАТЬ — РЕШАЕТ ПАМЯТЬ О ВКЛАДКЕ (2026-08-15)

### `_tail_args()` — строки 5834–5946 (112)

Хвост после имени инструмента -> аргументы (2026-08-18).

- 5877 — ЧУЖИЕ ИМЕНА КЛЮЧЕЙ

## Ручки HTTP и WebSocket

| Строка | Метод | Путь |
|---:|---|---|
| 295 | GET | `/` |
| 2788 | GET | `/api/attention` |
| 2733 | POST | `/api/attention/glow` |
| 2763 | POST | `/api/attention/highlight` |
| 3451 | GET | `/api/attention_toggle` |
| 3442 | GET | `/api/audio_level` |
| 2587 | GET | `/api/avatar/current` |
| 2547 | POST | `/api/avatar/delete` |
| 1916 | GET | `/api/avatar/desk` |
| 1925 | POST | `/api/avatar/desk` |
| 2553 | POST | `/api/avatar/folder` |
| 2532 | GET | `/api/avatar/library` |
| 2539 | POST | `/api/avatar/select` |
| 1886 | POST | `/api/avatar/selfie` |
| 2559 | POST | `/api/avatar/settings` |
| 2570 | POST | `/api/avatar/upload` |
| 494 | GET | `/api/baymax` |
| 1993 | GET | `/api/brains` |
| 1985 | POST | `/api/brains/connect` |
| 1976 | GET | `/api/brains/providers` |
| 1933 | GET | `/api/cards` |
| 1947 | POST | `/api/cards/make` |
| 1940 | POST | `/api/cards/wear` |
| 3471 | POST | `/api/chat` |
| 3459 | POST | `/api/chat_text` |
| 2234 | GET | `/api/config` |
| 2263 | POST | `/api/control` |
| 1683 | GET | `/api/cortex` |
| 1416 | GET | `/api/denoise` |
| 1436 | POST | `/api/denoise/relearn` |
| 1423 | POST | `/api/denoise/set` |
| 2240 | GET | `/api/devboard` |
| 2245 | POST | `/api/devboard/add` |
| 2258 | POST | `/api/devboard/delete` |
| 2251 | POST | `/api/devboard/update` |
| 2975 | POST | `/api/dialog/clear` |
| 2431 | POST | `/api/dialog/drop_last` |
| 2001 | GET | `/api/doctor/model` |
| 2008 | POST | `/api/doctor/model` |
| 3010 | POST | `/api/dreampc/ensure` |
| 3024 | GET | `/api/dreampc/install_status` |
| 3052 | POST | `/api/dreampc/model` |
| 3047 | GET | `/api/dreampc/models` |
| 3029 | GET | `/api/dreampc/status` |
| 1344 | GET | `/api/earlog` |
| 1367 | POST | `/api/earlog/adopt` |
| 1360 | POST | `/api/earlog/report` |
| 1349 | POST | `/api/earlog/start` |
| 1355 | POST | `/api/earlog/stop` |
| 2999 | POST | `/api/git/pull` |
| 2984 | GET | `/api/git/status` |
| 2989 | POST | `/api/git/sync` |
| 1514 | GET | `/api/guard` |
| 1531 | GET | `/api/hear` |
| 1691 | GET | `/api/hear/bench` |
| 1731 | GET | `/api/hear/neuro_vad` |
| 1711 | GET | `/api/hear/segment_denoise` |
| 1745 | GET | `/api/hear/vad` |
| 1248 | GET | `/api/llm/cloud` |
| 1259 | POST | `/api/llm/cloud` |
| 2274 | GET | `/api/llm/free` |
| 1214 | POST | `/api/llm/model` |
| 1205 | POST | `/api/llm/off` |
| 2475 | GET | `/api/llm/sampling` |
| 2862 | POST | `/api/llm/sampling` |
| 2834 | GET | `/api/llm/speed` |
| 2845 | POST | `/api/llm/speed` |
| 2373 | GET | `/api/lore` |
| 2387 | POST | `/api/lore/delete` |
| 2379 | POST | `/api/lore/save` |
| 3241 | POST | `/api/memory/compress` |
| 1653 | GET | `/api/mic` |
| 1662 | POST | `/api/mic/device` |
| 444 | GET | `/api/models` |
| 2500 | GET | `/api/models/dossier` |
| 2509 | POST | `/api/models/dossier` |
| 552 | GET | `/api/net` |
| 2418 | GET | `/api/notes` |
| 2423 | POST | `/api/notes` |
| 2039 | POST | `/api/panic_unload` |
| 2664 | GET | `/api/pc` |
| 2688 | POST | `/api/pc/refresh` |
| 2698 | POST | `/api/pc/set` |
| 2802 | GET | `/api/pc/windows` |
| 2615 | GET | `/api/phone` |
| 2621 | POST | `/api/phone` |
| 2643 | GET | `/api/phone/qr` |
| 2394 | GET | `/api/prompt/order` |
| 2401 | POST | `/api/prompt/order` |
| 2482 | GET | `/api/psyche` |
| 2488 | POST | `/api/psyche` |
| 479 | POST | `/api/ratings/manual` |
| 1557 | GET | `/api/ready` |
| 1521 | GET | `/api/room` |
| 2142 | POST | `/api/select` |
| 1669 | GET | `/api/soundmap` |
| 416 | GET | `/api/status` |
| 1321 | POST | `/api/stt/model` |
| 1115 | GET | `/api/system` |
| 3161 | GET | `/api/training/base_models` |
| 3081 | POST | `/api/training/dataset/expand` |
| 3091 | GET | `/api/training/dataset/expand_status` |
| 3096 | POST | `/api/training/dataset/expand_stop` |
| 3127 | POST | `/api/training/dataset/hf_import` |
| 3113 | POST | `/api/training/dataset/hf_preview` |
| 3101 | POST | `/api/training/dataset/hf_search` |
| 3141 | POST | `/api/training/dataset/merge` |
| 3076 | POST | `/api/training/dataset/open_folder` |
| 3071 | GET | `/api/training/dataset/summary` |
| 3166 | POST | `/api/training/ensure` |
| 3226 | POST | `/api/training/export_gguf` |
| 3175 | GET | `/api/training/install_status` |
| 3180 | POST | `/api/training/start` |
| 3212 | GET | `/api/training/status` |
| 3219 | POST | `/api/training/stop` |
| 1388 | GET | `/api/transcript` |
| 1393 | POST | `/api/transcript/start` |
| 1398 | POST | `/api/transcript/stop` |
| 2122 | POST | `/api/tts/model` |
| 2349 | POST | `/api/tts/preview` |
| 2298 | POST | `/api/tts/voice` |
| 2333 | POST | `/api/tts/voice/delete` |
| 2314 | POST | `/api/tts/voice/download` |
| 2284 | GET | `/api/tts/voices` |
| 1908 | GET | `/api/usage` |
| 2957 | GET | `/api/vision/mjpeg` |
| 2897 | POST | `/api/vision/set` |
| 2932 | POST | `/api/vision/shot` |
| 2887 | GET | `/api/vision/state` |
| 2948 | POST | `/api/vision/test_cameras` |
| 1954 | GET | `/api/voice/shape` |
| 1962 | POST | `/api/voice/shape` |
| 1450 | GET | `/api/voiceprint` |
| 1869 | POST | `/api/voiceprint/clear_map` |
| 1788 | POST | `/api/voiceprint/color` |
| 1475 | POST | `/api/voiceprint/enroll` |
| 1814 | POST | `/api/voiceprint/enroll_file` |
| 1836 | POST | `/api/voiceprint/enroll_path` |
| 1864 | POST | `/api/voiceprint/forget` |
| 1857 | POST | `/api/voiceprint/merge` |
| 1490 | POST | `/api/voiceprint/passport` |
| 1455 | GET | `/api/voiceprint/points` |
| 1875 | POST | `/api/voiceprint/refit` |
| 1506 | POST | `/api/voiceprint/rename` |
| 1795 | POST | `/api/voiceprint/seal` |
| 1464 | POST | `/api/voiceprint/set` |
| 1851 | POST | `/api/voiceprint/undo` |
| 1803 | POST | `/api/voiceprint/unseal` |
| 304 | GET | `/avatar` |
| 351 | GET | `/avatar/anims` |
| 361 | GET | `/avatar/anims/{fname}` |
| 329 | GET | `/avatar/model.vrm` |
| 385 | GET | `/avatar/outfits` |
| 394 | GET | `/avatar/outfits/{fname}` |
| 2599 | GET | `/avatar/sprite` |
| 404 | GET | `/baymax/{fname}` |
| 1374 | GET | `/earlog/{fname}` |
| 1407 | GET | `/transcript/{fname}` |
| 310 | GET | `/vendor/{fname}` |
| 6380 | WEBSOCKET | `/ws` |

## Классы

- **`_ServerSpeaker`** (строки 3255–3418) — Играет PCM (int16 mono) через колонки ЭТОГО ПК — для клиентов без
