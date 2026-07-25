@echo off
cd /d "%~dp0"
title HandsPC - add browser hands

if not exist ".venv\Scripts\python.exe" (
    echo [X] Run run.bat first to create the venv.
    pause & exit /b 1
)

echo [1/2] Installing browser-use (this pulls playwright etc)...
".venv\Scripts\python.exe" -m pip install browser-use
if errorlevel 1 (
    echo [!] PyPI failed, trying mirror...
    ".venv\Scripts\python.exe" -m pip install browser-use -i https://pypi.tuna.tsinghua.edu.cn/simple
)

echo [2/2] Downloading Chromium for Playwright (~150 MB)...
".venv\Scripts\python.exe" -m playwright install chromium
if errorlevel 1 (
    echo [X] Chromium download failed - check internet and rerun.
    pause & exit /b 1
)

echo.
echo Done. Restart HandsPC (close its window, run run.bat or Saika's start.bat).
echo Saika will pick up the new "browser_task" tool automatically.
pause
