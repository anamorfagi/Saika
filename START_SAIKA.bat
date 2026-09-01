@echo off
rem ODIN KLIK - RABOCHAYA VERSIYA (2026-08-31).
rem
rem RANSHE ETOT FAIL ZAPUSKAL build\ANAMORF-0.2.1 - STARUYU SBORKU.
rem Vladelets rabotaet ne s ney: v sborke ostayutsya staryy interfeys i
rem staraya logika, i trogat ee nelzya. Rabochaya versiya - eta papka:
rem .venv + anamorf\ + ui\, ee zapuskaet start.bat.
rem
rem POCHEMU PROSTO start.bat, A NE SVOY ZAPUSK. start.bat uzhe delaet vse:
rem chinit venv posle perenosa diska, zovet doctor --fix --fast, dotyagivaet
rem zavisimosti fich, podnimaet HandsPC i Ollama pri nadobnosti, i sam
rem perezapuskaet Saiku posle padeniya (3 popytki, mezhdu nimi doctor, a s
rem 2-y - II-Beymaks). Dublirovat eto zdes znachit razvesti dve raznye
rem logiki starta.
rem
rem OKNO SVERNUTOE, A NE SKRYTOE: klik odin, no esli chto-to slomaetsya,
rem oshibka vidna v konsoli, a ne teryaetsya nasovsem.
rem
rem STOROZH watchdog_saika.pyw ZDES NE ZOVETSYA: on umeet tolko raskladku
rem sborki (ANAMORF.exe + app\ + code_backup) i k rabochey versii ne
rem otnositsya. Ee tsikl perezapuska zhivet vnutri start.bat.
cd /d "%~dp0"
start "Saika" /min "%~dp0start.bat"
exit
