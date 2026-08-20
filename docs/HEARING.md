<!-- Сайка · карта технологий слуха. Собрано 2026-07-28 веб-поиском под
     это железо (Windows, RTX 4070 Ti Super 16ГБ, 64ГБ ОЗУ). Это НЕ
     руководство по проекту, а обзор внешних вариантов: что брать, чем
     платить, куда двигаться дальше. Что уже сделано у нас — anamorf/denoise.py
     (сменные движки + стенд tools/denoise_bench.py) и anamorf/voiceprint/
     (кто говорит). Следующий слой — «ухо»: метки окружающих звуков. -->

# Технический обзор: шумоподавление речи и распознавание звуков окружения в реальном времени (локальный запуск, Windows + RTX 4070 Ti Super 16 ГБ, 64 ГБ ОЗУ)

> Дата обзора: 28 июля 2026. Все данные проверены веб-поиском на актуальность; там, где свежих/точных цифр найти не удалось, это указано явно — цифры не выдуманы.

## 1. Краткий вывод

**Задача 1 (шумоподавление).** Для старта на вашей машине лучший баланс качество/простота/CPU-нагрузка — **DeepFilterNet3** (`pip install deepfilternet`, MIT/Apache-2.0, 48 кГц full-band, RTF≈0.19 на одном потоке CPU ноутбука — на вашем настольном CPU будет ещё быстрее, GPU почти не нужен). Если нужен максимально лёгкий вариант «почти бесплатно по CPU» (embedded-класс, <100 K параметров) — **GTCRN** (RTF 0.07 на Core i5) или классический **RNNoise** (BSD-3, работает без GPU и без Python-биндингов «из коробки», но очень быстрый и проверенный временем). Если хочется максимального качества и не жалко GPU (RTX 4070 Ti Super потянет с большим запасом) — **ClearerVoice-Studio / FRCRN и MossFormer2** от Alibaba (`pip install clearvoice`, Apache-2.0) дают более высокий DNSMOS/PESQ, но менее «единообразный» стриминг-API, чем DeepFilterNet. DTLN — хороший компактный вариант «второго эшелона» (16 кГц, MIT, TF-lite/ONNX, PESQ 3.04), но объективно уступает более новым GTCRN/FastEnhancer при сравнимом размере. Классика (спектральное вычитание, Винер, Martin minimum statistics, MMSE-LSA) на 2026 год интересна скорее как baseline/фолбэк без ML-зависимостей (пакет `noisereduce`), качество заметно ниже нейросетевых методов на нестационарном шуме.

**Задача 2 (звуки окружения).** Для быстрого старта — **YAMNet** (521 класс AudioSet, TensorFlow/TF-Lite, легко ставится, отлично документирован, TensorFlow Hub) — самый простой путь «из коробки» под Windows. Если нужна более высокая точность и есть GPU — **PANNs (CNN14)** через `pip install panns-inference` (527 классов AudioSet, PyTorch) или ещё быстрее — **E-PANNs** (`pip install epanns-inference`, урезанная/прунингованная CNN14, для CPU/edge). Если нужно распознавать своими словами произвольные звуки без переобучения (zero-shot по текстовому описанию) — **LAION-CLAP** (`pip install laion-clap`, CC0). Для max качества классификации/дообучения на своих данных, если не жалко ресурсов — **BEATs** (Microsoft) или **AST** (Audio Spectrogram Transformer, 527 классов AudioSet, mAP 0.459). DCASE-модели (SED, полифоническое обнаружение событий с точным таймингом) полезны, если нужна не просто метка «что звучит», а точные границы события — но требуют больше возни с датасетами и лицензиями конкретных бейзлайнов.

**Диаризация/«кто говорит».** На июль 2026 лучший баланс для домашнего использования — связка **pyannote-audio** (pipeline `speaker-diarization-community-1`, опенсорсная, значительно точнее версии 3.1) для оффлайн/почти-реалтайм анализа, и **diart** (обёртка над pyannote для потокового применения, MIT, задержка настраивается от 0.5 до 5 с). Если нужна максимальная production-скорость на GPU и поддержка потока «из коробки» — **NVIDIA NeMo Streaming Sortformer** (до 4 спикеров, задержка от 0.32 с, RTF 0.002–0.18 на RTX 6000 Ada — на 4070 Ti Super будет сопоставимо или чуть медленнее, но с запасом для реального времени). WeSpeaker и 3D-Speaker — скорее toolkit-и для эмбеддингов/верификации голоса и оффлайн-диаризации (кластеризация), чем готовые потоковые решения.

---

## 2. Таблицы сравнения

### 2.1 Задача 1 — шумоподавление в реальном времени

