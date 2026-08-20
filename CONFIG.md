# Справочник настроек Сайки

> Файл СГЕНЕРИРОВАН: `python -m tools.config_map`. Руками не править —
> перезапишется. Правится код или `config.json`.

Всего ключей: **640**. Из них в коде читается 473, в конфигах лежит 345.

Как это работает: `config.local.json` накладывается поверх `config.json` при загрузке, поэтому личные настройки машины переживают `git pull`. Ключа нет нигде — берётся значение по умолчанию прямо из кода, колонка «по умолчанию».

## ⚠ Читается в коде, но в конфигах отсутствует

Работает на значении по умолчанию. Это нормально (так задумано для новых возможностей), но если ключ важен — его стоит внести в `config.json`, чтобы он был виден человеку.

- `<выражение>`
- `agent.budget_s`
- `agent.enabled`
- `agent.max_steps`
- `aliases`
- `assistant.name`
- `attention.social`
- `attn`
- `autostart.enabled`
- `avatar`
- `avatar.desk`
- `avatar.desk.span`
- `avatar.gestures.tone_map`
- `avatar.web.library_dir`
- `base_model`
- `batch_size`
- `beatbox.enabled`
- `beatbox.floor`
- `beatbox.max_event_s`
- `beatbox.trill_peak`
- `browser.ai_query`
- `browser.ask_after_min`
- `browser.cdp_port`
- `browser.channel`
- `browser.chrome_profile`
- `browser.enabled`
- `browser.idle_close_min`
- `browser.use_system_chrome`
- `compile_mode`
- `compression_ratio_threshold`
- `compute_type`
- `consult.base_url`
- `consult.cooldown_s`
- `consult.enabled`
- `consult.model`
- `cortex.forget_s`
- `dataset_dir`
- `decode_window_frames`
- `denoise.dd_alpha`
- `denoise.floor`
- `denoise.gate_hold_ms`
- `denoise.gate_min`
- `denoise.gate_ratio`
- `denoise.min_bias`
- `denoise.nr_prop`
- `denoise.nr_stationary`
- `denoise.over`
- `denoise.segment_engine`
- `denoise.speech_ratio`
- `device`
- `dialog.live_context`
- `dialog.live_context_grace_s`
- `dialog.live_context_min_gap_s`
- `doctor.startup_ai`
- `doctor.startup_ai_delay_s`
- `dreampc`
- `earlog.max_cluster`
- `earlog.sound_thr`
- `earlog.voice_thr`
- `emit_every_frames`
- `epochs`
- `files.enabled`
- `files.roots`
- `game_watch.cooldown_s`
- `game_watch.enabled`
- `game_watch.titles`
- `grad_accum`
- `guard.auto_free_engine`
- `guard.period_s`
- `guard.protect`
- `guard.temp_calm`
- `guard.temp_crit`
- `guard.temp_warn`
- `guard.triage`
- `guard.vram_calm`
- `guard.vram_crit`
- `guard.vram_warn`
- `hands.send_ask_life_s`
- `hands.web_cycle_s`
- `heal.enabled`
- …и ещё 215

## ⚠ Лежит в конфиге, но код его не читает

Кандидаты на удаление: либо остались от вырезанных возможностей, либо читаются не через `CFG.get` (например, целой веткой — тогда это ложная тревога).

- `_comment` = "Настройки ЭТОЙ машины. Файл в .gitignore…
- `avatar.desk.ghost` = false
- `avatar.desk.h` = 918
- `avatar.desk.slots.saika_v1.h` = 918
- `avatar.desk.slots.saika_v1.view.az` = 0.0
- `avatar.desk.slots.saika_v1.view.dist` = 0.0
- `avatar.desk.slots.saika_v1.view.el` = 0.0
- `avatar.desk.slots.saika_v1.view.headFollow` = true
- `avatar.desk.slots.saika_v1.view.lean` = 0.0
- `avatar.desk.slots.saika_v1.view.ortho` = false
- `avatar.desk.slots.saika_v1.view.ox` = 0.001412315484514749
- `avatar.desk.slots.saika_v1.view.oy` = 0.0805019826173407
- `avatar.desk.slots.saika_v1.view.oz` = 0.0
- `avatar.desk.slots.saika_v1.view.rx` = 0.0
- `avatar.desk.slots.saika_v1.view.ry` = 0.0
- `avatar.desk.slots.saika_v1.view.rz` = 0.0
- `avatar.desk.slots.saika_v1.view.snap` = 0.0
- `avatar.desk.slots.saika_v1.view.x` = -0.007489694230383152
- `avatar.desk.slots.saika_v1.view.y` = 0.001412315484514749
- `avatar.desk.slots.saika_v1.view.z` = 0.0
- `avatar.desk.slots.saika_v1.view.zoom` = 1.0
- `avatar.desk.slots.saika_v1.w` = 434
- `avatar.desk.slots.saika_v1.x` = 3317
- `avatar.desk.slots.saika_v1.y` = 262
- `avatar.desk.view.az` = 0.0
- `avatar.desk.view.dist` = 0.0
- `avatar.desk.view.el` = 0.0
- `avatar.desk.view.headFollow` = true
- `avatar.desk.view.lean` = 0.0
- `avatar.desk.view.ortho` = false
- `avatar.desk.view.ox` = 0.001412315484514749
- `avatar.desk.view.oy` = 0.0805019826173407
- `avatar.desk.view.oz` = 0.0
- `avatar.desk.view.rx` = 0.0
- `avatar.desk.view.ry` = 0.0
- `avatar.desk.view.rz` = 0.0
- `avatar.desk.view.snap` = 0.0
- `avatar.desk.view.x` = -0.007489694230383152
- `avatar.desk.view.y` = 0.001412315484514749
- `avatar.desk.view.z` = 0.0
- `avatar.desk.view.zoom` = 1.0
- `avatar.desk.w` = 434
- `avatar.desk.x` = 3317
- `avatar.desk.y` = 262
- `avatar.gestures.tone_map.flirt` = "fun"
- `avatar.gestures.tone_map.hostile` = "angry"
- `avatar.gestures.tone_map.praise` = "joy"
- `avatar.gestures.tone_map.provoke` = "good"
- `avatar.gestures.tone_map.vulgar` = "shaking"
- `dreampc.block_length` = 32
- `dreampc.gen_length` = 128
- `dreampc.port` = 8768
- `dreampc.quant` = "4bit"
- `dreampc.setup` = "setup/install_dreampc.bat"
- `dreampc.steps` = 128
- `dreampc.temperature` = 0.0
- `dreampc.timeout_s` = 1800
- `dreampc.venv` = ".venv_dreampc"
- `dreampc.worker` = "workers/dreampc_worker.py"
- `llamacpp.n_ctx` = 24576
- `llm.max_history` = 14
- `llm.n_ctx` = "32768"
- `llm.sampling.dry_allowed_length` = 2
- `llm.sampling.dry_base` = 1.75
- `llm.sampling.dry_multiplier` = 0.0
- `llm.sampling.dynatemp_exponent` = 1.0
- `llm.sampling.dynatemp_range` = 0.0
- `llm.sampling.enabled` = false
- `llm.sampling.frequency_penalty` = 0.0
- `llm.sampling.min_p` = 0.05
- `llm.sampling.presence_penalty` = 0.0
- `llm.sampling.preset` = "off"
- `llm.sampling.repeat_penalty` = 1.0
- `llm.sampling.seed` = -1
- `llm.sampling.stop` = []
- `llm.sampling.top_k` = 40
- `llm.sampling.top_p` = 0.95
- `llm.sampling.typical_p` = 1.0
- `llm.sampling.xtc_probability` = 0.0
- `llm.sampling.xtc_threshold` = 0.1
- …и ещё 87

## Все ключи по разделам

### <выражение>

| ключ | сейчас | по умолчанию | где читается |
|---|---|---|---|
| `<выражение>` | — | `'<выражение>' / — / 'off' ⚠` | `anamorf/avatar_hub.py`, `anamorf/cards.py`, `anamorf/denoise.py` +5 |

### _comment

| ключ | сейчас | по умолчанию | где читается |
|---|---|---|---|
| `_comment` | "Настройки ЭТОЙ машины. Файл в .gitignore… | `—` | — |

### agent

| ключ | сейчас | по умолчанию | где читается |
|---|---|---|---|
| `agent.budget_s` | — | `35` | `anamorf/agent.py` |
| `agent.enabled` | — | `True` | `anamorf/agent.py` |
| `agent.max_steps` | — | `5` | `anamorf/agent.py` |

### aliases

| ключ | сейчас | по умолчанию | где читается |
|---|---|---|---|
| `aliases` | — | `{}` | `anamorf/messengers.py` |

### assistant

| ключ | сейчас | по умолчанию | где читается |
|---|---|---|---|
| `assistant.name` | — | `'Сайка'` | `anamorf/misheard.py` |

### assistant_name

| ключ | сейчас | по умолчанию | где читается |
|---|---|---|---|
| `assistant_name` | "Сайка" | `'Сайка'` | `anamorf/main.py`, `anamorf/voiceprint/__init__.py` |

### attention

