@echo off
chcp 65001 >nul
title FIX VENV
rem Починка основного .venv после оборванной установки (2026-08-15).
rem В site-packages остался НУЛЕВОЙ файл scipy-1.18.0-*.whl и полуобновлённые
rem scipy/transformers: отсюда "Module scipy has no attribute _lib" (слух,
rem уши, шумодав) и "cannot import GenerationMixin" (голос qwen3).
rem Ставим те же версии заново, целиком, без зависимостей — ничего не обновляем.
cd /d %~dp0
del /q ".venv\Lib\site-packages\scipy-1.18.0-cp312-cp312-win_amd64.whl" 2>nul
.venv\Scripts\python.exe -m pip install --force-reinstall --no-deps scipy==1.18.0 transformers==4.57.3
echo.
echo Готово. Запускай start.bat — qwen3, слух и уши должны ожить.
pause
