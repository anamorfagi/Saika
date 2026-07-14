# Шпаргалка известных проблем Сайки

Читают: человек и ИИ-доктор (setup/ai_doctor.py подмешивает файл в контекст
локальной LLM). Формат: симптом -> причина -> лечение. Пополняется по мере
находок.

## Импорт/пакеты

- **«No module named X.Y.Z», хотя `pip install` говорит "already satisfied"**
  -> у пакета-владельца модуля пропали файлы (битый диск, недокопированный
  robocopy). Обычный pip install НЕ чинит. Лечение: переустановить
  дистрибутивы-владельцы верхнего модуля X с `--force-reinstall --no-deps`
  (доктор делает сам через `_pip_fix`), либо прогнать
  `python setup/repair_venv.py --deep` — проверит весь venv.

- **«No module named qwen_tts / gigaam», папка third_party/ на месте**
  -> editable-установка помнит старый абсолютный путь (сменилась буква диска
  или папка переехала). Лечение: `pip install -e third_party/<пакет> --no-deps`
  (доктор делает сам).

- **WinError 1392 «файл или папка повреждены» при чтении любых файлов**
  -> повреждена файловая система диска. Лечение: `chkdsk X: /f` от
  администратора, затем `setup/repair_venv.py --deep`. Если повторяется —
  диск умирает, срочно копировать проект на здоровый.

- **WinError 1114 «сбой инициализации DLL» на torch\lib\*.dll**
  -> битые файлы torch (после сбоя диска) ИЛИ конфликт CUDA-DLL. Лечение:
  `pip install --force-reinstall --no-deps torch torchaudio
  --index-url https://download.pytorch.org/whl/cu130`.

## CUDA / GPU

- **«Library cublas64_12.dll is not found» у faster-whisper**
  -> CTranslate2 собран под CUDA 12, torch cu130 несёт только 13-е DLL.
  Лечение: `pip install nvidia-cublas-cu12` (шаг cuda_dlls установщика);
  server/config.py подключает только cublas и nvrtc.

- **CUDNN_STATUS_SUBLIBRARY_VERSION_MISMATCH при синтезе TTS**
  -> в поиск DLL попали два разных cuDNN (torch\lib и nvidia-cudnn-cu12).
  Лечение: НЕ добавлять nvidia/cudnn/bin в PATH/add_dll_directory — уже
  учтено в server/config.py. Не «чинить» установкой nvidia-cudnn-cu12 заново.

- **CUDA недоступна на новом ПК** -> нет NVIDIA GPU или драйвера. Всё
  работает на CPU, просто медленно. Пакетами не лечится.

## Сеть / HuggingFace

- **getaddrinfo failed / NameResolutionError на huggingface.co**
  -> DNS/блокировка. Лечение уже в server/config.py: авто-зеркало
  hf-mirror.com или офлайн-режим. Не крутить ретраи, не переустанавливать
  пакеты. Если модель уже в кэше models/hf — она грузится локально.

- **ConnectionReset 10054 на cas-server.xethub.hf.co, скачивание висит на 0%**
  -> Xet-бэкенд HF заблокирован провайдером. Лечение: HF_HUB_DISABLE_XET=1
  (уже стоит в конфиге/скриптах).

- **silero/edge TTS падают с сетевыми ошибками** -> им нужен интернет
  (github/bing). Это запасные голоса; основной qwen3 работает офлайн.
  Пакетами не лечится — только note.

## Перенос на другой ПК/диск

- **«No Python at C:\Users\<старый юзер>\...\python.exe»**
  -> venv помнит путь к Python старого ПК в pyvenv.cfg. Лечение:
  `python setup/fix_venv.py` системным Python 3.12 (start.bat делает сам).

- **Отказано в доступе при записи конфига/логов**
  -> проект лежит в C:\Program Files* — туда запись только админом.
  Лечение: перенести папку в обычное место (C:\AI\Saika).

## Ложные тревоги (НЕ чинить)

- **«flash-attn is not installed»** — необязательное ускорение, TTS работает
  на sdpa. Игнорировать.
- **«SoX could not be found»** — бинарник sox не нужен, конвертирует ffmpeg.
  Игнорировать.
- **«[fail] LM Studio: не отвечает»** — просто не запущен, это второй
  необязательный LLM-бэкенд. Игнорировать, если Ollama работает.
- **INFO talker_config is None…** — обычный шум загрузки qwen_tts.

## TTS

- **«Either voice_clone_prompt or ref_audio must be provided»**
  -> гонка двойной загрузки Qwen3 (исправлена замком в tts/manager.py).
  Если появилась вновь — не переустанавливать пакеты, смотреть код load().
- **«Нет референса голоса»** -> нет wav по пути tts.voice_ref_wav
  (по умолчанию voice/ref.wav) или пустой tts.voice_ref_text в config.json.
  Лечение: шаг voice в setup/first_run.py.

## Разное

- **Первый ответ после старта ~40 с без голоса** — разовая компиляция
  Qwen3-TTS (прогрев). Норма.
- **Медленная смена LLM-модели** — Ollama грузит модель в VRAM. Норма.
- **Voxtral требует transformers>=5.2, Qwen3-TTS пинит 4.57.3** — конфликт
  решён отдельным окружением .venv_voxtral (setup/install_voxtral.py);
  не ставить transformers 5.x в основной venv.
