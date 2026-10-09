import json, urllib.request, subprocess
r = urllib.request.Request("http://127.0.0.1:8765/api/media/cmd", data=json.dumps({"op":"pause"}).encode(), headers={"Content-Type":"application/json"})
print(json.load(urllib.request.urlopen(r, timeout=10)))
out = subprocess.run(["tasklist","/FI","IMAGENAME eq mpc-hc64.exe"],capture_output=True,text=True).stdout
print("mpc:", "mpc-hc64" in out)
if "mpc-hc64" in out:
    subprocess.run(["taskkill","/IM","mpc-hc64.exe","/F"],capture_output=True)
    print("mpc закрыт")
