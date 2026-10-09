import subprocess
# CommandLine может быть пустым у CIM без прав — бьём по PID, найденным через tasklist+wmic
r = subprocess.run(["powershell","-NoProfile","-Command",
  "$p = Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'python.exe' -and $_.CommandLine -and ($_.CommandLine -like '*hear_loop*' -or $_.CommandLine -like '*first30*' -or $_.CommandLine -like '*split30*' -or $_.CommandLine -like '*wo_test*') }; "
  "if(-not $p){ 'нет процессов'; } else { foreach($x in $p){ Stop-Process -Id $x.ProcessId -Force -ErrorAction SilentlyContinue; \"убит $($x.ProcessId) $($x.CommandLine)\" } }"],
  capture_output=True, text=True, timeout=30)
print("STDOUT:", r.stdout); print("STDERR:", r.stderr[:300])
r2 = subprocess.run(["taskkill","/PID","18560","/F"], capture_output=True, text=True); print("taskkill 18560:", (r2.stdout or r2.stderr).strip())
r3 = subprocess.run(["taskkill","/PID","21088","/F"], capture_output=True, text=True); print("taskkill 21088:", (r3.stdout or r3.stderr).strip())
