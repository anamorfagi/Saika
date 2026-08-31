# -*- coding: utf-8 -*-
"""Оставить ОДНО приложение: то, что реально держит порт 8765."""
import io, os, subprocess, ctypes, time
from ctypes import wintypes
OUT = r"E:\Loading\_atlas_tmp\dedup.txt"
def w(m):
    with io.open(OUT,"a",encoding="utf-8") as f: f.write(str(m)+"\n")
io.open(OUT,"w",encoding="utf-8").write("")

# кто слушает 8765
owner = None
try:
    r = subprocess.run(["netstat","-ano","-p","TCP"], capture_output=True, text=True,
                       timeout=25, creationflags=0x08000000)
    for ln in r.stdout.splitlines():
        p = ln.split()
        if len(p) >= 5 and p[0] == "TCP" and p[1].endswith(":8765") and p[3] == "LISTENING":
            owner = int(p[4]); break
except Exception as e:
    w("netstat: %r" % e)
w("порт 8765 держит PID %s" % owner)

# дерево процессов: чей это родитель
tree = set()
if owner:
    tree.add(owner)
    try:
        import psutil
        p = psutil.Process(owner)
        for a in p.parents(): tree.add(a.pid)
        for c in p.children(recursive=True): tree.add(c.pid)
        w("дерево владельца: %s" % sorted(tree))
    except Exception as e:
        w("psutil нет (%r) — считаю по WMIC" % e)
        try:
            r = subprocess.run(["wmic","process","get","ProcessId,ParentProcessId"],
                               capture_output=True, text=True, timeout=25,
                               creationflags=0x08000000)
            pp = {}
            for ln in r.stdout.splitlines()[1:]:
                f = ln.split()
                if len(f) == 2:
                    pp[int(f[1])] = int(f[0])
            cur = owner
            for _ in range(6):
                par = pp.get(cur)
                if not par: break
                tree.add(par); cur = par
            for k, v in pp.items():
                if v in tree: tree.add(k)
            w("дерево по WMIC: %s" % sorted(tree))
        except Exception as e2:
            w("wmic тоже нет: %r" % e2)

u32 = ctypes.windll.user32
wins = []
def cb(h, _):
    n = u32.GetWindowTextLengthW(h)
    if n:
        b = ctypes.create_unicode_buffer(n+1)
        u32.GetWindowTextW(h, b, n+1)
        if b.value.strip().upper() == "ANAMORF" and u32.IsWindowVisible(h):
            pid = wintypes.DWORD()
            u32.GetWindowThreadProcessId(h, ctypes.byref(pid))
            wins.append((h, int(pid.value)))
    return True
P = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
u32.EnumWindows(P(cb), 0)
w("окон ANAMORF: %d -> %s" % (len(wins), [(h, p) for h, p in wins]))

if len(wins) > 1 and tree:
    keep = [x for x in wins if x[1] in tree]
    drop = [x for x in wins if x[1] not in tree]
    w("оставляю: %s | закрываю: %s" % (keep, drop))
    for h, pid in drop:
        u32.PostMessageW(h, 0x0010, 0, 0)     # WM_CLOSE — мягко, как крестиком
        w("послал закрытие окну %s (PID %s)" % (h, pid))
    time.sleep(3)
    left = []
    def cb2(h, _):
        n = u32.GetWindowTextLengthW(h)
        if n:
            b = ctypes.create_unicode_buffer(n+1)
            u32.GetWindowTextW(h, b, n+1)
            if b.value.strip().upper() == "ANAMORF" and u32.IsWindowVisible(h):
                left.append(h)
        return True
    u32.EnumWindows(P(cb2), 0)
    w("осталось окон: %d" % len(left))
else:
    w("закрывать нечего или владелец не определён")
