import subprocess, sys
r = subprocess.run([sys.executable, "-m", "pip", "install", "-q", "shazamio"], capture_output=True, text=True, timeout=900)
print("rc", r.returncode, r.stderr[-800:])
import importlib; importlib.invalidate_caches()
import shazamio; print("shazamio ok", getattr(shazamio, "__version__", "?"))
import pydub; print("pydub ok")
