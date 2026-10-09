@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
title Anamorf Genom — сборка exe
cd /d "%~dp0"

rem ============================================================================
rem  СБОРКА ГОТОВОГО ПРОЕКТА В ОДИН EXE
rem
rem  Что делает: собирает свежую студию из конвейера, складывает всё нужное в
rem  папку AnamorfGenom\ и компилирует лаунчер в AnamorfGenom\AnamorfGenom.exe.
rem  Запускать, когда проект готов. Ничего в исходниках не меняет.
rem
rem  Что нужно на машине: Node.js (проверяется ниже). Интернет — только на
rem  первую компиляцию, чтобы скачать упаковщик и ядро node под Windows.
rem  Нет интернета — соберётся папка без exe, она всё равно рабочая (см. конец).
rem ============================================================================

set "OUT=%~dp0AnamorfGenom"
set "APP=%OUT%\app"
set "PIPE=%OUT%\pipeline"
set "FAIL=0"

echo.
echo ============================================================
echo   ANAMORF GENOM · сборка
echo   Отсюда:  %~dp0
echo   Сюда:    %OUT%
echo ============================================================
echo.

rem --- [1] Node на месте? Без него ни собрать студию, ни скомпилировать exe ---
where node >nul 2>&1
if errorlevel 1 (
    echo [X] Node.js не найден в PATH.
    echo     Поставь с nodejs.org ^(LTS^) и запусти этот файл снова.
    goto :end
)
for /f "delims=" %%v in ('node -v') do set "NODEV=%%v"
echo [ok] Node.js !NODEV!

rem --- [2] Свежая студия из конвейера. Если конвейер не отрабатывает, берём ---
rem ---     готовый genome-studio.html — он всегда лежит рядом.              ---
if exist "%~dp0pipeline\build.sh" (
    where bash >nul 2>&1
    if errorlevel 1 (
        echo [i]  bash не найден — конвейер пропускаю, беру готовый genome-studio.html
    ) else (
        echo [*]  Пересобираю студию из конвейера...
        bash "%~dp0pipeline\build.sh" >"%~dp0build_exe.log" 2>&1
        if errorlevel 1 (
            echo [!]  Конвейер не отработал — подробности в build_exe.log.
            echo      Беру готовый genome-studio.html.
        ) else (
            echo [ok] Студия пересобрана
        )
    )
)
if not exist "%~dp0genome-studio.html" (
    echo [X] Нет genome-studio.html — собирать нечего.
    goto :end
)

rem --- [3] Чистая папка сборки: старое не должно примешиваться ---------------
if exist "%OUT%" (
    echo [*]  Чищу прошлую сборку...
    rmdir /s /q "%OUT%" 2>nul
)
mkdir "%APP%" 2>nul
mkdir "%PIPE%" 2>nul

rem --- [4] Страница и её спутники. ver.js обязателен: по нему страница ------
rem ---     сама перезагружается, когда файл обновили.                   ------
copy /y "%~dp0genome-studio.html" "%APP%\" >nul && echo [ok] app\genome-studio.html
if exist "%~dp0research-live.js" copy /y "%~dp0research-live.js" "%APP%\" >nul && echo [ok] app\research-live.js
if exist "%~dp0ver.js" copy /y "%~dp0ver.js" "%APP%\" >nul && echo [ok] app\ver.js

rem --- [5] Конвейер: то, что нужно ЖИВОЙ программе, а не разработке ---------
rem     Скрипты update_*.js — инструменты сборки, в дистрибутив не идут.
for %%f in (
    llm.py probe.py providers.json
    research.py research_server.py model_checks.py start_research.ps1
    investigate.py aggregate.py genes.json correlations.json sigs.json
    desc_lex.json descriptions.json tags2genes.json age_lex.py
    persona.py profile.py prosody.py observer.py scout.py ingest.py
    tagger.py corpus.py export_char.py voice_live.py
    launcher.js build_char.js export_all.js share_index.js
    GENOME_GUIDE.md RESEARCH.md investigator.md profiler.md README.md
) do (
    if exist "%~dp0pipeline\%%f" copy /y "%~dp0pipeline\%%f" "%PIPE%\" >nul
)
for /f %%c in ('dir /b "%PIPE%" 2^>nul ^| find /c /v ""') do echo [ok] pipeline: %%c файлов

