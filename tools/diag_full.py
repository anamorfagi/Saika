# -*- coding: utf-8 -*-
"""ПОЛНАЯ ДИАГНОСТИКА ВЫКЛЮЧЕНИЙ.

Собираем всё, что различает три версии: питание, перегрев, видеокарта.
Пишем в UTF-8, чтобы русский из PowerShell не превращался в кашу.
"""
import subprocess, sys, os, datetime
# ПИШЕМ В ФАЙЛ, А НЕ В КОНСОЛЬ. Через канал runpy вывод уехал пустым:
# консоль запускающего процесса живёт в другой кодировке и другом буфере.
# Свой файл — единственный надёжный способ донести результат.
_OUT = open(os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "data", "diag_report.txt"),
    "w", encoding="utf-8", errors="replace")
def print(*a, **k):
    _OUT.write(" ".join(str(x) for x in a) + "\n"); _OUT.flush()

def ps(cmd, timeout=200):
    full = ("[Console]::OutputEncoding=[Text.Encoding]::UTF8;"
            "$ErrorActionPreference='SilentlyContinue';" + cmd)
    r = subprocess.run(["powershell", "-NoProfile", "-Command", full],
                       capture_output=True, timeout=timeout)
    return (r.stdout.decode("utf-8", "replace").strip(),
            r.stderr.decode("utf-8", "replace").strip())

def блок(имя, cmd, timeout=200):
    print("\n" + "=" * 66)
    print("### " + имя)
    print("=" * 66)
    try:
        o, e = ps(cmd, timeout)
    except Exception as ex:
        print("не выполнилось:", ex); return
    print(o if o else "(пусто)")
    if e:
        print("[ошибки] " + e[:300])

блок("АППАРАТНЫЕ ОШИБКИ WHEA — сбои шины PCIe, памяти, процессора",
 "Get-WinEvent -FilterHashtable @{LogName='System';"
 " ProviderName='Microsoft-Windows-WHEA-Logger'} -MaxEvents 20 |"
 " ForEach-Object { '{0} | id {1} | {2}' -f "
 "  $_.TimeCreated.ToString('MM-dd HH:mm:ss'), $_.Id,"
 "  ($_.Message -replace '\\s+',' ') }")

блок("СРЫВЫ ВИДЕОДРАЙВЕРА (TDR, события 4101/4102)",
 "Get-WinEvent -FilterHashtable @{LogName='System'; Id=4101,4102} -MaxEvents 20 |"
 " ForEach-Object { '{0} | {1} | {2}' -f "
 "  $_.TimeCreated.ToString('MM-dd HH:mm:ss'), $_.ProviderName,"
 "  ($_.Message -replace '\\s+',' ') }")

блок("ВЫКЛЮЧЕНИЯ, СИНИЕ ЭКРАНЫ, ПИТАНИЕ",
 "Get-WinEvent -FilterHashtable @{LogName='System'; Id=41,1001,6008,137,46} -MaxEvents 30 |"
 " ForEach-Object { '{0} | id {1} | {2} | {3}' -f "
 "  $_.TimeCreated.ToString('MM-dd HH:mm:ss'), $_.Id, $_.ProviderName,"
 "  ($_.Message -replace '\\s+',' ') }")

блок("КОДЫ СИНИХ ЭКРАНОВ ВНУТРИ СОБЫТИЙ 41",
 "Get-WinEvent -FilterHashtable @{LogName='System'; Id=41} -MaxEvents 12 |"
 " ForEach-Object { $x=[xml]$_.ToXml();"
 "  $bc=($x.Event.EventData.Data | Where-Object {$_.Name -eq 'BugcheckCode'}).'#text';"
 "  $pb=($x.Event.EventData.Data | Where-Object {$_.Name -eq 'PowerButtonTimestamp'}).'#text';"
 "  '{0} | код синего экрана {1} | кнопка питания {2}' -f "
 "   $_.TimeCreated.ToString('MM-dd HH:mm:ss'), $bc, $pb }")

print("\n" + "=" * 66); print("### МИНИДАМПЫ"); print("=" * 66)
try:
    d = r"C:\WINDOWS\Minidump"
    fs = sorted(os.listdir(d))[-12:]
    if not fs: print("(пусто — синих экранов не записано)")
    for f in fs:
        p = os.path.join(d, f)
        print("%s  %d КБ  %s" % (f, os.path.getsize(p)//1024,
              datetime.datetime.fromtimestamp(
                  os.path.getmtime(p)).strftime("%m-%d %H:%M")))
except Exception as e:
    print("не прочитались:", e)

print("\n" + "=" * 66); print("### ВИДЕОКАРТА: ШИНА, ПИТАНИЕ, ТЕПЛО"); print("=" * 66)
try:
    r2 = subprocess.run(["nvidia-smi", "--query-gpu=driver_version,name,"
        "pcie.link.gen.current,pcie.link.gen.max,pcie.link.width.current,"
        "pcie.link.width.max,temperature.gpu,power.draw,power.limit,"
        "clocks_throttle_reasons.active,clocks_throttle_reasons.hw_power_brake_slowdown,"
        "clocks_throttle_reasons.hw_thermal_slowdown,memory.used,memory.total",
        "--format=csv"], capture_output=True, timeout=60)
    print(r2.stdout.decode("utf-8", "replace").strip()
          or r2.stderr.decode("utf-8", "replace")[:300])
except Exception as e:
    print("nvidia-smi не ответил:", e)

print("\n" + "=" * 66); print("### ОШИБКИ XID (внутренние сбои карты)"); print("=" * 66)
блок("Xid в журнале",
 "Get-WinEvent -LogName System -MaxEvents 400 |"
 " Where-Object { $_.Message -match 'Xid|nvlddmkm|display driver' } |"
 " Select-Object -First 15 |"
 " ForEach-Object { '{0} | {1} | {2}' -f "
 "  $_.TimeCreated.ToString('MM-dd HH:mm:ss'), $_.ProviderName,"
 "  (($_.Message -replace '\\s+',' ')) }")

_OUT.write("\n=== КОНЕЦ ОТЧЁТА ===\n"); _OUT.close()
