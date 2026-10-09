# -*- coding: utf-8 -*-
import subprocess
def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True, shell=True, timeout=30, encoding="cp866", errors="replace")
    return (r.stdout + r.stderr).strip()
print("TextInputHost до:", run('tasklist | findstr /i TextInputHost'))
print(run('taskkill /im TextInputHost.exe /f'))
print("перезапуск службы:", run('powershell -NoProfile -Command "Restart-Service cbdhsvc* -Force; Get-Service cbdhsvc* | Format-Table -AutoSize Name,Status"'))
print("elevated Saika?:", run('powershell -NoProfile -Command "([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)"'))
