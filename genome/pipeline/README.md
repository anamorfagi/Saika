# Genome Studio · конвейер захвата личности

Корпус → следователь → свод → оформитель → артефакт. Все шаги — код; модель зовётся через один клиент (`llm.py`, каталог `providers.json`).

```
python corpus.py <id> "<Имя>" --wiki en:Kaguya_Shinomiya --wiki "en:Kaguya-sama:_Love_Is_War_season_1" --fandom kaguyasama-wa-kokurasetai:Kaguya_Shinomiya
python investigate.py <id> --provider gigachat --groups 2          # или --emit → prompts/ и потом --ingest answers/
python aggregate.py <id>                                            # genome.json + stats.json
python profile.py <id> --provider gigachat                          # char.json: описание, реплики, маски, голос, трасса
node build_char.js <id>                                             # вставка в gs.html (из папки студии)
```
Ключи: `LLM_KEY` или `secrets.json` Сайки (`llm.cloud_keys.<provider>`). `python llm.py --list` — каталог; `python llm.py --provider mistral` — проверка.
Живой человек: `age_lex.py --year=ГОД файлы.txt` (возраст по речи), `prosody.py` (голос из аудио).
Вшитые субтитры: `python subtitle_ocr.py ролик.mp4 --out transcript.jsonl --plain-out transcript.txt` —
JSONL для проверки и текст `[м:сс]` для `observer.py`; реплики не печатаются в консоль.
Досъёмка одного блока: `investigate.py <id> --only dyn --append` → `aggregate.py <id> --merge-into chars/<id>/genome.json`.
Каждый прогон пишет `run.json` (запросы, токены, секунды, улики на группу) — данные для улучшения промпта.

## Наблюдение (функция 3)
`python observer.py <id> --transcript a.txt b.txt --provider gigachat` — следователь по окнам (180 с / шаг 180 с) → `chars/<id>/timeline.json`; `--follow live.txt` — живой режим по растущему файлу (слух Сайки). Вкладка «Наблюдение» в студии воспроизводит ленту: гены поднимаются из серого, спираль и отпечаток меняются по времени.
Замер на Максиме (62 мин, 21 окно, 474 события): 144 гена, уверенность 0.69; с ручным захватом совпало по знаку 124 из 137 общих генов, средняя |Δ| 0.15.

## Файл персонажа (обмен)
`<id>.genome.json`, формат `saika-genome/1`: карточка + геном с уликами в одном файле. В студии: кнопка «файл персонажа ↓» на карточке (сохранить + в буфер), «загрузить файл» / перетащить на карточку «Новый персонаж». В конвейере: `python export_char.py <id>` и `python export_char.py --import файл.genome.json` → `node build_char.js <id>`. Так люди в чате снимают своих персонажей у себя и скидывают файл — студия подгружает целиком.
