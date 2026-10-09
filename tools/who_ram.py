# -*- coding: utf-8 -*-
"""ЧТО ИМЕННО ЕСТ ПАМЯТЬ, ЕСЛИ ЛЛМ НЕ ЗАПУЩЕНА (06.09.2026).
Владелец в диспетчере видит три Python по 4.0 / 2.8 / 0.36 ГБ. Спрашиваем
у Windows командную строку каждого — и становится ясно, кто это."""
import subprocess
out = subprocess.run(
    ["powershell", "-NoProfile", "-Command",
     "Get-CimInstance Win32_Process -Filter \"Name='python.exe' or Name='llama-server.exe' or Name='ollama.exe'\" | "
     "Select-Object ProcessId,@{n='RSS_MB';e={[int]($_.WorkingSetSize/1MB)}},CommandLine | Format-List"],
    capture_output=True, text=True, timeout=30)
print(out.stdout[:4000])
