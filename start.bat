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
:: perenos na drugoy PK/disk: chinim absolyutnye puti vnutri venv
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
:: --fast: esli proshlyy zapusk byl zdorovym (mladshe sutok), polnyy osmotr
:: (desyatki sekund podprotsessov s torch) propuskaetsya - start zametno bystree.
:: Posle padeniya servera nizhe zovetsya polnyy doctor bez --fast.
"%VPY%" setup\doctor.py --fix --fast
if errorlevel 1 (
    echo [!] Critical problems found - trying to start anyway...
)

:: ---------- start Ollama in background if present ----------
:: MY ZAPUSTILI - MY I ZAKROEM (2026-08-14). Konsol Ollama ([GIN] GET /api/ps)
:: ostavalas viset posle vyhoda Saiki i mozolila glaza. No esli Ollama uzhe
:: rabotala DO nas - eto ne nasha programma: mozhet ee derzhit chto-to esche.
:: Poetomu stavim metku tolko kogda zapuskaem sami, i po metke gasim v konce.
set "OLLAMA_OURS="
:: NUZHNA LI ONA VOOBSCHE (2026-08-14, vopros vladeltsa). Ollama - odin iz
:: podderzhannyh dvizhkov, no esli mozgi rabotayut na llama.cpp ili v oblake,
:: ona prosto zanimaet pamyat i pokazyvaet konsol s logom [GIN]. Reshaem po
:: konfigu: nuzhna, esli vybrana dvizhkom ILI est zapasnye modeli s ee imenami.
:: Vyklyuchit nasovsem: "ollama": {"autostart": false} v config.json.
"%VPY%" -c "import json,sys;c=json.load(open('config.json',encoding='utf-8'));o=c.get('ollama',{});sys.exit(0 if o.get('autostart',True) else 1)" >nul 2>&1
if errorlevel 1 goto skip_ollama
where ollama >nul 2>&1 && (
    tasklist /FI "IMAGENAME eq ollama.exe" 2>nul | find /i "ollama.exe" >nul || (
        start "" /min ollama serve
        set "OLLAMA_OURS=1"
    )
)
:skip_ollama

:: ---------- start HandsPC (tools: web search etc.) if present ----------
:: skrytyy zapusk (bez okna konsoli): ranshe start /min plodil okno,
:: kotoroe prihodilos zakryvat rukami. Esli port 8767 uzhe zanyat -
:: HandsPC uzhe rabotaet, vtoroy ne podnimaem. Logi -> logs\handspc.log
:: HandsPC pereehal VNUTR proekta (2026-07-25): %~dp0HandsPC. Staroe mesto
:: (..\HandsPC, ryadom s Saikoy) podderzhivaem kak zapasnoe - chtoby u teh, kto
:: esche ne perenes papku, vse prodolzhalo rabotat bez pravok.
set "HANDS=%~dp0HandsPC\run.bat"
if not exist "%HANDS%" set "HANDS=%~dp0..\HandsPC\run.bat"
if exist "%HANDS%" (
:: KARETKA V KONTSE STROKI + CRLF = SLOMANNAYA KOMANDA (2026-08-14).
:: V logе vladeltsa: "" ne yavlyaetsya vnutrenney ili vneshney komandoy.
:: Prichina: "^" v kontse stroki ekraniroval NE perevod stroki, a CR,
:: i cmd poluchal "|| <CR>" - operator bez pravoy chasti. HandsPC pri
:: etom voobsche ne zapuskalsya. Bez perenosa - bez problem.
    netstat -ano | findstr ":8767 " | findstr "LISTENING" >nul 2>&1
    if errorlevel 1 powershell -NoProfile -Command "Start-Process -WindowStyle Hidden cmd -ArgumentList '/c','\"%HANDS%\" > \"%~dp0logs\handspc.log\" 2>&1'"
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
:: otkryt vkladku tolko na pervom zapuske; pri restarte posle padeniya
:: uzhe otkrytaya vkladka sama perepodklyuchitsya i obnovitsya (po BOOT_ID),
:: novuyu ne plodim - inache seriya kreshey zasypaet brauzer vkladkami
if %RESTARTS%==0 (set "SAIKA_AUTO_OPEN=1") else (set "SAIKA_AUTO_OPEN=0")
"%VPY%" -m anamorf.main
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
:: obychnyy osmotr ne pomog? zovem II-Beymaksa (lokalnaya LLM chitaet logi)
if %RESTARTS% GEQ 2 "%VPY%" setup\ai_doctor.py --auto
goto run

:end
:: gasim to, chto zapustili sami: Ollama i okno s modelyu na stole
if defined OLLAMA_OURS taskkill /F /IM ollama.exe >nul 2>&1
"%VPY%" -c "import sys; sys.path.insert(0,'.'); from anamorf import desk_avatar as d; d.kill_all()" >nul 2>&1
endlocal
