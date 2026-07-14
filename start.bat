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

:: ---------- run with self-restart ----------
set RESTARTS=0
:run
echo.
echo [*] Starting Saika... (Ctrl+C to exit)
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
echo [!] Saika crashed (code %CODE%). Running doctor and restarting... (attempt %RESTARTS%/3)
"%VPY%" setup\doctor.py --fix
:: обычный доктор не справился? зовём ИИ-доктора (локальная LLM читает логи)
if %RESTARTS% GEQ 2 "%VPY%" setup\ai_doctor.py --auto
goto run

:end
endlocal
