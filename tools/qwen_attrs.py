import inspect, qwen_tts
from qwen_tts import Qwen3TTSModel
src = inspect.getsource(Qwen3TTSModel.__init__)
print(inspect.getsourcefile(Qwen3TTSModel))
print(src[:2500])