rem --- [6] Данные: персонажи, аватары, исследования -------------------------
if exist "%~dp0share" xcopy /e /i /y /q "%~dp0share" "%OUT%\share" >nul && echo [ok] share\
if exist "%~dp0ava"   xcopy /e /i /y /q "%~dp0ava"   "%OUT%\ava"   >nul && echo [ok] ava\
if exist "%~dp0chars" xcopy /e /i /y /q "%~dp0chars" "%OUT%\chars" >nul && echo [ok] chars\
if exist "%~dp0ИНСТРУКЦИЯ.md" copy /y "%~dp0ИНСТРУКЦИЯ.md" "%OUT%\" >nul

rem --- [7] Обновляем список персонажей: единственный источник правды — share\ -
if exist "%PIPE%\export_all.js" (
    pushd "%~dp0"
    node "%PIPE%\export_all.js" "%OUT%" >nul 2>&1 && echo [ok] share\_list.js обновлён
    popd
)

rem --- [8] Компиляция. pkg собирает node + лаунчер в один .exe --------------
rem     @yao-pkg/pkg — живой форк vercel/pkg, умеет node22.
if not exist "%PIPE%\launcher.js" (
    echo [X] Нет pipeline\launcher.js — компилировать нечего.
    goto :end
)
mkdir "%OUT%\_build" 2>nul
copy /y "%PIPE%\launcher.js" "%OUT%\_build\launcher.js" >nul
>"%OUT%\_build\package.json" echo {"name":"anamorf-genom","version":"1.0.0","bin":"launcher.js","pkg":{"targets":["node22-win-x64"],"outputPath":"."}}

echo.
echo [*]  Компилирую exe. Первый раз качается ядро node (~40 МБ), это минуты.
pushd "%OUT%\_build"
call npx --yes @yao-pkg/pkg . --target node22-win-x64 --output "%OUT%\AnamorfGenom.exe" 2>&1
popd
if exist "%OUT%\AnamorfGenom.exe" (
    for %%s in ("%OUT%\AnamorfGenom.exe") do set "EXESIZE=%%~zs"
    set /a EXEMB=!EXESIZE!/1048576
    echo [ok] AnamorfGenom.exe собран, !EXEMB! МБ
    rmdir /s /q "%OUT%\_build" 2>nul
) else (
    set "FAIL=1"
    echo [!]  Скомпилировать не вышло ^(нет интернета или упаковщик отказал^).
    echo      Папка собрана и работает без exe — см. ниже.
    >"%OUT%\ЗАПУСК.bat" echo @echo off
    >>"%OUT%\ЗАПУСК.bat" echo chcp 65001 ^>nul
    >>"%OUT%\ЗАПУСК.bat" echo cd /d "%%~dp0"
    >>"%OUT%\ЗАПУСК.bat" echo node pipeline\launcher.js
    >>"%OUT%\ЗАПУСК.bat" echo pause
    echo [ok] Создан ЗАПУСК.bat — поднимает то же самое через node
)

rem --- [9] Что получилось: настоящие числа, а не «готово» -------------------
echo.
echo ============================================================
for /f %%c in ('dir /b /s "%OUT%" 2^>nul ^| find /c /v ""') do echo   Файлов в сборке: %%c
if exist "%OUT%\AnamorfGenom.exe" (
    echo   Запуск: AnamorfGenom\AnamorfGenom.exe
) else (
    echo   Запуск: AnamorfGenom\ЗАПУСК.bat
)
echo   Студия откроется на http://localhost:8765/genome-studio.html
echo ============================================================
echo.
if "%FAIL%"=="0" (
    choice /c YN /n /m "Запустить сейчас? [Y/N] "
    if not errorlevel 2 (
        if exist "%OUT%\AnamorfGenom.exe" ( start "" "%OUT%\AnamorfGenom.exe" ) else ( start "" "%OUT%\ЗАПУСК.bat" )
    )
)

:end
echo.
pause
