@echo off
setlocal
cd /d "%~dp0.."
title Saika - PDF support install
chcp 65001 >nul
echo Ставлю PyMuPDF (чтение PDF-чертежей — эвакуационные планы и т.п.)...
".venv\Scripts\python.exe" -m pip install --upgrade PyMuPDF
echo.
echo Готово. Если ошибок не было — перезапусти Сайку (start.bat) и просто
echo перетащи PDF-файл в окно чата.
echo.
pause
endlocal
