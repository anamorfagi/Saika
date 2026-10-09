# Какие пороги ФАКТИЧЕСКИ стоят в живой нарезке прямо сейчас.
# Настройки копируются в неё не при правке пульта, а при переключении
# режима прослушки — поэтому «применено» в логе и реальность расходятся.
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT))
from anamorf.config import CFG
print("в пульте:  max_segment_s=%s silence_ms=%s observe_max=%s observe_sil=%s wall=%s carry=%s"
      % (CFG.get("stt.vad.max_segment_s"), CFG.get("stt.vad.silence_ms"),
         CFG.get("stt.vad.observe_max_segment_s"), CFG.get("stt.vad.observe_silence_ms"),
         CFG.get("stt.vad.max_wall_s"), CFG.get("stt.vad.carry_ms")))
