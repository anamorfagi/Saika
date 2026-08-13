# UE5_AVATAR.md — чертёж говорящего аватара в UE 5.8

> Проектный документ для UE5-ветки Сайки. Составлен 2026-08-05 по результатам
> разбора реализации Convai (плагин v3/v4, исходники + документация) и ревизии
> модели Августы в Blender. Convai как продукт мы НЕ используем — берём только
> архитектурные решения, они выстраданы и проверены в проде.
>
> Читать после PHILOSOPHY.md и DEVBOARD.md. Дополняет пункт дев-доски
> «Интерфейс на UE 5.8: полный редизайн + ААА-персонаж».

---

## 0. Что решено и почему

**Convai не подключаем.** Он тащит свою облачную LLM, свой STT и свой TTS —
то есть дублирует всё ядро Сайки и уводит её в облако. Из него берётся только
архитектура лицевой анимации.

**MetaHuman не используем.** У Августы лицо без костей: ни челюсти, ни
face-джойнтов, только один бон `eyes` и 106 шейпкеев. MetaHuman-риг гоняет
251 кривую `CTRL_expressions_*` по своей топологии — состыковать это с
аниме-мешем можно только пересобрав ей голову, что убьёт стиль. Работаем на
её родных морфах.

**Скелет — через Auto-Rig Pro.** ARP 3.78.35 установлен, деформ-набор у неё
штатный ARP-овский (`root.x`, `spine_01..04.x`, `neck.x`, `head.x`,
`shoulder/arm_stretch/forearm_stretch/hand`, пальцы, `thigh_stretch/leg_stretch/
foot/toes_01`). Экспорт родным `Auto-Rig Pro: Export` с пресетом Unreal Engine —
он сам переименует кости в номенклатуру UE-манекена и уложит оси.

---

## 1. Главное архитектурное решение: визеmы считает сервер

Это то, ради чего писался документ.

**Как НЕ надо** (как сейчас в `ui/avatar.html`): движок слушает уровень
играющего звука и открывает рот пропорционально громкости. Это даёт «рыбу» —
рот открывается на любом звуке одинаково, гласные неразличимы.

**Как делает Convai и как надо нам:** сервер, порождая TTS-аудио, ОДНОВРЕМЕННО
порождает покадровую последовательность весов морфов. В движок приходят два
потока — PCM и кадры. В движке нет ни ML-инференса, ни анализа спектра.

```
FaceFrame  = { i: <int frame index>, bs: { "<curve>": <float 0..1>, ... } }
FaceSeq    = { fps: 60, duration: <sec>, frames: [FaceFrame, ...] }
```

Дословно из документации Convai:

> «Convai produces audio and a frame-indexed sequence of blendshape data at the
> same time… The reason data is precomputed rather than inferred at runtime is
> to avoid adding a machine learning inference step.»

### 1.1 Кадр выбирается по времени АУДИОУСТРОЙСТВА, а не по часам

Критично. У Convai:

```cpp
if (AudioPlaybackTimeProvider.IsBound())
    CurrentSequenceTimePassed = AudioPlaybackTimeProvider.Execute();  // позиция звука
else
    CurrentSequenceTimePassed = (FPlatformTime::Seconds() - StartTime) - TotalPausedDuration;
CurrentSequenceTimePassed += LipSyncTimeOffset;
```

С комментарием: *«robust to app freezes because it tracks what the audio device
has actually played»*.

**Это ровно те же грабли, что уже записаны у нас в `CLAUDE.md`:** серверный
`/api/audio_level` опережает воспроизведение на секунды и годится только как
фолбэк для OBS, поэтому липсинк в браузере берёт уровень с реально играющего
звука через `BroadcastChannel('saika-tts-level')`. Вывод совпал независимо —
значит он верный. В UE тянем позицию из аудиокомпонента, не из `GetWorld()->GetTimeSeconds()`.

---

## 2. Протокол: расширение существующего `/ws` (порт 8765)

Новых сокетов не заводим — Сайка уже держит `/ws`, UE-оболочка подключается
туда же (как записано в дев-доске).

### 2.1 Сервер → UE

