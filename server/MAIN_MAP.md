# Карта `server/main.py`

> Собрано механически: `python tools/make_main_map.py`. Правь код, а не эту страницу.

Всего строк: **9604**, ручек HTTP: **160**, функций верхнего уровня: **212**.

Это проводка, а не логика: HTTP, WebSocket и конвейер ответа. Вся предметная работа живёт в модулях — карта в [MODULES.md](MODULES.md). Файл большой не потому, что так задумано: распил записан в [../PLAN_BUILD.md](../PLAN_BUILD.md).

## Разделы по порядку

| Строка | Раздел |
|---:|---|
| 295 | REST |
| 304 | собственный веб-аватар (three-vrm, 2026-07-25) |
| 502 | LLM |
| 523 | Слух (STT) |
| 533 | Голос (TTS) |
| 618 | текстовый протокол жестов для маленьких моделей (2026-07-25) |
| 1341 | журнал слуха (час записи) |
| 1385 | шумодав |
| 1447 | отпечаток голоса (кто говорит) |
| 2247 | дев-доска (карта разработки) |
| 2291 | голоса |
| 2380 | лорбук |
| 2425 | заметки автора |
| 2451 | сэмплинг LLM |
| 2894 | зрение |
| 3072 | Инженерная вкладка обучения: датасет (локальный + HF) + LoRA-обучение |
| 3257 | REST-чат для нативных клиентов (UE5 и т.п.) |
| 3532 | диалоговый пайплайн |
| 5726 | импульсы (heartbeat) |
| 6285 | ступени тишины (как idle-анимации персонажа в игре) |
| 6357 | окно браузера простаивает -> сама спрашивает/закрывает |
| 6427 | WebSocket |
| 7812 | внимание: когда фраза адресована Сайке |

## Самые большие куски

Эти пять функций — половина файла. Читать их подряд не надо: ниже оглавление по внутренним заголовкам.

### `ws_endpoint()` — строки 6429–8863 (2434)