| Модель / метод | Лицензия | Репозиторий | Частота/размер модели | Стриминг | RTF CPU | RTF GPU | Качество (PESQ / DNSMOS) | Установка на Windows (pip) |
|---|---|---|---|---|---|---|---|---|
| Спектральное вычитание / Винер / Martin MS / MMSE-LSA (классика) | MIT (большинство реализаций) | [noisereduce](https://github.com/timsainb/noisereduce), [logMMSE](https://github.com/yuynwa/logMMSE), [spectral_estnoise_ms](https://github.com/AllisonOge/spectral_estnoise_ms) | без модели, DSP | частично (зависит от реализации, обычно нужен буфер) | очень низкий (чистый DSP) | не нужен | заметно ниже нейросетей на нестационарном шуме; цифр PESQ в актуальных источниках не найдено | `pip install noisereduce` — просто, чистый Python/NumPy |
| RNNoise (Xiph) | BSD-3-Clause | [xiph/rnnoise](https://github.com/xiph/rnnoise) | 48 кГц, GRU, ~85 K параметров («little»-вариант меньше) | да, изначально спроектирован как потоковый (кадры 10 мс) | очень низкий (доли % CPU на кадр) | не нужен | цифр PESQ/DNSMOS в README нет, репутационно — «хорошо, но слабее нейросетей 2020-х» | нет официального pip-пакета; нужны Python-биндинги сторонних авторов ([werman/noise-suppression-for-voice](https://github.com/werman/noise-suppression-for-voice) как VST/CLI) — на Windows сложнее, чем «pip install» |
| DTLN | MIT | [breizhn/DTLN](https://github.com/breizhn/DTLN) | 16 кГц, <1M параметров, блок 32 мс / сдвиг 8 мс | да (TF-Lite/ONNX, готов пример потоковой обработки через `sounddevice`) | ~0.36–0.6 мс/кадр (TF-lite, Intel i5/Macbook Air) | не требуется, но поддерживается | PESQ 3.04 (vs 2.70 baseline), STOI 94.76%, SI-SDR 16.34 дБ (DNS-Challenge) | `pip install tensorflow librosa wavinfo` — просто |
| DeepFilterNet / DeepFilterNet2 / DeepFilterNet3 | MIT или Apache-2.0 (на выбор) | [Rikorose/DeepFilterNet](https://github.com/Rikorose/DeepFilterNet) | 48 кГц full-band; DF2 ~2.31M / DF3 ~2.14M параметров | да, полноценный потоковый STFT/ISTFT конвейер | DF3: RTF≈0.19 на одном потоке CPU ноутбука (по arXiv 2305.08227) | легко real-time с большим запасом на RTX 4070 Ti Super | DF2/DF3 (по независимому сравнению DPDFNet, мультиязычный low-SNR сет): PESQ 2.59 / 2.76, DNSMOS P.808 3.19 / 3.22, STOI 91.2 / 90.5 | `pip install deepfilternet` — одна из самых простых установок; есть готовый бинарник `deep-filter.exe`; обучение официально тестировалось только под Linux, инференс — Windows/macOS/Linux |
| DCCRN | MIT (сторонние реализации, официального пакета нет) | [huyanxin/DeepComplexCRN](https://github.com/huyanxin/DeepComplexCRN), [wangtianrui/DCCRN](https://github.com/wangtianrui/DCCRN) | 16 кГц, комплексные свёртки+LSTM, ~3.7M параметров (по статье 2020 г.) | архитектурно потоковая (причинные свёртки), но готового «из коробки» стрим-примера в репо нет | цифр в открытом доступе на 2026 год не найдено | нет свежих RTF-цифр | PESQ ~2.68 (baseline DNS сравнения в статье 2020 г., по более новым источникам не переизмерялось) | только через клонирование репозитория и ручную сборку, pip-пакета нет |
| FRCRN (входит в ClearerVoice-Studio) | Apache-2.0 | [modelscope/ClearerVoice-Studio](https://github.com/modelscope/ClearerVoice-Studio) | 16/48 кГц; wideband ~6.9M, fullband ~10.27M параметров | да, каузальные свёртки, латентность ≤30 мс | цифр по CPU RTF в открытых источниках 2026 г. не найдено | на RTX 4070 Ti Super — с большим запасом реального времени | PESQ 3.60 (DNS-2020 wideband), 3.21 (VoiceBank+DEMAND); DNSMOS 3.545 (DNS-2022 dev), 3.89 (blind test) | `pip install clearvoice` — просто |
| MossFormer2 (SE, 48K, ClearerVoice-Studio) | Apache-2.0 | [modelscope/ClearerVoice-Studio](https://github.com/modelscope/ClearerVoice-Studio), веса на [Hugging Face](https://huggingface.co/alibabasglab/MossFormer2_SE_48K) | 48 кГц, transformer+conv гибрид, крупнее FRCRN | заявлена поддержка, но требует больше ресурсов, чем FRCRN | не найдено актуальных цифр RTF на CPU | комфортно на RTX 4070 Ti Super | конкретных PESQ/DNSMOS чисел для этой версии в открытых источниках на 2026 г. не найдено (только общие заявления о SOTA) | `pip install clearvoice` |
| Demucs-denoiser (facebookresearch/denoiser) | CC-BY-NC 4.0 (некоммерческая!) | [facebookresearch/denoiser](https://github.com/facebookresearch/denoiser) | waveform-domain encoder-decoder, варианты H=48 / H=64 | да, есть флаг `--streaming` и live-режим | H=48: RTF 0.8 (1 поток) / 0.6 (4 потока); H=64: RTF 1.2 (1 поток) / 1.0 (4 потока) на quad-core i5 2 ГГц — то есть H=64 едва укладывается в реальное время на CPU | легко на RTX 4070 Ti Super | цифр PESQ в README нет (есть флаг `--no_pesq`, но конкретные числа не публикуются в README) | `pip install denoiser`; но лицензия **некоммерческая** — важно для использования не только «дома для себя» |
| Silero denoise | не подтверждено | [snakers4/silero-models](https://github.com/snakers4/silero-models) | нет актуальных данных | нет актуальных данных | нет актуальных данных | нет актуальных данных | Статус модели неясен: в репозитории есть только ноутбук `examples_denoise.ipynb`, README сфокусирован на TTS/STT; свежих (2025-2026) обновлений по denoise-модели не найдено — вероятно, направление заброшено/устарело. **Не выдумываю цифры — актуальных данных нет.** |
| GTCRN | MIT | [Xiaobin-Rong/gtcrn](https://github.com/Xiaobin-Rong/gtcrn) | 16 кГц, всего 48.2 K параметров, 33.0 MMACs | да, отдельная папка `stream` с потоковой реализацией | RTF 0.07 (Intel Core i5-12400) | не требуется, тривиально на RTX 4070 Ti Super | PESQ 2.87 (VCTK-DEMAND), DNSMOS-P.808 3.44 (DNS3 blind test), SI-SDR 18.83 | нет pip-пакета, но это один файл модели + чекпойнт — установка тривиальна (клонировать репо) |
| **Новое 2025-2026: FastEnhancer** | MIT | [aask1357/fastenhancer](https://github.com/aask1357/fastenhancer) | 16/48 кГц, 5 размеров: Tiny 22K … Large 1.1M параметров | да, ONNXRuntime потоковый инференс | Tiny RTF 0.0058 … Large RTF 0.1052 (на «M5 CPU») | легко на RTX 4070 Ti Super | Base: PESQ 3.13, DNSMOS(P.835) 3.38, STOI 0.945 (VoiceBank-DEMAND, 16 кГц) | нет pip, ONNX-модели в releases, инференс скриптами из репозитория |
| **Новое 2025-2026: DPDFNet (DeepFilterNet2 + Dual-Path RNN)** | не указана явно (научный препринт, дек. 2025) | статья [arXiv:2512.16420](https://arxiv.org/html/2512.16420v2), кода в открытом доступе на момент обзора не обнаружено | 2.49M–3.54M параметров (DPDFNet-2/4/8) | заявлена потоковость (наследует архитектуру DeepFilterNet2) | DPDFNet-4: RTF 0.97 на некоем edge NPU (NPN32) | легко на RTX 4070 Ti Super | PESQ 3.14–3.20, DNSMOS P.808 3.26–3.28, STOI 92.6–93.4% — превосходит DF2/DF3 на этом бенчмарке | публичного репозитория/пакета на момент обзора не найдено — только препринт |

Дополнительно, для полноты картины по классике и «инженерным» решениям: **webrtc-noise-gain** ([rhasspy/webrtc-noise-gain](https://github.com/rhasspy/webrtc-noise-gain), Apache-2.0/BSD, обёртка над WebRTC Audio Processing Module) — быстрая классическая NS+AGC без нейросетей, `pip install webrtc-noise-gain`, хороший фолбэк для очень слабого железа или как предварительный фильтр перед нейросетевой моделью.

### 2.2 Задача 2 — распознавание звуков окружения (SED / audio tagging)

| Модель | Классы | Размер | CPU/GPU скорость | Стриминг | Лицензия | Репозиторий | Дообучение |
|---|---|---|---|---|---|---|---|
| YAMNet | 521 (AudioSet-Youtube ontology) | ~3.7M параметров, MobileNetV1-подобная | быстрый на CPU, тривиально на RTX 4070 Ti Super | не нативно потоковый, но работает на скользящих окнах 0.96 с — легко завернуть в потоковый цикл | Apache-2.0 | [tensorflow/models](https://github.com/tensorflow/models/tree/master/research/audioset/yamnet), [TF Hub](https://www.tensorflow.org/hub/tutorials/yamnet) | да, есть официальный туториал transfer learning |
| PANNs (CNN14 и др.) | 527 (AudioSet) | CNN14 ~80M параметров (полная модель линейки PANNs крупнее YAMNet) | на CPU заметно медленнее YAMNet, на GPU (RTX 4070 Ti Super) — быстро | не нативно, окна фиксированной длины (обычно 10 с при 32 кГц), нужна собственная скользящая обвязка | MIT (обёртка `panns_inference`) | [qiuqiangkong/panns_inference](https://github.com/qiuqiangkong/panns_inference), [qiuqiangkong/audioset_tagging_cnn](https://github.com/qiuqiangkong/audioset_tagging_cnn) | да, есть примеры fine-tuning в основном репо |
| E-PANNs (efficient/pruned PANNs) | наследует классы PANNs (527) | CNN14 0.5-pruned — вдвое меньше по вычислениям, чем оригинальный CNN14 (конкретных параметров в открытых источниках не найдено) | заметно быстрее CNN14 на CPU, ориентирован на edge/встраиваемые системы | не заявлено явно | MIT | [StefanoGiacomelli/epanns_inference](https://github.com/StefanoGiacomelli/epanns_inference), статья [arXiv:2305.18665](https://arxiv.org/abs/2305.18665) | не описано в README, но исходники PyTorch — доступно |
| AST (Audio Spectrogram Transformer) | 527 (AudioSet) | 4 размера (tiny224…base384), base384 использовался в статье | без GPU — медленно (ViT-based), на RTX 4070 Ti Super — быстро | нет, требует полный спектрограммный тензор фиксированного размера, не потоковая архитектура «из коробки» | BSD-3-Clause | [YuanGongND/ast](https://github.com/YuanGongND/ast) | да, репозиторий — по сути fine-tuning фреймворк; веса — на Dropbox (не HF) |
| BEATs (Microsoft) | AudioSet fine-tuned варианты (Iter1-3, Iter3+) | не публикуются точные размеры в README, семейство на базе трансформера с акустическими токенами | без GPU медленно, на RTX 4070 Ti Super быстро | не заявлена | лицензия не указана явно в README (проект внутри `microsoft/unilm`, нужно проверять LICENSE репозитория перед коммерческим использованием) | [microsoft/unilm/beats](https://github.com/microsoft/unilm/tree/master/beats) | да, есть fine-tuned варианты и код |
| CLAP / LAION-CLAP | Zero-shot — произвольное число классов по тексту | 630k-audioset checkpoint (non-fusion/fusion варианты), базируется на HTSAT | на GPU (RTX 4070 Ti Super) — быстро; на CPU — приемлемо для коротких клипов | не потоковая «из коробки» (ориентирована на клипы ≤10 с, fusion-вариант — на более длинные), нужен скользящий буфer | CC0-1.0 | [LAION-AI/CLAP](https://github.com/LAION-AI/CLAP) | да, есть training/fine-tuning скрипты (Clotho и др.) |
| Perch / Perch 2.0 (bioacoustics, Google) | тысячи видов (в первую очередь птицы, расширено на других животных/китов в Perch 2.0) | не указано в открытых источниках явно | легковесная CNN-based, быстрая инференс, ориентирована на массовую обработку записей | не заявлена как потоковая в реальном времени, скорее батчевая обработка длинных записей | Apache-2.0 (репозиторий) | [google-research/perch](https://github.com/google-research/perch), [google-research/perch-hoplite](https://github.com/google-research/perch-hoplite) (agile modeling/embeddings), статья [arXiv:2508.04665](https://arxiv.org/html/2508.04665v1) | да, концепция «agile modeling» — быстрое дообучение на малом числе примеров через эмбеддинги |
| DCASE Task4 SED baseline (2025/2026) | зависит от задачи (обычно ~10 бытовых классов: речь, шаги, посуда и т.п.) | зависит от бейзлайна (CRNN/transformer) | оффлайн-ориентированные бейзлайны, не готовы «из коробки» для realtime | обычно требует адаптации под потоковый режим | зависят от конкретного репозитория (обычно MIT/Apache) | [nttcslab/dcase2026_task4_baseline](https://github.com/nttcslab/dcase2026_task4_baseline), [theMoro/dcase25task4](https://github.com/theMoro/dcase25task4) | да, это в первую очередь тренировочные пайплайны, предполагающие дообучение под свои классы |

---

## 3. Разбор кандидатов

### Задача 1 — шумоподавление

**Классика (спектральное вычитание, Винер, Martin minimum statistics, MMSE-LSA).**
Что это: набор алгоритмов 1979–2003 годов, оценивающих спектр шума по «тихим» участкам сигнала и вычитающих/фильтрующих его без обучения на данных. Чем хорош: нулевая зависимость от GPU/фреймворков, предсказуемое поведение, легко дебажить. Чем плох: заметно хуже на нестационарном/бытовом шуме (лай, посуда), часто вносит «музыкальный шум» (artifacts). Установка:
```bash
pip install noisereduce
```
Минимальный потоковый пример (буфер 100 мс при 16 кГц = 1600 сэмплов):
```python
import numpy as np, sounddevice as sd, noisereduce as nr

noise_clip = None  # первый чанк тишины для профиля шума
def callback(indata, frames, time, status):
    global noise_clip
    audio = indata[:, 0]
    if noise_clip is None:
        noise_clip = audio.copy()
    clean = nr.reduce_noise(y=audio, sr=16000, y_noise=noise_clip, stationary=False)
    # clean -> дальше в вывод/обработку

with sd.InputStream(samplerate=16000, blocksize=1600, channels=1, callback=callback):
    sd.sleep(10_000)
```

**RNNoise (Xiph).**
Что это: маленькая GRU-сеть (2018 г.) поверх классических признаков (BFCC), встроена в WebRTC/Discord-подобные пайплайны. Чем хорош: крошечный, проверенный годами, лицензия BSD-3, есть загружаемые кастомные модели (`rnnoise_model_from_file`). Чем плох: нет официального pip-пакета/python API, нужно собирать C-библиотеку или искать сторонние обёртки; качество уступает моделям 2022+. Установка (через сторонний CLI/VST, пример):
```bash
git clone https://github.com/xiph/rnnoise && cd rnnoise && ./autogen.sh && ./configure && make
```
Питон-обвязка обычно делается через `ctypes`/`cffi` вокруг собранной `librnnoise`, либо через сторонние проекты типа `werman/noise-suppression-for-voice` (VST-плагин, не голый Python).

**DTLN.**
Что это: два каскадных LSTM (один в частотной, один в обучаемой временной области), TensorFlow 2.x, изначально спроектирован под DNS-Challenge 2020. Чем хорош: <1M параметров, готовый экспорт в TF-lite/ONNX, есть готовый realtime-скрипт с `sounddevice`. Чем плох: фиксированные 16 кГц, объективно уступает GTCRN/FastEnhancer при похожем размере (PESQ 3.04 против 3.13+ у более новых сетей). Установка:
```bash
pip install tensorflow librosa wavinfo sounddevice
```
Минимальный пример (из репозитория `real_time_processing.py`, упрощённо):
```python
import tflite_runtime.interpreter as tflite
import numpy as np, sounddevice as sd

interp1 = tflite.Interpreter("model_1.tflite"); interp1.allocate_tensors()
interp2 = tflite.Interpreter("model_2.tflite"); interp2.allocate_tensors()
block_len, block_shift = 512, 128  # 32 мс / 8 мс при 16 кГц

def callback(indata, outdata, frames, time, status):
    # прогон блока через оба tflite-интерпретатора (см. DTLN/real_time_processing_tf_lite.py)
    outdata[:] = indata  # заглушка: реальный код — в репозитории

with sd.Stream(samplerate=16000, blocksize=block_shift, channels=1, callback=callback):
    sd.sleep(10_000)
```

**DeepFilterNet / DeepFilterNet2 / DeepFilterNet3.**
Что это: гибрид ERB-фильтрации огибающей + глубокая фильтрация (deep filtering) комплексного спектра, полнополосный (48 кГц), от Interspeech 2022-2023. Чем хорош: лучшая по совокупности установка (`pip install`), готовый бинарник, кроссплатформенность инференса, активно поддерживается и цитируется как база для новых работ (например DPDFNet, дек. 2025). Чем плох: обучение официально проверено только на Linux; полнополосность (48 кГц) требует ресемплинга, если у вас 16 кГц пайплайн. Установка:
```bash
pip install deepfilternet
# либо для GPU-инференса:
pip install deepfilternet torch --index-url https://download.pytorch.org/whl/cu121
```
Минимальный потоковый пример:
```python
import torch
from df.enhance import init_df, enhance
from df.io import load_audio

model, df_state, _ = init_df()  # автоматически скачает DeepFilterNet3
audio, _ = load_audio("input.wav", sr=df_state.sr())
enhanced = enhance(model, df_state, audio)  # для потока — резать на кадры df_state.hop_size()
```
Для по-настоящему потокового (frame-by-frame) сценария в репозитории есть низкоуровневый API `df.enhance` с сохранением состояния между вызовами (см. `libDF`/Rust-биндинги) — рекомендуется смотреть `examples/` в репозитории под конкретную версию.

**DCCRN.**
Что это: complex-valued CRNN (свёртки+LSTM в комплексной арифметике), Interspeech 2020, база для многих последующих архитектур (включая S-DCCRN). Чем хорош: хорошее качество на 16 кГц при умеренном размере, множество независимых PyTorch-реализаций. Чем плох: нет официального сопровождаемого репозитория с pip-пакетом, нет свежих (2025-2026) переизмерений качества/скорости — оценивать риски нужно самостоятельно на своих данных. Установка — только вручную клонировать один из community-репозиториев ([huyanxin/DeepComplexCRN](https://github.com/huyanxin/DeepComplexCRN)) и адаптировать инференс-скрипт под потоковую подачу кадров.

**FRCRN / ClearerVoice-Studio (Alibaba).**
Что это: Frequency Recurrent CRN — рекуррентность не только во времени, но и по частотной оси, часть большого тулкита ClearerVoice-Studio (речевое улучшение + разделение + target speaker extraction). Чем хорош: сильные объективные метрики (PESQ 3.60 wideband DNS-2020, DNSMOS 3.89 на blind test), простая установка, активно развивается (обновления в 2025-2026, статья ClearerVoice-Studio arXiv:2506.19398). Чем плох: тяжелее DTLN/GTCRN, для CPU-only сценария избыточен; готового «одна функция — один потоковый кадр» примера в документации меньше, чем у DeepFilterNet. Установка:
```bash
pip install clearvoice
```
Пример (батчевый, для потока нужно резать на кадры по 30 мс с overlap согласно документации репозитория):
```python
from clearvoice import ClearVoice

cv = ClearVoice(task="speech_enhancement", model_names=["FRCRN_SE_16K"])
output = cv(input_path="input.wav", online_write=False)
```

**GTCRN.**
Что это: «ультра-лёгкая» модель 2024 года (ICASSP), Grouped Temporal Convolutional Recurrent Network — 48.2K параметров, специально спроектирована как SOTA среди сверхлёгких моделей. Чем хорош: рекордное соотношение качество/вычисления (PESQ 2.87 при 33 MMACs), есть отдельная папка `stream` с готовой потоковой реализацией и измеренным RTF 0.07 на CPU. Чем плох: нет pip-пакета и обёртки для продакшена, надо интегрировать вручную; сообщество меньше, чем у DeepFilterNet. Установка — клонирование репозитория:
```bash
git clone https://github.com/Xiaobin-Rong/gtcrn
```
Потоковый пример — согласно `stream/` в репозитории (упрощённая идея):
```python
import torch
from stream.gtcrn_stream import GTCRNStream  # см. точное имя класса в репозитории

model = GTCRNStream()
model.load_state_dict(torch.load("checkpoints/model_trained_on_dns3.tar")["model"])
model.eval()
state = model.init_state()
# на каждый кадр (напр. 512 сэмплов при 16 кГц):
with torch.no_grad():
    frame_out, state = model(frame_in, state)
```

**Demucs-denoiser (facebookresearch/denoiser).**
Что это: waveform-to-waveform энкодер-декодер (архитектура похожа на Demucs для музыки), Interspeech 2020, две версии по размеру скрытого слоя (H=48/H=64). Чем хорош: качество на слух хорошее, есть готовый live-режим с виртуальным аудиоустройством. Чем плох: **лицензия CC-BY-NC 4.0 — только некоммерческое использование** (важно, если планируете что-то большее, чем личный проект); на CPU версия H=64 балансирует на грани реального времени (RTF≈1.0-1.2). Установка:
```bash
pip install denoiser
```
Пример запуска live-режима на Windows (согласно README):
```bash
python.exe -m denoiser.live --out_dir=out_dir
```
На RTX 4070 Ti Super эта модель бежит с огромным запасом (`--device cuda`), CPU-режим не обязателен.

**Silero denoise.**
Статус на 2026 год неясен: официальный репозиторий `snakers4/silero-models` содержит лишь пример-ноутбук `examples_denoise.ipynb`, а фокус проекта явно сместился на TTS/STT (Silero VAD выделен в отдельный активно поддерживаемый репозиторий `snakers4/silero-vad`, но это детектор речи, а не шумоподавитель). Свежих обновлений или заявлений о поддержке denoise-модели в 2025-2026 гг. не найдено. **Рекомендация: не полагаться на эту модель как на актуальное решение**, проверить историю коммитов репозитория перед использованием.

**Новое (2025-2026): FastEnhancer.**
Что это: свежая (сентябрь 2025) архитектура, специально оптимизированная под скорость на edge/CPU при сохранении качества, 5 конфигураций от Tiny (22K параметров) до Large (1.1M). Чем хорош: самый широкий диапазон trade-off качество/скорость среди современных моделей, RTF от 0.006 (Tiny) до 0.1 (Large), ONNXRuntime для продакшн-инференса. Чем плох: молодой проект (сентябрь 2025), меньше community и готовых интеграций, чем у DeepFilterNet. Установка — по инструкции из [документации проекта](https://aask1357.github.io/fastenhancer/installation) (репозиторий на GitHub, пакета в PyPI на момент обзора нет).

**Новое (2025-2026): DPDFNet.**
Препринт декабря 2025 года, добавляет Dual-Path RNN поверх архитектуры DeepFilterNet2 и превосходит DF2/DF3 по PESQ/DNSMOS/STOI на мультиязычном low-SNR бенчмарке. На момент обзора публичного кода/весов найти не удалось — только статья ([arXiv:2512.16420](https://arxiv.org/html/2512.16420v2)). Стоит следить за репозиторием авторов на предмет релиза кода.

---

### Задача 2 — «Ухо»: звуки окружения

**YAMNet.**
Что это: MobileNet-подобная CNN от Google, обучена на AudioSet (521 класс), эталонный «простой старт» для audio tagging. Чем хорош: минимальная установка через TensorFlow Hub, отличная документация, скорость с большим запасом на CPU. Чем плох: окна классификации фиксированной длины (~0.96 с/кадр), не «истинно потоковая» архитектура — нужен свой скользящий буфер; относительно скромная точность по сравнению с трансформерами (AST/BEATs). Установка:
```bash
pip install tensorflow tensorflow_hub numpy
```
Минимальный потоковый пример:
```python
import numpy as np, sounddevice as sd, tensorflow_hub as hub

yamnet = hub.load("https://tfhub.dev/google/yamnet/1")
class_names = [line.split(",")[2].strip() for line in
               open(yamnet.class_map_path().numpy().decode()).readlines()[1:]]

def callback(indata, frames, time, status):
    audio = indata[:, 0].astype(np.float32)
    scores, embeddings, spectrogram = yamnet(audio)
    top = np.argmax(scores.numpy().mean(axis=0))
    print(class_names[top])

with sd.InputStream(samplerate=16000, blocksize=15600, channels=1, callback=callback):  # ~0.96с при 16кГц реально нужен ресемпл в 16кГц (YAMNet ожидает 16кГц mono)
    sd.sleep(10_000)
```

**PANNs (CNN14).**
Что это: набор CNN, обученных на полном AudioSet (527 классов), из статьи 2019 г., до сих пор используется как сильный baseline. Чем хорош: официальный `pip`-пакет с готовым инференсом (`panns_inference`), поддержка audio tagging и sound event detection «из коробки». Чем плох: работает на 32 кГц (нужен ресемплинг с 16 кГц), крупнее и медленнее YAMNet на CPU, не спроектирован как потоковый. Установка:
```bash
pip install panns_inference torch librosa
```
Минимальный пример:
```python
import librosa
from panns_inference import AudioTagging

at = AudioTagging(checkpoint_path=None, device="cuda")  # скачает веса автоматически
audio, _ = librosa.load("chunk.wav", sr=32000, mono=True)
clipwise_output, embedding = at.inference(audio[None, :])
```

**E-PANNs (efficient PANNs).**
Что это: прунингованная версия CNN14 (Internoise 2023), сохраняющая классы PANNs при заметно меньших вычислениях. Чем хорош: специально нацелен на «дешёвый» инференс (edge/CPU), тот же набор классов, что у PANNs, поэтому drop-in замена. Чем плох: меньше документации/примеров, чем у оригинальных PANNs, конкретных цифр по размеру/скорости в открытых источниках немного. Установка:
```bash
pip install epanns_inference
```

**AST (Audio Spectrogram Transformer).**
Что это: чистый ViT-подобный трансформер поверх мел-спектрограммы, Interspeech 2021, один из первых успешных transformer-подходов к audio tagging (mAP 0.459 на AudioSet). Чем хорош: сильная точность, лицензия BSD-3, официальный код и веса. Чем плох: не потоковый (нужен целый спектрограммный тензор фиксированной длины), веса лежат на Dropbox, а не на HF (менее удобно скачивать), сравнительно тяжёлый для CPU. Установка:
```bash
git clone https://github.com/YuanGongND/ast && cd ast
python -m venv venvast && venvast\Scripts\activate
pip install -r requirements.txt
```
Для использования проще взять версию из `transformers`:
```python
from transformers import ASTForAudioClassification, ASTFeatureExtractor
import torch, librosa

fe = ASTFeatureExtractor.from_pretrained("MIT/ast-finetuned-audioset-10-10-0.4593")
model = ASTForAudioClassification.from_pretrained("MIT/ast-finetuned-audioset-10-10-0.4593")
audio, _ = librosa.load("chunk.wav", sr=16000)
inputs = fe(audio, sampling_rate=16000, return_tensors="pt")
with torch.no_grad():
    logits = model(**inputs).logits
```

**BEATs (Microsoft).**
Что это: self-supervised акустический трансформер с обучаемым «токенизатором» звука (аналог BERT для аудио), несколько итераций (Iter1…Iter3+), сильные результаты на AudioSet fine-tuning. Чем хорош: качество на уровне SOTA среди классификаторов, поддержка fine-tuning. Чем плох: минимальная документация по установке (нет `pip`, нет чёткого README про размеры/лицензию — нужно проверять LICENSE в `microsoft/unilm` перед использованием, особенно коммерческим), нет заявленной потоковости. Установка — вручную из монорепозитория:
```bash
git clone https://github.com/microsoft/unilm
cd unilm/beats
pip install torch fairseq  # или скорректированные зависимости из репозитория
```

**CLAP / LAION-CLAP.**
Что это: контрастная модель аудио-текст (аналог CLIP для звука), позволяет классифицировать звук по произвольному текстовому описанию без переобучения (zero-shot: «This is a sound of dog barking»). Чем хорош: гибкость — не нужно заранее фиксировать список классов, легко добавлять новые метки текстом; лицензия CC0 (максимально свободная). Чем плох: ориентирован на клипы до ~10 с (без fusion-варианта), zero-shot точность обычно ниже дообученного классификатора на тех же классах; для потоковой работы нужно самому организовать скользящее окно. Установка:
```bash
pip install laion-clap
```
Минимальный пример zero-shot:
```python
import laion_clap
import numpy as np

model = laion_clap.CLAP_Module(enable_fusion=False)
model.load_ckpt()  # скачает 630k-audioset-best.pt

text_data = ["dog barking", "footsteps", "rain", "keyboard typing", "dishes clinking"]
text_embed = model.get_text_embedding(text_data)

audio_chunk = np.random.randn(1, 48000).astype(np.float32)  # 1с при 48кГц
audio_embed = model.get_audio_embedding_from_data(x=audio_chunk, use_tensor=False)

sims = audio_embed @ text_embed.T
print(text_data[int(np.argmax(sims))])
```

**Perch / Perch 2.0.**
Что это: биоакустическая модель Google (изначально — птицы, во 2-й версии, 2025 г., расширена на другие таксоны, включая китов — статья arXiv:2508.04665 подтверждает генерализацию на подводную акустику). Чем хорош: концепция «agile modeling» через `perch-hoplite` — быстрое дообучение классификатора поверх эмбеддингов на нескольких примерах пользовательских звуков (актуально для задачи «дообучить под свои бытовые звуки»). Чем плох: заточена под природные/видовые звуки, а не под бытовые (посуда/клавиатура/шаги) — для вашей задачи это скорее источник методики (embedding + быстрое дообучение), чем готовый классификатор нужных классов. Установка:
```bash
git clone https://github.com/google-research/perch-hoplite
pip install -e perch-hoplite
```

**DCASE Task4 SED-модели.**
Что это: ежегодные бейзлайны DCASE Challenge по полифоническому обнаружению звуковых событий (Sound Event Detection) — в отличие от audio tagging, дают не просто метку на клип, а временные границы события. Чем хорош: точный тайминг событий, активное сообщество, свежие бейзлайны 2025/2026 годов ([dcase2026_task4_baseline](https://github.com/nttcslab/dcase2026_task4_baseline), [dcase25task4](https://github.com/theMoro/dcase25task4)). Чем плох: бейзлайны рассчитаны на оффлайн-обучение/оценку на конкретных датасетах (обычно бытовые классы ограничены ~10 категориями), адаптация под ваш потоковый realtime-сценарий и собственные звуки потребует заметной инженерной работы (не «из коробки»). Рекомендуется как «третий эшелон» — источник архитектур и рецептов дообучения, если YAMNet/PANNs/CLAP не дадут нужной точности по границам событий.

---

### Диаризация и «кто говорит» (кратко)

- **pyannote-audio** (пайплайн `speaker-diarization-community-1`) — опенсорсный, по данным официального блога значительно точнее версии 3.1 по speaker confusion; для оффлайн/квази-реального времени. Установка: `pip install pyannote.audio`, использование:
```python
from pyannote.audio import Pipeline
pipeline = Pipeline.from_pretrained("pyannote/speaker-diarization-community-1", token="hf_...")
diarization = pipeline("meeting.wav")
```
- **diart** — потоковая обёртка над сегментацией/эмбеддингами pyannote, MIT, задержка настраивается 0.5–5 с, задержки моделей на CPU/GPU (AMD Ryzen 9 / RTX 4060) — единицы-десятки миллисекунд на кадр. Хороший выбор именно для «домашнего realtime».
```bash
pip install diart
```
- **NVIDIA NeMo Streaming Sortformer** — до 4 спикеров, лицензия CC-BY-4.0, латентность от 0.32 с («ultra low latency»), RTF 0.002–0.18 на RTX 6000 Ada (на 4070 Ti Super ожидаемо сопоставимо или чуть медленнее — с запасом для realtime). Наиболее production-ready вариант с готовым HF-чекпойнтом `nvidia/diar_streaming_sortformer_4spk-v2`, но требует установки полного NeMo toolkit (тяжёлая зависимость).
- **WeSpeaker** — Apache-2.0, в первую очередь тулкит speaker embedding/verification (ECAPA-TDNN и др.), для диаризации использует кластеризацию (UMAP+HDBSCAN) поверх эмбеддингов — хорош как источник качественных голосовых эмбеддингов для «узнавания» конкретных людей дома, но не готовый потоковый диаризатор.
- **3D-Speaker** (Alibaba/ModelScope) — аналогичный WeSpeaker многомодальный тулкит (аудио+видео) для верификации/диаризации, полезен, если вдруг понадобится мультимодальность (видео с микрофоном), для чисто аудио-домашнего сценария избыточен.

**Вывод по диаризации:** для дома лучше всего связка **diart (потоковый слой) + модели pyannote community-1 (сегментация/эмбеддинги)** — минимальная лицензия трения (MIT), приемлемая задержка, готовые Python-примеры. NeMo Sortformer — запасной вариант, если понадобится более строгий realtime и вы готовы поставить полный NeMo.

---

## 4. Порядок внедрения

1. **Первым делом (день 1-2):**
   - Шумоподавление: поставить **DeepFilterNet3** (`pip install deepfilternet`) и прогнать на реальном микрофоне — это даст сразу приемлемое качество почти без возни с интеграцией.
   - Звуки окружения: поставить **YAMNet** через `tensorflow_hub` — минимальный код, сразу 521 класс AudioSet для проверки принципиальной работоспособности пайплайна (захват аудио → чанки 100 мс → инференс → метка).
   - Диаризация (если нужна сразу): **diart** поверх pyannote — быстрый рабочий прототип «кто говорит».

2. **Вторым шагом (неделя 1-2), если первого недостаточно по качеству/скорости:**
   - Шумоподавление: сравнить с **GTCRN** (если критична минимальная CPU-нагрузка на слабом фоновом процессе) и/или **FRCRN/MossFormer2 из ClearerVoice-Studio** (если критично максимальное качество и GPU не жалко).
   - Звуки окружения: перейти на **PANNs (`panns_inference`)** для более высокой точности классификации, добавить **LAION-CLAP** для тех классов, которые не покрыты фиксированным списком AudioSet (произвольные текстовые описания «звук открывающейся двери» и т.п.).
   - Диаризация: если нужна выше точность/устойчивость к числу говорящих — попробовать **pyannote speaker-diarization-community-1** напрямую (без streaming-обёртки) в оффлайн-режиме на записанных фрагментах, сравнить с diart.

3. **Третий эшелон (по необходимости для продакшн-качества/специфики):**
   - Шумоподавление: оценить свежие исследовательские модели — **FastEnhancer** (гибкий выбор размера под задержку) и следить за релизом кода **DPDFNet**; при необходимости фолбэка без ML — **webrtc-noise-gain** как дешёвый предварительный фильтр.
   - Звуки окружения: **AST/BEATs** для максимальной точности классификации (если хватает GPU-бюджета) и/или дообучение под свои конкретные бытовые звуки на базе эмбеддингов (методика **Perch/perch-hoplite** — быстрое дообучение по нескольким примерам — переносима и на не-биоакустические классы); при необходимости точных временных границ событий — адаптировать бейзлайн **DCASE Task4**.
   - Диаризация: если нужен строгий production-realtime с GPU-ускорением — **NVIDIA NeMo Streaming Sortformer**; для точной идентификации конкретных членов семьи — построить отдельную базу голосовых эмбеддингов через **WeSpeaker**.

---

### Общие замечания по установке на Windows

- Все перечисленные `pip install` пакеты (deepfilternet, clearvoice, panns_inference, epanns_inference, laion-clap, noisereduce, diart, pyannote.audio) ставятся на Windows штатно через pip; основные сложности на практике — с `torch`+CUDA (нужно ставить с явным `--index-url` под вашу версию CUDA/RTX 4070 Ti Super) и с системными аудио-зависимостями diart/pyannote (ffmpeg, portaudio, libsndfile) — их проще всего поставить через conda-forge, если чистый pip не находит бинарники под Windows.
- Модели без pip-пакета (RNNoise, DCCRN, GTCRN, FastEnhancer, DPDFNet) требуют клонирования репозитория и запуска из исходников — на Windows это тоже работает, но обычно нужен Git и иногда Visual C++ Build Tools для нативных зависимостей.
- Лицензии, требующие внимания: **facebookresearch/denoiser — CC-BY-NC-4.0 (только некоммерческое использование)**; BEATs — лицензия явно не прописана в README, проверить LICENSE-файл в `microsoft/unilm` перед использованием вне личных экспериментов.
