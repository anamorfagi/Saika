@echo off
setlocal
cd /d "%~dp0"
title Saika - finish day

:: "Финал дня" одной кнопкой: добавить всё, закоммитить, запушить.
:: Сообщение коммита можно передать аргументом:
::   finish_day.bat "что сделали сегодня"
:: без аргумента подставится дата.

set "MSG=%~1"
if "%MSG%"=="" set "MSG=work session %date% %time%"

echo [*] git add -A
git add -A

echo [*] git commit
git commit -m "%MSG%"
if errorlevel 1 (
    echo [i] Нечего коммитить или коммит не прошёл - смотри выше.
)

echo [*] git push
git push
if errorlevel 1 (
    echo.
    echo [!] Push не прошёл. Частая причина - удалённая ветка ушла вперёд.
    echo     Попробуй:  git pull --no-rebase   потом снова finish_day.bat
    pause
    exit /b 1
)

echo.
echo [OK] День сохранён в git.
timeout /t 3 >nul
