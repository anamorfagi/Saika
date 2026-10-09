# подхватить новую сигнатуру FasterWhisperEngine.transcribe(language=) без перезапуска
import importlib, inspect, re, types
from anamorf.stt import engines as E
src = open(r"C:\AI\Saika\anamorf\stt\engines.py", encoding="utf-8").read()
ns = {}
exec(compile(src, r"C:\AI\Saika\anamorf\stt\engines.py", "exec"), ns)   # свежий модуль в отдельном пространстве
new_cls = ns["FasterWhisperEngine"]
E.FasterWhisperEngine.transcribe = new_cls.transcribe
# новая функция ссылается на globals свежего пространства — CFG/log/pcm16_to_float там есть
print("сигнатура:", inspect.signature(E.FasterWhisperEngine.transcribe))
wh = stt._get("faster_whisper")
print("инстанс:", type(wh).__name__, "метод класса:", inspect.signature(type(wh).transcribe))
