@echo off
:: Saika - vision dependencies installer.
:: ASCII only on purpose: cmd.exe parses .bat in the OEM codepage, so
:: Cyrillic and em-dashes here break command lines apart (seen 2026-07-25:
:: "'e" -m pip install ...' is not recognized"). All human-readable Russian
:: output lives in setup\ensure_features.py, which is plain UTF-8 Python.
setlocal
cd /d "%~dp0.."
title Saika - vision install
chcp 65001 >nul
set "PIP_CACHE_DIR=%~dp0..\.pip_cache"

if not exist ".venv\Scripts\python.exe" (
  echo [X] .venv not found. Run start.bat once first.
  pause
  exit /b 1
)

".venv\Scripts\python.exe" setup\ensure_features.py vision --force

echo.
echo Restart Saika (start.bat), press F5 in the browser, then enable the eye
echo button in the header. Test it: say "posmotri na ekran".
echo.
pause
endlocal