- 6490 — ГЛУБИНА ОЧЕРЕДИ СЛУХА
- 6506 — ОЧЕРЕДЬ ГОТОВЫХ ФРАЗ
- 6530 — ЕСЛИ НЕ УСПЕВАЕМ — ЖЕРТВУЕМ АНАЛИЗОМ
- 6574 — КОРОТКИЙ ПУТЬ ДЛЯ СИСТЕМНОГО ЗВУКА
- 6581 — УШИ СЛУШАЮТ И КОМПЬЮТЕР (2026-08-16)
- 6627 — СВОЁ ЭХО НЕ ГОНЯЕМ ЧЕРЕЗ ТЯЖЁЛЫЙ КОНВЕЙЕР (2026-08-15)
- 6647 — «СТОЙ» ОБЯЗАНО РАБОТАТЬ И КОГДА ОНА ГОВОРИТ
- 6674 — ПРЕДОХРАНИТЕЛЬ РЕАЛЬНОГО ВРЕМЕНИ
- 6700 — «БУДЬ ЗДОРОВ»
- 6723 — БИТБОКС-ТРАНСКРИБ
- 6733 — КЛАВИАТУРА — НЕ БИТБОКС
- 6790 — ОТПЕЧАТОК — ТОЛЬКО НА НАСТОЯЩЕЙ РЕЧИ (2026-08-15)
- 6904 — СКОЛЬЗЯЩАЯ НОРМАЛИЗАЦИЯ
- 6948 — ЖИВАЯ ПОДСВЕТКА КАЧЕСТВА
- 6986 — ДОЛЯ ОЗВОНЧЕННОГО (2026-08-16)
- 7083 — ПРОТУХШИЙ КУСОК НЕ РОЖДАЕТ ФРАЗУ
- 7099 — ОПОЗДАТЬ И НАПИСАТЬ ЛУЧШЕ
- 7128 — НАЗЫВАЕМ ВИНОВНИКА ВСЛУХ
- 7162 — ВТОРОЙ ПРОХОД ШУМОДАВА — НА СОБРАННОЙ ФРАЗЕ (2026-08-15)
- 7180 — СМЕНА ГОЛОСА ВНУТРИ ФРАЗЫ (2026-08-15)
- 7211 — ДВЕ ДОРОЖКИ ИЗ ОДНОГО МИКРОФОНА (2026-08-16)
- 7236 — МАСТЕРИНГ ФРАЗЫ ПЕРЕД ДВИЖКОМ (2026-08-16)
- 7256 — АНАЛИЗ — ПО ВЫРОВНЕННОМУ ЗВУКУ ТОЖЕ
- 7292 — МЕТКИ ГОЛОСА
- 7307 — ДЛЯ РАЗВОДА ПО ЛЮДЯМ — ECAPA
- 7360 — СКЛЕЙКА ОБОРВАННОЙ МЫСЛИ (2026-08-16)
- 7378 — СКЛЕЙКА — ПО КАНАЛАМ
- 7391 — ДВА ГОЛОСА ЗА «МЫСЛЬ КОНЧИЛАСЬ»
- 7408 — ФАНТОМ НА КЛАВИАТУРЕ
- 7428 — УДАР — ТА ЖЕ УЛИКА
- 7487 — ЛОГИКА ПРАВИЛЬНОГО НАПИСАНИЯ (2026-08-15)
- 7493 — РАСТЯЖКА
- 7616 — МОДЕЛЬ ВЫКЛЮЧЕНА (2026-07-28)
- 7657 — ОТПРАВЛЯТЬ ИЛИ НЕТ — ПЕРЕД ВСЕМ ОСТАЛЬНЫМ (2026-08-20)
- 7666 — ОТКАЗ СИЛЬНЕЕ СОГЛАСИЯ
- 7694 — МОЛЧА И ВИДНО
- 7741 — ПРИДЕРЖКА ПЕРЕБИВОК
- 7995 — ШИРОКАЯ ПОЛОСА — НЕ УЛИКА
- 8040 — ТОН БЕЗ ТЕМБРА НОВЫХ ИМЁН НЕ РАЗДАЁТ
- 8058 — ГРУППЫ ПО ТОНУ: КОГДА КАРТА ГОЛОСОВ ЕЩЁ НИКОГО НЕ ЗНАЕТ
- 8106 — ПОРОГ ЗАВИСИТ ОТ ТОГО
- 8243 — НОВЫЙ ЧЕЛОВЕК ЗАВОДИТСЯ ТОЛЬКО С ХОРОШЕГО КУСКА
- 8290 — СЛИЯНИЕ СБЛИЗИВШИХСЯ ГРУПП
- 8383 — «СТОП» ВЫШЕ ВСЕГО ОСТАЛЬНОГО
- 8407 — МЕТКА ГОВОРЯЩЕГО (2026-07-28)
- 8430 — КОРМИМ СКЕЛЕТ ГОЛОСА (2026-08-16)
- 8456 — ПОД МУЗЫКУ ТИХИЙ КУСОК — ПОЧТИ ВСЕГДА ВЫДУМКА
- 8483 — СТЕНОГРАММА
- 8509 — ЭХО ИЗ КОЛОНОК
- 8528 — ОТВЕЧАЮ ТОЛЬКО ВЛАДЕЛЬЦУ
- 8550 — ТИХАЯ ЗАЩИТА — НЕ ЗАЩИТА (2026-08-14)
- 8567 — ЛИДЕР СРАВНЕНИЯ
- 8612 — ТИХИЙ РЕЖИМ
- 8624 — СОЦИАЛЬНЫЙ ТАКТ
- 8633 — СЧИТАЕМ ФРАЗЫ
- 8674 — СЛУХ ЖИВЁТ В СВОЁМ ПОТОКЕ
- 8712 — ЧТО ИМЕННО НЕ УСПЕВАЕТ — В ТОЙ ЖЕ СТРОКЕ
- 8773 — КОРОТКИЕ КУСКИ ДЛЯ НЕПРЕРЫВНОЙ РЕЧИ (2026-07-28)
- 8785 — ЧИСЛА ВЫНЕСЕНЫ В КОНФИГ (2026-08-16)

### `run_dialog()` — строки 3604–5723 (2119)

Блокирующий пайплайн в отдельном потоке: LLM stream -> TTS stream.

