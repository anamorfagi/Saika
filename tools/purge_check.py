import io, json, sys
from urllib import request
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
O=[]
def say(*a):
    s=" ".join(str(x) for x in a); print(s); O.append(s)
    io.open(ROOT/"data"/"purge_check.txt","w",encoding="utf-8").write("\n".join(O))
for path in ("/api/voiceprint/purge_mixed?dry=1", "/api/voiceprint/purge_ghosts?dry=1"):
    try:
        r = request.Request("http://127.0.0.1:8765"+path, method="POST")
        with request.urlopen(r, timeout=25) as f:
            d = json.loads(f.read().decode("utf-8"))
        say(path, "->", json.dumps(d, ensure_ascii=False)[:700])
    except Exception as e:
        say(path, "-> ОШИБКА", repr(e)[:200])
