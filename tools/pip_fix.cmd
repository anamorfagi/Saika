@echo off
:: Pochinka paketov mezhdu ostanovkoy i zapuskom Saiki (2026-09-06).
:: %1 - PID staroy Saiki, %2 - python venv. Stroki data\pip_fix.txt -> pip install.
set PID=%1
set VPY=%2
cd /d "%~dp0\.."
:wait
tasklist /FI "PID eq %PID%" 2>nul | find "%PID%" >nul
if not errorlevel 1 (timeout /t 1 /nobreak >nul & goto wait)
timeout /t 2 /nobreak >nul
for /f "usebackq delims=" %%p in ("data\pip_fix.txt") do "%VPY%" -m pip install --no-deps --force-reinstall %%p >> logs\pip_fix.log 2>&1
del "data\pip_fix.txt"
del "data\pip_fix.lock"
