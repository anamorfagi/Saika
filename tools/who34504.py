import subprocess
r=subprocess.run(["powershell","-NoProfile","-Command","Get-CimInstance Win32_Process -Filter 'ProcessId=34504' | Select-Object ProcessId,ParentProcessId,WorkingSetSize,CommandLine | Format-List"],capture_output=True,text=True)
print(r.stdout[:800], r.stderr[:300])