```jsonc
// начало реплики: кадры лица приходят ВПЕРЁД аудио, пакетами
{ "t": "face_seq",  "id": "utt-4711", "fps": 60, "start_frame": 0,
  "frames": [ {"i":0,"bs":{"aa":0.8,"E":0.1}}, ... ] }

// аудио — как сейчас (или отдельным бинарным каналом)
{ "t": "audio",     "id": "utt-4711", "sr": 24000, "seq": 3, "pcm": "<base64>" }

// эмоция реплики: скаляры 0..1, НЕ морфы
{ "t": "emotion",   "scores": {"joy":0.6,"anger":0.0,"sadness":0.1}, "lock": false }

// жест из текстового маркера [жест:имя] — уже есть в main.py
{ "t": "gesture",   "name": "nod" }

// куда смотреть
{ "t": "lookat",    "target": "player" | "screen" | null }

// конец реплики
{ "t": "utt_end",   "id": "utt-4711" }
```

### 2.2 UE → сервер

```jsonc
{ "t": "mic",       "pcm": "<base64>" }          // если микрофон переезжает в UE
{ "t": "player",    "gaze": "avatar"|"away", "dist": 210.5 }
{ "t": "action_done","name":"nod","ok":true }
```

**Почему кадры вперёд аудио.** Convai держит `FramesBufferDuration = 0.5` сек и
не начинает воспроизведение, пока не накоплено `MinBufferDuration = 0.2` сек
лицевых кадров либо `LipSyncDuration >= AudioDuration * AudioLipSyncRatio`
(`AudioLipSyncRatio = 0.1`). Копируем эту логику: аудио не стартует, пока лицо
не набрало буфер, иначе первые фонемы уедут.

---

## 3. Серверная часть: что добавить в Сайку

Новый модуль **`server/face/`** рядом с `tts/`:

| Файл | Роль |
|---|---|
| `phonemize.py` | текст реплики → фонемы с таймингами |
| `visemes.py` | фонемы → кадры визем `{name: weight}` на 60 fps |
| `emotion_map.py` | метка тона из `tone.py` → скаляры эмоций |

**Откуда брать тайминги фонем.** Три пути по убыванию качества:

1. **Из TTS напрямую.** Многие движки (Piper, XTTS, Silero) умеют отдавать
   алайнмент фонем или хотя бы длительности токенов. Это бесплатно и точно —
   смотреть в первую очередь, что отдаёт наш текущий движок.
2. **Форсед-алайнмент постфактум** по синтезированному wav (`montreal-forced-aligner`,
   `whisperX`). Точно, но добавляет проход по аудио — плюс задержка.
3. **Оценка по тексту** — грубая раскладка по слогам с равномерными длительностями.
   Фолбэк, если первые два не вышли.

**Русский.** Convai работает на английской фонетике. Для русского берём
собственный набор соответствий фонема→визеmа; кириллицу гоняем через
`ru` G2P (`russian_g2p` / словарь + правила), не через транслит.

**Сглаживание на сервере, а не в движке.** Соседние фонемы коартикулируются:
одиночный кадр `PP` между двумя гласными должен не полностью закрывать рот.
Проще сделать это один раз при генерации, чем каждый кадр в AnimGraph.

---

## 4. UE-часть: компоненты и AnimGraph

### 4.1 Структура

| Наш класс | Аналог у Convai | Роль |
|---|---|---|
| `USaikaLinkComponent` | `ConvaiChatbotComponent` | WebSocket на 8765, разбор сообщений, `LookAtTarget`, скоры эмоций |
| `USaikaFaceSyncComponent` | `ConvaiFaceSyncComponent` | кольцевой буфер `FaceSeq`, выбор и интерполяция кадров, `CurrentBlendShapesMap` под локом |
| `USaikaAudioStreamer` | `ConvaiAudioStreamer` | `USynthComponent`, воспроизведение PCM, отдаёт позицию воспроизведения в FaceSync |
| `FAnimNode_SaikaFaceSync` | `FAnimNode_ConvaiFaceSync` | нода AnimGraph, пишет кривые в позу |

Отдельный **UncookedOnly**-модуль под AnimGraph-ноду (у Convai это
`ConvaiAnimGraph` с `PlatformAllowList = Win64`) — иначе не соберётся билд.

### 4.2 Нода AnimGraph — обязательный набор параметров

Скопировать почти дословно, каждый пункт там появился не просто так:

