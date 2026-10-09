import subprocess, sys
r = subprocess.run([sys.executable, "-m", "pip", "install", "-q", "yt-dlp"], capture_output=True, text=True, timeout=600)
print("rc", r.returncode, r.stdout[-500:], r.stderr[-800:])
import importlib; importlib.invalidate_caches()
import yt_dlp; print("yt_dlp", yt_dlp.version.__version__)
