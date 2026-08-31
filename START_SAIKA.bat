@echo off
rem Odin klik. Dalshe storozh derzhit Saiku zhivoi sam.
cd /d "%~dp0build\ANAMORF-0.2.1"
start "" "ANAMORF.exe"
start "" "runtime\pythonw.exe" "watchdog_saika.pyw"
exit
