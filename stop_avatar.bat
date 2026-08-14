@echo off
:: ZAKRYT OKNO S MODELYU, KOGDA SERVER NE ZAPUSCHEN (2026-08-14).
::
:: Vladelets: "okno ne mogu zakryt esli sistema ne zapuschena". Okno na
:: stole - eto otdelnyy protsess bez ramki, bez krestika i bez stroki v
:: paneli zadach, a knopka "zakryt" zhivet v interfeyse Saiki. Server
:: upal - i vzyat okno nechem. Teper okno i samo pokazhet ramku cherez
:: 8 sekund molchaniya servera i zakroetsya cherez 90, no zhdat nikto
:: ne obyazan - etot fayl ubivaet ego srazu.
::
:: BEZ PERENOSOV STROKI. Karetka "^" v kontse stroki v .bat s CRLF uzhe
:: odin raz slomala zapusk (sm. start.bat, 2026-08-14) - povtoryat ne budem.
:: ASCII only: cmd chitaet .bat v OEM-kodirovke.
powershell -NoProfile -Command "$p = Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*desk_avatar*' }; if ($p) { $p | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue } ; Write-Host ('Zakryto okon: ' + @($p).Count) } else { Write-Host 'Okon avatara ne naydeno.' }"
