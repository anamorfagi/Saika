import subprocess
r=subprocess.run([r"C:\AI\Saika\tools\ffmpeg\bin\ffprobe.exe","-v","error","-show_entries","stream=index,codec_type,codec_name,channels,sample_rate:stream_tags=language,title","-of","compact",r"C:\AI\Saika\slux_test\snailkik_dnk\ДЯДЯ ОТЦА МАТЕРИ СЫНА _ СМОТРИМ ДНК.mp4"],capture_output=True,text=True,encoding="utf-8",errors="replace")
print(r.stdout, r.stderr[:300])
