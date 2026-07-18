@echo off
setlocal
cd /d "%~dp0.."
title Saika - Train install
chcp 65001 >nul
set "HF_HOME=%cd%\models\hf"
set "HF_HUB_DISABLE_XET=1"
".venv\Scripts\python.exe" setup\install_train.py %*
echo.
pause
endlocal