```cpp
FPoseLink SourcePose;
USaikaLinkComponent* LinkComponent;          // пин, с фолбэком на FindComponentByClass
                                             // и на GetAttachParentActor()

// Разделение лица
TArray<FName> UpperFaceBlendshapeNames;      // брови/веки Августы
float UpperFaceAlpha = 0.8f;                 // НЕ 1.0 — оставляем место эмоциям
float LowerFaceAlpha = 1.0f;

// Применение
enum ApplyMode { Add, Override } = Add;      // Add поверх слоя эмоций

// Сглаживание (EMA, кадронезависимое)
bool  bEnableLowerFaceSmoothing = false;
float LowerFaceSmoothingSpeed   = 1.0f;
bool  bEnableUpperFaceSmoothing = false;
float UpperFaceSmoothingSpeed   = 1.0f;
// SmoothFactor = 1 - Pow(1 - Speed, DeltaTime * 60)

// Голодание буфера
float StarvationBlendInDuration  = 0.1f;
float StarvationBlendOutDuration = 0.8f;

// Ремап
TMap<FName, FSaikaBlendshapeParams> BlendshapeMapping;
float GlobalMultiplier = 1.0f;
float GlobalOffset     = 0.0f;
```

`FSaikaBlendshapeParams`: `TArray<FName> TargetNames`, `Multiplier`, `Offset`,
`ClampMin = 0`, `ClampMax = 1`, `bIgnoreGlobalModifiers`, `bUseOverrideValue`,
`OverrideValue`. Правило коллизий — **побеждает максимум**: если две исходные
кривые пишут в одну целевую, берётся большее значение.

**Зачем `UpperFaceAlpha = 0.8`.** Дословно из внутренней документации Convai:
*«keep upper-face lip-sync subtle so emotion-driven brow/eye shapes show through
(headroom for the emotion layer)»*. Верх лица принадлежит эмоциям, низ — речи.

**Зачем starvation-blend.** Если сеть моргнула и кадры кончились — лицо не
должно щёлкнуть в ноль. Альфа уезжает за 0.8 сек. Обратно — за 0.1 сек.
Отдельно у Convai есть `LipSyncStarvationFallback = 5.0` сек: если разрыв
между временем аудио и концом буфера превысил это, лицо принудительно
сбрасывается в ноль.

Запись кривых — **батчем**, не по одной:
```cpp
FBlendedHeapCurve OurCurve;
UE::Anim::FCurveUtils::BuildUnsorted(OurCurve, FinalValues);
ApplyMode == Add ? Output.Curve.Accumulate(OurCurve, 1.0f)
                 : Output.Curve.Combine(OurCurve);
```

Ранний выход при `CurrentStarvationAlpha <= KINDA_SMALL_NUMBER` — молчащий
персонаж должен стоить ноль.

### 4.3 Порядок слоёв в AnimGraph лица

```
[ базовая поза лица ]
        │
        ├─► слой ЭМОЦИЙ           (Override, снизу)
        │
        ├─► слой МОРГАНИЯ         (Add, свой таймер)
        │
        ├─► FAnimNode_SaikaFaceSync (Add, ЛИПСИНК)   ◄── верх лица на 0.8
        │
        └─► слой ВЗГЛЯДА          (Add, Pupil_*)
```

---

## 5. Таблица ремапа: OVR-визеmы → морфы Августы

Набор источника — 15 визем Oculus, тот же, что у Convai в режиме `VisemeBased`:

```
sil, PP, FF, TH, DD, kk, CH, SS, nn, RR, aa, E, ih, oh, ou
```

Целевые морфы **проверены визуально** — каждый выкручен в 1.0 и отрендерен
(рендеры лежат в `_visemes/`, скрипт съёмки — в истории чата 2026-08-05).
Что реально делает каждый морф Августы:

