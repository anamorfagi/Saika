import urllib.request, re
b = urllib.request.urlopen("http://127.0.0.1:8765/app", timeout=10).read().decode("utf-8","replace")
print(len(b), "served;", "jserr hook:", "jserr" in b, "TRKV:" , "TRKV" in b)
import subprocess, json, sys
# проверить синтаксис тем же node? нет node на винде? попробуем
open(r"C:\AI\Saika\data\app_served.html","w",encoding="utf-8").write(b)