- 3655 — В РАЗГОВОРЕ МОЗГИ НЕ МЕНЯЮТСЯ (2026-08-15)
- 3671 — ЛЕСТНИЦА МОЗГОВ
- 3701 — РУКИ — ТОЛЬКО ТОМУ
- 3753 — ЧТО ИЗ ЭТОГО ВЫШЛО — В ЧАТ
- 3764 — АГЕНТНЫЙ ЦИКЛ
- 3821 — ОТКЛИК ВЛАДЕЛЬЦА (2026-07-26)
- 3834 — МЕТКА ТОНА
- 3855 — РЕАКЦИЯ АВАТАРА
- 3863 — БЫСТРЫЙ РЕЖИМ
- 3879 — КТО ПЕРЕД ТОБОЙ
- 3902 — ГДЕ Я СЕЙЧАС
- 3920 — ЧТО Я УМЕЮ И ЧЬИМИ РУКАМИ
- 3932 — ГДЕ МЫ СЕЙЧАС СТОИМ В ПАПКАХ И ЧТО ПОКАЗАНО СПИСКОМ (2026-08-14)
- 3945 — ЧТО НА СТОЛЕ
- 3957 — РАБОЧЕЕ МЕСТО
- 3981 — КОСТЮМ (2026-08-13)
- 3991 — РЕГЛАМЕНТ РУК
- 4005 — ОТПРАВКА — ТОЛЬКО ПО ПОДТВЕРЖДЕНИЮ
- 4029 — ЧТО СЛЫШНО ВОКРУГ
- 4095 — СВОДКА ПРО СВОИ ЖЕ МОЗГИ (2026-07-26)
- 4117 — КТО ЭТО УМЕЕТ (2026-08-15)
- 4128 — ЯКОРЬ ДЛЯ КОРОТКОЙ РЕПЛИКИ (2026-08-15)
- 4144 — ЧТО В РУКАХ ПРЯМО СЕЙЧАС
- 4226 — СЛЕПАЯ МОДЕЛЬ — НЕ ПОВОД ПЕРЕСПРАШИВАТЬ
- 4378 — «НАЙДИ» ПРО ДИСК — НЕ ПОВОД ЛЕЗТЬ В ИНТЕРНЕТ (2026-08-14)
- 4573 — ЯКОРЬ ИСТОРИИ
- 4597 — ОКНО БЕРЁМ У ТОГО
- 4640 — ПОТОЛОК ПО МОДЕЛИ
- 4652 — ОКНО МЕРЯЕМ У ТОЙ МОДЕЛИ
- 4694 — СЧИТАЕМ ТО
- 4704 — ПАСПОРТНЫЙ ПОТОЛОК — НЕ ДЛЯ СВОЕГО ДВИЖКА (2026-07-28)
- 4720 — ОКНО МЕНЬШЕ
- 4735 — СОВЕТ ПРО LM STUDIO ОБЛАЧНОЙ МОДЕЛИ — ЭТО МУСОР
- 4753 — И В ИНТЕРФЕЙС
- 4870 — СВОЙ ГОЛОС В ПРОСТРАНСТВО ГОЛОСОВ (2026-07-28)
- 4897 — РОД — МЕХАНИЧЕСКИ
- 4907 — РОД ПРАВИМ И В ЧАТЕ
- 4926 — ПРИДЕРЖАННОЕ ТОЖЕ НАДО ПОКАЗАТЬ (2026-08-15)
- 4977 — ЖИВОЙ СТАТУС ПРИ ДОЛГОМ МОЛЧАНИИ (2026-07-23)
- 5235 — ЛЮБОЙ ИНСТРУМЕНТ
- 5389 — ХВОСТ ПОКАЗЫВАЕМ
- 5455 — СКОЛЬКО ПРОМПТА ВЗЯЛОСЬ ИЗ КЭША
- 5523 — ТРИ ПОПЫТКИ (2026-07-26)
- 5538 — ДОСЬЕ МОДЕЛИ (2026-07-26)
- 5630 — «СКАЗАЛА "ПОНЯЛА"
- 5670 — ДЕЛО СДЕЛАНО — МОЛЧАНИЕ НЕ СТРАШНО

### `_autostart_components()` — строки 8900–9256 (356)

Автопуск слуха/голоса/мозгов при старте (2026-07-20). Каждый компонент

- 8917 — ПОДКЛЮЧИТЬ ВСЁ
- 8931 — БРАУЗЕР ЧЕЛОВЕКА — САМИ
- 8999 — СТРАЖ ПЕТЛИ КРАШЕЙ — ДО ВСЯКОЙ ЗАГРУЗКИ ГОЛОСА (2026-08-14)
- 9014 — РЕВИЗИЯ СВЯЗНОСТИ (2026-08-15)
- 9097 — ПОРЯДОК ЗАПУСКА
- 9146 — ОБЛАКО ТОЖЕ УЧАСТВУЕТ (2026-08-14)
- 9191 — ОБЛАЧНАЯ ПЕРВОЙ — И ЭТО МГНОВЕННО
- 9248 — ЗАСЕЧКА ЗДОРОВОГО ЗАПУСКА (2026-08-14)

### `main()` — строки 9259–9599 (340)

- 9372 — ЗАЩИТА ЖЕЛЕЗА
- 9381 — БЕСХОЗНЫЙ ДВИЖОК ПРИ ТЕСНОЙ ПАМЯТИ ВЫГРУЖАЕМ САМИ
- 9407 — СНАЧАЛА ЛИШНЕЕ
- 9518 — СКОЛЬКО ЖДАТЬ — РЕШАЕТ ПАМЯТЬ О ВКЛАДКЕ (2026-08-15)

