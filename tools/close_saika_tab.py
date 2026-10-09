import json, urllib.request
try:
    tabs = json.load(urllib.request.urlopen("http://127.0.0.1:9222/json", timeout=5))
except Exception as e:
    print("cdp нет:", e); raise SystemExit
for t in tabs:
    if "127.0.0.1:8765/app" in t.get("url",""):
        try:
            urllib.request.urlopen("http://127.0.0.1:9222/json/close/" + t["id"], timeout=5).read()
            print("закрыл вкладку Сайки-хрома:", t["url"])
        except Exception as e: print("не закрыл:", e)
print("осталось:", [t.get("url","")[:60] for t in json.load(urllib.request.urlopen("http://127.0.0.1:9222/json", timeout=5))])
