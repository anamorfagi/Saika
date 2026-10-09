# -*- coding: utf-8 -*-
"""Почему не работает Win+V (журнал буфера обмена): служба, политика, кто держит буфер."""
import subprocess, sys
def run(cmd):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, shell=True, timeout=20, encoding="cp866", errors="replace")
        return (r.stdout + r.stderr).strip()
    except Exception as e:
        return "ERR " + str(e)
print("== службы cbdhsvc (Clipboard User Service) ==")
print(run('sc query type= service state= all | findstr /i "cbdhsvc"'))
print(run('powershell -NoProfile -Command "Get-Service cbdhsvc* | Format-Table -AutoSize Name,Status,StartType"'))
print("== политика AllowClipboardHistory (HKLM/HKCU) ==")
print(run(r'reg query HKLM\SOFTWARE\Policies\Microsoft\Windows\System /v AllowClipboardHistory'))
print(run(r'reg query HKCU\SOFTWARE\Policies\Microsoft\Windows\System /v AllowClipboardHistory'))
print("== пользовательская настройка ==")
print(run(r'reg query HKCU\Software\Microsoft\Clipboard'))
print("== тип запуска cbdhsvc в реестре ==")
print(run(r'reg query HKLM\SYSTEM\CurrentControlSet\Services\cbdhsvc /v Start'))
print("== кто держит буфер обмена сейчас ==")
print(run('powershell -NoProfile -Command "Add-Type -Namespace W -Name C -MemberDefinition \'[DllImport(\\"user32.dll\\")] public static extern System.IntPtr GetOpenClipboardWindow(); [DllImport(\\"user32.dll\\")] public static extern uint GetWindowThreadProcessId(System.IntPtr h, out uint pid);\'; $h=[W.C]::GetOpenClipboardWindow(); if($h -eq 0){\'никто\'} else { $pid=0; [W.C]::GetWindowThreadProcessId($h,[ref]$pid) | Out-Null; Get-Process -Id $pid | Select-Object Id,ProcessName }"'))
print("== менеджеры буфера в процессах ==")
print(run('tasklist | findstr /i "ditto clipboard powertoys clipdiary copyq 1clipboard"'))
