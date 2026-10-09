import subprocess, sys, os
d = r"C:\AI\Saika\tools\proclb"
r = subprocess.run(["dotnet", "build", "-c", "Release", "-o", os.path.join(d, "bin")], cwd=d, capture_output=True, text=True, timeout=600)
print("rc", r.returncode); print(r.stdout[-3000:]); print(r.stderr[-1500:])
