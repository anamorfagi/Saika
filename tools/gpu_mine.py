import json, urllib.request
d = json.load(urllib.request.urlopen("http://127.0.0.1:8765/api/gpu/mine", timeout=60))
G=lambda b: round(b/2**30,2)
print("before: alloc", G(d["before"]["allocated"]), "reserved", G(d["before"]["reserved"]), "max_alloc", G(d["before"]["max_allocated"]))
print("device used", G(d["device"]["used"]), "free", G(d["device"]["free"]))
print("modules total MB", d["modules_mb"], "loose MB", d["loose_tensors_mb"])
for r in d["modules"]: print("  ", r["mb"], r["module"])