| Морф | Форма |
|---|---|
| `Aa` | рот открыт средне-широко, видны зубы |
| `A` | открыт уже и площе |
| `E` | приоткрыт, растянут вширь |
| `I` | почти закрыт, тонкая широкая щель |
| `O` | округлён, тёмный овал |
| `U` | маленький, собран в трубочку |
| `M_OpenSmall` | еле приоткрыт |
| `M_Laugh` | широко открыт, улыбка с зубами |
| `M_Trapezoid` | трапеция, оба ряда зубов |
| `M_O` | сильно округлён, больше чем `O` |
| `M_Nutcracker` | губы плотно сжаты |
| `M_Smile_L/R` | полуулыбка (раздельно по сторонам) |
| `M_Scared` | открытый овал |
| `M_Anger` | оскал |
| `M_Ennui_L/R` | уголки вниз |

Таблица (значения — стартовые, подкручиваются на слух):

| Виземa | Звуки | Морфы Августы |
|---|---|---|
| `sil` | тишина | все в 0 |
| `PP` | п б м | `M_Nutcracker` 1.0 |
| `FF` | ф в | `M_Nutcracker` 0.40 + `I` 0.35 |
| `TH` | межзубные | `Aa` 0.25 + `I` 0.20 |
| `DD` | д т | `Aa` 0.30 |
| `kk` | к г х | `A` 0.35 |
| `CH` | ч ш щ ж | `U` 0.40 + `O` 0.20 |
| `SS` | с з ц | `I` 0.50 |
| `nn` | н л | `Aa` 0.25 + `I` 0.15 |
| `RR` | р | `U` 0.35 + `O` 0.25 |
| `aa` | а я | `Aa` 1.0 |
| `E` | э е | `E` 1.0 |
| `ih` | и ы | `I` 1.0 |
| `oh` | о ё | `O` 1.0 |
| `ou` | у ю | `U` 1.0 |

Громкая/эмоциональная речь: подмешивать `M_Laugh` к `aa` пропорционально
громкости — даёт разницу между «говорит» и «кричит».

**Верх лица** (`UpperFaceBlendshapeNames`): `B_Anger`, `B_Happy`, `B_Cheerful`,
`B_Sad`, `B_Flat`, `B_AH_R`, `B_AH_L`, `B_Up_Add`, `B_Down_Add`, `E_Close`,
`E_Smile_R`, `E_Smile_L`, `E_Anger`, `E_Sad`, `E_Focus`, `E_Insipid`, `E_Stare`.

---

## 6. Эмоции

Convai шлёт метку + силу 1..3, считает `score = clamp(scale/3 + offset, 0, 1)`
и — важно — **сам морфы не трогает**: *«The plugin does not auto-populate
morphs… read scores with Get Emotion Score and apply them to morph targets»*.
Веса градаций: `LessIntense = 0.25`, `Basic = 0.60`, `MoreIntense = 1.00`.

У нас источник уже есть — `server/tone.py` с метками тона реплики. Отдаём
скаляры, раскладываем в UE:

| Эмоция | Морфы Августы |
|---|---|
| радость | `M_Smile_L/R` + `B_Happy` + `E_Smile_L/R` |
| веселье | `M_Laugh` + `B_Cheerful` |
| злость | `M_Anger` + `B_Anger` + `E_Anger` |
| грусть | `M_Ennui_L/R` + `B_Sad` + `E_Sad` |
| удивление | `M_Scared` + `B_Up_Add` + `E_Stare` |
| скука | `M_Ennui_L/R` + `E_Insipid` |
| сосредоточенность | `E_Focus` + `B_Flat` |

Приём, который стоит украсть: у Convai в графе есть узел **`Emotions Alternator`**
с комментарием *«Alternate neutral with emotion for more life»* — эмоция не
держится константой, а слегка переливается с нейтралью. Это ровно наш принцип
из `CLAUDE.md`: живость даёт дискретность, а не амплитуда.

Флаг `LockEmotionState` — чтобы можно было принудительно зафиксировать
выражение (для сцен и отладки).

---

## 7. Взгляд и внимание

### 7.1 Персонаж смотрит на игрока

У Convai это не отдельный компонент, а **свойство `LookAtTarget` (AActor*) на
чатбот-компоненте**, которое body-AnimBP читает каждый кадр. Флага включения
нет: выставил актора — смотрит, поставил null — перестала.

Реализация у них — 2D BlendSpace-ы (`B2D_MH_HeadLook` по осям `HeadYaw`/`HeadPitch`,
`A2D_MH_EyeLook` по `LookYaw`/`LookPitch`) плюс `LayeredBoneBlend` с
`PerBoneBlendWeights` для распределения голова/шея/глаза. Доворот корпуса —
`FindLookAtRotation` → `RInterpTo` → `SetActorRotation` только по Yaw, с
комментарием в графе: *«Rotate towards player, only if we are talking and that
he is far by 45 degrees»*.

