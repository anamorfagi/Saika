@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"
title Saika

:: ---------- admin rights (2026-07-28) ----------
:: One launcher, no extra files: start.bat elevates ITSELF. Why: Windows
:: (UIPI) silently ignores window commands from a normal process to elevated
:: windows - Task Manager could not be minimized. Elevated Saika can command
:: everything. If UAC is declined, we continue as a normal user: everything
:: works except controlling elevated windows.
net session >nul 2>&1
if errorlevel 1 (
    echo [*] Requesting admin rights - so Saika can command ALL windows,
    echo     including Task Manager. Decline is fine: she still runs,
    echo     just without power over elevated windows.
    powershell -NoProfile -Command "try { Start-Process -FilePath '%~f0' -WorkingDirectory '%~dp0' -Verb RunAs -ErrorAction Stop; exit 0 } catch { exit 1 }"
    if not errorlevel 1 exit /b 0
    echo [i] UAC declined - continuing as normal user.
)

:: ---------- keep all model caches on this (portable) drive ----------
set "HF_HOME=%~dp0models\hf"
set "TORCH_HOME=%~dp0models\torch"
set "HF_HUB_DISABLE_SYMLINKS_WARNING=1"
set "HF_HUB_DISABLE_XET=1"
set "PIP_CACHE_DIR=%~dp0.pip_cache"

echo.
echo   ============================================
echo    Saika - local AI companion
echo   ============================================
echo.

:: ---------- find Python 3.12 ----------
set "PYCMD="
py -3.12 -c "print()" >nul 2>&1 && set "PYCMD=py -3.12"
if not defined PYCMD (
    python -c "import sys; sys.exit(0 if sys.version_info[:2]==(3,12) else 1)" >nul 2>&1 && set "PYCMD=python"
)
if not defined PYCMD (
    echo [!] Python 3.12 required. Installing via winget...
    winget install --id Python.Python.3.12 -e --accept-source-agreements --accept-package-agreements
    py -3.12 -c "print()" >nul 2>&1 && set "PYCMD=py -3.12"
)
if not defined PYCMD (
    echo [X] Python 3.12 not found. Install from python.org and run again.
    pause
    exit /b 1
)

:: ---------- venv ----------
:: перенос на другой ПК/диск: чиним абсолютные пути внутри venv
%PYCMD% setup\fix_venv.py
if not exist ".venv\Scripts\python.exe" (
    echo [*] Creating virtual environment...
    %PYCMD% -m venv .venv
)
set "VPY=.venv\Scripts\python.exe"

:: ---------- first-run setup ----------
set "NEED_SETUP=1"
if exist ".setup_state.json" (
    findstr /c:"\"setup_complete\": true" ".setup_state.json" >nul 2>&1 && set "NEED_SETUP=0"
)
if "%NEED_SETUP%"=="1" (
    echo [*] First run - setup manager. This takes a while: models are downloading.
    "%VPY%" setup\first_run.py
    if errorlevel 1 (
        echo [X] Setup did not finish. Check messages above and run start.bat again -
        echo     completed steps are skipped, it continues from the failed one.
        pause
        exit /b 1
    )
)

:: ---------- quick check + auto-fix before start ----------
:: --fast: если прошлый запуск был здоровым (младше суток), полный осмотр
:: (десятки секунд подпроцессов с torch) пропускается — старт заметно быстрее.
:: После падения сервера ниже зовётся полный doctor без --fast.
"%VPY%" setup\doctor.py --fix --fast
if errorlevel 1 (
    echo [!] Critical problems found - trying to start anyway...
)

:: ---------- start Ollama in background if present ----------
where ollama >nul 2>&1 && (
    tasklist /FI "IMAGENAME eq ollama.exe" 2>nul | find /i "ollama.exe" >nul || start "" /min ollama serve
)

:: ---------- start HandsPC (tools: web search etc.) if present ----------
:: скрытый запуск (без окна консоли): раньше start /min плодил окно,
:: которое приходилось закрывать руками. Если порт 8767 уже занят -
:: HandsPC уже работает, второй не поднимаем. Логи -> logs\handspc.log
:: HandsPC переехал ВНУТРЬ проекта (2026-07-25): %~dp0HandsPC. Старое место
:: (..\HandsPC, рядом с Саикой) поддерживаем как запасное — чтобы у тех, кто
:: ещё не перенёс папку, всё продолжало работать без правок.
set "HANDS=%~dp0HandsPC\run.bat"
if not exist "%HANDS%" set "HANDS=%~dp0..\HandsPC\run.bat"
if exist "%HANDS%" (
    netstat -ano | findstr ":8767 " | findstr "LISTENING" >nul 2>&1 || ^
    powershell -NoProfile -Command "Start-Process -WindowStyle Hidden cmd -ArgumentList '/c','\"%HANDS%\" > \"%~dp0logs\handspc.log\" 2>&1'"
)

:: ---------- top up per-feature dependencies ----------
:: 2026-07-25. first_run.py runs ONCE, so anything added to the project
:: later stays without its libraries on an already-configured machine -
:: painfully so on the second PC, where code arrives via git but pip was
:: never run. The check costs milliseconds (find_spec, no import); if
:: everything is present it exits silently. It never fails the start:
:: no internet means Saika still boots, just without that feature.
:: NOTE: ASCII only in .bat files - cmd parses them in the OEM codepage
:: and Cyrillic here splits command lines apart.
if exist ".venv\Scripts\python.exe" (
    "%VPY%" setup\ensure_features.py
)

:: ---------- run with self-restart ----------
set RESTARTS=0
:run
echo.
echo [*] Starting Saika... (Ctrl+C to exit)
:: открыть вкладку только на первом запуске; при рестарте после падения
:: уже открытая вкладка сама переподключится и обновится (по BOOT_ID),
:: новую не плодим — иначе серия крэшей засыпает браузер вкладками
if %RESTARTS%==0 (set "SAIKA_AUTO_OPEN=1") else (set "SAIKA_AUTO_OPEN=0")
"%VPY%" -m server.main
set CODE=%errorlevel%
if %CODE%==0 goto end
set /a RESTARTS+=1
if %RESTARTS% GTR 3 (
    echo [X] Saika keeps crashing. See logs\doctor_report.json and logs\saika.log
    pause
    exit /b 1
)
echo.
echo [!] Saika crashed (code %CODE%). Beymax is looking into it... (attempt %RESTARTS%/3)
"%VPY%" setup\doctor.py --fix
:: обычный осмотр не помог? зовём ИИ-Беймакса (локальная LLM читает логи)
if %RESTARTS% GEQ 2 "%VPY%" setup\ai_doctor.py --auto
goto run

:end
endlocal
