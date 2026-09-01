# -*- coding: utf-8 -*-
"""Почему компьютер выключился: спрашиваем журнал Windows.

Коды, которые тут важны:
  41  Kernel-Power — питание пропало или система встала без «мягкого»
      выключения (обрыв питания, срабатывание защиты, зависание намертво)
  6008 EventLog     — прошлое выключение было неожиданным
  1001 BugCheck     — синий экран, с кодом остановки
  6013 EventLog     — сколько система проработала до этого
"""
import subprocess, sys
ps = (
 "$ErrorActionPreference='SilentlyContinue';"
 "Get-WinEvent -FilterHashtable @{LogName='System';"
 "  Id=41,1001,6008,6013,109,506,507} -MaxEvents 40 |"
 " Sort-Object TimeCreated -Descending |"
 " ForEach-Object { '{0} | id {1} | {2} | {3}' -f "
 "   $_.TimeCreated.ToString('yyyy-MM-dd HH:mm:ss'), $_.Id, $_.ProviderName,"
 "   ($_.Message -replace '\\s+',' ').Substring(0,[Math]::Min(220,($_.Message -replace '\\s+',' ').Length)) }"
)
r = subprocess.run(["powershell","-NoProfile","-Command",ps],
                   capture_output=True, text=True, timeout=180)
print(r.stdout or "(пусто)")
if r.stderr.strip():
    print("--- ошибки ---"); print(r.stderr[:800])
# заодно температура и питание, если драйвер отдаёт
ps2 = ("$ErrorActionPreference='SilentlyContinue';"
       "Get-CimInstance -Namespace root/wmi -ClassName MSAcpi_ThermalZoneTemperature |"
       " ForEach-Object { 'зона {0}: {1:N1} C' -f $_.InstanceName, "
       "(($_.CurrentTemperature/10)-273.15) }")
r2 = subprocess.run(["powershell","-NoProfile","-Command",ps2],
                    capture_output=True, text=True, timeout=60)
print("--- температура ---"); print(r2.stdout or "(датчик не отдаёт)")