Конкретные числа (скорости интерполяции, пределы BlendSpace, веса по костям)
зашиты в бинарные `.uasset` и наружу не выведены — **единственное извлечённое
число это порог 45°**. Так что берём свои, уже выстраданные, из `avatar.html`:

- горизонталь **±35°**, вертикаль **±18°** — иначе «сова»;
- добавка только аддитивно (у нас это `addAx()`), потому что прямая запись
  копится примерно в 6 раз и однажды выкрутила шею;
- фильтр ~100 мс на повороте.

Распределение: глаза ведут (быстро, без задержки), голова догоняет с
запаздыванием, корпус доворачивается только за порогом 45° и только когда
говорит.

Глаза у Августы кроме бона `eyes` имеют морфы `Pupil_Up/Down/R/L` и
`Pupil_Scale` — можно вести взгляд морфами, как Convai ведёт своими 9
ротационными каналами ARKit (`LeftEyeYaw/Pitch/Roll` и т.д.).

Моргание — `E_Close`, свой таймер, не трогает липсинк.

### 7.2 Игрок смотрит на персонажа

У Convai это `Gaze Attention` на компоненте игрока, **по умолчанию выключено**.
Числа их дефолтов, годятся как старт:

```
GazeAttentionDelay      = 1.0   сек   // сколько смотреть, чтобы засчиталось
GazeAttentionLossDelay  = 5.0   сек   // сколько не смотреть, чтобы сбросилось
GazeMaxDistance         = 5000  см
GazeAngleTolerance      = 5     градусов
```

Алгоритм: `LineTrace` от точки взгляда игрока, при промахе — фолбэк по
dot-product среди помеченных объектов, побеждает максимальный dot.

Для нас это, скорее, «Сайка замечает, что на неё смотрят» — и может
прокомментировать. Пока не первоочередное.

### 7.3 Как правильно инициировать реакцию

Тонкость из документации Convai, которая нам прямо в тему PHILOSOPHY.md: чтобы
персонаж поздоровался при приближении, **не проигрывают анимацию и не суют
готовую реплику**, а отправляют в контекст *наблюдение*:

> «"The player just walked up to you; greet and welcome them" — NOT the literal
> line to say»

То есть модели дают факт, а не текст. Это ровно наш договор «не прописывать ей
реплики».

---

## 8. Числа: константы Convai, проверенные по исходникам

Пригодятся как стартовые значения — они подобраны в проде.

| Параметр | Значение | Смысл |
|---|---|---|
| `OutputFPS` | 90 (раньше 60) | fps лицевой анимации с сервера |
| viseme-поток v3 | 100 fps / 10 мс на кадр | шаг кадра |
| `LipSyncTimeOffset` | 0.02 сек (в одной из бет поднимали до 0.2) | сдвиг лицо/звук |
| `FramesBufferDuration` | 0.5 сек | целевой буфер кадров |
| `MinBufferDuration` | 0.2 сек (в v3 было 0.9) | порог старта воспроизведения |
| `AudioLipSyncRatio` | 0.1 | альтернативный порог старта |
| `LipSyncStarvationFallback` | 5.0 сек | после — сброс лица в ноль |
| `StarvationBlendIn/Out` | 0.1 / 0.8 сек | вход/выход из голодания |
| `UpperFaceAlpha / LowerFaceAlpha` | 0.8 / 1.0 | разделение лица |
| `ChunkSize` | 10 мс | размер аудиочанка |
| частота захвата микрофона | 16 кГц (v3) → 48 кГц (v4, WebRTC) | |
| частота TTS | 21 кГц по умолчанию | |

Нам 60 fps лицевых кадров хватит с запасом: у Августы 6 гласных, а не 251
кривая MetaHuman.

---

## 9. Грабли (собраны из документации, issues и форума Convai)

