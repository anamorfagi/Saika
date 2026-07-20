@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"
title Saika

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
"%VPY%" setup\doctor.py --fix
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
if exist "%~dp0..\HandsPC\run.bat" (
    netstat -ano | findstr ":8767 " | findstr "LISTENING" >nul 2>&1 || ^
    powershell -NoProfile -Command "Start-Process -WindowStyle Hidden cmd -ArgumentList '/c','\"%~dp0..\HandsPC\run.bat\" > \"%~dp0logs\handspc.log\" 2>&1'"
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
