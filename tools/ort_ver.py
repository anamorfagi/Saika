import subprocess, sys, json
r=subprocess.run([sys.executable,"-m","pip","list","--format=json"],capture_output=True,text=True)
for p in json.loads(r.stdout):
    if "onnx" in p["name"].lower(): print(p)