1. **Имена кривых регистрозависимы.** У Convai при переходе v3→v4 сменился
   регистр ARKit-имён (`jawOpen` → `JawOpen`) и это ломало лицо молча.
   У нас имена морфов приезжают из Blender как есть — зафиксировать один раз
   и не трогать. Отдельная строка лога «нода пыталась записать кривую X,
   такой в скелете нет» экономит часы.
2. **Нода должна стоять в АКТИВНОЙ цепочке поз.** Самая частая причина «рот не
   двигается вообще» — нода в графе есть, но её выход никуда не идёт.
3. **Автопоиск компонента ломается на заспавненных и вложенных актёрах.**
   Поэтому у Convai три уровня фолбэка, включая `GetAttachParentActor()`.
   Пин компонента лучше биндить явно.
4. **Рот замирает посреди речи** = голодание буфера, а не баг кода. Лечится
   `StarvationBlendOutDuration` и размером буфера, не отключением интерполяции.
5. **В упакованном билде лицо не работает** — кривые/AnimBP не попали в cook.
   Проверять до того, как чинить код.
6. **Морфы и LOD.** Convai это нигде не адресует, но проблема реальна:
   у узлов их FaceAnim выставлен `LODThreshold`, то есть часть графа
   отключается на дальних LOD. Наша нода `LODThreshold` иметь не должна — лицо
   пишется всегда, а вот сам меш надо проверить на стриппинг морфов в LOD1+.
7. **Потоки.** Карта текущих весов пишется в игровом потоке, читается в
   анимационном воркере — только под `FCriticalSection`, ссылка на компонент
   слабая с перерезолвом. У Convai был краш в мультиплеере ровно на этом.
8. **Кламп по громкости.** Пользователи Convai жалуются на «резиновое лицо» и
   гасят его `AmplitudeMultiplier = 0.55`, `EmotionsIntensityScale = 0.35`.
   Закладываем глобальный множитель сразу.

---

## 10. Порядок работ

**Этап A — Августа доезжает до UE (в работе)**
1. Отдельный `.blend` под экспорт, оригинал не трогаем.
2. Чистка: NSFW-морфы и кости, `Subsurf`/`Solidify`/`Mask` с тела, лишние
   меши, масштаб в сантиметры.
3. Экспорт `Auto-Rig Pro: Export` → FBX, пресет Unreal Engine, шейпкеи включены.
4. Импорт в UE 5.8, проверка морфов в редакторе.

**Этап B — липсинк end-to-end**
5. `server/face/` — генерация кадров визем из TTS.
6. Расширение `/ws` сообщениями `face_seq` / `emotion` / `lookat`.
7. `USaikaFaceSyncComponent` + `USaikaAudioStreamer` в UE.
8. `FAnimNode_SaikaFaceSync` в отдельном UncookedOnly-модуле.
9. Таблица ремапа из §5, подгонка на слух.

**Этап C — живость**
10. Слой эмоций из `tone.py`.
11. Взгляд и моргание, пороги из §7.1.
12. Трёхслойная схема IDLE→OVERLAY→TRANSIENT на AnimGraph — как в `avatar.html`.

**Этап D — своя модель**
13. Августа — рип из Wuthering Waves. Для отладки и для себя годится, для
    стримов и билда нужен свой персонаж. Пайплайн от этого не зависит: меняется
    только таблица ремапа.

---

## Источники

Документация Convai (`docs.convai.com`): how-lip-sync-works, lip-sync-quick-start,
face-sync-component-reference, face-sync-animgraph-node-reference,
troubleshoot-lip-sync, character-rig-support, plugin-architecture,
gaze-attention-reference, how-the-emotion-system-works, convai-chatbot-component.
Исходники: `Conv-AI/Convai-UnrealEngine-SDK` (v3, до 3.6.9) и
`Conv-AI/Convai-UnrealEngine-SDK-V4` (4.0.0-beta.26) — `ConvaiDefinitions.h`,
`ConvaiFaceSync.h/.cpp`, `Animation/AnimNode_ConvaiFaceSync.h/.cpp`,
`ConvaiAudioStreamer.cpp`, `ConvaiUtils.cpp`, `ConvaiPlayerComponent.h`,
`ConvaiGRPC.cpp`, распакованные `Convai_MetaHuman_FaceAnim` и `ConvaiBaseCharacter`.
Форум Convai: треды по рассинхрону липсинка в UE 5.5–5.7.
