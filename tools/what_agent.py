# -*- coding: utf-8 -*-
"""Что за окно «Anamorph Agent» и кто его запускает."""
import subprocess, os, sys
_OUT = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "data", "agent_report.txt"), "w", encoding="utf-8", errors="replace")
def w(*a): _OUT.write(" ".join(str(x) for x in a) + "\n"); _OUT.flush()

def ps(cmd, timeout=120):
    full = ("[Console]::OutputEncoding=[Text.Encoding]::UTF8;"
            "$ErrorActionPreference='SilentlyContinue';" + cmd)
    r = subprocess.run(["powershell","-NoProfile","-Command",full],
                       capture_output=True, timeout=timeout)
    return r.stdout.decode("utf-8","replace").strip()

w("=== ВСЕ КОНСОЛИ И ИХ КОМАНДНЫЕ СТРОКИ ===")
w(ps("Get-CimInstance Win32_Process | Where-Object { $_.Name -match 'cmd|powershell|conhost|python|pythonw' } |"
     " ForEach-Object { '{0} | pid {1} | родитель {2} | {3}' -f $_.Name, $_.ProcessId, $_.ParentProcessId,"
     " ($_.CommandLine -replace '\\s+',' ') }"))

w("\n=== ОКНА С ЗАГОЛОВКАМИ ===")
w(ps("Get-Process | Where-Object { $_.MainWindowTitle } |"
     " ForEach-Object { '{0} | pid {1} | «{2}»' -f $_.ProcessName, $_.Id, $_.MainWindowTitle }"))

w("\n=== АВТОЗАПУСК: папки ===")
for d in (os.path.expandvars(r"%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"),
          r"C:\ProgramData\Microsoft\Windows\Start Menu\Programs\StartUp"):
    w("--", d)
    try:
        for f in os.listdir(d): w("   ", f)
    except Exception as e: w("    не прочиталась:", e)

w("\n=== АВТОЗАПУСК: реестр ===")
w(ps("foreach($k in 'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Run',"
     "'HKLM:\\Software\\Microsoft\\Windows\\CurrentVersion\\Run'){"
     " Get-ItemProperty $k | Select-Object * -Exclude PS* |"
     " ForEach-Object { $_.PSObject.Properties | ForEach-Object { '{0} = {1}' -f $_.Name,$_.Value } } }"))

w("\n=== ЗАДАЧИ ПЛАНИРОВЩИКА С 'anamorf/anamorph/saika' ===")
w(ps("Get-ScheduledTask | Where-Object { $_.TaskName -match 'anamor|saika' } |"
     " ForEach-Object { '{0} | {1}' -f $_.TaskName, $_.State }"))
_OUT.write("\n=== КОНЕЦ ===\n"); _OUT.close()
