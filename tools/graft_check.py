co = broadcast_event.__code__
consts = [c for c in co.co_consts if isinstance(c, str)]
def walk(c, acc):
    for k in c.co_consts:
        if hasattr(k, "co_consts"): walk(k, acc)
        elif isinstance(k, str): acc.append(k)
    return acc
allc = walk(co, [])
open(r"C:\AI\Saika\data\graft_check.txt","w",encoding="utf-8").write("who in copilka: %s\nregex human: %s\nnames: %s" % (
    "who" in allc, any("Голос" in c for c in allc), [n for n in co.co_names if n in ("_re","match")]))