| ключ | сейчас | по умолчанию | где читается |
|---|---|---|---|
| `attention.always` | true | `False` | `anamorf/main.py` |
| `attention.enabled` | true | `True` | `anamorf/main.py` |
| `attention.fuzzy_max_edits` | 1 | `1` | `anamorf/main.py` |
| `attention.name_prefixes` | ["сайк", "saik"] | `['сайк', 'saik']` | `anamorf/main.py` |
| `attention.social` | — | `True` | `anamorf/main.py` |
| `attention.stop_words` | ["стоп", "стой", "хватит", "замолчи", "мо… | `['стоп', 'стой', 'хватит', 'замолчи', 'молчи', 'помолчи', 'заткнись', 'остановись', 'стопэ'] / [] ⚠` | `anamorf/main.py`, `anamorf/misheard.py` |
| `attention.window_s` | 30 | `30` | `anamorf/main.py` |

### attn

| ключ | сейчас | по умолчанию | где читается |
|---|---|---|---|
| `attn` | — | `'auto'` | `anamorf/tts/manager.py` |

### autostart

| ключ | сейчас | по умолчанию | где читается |
|---|---|---|---|
| `autostart.enabled` | — | `True` | `anamorf/main.py` |

### avatar

| ключ | сейчас | по умолчанию | где читается |
|---|---|---|---|
| `avatar` | — | `—` | `tools/desk_avatar.py` |
| `avatar.desk` | — | `{}` | `anamorf/desk_avatar.py` |
| `avatar.desk.frame` | false | `—` | `anamorf/desk_avatar.py` |
| `avatar.desk.ghost` | false | `—` | — |
| `avatar.desk.h` | 918 | `—` | — |
| `avatar.desk.lock` | true | `False` | `anamorf/desk_avatar.py` |
| `avatar.desk.on` | true | `—` | `anamorf/desk_avatar.py` |
| `avatar.desk.slots.saika_v1.h` | 918 | `—` | — |
| `avatar.desk.slots.saika_v1.view.az` | 0.0 | `—` | — |
| `avatar.desk.slots.saika_v1.view.dist` | 0.0 | `—` | — |
| `avatar.desk.slots.saika_v1.view.el` | 0.0 | `—` | — |
| `avatar.desk.slots.saika_v1.view.headFollow` | true | `—` | — |
| `avatar.desk.slots.saika_v1.view.lean` | 0.0 | `—` | — |
| `avatar.desk.slots.saika_v1.view.ortho` | false | `—` | — |
| `avatar.desk.slots.saika_v1.view.ox` | 0.001412315484514749 | `—` | — |
| `avatar.desk.slots.saika_v1.view.oy` | 0.0805019826173407 | `—` | — |
| `avatar.desk.slots.saika_v1.view.oz` | 0.0 | `—` | — |
| `avatar.desk.slots.saika_v1.view.rx` | 0.0 | `—` | — |
| `avatar.desk.slots.saika_v1.view.ry` | 0.0 | `—` | — |
| `avatar.desk.slots.saika_v1.view.rz` | 0.0 | `—` | — |
| `avatar.desk.slots.saika_v1.view.snap` | 0.0 | `—` | — |
| `avatar.desk.slots.saika_v1.view.x` | -0.007489694230383152 | `—` | — |
| `avatar.desk.slots.saika_v1.view.y` | 0.001412315484514749 | `—` | — |
| `avatar.desk.slots.saika_v1.view.z` | 0.0 | `—` | — |
| `avatar.desk.slots.saika_v1.view.zoom` | 1.0 | `—` | — |
| `avatar.desk.slots.saika_v1.w` | 434 | `—` | — |
| `avatar.desk.slots.saika_v1.x` | 3317 | `—` | — |
| `avatar.desk.slots.saika_v1.y` | 262 | `—` | — |
| `avatar.desk.span` | — | `—` | `anamorf/desk_avatar.py` |
| `avatar.desk.top` | true | `True` | `anamorf/desk_avatar.py` |
| `avatar.desk.view.az` | 0.0 | `—` | — |
| `avatar.desk.view.dist` | 0.0 | `—` | — |
| `avatar.desk.view.el` | 0.0 | `—` | — |
| `avatar.desk.view.headFollow` | true | `—` | — |
| `avatar.desk.view.lean` | 0.0 | `—` | — |
| `avatar.desk.view.ortho` | false | `—` | — |
| `avatar.desk.view.ox` | 0.001412315484514749 | `—` | — |
| `avatar.desk.view.oy` | 0.0805019826173407 | `—` | — |
| `avatar.desk.view.oz` | 0.0 | `—` | — |
| `avatar.desk.view.rx` | 0.0 | `—` | — |
| `avatar.desk.view.ry` | 0.0 | `—` | — |
| `avatar.desk.view.rz` | 0.0 | `—` | — |
| `avatar.desk.view.snap` | 0.0 | `—` | — |
| `avatar.desk.view.x` | -0.007489694230383152 | `—` | — |
| `avatar.desk.view.y` | 0.001412315484514749 | `—` | — |
| `avatar.desk.view.z` | 0.0 | `—` | — |
| `avatar.desk.view.zoom` | 1.0 | `—` | — |
| `avatar.desk.w` | 434 | `—` | — |
| `avatar.desk.x` | 3317 | `—` | — |
| `avatar.desk.y` | 262 | `—` | — |
| `avatar.enabled` | true | `False` | `anamorf/avatar.py`, `anamorf/llm/tools.py` |
| `avatar.gestures.cooldown_s` | 8 | `8` | `anamorf/avatar.py` |
| `avatar.gestures.enabled` | true | `True` | `anamorf/avatar.py` |
| `avatar.gestures.idle.enabled` | true | `True` | `anamorf/avatar.py` |
| `avatar.gestures.idle.max_s` | 300 | `300` | `anamorf/avatar.py` |
| `avatar.gestures.idle.min_s` | 120 | `120` | `anamorf/avatar.py` |
| `avatar.gestures.idle.slots` | ["idle1", "idle2"] | `['idle1', 'idle2']` | `anamorf/avatar.py` |
| `avatar.gestures.slot_names` | ["reset", "joy", "angry", "sorrow", "fun"… | `'<выражение>'` | `anamorf/avatar.py`, `anamorf/llm/tools.py` |
| `avatar.gestures.tone_map` | — | `'<выражение>'` | `anamorf/avatar.py` |
| `avatar.gestures.tone_map.flirt` | "fun" | `—` | — |
| `avatar.gestures.tone_map.hostile` | "angry" | `—` | — |
| `avatar.gestures.tone_map.praise` | "joy" | `—` | — |
| `avatar.gestures.tone_map.provoke` | "good" | `—` | — |
| `avatar.gestures.tone_map.vulgar` | "shaking" | `—` | — |
| `avatar.llm_gestures` | true | `True` | `anamorf/llm/tools.py` |
| `avatar.web.anims_dir` | "models/avatar/anims" | `'models/avatar/anims'` | `anamorf/anim_hub.py`, `anamorf/main.py` |
| `avatar.web.kind` | "3d" | `—` | `anamorf/avatar_hub.py` |
| `avatar.web.library_dir` | — | `'models/avatar/library'` | `anamorf/avatar_hub.py` |
| `avatar.web.model` | "models/avatar/library/Saika_v1.vrm" | `'models/avatar/model.vrm' / '' ⚠` | `anamorf/avatar_hub.py`, `anamorf/desk_avatar.py`, `anamorf/main.py` |
| `avatar.web.outfits_dir` | "models/avatar/outfits" | `'models/avatar/outfits'` | `anamorf/avatar_hub.py`, `anamorf/main.py` |

### base_model

| ключ | сейчас | по умолчанию | где читается |
|---|---|---|---|
| `base_model` | — | `—` | `anamorf/main.py` |

### batch_size

| ключ | сейчас | по умолчанию | где читается |
|---|---|---|---|
| `batch_size` | — | `2` | `anamorf/main.py` |

### beatbox

| ключ | сейчас | по умолчанию | где читается |
|---|---|---|---|
| `beatbox.enabled` | — | `True` | `anamorf/beatbox.py` |
| `beatbox.floor` | — | `0.006` | `anamorf/beatbox.py` |
| `beatbox.jitter_max` | 0.45 | `0.45` | `anamorf/beatbox.py` |
| `beatbox.kbd_veto` | 0.25 | `0.3` | `anamorf/main.py` |
| `beatbox.max_event_s` | — | `3.0` | `anamorf/beatbox.py` |
| `beatbox.trill_peak` | — | `6.0` | `anamorf/beatbox.py` |

### browser

| ключ | сейчас | по умолчанию | где читается |
|---|---|---|---|
| `browser.ai_query` | — | `True` | `anamorf/browser_hands.py` |
| `browser.ask_after_min` | — | `3` | `anamorf/main.py` |
| `browser.cdp_port` | — | `9222` | `anamorf/browser_hands.py` |
| `browser.channel` | — | `'chrome'` | `anamorf/browser_hands.py` |
| `browser.chrome_profile` | — | `'Default'` | `anamorf/browser_hands.py` |
| `browser.enabled` | — | `True` | `anamorf/llm/tools.py`, `anamorf/main.py` |
| `browser.idle_close_min` | — | `15` | `anamorf/browser_hands.py` |
| `browser.use_system_chrome` | — | `True` | `anamorf/browser_hands.py` |

### compile_mode

| ключ | сейчас | по умолчанию | где читается |
|---|---|---|---|
| `compile_mode` | — | `''` | `anamorf/tts/manager.py` |

### compression_ratio_threshold

| ключ | сейчас | по умолчанию | где читается |
|---|---|---|---|
| `compression_ratio_threshold` | — | `2.2` | `anamorf/stt/engines.py` |

### compute_type

| ключ | сейчас | по умолчанию | где читается |
|---|---|---|---|
| `compute_type` | — | `'auto'` | `anamorf/stt/engines.py` |

### consult

| ключ | сейчас | по умолчанию | где читается |
|---|---|---|---|
| `consult.base_url` | — | `'https://api.moonshot.ai/v1'` | `anamorf/ai_consult.py` |
| `consult.cooldown_s` | — | `180` | `anamorf/ai_consult.py` |
| `consult.enabled` | — | `True` | `anamorf/ai_consult.py` |
| `consult.model` | — | `'kimi-k3'` | `anamorf/ai_consult.py` |

### cortex

| ключ | сейчас | по умолчанию | где читается |
|---|---|---|---|
| `cortex.forget_s` | — | `45` | `anamorf/cortex.py` |

### dataset_dir

| ключ | сейчас | по умолчанию | где читается |
|---|---|---|---|
| `dataset_dir` | — | `'training/dataset'` | `anamorf/main.py` |

### decode_window_frames

| ключ | сейчас | по умолчанию | где читается |
|---|---|---|---|
| `decode_window_frames` | — | `80` | `anamorf/tts/manager.py` |

### denoise

| ключ | сейчас | по умолчанию | где читается |
|---|---|---|---|
| `denoise.dd_alpha` | — | `0.96` | `anamorf/denoise.py` |
| `denoise.engine` | "off" | `'off'` | `anamorf/hear_bench.py` |
| `denoise.floor` | — | `0.08` | `anamorf/denoise.py` |
| `denoise.gate_hold_ms` | — | `220` | `anamorf/denoise.py` |
| `denoise.gate_min` | — | `0.004` | `anamorf/denoise.py` |
| `denoise.gate_ratio` | — | `4.0` | `anamorf/denoise.py` |
| `denoise.min_bias` | — | `2.2` | `anamorf/denoise.py` |
| `denoise.nr_prop` | — | `0.85` | `anamorf/denoise.py` |
| `denoise.nr_stationary` | — | `False` | `anamorf/denoise.py` |
| `denoise.over` | — | `1.8` | `anamorf/denoise.py` |
| `denoise.segment_engine` | — | `'off'` | `anamorf/hear_bench.py`, `anamorf/main.py` |
| `denoise.speech_ratio` | — | `1.8` | `anamorf/denoise.py` |

### device

| ключ | сейчас | по умолчанию | где читается |
|---|---|---|---|
| `device` | — | `'auto'` | `anamorf/stt/engines.py` |

### dialog

| ключ | сейчас | по умолчанию | где читается |
|---|---|---|---|
| `dialog.live_context` | — | `True` | `anamorf/main.py` |
| `dialog.live_context_grace_s` | — | `6` | `anamorf/main.py` |
| `dialog.live_context_min_gap_s` | — | `3.0` | `anamorf/main.py` |

### doctor

| ключ | сейчас | по умолчанию | где читается |
|---|---|---|---|
| `doctor.backend` | "" | `''` | `anamorf/main.py`, `setup/ai_doctor.py` |
| `doctor.model` | "" | `''` | `anamorf/main.py`, `setup/ai_doctor.py` |
| `doctor.startup_ai` | — | `True` | `anamorf/main.py` |
| `doctor.startup_ai_delay_s` | — | `60` | `anamorf/main.py` |

### dreampc

| ключ | сейчас | по умолчанию | где читается |
|---|---|---|---|
| `dreampc` | — | `{}` | `anamorf/llm/dreampc.py` |
| `dreampc.block_length` | 32 | `—` | — |
| `dreampc.gen_length` | 128 | `—` | — |
| `dreampc.model` | "GSAI-ML/LLaDA-8B-Instruct" | `—` | `anamorf/main.py` |
| `dreampc.port` | 8768 | `—` | — |
| `dreampc.quant` | "4bit" | `—` | — |
| `dreampc.setup` | "setup/install_dreampc.bat" | `—` | — |
| `dreampc.steps` | 128 | `—` | — |
| `dreampc.temperature` | 0.0 | `—` | — |
| `dreampc.timeout_s` | 1800 | `—` | — |
| `dreampc.venv` | ".venv_dreampc" | `—` | — |
| `dreampc.worker` | "workers/dreampc_worker.py" | `—` | — |

### earlog

| ключ | сейчас | по умолчанию | где читается |
|---|---|---|---|
| `earlog.max_cluster` | — | `900` | `anamorf/earlog.py` |
| `earlog.sound_thr` | — | `0.45` | `anamorf/earlog.py` |
| `earlog.voice_thr` | — | `0.0` | `anamorf/earlog.py` |

### emit_every_frames

| ключ | сейчас | по умолчанию | где читается |
|---|---|---|---|
| `emit_every_frames` | — | `4` | `anamorf/tts/manager.py` |

### epochs

| ключ | сейчас | по умолчанию | где читается |
|---|---|---|---|
| `epochs` | — | `3` | `anamorf/main.py` |

### files

| ключ | сейчас | по умолчанию | где читается |
|---|---|---|---|
| `files.enabled` | — | `True` | `anamorf/llm/tools.py` |
| `files.roots` | — | `None / ['F:/AI_load_work'] ⚠` | `anamorf/file_hands.py`, `anamorf/main.py` |

### game_watch

| ключ | сейчас | по умолчанию | где читается |
|---|---|---|---|
| `game_watch.cooldown_s` | — | `240` | `anamorf/main.py` |
| `game_watch.enabled` | — | `True` | `anamorf/main.py` |
| `game_watch.titles` | — | `['genshin', 'impact', 'dota', 'cs2', 'cyberpunk', 'witcher', 'elden', 'baldur', 'minecraft', 'wow', 'honkai', 'zenless', 'war thunder', 'stalker']` | `anamorf/main.py` |

### grad_accum

| ключ | сейчас | по умолчанию | где читается |
|---|---|---|---|
| `grad_accum` | — | `4` | `anamorf/main.py` |

### guard

| ключ | сейчас | по умолчанию | где читается |
|---|---|---|---|
| `guard.auto_free_engine` | — | `True` | `anamorf/main.py` |
| `guard.calm_s` | 45 | `45` | `anamorf/triage.py`, `tests/test_triage.py` |
| `guard.period_s` | — | `5` | `anamorf/guard.py` |
| `guard.protect` | — | `True` | `anamorf/guard.py` |
| `guard.step_s` | 12 | `12` | `anamorf/triage.py`, `tests/test_triage.py` |
| `guard.temp_calm` | — | `70` | `anamorf/triage.py` |
| `guard.temp_crit` | — | `90 / 85 ⚠` | `anamorf/guard.py`, `anamorf/triage.py` |
| `guard.temp_warn` | — | `83 / 78 ⚠` | `anamorf/guard.py`, `anamorf/triage.py` |
| `guard.triage` | — | `True` | `anamorf/triage.py` |
| `guard.vram_calm` | — | `0.75` | `anamorf/triage.py` |
| `guard.vram_crit` | — | `0.96 / 0.93 ⚠` | `anamorf/guard.py`, `anamorf/main.py`, `anamorf/triage.py` |
| `guard.vram_warn` | — | `0.9` | `anamorf/guard.py`, `anamorf/triage.py` |

### hands

| ключ | сейчас | по умолчанию | где читается |
|---|---|---|---|
| `hands.confirm_send` | true | `True` | `anamorf/send_gate.py`, `tests/test_send_gate.py` |
| `hands.send_ask_life_s` | — | `120` | `anamorf/send_gate.py` |
| `hands.web_cycle_s` | — | `60` | `anamorf/send_gate.py` |

### heal

| ключ | сейчас | по умолчанию | где читается |
|---|---|---|---|
| `heal.enabled` | — | `True` | `anamorf/self_heal.py` |
| `heal.interval_sec` | — | `90` | `anamorf/self_heal.py` |

### hearing

| ключ | сейчас | по умолчанию | где читается |
|---|---|---|---|
| `hearing.clap.enabled` | — | `True` | `anamorf/clap_ears.py` |
| `hearing.clap.every_s` | — | `2.0` | `anamorf/hearing.py` |
| `hearing.clap.labels` | — | `None` | `anamorf/clap_ears.py` |
| `hearing.clap.min` | — | `0.45` | `anamorf/hearing.py` |
| `hearing.confirm_windows` | 2 | `2` | `anamorf/hearing.py` |
| `hearing.confirm_windows_outdoor` | 3 | `3` | `anamorf/hearing.py` |
| `hearing.device` | "cpu" | `'cpu'` | `anamorf/hearing.py` |
| `hearing.enabled` | — | `True` | `anamorf/hearing.py` |
| `hearing.feed_linger_s` | — | `2.5` | `anamorf/hearing.py` |
| `hearing.feed_min` | — | `0.35` | `anamorf/hearing.py` |
| `hearing.feed_min_outdoor` | 0.55 | `0.55` | `anamorf/hearing.py` |
| `hearing.mech_veto` | — | `0.25` | `anamorf/hearing.py` |
| `hearing.min_conf` | — | `0.12` | `anamorf/hearing.py` |
| `hearing.speech_min` | — | `0.15` | `anamorf/hearing.py` |

### hotkeys

| ключ | сейчас | по умолчанию | где читается |
|---|---|---|---|
| `hotkeys.enabled` | false | `False` | `anamorf/llm/tools.py`, `anamorf/main.py` |

### idle

| ключ | сейчас | по умолчанию | где читается |
|---|---|---|---|
| `idle.allow_self_shutdown` | — | `True` | `anamorf/llm/tools.py`, `anamorf/main.py` |
| `idle.enabled` | — | `True` | `anamorf/main.py` |
| `idle.first_min` | — | `6` | `anamorf/main.py` |
| `idle.goodbye_min` | — | `300` | `anamorf/main.py` |
| `idle.mutter_cooldown_min` | — | `35` | `anamorf/main.py` |
| `idle.mutter_min` | — | `40` | `anamorf/main.py` |
| `idle.second_min` | — | `18` | `anamorf/main.py` |
| `idle.shutdown_delay_s` | — | `25` | `anamorf/llm/tools.py` |

### kill_allowlist

| ключ | сейчас | по умолчанию | где читается |
|---|---|---|---|
| `kill_allowlist` | — | `[]` | `anamorf/messengers.py` |

### kill_denylist

| ключ | сейчас | по умолчанию | где читается |
|---|---|---|---|
| `kill_denylist` | — | `[]` | `anamorf/messengers.py` |

### knobs

| ключ | сейчас | по умолчанию | где читается |
|---|---|---|---|
| `knobs.enabled` | — | `True` | `anamorf/knobs.py` |

### language

| ключ | сейчас | по умолчанию | где читается |
|---|---|---|---|
| `language` | — | `'Russian'` | `anamorf/tts/manager.py` |

### launch_allowlist

| ключ | сейчас | по умолчанию | где читается |
|---|---|---|---|
| `launch_allowlist` | — | `{}` | `anamorf/messengers.py` |

### learning_rate

| ключ | сейчас | по умолчанию | где читается |
|---|---|---|---|
| `learning_rate` | — | `0.0002` | `anamorf/main.py` |

### llamacpp

| ключ | сейчас | по умолчанию | где читается |
|---|---|---|---|
| `llamacpp` | — | `{}` | `anamorf/llm/llamacpp.py`, `anamorf/llm/manager.py`, `anamorf/main.py` |
| `llamacpp.model` | "google/gemma-4-e4b" | `—` | `anamorf/llm/manager.py` |
| `llamacpp.n_ctx` | 24576 | `—` | — |
| `llamacpp.url` | — | `'' / — ⚠` | `anamorf/llm/manager.py` |

### llm

| ключ | сейчас | по умолчанию | где читается |
|---|---|---|---|
| `llm.backend` | "llamacpp" | `'' / — / 'ollama' ⚠` | `anamorf/browser_hands.py`, `anamorf/cards.py`, `anamorf/llm/brains.py` +8 |
| `llm.cache_prompt` | — | `True` | `anamorf/llm/manager.py` |
| `llm.catch_false_claims` | — | `True` | `anamorf/model_dossier.py` |
| `llm.cloud` | — | `{}` | `anamorf/llm/autoconnect.py`, `anamorf/llm/brains.py`, `anamorf/llm/manager.py` +2 |
| `llm.cloud.base_url` | "https://api.mistral.ai/v1" | `'' / — ⚠` | `anamorf/main.py`, `anamorf/model_dossier.py` |
| `llm.cloud.context_chars` | — | `9000` | `anamorf/main.py` |
| `llm.cloud.context_chars_max` | — | `40000` | `anamorf/main.py` |
| `llm.cloud.enabled` | true | `—` | `anamorf/main.py`, `anamorf/llm/manager.py` |
| `llm.cloud.giga_scope` | — | `'GIGACHAT_API_PERS'` | `anamorf/llm/manager.py` |
| `llm.cloud.model` | "mistral-medium-3-5" | `''` | `anamorf/main.py` |
| `llm.cloud.provider` | "mistral" | `'' / 'openrouter' ⚠` | `anamorf/llm/manager.py`, `anamorf/main.py` |
| `llm.cloud_daily_tokens` | — | `0` | `anamorf/usage.py` |
| `llm.cloud_saved` | [{"provider": "cloudflare", "base_url": "… | `[]` | `anamorf/llm/autoconnect.py` |
| `llm.cloudflare_account` | "dc53e2c4a12c1fbde30d66faee5f5706" | `''` | `anamorf/llm/autoconnect.py` |
| `llm.context_chars` | — | `— / 12000 ⚠` | `anamorf/llm/passport.py`, `anamorf/main.py` |
| `llm.context_chars_floor` | — | `2000` | `anamorf/llm/passport.py` |
| `llm.down_retry_s` | — | `60` | `anamorf/llm/manager.py` |
| `llm.escalate_on_fail` | true | `True` | `anamorf/llm/manager.py`, `anamorf/main.py` |
| `llm.fast_context_chars` | 45000 | `12000` | `anamorf/main.py` |
| `llm.fast_memory_chars` | — | `700` | `anamorf/main.py` |
| `llm.fast_mode` | true | `False` | `anamorf/main.py` |
| `llm.hands_local_second` | — | `False` | `anamorf/llm/brains.py` |
| `llm.hands_min_rank` | — | `7` | `anamorf/main.py` |
| `llm.keep_alive` | — | `'30m'` | `anamorf/llm/manager.py` |
| `llm.keep_only_one` | — | `True` | `anamorf/llm/brains.py`, `anamorf/llm/manager.py` |
| `llm.light_max_chars` | — | `48` | `anamorf/main.py` |
| `llm.lmstudio_url` | "http://127.0.0.1:1234" | `'http://127.0.0.1:1234'` | `anamorf/llm/manager.py` |
| `llm.max_gen_seconds` | — | `180` | `anamorf/main.py` |
| `llm.max_history` | 14 | `—` | — |
| `llm.max_tokens_hard` | — | `4000` | `anamorf/main.py` |
| `llm.max_tokens_short` | — | `300` | `anamorf/llm/manager.py` |
| `llm.model` | "google/gemma-4-e4b" | `'' / 'local' / — ⚠` | `anamorf/browser_hands.py`, `anamorf/cards.py`, `anamorf/llm/brains.py` +10 |
| `llm.models_cache_s` | — | `5` | `anamorf/llm/manager.py` |
| `llm.n_ctx` | "32768" | `—` | — |
| `llm.nothink_prefill` | — | `''` | `anamorf/llm/manager.py` |
| `llm.off` | false | `False / — ⚠` | `anamorf/main.py` |
| `llm.ollama_url` | "http://127.0.0.1:11434" | `'http://127.0.0.1:11434'` | `anamorf/llm/manager.py` |
| `llm.paid_ok` | — | `False` | `anamorf/llm/brains.py` |
| `llm.prefer_cheap` | — | `True` | `anamorf/main.py`, `anamorf/model_dossier.py` |
| `llm.prewarm_next` | — | `True` | `anamorf/llm/manager.py` |
| `llm.pricing` | — | `{}` | `anamorf/usage.py` |
| `llm.reasoning_effort` | "none" | `'none'` | `anamorf/llm/manager.py` |
| `llm.router.cloud_score` | — | `2` | `anamorf/llm/router.py` |
| `llm.router.enabled` | true | `False` | `anamorf/llm/manager.py`, `anamorf/llm/router.py` |
| `llm.router.long_chars` | — | `220` | `anamorf/llm/router.py` |
| `llm.sampling` | — | `{}` | `anamorf/llm/manager.py`, `anamorf/main.py` |
| `llm.sampling.dry_allowed_length` | 2 | `—` | — |
| `llm.sampling.dry_base` | 1.75 | `—` | — |
| `llm.sampling.dry_multiplier` | 0.0 | `—` | — |
| `llm.sampling.dynatemp_exponent` | 1.0 | `—` | — |
| `llm.sampling.dynatemp_range` | 0.0 | `—` | — |
| `llm.sampling.enabled` | false | `—` | — |
| `llm.sampling.frequency_penalty` | 0.0 | `—` | — |
| `llm.sampling.min_p` | 0.05 | `—` | — |
| `llm.sampling.presence_penalty` | 0.0 | `—` | — |
| `llm.sampling.preset` | "off" | `—` | — |
| `llm.sampling.repeat_penalty` | 1.0 | `—` | — |
| `llm.sampling.seed` | -1 | `—` | — |
| `llm.sampling.stop` | [] | `—` | — |
| `llm.sampling.top_k` | 40 | `—` | — |
| `llm.sampling.top_p` | 0.95 | `—` | — |
| `llm.sampling.typical_p` | 1.0 | `—` | — |
| `llm.sampling.xtc_probability` | 0.0 | `—` | — |
| `llm.sampling.xtc_threshold` | 0.1 | `—` | — |
| `llm.search_unreliable` | ["@cf/qwen/qwen3-30b-a3b-fp8", "google/ge… | `[]` | `anamorf/main.py` |
| `llm.slow_s` | — | `15` | `anamorf/llm/brains.py` |
| `llm.target_response_s` | — | `0` | `anamorf/llm/manager.py` |
| `llm.temperature` | 0.8 | `0.8` | `anamorf/llm/manager.py` |
| `llm.think` | false | `False` | `anamorf/llm/manager.py`, `anamorf/main.py` |
| `llm.tools_broken` | ["@cf/meta/llama-3.3-70b-instruct-fp8-fas… | `[]` | `anamorf/capabilities.py`, `anamorf/llm/manager.py`, `anamorf/llm/passport.py` +4 |
| `llm.trust_liars` | — | `False` | `anamorf/capabilities.py` |
| `llm.two_local_ok` | false | `False` | `anamorf/llm/one_local.py`, `tests/test_one_local.py` |

### lmstudio

| ключ | сейчас | по умолчанию | где читается |
|---|---|---|---|
| `lmstudio.cli` | — | `''` | `anamorf/llm/manager.py` |

### locallm

| ключ | сейчас | по умолчанию | где читается |
|---|---|---|---|
| `locallm` | — | `{}` | `anamorf/llm/locallm.py`, `setup/install_locallm.py` |
| `locallm.engine` | "llamacpp" | `—` | — |
| `locallm.max_new_tokens` | 2048 | `—` | — |
| `locallm.model` | "t-tech/T-lite-it-2.1" | `—` | — |
| `locallm.port` | 8770 | `—` | — |
| `locallm.venv` | ".venv_locallm" | `—` | — |
| `locallm.worker` | "workers/locallm_worker.py" | `—` | — |

### locallm_gguf

| ключ | сейчас | по умолчанию | где читается |
|---|---|---|---|
| `locallm_gguf` | — | `— / {} ⚠` | `anamorf/llm/llamacpp.py`, `anamorf/llm/locallm.py`, `anamorf/main.py` +1 |
| `locallm_gguf.kv_quant` | "q8_0" | `—` | — |
| `locallm_gguf.n_ctx` | 32768 | `—` | — |
| `locallm_gguf.quant` | "Q4_K_M" | `—` | — |
| `locallm_gguf.repo` | "t-tech/T-lite-it-2.1-GGUF" | `—` | — |

### log_prob_threshold

| ключ | сейчас | по умолчанию | где читается |
|---|---|---|---|
| `log_prob_threshold` | — | `-0.8` | `anamorf/stt/engines.py` |

### lora_alpha

| ключ | сейчас | по умолчанию | где читается |
|---|---|---|---|
| `lora_alpha` | — | `16` | `anamorf/main.py` |

### lora_dropout

| ключ | сейчас | по умолчанию | где читается |
|---|---|---|---|
| `lora_dropout` | — | `0.0` | `anamorf/main.py` |

### lora_r

| ключ | сейчас | по умолчанию | где читается |
|---|---|---|---|
| `lora_r` | — | `16` | `anamorf/main.py` |

### lore

| ключ | сейчас | по умолчанию | где читается |
|---|---|---|---|
| `lore.depth` | 4 | `4` | `anamorf/lorebook.py` |
| `lore.max_entries` | 6 | `6` | `anamorf/lorebook.py` |
| `lore.path` | "data/lorebook.json" | `'data/lorebook.json'` | `anamorf/lorebook.py` |

### mask_id

| ключ | сейчас | по умолчанию | где читается |
|---|---|---|---|
| `mask_id` | — | `0` | `anamorf/llm/dreampc.py` |

### max_seq_len

| ключ | сейчас | по умолчанию | где читается |
|---|---|---|---|
| `max_seq_len` | — | `1024` | `anamorf/main.py`, `workers/train_worker.py` |

### memory

| ключ | сейчас | по умолчанию | где читается |
|---|---|---|---|
| `memory.chroma_path` | "data/chroma" | `—` | `anamorf/memory/memory.py` |
| `memory.compress_raw_every_min` | 30 | `30` | `anamorf/memory/memory.py` |
| `memory.context_chars` | 3000 | `3000` | `anamorf/main.py`, `anamorf/memory/memory.py` |
| `memory.core_update_every_days` | 7 | `7` | `anamorf/memory/memory.py` |
| `memory.day_cache_s` | — | `900` | `anamorf/memory/memory.py` |
| `memory.day_chars` | — | `700` | `anamorf/memory/memory.py` |
| `memory.db_path` | "data/saika_memory.db" | `—` | `anamorf/memory/memory.py` |
| `memory.episode_hard_cap` | 10000 | `10000` | `anamorf/memory/memory.py` |
| `memory.rag_top_k` | 5 | `5` | `anamorf/memory/memory.py` |
| `memory.raw_limit_hours` | 4 | `4` | `anamorf/memory/memory.py` |
| `memory.raw_limit_messages` | 4000 | `4000` | `anamorf/memory/memory.py` |
| `memory.regular_min_messages` | 30 | `30` | `anamorf/memory/memory.py` |
| `memory.regular_min_sessions` | 3 | `3` | `anamorf/memory/memory.py` |
| `memory.self_tools` | — | `True` | `anamorf/llm/tools.py` |
| `memory.stranger_ttl_days` | 30 | `30` | `anamorf/memory/memory.py` |
| `memory.tools` | — | `True` | `anamorf/llm/tools.py` |

### messengers

| ключ | сейчас | по умолчанию | где читается |
|---|---|---|---|
| `messengers` | — | `{}` | `anamorf/messengers.py` |
| `messengers.aliases.vpn` | ["happ", "amnezia"] | `—` | — |
| `messengers.aliases.амнезия` | "amnezia" | `—` | — |
| `messengers.aliases.впн` | ["happ", "amnezia"] | `—` | — |
| `messengers.aliases.хапп` | "happ" | `—` | — |
| `messengers.control_enabled` | false | `False` | `anamorf/main.py`, `anamorf/messengers.py` |
| `messengers.kill_allowlist` | [] | `—` | — |
| `messengers.kill_denylist` | [] | `—` | — |
| `messengers.owner_ids.telegram` | [] | `—` | — |
| `messengers.owner_ids.vk` | [] | `—` | — |
| `messengers.pc_name` | "домашний-ПК" | `—` | — |
| `messengers.reply_timeout_s` | — | `180` | `anamorf/messengers.py` |
| `messengers.speak_aloud` | — | `False` | `anamorf/messengers.py` |
| `messengers.telegram.enabled` | false | `—` | — |
| `messengers.telegram.token` | "" | `—` | — |
| `messengers.vk.enabled` | false | `—` | — |
| `messengers.vk.group_id` | "" | `—` | — |
| `messengers.vk.token` | "" | `—` | — |

### mic

| ключ | сейчас | по умолчанию | где читается |
|---|---|---|---|
| `mic.device` | null | `—` | — |
| `mic.server_capture` | true | `False` | `anamorf/main.py` |

### model

| ключ | сейчас | по умолчанию | где читается |
|---|---|---|---|
| `model` | — | `'GSAI-ML/LLaDA-8B-Instruct' / 'medium' / 'large-v3-turbo' ⚠` | `anamorf/llm/dreampc.py`, `anamorf/stt/engines.py`, `anamorf/tts/manager.py` |

### n_threads

| ключ | сейчас | по умолчанию | где читается |
|---|---|---|---|
| `n_threads` | — | `8` | `anamorf/stt/engines.py` |

### net

| ключ | сейчас | по умолчанию | где читается |
|---|---|---|---|
| `net.bypass` | — | `{}` | `anamorf/netpolicy.py` |

### no_speech_threshold

| ключ | сейчас | по умолчанию | где читается |
|---|---|---|---|
| `no_speech_threshold` | — | `0.5` | `anamorf/stt/engines.py` |

### optimize

| ключ | сейчас | по умолчанию | где читается |
|---|---|---|---|
| `optimize` | — | `True` | `anamorf/tts/manager.py` |

### output_name

| ключ | сейчас | по умолчанию | где читается |
|---|---|---|---|
| `output_name` | — | `'saika-char'` | `anamorf/main.py` |

### owner

| ключ | сейчас | по умолчанию | где читается |
|---|---|---|---|
| `owner` | — | `{'name': 'Owner', 'id': 'owner'}` | `anamorf/memory/memory.py` |
| `owner.gender` | — | `'m'` | `anamorf/main.py` |
| `owner.guest_sim` | — | `0.45` | `anamorf/main.py` |
| `owner.id` | "owner" | `'owner'` | `anamorf/main.py`, `anamorf/self_memory.py` |
| `owner.min_conf` | — | `0.55` | `anamorf/main.py` |
| `owner.name` | "Anamorf" | `'Owner' / '' ⚠` | `anamorf/main.py` |
| `owner.only_owner` | — | `True` | `anamorf/main.py` |

### pc

| ключ | сейчас | по умолчанию | где читается |
|---|---|---|---|
| `pc.blocked_apps` | — | `[]` | `anamorf/pc_control.py` |
| `pc.enabled` | — | `True` | `anamorf/llm/tools.py`, `anamorf/main.py`, `anamorf/trust.py` |
| `pc.extra_scan_dirs` | — | `[]` | `anamorf/pc_control.py` |
| `pc.find_timeout_s` | — | `4.0` | `anamorf/pc_control.py` |
| `pc.highlight` | — | `True` | `anamorf/highlight.py` |
| `pc.highlight_color` | "#02a9ac" | `'#ff9a3c'` | `anamorf/highlight.py` |
| `pc.highlight_glow` | — | `'<выражение>'` | `anamorf/highlight.py` |
| `pc.highlight_ms` | — | `30000` | `anamorf/highlight.py` |
| `pc.index_ttl_h` | — | `24` | `anamorf/pc_control.py` |
| `pc.open_any_folder` | — | `True` | `anamorf/main.py`, `anamorf/pc_control.py` |
| `pc.scan_timeout_s` | — | `8.0` | `anamorf/explorer.py` |
| `pc.self_ui` | — | `True` | `anamorf/llm/tools.py`, `anamorf/main.py` |

### pc_name

| ключ | сейчас | по умолчанию | где читается |
|---|---|---|---|
| `pc_name` | — | `'этот ПК'` | `anamorf/messengers.py` |

### persona

| ключ | сейчас | по умолчанию | где читается |
|---|---|---|---|
| `persona.author_notes` | — | `''` | `anamorf/main.py` |

### port

| ключ | сейчас | по умолчанию | где читается |
|---|---|---|---|
| `port` | — | `8768 / 8769 ⚠` | `anamorf/llm/dreampc.py`, `anamorf/llm/train_manager.py` |

### prompt

| ключ | сейчас | по умолчанию | где читается |
|---|---|---|---|
| `prompt.order` | ["lore", "memory", "search", "devboard", … | `None` | `anamorf/prompt_blocks.py` |

### psyche

| ключ | сейчас | по умолчанию | где читается |
|---|---|---|---|
| `psyche.calm_minutes` | — | `12` | `anamorf/psyche.py` |
| `psyche.enabled` | — | `True` | `anamorf/psyche.py` |
| `psyche.give_up_after` | — | `3` | `anamorf/psyche.py` |
| `psyche.sensitivity` | — | `1.0` | `anamorf/psyche.py` |
| `psyche.temperament.a` | — | `0.05` | `anamorf/psyche.py` |
| `psyche.temperament.d` | — | `0.15` | `anamorf/psyche.py` |
| `psyche.temperament.p` | — | `0.25` | `anamorf/psyche.py` |

### quant

| ключ | сейчас | по умолчанию | где читается |
|---|---|---|---|
| `quant` | — | `'q4_k_m'` | `workers/train_worker.py` |

### recipes

| ключ | сейчас | по умолчанию | где читается |
|---|---|---|---|
| `recipes.enabled` | — | `True` | `anamorf/recipes.py` |
| `recipes.match` | — | `0.72` | `anamorf/recipes.py` |

### reflex

| ключ | сейчас | по умолчанию | где читается |
|---|---|---|---|
| `reflex.enabled` | — | `True` | `anamorf/reflex.py` |
| `reflex.extra` | — | `[]` | `anamorf/reflex.py` |
| `reflex.volume_step` | — | `10` | `anamorf/reflex.py` |

### sample_rate

| ключ | сейчас | по умолчанию | где читается |
|---|---|---|---|
| `sample_rate` | — | `48000` | `anamorf/tts/manager.py` |

### selfread

| ключ | сейчас | по умолчанию | где читается |
|---|---|---|---|
| `selfread.enabled` | — | `True` | `anamorf/llm/tools.py` |
| `selfread.extra_roots` | — | `[]` | `anamorf/self_read.py` |

### server

| ключ | сейчас | по умолчанию | где читается |
|---|---|---|---|
| `server` | — | `—` | `tools/desk_avatar.py` |
| `server.auto_open_browser` | true | `True` | `anamorf/main.py` |
| `server.host` | "0.0.0.0" | `'127.0.0.1'` | `anamorf/main.py` |
| `server.https` | — | `False` | `anamorf/phone.py` |
| `server.port` | 8765 | `8765` | `anamorf/main.py`, `anamorf/phone.py` |
| `server.token` | "DRbZ5FaL" | `—` | — |

### services

| ключ | сейчас | по умолчанию | где читается |
|---|---|---|---|
| `services.app_wait_s` | — | `2.0` | `anamorf/services.py` |
| `services.ask_life_s` | — | `180` | `anamorf/services.py` |

### situation

| ключ | сейчас | по умолчанию | где читается |
|---|---|---|---|
| `situation.enabled` | — | `True` | `anamorf/situation.py` |

### skills

| ключ | сейчас | по умолчанию | где читается |
|---|---|---|---|
| `skills.block` | — | `True` | `anamorf/llm/skills.py` |

### soundmap

| ключ | сейчас | по умолчанию | где читается |
|---|---|---|---|
| `soundmap.cos` | — | `0.6` | `anamorf/sound_map.py` |
| `soundmap.enabled` | — | `True` | `anamorf/sound_map.py` |
| `soundmap.speech_veto` | — | `0.35` | `anamorf/sound_map.py` |

### speaker

| ключ | сейчас | по умолчанию | где читается |
|---|---|---|---|
| `speaker` | — | `''` | `anamorf/tts/manager.py` |

### stt

| ключ | сейчас | по умолчанию | где читается |
|---|---|---|---|
| `stt.bench` | true | `False` | `anamorf/hear_bench.py` |
| `stt.bench_keep` | — | `300` | `anamorf/hear_bench.py` |
| `stt.bench_report_n` | — | `40` | `anamorf/main.py` |
| `stt.draft` | true | `True` | `anamorf/draft.py` |
| `stt.echo_guard` | — | `True` | `anamorf/main.py` |
| `stt.echo_tail_s` | — | `0.9` | `anamorf/main.py` |
| `stt.engine` | "gigaam" | `'' / 'off' / 'gigaam' ⚠` | `anamorf/main.py`, `anamorf/self_control.py`, `anamorf/stt/manager.py` +2 |
| `stt.engine_was` | "gigaam" | `''` | `anamorf/triage.py`, `setup/doctor.py` |
| `stt.engines.faster_whisper` | — | `{}` | `anamorf/stt/engines.py` |
| `stt.engines.faster_whisper.compute_type` | "auto" | `—` | — |
| `stt.engines.faster_whisper.device` | "auto" | `—` | — |
| `stt.engines.faster_whisper.model` | "large-v3-turbo" | `—` | — |
| `stt.engines.gigaam.model` | "v3_e2e_rnnt" | `'v3_e2e_rnnt'` | `anamorf/stt/engines.py` |
| `stt.engines.groq_whisper` | — | `{}` | `anamorf/stt/engines.py` |
| `stt.engines.vosk.model_dir` | "models/vosk-model-small-ru-0.22" | `—` | `anamorf/draft.py`, `anamorf/stt/engines.py` |
| `stt.engines.voxtral.model` | "mistralai/Voxtral-Mini-4B-Realtime-2602" | `—` | — |
| `stt.engines.voxtral.port` | 8766 | `—` | — |
| `stt.engines.voxtral.setup` | "setup/install_voxtral.bat" | `—` | — |
| `stt.engines.voxtral.timeout_s` | 45 | `—` | — |
| `stt.engines.voxtral.venv` | ".venv_voxtral" | `—` | — |
| `stt.engines.voxtral.worker` | "workers/voxtral_worker.py" | `—` | — |
| `stt.engines.whispercpp` | — | `{}` | `anamorf/stt/engines.py` |
| `stt.engines.whispercpp.model` | "medium" | `—` | — |
| `stt.engines.whispercpp.n_threads` | 8 | `—` | — |
| `stt.fallback_order` | ["faster_whisper", "gigaam", "vosk", "ton… | `[] / '<выражение>' ⚠` | `anamorf/main.py`, `anamorf/stt/manager.py`, `setup/doctor.py` |
| `stt.frontend` | — | `{}` | `anamorf/main.py` |
| `stt.frontend.comp_ratio` | 2.0 | `—` | — |
| `stt.frontend.comp_thr_db` | -24 | `—` | — |
| `stt.frontend.enabled` | true | `—` | — |
| `stt.frontend.hp_hz` | 70 | `—` | — |
| `stt.frontend.max_gain_db` | 30 | `—` | — |
| `stt.frontend.pad_ms` | 100 | `—` | — |
| `stt.frontend.target_dbfs` | -20 | `—` | — |
| `stt.join_dup_words` | — | `4` | `anamorf/main.py` |
| `stt.junk_phrases` | — | `[]` | `anamorf/stt/manager.py` |
| `stt.language` | "ru" | `'ru'` | `anamorf/stt/engines.py` |
| `stt.live_polish` | true | `True` | `anamorf/main.py` |
| `stt.music_phantom_dbfs` | — | `-40.0` | `anamorf/main.py` |
| `stt.phantom_max_s` | 1.2 | `1.6` | `anamorf/main.py` |
| `stt.phantom_mech_min` | 0.35 | `0.3` | `anamorf/main.py` |
| `stt.polish_every_s` | 0.5 | `0.55` | `anamorf/main.py` |
| `stt.polish_grow_s` | — | `0.2` | `anamorf/main.py` |
| `stt.q_starve` | — | `25` | `anamorf/main.py` |
| `stt.repair` | — | `True` | `anamorf/misheard.py` |
| `stt.repair_fuzzy` | — | `False` | `anamorf/misheard.py` |
| `stt.rescore.enabled` | true | `True` | `anamorf/stt/rescore.py` |
| `stt.rescore.max_edit` | 0.3 | `0.3` | `anamorf/stt/rescore.py` |
| `stt.rescore.max_grow` | 1.25 | `1.25` | `anamorf/stt/rescore.py` |
| `stt.rescore.max_sound_edit` | 0.22 | `0.34` | `anamorf/stt/rescore.py` |
| `stt.rescore.min_gap_s` | — | `2.0` | `anamorf/stt/rescore.py` |
| `stt.rescore.min_len` | 18 | `18` | `anamorf/stt/rescore.py` |
| `stt.rescore.quiet_dbfs` | -34 | `-34.0` | `anamorf/stt/rescore.py` |
| `stt.sample_rate` | 16000 | `16000` | `anamorf/draft.py`, `anamorf/main.py`, `anamorf/stt/engines.py` +1 |
| `stt.shaky_mark` | — | `True` | `anamorf/misheard.py` |
| `stt.shaky_rms` | — | `0.006` | `anamorf/misheard.py` |
| `stt.shaky_words_per_s` | — | `4.5` | `anamorf/misheard.py` |
| `stt.snap_expected` | — | `True` | `anamorf/misheard.py` |
| `stt.snap_max_rel` | — | `0.42` | `anamorf/misheard.py` |
| `stt.snap_window_s` | — | `60` | `anamorf/main.py` |
| `stt.stale_keep_q` | 3 | `3` | `anamorf/main.py` |
| `stt.stale_s` | 10 | `12` | `anamorf/main.py` |
| `stt.stretch` | — | `True` | `anamorf/misheard.py` |
| `stt.stretch_max` | 6 | `10` | `anamorf/misheard.py` |
| `stt.stretch_step_s` | 0.28 | `0.12` | `anamorf/misheard.py` |
| `stt.turns` | — | `True` | `anamorf/stt/turns.py` |
| `stt.turns_cos` | — | `0.35` | `anamorf/stt/turns.py` |
| `stt.turns_dna_cos` | 0.82 | `0.82` | `anamorf/stt/turns.py` |
| `stt.turns_dna_hop_s` | 0.15 | `0.15` | `anamorf/stt/turns.py` |
| `stt.turns_dna_win_s` | 0.5 | `0.5` | `anamorf/stt/turns.py` |
| `stt.turns_min_part_hard_s` | 0.8 | `0.8` | `anamorf/stt/turns.py` |
| `stt.turns_min_part_s` | 1.5 | `'<выражение>'` | `anamorf/stt/turns.py` |
| `stt.turns_min_s` | — | `2.5` | `anamorf/stt/turns.py` |
| `stt.turns_overlap_ms` | 120 | `120` | `anamorf/stt/turns.py` |
| `stt.turns_pitch_jump` | 0.16 | `0.16` | `anamorf/stt/turns.py` |
| `stt.unmix.device` | — | `'cuda'` | `anamorf/stt/unmix.py` |
| `stt.unmix.enabled` | — | `True` | `anamorf/stt/unmix.py` |
| `stt.unmix.max_s` | — | `10.0` | `anamorf/stt/unmix.py` |
| `stt.unmix.min_s` | — | `0.8` | `anamorf/stt/unmix.py` |
| `stt.unmix.model` | — | `'speechbrain/sepformer-whamr16k'` | `anamorf/stt/unmix.py` |
| `stt.unmix.track_min_rms` | — | `0.012` | `anamorf/stt/unmix.py` |
| `stt.unmix.warm_wait_max_s` | — | `600` | `anamorf/stt/unmix.py` |
| `stt.vad` | — | `{}` | `anamorf/main.py`, `anamorf/stt/manager.py` |
| `stt.vad.engine` | — | `'silero'` | `anamorf/stt/neuro_vad.py` |
| `stt.vad.max_segment_s` | 8 | `—` | — |
| `stt.vad.min_speech_ms` | 420 | `—` | — |
| `stt.vad.neuro_gate_rms` | 0.002 | `0.0025` | `anamorf/stt/manager.py` |
| `stt.vad.neuro_off` | 0.28 | `0.35` | `anamorf/stt/manager.py` |
| `stt.vad.neuro_on` | 0.42 | `0.5` | `anamorf/stt/manager.py` |
| `stt.vad.observe_max_segment_s` | 8 | `—` | — |
| `stt.vad.observe_silence_ms` | 600 | `—` | — |
| `stt.vad.preroll_ms` | 400 | `—` | — |
| `stt.vad.rms_threshold` | 0.006 | `0.012` | `anamorf/voiceprint/__init__.py` |
| `stt.vad.silence_ms` | 600 | `—` | — |
| `stt.vad.soft_cut_from` | 0.45 | `0.5` | `anamorf/stt/manager.py` |
| `stt.vad.soft_gap_ms` | 100 | `100` | `anamorf/stt/manager.py` |
| `stt.vocab` | — | `[]` | `anamorf/misheard.py` |

### tools

| ключ | сейчас | по умолчанию | где читается |
|---|---|---|---|
| `tools.browser_model` | "qwen3.6:latest" | `'qwen3.6:latest' / — ⚠` | `anamorf/llm/tools.py`, `anamorf/main.py` |
| `tools.browser_timeout_s` | — | `420` | `anamorf/llm/tools.py` |
| `tools.cache_s` | — | `20` | `anamorf/llm/tools.py` |
| `tools.devboard_tools` | — | `False` | `anamorf/llm/tools.py` |
| `tools.enabled` | true | `True` | `anamorf/llm/tools.py`, `anamorf/main.py` |
| `tools.grade` | — | `'auto'` | `anamorf/llm/tools.py` |
| `tools.handspc_url` | "http://127.0.0.1:8767" | `'http://127.0.0.1:8767'` | `anamorf/llm/tools.py`, `anamorf/main.py` |
| `tools.max_chars` | — | `12000` | `anamorf/llm/tools.py` |
| `tools.max_result_chars` | — | `2500 / 3000 ⚠` | `anamorf/llm/manager.py`, `anamorf/llm/tools.py` |
| `tools.max_rounds` | 3 | `3` | `anamorf/llm/manager.py` |
| `tools.max_tool_seconds` | — | `150` | `anamorf/llm/manager.py` |
| `tools.repeat_max` | — | `3` | `anamorf/llm/tools.py` |
| `tools.repeat_window_s` | — | `90` | `anamorf/llm/tools.py` |
| `tools.timeout_s` | 60 | `60` | `anamorf/llm/tools.py` |
| `tools.trim` | — | `True` | `anamorf/llm/tools.py` |
| `tools.workshop` | — | `True` | `anamorf/llm/tools.py` |
| `tools.workshop_dir` | — | `'workshop'` | `anamorf/llm/tools.py` |

### training

| ключ | сейчас | по умолчанию | где читается |
|---|---|---|---|
| `training` | — | `{}` | `anamorf/llm/train_manager.py`, `anamorf/main.py` |
| `training.base_model` | "unsloth/gemma-3n-E4B-it" | `—` | `anamorf/main.py` |
| `training.batch_size` | 2 | `—` | — |
| `training.dataset_dir` | "training/dataset" | `'training/dataset'` | `anamorf/dataset_hub.py` |
| `training.epochs` | 3 | `—` | — |
| `training.grad_accum` | 4 | `—` | — |
| `training.learning_rate` | 0.0002 | `—` | — |
| `training.lora_alpha` | 16 | `—` | — |
| `training.lora_dropout` | 0.0 | `—` | — |
| `training.lora_r` | 16 | `—` | — |
| `training.max_seq_len` | 1024 | `—` | — |
| `training.output_name` | "saika-char" | `—` | — |
| `training.port` | 8769 | `—` | — |
| `training.setup` | "setup/install_train.bat" | `—` | — |
| `training.venv` | ".venv_train" | `—` | — |
| `training.worker` | "workers/train_worker.py" | `—` | — |

### transcript

| ключ | сейчас | по умолчанию | где читается |
|---|---|---|---|
| `transcript.max_chars` | — | `320` | `anamorf/transcript.py` |
| `transcript.punctuate` | — | `True` | `anamorf/transcript.py` |

### trust

| ключ | сейчас | по умолчанию | где читается |
|---|---|---|---|
| `trust.level` | 7 | `5` | `anamorf/trust.py` |

### tts

| ключ | сейчас | по умолчанию | где читается |
|---|---|---|---|
| `tts` | — | `{}` | `anamorf/tts/manager.py` |
| `tts._hidden_note` | "xtts и f5ru требуют СВОЕГО venv: coqui-t… | `—` | — |
| `tts.boot_stub` | — | `False` | `anamorf/main.py` |
| `tts.disabled` | [] | `[]` | `anamorf/tts/manager.py` |
| `tts.edge.voice` | "ru-RU-SvetlanaNeural" | `'' / 'ru-RU-SvetlanaNeural' ⚠` | `anamorf/main.py`, `anamorf/tts/manager.py` |
| `tts.emotion` | true | `True` | `anamorf/tts/manager.py` |
| `tts.emotion_instruct` | "" | `''` | `anamorf/tts/manager.py` |
| `tts.enabled` | true | `True` | `anamorf/main.py`, `anamorf/tts/manager.py` |
| `tts.engine` | "qwen3" | `'' / — / 'qwen3' ⚠` | `anamorf/cards.py`, `anamorf/main.py`, `anamorf/self_control.py` +3 |
| `tts.f5ru.port` | 8771 | `8771` | `anamorf/tts/extra.py` |
| `tts.f5ru.setup` | "setup/install_f5.bat" | `—` | — |
| `tts.f5ru.venv` | ".venv_f5" | `—` | — |
| `tts.fallback_order` | ["qwen3", "piper", "silero", "edge"] | `[] / ['silero', 'edge'] ⚠` | `anamorf/main.py`, `anamorf/tts/manager.py`, `setup/doctor.py` |
| `tts.favorites` | — | `[]` | `setup/doctor.py` |
| `tts.headphones` | — | `False` | `anamorf/main.py` |
| `tts.hidden` | ["xtts", "f5ru"] | `[]` | `anamorf/tts/manager.py` |
| `tts.omni` | — | `{}` | `anamorf/tts/extra.py` |
| `tts.omni.language` | "ru" | `—` | — |
| `tts.omni.model` | "k2-fsa/OmniVoice" | `—` | — |
| `tts.omni.port` | 8772 | `—` | — |
| `tts.omni.setup` | "setup/install_omnivoice.bat" | `—` | — |
| `tts.omni.steps` | 16 | `—` | — |
| `tts.omni.timeout_s` | 120 | `—` | — |
| `tts.omni.venv` | ".venv_omni" | `—` | — |
| `tts.omni.worker` | "workers/omnivoice_worker.py" | `—` | — |
| `tts.out_latency` | — | `'high'` | `anamorf/main.py` |
| `tts.output_device` | "CABLE Input" | `—` | — |
| `tts.output_device_dup` | "WH-1000XM4" | `—` | `anamorf/main.py` |
| `tts.piper.voice` | "irina" | `'' / 'irina' ⚠` | `anamorf/main.py`, `anamorf/tts/extra.py` |
| `tts.pitch` | — | `0.0` | `anamorf/tts/shape.py` |
| `tts.preview_text` | — | `—` | `anamorf/tts/manager.py` |
| `tts.qwen3` | — | `{}` | `anamorf/tts/manager.py` |
| `tts.qwen3.attn` | "auto" | `—` | — |
| `tts.qwen3.compile_mode` | "default" | `—` | — |
| `tts.qwen3.decode_window_frames` | 80 | `—` | — |
| `tts.qwen3.emit_every_frames` | 4 | `—` | — |
| `tts.qwen3.language` | "Russian" | `—` | — |
| `tts.qwen3.model` | "Qwen/Qwen3-TTS-12Hz-1.7B-Base" | `—` | — |
| `tts.qwen3.optimize` | true | `—` | — |
| `tts.qwen3.warm_quiet_s` | — | `6` | `anamorf/main.py` |
| `tts.server_playback` | — | `True` | `anamorf/main.py` |
| `tts.server_volume` | — | `0.8` | `anamorf/main.py` |
| `tts.sick_hours` | — | `6.0` | `anamorf/tts/manager.py` |
| `tts.silero` | — | `{}` | `anamorf/tts/manager.py` |
| `tts.silero._note` | "v5_cis_base — MIT. Прежний v4_ru под CC-… | `—` | — |
| `tts.silero.model` | "v5_cis_base" | `—` | — |
| `tts.silero.model_reinstall` | "true" | `—` | — |
| `tts.silero.sample_rate` | 48000 | `—` | — |
| `tts.silero.speaker` | "" | `''` | `anamorf/main.py` |
| `tts.speed` | null | `1.0` | `anamorf/tts/shape.py` |
| `tts.tone` | null | `''` | `anamorf/main.py`, `anamorf/tts/manager.py` |
| `tts.voice_ref` | "voice/ref.wav" | `'voice/ref.mp3' / — ⚠` | `anamorf/tts/extra.py`, `setup/first_run.py` |
| `tts.voice_ref_text` | "Я проснулась раньше будильника, когда ко… | `'' / — ⚠` | `anamorf/tts/extra.py`, `anamorf/tts/manager.py`, `setup/doctor.py` +1 |
| `tts.voice_ref_wav` | "voice/ref.wav" | `— / '' / 'voice/ref.wav' ⚠` | `anamorf/main.py`, `anamorf/tts/extra.py`, `anamorf/tts/manager.py` +2 |
| `tts.xtts.language` | "ru" | `'ru'` | `anamorf/tts/extra.py` |
| `tts.xtts.sample_rate` | 24000 | `24000` | `anamorf/tts/extra.py` |

### vision

| ключ | сейчас | по умолчанию | где читается |
|---|---|---|---|
| `vision.auto_off_min` | — | `15` | `anamorf/main.py` |
| `vision.boot_engine_free_gb` | — | `7.0` | `anamorf/vision.py` |
| `vision.borrow_budget_s` | — | `12.0` | `anamorf/main.py` |
| `vision.camera_autofallback` | true | `True` | `anamorf/vision.py` |
| `vision.camera_h` | 720 | `720` | `anamorf/vision.py` |
| `vision.camera_idle_release_s` | 60 | `60` | `anamorf/vision.py` |
| `vision.camera_index` | 0 | `0` | `anamorf/vision.py` |
| `vision.camera_probe` | 4 | `4` | `anamorf/vision.py` |
| `vision.camera_w` | 1280 | `1280` | `anamorf/vision.py` |
| `vision.debounce` | 2 | `2` | `anamorf/vision.py` |
| `vision.default_source` | "screen" | `'screen'` | `anamorf/vision.py` |
| `vision.enabled` | true | `True` | `anamorf/vision.py` |
| `vision.impulse_cooldown_s` | 120 | `120` | `anamorf/main.py` |
| `vision.jpeg_quality` | 80 | `80` | `anamorf/vision.py` |
| `vision.max_side` | 1280 | `1280` | `anamorf/vision.py` |
| `vision.min_interval_s` | 45 | `45` | `anamorf/vision.py` |
| `vision.monitor` | 0 | `0` | `anamorf/vision.py` |
| `vision.preview_fps` | 10 | `10` | `anamorf/vision.py` |
| `vision.preview_max_s` | 600 | `600` | `anamorf/vision.py` |
| `vision.scene_threshold` | 6 | `6` | `anamorf/vision.py` |
| `vision.screen_order` | ["dxcam", "dxcam_winrt", "windows_capture… | `'<выражение>'` | `anamorf/vision.py` |
| `vision.swap_rb` | false | `False` | `anamorf/vision.py` |
| `vision.tools` | true | `—` | — |
| `vision.watch_hz` | 2 | `2` | `anamorf/vision.py` |
| `vision.watch_source` | "screen" | `'screen'` | `anamorf/vision.py` |
| `vision.watch_speaks` | true | `True` | `anamorf/main.py` |
| `vision.window_blocklist` | [] | `[]` | `anamorf/vision.py` |

### voiceprint

| ключ | сейчас | по умолчанию | где читается |
|---|---|---|---|
| `voiceprint.auto_meet` | — | `True` | `anamorf/voiceprint/__init__.py` |
| `voiceprint.auto_meet_n` | — | `22` | `anamorf/voiceprint/__init__.py` |
| `voiceprint.device` | "auto" | `'auto'` | `anamorf/voiceprint/encoder.py` |
| `voiceprint.dna_cos` | 0.9 | `0.86` | `anamorf/main.py` |
| `voiceprint.emit_ms` | — | `320` | `anamorf/voiceprint/__init__.py` |
| `voiceprint.enabled` | true | `True` | `anamorf/voiceprint/__init__.py` |
| `voiceprint.encoder` | — | `'auto'` | `anamorf/voiceprint/encoder.py` |
| `voiceprint.group_new_min_s` | — | `1.2` | `anamorf/main.py` |
| `voiceprint.learn_names` | — | `True` | `anamorf/voiceprint/__init__.py` |
| `voiceprint.listen_self` | true | `True` | `anamorf/voiceprint/__init__.py` |
| `voiceprint.name_weight` | — | `6.0` | `anamorf/voiceprint/registry.py` |
| `voiceprint.no_meet_while_media` | — | `True` | `anamorf/voiceprint/__init__.py` |
| `voiceprint.pitch_band_max` | 1.5 | `1.5` | `anamorf/main.py` |
| `voiceprint.pitch_group_max` | 4 | `4` | `anamorf/main.py` |
| `voiceprint.pitch_group_tol` | 0.18 | `0.18` | `anamorf/main.py` |
| `voiceprint.pitch_groups` | true | `True` | `anamorf/main.py` |
| `voiceprint.pitch_vote` | — | `True` | `anamorf/main.py` |
| `voiceprint.refit_min_s` | — | `180` | `anamorf/voiceprint/__init__.py` |
| `voiceprint.regroup_every` | — | `5` | `anamorf/main.py` |
| `voiceprint.room_window_s` | — | `180` | `anamorf/main.py` |
| `voiceprint.silence_rms` | — | `0.0022` | `anamorf/voiceprint/__init__.py` |
| `voiceprint.skel_min_conf` | — | `0.5` | `anamorf/main.py` |
| `voiceprint.speech_min` | — | `0.42` | `anamorf/main.py`, `anamorf/voiceprint/__init__.py` |
| `voiceprint.threshold` | — | `0.0` | `anamorf/voiceprint/registry.py` |
| `voiceprint.umap` | — | `True` | `anamorf/voiceprint/projector.py` |
| `voiceprint.vad_min` | — | `0.5` | `anamorf/main.py` |
| `voiceprint.window_s` | — | `1.2` | `anamorf/voiceprint/__init__.py` |

### warm_wait_max_s

| ключ | сейчас | по умолчанию | где читается |
|---|---|---|---|
| `warm_wait_max_s` | — | `300` | `anamorf/tts/manager.py` |

### word_conf

| ключ | сейчас | по умолчанию | где читается |
|---|---|---|---|
| `word_conf` | — | `True` | `anamorf/stt/engines.py` |

### worker

| ключ | сейчас | по умолчанию | где читается |
|---|---|---|---|
| `worker` | — | `'workers/dreampc_worker.py' / 'workers/train_worker.py' ⚠` | `anamorf/llm/dreampc.py`, `anamorf/llm/train_manager.py` |

---

⚠ в колонке «по умолчанию» значит, что РАЗНЫЕ модули читают один ключ с РАЗНЫМИ значениями по умолчанию. Это ловушка: поведение зависит от того, кто спросил первым. Такие места стоит свести к одному значению.
