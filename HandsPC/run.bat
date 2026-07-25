@echo off
cd /d "%~dp0"
title HandsPC

rem -- find python 3.x
set "PYCMD="
py -3.12 -c "print()" >nul 2>&1 && set "PYCMD=py -3.12"
if not defined PYCMD (
    python -c "print()" >nul 2>&1 && set "PYCMD=python"
)
if not defined PYCMD (
    echo [X] Python not found. Run Saika's start.bat first - it installs Python 3.12.
    pause & exit /b 1
)

rem -- venv is tiny: if it does not start (moved to another PC) just recreate
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -c "print()" >nul 2>&1 || rmdir /s /q .venv
)
if not exist ".venv\Scripts\python.exe" (
    echo [*] Creating HandsPC venv...
    %PYCMD% -m venv .venv
    ".venv\Scripts\python.exe" -m pip install --upgrade pip
)

rem -- deps: install only if missing, with mirror fallback (flaky DNS to pypi)
set "DEPS=fastapi uvicorn ddgs trafilatura requests"
".venv\Scripts\python.exe" -c "import fastapi,uvicorn,ddgs,trafilatura,requests" >nul 2>&1
if errorlevel 1 ".venv\Scripts\python.exe" -m pip install -q %DEPS%
".venv\Scripts\python.exe" -c "import fastapi,uvicorn,ddgs,trafilatura,requests" >nul 2>&1
if errorlevel 1 (
    echo [!] PyPI unreachable, trying mirror...
    ".venv\Scripts\python.exe" -m pip install -q %DEPS% -i https://pypi.tuna.tsinghua.edu.cn/simple
)
".venv\Scripts\python.exe" -c "import fastapi,uvicorn,ddgs,trafilatura,requests" >nul 2>&1
if errorlevel 1 (
    echo [X] Could not install dependencies - check internet/DNS and rerun.
    pause & exit /b 1
)

".venv\Scripts\python.exe" server.py
pause
