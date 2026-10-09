import shutil, subprocess, sys
print("yt-dlp:", shutil.which("yt-dlp"), shutil.which("yt-dlp.exe"))
try:
    import yt_dlp; print("yt_dlp module", yt_dlp.version.__version__)
except Exception as e: print("no module", e)
import starlette; print("starlette", starlette.__version__)