### `_tail_args()` — строки 5866–5978 (112)

Хвост после имени инструмента -> аргументы (2026-08-18).

- 5909 — ЧУЖИЕ ИМЕНА КЛЮЧЕЙ

## Ручки HTTP и WebSocket

| Строка | Метод | Путь |
|---:|---|---|
| 296 | GET | `/` |
| 2796 | GET | `/api/attention` |
| 2741 | POST | `/api/attention/glow` |
| 2771 | POST | `/api/attention/highlight` |
| 3459 | GET | `/api/attention_toggle` |
| 3450 | GET | `/api/audio_level` |
| 2595 | GET | `/api/avatar/current` |
| 2555 | POST | `/api/avatar/delete` |
| 1917 | GET | `/api/avatar/desk` |
| 1926 | POST | `/api/avatar/desk` |
| 2561 | POST | `/api/avatar/folder` |
| 2540 | GET | `/api/avatar/library` |
| 2547 | POST | `/api/avatar/select` |
| 1887 | POST | `/api/avatar/selfie` |
| 2567 | POST | `/api/avatar/settings` |
| 2578 | POST | `/api/avatar/upload` |
| 495 | GET | `/api/baymax` |
| 1994 | GET | `/api/brains` |
| 1986 | POST | `/api/brains/connect` |
| 1977 | GET | `/api/brains/providers` |
| 1934 | GET | `/api/cards` |
| 1948 | POST | `/api/cards/make` |
| 1941 | POST | `/api/cards/wear` |
| 3479 | POST | `/api/chat` |
| 3467 | POST | `/api/chat_text` |
| 2242 | GET | `/api/config` |
| 2271 | POST | `/api/control` |
| 1684 | GET | `/api/cortex` |
| 1417 | GET | `/api/denoise` |
| 1437 | POST | `/api/denoise/relearn` |
| 1424 | POST | `/api/denoise/set` |
| 2248 | GET | `/api/devboard` |
| 2253 | POST | `/api/devboard/add` |
| 2266 | POST | `/api/devboard/delete` |
| 2259 | POST | `/api/devboard/update` |
| 2983 | POST | `/api/dialog/clear` |
| 2439 | POST | `/api/dialog/drop_last` |
| 2002 | GET | `/api/doctor/model` |
| 2009 | POST | `/api/doctor/model` |
| 3018 | POST | `/api/dreampc/ensure` |
| 3032 | GET | `/api/dreampc/install_status` |
| 3060 | POST | `/api/dreampc/model` |
| 3055 | GET | `/api/dreampc/models` |
| 3037 | GET | `/api/dreampc/status` |
| 1345 | GET | `/api/earlog` |
| 1368 | POST | `/api/earlog/adopt` |
| 1361 | POST | `/api/earlog/report` |
| 1350 | POST | `/api/earlog/start` |
| 1356 | POST | `/api/earlog/stop` |
| 3007 | POST | `/api/git/pull` |
| 2992 | GET | `/api/git/status` |
| 2997 | POST | `/api/git/sync` |
| 1515 | GET | `/api/guard` |
| 1532 | GET | `/api/hear` |
| 1692 | GET | `/api/hear/bench` |
| 1732 | GET | `/api/hear/neuro_vad` |
| 1712 | GET | `/api/hear/segment_denoise` |
| 1746 | GET | `/api/hear/vad` |
| 1249 | GET | `/api/llm/cloud` |
| 1260 | POST | `/api/llm/cloud` |
| 2282 | GET | `/api/llm/free` |
| 1215 | POST | `/api/llm/model` |
| 1206 | POST | `/api/llm/off` |
| 2483 | GET | `/api/llm/sampling` |
| 2870 | POST | `/api/llm/sampling` |
| 2842 | GET | `/api/llm/speed` |
| 2853 | POST | `/api/llm/speed` |
| 2381 | GET | `/api/lore` |
| 2395 | POST | `/api/lore/delete` |
| 2387 | POST | `/api/lore/save` |
| 3249 | POST | `/api/memory/compress` |
| 1654 | GET | `/api/mic` |
| 1663 | POST | `/api/mic/device` |
| 445 | GET | `/api/models` |
| 2508 | GET | `/api/models/dossier` |
| 2517 | POST | `/api/models/dossier` |
| 553 | GET | `/api/net` |
| 2426 | GET | `/api/notes` |
| 2431 | POST | `/api/notes` |
| 2040 | POST | `/api/panic_unload` |
| 2672 | GET | `/api/pc` |
| 2696 | POST | `/api/pc/refresh` |
| 2706 | POST | `/api/pc/set` |
| 2810 | GET | `/api/pc/windows` |
| 2623 | GET | `/api/phone` |
| 2629 | POST | `/api/phone` |
| 2651 | GET | `/api/phone/qr` |
| 2402 | GET | `/api/prompt/order` |
| 2409 | POST | `/api/prompt/order` |
| 2490 | GET | `/api/psyche` |
| 2496 | POST | `/api/psyche` |
| 480 | POST | `/api/ratings/manual` |
| 1558 | GET | `/api/ready` |
| 1522 | GET | `/api/room` |
| 2150 | POST | `/api/select` |
| 1670 | GET | `/api/soundmap` |
| 417 | GET | `/api/status` |
| 1322 | POST | `/api/stt/model` |
| 1116 | GET | `/api/system` |
| 3169 | GET | `/api/training/base_models` |
| 3089 | POST | `/api/training/dataset/expand` |
| 3099 | GET | `/api/training/dataset/expand_status` |
| 3104 | POST | `/api/training/dataset/expand_stop` |
| 3135 | POST | `/api/training/dataset/hf_import` |
| 3121 | POST | `/api/training/dataset/hf_preview` |
| 3109 | POST | `/api/training/dataset/hf_search` |
| 3149 | POST | `/api/training/dataset/merge` |
| 3084 | POST | `/api/training/dataset/open_folder` |
| 3079 | GET | `/api/training/dataset/summary` |
| 3174 | POST | `/api/training/ensure` |
| 3234 | POST | `/api/training/export_gguf` |
| 3183 | GET | `/api/training/install_status` |
| 3188 | POST | `/api/training/start` |
| 3220 | GET | `/api/training/status` |
| 3227 | POST | `/api/training/stop` |
| 1389 | GET | `/api/transcript` |
| 1394 | POST | `/api/transcript/start` |
| 1399 | POST | `/api/transcript/stop` |
| 2130 | POST | `/api/tts/model` |
| 2357 | POST | `/api/tts/preview` |
| 2306 | POST | `/api/tts/voice` |
| 2341 | POST | `/api/tts/voice/delete` |
| 2322 | POST | `/api/tts/voice/download` |
| 2292 | GET | `/api/tts/voices` |
| 1909 | GET | `/api/usage` |
| 2965 | GET | `/api/vision/mjpeg` |
| 2905 | POST | `/api/vision/set` |
| 2940 | POST | `/api/vision/shot` |
| 2895 | GET | `/api/vision/state` |
| 2956 | POST | `/api/vision/test_cameras` |
| 1955 | GET | `/api/voice/shape` |
| 1963 | POST | `/api/voice/shape` |
| 1451 | GET | `/api/voiceprint` |
| 1870 | POST | `/api/voiceprint/clear_map` |
| 1789 | POST | `/api/voiceprint/color` |
| 1476 | POST | `/api/voiceprint/enroll` |
| 1815 | POST | `/api/voiceprint/enroll_file` |
| 1837 | POST | `/api/voiceprint/enroll_path` |
| 1865 | POST | `/api/voiceprint/forget` |
| 1858 | POST | `/api/voiceprint/merge` |
| 1491 | POST | `/api/voiceprint/passport` |
| 1456 | GET | `/api/voiceprint/points` |
| 1876 | POST | `/api/voiceprint/refit` |
| 1507 | POST | `/api/voiceprint/rename` |
| 1796 | POST | `/api/voiceprint/seal` |
| 1465 | POST | `/api/voiceprint/set` |
| 1852 | POST | `/api/voiceprint/undo` |
| 1804 | POST | `/api/voiceprint/unseal` |
| 305 | GET | `/avatar` |
| 352 | GET | `/avatar/anims` |
| 362 | GET | `/avatar/anims/{fname}` |
| 330 | GET | `/avatar/model.vrm` |
| 386 | GET | `/avatar/outfits` |
| 395 | GET | `/avatar/outfits/{fname}` |
| 2607 | GET | `/avatar/sprite` |
| 405 | GET | `/baymax/{fname}` |
| 1375 | GET | `/earlog/{fname}` |
| 1408 | GET | `/transcript/{fname}` |
| 311 | GET | `/vendor/{fname}` |
| 6428 | WEBSOCKET | `/ws` |

## Классы

- **`_ServerSpeaker`** (строки 3263–3426) — Играет PCM (int16 mono) через колонки ЭТОГО ПК — для клиентов без
