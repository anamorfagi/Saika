@echo off
:: Saika - OmniVoice (voice cloning, Apache-2.0) installer.
:: ASCII only: cmd parses .bat in the OEM codepage and Cyrillic here breaks
:: command lines apart. All Russian output lives in the Python script.
setlocal
cd /d "%~dp0.."
title Saika - OmniVoice install
chcp 65001 >nul
set "PIP_CACHE_DIR=%~dp0..\.pip_cache"
if not exist ".venv\Scripts\python.exe" (
  echo [X] .venv not found. Run start.bat once first.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" setup\install_omnivoice.py %*
pause
endlocal
