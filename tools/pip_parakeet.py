import subprocess, sys
r = subprocess.run([sys.executable, "-m", "pip", "install", "-q", "--no-deps", "onnx-asr"], capture_output=True, text=True, timeout=900)
print("rc", r.returncode, r.stderr[-600:])
import importlib; importlib.invalidate_caches()
import onnx_asr; print("onnx_asr", getattr(onnx_asr, "__version__", "?"))
import onnxruntime as ort; print("ort", ort.__version__, ort.get_available_providers())
