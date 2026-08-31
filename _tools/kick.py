import io,json,urllib.request
OUT=r"E:\Loading\_atlas_tmp\kick.txt"
try:
    d=json.loads(urllib.request.urlopen("http://127.0.0.1:8765/api/mic",timeout=10).read().decode())
    io.open(OUT,"w",encoding="utf-8").write(
        "системный звук поднят: %s\nошибка: %s\n" % (d.get("sys_audio"), d.get("sys_audio_err")))
except Exception as e:
    io.open(OUT,"w",encoding="utf-8").write("ошибка: %r"%e)
