@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

rem Версию не пишем руками: она живёт в VERSION, и вторая копия числа
rem разошлась бы с первой на следующем же выпуске и врала бы молча.
set "VER=0.0.0"
if exist VERSION set /p VER=<VERSION
set "OUT=build\ANAMORF-%VER%"

rem Интерпретатор: сначала свой из .venv, потом системный. Системный может
rem оказаться другой версии или вовсе без зависимостей — тогда сборка падает
rem на импорте, а выглядит это как «поломался билд».
set "PY=%~dp0.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"

echo.
echo === 1. Гашу билд целиком =========================================
rem Окно, сервер и движок моделей — три разных процесса, и закрытие окна
rem гасит только первый. Пока живы остальные, Windows держит их DLL, и
rem пересборка упирается в занятый файл на середине копирования.
rem
rem Путь передаём ПЕРЕМЕННОЙ ОКРУЖЕНИЯ, а не подстановкой в текст команды.
rem Было: -like %%~dp0build\* — cmd подставлял путь как есть, без кавычек,
rem и PowerShell видел «-like C:\AI\Saika\build\*», то есть оператор без
rem значения. Отсюда «You must provide a value expression following the
rem '-like' operator» при каждом запуске: шаг падал, ничего не гасил, и
rem сборка шла поверх живого билда. Через $env:... путь приезжает одной
rem строкой — ни пробелы, ни обратные слэши, ни кавычки внутри него
rem ничего не ломают.
set "KILLDIR=%~dp0build\*"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='SilentlyContinue'; $p=@(Get-Process | Where-Object { $_.Path -like $env:KILLDIR }); if($p.Count){ $p | Stop-Process -Force; Write-Host ('    погашено процессов: ' + $p.Count) } else { Write-Host '    нечего гасить, билд не запущен' }"
timeout /t 2 /nobreak >nul

echo.
echo === 2. Пересобираю билд ==========================================
echo     Идёт несколько минут: один llama.cpp это 1.1 ГБ.
"%PY%" tools\build_client.py --profile base --apply
if errorlevel 1 goto fail

echo.
echo === 3. Проверяю лаунчер ==========================================
rem Лаунчер — окно и присмотр за сервером — собирается ОТДЕЛЬНО, шаг выше
rem его не строит: build_client только КОПИРУЕТ готовый exe из
rem build\_launcher_build\. Поэтому сравнивать надо с ним, а не с копией в
rem билде: копия обновляется каждой сборкой и всегда выглядит свежей, даже
rem когда внутри неё позавчерашний код.
rem
rem Молча пересобирать не будем: pyinstaller идёт свои минуты и стоит не на
rem каждой машине. Наше дело — заметить и сказать.
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='SilentlyContinue'; $exe=Get-Item 'build\_launcher_build\ANAMORF.exe'; $src=@(Get-ChildItem 'launcher\main.py','launcher\ANAMORF.spec','launcher\ANAMORF.ico' | Sort-Object LastWriteTime -Descending); if(-not $exe){ Write-Host '    лаунчер ещё ни разу не собран' } elseif($src.Count -and $src[0].LastWriteTime -gt $exe.LastWriteTime){ Write-Host ('    ВНИМАНИЕ: в билде лаунчер СТАРЕЕ исходников (' + $src[0].Name + ').'); Write-Host '    Пересобрать:  pyinstaller launcher\ANAMORF.spec --distpath build --workpath build\_pyi'; Write-Host '    и запустить update.cmd ещё раз.' } else { Write-Host '    лаунчер свежий' }"

echo.
echo === Готово =======================================================
echo     Запуск: %OUT%\ANAMORF.exe
echo.
pause
exit /b 0

:fail
echo.
echo === НЕ СОБРАЛОСЬ ================================================
echo     Смотри сообщение выше.
echo.
pause
exit /b 1
